"""Portfolio baseline — what the screener compares against, and how reliable it is."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from lea import theme
from lea.appengine import get_ready_engine
from lea.detect import run_validation
from lea.features import METRICS, read_features

theme.apply("Portfolio Baseline — LEA")

engine = get_ready_engine()

theme.header("Portfolio baseline")

portfolio = read_features(engine, in_portfolio=True)
st.metric("Firms in the baseline", len(portfolio))

if not portfolio:
    st.stop()

frame = pd.DataFrame(portfolio)
display_cols = ["firm_name"] + [m.key for m in METRICS] + ["dominant_practice"]
display_cols = [c for c in display_cols if c in frame.columns]
st.dataframe(
    frame[display_cols].rename(columns={m.key: m.label for m in METRICS}),
    use_container_width=True,
    hide_index=True,
)

st.subheader("How well does the detector work?")

report = run_validation(engine)
if "note" in report:
    st.info(report["note"])
else:
    a, b = st.columns(2)
    a.metric("False-positive rate", f"{report['false_positive_rate']}%",
             help="How often a normal firm gets flagged. Lower is better; ~5% "
             "is a common target.")
    b.markdown("**Detection rate by size of the anomaly**")
    b.dataframe(
        pd.DataFrame(
            [{"Anomaly size": k, "Caught": f"{v}%"}
             for k, v in report["detection_rate"].items()]
        ),
        use_container_width=True,
        hide_index=True,
    )
