"""Canonical field catalog — the targets any firm's columns map onto.

This is the vocabulary of the schema-matching system. A firm can call a column
whatever it likes; the mapping engine (and the LLM proposer) line it up against
one of these canonical fields. Synonyms drive the offline fuzzy matcher and seed
the LLM's choices; descriptions tell the LLM what each field means.

Add a canonical field here and every firm can map to it — no per-firm code.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CanonicalField:
    name: str
    dtype: str  # "text" | "money" | "number" | "int" | "date"
    description: str
    synonyms: tuple[str, ...] = field(default_factory=tuple)


# Target table -> its canonical fields. cas_economics is the case-economics
# table the case explorer reads; more targets can be added the same way.
CATALOG: dict[str, list[CanonicalField]] = {
    "cas_economics": [
        CanonicalField("case_ref", "text", "The firm's identifier for the case",
                       ("file number", "file no", "case id", "case ref",
                        "case number", "matter number", "matter id")),
        CanonicalField("attorney", "text", "Handling attorney or team member",
                       ("handling attorney", "attorney", "team member",
                        "responsible attorney", "lawyer", "handler")),
        CanonicalField("injury_type", "text",
                       "Practice area or type of injury/matter",
                       ("practice area", "case type", "injury type", "injury",
                        "matter type", "area of law", "type")),
        CanonicalField("city", "text", "Locality of the case — city or county",
                       ("city", "county", "locality", "venue", "jurisdiction")),
        CanonicalField("state", "text", "US state",
                       ("state", "st", "province")),
        CanonicalField("coverage_band", "text",
                       "Insurance coverage tier / policy-limit band",
                       ("coverage", "coverage band", "policy limit band")),
        CanonicalField("policy_limit", "money", "Insurance policy limit in dollars",
                       ("policy limit", "coverage limit", "limit")),
        CanonicalField("gross_settlement", "money",
                       "Total gross settlement or recovery in dollars",
                       ("settlement amount", "gross settlement", "gross recovery",
                        "total settlement", "settlement", "recovery", "award")),
        CanonicalField("net_fee", "money",
                       "Fee earned by the firm in dollars",
                       ("attorney fee", "net fee", "fee to firm", "legal fee",
                        "firm fee", "fee")),
        CanonicalField("fee_pct", "number", "Fee as a percent of gross settlement",
                       ("fee percent", "fee pct", "fee %", "contingency",
                        "contingency rate")),
        CanonicalField("duration_days", "int", "Days from open to settlement",
                       ("time to settle", "days to settle", "duration",
                        "cycle time", "time to resolution")),
        CanonicalField("settled_year", "int", "Year the case settled / closed",
                       ("close year", "settlement year", "dep year",
                        "deposit year", "year settled", "closed year")),
    ],
}

# A few source tokens should never be mapped to a canonical field.
IGNORE = "(ignore)"


def fields_for(target_table: str) -> list[CanonicalField]:
    return CATALOG.get(target_table, [])


def field_names(target_table: str) -> list[str]:
    return [f.name for f in fields_for(target_table)]
