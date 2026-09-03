"""Data-driven mapping recipes: apply a saved column map, and persist new ones.

A MappingSpec is a recognised file shape expressed as configuration, not code:
which target table, and which source column feeds each canonical field. Once
saved (as JSON keyed by the sheet's fingerprint) it is applied deterministically
forever after — the LLM is not in this path.

This is what makes the pipeline handle new firms without new code: teach it a
layout once, and it becomes a reusable recipe.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .catalog import IGNORE, fields_for
from .excel import (
    SheetProbe, fingerprint, normalise, read_rows, to_date, to_int, to_number, to_text,
)
from .recipes import Finding, ParseResult

MAPPINGS_DIR = Path(__file__).resolve().parent.parent / "config" / "mappings"

# Named transforms a mapping can apply to a source value before storing it.
TRANSFORMS = {
    "none": lambda v: v,
    "months_to_days": lambda v: None if v is None else v * 30.44,
    "ratio_to_pct": lambda v: None if v is None else v * 100,
}


@dataclass
class MappingSpec:
    fingerprint: str
    target_table: str
    column_map: dict[str, str]          # normalised source header -> canonical field
    transforms: dict[str, str] = field(default_factory=dict)  # canonical -> transform
    label: str = ""
    firm_hint: str = ""
    created_at: str = ""

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)


def save_mapping(spec: MappingSpec) -> Path:
    MAPPINGS_DIR.mkdir(parents=True, exist_ok=True)
    if not spec.created_at:
        spec.created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    path = MAPPINGS_DIR / f"{spec.fingerprint}.json"
    path.write_text(spec.to_json(), encoding="utf-8")
    return path


def load_mappings() -> dict[str, MappingSpec]:
    """All saved mappings, keyed by fingerprint."""
    out: dict[str, MappingSpec] = {}
    if not MAPPINGS_DIR.exists():
        return out
    for file in MAPPINGS_DIR.glob("*.json"):
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
            out[data["fingerprint"]] = MappingSpec(**data)
        except Exception:
            continue
    return out


def _coerce(value, dtype: str):
    if dtype in ("money", "number"):
        return to_number(value)
    if dtype == "int":
        return to_int(value)
    if dtype == "date":
        parsed, _ = to_date(value)
        return parsed.isoformat() if parsed else None
    return to_text(value)


class MappingRecipe:
    """Adapts a saved MappingSpec to the Recipe interface used by the loader."""

    def __init__(self, spec: MappingSpec):
        self.spec = spec
        self.name = f"mapping:{spec.label or spec.target_table}"
        self.description = (
            f"Saved mapping{f' for {spec.firm_hint}' if spec.firm_hint else ''} "
            f"→ {spec.target_table}"
        )
        self.target_table = spec.target_table

    def matches(self, probe: SheetProbe) -> bool:
        return probe.header_row is not None and fingerprint(probe) == self.spec.fingerprint

    def parse(self, path: str, probe: SheetProbe, firm_id: str) -> ParseResult:
        header, data = read_rows(path, probe.sheet_name, probe.header_row)
        index = {normalise(h): i for i, h in enumerate(header) if h}
        by_name = {f.name: f for f in fields_for(self.spec.target_table)}
        result = ParseResult(target_table=self.spec.target_table, rows_read=len(data))

        # canonical field -> source column position
        wiring = {
            canonical: index[src]
            for src, canonical in self.spec.column_map.items()
            if canonical != IGNORE and src in index and canonical in by_name
        }

        # Every row must carry the same keys, or the bulk insert rejects them.
        # fee_pct is included when it can be derived even if not mapped.
        columns = ["firm_id"] + list(wiring)
        derive_fee = ("net_fee" in wiring and "gross_settlement" in wiring
                      and "fee_pct" not in wiring)
        if derive_fee:
            columns.append("fee_pct")

        for offset, raw in enumerate(data):
            row_number = probe.header_row + offset + 2
            record: dict = {col: None for col in columns}
            record["firm_id"] = firm_id

            for canonical, pos in wiring.items():
                value = raw[pos] if pos < len(raw) else None
                dtype = by_name[canonical].dtype
                transform = self.spec.transforms.get(canonical)
                if transform and transform != "none":
                    record[canonical] = _coerce(TRANSFORMS[transform](to_number(value)), dtype)
                else:
                    record[canonical] = _coerce(value, dtype)

            if not record.get("case_ref"):
                continue

            gross = record.get("gross_settlement")
            net = record.get("net_fee")
            if gross and net:
                if net > gross:
                    result.findings.append(Finding(
                        "fee_exceeds_settlement", "warning",
                        f"Fee {net:,.0f} exceeds settlement {gross:,.0f}.", row_number))
                if derive_fee:
                    record["fee_pct"] = round(100 * net / gross, 1)

            result.rows.append(record)

        result.findings.append(Finding(
            "mapped_via_saved_recipe", "info",
            f"Loaded through the saved mapping for this layout "
            f"({len(wiring)} columns mapped).",
        ))
        return result


def saved_recipe_for(probe: SheetProbe) -> MappingRecipe | None:
    if probe.header_row is None:
        return None
    spec = load_mappings().get(fingerprint(probe))
    return MappingRecipe(spec) if spec else None
