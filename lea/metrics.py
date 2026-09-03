"""Compute the firm-level feature vector from the loaded Silver tables.

This is what turns a real firm's ingested data — the census, the case ledger,
the tools list, the diligence answers — into the same set of numbers the
synthetic portfolio is expressed in, so a real target can be compared against
the baseline on equal footing.

Where a metric has no source (office count, which no seller file feeds today)
the value is left as None. That gap is surfaced honestly in the screen rather
than filled with a guess.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Engine

from .features import upsert_features

_ATTORNEY_WORDS = ("attorney", "counsel", "litigator", "partner")


def compute_and_store(
    engine: Engine, firm_id: str, firm_name: str, in_portfolio: bool = False
) -> dict:
    values, dominant = _compute(engine, firm_id)
    upsert_features(engine, firm_id, firm_name, values, dominant, in_portfolio)
    return values


def _compute(engine: Engine, firm_id: str) -> tuple[dict, str | None]:
    with engine.connect() as conn:
        census = conn.execute(
            text(
                "SELECT dept_title, function_role, employment_status, "
                "annual_salary, total_annual_comp "
                "FROM per_employee_census WHERE firm_id = :f"
            ),
            {"f": firm_id},
        ).mappings().all()

        cases = conn.execute(
            text(
                "SELECT case_type, disposition_code FROM cas_case_ledger "
                "WHERE firm_id = :f"
            ),
            {"f": firm_id},
        ).mappings().all()

        tool_count = conn.execute(
            text("SELECT COUNT(*) FROM tec_tools WHERE firm_id = :f"), {"f": firm_id}
        ).scalar() or 0

        dd = conn.execute(
            text(
                "SELECT is_answered FROM dd_responses WHERE firm_id = :f"
            ),
            {"f": firm_id},
        ).scalars().all()

        econ = conn.execute(
            text(
                "SELECT injury_type, gross_settlement, net_fee, fee_pct, "
                "duration_days FROM cas_economics WHERE firm_id = :f"
            ),
            {"f": firm_id},
        ).mappings().all()

    values: dict[str, float | None] = {key: None for key in (
        "headcount", "attorney_to_staff_ratio", "avg_attorney_salary",
        "comp_concentration_pct", "pct_contractors", "total_cases",
        "settlement_rate", "drop_rate", "practice_concentration_pct",
        "software_tool_count", "diligence_completeness_pct", "office_count",
        "avg_settlement", "avg_net_fee", "avg_fee_pct", "avg_time_to_settle",
    )}

    # --- personnel ---
    if census:
        headcount = len(census)
        values["headcount"] = headcount

        attorneys = [
            r for r in census
            if _is_attorney(r["dept_title"]) or _is_attorney(r["function_role"])
        ]
        staff = headcount - len(attorneys)
        if staff > 0 and attorneys:
            values["attorney_to_staff_ratio"] = round(len(attorneys) / staff, 2)

        salaries = [r["annual_salary"] for r in attorneys if r["annual_salary"]]
        if salaries:
            values["avg_attorney_salary"] = round(sum(salaries) / len(salaries))

        comps = [r["total_annual_comp"] for r in census if r["total_annual_comp"]]
        if comps and sum(comps) > 0:
            values["comp_concentration_pct"] = round(100 * max(comps) / sum(comps), 1)

        contractors = sum(
            1 for r in census
            if r["employment_status"] and (
                "1099" in r["employment_status"]
                or "contract" in r["employment_status"].lower()
            )
        )
        values["pct_contractors"] = round(100 * contractors / headcount, 1)

    # --- cases ---
    dominant_practice = None
    if cases:
        values["total_cases"] = len(cases)

        dispositions = [c["disposition_code"] for c in cases if c["disposition_code"]]
        if dispositions:
            settled = sum(1 for d in dispositions if d == "SET")
            dropped = sum(1 for d in dispositions if d == "DRP")
            values["settlement_rate"] = round(100 * settled / len(dispositions), 1)
            values["drop_rate"] = round(100 * dropped / len(dispositions), 1)

        by_type: dict[str, int] = {}
        for c in cases:
            key = c["case_type"] or "Unknown"
            by_type[key] = by_type.get(key, 0) + 1
        dominant_practice, top = max(by_type.items(), key=lambda kv: kv[1])
        values["practice_concentration_pct"] = round(100 * top / len(cases), 1)

    # --- technology ---
    if tool_count:
        values["software_tool_count"] = tool_count

    # --- diligence ---
    if dd:
        values["diligence_completeness_pct"] = round(100 * sum(dd) / len(dd), 1)

    # --- case economics (settled-case files like Nugent's) ---
    if econ:
        settlements = [r["gross_settlement"] for r in econ if r["gross_settlement"]]
        fees = [r["net_fee"] for r in econ if r["net_fee"]]
        fee_pcts = [r["fee_pct"] for r in econ if r["fee_pct"]]
        durations = [r["duration_days"] for r in econ if r["duration_days"]]

        if settlements:
            values["avg_settlement"] = round(sum(settlements) / len(settlements))
        if fees:
            values["avg_net_fee"] = round(sum(fees) / len(fees))
        if fee_pcts:
            values["avg_fee_pct"] = round(sum(fee_pcts) / len(fee_pcts), 1)
        if durations:
            values["avg_time_to_settle"] = round(sum(durations) / len(durations))

        # Fill case-count / practice mix from here if the ledger didn't.
        if values["total_cases"] is None:
            values["total_cases"] = len(econ)
        if values["practice_concentration_pct"] is None:
            by_type: dict[str, int] = {}
            for r in econ:
                key = r["injury_type"] or "Unknown"
                by_type[key] = by_type.get(key, 0) + 1
            top_practice, top_n = max(by_type.items(), key=lambda kv: kv[1])
            values["practice_concentration_pct"] = round(100 * top_n / len(econ), 1)
            dominant_practice = dominant_practice or top_practice

    # office_count intentionally stays None — no seller file feeds it yet.
    return values, dominant_practice


def _is_attorney(title: str | None) -> bool:
    return bool(title) and any(word in title.lower() for word in _ATTORNEY_WORDS)
