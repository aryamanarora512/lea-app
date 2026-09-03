"""Case explorer — does an incoming case qualify, and what do comparables settle for.

An attorney describes a case (injury type, city, coverage) in plain words or with
the selectors, and sees the settlement distribution of comparable cases as a box
plot, plus a plain verdict on whether the case is worth taking. The optional AI
box only translates the words into the selectors; every number is computed by
SQL over real rows.
"""

from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from lea import llm, textql, theme
from lea.cases import (
    COVERAGE_BANDS, MEASURES, QuerySpec, distinct_values, fetch_rows,
    group_summary, percentiles, qualify_case,
)
from lea.appengine import get_ready_engine
from lea.nlquery import resolve

theme.apply("Case Explorer — LEA")

engine = get_ready_engine()

theme.header("Case explorer")

# --- Ask the data (text-to-SQL) ------------------------------------------

st.subheader("Ask the data")

if not llm.is_configured():
    st.info("Turn on an AI provider in Settings to ask free-form questions.")
else:
    EXAMPLES = [
        "Show the distribution of cases by settlement range",
        "Which 5 attorneys have the highest total fees?",
        "Average settlement and case count by practice area",
    ]
    ex_cols = st.columns(len(EXAMPLES))
    for i, x in enumerate(EXAMPLES):
        if ex_cols[i].button(x, key=f"dq_ex:{i}", use_container_width=True):
            st.session_state.data_q = x
    dq = st.text_input(
        "Your question", key="data_q",
        placeholder="e.g. how many cases settled above $100k, by year?",
    )
    if dq:
        with st.spinner("Writing and running the query…"):
            res = textql.ask(dq, engine)
        if res.error:
            st.warning(res.error)
            if res.sql:
                st.code(res.sql, language="sql")
        else:
            st.markdown(res.answer.replace("$", "\\$"))
            with st.expander("Show the SQL and full results"):
                st.code(res.sql, language="sql")
                if res.rows:
                    st.dataframe(pd.DataFrame(res.rows), use_container_width=True,
                                 hide_index=True)

st.divider()

injuries = distinct_values(engine, "injury_type")
cities = distinct_values(engine, "city")

# --- natural-language box (optional) --------------------------------------

with st.container():
    nl = st.text_input(
        "Describe what you want to see",
        placeholder="settlement percentiles for dog bites in Los Angeles",
    )
    use_ai = st.toggle(
        "Use AI to read my request",
        help="On: Claude maps your sentence to the filters below (it can only "
        "pick from allowed values). Off, or with no API key: keyword matching.",
    )

if "spec" not in st.session_state:
    st.session_state.spec = QuerySpec()

if nl:
    spec, source = resolve(nl, engine, use_ai=use_ai)
    st.session_state.spec = spec
    st.caption(
        f"Read as: {MEASURES[spec.measure]}"
        + (f", {spec.injury_type}" if spec.injury_type else "")
        + (f", {spec.city}" if spec.city else "")
        + (f", {spec.coverage_band}" if spec.coverage_band else "")
        + f"  ·  interpreted by {'AI' if source == 'ai' else 'keywords'}"
    )

spec = st.session_state.spec

# --- selectors ------------------------------------------------------------

c1, c2, c3, c4 = st.columns(4)
measure = c1.selectbox(
    "Measure", list(MEASURES), format_func=lambda k: MEASURES[k],
    index=list(MEASURES).index(spec.measure),
)
injury = c2.selectbox(
    "Injury type", ["All"] + injuries,
    index=(injuries.index(spec.injury_type) + 1) if spec.injury_type in injuries else 0,
)
city = c3.selectbox(
    "City", ["All"] + cities,
    index=(cities.index(spec.city) + 1) if spec.city in cities else 0,
)
coverage = c4.selectbox(
    "Coverage", ["All"] + COVERAGE_BANDS,
    index=(COVERAGE_BANDS.index(spec.coverage_band) + 1)
    if spec.coverage_band in COVERAGE_BANDS else 0,
)

group_by = st.radio(
    "Split the chart by", ["injury_type", "city", "coverage_band"],
    format_func=lambda c: {"injury_type": "Injury type", "city": "City",
                           "coverage_band": "Coverage"}[c],
    horizontal=True,
)

active = QuerySpec(
    measure=measure,
    injury_type=None if injury == "All" else injury,
    city=None if city == "All" else city,
    coverage_band=None if coverage == "All" else coverage,
    group_by=group_by,
)

# --- box-and-whiskers -----------------------------------------------------

rows = fetch_rows(engine, active)
if not rows:
    st.info("No cases match those filters. Loosen one and try again.")
    st.stop()

money = active.measure in ("gross_settlement", "net_fee")
axis_fmt = "$,.0f" if money else (".0f" if active.measure == "duration_days" else ".1f")


def fmt(v) -> str:
    if v is None:
        return "—"
    if money:
        return f"${v:,.0f}"
    if active.measure == "fee_pct":
        return f"{v:.1f}%"
    return f"{v:,.0f}"


# The verb that reads naturally for the chosen measure.
verb = "settled" if money else "fell"

summary = group_summary(engine, active)
frame = pd.DataFrame([
    {
        **g,
        "box_tip": (
            f"{g['group']}  —  about two-thirds (68%) of cases {verb} between "
            f"{fmt(g['lo68'])} and {fmt(g['hi68'])}"
        ),
        "whisker_tip": (
            f"{g['group']}  —  95% of cases {verb} between "
            f"{fmt(g['lo95'])} and {fmt(g['hi95'])}"
        ),
        "median_tip": (
            f"{g['group']}  —  median {fmt(g['median'])}: half of the "
            f"{g['n']:,} cases {verb} above this, half below"
        ),
    }
    for g in summary
])

x_enc = alt.X("group:N", title=None, sort=alt.EncodingSortField("median", order="descending"),
              axis=alt.Axis(labelAngle=0, labelLimit=140))
y_title = MEASURES[active.measure]

whisker = alt.Chart(frame).mark_rule(color=theme.BLUE, size=2, opacity=0.55).encode(
    x=x_enc,
    y=alt.Y("lo95:Q", title=y_title, axis=alt.Axis(format=axis_fmt)),
    y2="hi95:Q",
    tooltip=alt.Tooltip("whisker_tip:N", title="Full range"),
)
box = alt.Chart(frame).mark_bar(size=46, color=theme.BLUE, cornerRadius=4).encode(
    x=x_enc, y="lo68:Q", y2="hi68:Q",
    tooltip=alt.Tooltip("box_tip:N", title="Typical"),
)
median = alt.Chart(frame).mark_tick(color="white", size=46, thickness=2.5).encode(
    x=x_enc, y="median:Q",
    tooltip=alt.Tooltip("median_tip:N", title="Median"),
)
chart = (
    (whisker + box + median)
    .properties(height=420)
    .configure_view(strokeWidth=0)
    .configure_axis(grid=True, gridColor="#EDF1F6", labelColor=theme.INK,
                    titleColor=theme.MUTED)
)
st.altair_chart(chart, use_container_width=True)
st.caption("Hover any bar: box = middle ~68% · line = 95% range · white mark = median.")

stats = percentiles([r["value"] for r in rows])


theme.stat_cards([
    ("Cases", stats["n"], theme.BLUE),
    ("25th pct", fmt(stats["p25"]), theme.MUTED),
    ("Median", fmt(stats["median"]), theme.INK),
    ("75th pct", fmt(stats["p75"]), theme.MUTED),
    ("90th pct", fmt(stats["p90"]), theme.MUTED),
])

# --- does this case qualify ----------------------------------------------

st.subheader("Would an incoming case qualify?")
q1, q2, q3, q4 = st.columns(4)
qi = q1.selectbox("Injury type ", injuries, key="q_injury")
qc = q2.selectbox("City ", cities, key="q_city")
qcov = q3.selectbox("Coverage ", COVERAGE_BANDS, key="q_cov")
threshold = q4.number_input("Minimum net fee to take it", value=15000, step=5000)

if st.button("Check this case", type="primary"):
    result = qualify_case(
        engine,
        QuerySpec(injury_type=qi, city=qc, coverage_band=qcov),
        min_net_fee=threshold,
    )
    if result["verdict"] == "no_comparables":
        st.warning("No comparable settled cases on file for that combination.")
    else:
        verdict_map = {
            "qualifies": (theme.GREEN, "Likely worth taking"),
            "borderline": (theme.AMBER, "Borderline — worth a closer look"),
            "below_threshold": (theme.RED, "Below your threshold"),
        }
        color, label = verdict_map[result["verdict"]]
        st.markdown(
            f"<div style='background:{color}14;border-left:6px solid {color};"
            f"padding:16px 20px;border-radius:14px;'>"
            f"<b style='color:{color};font-size:1.3rem;'>{label}</b><br>"
            f"Comparable cases earn a median net fee of "
            f"<b>${result['expected_net_fee']:,.0f}</b> "
            f"(across {result['n']} cases; range ${result['min']:,.0f}–"
            f"${result['max']:,.0f}). Your threshold is ${threshold:,.0f}.</div>",
            unsafe_allow_html=True,
        )
        st.caption(
            "Synthetic case book for the demo — the real version runs on the "
            "firm's own settled cases once that data is loaded."
        )
