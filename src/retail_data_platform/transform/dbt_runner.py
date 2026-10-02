"""Runs dbt as a subprocess (argument list, never a shell string)."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from retail_data_platform.config import Settings
from retail_data_platform.observability import get_logger, timed_operation

log = get_logger(__name__)


def dbt_executable() -> str:
    """Prefer the dbt installed next to this interpreter (same virtualenv)."""
    sibling = Path(sys.executable).with_name("dbt")
    if sibling.is_file():
        return str(sibling)
    found = shutil.which("dbt")
    if found is None:
        raise FileNotFoundError("dbt executable not found; install the 'dbt' extra")
    return found


def run_dbt(command: list[str], settings: Settings, *, extra_args: list[str] | None = None) -> int:
    """Run ``dbt <command>`` against the configured project/profile; return the exit code."""
    args = [
        dbt_executable(),
        *command,
        "--project-dir",
        str(settings.dbt_project_dir.resolve()),
        "--profiles-dir",
        str(settings.dbt_profiles_dir.resolve()),
        "--target",
        settings.dbt_target,
        "--target-path",
        str(settings.dbt_target_path.resolve()),
        "--log-path",
        str(settings.dbt_log_path.resolve()),
        *(extra_args or []),
    ]
    with timed_operation("dbt", command=" ".join(command)) as op:
        completed = subprocess.run(args, check=False)  # noqa: S603 - fixed argument list
        op["exit_code"] = completed.returncode
    return completed.returncode
