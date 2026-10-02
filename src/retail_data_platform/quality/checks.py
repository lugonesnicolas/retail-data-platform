"""Quality result model and ingestion-boundary checks.

Severity semantics used across the platform:

* ``critical`` - the pipeline run must fail (e.g. a source returned nothing, too many rejects,
  a dbt test configured with ``severity: error`` failed);
* ``warning``  - recorded and surfaced on the dashboard, does not fail the run;
* ``info``     - a metric worth tracking over time (row counts, duplicates skipped).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from retail_data_platform.models import SourceName


class Severity(StrEnum):
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


class CheckStatus(StrEnum):
    PASS = "pass"  # noqa: S105 - not a password
    FAIL = "fail"
    ERROR = "error"
    SKIPPED = "skipped"


@dataclass(frozen=True, slots=True)
class QualityResult:
    check_name: str
    layer: str
    severity: Severity
    status: CheckStatus
    source: str | None = None
    observed_value: Decimal | None = None
    threshold: Decimal | None = None
    details: str | None = None

    @property
    def is_critical_failure(self) -> bool:
        return self.severity is Severity.CRITICAL and self.status in {
            CheckStatus.FAIL,
            CheckStatus.ERROR,
        }


def ingestion_checks(
    source: SourceName,
    *,
    rows_extracted: int,
    rows_rejected: int,
    max_reject_ratio: float,
    min_rows: int,
) -> list[QualityResult]:
    """Gating checks evaluated for every source batch *before* it is committed to raw."""
    reject_ratio = (
        Decimal(rows_rejected) / Decimal(rows_extracted) if rows_extracted else Decimal(0)
    )
    reject_ratio = reject_ratio.quantize(Decimal("0.0001"))
    return [
        QualityResult(
            check_name="ingestion.min_rows_extracted",
            layer="ingestion",
            severity=Severity.CRITICAL,
            status=CheckStatus.PASS if rows_extracted >= min_rows else CheckStatus.FAIL,
            source=source.value,
            observed_value=Decimal(rows_extracted),
            threshold=Decimal(min_rows),
            details="source must return at least the configured number of records",
        ),
        QualityResult(
            check_name="ingestion.reject_ratio",
            layer="ingestion",
            severity=Severity.CRITICAL,
            status=CheckStatus.PASS
            if reject_ratio <= Decimal(str(max_reject_ratio))
            else CheckStatus.FAIL,
            source=source.value,
            observed_value=reject_ratio,
            threshold=Decimal(str(max_reject_ratio)),
            details="share of records violating the data contract",
        ),
        QualityResult(
            check_name="ingestion.no_rejected_records",
            layer="ingestion",
            severity=Severity.WARNING,
            status=CheckStatus.PASS if rows_rejected == 0 else CheckStatus.FAIL,
            source=source.value,
            observed_value=Decimal(rows_rejected),
            threshold=Decimal(0),
            details="rejected records are stored in raw.rejected_records",
        ),
    ]


def load_metric(source: SourceName, *, rows_loaded: int, rows_duplicate: int) -> QualityResult:
    """Informational metric recorded after a batch has been committed."""
    return QualityResult(
        check_name="ingestion.rows_loaded",
        layer="ingestion",
        severity=Severity.INFO,
        status=CheckStatus.PASS,
        source=source.value,
        observed_value=Decimal(rows_loaded),
        details=f"new observations appended; {rows_duplicate} already-ingested duplicates skipped",
    )
