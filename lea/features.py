"""The metric registry: the firm-level features we monitor.

Everything downstream — synthetic generation, the feature table, detection, and
the plain-language output — is generated from this one list. Adding a monitored
metric is an edit here, not a rewrite of the pipeline.

Each metric records not just how to compute it but *why a deal person should
care*, so the anomaly explanation can speak in business terms rather than
statistics.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.engine import Engine


@dataclass(frozen=True)
class Metric:
    key: str
    label: str
    unit: str  # "count" | "money" | "ratio" | "pct"
    concerning: str  # "high" | "low" | "both" — which direction warrants a look
    why: str  # plain-language reason a deviation matters

    def format(self, value: float | None) -> str:
        if value is None:
            return "—"
        if self.unit == "money":
            return f"${value:,.0f}"
        if self.unit == "pct":
            return f"{value:.0f}%"
        if self.unit == "ratio":
            return f"{value:.2f}"
        return f"{value:,.0f}"


METRICS: list[Metric] = [
    Metric("headcount", "Total headcount", "count", "both",
           "Sets the scale of the firm; a target far from the portfolio is a "
           "different kind of business than we usually buy."),
    Metric("attorney_to_staff_ratio", "Attorney-to-staff ratio", "ratio", "both",
           "Too high means thin support and burnout risk; too low means an "
           "expensive back office relative to fee earners."),
    Metric("avg_attorney_salary", "Average attorney salary", "money", "both",
           "Far above portfolio suggests an expensive cost base; far below can "
           "signal retention risk or understated compensation."),
    Metric("comp_concentration_pct", "Pay concentration (top earner)", "pct", "high",
           "A large share of payroll going to one person is key-person risk — "
           "if they leave, revenue may follow."),
    Metric("pct_contractors", "Share of staff on 1099 / contract", "pct", "high",
           "A heavily contracted workforce can mean weaker retention and "
           "misclassification exposure."),
    Metric("total_cases", "Total cases on file", "count", "both",
           "The engine of the business; a very small book relative to headcount "
           "raises questions about productivity."),
    Metric("settlement_rate", "Settlement rate", "pct", "low",
           "A low share of cases reaching settlement can indicate weak case "
           "selection or an unusually litigious book."),
    Metric("drop_rate", "Case drop rate", "pct", "high",
           "A high share of dropped cases is wasted intake spend and can signal "
           "loose screening at the front door."),
    Metric("practice_concentration_pct", "Practice concentration", "pct", "high",
           "Most revenue in one practice area is concentration risk — a change "
           "in that market hits the whole firm."),
    Metric("software_tool_count", "Software tools in use", "count", "low",
           "A very light technology stack can mean manual process and "
           "integration cost after acquisition."),
    Metric("diligence_completeness_pct", "Diligence answers completed", "pct", "low",
           "A low completion rate means we are being asked to price the firm "
           "with important questions still open."),
    Metric("office_count", "Number of offices", "count", "both",
           "Footprint drives fixed cost and integration complexity; an outlier "
           "either way is worth understanding."),
    # --- case-economics metrics (from settled-case data like Nugent's) ---
    Metric("avg_settlement", "Average settlement", "money", "both",
           "The typical size of a case. Far below portfolio suggests a small-case "
           "book; far above may mean lumpy, harder-to-repeat outcomes."),
    Metric("avg_net_fee", "Average net fee per case", "money", "both",
           "What the firm actually earns per case after costs — the core unit of "
           "profitability."),
    Metric("avg_fee_pct", "Average fee %", "pct", "low",
           "The firm's effective take rate. A low rate erodes revenue on the same "
           "settlement volume."),
    Metric("avg_time_to_settle", "Average time to settle (days)", "count", "high",
           "How long capital and effort are tied up per case; slower cycles hurt "
           "cash flow and throughput."),
]

METRIC_BY_KEY = {m.key: m for m in METRICS}
_NUMERIC_KEYS = [m.key for m in METRICS]


def features_ddl(dialect: str = "sqlite") -> str:
    """One wide row per firm — the Gold feature table BI tools also read."""
    number = {"sqlite": "REAL", "postgres": "NUMERIC(18, 4)"}.get(dialect, "DECIMAL(18, 4)")
    text_type = {"sqlite": "TEXT", "postgres": "TEXT"}.get(dialect, "NVARCHAR(200)")
    columns = [f"    {key} {number}" for key in _NUMERIC_KEYS]
    columns = [
        f"    firm_id {text_type} NOT NULL PRIMARY KEY",
        f"    firm_name {text_type}",
        *columns,
        f"    dominant_practice {text_type}",
        "    in_portfolio INTEGER",
        f"    computed_at {text_type}",
    ]
    body = ",\n".join(columns)
    return f"CREATE TABLE IF NOT EXISTS firm_features (\n{body}\n);"


def upsert_features(
    engine: Engine,
    firm_id: str,
    firm_name: str,
    values: dict[str, float | None],
    dominant_practice: str | None,
    in_portfolio: bool,
) -> None:
    from datetime import datetime, timezone

    row = {
        "firm_id": firm_id,
        "firm_name": firm_name,
        "dominant_practice": dominant_practice,
        "in_portfolio": 1 if in_portfolio else 0,
        "computed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    for key in _NUMERIC_KEYS:
        row[key] = values.get(key)

    columns = list(row.keys())
    placeholders = ", ".join(f":{c}" for c in columns)
    updates = ", ".join(f"{c} = excluded.{c}" for c in columns if c != "firm_id")

    with engine.begin() as conn:
        conn.execute(
            text(
                f"INSERT INTO firm_features ({', '.join(columns)}) "
                f"VALUES ({placeholders}) "
                f"ON CONFLICT (firm_id) DO UPDATE SET {updates}"
            ),
            row,
        )


def read_features(engine: Engine, in_portfolio: bool | None = None) -> list[dict]:
    clause = ""
    if in_portfolio is True:
        clause = "WHERE in_portfolio = 1"
    elif in_portfolio is False:
        clause = "WHERE in_portfolio = 0"
    with engine.connect() as conn:
        return [
            dict(r)
            for r in conn.execute(
                text(f"SELECT * FROM firm_features {clause} ORDER BY firm_id")
            ).mappings()
        ]


def read_one(engine: Engine, firm_id: str) -> dict | None:
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT * FROM firm_features WHERE firm_id = :f"),
            {"f": firm_id},
        ).mappings().first()
    return dict(row) if row else None
