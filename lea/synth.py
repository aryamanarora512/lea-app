"""Synthetic portfolio generator.

The real portfolio has only a handful of firms and the data is proprietary.
This module manufactures a plausible portfolio so the demo runs anywhere, with
no real data, and so anomaly detection has a baseline to compare against. It is
also the publishable version of the project.

Two pre-built targets are included: one deliberately anomalous (so a reviewer
sees red flags fire) and one deliberately ordinary (so they see a clean pass).
Numbers are drawn from distributions chosen to resemble mid-market
personal-injury firms; they are invented, not real.
"""

from __future__ import annotations

import random

from sqlalchemy.engine import Engine

from .features import upsert_features

PORTFOLIO_NAMES = [
    "Northgate Injury Partners", "Vale & Rourke", "Cardinal Trial Group",
    "Meridian Accident Law", "Halloran Sanchez", "Brightwater Legal",
    "Stonebridge Injury Attorneys", "Pratt & Osei", "Lakeshore Advocates",
    "Ironwood Trial Lawyers", "Delacroix Personal Injury", "Summit & Vance",
]

# Portfolio metric distributions: (mean, sd, low clamp, high clamp).
_DISTS = {
    "avg_attorney_salary": (190_000, 22_000, 130_000, 260_000),
    "comp_concentration_pct": (22, 6, 10, 45),
    "pct_contractors": (12, 5, 0, 35),
    "settlement_rate": (62, 7, 40, 80),
    "drop_rate": (14, 4, 3, 30),
    "practice_concentration_pct": (68, 10, 40, 92),
    "software_tool_count": (21, 5, 8, 40),
    "diligence_completeness_pct": (80, 10, 45, 100),
    # case-economics metrics, so case-data firms have a baseline to compare to
    "avg_settlement": (34_000, 9_000, 12_000, 70_000),
    "avg_net_fee": (11_000, 3_000, 4_000, 24_000),
    "avg_fee_pct": (33, 3, 25, 40),
    "avg_time_to_settle": (400, 90, 200, 640),
}
_PRACTICES = (["Motor Vehicle"] * 7 + ["Premises"] * 2 + ["Med Mal"] + ["Product"])


def _clamped(rng: random.Random, mean, sd, low, high) -> float:
    return round(min(high, max(low, rng.gauss(mean, sd))), 1)


def _make_portfolio_firm(rng: random.Random) -> dict:
    headcount = int(min(130, max(12, rng.gauss(38, 18))))
    attorney_ratio = min(0.5, max(0.18, rng.gauss(0.33, 0.06)))
    attorneys = max(2, round(headcount * attorney_ratio))
    staff = max(1, headcount - attorneys)

    values = {
        "headcount": headcount,
        "attorney_to_staff_ratio": round(attorneys / staff, 2),
        "total_cases": int(min(8000, max(300, rng.lognormvariate(7.5, 0.5)))),
        "office_count": max(1, min(12, round(rng.gauss(5, 2)))),
    }
    for key, params in _DISTS.items():
        values[key] = _clamped(rng, *params)

    return {"values": values, "dominant_practice": rng.choice(_PRACTICES)}


def generate_portfolio(engine: Engine, n: int = 12, seed: int = 7) -> list[str]:
    """Create (or refresh) a synthetic portfolio. Returns the firm ids."""
    rng = random.Random(seed)
    firm_ids = []
    for i, name in enumerate(PORTFOLIO_NAMES[:n]):
        firm_id = f"9{i + 1:03d}"
        firm = _make_portfolio_firm(rng)
        upsert_features(
            engine, firm_id, name, firm["values"], firm["dominant_practice"],
            in_portfolio=True,
        )
        firm_ids.append(firm_id)
    return firm_ids


# Pre-built demo targets — NOT in the portfolio (in_portfolio=False).
_DEMO_TARGETS = {
    "0801": {
        "firm_name": "Project Condor (demo — anomalous)",
        "dominant_practice": "Motor Vehicle",
        "values": {
            "headcount": 9,
            "attorney_to_staff_ratio": 0.6,
            "avg_attorney_salary": 152_000,
            "comp_concentration_pct": 48,   # one rainmaker
            "pct_contractors": 40,          # heavily contracted
            "total_cases": 420,
            "settlement_rate": 44,          # low
            "drop_rate": 28,                # high
            "practice_concentration_pct": 94,  # all one practice
            "software_tool_count": 6,       # light tech
            "diligence_completeness_pct": 40,  # many open questions
            "office_count": 1,
        },
    },
    "0802": {
        "firm_name": "Project Marlin (demo — ordinary)",
        "dominant_practice": "Motor Vehicle",
        "values": {
            "headcount": 40,
            "attorney_to_staff_ratio": 0.5,
            "avg_attorney_salary": 188_000,
            "comp_concentration_pct": 21,
            "pct_contractors": 11,
            "total_cases": 1_950,
            "settlement_rate": 63,
            "drop_rate": 13,
            "practice_concentration_pct": 66,
            "software_tool_count": 22,
            "diligence_completeness_pct": 82,
            "office_count": 5,
        },
    },
}


def generate_demo_targets(engine: Engine) -> list[str]:
    for firm_id, spec in _DEMO_TARGETS.items():
        upsert_features(
            engine, firm_id, spec["firm_name"], spec["values"],
            spec["dominant_practice"], in_portfolio=False,
        )
    return list(_DEMO_TARGETS)
