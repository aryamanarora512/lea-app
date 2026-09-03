"""Recipes for the file shapes seen in seller data so far.

Each recipe encodes what we learned by reading a real workbook. The data-quality
checks are not hypothetical: every one of them fires on the sample files.
"""

from __future__ import annotations

import hashlib
import os
import re
from typing import Any

from ..excel import (
    SheetProbe,
    looks_like_total_row,
    normalise,
    read_rows,
    to_date,
    to_int,
    to_number,
    to_text,
)
from . import Finding, ParseResult, has_tokens, register


def _column_index(header: list[str]) -> dict[str, int]:
    """Map normalised header token -> column position."""
    return {normalise(h): i for i, h in enumerate(header) if h}


def _get(row: list[Any], index: dict[str, int], token: str) -> Any:
    position = index.get(token)
    if position is None or position >= len(row):
        return None
    return row[position]


def pseudonymise(value: str | None) -> str | None:
    """Salted hash for personal names.

    Seller files contain plaintiff and employee names. They are not needed for
    any statistic we compute, but dropping them entirely would break row
    identity across reloads, so we keep a stable salted digest instead. The
    salt lives outside the codebase so the published version cannot be used to
    reverse the hashes.
    """
    if not value:
        return None
    salt = os.environ.get("LEA_PII_SALT", "")
    return hashlib.sha256(f"{salt}|{value.strip().lower()}".encode()).hexdigest()[:24]


# --------------------------------------------------------------------------
# Employee census
# --------------------------------------------------------------------------


class EmployeeCensusRecipe:
    name = "employee_census"
    description = "Headcount roster with compensation (one row per employee)"
    target_table = "per_employee_census"

    def matches(self, probe: SheetProbe) -> bool:
        return has_tokens(probe, "employee", "division") and (
            has_tokens(probe, "annual_salary") or has_tokens(probe, "compensation_method")
        )

    def parse(self, path: str, probe: SheetProbe, firm_id: str) -> ParseResult:
        header, data = read_rows(path, probe.sheet_name, probe.header_row)
        index = _column_index(header)
        result = ParseResult(target_table=self.target_table, rows_read=len(data))

        for offset, raw in enumerate(data):
            row_number = probe.header_row + offset + 2  # 1-based, as shown in Excel

            if looks_like_total_row(raw, label_columns=4):
                result.findings.append(
                    Finding(
                        "totals_row_excluded",
                        "info",
                        "Trailing totals row detected and excluded from the load.",
                        row_number,
                    )
                )
                continue

            name = to_text(_get(raw, index, "employee"))
            if not name:
                continue

            # A trailing asterisk marks a footnote above the header ("left the
            # firm on ...", "salary copied in"). Keep the flag, clean the name.
            has_footnote = name.endswith("*")
            if has_footnote:
                name = name.rstrip("* ")
                result.findings.append(
                    Finding(
                        "footnote_marker",
                        "info",
                        f"'{name}' carries a footnote marker — check the note above "
                        "the header; it often means departed or adjusted comp.",
                        row_number,
                        "full_name",
                    )
                )

            salary = to_number(_get(raw, index, "annual_salary"))
            bonus = to_number(_get(raw, index, "annual_bonus"))
            total = to_number(_get(raw, index, "total_annual_compensation"))
            comp_method = to_text(_get(raw, index, "compensation_method"))
            status = to_text(_get(raw, index, "status"))
            start_date, is_placeholder = to_date(_get(raw, index, "approx_start_date"))

            # Footing check: the firm's own arithmetic should reconcile.
            if total is not None and (salary is not None or bonus is not None):
                expected = (salary or 0) + (bonus or 0)
                if abs(expected - total) > 0.01:
                    result.findings.append(
                        Finding(
                            "comp_footing_mismatch",
                            "warning",
                            f"salary + bonus = {expected:,.2f} but total reads "
                            f"{total:,.2f} (difference {total - expected:,.2f}).",
                            row_number,
                            "total_annual_comp",
                        )
                    )
            elif total is None and (salary is not None or bonus is not None):
                result.findings.append(
                    Finding(
                        "comp_total_missing",
                        "warning",
                        "Compensation components present but total is blank.",
                        row_number,
                        "total_annual_comp",
                    )
                )

            if comp_method and comp_method.lower().startswith("hourly") and salary:
                result.findings.append(
                    Finding(
                        "hourly_with_annual_salary",
                        "warning",
                        f"Marked '{comp_method}' but carries an annual salary of "
                        f"{salary:,.0f} — confirm whether this is annualised.",
                        row_number,
                        "comp_method",
                    )
                )

            if is_placeholder:
                result.findings.append(
                    Finding(
                        "placeholder_start_date",
                        "warning",
                        f"Start date {start_date} falls on 1 January — usually a "
                        "placeholder, not a real hire date. Tenure will be wrong.",
                        row_number,
                        "start_date",
                    )
                )

            result.rows.append(
                {
                    "firm_id": firm_id,
                    "employee_number": to_int(_get(raw, index, "number"))
                    or to_int(_get(raw, index, ""))
                    or offset + 1,
                    "full_name": pseudonymise(name),
                    "dept_title": to_text(_get(raw, index, "dept_title")),
                    "function_role": to_text(_get(raw, index, "function")),
                    "division": to_text(_get(raw, index, "division")),
                    "employment_status": status,
                    "start_date": start_date.isoformat() if start_date else None,
                    "comp_method": comp_method,
                    "annual_salary": salary,
                    "annual_bonus": bonus,
                    "total_annual_comp": total,
                    "notes": to_text(_get(raw, index, "other_compensation_notes")),
                    "is_active": _derive_is_active(status, has_footnote),
                }
            )

        _check_unmapped(header, index, result, self.target_table)
        return result


def _derive_is_active(status: str | None, has_footnote: bool) -> int | None:
    """is_active exists in the schema but not in any seller file — derive it."""
    if has_footnote:
        return 0  # footnotes on this sheet flag departures
    if not status:
        return None
    lowered = status.lower()
    if any(word in lowered for word in ("term", "left", "former", "inactive")):
        return 0
    return 1


# --------------------------------------------------------------------------
# Case ledger (one row per case)
# --------------------------------------------------------------------------


class CaseLedgerRecipe:
    name = "case_ledger"
    description = "Case-level ledger, one tab per case type"
    target_table = "cas_case_ledger"

    def matches(self, probe: SheetProbe) -> bool:
        return has_tokens(probe, "opened", "case", "class")

    def parse(self, path: str, probe: SheetProbe, firm_id: str) -> ParseResult:
        header, data = read_rows(path, probe.sheet_name, probe.header_row)
        index = _column_index(header)
        result = ParseResult(target_table=self.target_table, rows_read=len(data))

        # The sheet tab name is itself a dimension. Where the in-row value
        # disagrees with the tab, the tab wins and we record the conflict.
        tab_case_type = probe.sheet_name.strip().upper()

        for offset, raw in enumerate(data):
            row_number = probe.header_row + offset + 2

            case_number = to_text(_get(raw, index, "case"))
            if not case_number:
                continue

            row_case_type = to_text(_get(raw, index, "case_type"))
            if row_case_type and row_case_type.strip().upper() != tab_case_type:
                result.findings.append(
                    Finding(
                        "case_type_tab_conflict",
                        "warning",
                        f"Row says '{row_case_type}' but the tab is "
                        f"'{tab_case_type}'. Using the tab.",
                        row_number,
                        "case_type",
                    )
                )

            opened, _ = to_date(_get(raw, index, "opened"))
            if opened is None:
                result.findings.append(
                    Finding(
                        "unparseable_open_date",
                        "warning",
                        f"Could not parse open date "
                        f"{_get(raw, index, 'opened')!r}.",
                        row_number,
                        "opened_date",
                    )
                )

            disposition = to_text(_get(raw, index, "class"))
            if not disposition:
                result.findings.append(
                    Finding(
                        "missing_disposition",
                        "warning",
                        "Disposition code is blank — the case cannot be counted as "
                        "settled, dropped, or referred.",
                        row_number,
                        "disposition_code",
                    )
                )

            result.rows.append(
                {
                    "firm_id": firm_id,
                    "case_number": case_number,
                    "party_name_hash": pseudonymise(to_text(_get(raw, index, "party_name"))),
                    "case_type": tab_case_type,
                    "disposition_code": disposition,
                    "party_role": to_text(_get(raw, index, "role")),
                    "opened_date": opened.isoformat() if opened else None,
                    "period_year": opened.year if opened else None,
                }
            )

        # The file is named "closed cases" but carries no close date, so
        # duration and settlement-year attribution are impossible from it.
        if "closed_date" not in index and "settled" not in " ".join(index):
            result.findings.append(
                Finding(
                    "no_close_date_column",
                    "warning",
                    "This ledger has an open date but no close/settle date. Case "
                    "duration and settlement-year metrics cannot be derived from "
                    "it — request a close date from the seller.",
                )
            )

        _check_unmapped(header, index, result, self.target_table)
        return result


# --------------------------------------------------------------------------
# Software tools
# --------------------------------------------------------------------------

_TOOL_CATEGORY = re.compile(r"^\s*(security|storage|accounting|legal)\s*:", re.I)


class SoftwareToolsRecipe:
    name = "software_tools"
    description = "Application inventory (name + description)"
    target_table = "tec_tools"

    def matches(self, probe: SheetProbe) -> bool:
        return has_tokens(probe, "software_application") or has_tokens(
            probe, "software", "description_function"
        )

    def parse(self, path: str, probe: SheetProbe, firm_id: str) -> ParseResult:
        header, data = read_rows(path, probe.sheet_name, probe.header_row)
        index = _column_index(header)
        result = ParseResult(target_table=self.target_table, rows_read=len(data))

        name_col = index.get("software_application", 0)
        desc_col = index.get("description_function", 1)

        for offset, raw in enumerate(data):
            row_number = probe.header_row + offset + 2
            tool_name = to_text(raw[name_col] if name_col < len(raw) else None)
            if not tool_name:
                continue

            description = to_text(raw[desc_col] if desc_col < len(raw) else None)

            # Analyst notes-to-self leak into the value column
            # ("Mimecast ask Charlie", "Anti-Virus will secure name").
            if re.search(r"\b(ask|tbc|tbd|confirm|check)\b", tool_name, re.I):
                result.findings.append(
                    Finding(
                        "note_embedded_in_value",
                        "warning",
                        f"Tool name '{tool_name}' looks like it contains an "
                        "analyst note rather than a clean product name.",
                        row_number,
                        "tool_name",
                    )
                )

            category = None
            if description:
                match = _TOOL_CATEGORY.match(description)
                if match:
                    category = match.group(1).title()

            result.rows.append(
                {
                    "firm_id": firm_id,
                    "tool_name": tool_name,
                    "category": category,
                    "notes": description,
                }
            )

        # tec_tools has nine attributes; this file supplies two. Recording it
        # as expected sparsity stops completeness monitoring from alerting on
        # fields the source structurally cannot provide.
        result.findings.append(
            Finding(
                "structurally_sparse_source",
                "info",
                "This source supplies tool name and description only. vendor, "
                "monthly_cost, contract_expiry, auto_renews, primary_users, "
                "integration_status, and satisfaction_score stay NULL by design.",
            )
        )
        return result


# --------------------------------------------------------------------------
# Top 25 cases
# --------------------------------------------------------------------------


class Top25CasesRecipe:
    name = "top_25_cases"
    description = "Largest settlements for a year (one tab per year)"
    target_table = "cas_top_25_cases"

    def matches(self, probe: SheetProbe) -> bool:
        return has_tokens(probe, "gross_settlement", "net_fee_to_firm")

    def parse(self, path: str, probe: SheetProbe, firm_id: str) -> ParseResult:
        header, data = read_rows(path, probe.sheet_name, probe.header_row)
        index = _column_index(header)
        result = ParseResult(target_table=self.target_table, rows_read=len(data))

        year = _year_from_sheet_name(probe.sheet_name)
        snapshot = f"{year}-12-31" if year else None

        for offset, raw in enumerate(data):
            row_number = probe.header_row + offset + 2
            gross = to_number(_get(raw, index, "gross_settlement"))
            net_fee = to_number(_get(raw, index, "net_fee_to_firm"))

            if gross is None and net_fee is None:
                continue  # unfilled template row

            if gross and net_fee and net_fee > gross:
                result.findings.append(
                    Finding(
                        "fee_exceeds_settlement",
                        "error",
                        f"Net fee {net_fee:,.0f} exceeds gross settlement "
                        f"{gross:,.0f} — impossible.",
                        row_number,
                        "net_fee",
                    )
                )

            result.rows.append(
                {
                    "firm_id": firm_id,
                    "snapshot_date": snapshot,
                    "rank": to_int(_get(raw, index, "number")) or offset + 1,
                    "practice_area": to_text(_get(raw, index, "practice_area")),
                    "county": to_text(_get(raw, index, "county")),
                    "supervising_attorney": pseudonymise(
                        to_text(_get(raw, index, "responsible_attorney_staff"))
                    ),
                    "gross_settlement": gross,
                    "net_fee": net_fee,
                    "case_costs_advanced": to_number(
                        _get(raw, index, "case_costs_advanced")
                    ),
                    "case_duration_days": to_int(
                        _get(raw, index, "time_from_intake_to_settle")
                    ),
                    "insurance_carrier": to_text(_get(raw, index, "insurance_company")),
                }
            )

        if not result.rows:
            result.findings.append(
                Finding(
                    "empty_template",
                    "warning",
                    f"Tab '{probe.sheet_name}' is an unfilled template — the rank "
                    "column is numbered but every data cell is blank. Nothing to "
                    "load; request the completed file from the seller.",
                )
            )

        _check_unmapped(header, index, result, self.target_table)
        return result


def _year_from_sheet_name(sheet_name: str) -> int | None:
    match = re.search(r"(19|20)\d{2}", sheet_name)
    return int(match.group(0)) if match else None


# --------------------------------------------------------------------------
# Diligence questionnaire
# --------------------------------------------------------------------------

_AWAITING = re.compile(r"awaiting|pending|tbd|n/?a", re.I)


class DiligenceQuestionsRecipe:
    name = "diligence_questions"
    description = "Commercial DD question-and-answer log"
    target_table = "dd_responses"

    def matches(self, probe: SheetProbe) -> bool:
        return has_tokens(probe, "topic", "question_to_seller")

    def parse(self, path: str, probe: SheetProbe, firm_id: str) -> ParseResult:
        header, data = read_rows(path, probe.sheet_name, probe.header_row)
        index = _column_index(header)
        result = ParseResult(target_table=self.target_table, rows_read=len(data))

        answered = 0
        for offset, raw in enumerate(data):
            question = to_text(_get(raw, index, "question_to_seller"))
            if not question:
                continue

            answer = to_text(_get(raw, index, "seller_answer"))
            is_answered = bool(answer) and not _AWAITING.match(answer)
            answered += int(is_answered)

            result.rows.append(
                {
                    "firm_id": firm_id,
                    "topic": to_text(_get(raw, index, "topic")),
                    "question": question,
                    "seller_answer": answer,
                    "status": to_text(_get(raw, index, "status")),
                    "is_answered": int(is_answered),
                }
            )

        # Diligence completeness is a genuine firm-level signal: a target that
        # has answered 40% of questions is a different risk from one at 95%.
        if result.rows:
            pct = 100 * answered / len(result.rows)
            result.findings.append(
                Finding(
                    "diligence_completeness",
                    "info" if pct >= 70 else "warning",
                    f"{answered} of {len(result.rows)} questions answered "
                    f"({pct:.0f}%).",
                )
            )
        return result


# --------------------------------------------------------------------------


def _check_unmapped(
    header: list[str], index: dict[str, int], result: ParseResult, target: str
) -> None:
    """Report source columns the recipe ignored — the schema-drift alarm.

    A new column appearing in a seller's file is the signal that their
    reporting changed. Silently dropping it is how pipelines rot.
    """
    from ..schema_map import mapped_tokens

    known = mapped_tokens(target)
    unmapped = [h for h in header if h and normalise(h) not in known]
    if unmapped:
        result.findings.append(
            Finding(
                "unmapped_source_columns",
                "info",
                "Columns present in the file but not loaded: "
                + ", ".join(repr(u) for u in unmapped)
                + ". Add them to the schema if they matter.",
            )
        )


for _recipe in (
    EmployeeCensusRecipe(),
    CaseLedgerRecipe(),
    SoftwareToolsRecipe(),
    Top25CasesRecipe(),
    DiligenceQuestionsRecipe(),
):
    register(_recipe)
