from __future__ import annotations

import altair as alt
import streamlit as st

from warehouse import load, source_color_scale

st.title("Product & Price Explorer")

products = load(
    """
    select l.product_key, l.source, l.product_name, l.brand, l.category, l.retailer,
           l.price, l.currency, l.price_usd, l.availability, l.rating, l.last_observed_at,
           c.price_change_pct, c.category_price_index, l.observation_count, l.product_url
    from mart.mart_product_latest as l
    join mart.mart_price_comparison as c using (product_key)
    """
)

f1, f2, f3, f4 = st.columns([1, 1.4, 1.4, 1.6])
sources = f1.multiselect("Source", sorted(products.source.unique()))
categories = f2.multiselect("Category", sorted(products.category.unique()))
brands = f3.multiselect("Brand", sorted(products.brand.dropna().unique()))
search = f4.text_input("Product contains", placeholder="e.g. iPhone")

view = products
if sources:
    view = view[view.source.isin(sources)]
if categories:
    view = view[view.category.isin(categories)]
if brands:
    view = view[view.brand.isin(brands)]
if search:
    view = view[view.product_name.str.contains(search, case=False, regex=False)]

st.caption(
    f"{len(view):,} of {len(products):,} products · "
    "prices compared in USD using static reference rates"
)
if view.empty:
    st.info("No products match the filters.")
    st.stop()

color = alt.Color(
    "source:N", scale=alt.Scale(**source_color_scale()), legend=alt.Legend(title="Source")
)

left, right = st.columns(2)
with left:
    st.markdown("**Price distribution by category (USD, log scale)**")
    strip = (
        alt.Chart(view)
        .mark_circle(size=70, opacity=0.8, stroke="white", strokeWidth=1)
        .encode(
            x=alt.X("price_usd:Q", scale=alt.Scale(type="log"), title="Price (USD)"),
            y=alt.Y("category:N", title=None),
            yOffset=alt.YOffset("source:N"),
            color=color,
            tooltip=["product_name", "source", "brand", "price", "currency", "price_usd"],
        )
        .properties(height=40 * view.category.nunique() + 40)
    )
    st.altair_chart(strip, use_container_width=True)
with right:
    st.markdown("**Median price per category and source (USD)**")
    medians = view.groupby(["category", "source"], as_index=False).agg(
        median_price_usd=("price_usd", "median"), products=("product_key", "count")
    )
    grouped = (
        alt.Chart(medians)
        .mark_bar(cornerRadiusEnd=4, size=12)
        .encode(
            x=alt.X("median_price_usd:Q", title="Median price (USD)"),
            y=alt.Y("category:N", title=None),
            yOffset="source:N",
            color=color,
            tooltip=[
                "category",
                "source",
                alt.Tooltip("median_price_usd:Q", format="$.2f"),
                "products",
            ],
        )
        .properties(height=40 * medians.category.nunique() + 40)
    )
    st.altair_chart(grouped, use_container_width=True)

st.markdown("**Products**")
st.dataframe(
    view.drop(columns=["product_key"]).sort_values(["category", "price_usd"]),
    hide_index=True,
    use_container_width=True,
    column_config={
        "price_usd": st.column_config.NumberColumn("price USD", format="$%.2f"),
        "price_change_pct": st.column_config.NumberColumn("Δ vs prev. %", format="%.2f"),
        "category_price_index": st.column_config.NumberColumn(
            "category index", help="price / category median (USD)", format="%.2f"
        ),
        "product_url": st.column_config.LinkColumn("url", display_text="open"),
        "last_observed_at": st.column_config.DatetimeColumn("observed", format="YYYY-MM-DD HH:mm"),
    },
)

st.markdown("**Price history**")
options = view.sort_values("product_name")
choice = st.selectbox(
    "Product",
    options.product_key,
    format_func=lambda key: "{} · {}".format(
        *options.loc[options.product_key == key, ["product_name", "source"]].iloc[0]
    ),
)
history = load(
    "select observed_at, price, currency, availability from mart.fct_price_observation "
    "where product_key = %s order by observed_at",
    (choice,),
)
if len(history) < 2:
    st.caption("Only one observation so far - history appears after the next daily run.")
line = (
    alt.Chart(history)
    .mark_line(point=alt.OverlayMarkDef(size=64, filled=True), strokeWidth=2, color="#2a78d6")
    .encode(
        x=alt.X("observed_at:T", title="Observed", axis=alt.Axis(format="%Y-%m-%d")),
        y=alt.Y("price:Q", title=f"Price ({history.currency.iloc[0] if len(history) else ''})"),
        tooltip=["observed_at:T", "price", "currency", "availability"],
    )
    .properties(height=260)
)
st.altair_chart(line, use_container_width=True)
