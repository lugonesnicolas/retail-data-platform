"""Source-agnostic ingestion: extract -> normalize/validate -> quality gate -> load -> metadata."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from decimal import InvalidOperation

from pydantic import ValidationError

from retail_data_platform.config import Settings
from retail_data_platform.database import WarehouseRepository
from retail_data_platform.ingestion.base import SourceAdapter, SourceRecord
from retail_data_platform.ingestion.http import RetryingHttpClient
from retail_data_platform.models import ProductObservation, RejectedRecord
from retail_data_platform.observability import bind_context, get_logger, timed_operation
from retail_data_platform.quality import QualityResult, ingestion_checks, load_metric

log = get_logger(__name__)


class IngestionFailedError(RuntimeError):
    """A source run ended in ``failed`` state (details are persisted in ops.source_runs)."""


@dataclass
class IngestionResult:
    source_run_id: uuid.UUID
    source: str
    status: str = "running"
    rows_extracted: int = 0
    rows_valid: int = 0
    rows_loaded: int = 0
    rows_duplicate: int = 0
    rows_rejected: int = 0
    duration_seconds: float = 0.0
    error_type: str | None = None
    error_summary: str | None = None
    quality: list[QualityResult] = field(default_factory=list)


def _error_details(exc: Exception) -> list[dict[str, object]]:
    if isinstance(exc, ValidationError):
        return [
            {
                "loc": ".".join(str(part) for part in err["loc"]),
                "msg": err["msg"],
                "type": err["type"],
            }
            for err in exc.errors(include_url=False, include_input=False)
        ]
    return [{"loc": "", "msg": str(exc), "type": type(exc).__name__}]


def validate_records(
    adapter: SourceAdapter, records: list[SourceRecord]
) -> tuple[list[tuple[ProductObservation, SourceRecord]], list[RejectedRecord]]:
    """Apply the contract to every record; nothing is dropped without a trace."""
    valid: list[tuple[ProductObservation, SourceRecord]] = []
    rejected: list[RejectedRecord] = []
    seen: set[str] = set()
    for record in records:
        try:
            observation = adapter.normalize(record)
        except (ValidationError, ValueError, KeyError, InvalidOperation) as exc:
            rejected.append(
                RejectedRecord(
                    source=adapter.source,
                    source_record_ref=record.ref,
                    raw_payload=record.payload,
                    errors=_error_details(exc),
                    source_url=record.source_url,
                )
            )
            continue
        # The same product can legitimately appear twice in one extraction (e.g. listed in two
        # pages); keep the first occurrence so the batch itself is duplicate-free.
        if observation.record_hash in seen:
            continue
        seen.add(observation.record_hash)
        valid.append((observation, record))
    return valid, rejected


def run_source_ingestion(
    adapter: SourceAdapter,
    repo: WarehouseRepository,
    settings: Settings,
    *,
    pipeline_run_id: str | None,
    http_client: RetryingHttpClient | None = None,
) -> IngestionResult:
    """Run one source end-to-end and persist its operational metadata.

    The batch is committed atomically. If a critical gate fails (no rows, too many rejects) the
    valid rows are *not* loaded - a mostly-broken batch usually signals an upstream contract
    change - but rejected rows and quality results are still persisted for diagnosis.
    """
    source = adapter.source
    started = time.perf_counter()
    source_run_id = repo.start_source_run(
        source=source, pipeline_run_id=pipeline_run_id, source_mode=settings.source_mode.value
    )
    result = IngestionResult(source_run_id=source_run_id, source=source.value)

    with (
        bind_context(source=source.value, source_run_id=str(source_run_id), run_id=pipeline_run_id),
        timed_operation("ingest", source_mode=settings.source_mode.value) as op,
    ):
        try:
            records = list(adapter.extract())
            result.rows_extracted = len(records)
            valid, rejected = validate_records(adapter, records)
            result.rows_valid = len(valid)
            result.rows_rejected = len(rejected)

            gate = ingestion_checks(
                source,
                rows_extracted=result.rows_extracted,
                rows_rejected=result.rows_rejected,
                max_reject_ratio=settings.max_reject_ratio,
                min_rows=settings.min_rows_per_source,
            )
            result.quality.extend(gate)
            blocked = [check.check_name for check in gate if check.is_critical_failure]

            with repo.conn.transaction():
                repo.insert_rejected(
                    rejected, source_run_id=source_run_id, pipeline_run_id=pipeline_run_id
                )
                if not blocked:
                    result.rows_loaded = repo.insert_observations(
                        source,
                        [obs for obs, _ in valid],
                        source_run_id=source_run_id,
                        pipeline_run_id=pipeline_run_id,
                        source_urls=[rec.source_url for _, rec in valid],
                    )
                    result.rows_duplicate = result.rows_valid - result.rows_loaded
                    result.quality.append(
                        load_metric(
                            source,
                            rows_loaded=result.rows_loaded,
                            rows_duplicate=result.rows_duplicate,
                        )
                    )
                    result.status = "success"
                else:
                    result.status = "failed"
                    result.error_type = "QualityGateFailed"
                    result.error_summary = f"batch not loaded, critical checks failed: {blocked}"
                repo.record_quality_results(
                    result.quality, pipeline_run_id=pipeline_run_id, source_run_id=source_run_id
                )
                repo.finish_source_run(
                    source_run_id,
                    status=result.status,
                    rows_extracted=result.rows_extracted,
                    rows_valid=result.rows_valid,
                    rows_loaded=result.rows_loaded,
                    rows_duplicate=result.rows_duplicate,
                    rows_rejected=result.rows_rejected,
                    http_requests=http_client.request_count if http_client else None,
                    error_type=result.error_type,
                    error_summary=result.error_summary,
                )
        except Exception as exc:
            # Acquisition/schema/database failure: make sure the failure is visible in ops.
            repo.conn.rollback()
            result.status = "failed"
            result.error_type = type(exc).__name__
            result.error_summary = str(exc)[:4000]
            with repo.conn.transaction():
                repo.finish_source_run(
                    source_run_id,
                    status="failed",
                    rows_extracted=result.rows_extracted,
                    http_requests=http_client.request_count if http_client else None,
                    error_type=result.error_type,
                    error_summary=result.error_summary,
                )
            raise
        finally:
            result.duration_seconds = round(time.perf_counter() - started, 3)
            op.update(
                status=result.status,
                rows_extracted=result.rows_extracted,
                rows_loaded=result.rows_loaded,
                rows_duplicate=result.rows_duplicate,
                rows_rejected=result.rows_rejected,
            )

    if result.status != "success":
        raise IngestionFailedError(f"{source.value}: {result.error_summary}")
    return result
