"""Recipe registry: how a recognised file shape becomes typed rows.

A recipe knows three things: whether it can handle a given sheet, which target
table it writes to, and how to turn each spreadsheet row into a dict of typed
column values plus a list of data-quality findings.

Recognition is by fingerprint (the sorted set of normalised header tokens), so
the same recipe handles all seven case-type tabs of one workbook and keeps
working when a firm reorders columns. When no recipe matches, the GUI falls
back to manual column mapping and saves the result as a new recipe — which is
how adding a monitored file type becomes a config change rather than a code
change.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from ..excel import SheetProbe


@dataclass
class Finding:
    """One data-quality observation, tied to a row where possible."""

    check_name: str
    severity: str  # "error" blocks the row | "warning" flags it | "info"
    detail: str
    row_index: int | None = None
    column_name: str | None = None


@dataclass
class ParseResult:
    target_table: str
    rows: list[dict[str, Any]] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    rows_read: int = 0

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "error"]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "warning"]


class Recipe(Protocol):
    name: str
    description: str
    target_table: str

    def matches(self, probe: SheetProbe) -> bool: ...

    def parse(self, path: str, probe: SheetProbe, firm_id: str) -> ParseResult: ...


_REGISTRY: list[Recipe] = []


def register(recipe: Recipe) -> Recipe:
    _REGISTRY.append(recipe)
    return recipe


def all_recipes() -> list[Recipe]:
    return list(_REGISTRY)


def find_recipe(probe: SheetProbe) -> Recipe | None:
    """First recipe that claims this sheet, or None for manual mapping.

    Built-in recipes are checked first, then saved (user-taught) mappings — so
    a layout learned once through the mapping UI is recognised automatically on
    every later file of the same shape.
    """
    for recipe in _REGISTRY:
        try:
            if recipe.matches(probe):
                return recipe
        except Exception:  # a broken recipe must not block the others
            continue

    from .. import mapping  # imported here to avoid a circular import at load time
    return mapping.saved_recipe_for(probe)


def has_tokens(probe: SheetProbe, *required: str) -> bool:
    """True when every required token appears in the sheet's header."""
    present = set(probe.normalised_header)
    return all(token in present for token in required)


# Importing the built-ins registers them as a side effect.
from . import builtin  # noqa: E402,F401
