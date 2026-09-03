"""Ask-the-data: safe natural-language questions answered by generated SQL.

The LLM writes a single read-only SELECT over the case table; we validate it
hard (SELECT only, only cas_economics, no writes, enforced LIMIT), run it, and
the LLM phrases the result. The generated SQL and the result rows are always
returned so the analyst can see exactly what was computed — no black box, and
the model never invents a number (every figure comes from the query result).

For distribution / "by range" questions the model is told to bucket the measure
into bands with CASE WHEN, so answers come back segmented by range.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.engine import Engine

from . import llm

TABLE = "cas_economics"

_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|attach|detach|pragma|replace|"
    r"truncate|grant|revoke|vacuum|merge|copy|into)\b",
    re.IGNORECASE,
)
_TABLE_REF = re.compile(r"\b(?:from|join)\s+([a-zA-Z_][\w.]*)", re.IGNORECASE)


@dataclass
class DataAnswer:
    question: str
    sql: str | None = None
    rows: list[dict] = field(default_factory=list)
    answer: str = ""
    error: str | None = None


def _schema_card(engine: Engine) -> str:
    def distinct(col: str, limit: int = 25) -> list[str]:
        with engine.connect() as conn:
            return [
                r[0] for r in conn.execute(
                    text(f"SELECT DISTINCT {col} FROM {TABLE} "
                         f"WHERE {col} IS NOT NULL ORDER BY {col} LIMIT {limit}")
                ).all()
            ]

    injuries = distinct("injury_type")
    states = distinct("state")
    return (
        f"Table {TABLE} — one row per settled/closed legal case.\n"
        "Columns:\n"
        "  case_ref (text) — case/file number\n"
        "  attorney (text) — handling attorney name\n"
        f"  injury_type (text) — practice area; values: {injuries}\n"
        "  city (text) — county or city (free text)\n"
        f"  state (text) — values: {states}\n"
        "  gross_settlement (number, USD) — settlement amount\n"
        "  net_fee (number, USD) — fee earned by the firm\n"
        "  fee_pct (number) — fee as a percent of gross settlement\n"
        "  duration_days (int) — days from case open to settlement\n"
        "  settled_year (int) — year the case settled\n"
    )


def generate_sql(question: str, engine: Engine) -> str | None:
    prompt = (
        "Write ONE read-only SQL SELECT (portable across SQLite and Postgres) "
        "that answers the question about settled legal cases.\n\n"
        f"{_schema_card(engine)}\n"
        "Rules:\n"
        f"- SELECT only. Reference only the {TABLE} table. No writes or DDL.\n"
        "- Portable SQL only: COUNT, SUM, AVG, MIN, MAX, ROUND, CASE WHEN, "
        "GROUP BY, ORDER BY, LIMIT. Do NOT use percentile/window functions or "
        "any DB-specific syntax.\n"
        "- For 'distribution', 'how many', 'breakdown', or 'by range' questions, "
        "bucket the relevant amount into ranges using CASE WHEN and GROUP BY the "
        "range, ordered from low to high.\n"
        "- Round money to whole numbers. Always end with LIMIT 200 or less.\n"
        "Return ONLY the SQL — no prose, no markdown fences.\n\n"
        f"Question: {question}"
    )
    # Generous budget: gemini-flash-latest spends output tokens on internal
    # reasoning, so a small cap truncates longer bucketing (CASE WHEN) queries.
    sql = llm.complete(prompt, max_tokens=2000)
    if not sql:
        return None
    # strip any accidental code fences
    sql = re.sub(r"^```[a-z]*|```$", "", sql.strip(), flags=re.IGNORECASE).strip()
    return sql


def validate(sql: str) -> tuple[bool, str]:
    """Return (ok, reason). Rejects anything that isn't a single safe SELECT."""
    s = sql.strip().rstrip(";").strip()
    if not s:
        return False, "empty query"
    if ";" in s:
        return False, "multiple statements are not allowed"
    low = s.lower()
    if not (low.startswith("select") or low.startswith("with")):
        return False, "only SELECT queries are allowed"
    if _FORBIDDEN.search(s):
        return False, "the query contains a write/DDL keyword"
    for tbl in _TABLE_REF.findall(s):
        if tbl.lower() != TABLE:
            return False, f"only the {TABLE} table may be queried (found '{tbl}')"
    return True, "ok"


def _with_limit(sql: str, cap: int = 200) -> str:
    return sql if re.search(r"\blimit\b", sql, re.IGNORECASE) else f"{sql}\nLIMIT {cap}"


def run_readonly(engine: Engine, sql: str) -> list[dict]:
    from decimal import Decimal
    with engine.connect() as conn:
        result = conn.execute(text(_with_limit(sql)))
        cols = list(result.keys())
        out = []
        for row in result.fetchall():
            # Convert Postgres Decimals to float; leave ints/text as-is.
            out.append({c: (float(v) if isinstance(v, Decimal) else v)
                        for c, v in zip(cols, row)})
        return out


def ask(question: str, engine: Engine) -> DataAnswer:
    result = DataAnswer(question=question)
    if not llm.is_configured():
        result.error = "Turn on an AI provider in Settings to ask free-form questions."
        return result

    sql = generate_sql(question, engine)
    if not sql:
        result.error = "The AI could not generate a query (try rephrasing)."
        return result
    result.sql = sql

    ok, reason = validate(sql)
    if not ok:
        result.error = f"Generated query was rejected for safety: {reason}."
        return result

    try:
        result.rows = run_readonly(engine, sql)
    except Exception as exc:
        result.error = f"Query failed to run: {str(exc).splitlines()[0][:160]}"
        return result

    result.answer = _phrase(question, result.rows)
    return result


def _phrase(question: str, rows: list[dict]) -> str:
    if not rows:
        return "No matching cases were found for that question."
    payload = json.dumps(rows[:60], default=str)
    prompt = (
        "Answer the user's question in 1-3 plain sentences using ONLY these "
        "query results. Do not invent or alter any number. If the results are "
        "ranges/buckets, describe the distribution.\n\n"
        f"Question: {question}\nResults (JSON): {payload}"
    )
    text_out = llm.complete(prompt, max_tokens=800)
    if not text_out:
        # Fall back to a plain statement of the first row(s).
        return "Results returned below." if len(rows) > 1 else str(rows[0])
    return text_out.strip()
