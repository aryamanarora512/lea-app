"""Aggregations for the case dashboard — deterministic SQL, firm-aware.

Every figure on the dashboard comes from these queries over cas_economics, so
the visuals are exact, not model-generated. All are filterable by firm_id
(None = all firms), which is why firm_id must be its own column: two firms can
share a case_ref, and (firm_id, case_ref) keeps them distinct.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.engine import Engine


def _rows(engine: Engine, sql: str, params: dict) -> list[dict]:
    with engine.connect() as conn:
        result = conn.execute(text(sql), params)
        cols = list(result.keys())
        return [
            {c: (float(v) if isinstance(v, Decimal) else v) for c, v in zip(cols, r)}
            for r in result.fetchall()
        ]


def _firm_clause(firm_id: str | None) -> tuple[str, dict]:
    if firm_id and firm_id != "All firms":
        return "firm_id = :f", {"f": firm_id}
    return "1=1", {}


def firm_options(engine: Engine) -> list[tuple[str, str]]:
    """(firm_id, display_name) for firms present in the case data."""
    ids = [r["firm_id"] for r in _rows(
        engine, "SELECT DISTINCT firm_id FROM cas_economics ORDER BY firm_id", {})]
    names = {r["firm_id"]: r["firm_name"] for r in _rows(
        engine, "SELECT firm_id, firm_name FROM firms", {})}
    from .cases import SAMPLE_FIRMS
    names.update(dict(SAMPLE_FIRMS))
    return [(fid, f"{fid} — {names.get(fid, 'Unknown')}") for fid in ids]


def totals(engine: Engine, firm_id: str | None) -> dict:
    where, params = _firm_clause(firm_id)
    rows = _rows(engine, f"""
        SELECT COUNT(*) AS n_cases,
               ROUND(SUM(gross_settlement)) AS total_settlement,
               ROUND(SUM(net_fee)) AS total_fee,
               ROUND(AVG(gross_settlement)) AS avg_settlement,
               ROUND(AVG(duration_days)) AS avg_days
        FROM cas_economics WHERE {where}
    """, params)
    return rows[0] if rows else {}


def by_year(engine: Engine, firm_id: str | None) -> list[dict]:
    where, params = _firm_clause(firm_id)
    return _rows(engine, f"""
        SELECT settled_year AS year, COUNT(*) AS cases,
               ROUND(SUM(gross_settlement)) AS total_settlement,
               ROUND(SUM(net_fee)) AS total_fee
        FROM cas_economics WHERE {where} AND settled_year IS NOT NULL
        GROUP BY settled_year ORDER BY settled_year
    """, params)


def by_practice(engine: Engine, firm_id: str | None) -> list[dict]:
    where, params = _firm_clause(firm_id)
    return _rows(engine, f"""
        SELECT injury_type AS practice, COUNT(*) AS cases,
               ROUND(SUM(gross_settlement)) AS total_settlement,
               ROUND(AVG(gross_settlement)) AS avg_settlement
        FROM cas_economics WHERE {where} AND injury_type IS NOT NULL
        GROUP BY injury_type ORDER BY total_settlement DESC
    """, params)


def by_attorney(engine: Engine, firm_id: str | None, limit: int = 10) -> list[dict]:
    where, params = _firm_clause(firm_id)
    params = {**params, "lim": limit}
    return _rows(engine, f"""
        SELECT attorney, COUNT(*) AS cases,
               ROUND(SUM(net_fee)) AS total_fee,
               ROUND(SUM(gross_settlement)) AS total_settlement,
               ROUND(AVG(gross_settlement)) AS avg_settlement
        FROM cas_economics WHERE {where} AND attorney IS NOT NULL
        GROUP BY attorney ORDER BY total_fee DESC LIMIT :lim
    """, params)


def by_county(engine: Engine, firm_id: str | None, limit: int = 12) -> list[dict]:
    where, params = _firm_clause(firm_id)
    params = {**params, "lim": limit}
    return _rows(engine, f"""
        SELECT city AS county, COUNT(*) AS cases,
               ROUND(SUM(gross_settlement)) AS total_settlement
        FROM cas_economics WHERE {where} AND city IS NOT NULL
        GROUP BY city ORDER BY total_settlement DESC LIMIT :lim
    """, params)


def largest_cases(engine: Engine, firm_id: str | None, limit: int = 12) -> list[dict]:
    where, params = _firm_clause(firm_id)
    params = {**params, "lim": limit}
    return _rows(engine, f"""
        SELECT case_ref, injury_type, city, attorney,
               ROUND(gross_settlement) AS gross_settlement,
               ROUND(net_fee) AS net_fee, settled_year
        FROM cas_economics WHERE {where}
        ORDER BY gross_settlement DESC LIMIT :lim
    """, params)
