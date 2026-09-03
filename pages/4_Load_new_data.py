"""Add data — drop a firm's Excel files, then Sync or Compare.

Two large actions after review:
  • Sync to database   — unwrap the Excel and write it to the live database
                         (Supabase when configured, the local file otherwise).
  • Compare with portfolio — screen the firm against the portfolio baseline.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

from lea import theme
from lea.appengine import get_ready_engine
from lea.catalog import CATALOG, IGNORE, field_names
from lea.dbconfig import check
from lea.detect import screen_firm
from lea.excel import fingerprint, normalise, read_rows
from lea.firms import list_firms, next_firm_id, register_firm
from lea.load import commit_plan, plan_file
from lea.mapper import propose
from lea.mapping import MappingSpec, save_mapping
from lea.metrics import compute_and_store

theme.apply("Add data — LEA")

SEVERITY_LABEL = {"error": "error", "warning": "warning", "info": "note"}


engine = get_ready_engine()
status = check(engine)


def _synced_before(firm_id: str) -> bool:
    """True once the firm's data is in the database and screenable."""
    if firm_id in st.session_state.get("_synced", set()):
        return True
    from lea.features import read_one
    return read_one(engine, firm_id) is not None


def _teach_layout(path, sheet) -> None:
    """Human-in-the-loop mapping for a sheet no recipe recognises.

    A proposal (AI or fuzzy) pre-fills a dropdown per source column; the user
    corrects it and saves. The saved mapping makes this layout load
    automatically from then on — for this firm and any other with the same shape.
    """
    probe = sheet.probe
    if probe is None or probe.header_row is None:
        st.caption(f"{sheet.sheet_name} — no clear header row; skipped.")
        return

    headers = [h for h in probe.header if h]

    # A pivot / cross-tab (years repeated across metric blocks) has duplicate
    # column labels. That shape is a report derived from the raw data, not a
    # record list — a column-to-field mapping cannot represent it, so we skip
    # it rather than offer a mapping that can't work.
    from collections import Counter
    norm_headers = [normalise(h) for h in headers]
    duplicated = [h for h, c in Counter(norm_headers).items() if h and c > 1]
    if duplicated:
        st.caption(
            f"{sheet.sheet_name} — looks like a pre-computed summary (repeated "
            "columns such as year totals). It is derived from the raw data and "
            "can be skipped; there is nothing to map here."
        )
        return

    fp = fingerprint(probe)
    # Widget keys must be unique per (file, sheet, column). Sheet names are
    # unique within a workbook and the file name distinguishes across uploads,
    # so this prefix is collision-proof even when two sheets are identical
    # (e.g. Nugent's four Close Year tabs) or a sheet repeats a column label.
    wid = f"{path.name}:{sheet.sheet_name}"
    with st.expander(f"Teach the app this layout — {sheet.sheet_name}"):
        st.caption(
            "This tab is not recognised yet. Map its columns once and it will "
            "load automatically every time this shape appears."
        )
        target = st.selectbox("Load this tab into", list(CATALOG), key=f"tgt:{wid}")
        use_ai = st.toggle(
            "Let AI propose the mapping", key=f"ai:{wid}",
            help="AI suggests which column feeds each field (it can only pick "
            "real fields). Off, or no API key: keyword matching.",
        )

        samples = read_rows(str(path), sheet.sheet_name, probe.header_row, max_rows=3)[1]
        cache_key = f"prop:{fp}:{target}:{use_ai}"
        if cache_key not in st.session_state:
            st.session_state[cache_key] = propose(headers, samples, target, use_ai)
        proposal, source = st.session_state[cache_key]
        st.caption(f"Proposal by {'AI' if source == 'ai' else 'keyword matching'} — "
                   "review and correct below.")

        choices = [IGNORE] + field_names(target)
        column_map: dict[str, str] = {}
        for i, h in enumerate(headers):
            default = proposal.get(normalise(h), {}).get("canonical", IGNORE)
            idx = choices.index(default) if default in choices else 0
            # Key by column position so repeated labels can never collide.
            pick = st.selectbox(h, choices, index=idx, key=f"map:{wid}:{i}")
            if pick != IGNORE:
                column_map[normalise(h)] = pick

        if st.button("Save mapping", type="primary", key=f"save:{wid}"):
            if "case_ref" not in column_map.values():
                st.error("Map at least the case identifier (case_ref) before saving.")
            else:
                save_mapping(MappingSpec(
                    fingerprint=fingerprint(probe),
                    target_table=target,
                    column_map=column_map,
                    label=f"{selected_firm.firm_name}_{sheet.sheet_name}".lower(),
                    firm_hint=selected_firm.firm_name,
                ))
                st.success("Saved. Re-drop the file and this tab will load "
                           "automatically.")
                st.rerun()

theme.header("Add firm data")

badge = theme.GREEN if status.reachable else theme.RED
st.markdown(
    f"<div style='margin:-6px 0 14px;color:{theme.MUTED};'>Database: "
    f"<b style='color:{theme.INK}'>{status.kind}</b> "
    f"<span style='color:{badge}'>&#9679;</span> {status.detail}</div>",
    unsafe_allow_html=True,
)

# --- firm -----------------------------------------------------------------

st.subheader("1. Which firm is this data for?")
firms = list_firms(engine)
options = ["Add a new firm…"] + [f.label for f in firms]
choice = st.selectbox("Firm", options, label_visibility="collapsed", key="firm_choice")

selected_firm = None
if choice == "Add a new firm…":
    with st.form("new_firm"):
        st.caption(f"The next firm ID will be {next_firm_id(engine)}.")
        col1, col2, col3 = st.columns(3)
        name = col1.text_input("Firm name", placeholder="Ellis Law Corporation")
        city = col2.text_input("City", placeholder="Downey")
        state = col3.text_input("State", placeholder="CA", max_chars=2)
        practice = st.text_input("Primary practice", placeholder="Personal Injury")
        notes = st.text_input("Deal codename / notes", placeholder="Project Palm")
        if st.form_submit_button("Create firm", type="primary"):
            try:
                created = register_firm(engine, name, state, city, practice, notes)
                # Auto-select the new firm so file upload is immediately enabled.
                st.session_state["firm_choice"] = created.label
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
else:
    selected_firm = next(f for f in firms if f.label == choice)

# --- files ----------------------------------------------------------------

st.subheader("2. Drop the Excel files")
st.markdown(theme.UPLOAD_ICON, unsafe_allow_html=True)
uploads = st.file_uploader(
    "Drag and drop one or more .xlsx files",
    type=["xlsx", "xlsm"],
    accept_multiple_files=True,
    disabled=selected_firm is None,
    label_visibility="collapsed",
)

if selected_firm is None:
    st.info("Choose a firm above to enable file upload.")
    st.stop()
if not uploads:
    st.stop()

# --- review ---------------------------------------------------------------

st.subheader("3. Review")
scratch = Path(tempfile.mkdtemp(prefix="lea_upload_"))
plans = []
for upload in uploads:
    local = scratch / upload.name
    local.write_bytes(upload.getbuffer())
    plans.append(plan_file(engine, local, selected_firm.firm_id))

selected_sheets: dict[Path, set[str]] = {}
for plan in plans:
    # A bordered container (not an expander) so the per-sheet "Teach layout"
    # and findings expanders inside can render — expanders cannot nest.
    st.markdown(f"**{plan.path.name}** — {plan.total_rows:,} rows ready")
    with st.container(border=True):
        if plan.previously_loaded:
            st.info(
                f"Already synced on {plan.previously_loaded['ingested_at_utc']} "
                f"as firm {plan.previously_loaded['firm_id']}. Re-syncing updates "
                "existing rows rather than duplicating them."
            )
        chosen: set[str] = set()
        for sheet in plan.sheets:
            if sheet.recipe_name is None:
                _teach_layout(plan.path, sheet)
                continue
            result = sheet.result
            rows = len(result.rows) if result else 0
            label = f"{sheet.sheet_name} → {sheet.target_table} ({rows:,} rows)"
            if result and result.errors:
                st.error(f"{label} — blocked by {len(result.errors)} error(s)")
            elif rows == 0:
                st.caption(f"{label} — nothing to load")
            elif st.checkbox(label, value=True, key=f"{plan.path.name}:{sheet.sheet_name}"):
                chosen.add(sheet.sheet_name)

            if result and (result.warnings or result.errors):
                findings = pd.DataFrame(
                    [
                        {"Type": SEVERITY_LABEL.get(f.severity, ""),
                         "Check": f.check_name.replace("_", " "),
                         "Row": f.row_index, "Detail": f.detail}
                        for f in result.findings if f.severity in ("error", "warning")
                    ]
                )
                with st.expander(
                    f"{len(result.errors)} errors, {len(result.warnings)} warnings"
                ):
                    st.dataframe(findings, use_container_width=True, hide_index=True)
    selected_sheets[plan.path] = chosen

total = sum(
    len(s.result.rows)
    for p in plans for s in p.sheets
    if s.result and s.sheet_name in selected_sheets.get(p.path, set())
)

# --- the two large actions ------------------------------------------------

st.subheader("4. Sync or compare")
st.caption(
    f"{total:,} rows ready for firm {selected_firm.firm_id} — "
    f"{selected_firm.firm_name}."
)

st.markdown('<div class="hero">', unsafe_allow_html=True)
left, right = st.columns(2)
sync_clicked = left.button(
    f"Sync to {status.kind}", type="primary", disabled=total == 0,
    use_container_width=True,
    help="Unwrap the Excel and write it to the live database.",
)
compare_clicked = right.button(
    "Compare with portfolio", disabled=not _synced_before(selected_firm.firm_id),
    use_container_width=True,
    help="Screen this firm against the portfolio baseline.",
)
st.markdown("</div>", unsafe_allow_html=True)

if sync_clicked:
    summaries = []
    progress = st.progress(0.0)
    for i, plan in enumerate(plans, start=1):
        summaries += commit_plan(
            engine, plan, selected_firm.firm_id, "gui",
            only_sheets=selected_sheets.get(plan.path, set()),
        )
        progress.progress(i / len(plans))

    failed = [s for s in summaries if s["status"] != "success"]
    if failed:
        st.error(f"{len(failed)} sheet(s) failed. Nothing written for those.")
    else:
        compute_and_store(
            engine, selected_firm.firm_id, selected_firm.firm_name, in_portfolio=False
        )
        st.session_state.setdefault("_synced", set()).add(selected_firm.firm_id)
        st.success(
            f"Synced {sum(s['rows_written'] for s in summaries):,} rows to "
            f"{status.kind}. Press Compare with portfolio, or open Screen an "
            "incoming firm in the sidebar."
        )
    st.dataframe(pd.DataFrame(summaries), use_container_width=True, hide_index=True)

if compare_clicked:
    screening = screen_firm(engine, selected_firm.firm_id)
    color = {"investigate": theme.RED, "review": theme.AMBER,
             "in line": theme.GREEN}[screening.verdict]
    st.markdown(
        f"<div style='background:{color}14;border-left:6px solid {color};"
        f"padding:14px 18px;border-radius:12px;margin-top:8px;'>"
        f"<b style='color:{color};font-size:1.3rem;'>"
        f"{screening.verdict.title()}</b><br>{screening.headline}</div>",
        unsafe_allow_html=True,
    )
    st.caption("Full breakdown on the Screen an incoming firm page.")
