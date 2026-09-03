"""Shared visual language: white background, blue accents, large Apple-style UI.

Every page calls apply() once at the top. Colours and radii live here so the
whole app stays consistent.
"""

from __future__ import annotations

import streamlit as st

BLUE = "#2F80ED"
BLUE_DARK = "#1C63C7"
INK = "#1A1A1A"
MUTED = "#6B7280"
GREEN = "#34A853"
AMBER = "#F2A63B"
RED = "#E5484D"
GREY = "#9AA0A6"

FLAG_COLOR = {"red": RED, "amber": AMBER, "green": GREEN,
              "no_data": GREY, "no_baseline": GREY}

# Vibrant categorical palette for dense dashboards — reads well on white.
PALETTE = ["#2F80ED", "#27AE94", "#9B59B6", "#EB5F8B", "#F2A63B",
           "#56CCF2", "#6C5CE7", "#2D9CDB", "#E5484D", "#16A085"]

_CSS = f"""
<style>
  html, body, [class*="css"] {{
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI",
                 Roboto, Helvetica, Arial, sans-serif;
  }}
  .block-container {{ padding-top: 2.4rem; max-width: 1100px; }}
  #MainMenu, footer, header [data-testid="stToolbar"] {{ visibility: hidden; }}

  h1 {{ font-weight: 700; letter-spacing: -0.02em; color: {INK}; }}
  h2, h3 {{ font-weight: 650; letter-spacing: -0.01em; color: {INK}; }}

  /* Buttons — large, rounded, blue */
  div[data-testid="stButton"] > button,
  div[data-testid="stFormSubmitButton"] > button {{
    border-radius: 14px;
    padding: 0.7rem 1.3rem;
    font-size: 1.02rem;
    font-weight: 600;
    border: 1px solid #E3E8EF;
    transition: transform .05s ease, box-shadow .15s ease;
  }}
  div[data-testid="stButton"] > button:hover {{
    box-shadow: 0 4px 14px rgba(47,128,237,0.18);
    transform: translateY(-1px);
  }}
  div[data-testid="stButton"] > button[kind="primary"],
  div[data-testid="stFormSubmitButton"] > button[kind="primary"] {{
    background: {BLUE};
    border: none;
    color: #fff;
  }}
  div[data-testid="stButton"] > button[kind="primary"]:hover {{ background: {BLUE_DARK}; }}

  /* The two hero action buttons */
  .hero div[data-testid="stButton"] > button {{
    min-height: 5.2rem;
    font-size: 1.25rem;
    border-radius: 20px;
    width: 100%;
  }}

  [data-testid="stMetricValue"] {{ font-weight: 700; }}
  [data-baseweb="select"] > div {{ border-radius: 12px; }}
  [data-testid="stFileUploaderDropzone"] {{
    border-radius: 18px; border: 2px dashed #C7D2E1; background: #FBFCFE;
  }}
</style>
"""

UPLOAD_ICON = """
<svg width="46" height="46" viewBox="0 0 24 24" fill="none"
     xmlns="http://www.w3.org/2000/svg" style="display:block;margin:0 auto;">
  <path d="M12 3v11" stroke="#2F80ED" stroke-width="2.2" stroke-linecap="round"/>
  <path d="M7.5 7.5 12 3l4.5 4.5" stroke="#2F80ED" stroke-width="2.2"
        stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M5 13v4.5A2.5 2.5 0 0 0 7.5 20h9a2.5 2.5 0 0 0 2.5-2.5V13"
        stroke="#2F80ED" stroke-width="2.2" stroke-linecap="round"/>
</svg>
"""


def apply(page_title: str) -> None:
    st.set_page_config(page_title=page_title, page_icon=None, layout="wide")
    st.markdown(_CSS, unsafe_allow_html=True)


def header(title: str, subtitle: str = "") -> None:
    st.markdown(f"<h1 style='margin-bottom:.2rem'>{title}</h1>", unsafe_allow_html=True)
    if subtitle:
        st.markdown(
            f"<p style='color:{MUTED};font-size:1.05rem;margin-top:0;"
            f"max-width:720px'>{subtitle}</p>",
            unsafe_allow_html=True,
        )


def stat_cards(cards: list[tuple[str, int, str]]) -> None:
    """cards: (label, value, color-hex). Rendered as a clean row of tiles."""
    cols = st.columns(len(cards))
    for col, (label, value, color) in zip(cols, cards):
        col.markdown(
            f"""
            <div style="background:#FBFCFE;border:1px solid #EDF1F6;
                        border-radius:16px;padding:14px 16px;">
              <div style="display:flex;align-items:center;gap:8px;">
                <span style="width:11px;height:11px;border-radius:50%;
                             background:{color};display:inline-block;"></span>
                <span style="color:{MUTED};font-size:.9rem;">{label}</span>
              </div>
              <div style="font-size:2rem;font-weight:700;color:{INK};
                          margin-top:2px;">{value}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
