"""LEA Target Screener — the deal-team home screen.

A non-technical reviewer picks an incoming firm and immediately sees whether its
data looks anomalous versus the existing portfolio, with plain-language reasons
and a clear "what to investigate" list. No SQL, no statistics knowledge, no code.
"""

from __future__ import annotations

import html

import streamlit as st

from lea import theme
from lea.appengine import get_ready_engine
from lea.demo import reset
from lea.detect import AMBER, GREEN, NO_BASELINE, NO_DATA, RED, Screening, screen_firm
from lea.features import read_features
from lea.narrate import bullet, summarize

theme.apply("LEA Target Screener")

FLAG_COLOR = theme.FLAG_COLOR
VERDICT_STYLE = {
    "investigate": (theme.RED, "Investigate before proceeding"),
    "review": (theme.AMBER, "A few things to review"),
    "in line": (theme.GREEN, "In line with the portfolio"),
}


def md(text: str) -> str:
    """Escape `$` so Streamlit markdown doesn't read money as LaTeX math."""
    return text.replace("$", "\\$")


engine = get_ready_engine()

theme.header("Screen an incoming firm")

# --- pick a target --------------------------------------------------------

targets = read_features(engine, in_portfolio=False)
portfolio = read_features(engine, in_portfolio=True)

if not targets:
    st.info(
        "No incoming firms yet. Use **Load new data** in the sidebar to add one, "
        "or reset the demo below to regenerate the sample targets."
    )
    if st.button("↺ Reset demo data"):
        reset(engine)
        st.cache_resource.clear()
        st.rerun()
    st.stop()

col_pick, col_meta = st.columns([3, 1])
labels = {t["firm_name"]: t["firm_id"] for t in targets}
chosen_name = col_pick.selectbox("Incoming firm", list(labels))
col_meta.metric("Portfolio firms compared against", len(portfolio))

screening: Screening = screen_firm(engine, labels[chosen_name])

# --- verdict banner -------------------------------------------------------

color, phrase = VERDICT_STYLE[screening.verdict]
st.markdown(
    f"""
    <div style="background:{color}14;border-left:6px solid {color};
                padding:18px 22px;border-radius:14px;margin:8px 0 14px;">
      <div style="font-size:24px;font-weight:700;color:{color};">{phrase}</div>
      <div style="font-size:15px;color:#333;margin-top:2px;">
        {html.escape(screening.headline)} — {html.escape(chosen_name)}
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

theme.stat_cards([
    ("Investigate", len(screening.reds), theme.RED),
    ("Review", len(screening.ambers), theme.AMBER),
    ("In line", sum(1 for r in screening.results if r.flag == GREEN), theme.GREEN),
    ("No data", sum(1 for r in screening.results if r.flag == NO_DATA), theme.GREY),
])

# --- plain-language summary ----------------------------------------------

st.subheader("What to investigate")
use_ai = st.toggle(
    "Write the summary with AI (optional)",
    help="Off: a deterministic template. On: Claude phrases the same numbers, "
    "checked so it cannot introduce a figure that isn't in the data. Needs an "
    "API key; falls back to the template automatically if none is set.",
)
summary, source = summarize(screening, use_ai=use_ai)
st.markdown(md(summary))
if use_ai:
    st.caption(
        "Summary written by AI, every number verified against the data."
        if source == "ai"
        else "No API key found (or AI declined) — showing the deterministic template."
    )

# --- the metric-by-metric scorecard --------------------------------------

st.subheader("Every metric, side by side")


def _position_bar(r) -> str:
    """A range track with the portfolio median and the target's position."""
    if r.vmin is None or r.vmax is None or r.value is None:
        return '<div style="color:#9aa0a6;">no comparison available</div>'
    span = (r.vmax - r.vmin) or 1
    median_pct = 100 * (r.median - r.vmin) / span
    target_pct = min(100, max(0, 100 * (r.value - r.vmin) / span))
    dot = FLAG_COLOR[r.flag]
    outside = r.value < r.vmin or r.value > r.vmax
    marker = (
        f'<div style="position:absolute;left:{target_pct}%;top:-4px;'
        f'transform:translateX(-50%);color:{dot};font-size:16px;'
        f'font-weight:800;">{"◀" if r.value < r.vmin else "▶" if outside else "●"}</div>'
    )
    return f"""
    <div style="position:relative;height:22px;margin:6px 0;">
      <div style="position:absolute;top:8px;width:100%;height:5px;
                  background:#e6e6e6;border-radius:3px;"></div>
      <div style="position:absolute;top:5px;left:{median_pct}%;width:2px;
                  height:11px;background:#666;" title="portfolio median"></div>
      {marker}
    </div>
    """


order = {RED: 0, AMBER: 1, GREEN: 2, NO_DATA: 3, NO_BASELINE: 4}
for r in sorted(screening.results, key=lambda x: (order[x.flag], x.metric.label)):
    m = r.metric
    left, mid, right = st.columns([3, 3, 4])

    dot = FLAG_COLOR[r.flag]
    left.markdown(
        f"<span style='color:{dot};font-size:18px;'>●</span> "
        f"**{m.label}**<br><span style='font-size:20px;font-weight:700;'>"
        f"{html.escape(m.format(r.value))}</span>",
        unsafe_allow_html=True,
    )

    if r.flag == NO_DATA:
        mid.markdown("<span style='color:#9aa0a6;'>No source file feeds this "
                     "metric yet.</span>", unsafe_allow_html=True)
    elif r.flag == NO_BASELINE:
        mid.markdown("<span style='color:#9aa0a6;'>Too few portfolio firms to "
                     "compare.</span>", unsafe_allow_html=True)
    else:
        mid.markdown(
            md(
                f"portfolio median **{m.format(r.median)}**  ·  range "
                f"{m.format(r.vmin)}–{m.format(r.vmax)}  ·  n={r.n}"
            ),
            unsafe_allow_html=True,
        )
        mid.markdown(_position_bar(r), unsafe_allow_html=True)

    right.caption(m.why if r.flag in (RED, AMBER) else "")

st.divider()
with st.expander("How to read this — for reviewers"):
    st.markdown(
        "- **The portfolio is small.** Where there are enough firms to be "
        "meaningful, we use a robust outlier score (median + MAD) that a single "
        "extreme firm cannot distort. Where firms are few, we fall back to a "
        "plain statement of rank — *\"below all 8 of our firms\"* — rather than "
        "a statistic the data can't support.\n"
        "- **No data is not zero.** A grey ⚪ metric means no source file feeds "
        "it; it is left blank, never guessed.\n"
        "- **A red flag is a question, not a verdict.** It means this firm sits "
        "outside the portfolio's experience on that measure — the reason to ask, "
        "not the answer."
    )
    if st.button("↺ Reset demo data"):
        reset(engine)
        st.cache_resource.clear()
        st.rerun()
