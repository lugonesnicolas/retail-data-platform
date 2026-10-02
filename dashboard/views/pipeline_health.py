from __future__ import annotations

import altair as alt
import streamlit as st

from warehouse import HEALTH_LABELS, SOURCE_COLORS, load, source_color_scale

st.title("Pipeline Health")

runs = load(
    """
    select run_id, trigger, status, health, started_at, finished_at, duration_seconds,
           rows_extracted, rows_loaded, rows_rejected, failed_source_runs,
           critical_failures, warnings, checks_total, alerted_at, error_summary
    from mart.mart_pipeline_health
    order by started_at desc
    limit 50
    """
)
if runs.empty:
    st.info("No pipeline runs recorded yet. Trigger the `retail_pipeline` DAG in Airflow.")
    st.stop()

runs["health"] = runs["health"].map(lambda h: HEALTH_LABELS.get(h, h))
st.subheader("Recent pipeline runs")
st.dataframe(
    runs,
    hide_index=True,
    use_container_width=True,
    column_config={
        "duration_seconds": st.column_config.NumberColumn("duration s", format="%.1f"),
        "started_at": st.column_config.DatetimeColumn("started", format="YYYY-MM-DD HH:mm:ss"),
        "finished_at": st.column_config.DatetimeColumn("finished", format="YYYY-MM-DD HH:mm:ss"),
        "alerted_at": st.column_config.DatetimeColumn("alert sent", format="YYYY-MM-DD HH:mm:ss"),
    },
)

finished = runs.dropna(subset=["duration_seconds"]).sort_values("started_at")
left, right = st.columns(2)
with left:
    st.markdown("**Run duration (seconds)**")
    st.altair_chart(
        alt.Chart(finished)
        .mark_bar(color="#2a78d6", cornerRadiusEnd=4, size=14)
        .encode(
            x=alt.X("started_at:T", title="Run start", axis=alt.Axis(format="%m-%d %H:%M")),
            y=alt.Y("duration_seconds:Q", title="Seconds"),
            tooltip=["run_id", "status", alt.Tooltip("duration_seconds:Q", format=".1f")],
        )
        .properties(height=240),
        use_container_width=True,
    )

source_runs = load(
    """
    select source, status, started_at, duration_seconds, rows_extracted, rows_loaded,
           rows_duplicate, rows_rejected, http_requests, source_mode, error_type, error_summary,
           pipeline_run_id
    from mart.mart_source_run_history
    order by started_at desc
    limit 150
    """
)
with right:
    st.markdown("**Rows rejected per source run**")
    st.altair_chart(
        alt.Chart(source_runs)
        .mark_circle(size=80, stroke="white", strokeWidth=1)
        .encode(
            x=alt.X("started_at:T", title="Source run start", axis=alt.Axis(format="%m-%d %H:%M")),
            y=alt.Y("rows_rejected:Q", title="Rejected rows"),
            color=alt.Color("source:N", scale=alt.Scale(**source_color_scale())),
            tooltip=[
                "source",
                "status",
                "rows_extracted",
                "rows_loaded",
                "rows_rejected",
                "pipeline_run_id",
            ],
        )
        .properties(height=240),
        use_container_width=True,
    )

st.subheader("Source freshness")
freshness = load(
    "select source, last_run_status, last_success_at, hours_since_last_success, is_stale, "
    "failed_runs_7d, rows_rejected_7d from mart.mart_source_metrics order by source"
)
cols = st.columns(len(freshness))
for col, row in zip(cols, freshness.itertuples(), strict=True):
    hours = (
        "never" if row.hours_since_last_success is None else f"{row.hours_since_last_success:.1f} h"
    )
    col.metric(
        f"{row.source} {'🟡 stale' if row.is_stale else '🟢 fresh'}",
        hours,
        f"{row.failed_runs_7d} failed runs · {row.rows_rejected_7d} rejected (7d)",
        delta_color="off",
        delta_arrow="off",
    )
    col.markdown(
        f"<span style='display:inline-block;width:10px;height:10px;border-radius:2px;"
        f"background:{SOURCE_COLORS.get(row.source, '#888')}'></span> last run: "
        f"**{row.last_run_status or 'n/a'}**",
        unsafe_allow_html=True,
    )

st.subheader("Source runs")
st.dataframe(source_runs, hide_index=True, use_container_width=True)

st.subheader("Data-quality findings (last 7 days)")
quality = load(
    """
    select checked_at, severity, layer, check_name, source, status, observed_value, threshold,
           details, pipeline_run_id
    from mart.mart_data_quality
    where status in ('fail', 'error') and checked_at >= now() - interval '7 days'
    order by case severity when 'critical' then 0 when 'warning' then 1 else 2 end,
             checked_at desc
    limit 200
    """
)
if quality.empty:
    st.success("No failing quality checks in the last 7 days.", icon="✅")
else:
    quality["severity"] = quality["severity"].map(
        {"critical": "🔴 critical", "warning": "🟡 warning", "info": "🔵 info"}
    )
    st.dataframe(quality, hide_index=True, use_container_width=True)
