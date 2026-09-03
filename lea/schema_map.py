"""Source-column vocabulary per target table, plus tables missing from the DBML.

MAPPED_TOKENS records which normalised source headers each recipe knowingly
consumes. Anything in a file outside this vocabulary is reported as an unmapped
column — that report is the schema-drift alarm, and it is the main reason a
seller changing their reporting shows up as a notice rather than as silent
data loss.
"""

from __future__ import annotations

MAPPED_TOKENS: dict[str, set[str]] = {
    "per_employee_census": {
        "", "number", "employee", "dept_title", "function", "division",
        "location", "in_place_remote", "status", "approx_start_date",
        "compensation_method", "annual_salary", "annual_bonus",
        "total_annual_compensation", "other_compensation_notes",
        "retirement_benefits",
    },
    "cas_case_ledger": {"opened", "party_name", "case", "case_type", "class", "role"},
    "tec_tools": {"software_application", "description_function"},
    "cas_top_25_cases": {
        "", "number", "plaintiff", "gross_settlement", "net_fee_to_firm", "state",
        "practice_area", "responsible_attorney_staff", "case_acquisition_method",
        "time_from_intake_to_settle", "stage_reached", "case_costs_advanced",
        "referral_fees", "insurance_company", "county",
    },
    "dd_responses": {
        "topic", "question_to_seller", "seller_answer", "lea_follow_up",
        "seller_follow_up", "status",
    },
    "cas_closed_cases": {"case_type", "no", "amount"},
}


def mapped_tokens(target_table: str) -> set[str]:
    return MAPPED_TOKENS.get(target_table, set())


# Tables the seller data requires but the DBML does not yet declare.
# Paste these into `Table firms {.go` to make the diagram authoritative again:
#
#   cas_case_ledger  — the DBML has only the aggregated cas_closed_cases, but
#                      sellers send case-level ledgers. Aggregates are derived
#                      from this table rather than trusted as an input.
#   dd_responses     — the diligence questionnaire has no home in the schema,
#                      yet answer completeness is a real firm-level risk signal.
EXTRA_TABLES_DDL = {
    "sqlite": """
CREATE TABLE IF NOT EXISTS cas_case_ledger (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    firm_id          TEXT REFERENCES firms(firm_id),
    case_number      TEXT,
    party_name_hash  TEXT,
    case_type        TEXT,
    disposition_code TEXT,
    party_role       TEXT,
    opened_date      DATE,
    period_year      INTEGER,
    load_id          TEXT,
    source_file      TEXT,
    ingested_at_utc  TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_cas_case_ledger
    ON cas_case_ledger (firm_id, case_number);

CREATE TABLE IF NOT EXISTS dd_responses (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    firm_id       TEXT REFERENCES firms(firm_id),
    topic         TEXT,
    question      TEXT,
    seller_answer TEXT,
    status        TEXT,
    is_answered   INTEGER,
    load_id       TEXT,
    source_file   TEXT,
    ingested_at_utc TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_dd_responses
    ON dd_responses (firm_id, question);

CREATE TABLE IF NOT EXISTS ref_disposition_code (
    code        TEXT PRIMARY KEY,
    label       TEXT,
    is_settled  INTEGER,
    description TEXT
);
""",
}
EXTRA_TABLES_DDL["mssql"] = (
    EXTRA_TABLES_DDL["sqlite"]
    .replace("INTEGER PRIMARY KEY AUTOINCREMENT", "INT IDENTITY(1,1) PRIMARY KEY")
    .replace("TEXT PRIMARY KEY", "NVARCHAR(16) NOT NULL PRIMARY KEY")
    .replace("TEXT", "NVARCHAR(400)")
    .replace("INTEGER", "INT")
)
EXTRA_TABLES_DDL["postgres"] = EXTRA_TABLES_DDL["sqlite"].replace(
    "INTEGER PRIMARY KEY AUTOINCREMENT",
    "INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY",
)

# The disposition codes are undocumented in the source files. These readings are
# inferred from context and MUST be confirmed with the seller before any
# settlement-rate metric built on them is trusted.
DISPOSITION_CODES = [
    ("SET", "Settled", 1, "Case resolved with a settlement"),
    ("DRP", "Dropped", 0, "Case closed without recovery"),
    ("SUB", "Substituted out", 0, "Transferred to another firm"),
    ("INI", "Initial / intake", 0, "Opened, not yet progressed — INFERRED"),
    ("LIT", "In litigation", 0, "Suit filed — INFERRED"),
    ("ARB", "Arbitration", 0, "Resolved in arbitration — INFERRED"),
    ("L-P", "Litigation pending", 0, "INFERRED — confirm with seller"),
    ("I-P", "Intake pending", 0, "INFERRED — confirm with seller"),
    ("A-P", "Arbitration pending", 0, "INFERRED — confirm with seller"),
    ("SRL", "Self-represented / released", 0, "INFERRED — confirm with seller"),
]
