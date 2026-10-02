"""Read-only data access for the dashboard.

Only ``mart`` (Gold) relations are queried - never ``raw``. In Docker the dashboard connects
with a role that has SELECT on ``mart`` and nothing else. Results are cached for
``RDP_DASHBOARD_CACHE_TTL`` seconds (default 300).
"""

from __future__ import annotations

import os

import pandas as pd
import psycopg
import streamlit as st
from psycopg.types.numeric import FloatLoader

from retail_data_platform.config import Settings, get_settings
from retail_data_platform.database import connect

CACHE_TTL = int(os.environ.get("RDP_DASHBOARD_CACHE_TTL", "300"))

# Fixed categorical slots per source (validated colour order; colour follows the entity).
SOURCE_COLORS = {"api": "#2a78d6", "web": "#eb6834", "dataset": "#1baf7a"}
# Reserved status colours - always shown together with an icon and a label.
HEALTH_LABELS = {
    "healthy": "🟢 healthy",
    "warning": "🟡 warning",
    "critical": "🔴 critical",
    "running": "🔵 running",
    "abandoned": "⚫ abandoned",
}


class DataUnavailableError(RuntimeError):
    pass


def _settings() -> Settings:
    return get_settings()


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def query(sql: str, params: tuple[object, ...] = ()) -> pd.DataFrame:
    try:
        with connect(_settings(), autocommit=True) as conn:
            # Charts need floats, not Decimal. Must be registered before the cursor exists:
            # cursors copy the connection's adapters when they are created.
            conn.adapters.register_loader("numeric", FloatLoader)
            cur = conn.execute(sql.encode(), params or None)
            columns = [c.name for c in cur.description or []]
            return pd.DataFrame(cur.fetchall(), columns=columns)
    except psycopg.Error as exc:
        first_line = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
        raise DataUnavailableError(first_line) from exc


def load(sql: str, params: tuple[object, ...] = ()) -> pd.DataFrame:
    """Query or stop the page with an actionable error instead of a stack trace."""
    try:
        frame = query(sql, params)
    except DataUnavailableError as exc:
        st.error(
            "The warehouse is not reachable or the marts have not been built yet.\n\n"
            f"Details: `{exc}`\n\n"
            "Run the pipeline (`make pipeline`) and refresh this page.",
            icon="⚠️",
        )
        st.stop()
    return frame


def source_color_scale() -> dict[str, list[str]]:
    return {"domain": list(SOURCE_COLORS), "range": list(SOURCE_COLORS.values())}
