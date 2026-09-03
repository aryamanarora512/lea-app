"""Natural language -> a validated chart query.

The attorney can type "settlement percentiles for dog bites in Los Angeles" and
get the right chart. The LLM's ONLY job is to map that sentence onto a fixed set
of choices — which measure, which filters, what to group by. It never touches
the data and never produces a number. Its output is validated against the known
column values; anything it invents is dropped.

With no API key, keyword matching fills the same spec, so the feature works
offline. Either way the chart is drawn by deterministic SQL over real rows.
"""

from __future__ import annotations

import json
import os

from sqlalchemy.engine import Engine

from .cases import MEASURES, QuerySpec, distinct_values


def _options(engine: Engine) -> dict:
    return {
        "measure": list(MEASURES),
        "injury_type": distinct_values(engine, "injury_type"),
        "city": distinct_values(engine, "city"),
        "coverage_band": distinct_values(engine, "coverage_band"),
        "group_by": ["injury_type", "city", "coverage_band"],
    }


def _validate(raw: dict, options: dict) -> QuerySpec:
    def pick(field, default=None):
        value = raw.get(field)
        return value if value in options[field] else default

    return QuerySpec(
        measure=pick("measure", "gross_settlement"),
        injury_type=pick("injury_type"),
        city=pick("city"),
        coverage_band=pick("coverage_band"),
        group_by=pick("group_by", "injury_type"),
    )


def keyword_spec(question: str, engine: Engine) -> QuerySpec:
    """Deterministic fallback: match the question against known values."""
    q = question.lower()
    options = _options(engine)
    raw: dict = {}

    for field in ("injury_type", "city", "coverage_band"):
        for value in options[field]:
            if value.lower() in q:
                raw[field] = value
                break
    if "net fee" in q or "fee to firm" in q:
        raw["measure"] = "net_fee"
    elif "fee %" in q or "fee percent" in q or "percentage" in q:
        raw["measure"] = "fee_pct"
    elif "duration" in q or "time to" in q or "days" in q:
        raw["measure"] = "duration_days"
    else:
        raw["measure"] = "gross_settlement"

    if "by city" in q:
        raw["group_by"] = "city"
    elif "by coverage" in q or "by policy" in q:
        raw["group_by"] = "coverage_band"
    return _validate(raw, options)


def resolve(question: str, engine: Engine, use_ai: bool = True) -> tuple[QuerySpec, str]:
    """Return (spec, source). source is 'ai' or 'keywords'."""
    from . import llm
    if not use_ai or not llm.is_configured():
        return keyword_spec(question, engine), "keywords"

    options = _options(engine)
    prompt = (
        "Map the attorney's request onto a chart query. Choose only from the "
        "allowed values; if a filter is not mentioned, use null for it. Return a "
        "JSON object with keys: measure, injury_type, city, coverage_band, "
        "group_by.\n\n"
        f"Allowed values: {json.dumps(options)}\n\n"
        f"Request: {question}"
    )
    raw = llm.complete_json(prompt, max_tokens=1500)
    if not isinstance(raw, dict):
        return keyword_spec(question, engine), "keywords"
    return _validate(raw, options), "ai"
