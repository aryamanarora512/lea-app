"""One shared database engine for the whole app.

Streamlit caches this per-process, so every page reuses a single connection
pool rather than each opening its own. That keeps the total number of
connections tiny — important when talking to Supabase's shared pooler, which
trips a circuit breaker if it sees a connection storm.
"""

from __future__ import annotations

import streamlit as st

from .db import get_engine
from .dbconfig import load_env_into_process
from .demo import ensure_ready


@st.cache_resource(show_spinner="Connecting to the database…")
def get_ready_engine():
    load_env_into_process()  # make saved LLM/DB config visible to this process
    engine = get_engine()
    ensure_ready(engine)
    return engine
