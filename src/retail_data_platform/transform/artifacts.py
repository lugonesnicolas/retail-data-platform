"""Translate dbt artefacts (run_results.json, sources.json) into :class:`QualityResult` rows."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from retail_data_platform.quality import CheckStatus, QualityResult, Severity

_TEST_STATUS = {
    "pass": CheckStatus.PASS,
    "fail": CheckStatus.FAIL,
    "warn": CheckStatus.FAIL,
    "error": CheckStatus.ERROR,
    "skipped": CheckStatus.SKIPPED,
}


def _load(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_text("utf-8"))
    return data


def results_from_run(target_path: Path) -> list[QualityResult]:
    """Every dbt test becomes a check; models/seeds only when they errored or were skipped."""
    run_results = _load(target_path / "run_results.json")
    manifest_path = target_path / "manifest.json"
    nodes: dict[str, Any] = _load(manifest_path)["nodes"] if manifest_path.exists() else {}

    results: list[QualityResult] = []
    for item in run_results.get("results", []):
        unique_id: str = item["unique_id"]
        resource_type = unique_id.split(".", 1)[0]
        node = nodes.get(unique_id, {})
        name = node.get("name", unique_id.rsplit(".", 1)[-1])
        status = str(item.get("status", "")).lower()
        message = item.get("message")

        if resource_type == "test":
            configured = str(node.get("config", {}).get("severity", "error")).lower()
            severity = Severity.CRITICAL if configured == "error" else Severity.WARNING
            failures = item.get("failures")
            attached = node.get("attached_node") or ""
            results.append(
                QualityResult(
                    check_name=f"dbt.test.{name}",
                    layer="dbt",
                    severity=severity,
                    status=_TEST_STATUS.get(status, CheckStatus.ERROR),
                    observed_value=Decimal(failures) if failures is not None else None,
                    threshold=Decimal(0),
                    details=(f"{attached.rsplit('.', 1)[-1]}: {message}" if attached else message),
                )
            )
        elif status in {"error", "skipped"}:
            results.append(
                QualityResult(
                    check_name=f"dbt.{resource_type}.{name}",
                    layer="dbt",
                    severity=Severity.CRITICAL if status == "error" else Severity.WARNING,
                    status=CheckStatus.ERROR if status == "error" else CheckStatus.SKIPPED,
                    details=message,
                )
            )
    return results


def results_from_freshness(target_path: Path) -> list[QualityResult]:
    sources = _load(target_path / "sources.json")
    results: list[QualityResult] = []
    for item in sources.get("results", []):
        status = str(item.get("status", "")).lower()
        unique_id: str = item["unique_id"]
        # source.<project>.<source_name>.<table>
        table = ".".join(unique_id.split(".")[2:])
        age = item.get("max_loaded_at_time_ago_in_s")
        results.append(
            QualityResult(
                check_name=f"freshness.{table}",
                layer="freshness",
                severity=Severity.CRITICAL if status == "error" else Severity.WARNING,
                status=CheckStatus.PASS
                if status == "pass"
                else (CheckStatus.ERROR if status == "runtime error" else CheckStatus.FAIL),
                observed_value=Decimal(str(round(age / 3600, 2))) if age is not None else None,
                details=f"hours since last load (status={status})",
            )
        )
    return results
