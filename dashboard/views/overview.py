from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from warehouse import HEALTH_LABELS, load


def _ago(ts: pd.Timestamp | None) -> str:
    if ts is None or pd.isna(ts):
        return "never"
    hours = (pd.Timestamp.now(tz="UTC") - ts).total_seconds() / 3600
    return f"{hours * 60:.0f} min ago" if hours < 1 else f"{hours:.1f} h ago"


st.title("Overview")
st.caption("Multi-source retail product observations - API, web scraping and a CSV dataset.")

totals = load(
    """
    select
        (select count(*) from mart.mart_product_latest)        as products,
        (select count(*) from mart.fct_price_observation)      as observations,
        (select count(*) from mart.mart_source_metrics where not is_stale) as fresh_sources,
        (select count(*) from mart.mart_source_metrics)        as sources,
        (select max(hours_since_last_success) from mart.mart_source_metrics) as worst_freshness_h
    """
).iloc[0]
last_success = load(
    "select max(finished_at) as finished_at from mart.mart_pipeline_health where status = 'success'"
).iloc[0]["finished_at"]
latest_run = load(
    "select run_id, health, critical_failures, warnings from mart.mart_pipeline_health "
    "where status <> 'running' order by started_at desc limit 1"
)

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Products", f"{int(totals.products):,}")
c2.metric("Price observations", f"{int(totals.observations):,}")
c3.metric("Fresh sources", f"{int(totals.fresh_sources)} / {int(totals.sources)}")
c4.metric("Last successful run", _ago(last_success))
if latest_run.empty:
    c5.metric("Data quality", "no runs yet")
else:
    run = latest_run.iloc[0]
    c5.metric("Data quality (last run)", str(run.health).capitalize())
    c5.caption(
        f"{HEALTH_LABELS.get(run.health, run.health)} · "
        f"{int(run.critical_failures)} critical · {int(run.warnings)} warnings"
    )
if pd.notna(totals.worst_freshness_h):
    st.caption(f"Stalest source: last successful load {totals.worst_freshness_h:.1f} h ago.")

st.subheader("Sources")
sources = load(
    """
    select source, display_name, acquisition_method, product_count, observation_count,
           last_run_status, last_run_mode, last_success_at, hours_since_last_success, is_stale,
           rows_rejected_7d, failed_checks_7d
    from mart.mart_source_metrics order by source
    """
)
sources["freshness"] = sources["is_stale"].map({True: "🟡 stale", False: "🟢 fresh"})
st.dataframe(
    sources.drop(columns=["is_stale"]),
    hide_index=True,
    use_container_width=True,
    column_config={
        "hours_since_last_success": st.column_config.NumberColumn(
            "hours since success", format="%.1f"
        ),
        "last_success_at": st.column_config.DatetimeColumn(
            "last success", format="YYYY-MM-DD HH:mm"
        ),
    },
)

st.subheader("Products per category")
categories = load(
    "select category, product_count, source_count, sources, median_price_usd, "
    "availability_ratio, avg_rating from mart.mart_category_metrics order by product_count desc"
)
left, right = st.columns([3, 2])
with left:
    bars = (
        alt.Chart(categories)
        .mark_bar(color="#2a78d6", cornerRadiusEnd=4, size=18)
        .encode(
            x=alt.X("product_count:Q", title="Products"),
            y=alt.Y("category:N", sort="-x", title=None),
            tooltip=["category", "product_count", "sources", "median_price_usd"],
        )
        .properties(height=36 * max(len(categories), 1))
    )
    labels = bars.mark_text(align="left", dx=4).encode(text="product_count:Q")
    st.altair_chart(bars + labels, use_container_width=True)
with right:
    st.dataframe(
        categories,
        hide_index=True,
        use_container_width=True,
        column_config={
            "median_price_usd": st.column_config.NumberColumn("median USD", format="$%.2f"),
            "availability_ratio": st.column_config.ProgressColumn(
                "available", min_value=0.0, max_value=1.0, format="percent"
            ),
        },
    )
