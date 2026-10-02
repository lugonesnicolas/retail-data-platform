"""Retail Data Platform dashboard (Streamlit). Reads the Gold/Mart layer only."""

from __future__ import annotations

import streamlit as st

st.set_page_config(page_title="Retail Data Platform", page_icon="🛒", layout="wide")

pages = st.navigation(
    [
        st.Page("views/overview.py", title="Overview", icon="📊", default=True),
        st.Page(
            "views/price_explorer.py",
            title="Product & Price Explorer",
            icon="🔎",
            url_path="explorer",
        ),
        st.Page("views/pipeline_health.py", title="Pipeline Health", icon="🩺", url_path="health"),
    ]
)

with st.sidebar:
    st.caption(
        "Data: PostgreSQL `mart` schema (dbt Gold layer). "
        "Cached for a few minutes - use **Refresh data** after a pipeline run."
    )
    if st.button("Refresh data", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

pages.run()
