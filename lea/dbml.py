"""Parse the DBML schema file into table definitions and emit CREATE TABLE DDL.

The DBML file (dbdiagram.io export) is the single source of truth for the
portfolio schema. Editing the diagram and re-running `init_db` propagates the
change to the database, so the ERD and the physical schema cannot drift apart.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# DBML uses SQLite-flavoured type names. Money must never land in a float:
# binary floating point cannot represent 0.01 exactly, so footing checks
# (does salary + bonus equal total?) fail nondeterministically on real data.
TYPE_MAP = {
    "sqlite": {
        "text": "TEXT",
        "int": "INTEGER",
        "integer": "INTEGER",
        "real": "NUMERIC(18, 2)",
        "date": "DATE",
    },
    "mssql": {
        "text": "NVARCHAR(400)",
        "int": "INT",
        "integer": "INT",
        "real": "DECIMAL(18, 2)",
        "date": "DATE",
    },
    "postgres": {
        "text": "TEXT",
        "int": "INTEGER",
        "integer": "INTEGER",
        "real": "NUMERIC(18, 2)",
        "date": "DATE",
    },
}

_TABLE_RE = re.compile(r"^Table\s+(\w+)\s*\{", re.MULTILINE)
_COLUMN_RE = re.compile(r"^\s*(\w+)\s+(\w+)\s*(\[[^\]]*\])?\s*$")
_REF_RE = re.compile(r"ref:\s*>\s*(\w+)\.(\w+)")


@dataclass
class Column:
    name: str
    dbml_type: str
    is_pk: bool = False
    ref_table: str | None = None
    ref_column: str | None = None

    def ddl(self, dialect: str) -> str:
        sql_type = TYPE_MAP[dialect].get(self.dbml_type, TYPE_MAP[dialect]["text"])
        parts = [f"    {self.name} {sql_type}"]
        if self.is_pk:
            parts.append("NOT NULL PRIMARY KEY")
        return " ".join(parts)


@dataclass
class Table:
    name: str
    columns: list[Column] = field(default_factory=list)

    @property
    def pk(self) -> Column | None:
        return next((c for c in self.columns if c.is_pk), None)

    def column(self, name: str) -> Column | None:
        return next((c for c in self.columns if c.name == name), None)


def parse_dbml(path: str | Path) -> dict[str, Table]:
    """Parse a DBML file into {table_name: Table}. TableGroups are ignored."""
    text = Path(path).read_text(encoding="utf-8")
    tables: dict[str, Table] = {}

    for match in _TABLE_RE.finditer(text):
        name = match.group(1)
        body, _ = _extract_block(text, match.end() - 1)
        table = Table(name=name)

        for line in body.splitlines():
            line = line.strip()
            if not line or line.startswith("//"):
                continue
            col_match = _COLUMN_RE.match(line)
            if not col_match:
                continue
            col_name, col_type, attrs = col_match.groups()
            attrs = attrs or ""
            column = Column(
                name=col_name,
                dbml_type=col_type.lower(),
                is_pk="[pk]" in attrs.replace(" ", ""),
            )
            ref = _REF_RE.search(attrs)
            if ref:
                column.ref_table, column.ref_column = ref.group(1), ref.group(2)
            table.columns.append(column)

        tables[name] = table

    return tables


def _extract_block(text: str, open_brace_index: int) -> tuple[str, int]:
    """Return the contents between a `{` and its matching `}`."""
    depth = 0
    for i in range(open_brace_index, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[open_brace_index + 1 : i], i
    raise ValueError("Unbalanced braces in DBML file")


# Natural keys the DBML does not declare. Without these, re-running a load
# inserts a second copy of every row: the surrogate `id integer [pk]` is
# generated fresh each time, so it can never detect that a row already exists.
# Declaring the business key is what makes loading idempotent.
NATURAL_KEYS: dict[str, list[str]] = {
    "per_employee_census": ["firm_id", "employee_number"],
    "cas_case_ledger": ["firm_id", "case_number"],
    "cas_closed_cases": ["firm_id", "period_year", "quarter", "case_type"],
    "tec_tools": ["firm_id", "tool_name"],
    "cas_top_25_cases": ["firm_id", "snapshot_date", "rank"],
    "geo_office_overview": ["office_id"],
    "geo_office_performance": ["firm_id", "office_name", "period_year"],
}

# Columns added to every physical table for lineage and idempotency.
AUDIT_COLUMNS: dict[str, dict[str, str]] = {
    "load_id": {"sqlite": "TEXT", "mssql": "NVARCHAR(64)", "postgres": "TEXT"},
    "source_file": {"sqlite": "TEXT", "mssql": "NVARCHAR(400)", "postgres": "TEXT"},
    "ingested_at_utc": {"sqlite": "TEXT", "mssql": "DATETIME2", "postgres": "TEXT"},
}


def table_ddl(table: Table, dialect: str = "sqlite") -> str:
    """Emit CREATE TABLE for one parsed DBML table, with audit columns."""
    lines = [c.ddl(dialect) for c in table.columns]
    lines += [f"    {n} {t[dialect]}" for n, t in AUDIT_COLUMNS.items()]

    for column in table.columns:
        if column.ref_table:
            lines.append(
                f"    FOREIGN KEY ({column.name}) "
                f"REFERENCES {column.ref_table}({column.ref_column})"
            )

    body = ",\n".join(lines)
    ddl = f"CREATE TABLE IF NOT EXISTS {table.name} (\n{body}\n);"

    key = NATURAL_KEYS.get(table.name)
    if key:
        ddl += (
            f"\nCREATE UNIQUE INDEX IF NOT EXISTS ux_{table.name} "
            f"ON {table.name} ({', '.join(key)});"
        )
    return ddl


def schema_ddl(tables: dict[str, Table], dialect: str = "sqlite") -> str:
    """Emit the full schema. `firms` first so foreign keys resolve."""
    ordered = ["firms"] + sorted(n for n in tables if n != "firms")
    return "\n\n".join(table_ddl(tables[n], dialect) for n in ordered if n in tables)
