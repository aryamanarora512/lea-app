"""Propose a column mapping for an unrecognised sheet.

The LLM reads ONLY the header row — the column names — and says which canonical
field each column feeds (by name/position). It never sees the data rows, so it
cannot hallucinate or alter a value. Deterministic code then reads every data
row by column position and loads it. This is the whole point: the model does the
one-time structural judgment; standard unwrappers move the data.

Two engines, same output shape:

* AI (optional, needs a key): the model maps header names to canonical fields,
  constrained to the real catalog so it cannot invent a target.
* Offline (default): fuzzy string matching of each header against the catalog's
  synonyms — works with no key and gives the human a first draft.

Either way a person reviews and approves before it is saved; once saved, the
mapping runs deterministically with no model involved.
"""

from __future__ import annotations

import json
import os

from .catalog import IGNORE, fields_for
from .excel import normalise


def _fuzzy(header: str, target_table: str) -> tuple[str, float]:
    """Best canonical match for one header, by synonym / name overlap."""
    token = normalise(header)
    if not token:
        return IGNORE, 0.0
    best, best_score = IGNORE, 0.0
    for f in fields_for(target_table):
        candidates = [normalise(f.name)] + [normalise(s) for s in f.synonyms]
        for cand in candidates:
            if not cand:
                continue
            if token == cand:
                score = 1.0
            elif token in cand or cand in token:
                score = 0.8
            else:
                shared = set(token.split("_")) & set(cand.split("_"))
                score = 0.6 if shared else 0.0
            if score > best_score:
                best, best_score = f.name, score
    return best, best_score


def fuzzy_mapping(headers: list[str], target_table: str) -> dict[str, dict]:
    """{normalised_header: {canonical, confidence, source}} for every header."""
    out: dict[str, dict] = {}
    for h in headers:
        if not h:
            continue
        canonical, score = _fuzzy(h, target_table)
        out[normalise(h)] = {
            "source_header": h,
            "canonical": canonical if score >= 0.6 else IGNORE,
            "confidence": round(score, 2),
        }
    return out


def propose(
    headers: list[str], samples: list[list], target_table: str, use_ai: bool = True
) -> tuple[dict[str, dict], str]:
    """Return (proposal, source) where source is 'ai' or 'fuzzy'."""
    from . import llm

    base = fuzzy_mapping(headers, target_table)
    if not use_ai or not llm.is_configured():
        return base, "fuzzy"

    fields = fields_for(target_table)
    allowed = [f.name for f in fields] + [IGNORE]
    catalog_desc = "\n".join(
        f"- {f.name} ({f.dtype}): {f.description}" for f in fields
    )
    # Headers only — the model never sees data rows, by design.
    prompt = (
        "Map each source COLUMN NAME to one canonical field, or to "
        f"'{IGNORE}' if none fits. Use ONLY the canonical field names listed. "
        "You are given only the column headers — never the data. Return JSON: an "
        "object mapping each source header to a canonical field name.\n\n"
        f"Canonical fields for {target_table}:\n{catalog_desc}\n\n"
        f"Source headers: {json.dumps([h for h in headers if h])}"
    )
    raw = llm.complete_json(prompt)
    if not isinstance(raw, dict):
        return base, "fuzzy"

    proposal: dict[str, dict] = {}
    for header in headers:
        if not header:
            continue
        canonical = raw.get(header)
        if canonical not in allowed:  # reject anything invented
            canonical = base.get(normalise(header), {}).get("canonical", IGNORE)
        proposal[normalise(header)] = {
            "source_header": header,
            "canonical": canonical,
            "confidence": 0.9 if canonical != IGNORE else 0.0,
        }
    return proposal, "ai"
