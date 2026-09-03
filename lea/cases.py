"""Case-economics data: schema, synthetic generation, and query layer.

This backs the attorney case explorer. The real data for it — settlement value,
net fee, injury type, city, coverage — is exactly the case-level economics on
the data wishlist and is NOT in the sample files, so a synthetic book is
generated to demonstrate the feature. Values are invented from injury- and
coverage-dependent distributions that resemble a mid-market personal-injury
practice; they are not real cases.

The query layer is deterministic. The LLM (see nlquery.py) only chooses which
filters and measure to apply; the numbers on every chart come from here.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.engine import Engine

# Nugent-flavoured synthetic data: personal-injury firm, Georgia-heavy, MVA-heavy.
INJURY_TYPES = [
    "Auto (MVA)", "Premises Liability", "Medical Malpractice",
    "Dog Bite", "Product Liability", "Workers' Comp",
]
CITIES = [
    ("Fulton", "GA"), ("Gwinnett", "GA"), ("Dekalb", "GA"), ("Cobb", "GA"),
    ("Clayton", "GA"), ("Chatham", "GA"), ("Richmond", "GA"), ("Muscogee", "GA"),
]
# Synthetic attorney names (invented — no real people).
ATTORNEYS = [
    "S. Hendrickson", "R. Deutschman", "J. Kirtlink", "A. Wigley", "D. Mullins",
    "M. Clements", "C. Adams", "W. Hammill", "A. Josey", "B. Valentine",
]
COVERAGE_BANDS = ["15/30 (minimum)", "50/100", "100/300", "250/500", "1M+ (excess)"]

# Median gross settlement by injury type (USD) and the lognormal spread.
_INJURY_BASE = {
    "Auto (MVA)": (18_000, 0.95),
    "Premises Liability": (40_000, 0.95),
    "Medical Malpractice": (180_000, 1.05),
    "Dog Bite": (24_000, 0.85),
    "Product Liability": (85_000, 1.0),
    "Workers' Comp": (30_000, 0.8),
}
# A policy limit effectively caps most settlements; this is the soft ceiling.
_COVERAGE_CAP = {
    "15/30 (minimum)": 30_000, "50/100": 100_000, "100/300": 300_000,
    "250/500": 500_000, "1M+ (excess)": 2_000_000,
}
MEASURES = {
    "gross_settlement": "Gross settlement",
    "net_fee": "Net fee to firm",
    "fee_pct": "Fee % of gross",
    "duration_days": "Time to settle (days)",
}


def cases_ddl(dialect: str = "sqlite") -> str:
    number = "REAL" if dialect == "sqlite" else "NUMERIC(18,2)"
    ident = ("INTEGER PRIMARY KEY AUTOINCREMENT" if dialect == "sqlite"
             else "INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY" if dialect == "postgres"
             else "INT IDENTITY(1,1) PRIMARY KEY")
    tt = "TEXT" if dialect != "mssql" else "NVARCHAR(200)"
    return f"""
CREATE TABLE IF NOT EXISTS cas_economics (
    id              {ident},
    firm_id         {tt},
    case_ref        {tt},
    injury_type     {tt},
    city            {tt},
    state           {tt},
    attorney        {tt},
    coverage_band   {tt},
    policy_limit    {number},
    gross_settlement {number},
    net_fee         {number},
    fee_pct         {number},
    duration_days   INTEGER,
    settled_year    INTEGER,
    load_id         {tt},
    source_file     {tt},
    ingested_at_utc {tt}
);
CREATE INDEX IF NOT EXISTS ix_cas_econ_filter
    ON cas_economics (injury_type, city, coverage_band);
CREATE UNIQUE INDEX IF NOT EXISTS ux_cas_economics
    ON cas_economics (firm_id, case_ref);
"""


# A few synthetic firms so firm_id is meaningful, and case_refs deliberately
# overlap across them to demonstrate that (firm_id, case_ref) keeps them distinct.
SAMPLE_FIRMS = [("9001", "Northgate Injury Partners"),
                ("9002", "Vale & Rourke"),
                ("9003", "Cardinal Trial Group")]


def generate_cases(engine: Engine, n_per_firm: int = 800, seed: int = 11) -> int:
    """Populate a Nugent-flavoured synthetic case book across a few firms."""
    rng = random.Random(seed)
    rows = []
    for firm_id, _name in SAMPLE_FIRMS:
        for i in range(n_per_firm):
            injury = rng.choices(INJURY_TYPES, weights=[64, 12, 4, 8, 4, 8], k=1)[0]
            city, state = rng.choice(CITIES)
            band = rng.choices(COVERAGE_BANDS, weights=[24, 30, 26, 14, 6], k=1)[0]
            cap = _COVERAGE_CAP[band]

            median, sigma = _INJURY_BASE[injury]
            gross = rng.lognormvariate(_mu(median), sigma)
            gross = min(gross, cap * rng.uniform(0.85, 1.05))
            gross = round(max(1_500, gross), 2)

            fee_pct = round(rng.choice([33.3, 33.3, 33.3, 40.0, 40.0, 25.0]), 1)
            costs = gross * rng.uniform(0.03, 0.12)
            net_fee = round(max(0, gross * fee_pct / 100 - costs * 0.3), 2)
            duration = int(max(60, rng.gauss(430, 160)))

            rows.append({
                "firm_id": firm_id,
                "case_ref": f"{1050000 + i}",  # overlaps across firms on purpose
                "injury_type": injury, "city": city, "state": state,
                "attorney": rng.choice(ATTORNEYS),
                "coverage_band": band, "policy_limit": float(cap),
                "gross_settlement": gross, "net_fee": net_fee,
                "fee_pct": fee_pct, "duration_days": duration,
                "settled_year": rng.randint(2021, 2025),
            })

    with engine.begin() as conn:
        conn.execute(text("DELETE FROM cas_economics"))
        conn.execute(
            text(
                "INSERT INTO cas_economics "
                "(firm_id, case_ref, injury_type, city, state, attorney, "
                " coverage_band, policy_limit, gross_settlement, net_fee, fee_pct, "
                " duration_days, settled_year) VALUES "
                "(:firm_id, :case_ref, :injury_type, :city, :state, :attorney, "
                " :coverage_band, :policy_limit, :gross_settlement, :net_fee, "
                " :fee_pct, :duration_days, :settled_year)"
            ),
            rows,
        )
    return len(rows)


def _mu(median: float) -> float:
    import math
    return math.log(median)


# --- query layer ----------------------------------------------------------


@dataclass
class QuerySpec:
    measure: str = "gross_settlement"
    injury_type: str | None = None
    city: str | None = None
    coverage_band: str | None = None
    group_by: str | None = "injury_type"  # what the box plot splits on


def distinct_values(engine: Engine, column: str) -> list[str]:
    with engine.connect() as conn:
        return [
            r[0] for r in conn.execute(
                text(f"SELECT DISTINCT {column} FROM cas_economics "
                     f"WHERE {column} IS NOT NULL ORDER BY {column}")
            ).all()
        ]


_ALLOWED_COLUMNS = {"injury_type", "city", "coverage_band", "state"}


def fetch_rows(engine: Engine, spec: QuerySpec) -> list[dict]:
    """Return matching cases: the group label and the measured value.

    Column and measure names are validated against allow-lists before being
    put in the SQL, so a bad (or model-supplied) spec can never inject SQL.
    """
    measure = spec.measure if spec.measure in MEASURES else "gross_settlement"
    group = spec.group_by if spec.group_by in _ALLOWED_COLUMNS else "injury_type"

    clauses = [f"{measure} IS NOT NULL"]
    params: dict = {}
    for col, value in (("injury_type", spec.injury_type),
                       ("city", spec.city), ("coverage_band", spec.coverage_band)):
        if value:
            clauses.append(f"{col} = :{col}")
            params[col] = value

    sql = (f"SELECT {group} AS grp, {measure} AS val FROM cas_economics "
           f"WHERE {' AND '.join(clauses)}")
    with engine.connect() as conn:
        # float() guards against Postgres returning Decimal for NUMERIC columns.
        return [
            {"group": r[0], "value": float(r[1])}
            for r in conn.execute(text(sql), params).all() if r[1] is not None
        ]


def _pctile(sorted_values: list[float], p: float) -> float | None:
    """Linear-interpolated percentile of an already-sorted list."""
    n = len(sorted_values)
    if n == 0:
        return None
    if n == 1:
        return sorted_values[0]
    k = (n - 1) * p
    lo = int(k)
    hi = min(lo + 1, n - 1)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (k - lo)


def percentiles(values: list[float]) -> dict:
    if not values:
        return {}
    values = sorted(values)
    return {
        "n": len(values), "min": values[0], "p25": _pctile(values, 0.25),
        "median": _pctile(values, 0.5), "p75": _pctile(values, 0.75),
        "p90": _pctile(values, 0.90), "max": values[-1],
    }


def group_summary(engine: Engine, spec: QuerySpec) -> list[dict]:
    """Per-group percentile bands for a self-explaining box plot.

    The box spans the central ~68% of cases (16th-84th percentile) and the
    whiskers the central 95% (2.5th-97.5th) — bands a non-technical reader can
    read directly ("two-thirds settled between X and Y"), computed as
    percentiles so the skew in settlement data doesn't distort them.
    """
    from collections import defaultdict

    grouped: dict[str, list[float]] = defaultdict(list)
    for row in fetch_rows(engine, spec):
        grouped[row["group"]].append(row["value"])

    out = []
    for group, values in grouped.items():
        values = sorted(values)
        out.append({
            "group": group,
            "n": len(values),
            "lo95": _pctile(values, 0.025),
            "lo68": _pctile(values, 0.16),
            "median": _pctile(values, 0.5),
            "hi68": _pctile(values, 0.84),
            "hi95": _pctile(values, 0.975),
        })
    return out


def qualify_case(engine: Engine, spec: QuerySpec, min_net_fee: float = 15_000) -> dict:
    """Where would an incoming case sit, and is it worth taking?

    Compares the incoming case's profile against comparable settled cases and
    reports the expected value plus a plain verdict driven by expected net fee.
    """
    rows = fetch_rows(engine, QuerySpec(
        measure="net_fee", injury_type=spec.injury_type,
        city=spec.city, coverage_band=spec.coverage_band, group_by="injury_type",
    ))
    fees = [r["value"] for r in rows]
    stats = percentiles(fees)
    if not stats:
        return {"verdict": "no_comparables", "n": 0}

    expected = stats["median"]
    if expected >= min_net_fee * 1.5:
        verdict = "qualifies"
    elif expected >= min_net_fee:
        verdict = "borderline"
    else:
        verdict = "below_threshold"
    return {"verdict": verdict, "expected_net_fee": expected, **stats}
