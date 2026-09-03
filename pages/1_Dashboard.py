"""Case dashboard — a dense, vibrant view of a firm's case book.

Pick a firm (or all firms), then toggle through views. Every number and bar is
computed by SQL over cas_economics — on your Supabase that's the real loaded
data (e.g. Nugent); locally it's the synthetic sample book.
"""

from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from lea import dashboard as dash
from lea import theme
from lea.appengine import get_ready_engine

theme.apply("Dashboard — LEA")
engine = get_ready_engine()

theme.header("Case dashboard")

firms = dash.firm_options(engine)
if not firms:
    st.info("No case data yet. Load a firm's case file (Load new data), or load "
            "sample data from Settings.")
    st.stop()

labels = ["All firms"] + [name for _fid, name in firms]
choice = st.selectbox("Firm", labels)
firm_id = None if choice == "All firms" else choice.split(" — ")[0]


def money(v) -> str:
    if v is None:
        return "—"
    if abs(v) >= 1_000_000:
        return f"${v/1_000_000:.1f}M"
    if abs(v) >= 1_000:
        return f"${v/1_000:.0f}K"
    return f"${v:,.0f}"


def bar(data, x, y, x_title, y_title, horizontal=False, money_axis=True, color_field=None):
    df = pd.DataFrame(data)
    if df.empty:
        return None
    fmt = "$,.0f" if money_axis else ",.0f"
    enc_val = alt.X(f"{y}:Q", title=y_title, axis=alt.Axis(format=fmt)) if horizontal \
        else alt.Y(f"{y}:Q", title=y_title, axis=alt.Axis(format=fmt))
    enc_cat = alt.Y(f"{x}:N", title=None, sort="-x") if horizontal \
        else alt.X(f"{x}:N", title=x_title, sort="-y", axis=alt.Axis(labelAngle=0))
    color = (alt.Color(f"{color_field or x}:N", scale=alt.Scale(range=theme.PALETTE),
                       legend=None))
    chart = alt.Chart(df).mark_bar(cornerRadius=4).encode(
        x=enc_val if horizontal else enc_cat,
        y=enc_cat if horizontal else enc_val,
        color=color,
        tooltip=list(df.columns),
    ).properties(height=300).configure_view(strokeWidth=0).configure_axis(
        grid=True, gridColor="#EDF1F6", labelColor=theme.INK, titleColor=theme.MUTED)
    return chart


t = dash.totals(engine, firm_id)
theme.stat_cards([
    ("Cases", f"{int(t.get('n_cases') or 0):,}", theme.BLUE),
    ("Total settlements", money(t.get("total_settlement")), theme.PALETTE[1]),
    ("Total fees", money(t.get("total_fee")), theme.PALETTE[2]),
    ("Avg settlement", money(t.get("avg_settlement")), theme.PALETTE[3]),
    ("Avg days to settle", f"{int(t.get('avg_days') or 0):,}", theme.PALETTE[5]),
])

tab_overview, tab_practice, tab_attorney, tab_geo = st.tabs(
    ["Overview", "Practice areas", "Attorneys", "Geography"])

with tab_overview:
    left, right = st.columns(2)
    yr = dash.by_year(engine, firm_id)
    if yr:
        left.markdown("**Total settlements by year**")
        c = bar(yr, "year", "total_settlement", "Year", "Total settlement")
        left.altair_chart(c, use_container_width=True)
    pr = dash.by_practice(engine, firm_id)
    if pr:
        right.markdown("**Settlements by practice area**")
        c = bar(pr, "practice", "total_settlement", "", "Total settlement",
                horizontal=True)
        right.altair_chart(c, use_container_width=True)
    st.markdown("**Largest cases**")
    big = dash.largest_cases(engine, firm_id)
    if big:
        df = pd.DataFrame(big).rename(columns={
            "case_ref": "Case", "injury_type": "Practice", "city": "County",
            "attorney": "Attorney", "gross_settlement": "Settlement",
            "net_fee": "Net fee", "settled_year": "Year"})
        st.dataframe(df, use_container_width=True, hide_index=True)

with tab_practice:
    pr = dash.by_practice(engine, firm_id)
    left, right = st.columns(2)
    if pr:
        left.markdown("**Case count by practice area**")
        left.altair_chart(bar(pr, "practice", "cases", "", "Cases",
                              horizontal=True, money_axis=False),
                          use_container_width=True)
        right.markdown("**Average settlement by practice area**")
        right.altair_chart(bar(pr, "practice", "avg_settlement", "", "Avg settlement",
                              horizontal=True), use_container_width=True)
        st.dataframe(pd.DataFrame(pr).rename(columns={
            "practice": "Practice area", "cases": "Cases",
            "total_settlement": "Total settlement", "avg_settlement": "Avg settlement"}),
            use_container_width=True, hide_index=True)

with tab_attorney:
    at = dash.by_attorney(engine, firm_id)
    if at:
        left, right = st.columns(2)
        left.markdown("**Top attorneys by total fees**")
        left.altair_chart(bar(at, "attorney", "total_fee", "", "Total fees",
                              horizontal=True), use_container_width=True)
        right.markdown("**Top attorneys by case count**")
        right.altair_chart(bar(at, "attorney", "cases", "", "Cases",
                              horizontal=True, money_axis=False),
                          use_container_width=True)
        st.dataframe(pd.DataFrame(at).rename(columns={
            "attorney": "Attorney", "cases": "Cases", "total_fee": "Total fees",
            "total_settlement": "Total settlement", "avg_settlement": "Avg settlement"}),
            use_container_width=True, hide_index=True)
    else:
        st.info("No attorney data. Re-sync the firm's file so the attorney column "
                "is populated.")

with tab_geo:
    co = dash.by_county(engine, firm_id)
    if co:
        left, right = st.columns(2)
        left.markdown("**Top counties by total settlement**")
        left.altair_chart(bar(co, "county", "total_settlement", "", "Total settlement",
                              horizontal=True), use_container_width=True)
        right.markdown("**Cases by county**")
        right.altair_chart(bar(co, "county", "cases", "", "Cases",
                              horizontal=True, money_axis=False),
                          use_container_width=True)
