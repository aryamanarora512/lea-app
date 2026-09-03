"""Settings — point the app at Supabase, or stay on the local file.

The user pastes their own Supabase connection string (from their Supabase
dashboard). It is saved to a local .env beside the app and used for every
database action from then on. Nothing is sent anywhere except to the database
they name here.
"""

from __future__ import annotations

import streamlit as st

from lea import theme
from lea.db import get_engine
from lea.dbconfig import check, clear_url, current_url, is_supabase, save_url

theme.apply("Settings — LEA")

theme.header("Settings")

# A transient engine just for the status check — disposed immediately so the
# Settings page never leaves connections open against the Supabase pooler.
engine = get_engine()
try:
    status = check(engine)
finally:
    engine.dispose()

badge = theme.GREEN if status.reachable else theme.RED
st.markdown(
    f"<div style='background:#FBFCFE;border:1px solid #EDF1F6;border-radius:16px;"
    f"padding:18px 20px;margin-bottom:18px;'>"
    f"<div style='color:{theme.MUTED};font-size:.9rem;'>Currently connected to</div>"
    f"<div style='font-size:1.4rem;font-weight:700;margin-top:2px;'>{status.kind} "
    f"<span style='color:{badge};font-size:1rem;'>&#9679;</span> "
    f"<span style='font-size:1rem;font-weight:500;color:{theme.MUTED};'>"
    f"{status.detail}</span></div></div>",
    unsafe_allow_html=True,
)

st.subheader("Connect to Supabase")
st.markdown(
    "In your Supabase project: **Project Settings → Database → Connection "
    "string → URI**. Use the **Session pooler** string, and replace "
    "`[YOUR-PASSWORD]` with your database password."
)

existing = current_url() or ""
masked = existing
if is_supabase(existing) and "@" in existing:
    # Never redisplay the password.
    head, _, tail = existing.partition("@")
    masked = head.split("//")[0] + "//****:****@" + tail

pasted = st.text_input(
    "Supabase connection string",
    value="" if is_supabase(existing) else "",
    placeholder="postgresql://postgres.xxxx:[YOUR-PASSWORD]@aws-0-...pooler.supabase.com:5432/postgres",
    type="password",
)
if is_supabase(existing):
    st.caption(f"Saved connection: {masked}")

col1, col2 = st.columns(2)
if col1.button("Save and connect", type="primary", disabled=not pasted):
    try:
        save_url(pasted)
        st.cache_resource.clear()
        st.success("Saved. Reconnecting…")
        st.rerun()
    except Exception as exc:
        st.error(f"Could not save: {exc}")

if col2.button("Switch back to local file", disabled=not is_supabase(existing)):
    clear_url()
    st.cache_resource.clear()
    st.success("Now using the local file.")
    st.rerun()

if status.reachable and is_supabase(existing):
    st.divider()
    st.subheader("Sample data (optional)")
    st.caption(
        "Your database starts empty. Load the synthetic demo portfolio (12 firms "
        "and a practice case book) if you want to try the screens before real "
        "firm data is in. You can clear it later from Supabase."
    )
    if st.button("Load sample data"):
        from lea.demo import seed_demo
        seed_engine = get_engine()
        try:
            with st.spinner("Loading sample data…"):
                seed_demo(seed_engine)
        finally:
            seed_engine.dispose()
        st.cache_resource.clear()
        st.success("Sample data loaded.")

st.divider()
st.subheader("AI provider (optional)")
st.markdown(
    "Turn on AI-assisted column mapping and the chatbot by connecting any "
    "**OpenAI-compatible** provider. Leave it blank to run in offline mode "
    "(keyword matching and templates still work)."
)

from lea import llm
from lea.dbconfig import get_env, set_env

st.caption(f"Current: {llm.provider_label()}")

preset = st.selectbox("Provider", ["(keep current)"] + list(llm.PROVIDER_PRESETS))
if preset != "(keep current)":
    st.caption(llm.PROVIDER_PRESETS[preset]["note"])

col_a, col_b = st.columns(2)
default_base = (llm.PROVIDER_PRESETS[preset]["base_url"]
                if preset != "(keep current)" else get_env("LEA_LLM_BASE_URL") or "")
default_model = (llm.PROVIDER_PRESETS[preset]["model"]
                 if preset != "(keep current)" else get_env("LEA_LLM_MODEL") or "")
base_url = col_a.text_input("Base URL", value=default_base)
model = col_b.text_input("Model", value=default_model)
api_key = st.text_input("API key", type="password",
                        placeholder="paste your provider key")

c1, c2 = st.columns(2)
if c1.button("Save AI provider", type="primary"):
    payload = {"LEA_LLM_BASE_URL": base_url.strip(), "LEA_LLM_MODEL": model.strip()}
    if api_key.strip():
        payload["LEA_LLM_API_KEY"] = api_key.strip()
    set_env(payload)
    st.cache_resource.clear()
    st.success("Saved.")
    st.rerun()

if c2.button("Test connection"):
    ok, detail = llm.health_check()
    (st.success if ok else st.error)(detail)

if get_env("LEA_LLM_BASE_URL"):
    if st.button("Turn off AI (offline mode)"):
        set_env({"LEA_LLM_BASE_URL": "", "LEA_LLM_API_KEY": "", "LEA_LLM_MODEL": ""})
        st.cache_resource.clear()
        st.success("AI turned off. Running in offline mode.")
        st.rerun()

with st.expander("Notes for whoever sets this up"):
    st.markdown(
        "- The **Postgres driver** must be installed: "
        "`pip install psycopg2-binary`.\n"
        "- Use the **Session pooler** connection string on port 5432, not the "
        "direct connection (which is IPv6-only and often unreachable on a "
        "corporate network).\n"
        "- The string is stored in a local `.env` file next to the app and is "
        "never committed or transmitted anywhere else.\n"
        "- Once connected, **Sync to Supabase** on the Add data page writes "
        "there, and Tableau or Alteryx can read the same database directly."
    )
