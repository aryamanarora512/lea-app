"""Quick Compare — drop an incoming firm's files, compare, ask questions.

Unlike Add data (which saves a firm to the database), Quick Compare screens an
incoming firm against the portfolio baseline WITHOUT saving anything. Drop the
files, see the red flags, and ask plain-language questions about how the firm
stacks up.
"""

from __future__ import annotations

import html
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

from lea import theme
from lea.appengine import get_ready_engine
from lea.ask import answer
from lea.detect import GREEN, NO_DATA, RED
from lea.features import read_features
from lea.narrate import summarize
from lea.quickcompare import portfolio_available, quick_compare

theme.apply("Quick Compare — LEA")

engine = get_ready_engine()

theme.header("Quick compare")

baseline_n = portfolio_available(engine)
if baseline_n == 0:
    st.warning(
        "There are no portfolio firms to compare against yet. Add portfolio "
        "firms, or load the sample portfolio from the Settings page (Load sample "
        "data), then come back here."
    )

VERDICT = {"investigate": (theme.RED, "Investigate before proceeding"),
           "review": (theme.AMBER, "A few things to review"),
           "in line": (theme.GREEN, "In line with the portfolio")}

# --- drop files -----------------------------------------------------------

name = st.text_input("Incoming firm name (optional)", placeholder="Incoming firm")
st.markdown(theme.UPLOAD_ICON, unsafe_allow_html=True)
uploads = st.file_uploader(
    "Drag and drop the incoming firm's .xlsx files",
    type=["xlsx", "xlsm"], accept_multiple_files=True, label_visibility="collapsed",
)

if not uploads:
    st.caption("Nothing is saved from this screen — it is a look, not a load.")
    st.stop()

# Compute once per distinct file set, not on every chat rerun.
signature = tuple(sorted((u.name, u.size) for u in uploads)) + (name,)
if st.session_state.get("qc_sig") != signature:
    scratch = Path(tempfile.mkdtemp(prefix="lea_qc_"))
    paths = []
    for u in uploads:
        p = scratch / u.name
        p.write_bytes(u.getbuffer())
        paths.append(p)
    with st.spinner("Comparing against the portfolio…"):
        screening, values, summaries = quick_compare(
            engine, paths, name.strip() or "Incoming firm")
    st.session_state.qc_sig = signature
    st.session_state.qc = {
        "screening": screening, "values": values, "summaries": summaries,
        "portfolio": read_features(engine, in_portfolio=True),
    }
    st.session_state.qc_chat = []

qc = st.session_state.qc
screening = qc["screening"]

# --- verdict + scorecard --------------------------------------------------

color, phrase = VERDICT[screening.verdict]
st.markdown(
    f"<div style='background:{color}14;border-left:6px solid {color};"
    f"padding:18px 22px;border-radius:14px;margin:6px 0 14px;'>"
    f"<div style='font-size:22px;font-weight:700;color:{color};'>{phrase}</div>"
    f"<div style='color:#333;margin-top:2px;'>{html.escape(screening.headline)} "
    f"— {html.escape(screening.firm_name)}</div></div>",
    unsafe_allow_html=True,
)
theme.stat_cards([
    ("Investigate", len(screening.reds), theme.RED),
    ("Review", len(screening.ambers), theme.AMBER),
    ("In line", sum(1 for r in screening.results if r.flag == GREEN), theme.GREEN),
    ("No data", sum(1 for r in screening.results if r.flag == NO_DATA), theme.GREY),
])

use_ai = st.toggle("Write with AI", help="Off: deterministic template. On: Claude "
                   "phrases the same numbers (needs an API key).")
summary, _ = summarize(screening, use_ai=use_ai)
st.markdown(summary.replace("$", "\\$"))

with st.expander("Every metric, side by side"):
    table = pd.DataFrame([
        {"Metric": r.metric.label,
         "Incoming firm": r.metric.format(r.value),
         "Portfolio median": r.metric.format(r.median),
         "Flag": {RED: "Investigate", "amber": "Review", GREEN: "In line",
                  NO_DATA: "No data", "no_baseline": "No baseline"}.get(r.flag, r.flag)}
        for r in screening.results
    ])
    st.dataframe(table, use_container_width=True, hide_index=True)

# --- chatbot --------------------------------------------------------------

st.subheader("Ask about this firm")

# EvenUp-style prompt gallery: one-tap questions grouped by intent.
PROMPT_GROUPS = {
    "Overall verdict": [
        "Any red flags before we buy this firm?",
        "What's the overall assessment versus the portfolio?",
        "Is anything anomalous or of note here?",
    ],
    "Specific comparisons": [
        "How does the attorney pay compare?",
        "Is the practice too concentrated?",
        "How does the case volume compare?",
        "How complete is their diligence?",
        "How concentrated is the pay on one person?",
    ],
}

pending: str | None = None
for group, prompts in PROMPT_GROUPS.items():
    st.markdown(f"<span style='color:{theme.MUTED};font-size:.85rem;'>{group}</span>",
                unsafe_allow_html=True)
    cols = st.columns(3)
    for i, p in enumerate(prompts):
        if cols[i % 3].button(p, key=f"prompt:{group}:{i}", use_container_width=True):
            pending = p

for role, text in st.session_state.get("qc_chat", []):
    with st.chat_message(role):
        st.markdown(text.replace("$", "\\$"))

typed = st.chat_input("Ask your own question about the incoming firm")
question = typed or pending
if question:
    reply = answer(question, qc["values"], qc["portfolio"], use_ai=use_ai,
                   firm_name=screening.firm_name)
    st.session_state.qc_chat.append(("user", question))
    st.session_state.qc_chat.append(("assistant", reply))
    st.rerun()
