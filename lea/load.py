"""Loading: idempotent writes, load logging, and duplicate detection.

Two independent guards stop double-loading:

1. Content hash — the same file dropped twice is recognised before parsing.
2. Natural-key upsert — the same *rows* arriving through a different file
   (a re-export, a renamed copy, an updated tab) update in place instead of
   duplicating, because every target table declares a business key.

Together they mean a nervous user can drop the same folder five times and the
database is identical to dropping it once.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from .dbml import NATURAL_KEYS
from .excel import content_hash, probe_workbook
from .recipes import Finding, ParseResult, find_recipe


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class SheetPlan:
    """One sheet, the recipe that claimed it, and the parse preview."""

    sheet_name: str
    recipe_name: str | None
    recipe_description: str
    target_table: str | None
    result: ParseResult | None
    probe: Any = None

    @property
    def loadable(self) -> bool:
        return bool(self.result and self.result.rows and not self.result.errors)


@dataclass
class FilePlan:
    """Everything the GUI needs to show before the user commits."""

    path: Path
    file_hash: str
    sheets: list[SheetPlan]
    previously_loaded: dict | None = None

    @property
    def total_rows(self) -> int:
        return sum(len(s.result.rows) for s in self.sheets if s.result)

    @property
    def unrecognised(self) -> list[SheetPlan]:
        return [s for s in self.sheets if s.recipe_name is None]


def plan_file(engine: Engine, path: str | Path, firm_id: str) -> FilePlan:
    """Parse a workbook into a preview without writing anything.

    Nothing touches the database until the user confirms. Non-technical staff
    need to see what will happen before it happens.
    """
    path = Path(path)
    file_hash = content_hash(path)

    with engine.connect() as conn:
        prior = conn.execute(
            text(
                "SELECT load_id, source_file, firm_id, ingested_at_utc, rows_written "
                "FROM load_log WHERE content_sha256 = :h AND status = 'success' "
                "ORDER BY ingested_at_utc DESC"
            ),
            {"h": file_hash},
        ).mappings().first()

    sheets: list[SheetPlan] = []
    for probe in probe_workbook(path):
        if probe.header_row is None:
            sheets.append(
                SheetPlan(probe.sheet_name, None, "No header row found", None, None, probe)
            )
            continue

        recipe = find_recipe(probe)
        if recipe is None:
            sheets.append(
                SheetPlan(
                    probe.sheet_name,
                    None,
                    "Unrecognised layout — needs manual column mapping",
                    None,
                    None,
                    probe,
                )
            )
            continue

        try:
            result = recipe.parse(str(path), probe, firm_id)
        except Exception as exc:  # a bad sheet must not sink the whole file
            result = ParseResult(target_table=recipe.target_table)
            result.findings.append(
                Finding("parse_failed", "error", f"{type(exc).__name__}: {exc}")
            )

        sheets.append(
            SheetPlan(
                probe.sheet_name,
                recipe.name,
                recipe.description,
                recipe.target_table,
                result,
                probe,
            )
        )

    return FilePlan(path, file_hash, sheets, dict(prior) if prior else None)


def commit_plan(
    engine: Engine,
    plan: FilePlan,
    firm_id: str,
    loaded_by: str = "gui",
    only_sheets: set[str] | None = None,
) -> list[dict]:
    """Write the planned rows and record the load. Returns a per-sheet summary."""
    summaries = []

    for sheet in plan.sheets:
        if only_sheets is not None and sheet.sheet_name not in only_sheets:
            continue
        if not sheet.result or not sheet.target_table:
            continue

        load_id = uuid.uuid4().hex
        timestamp = utcnow()
        rows = sheet.result.rows
        status, message, written = "success", None, 0

        try:
            if sheet.result.errors:
                raise ValueError(
                    f"{len(sheet.result.errors)} blocking error(s); nothing written."
                )
            written = _upsert(
                engine, sheet.target_table, rows, load_id, plan.path.name, timestamp
            )
        except Exception as exc:
            status, message = "failed", f"{type(exc).__name__}: {exc}"

        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO load_log (load_id, source_file, content_sha256, "
                    "firm_id, recipe, target_table, rows_read, rows_written, "
                    "rows_rejected, status, message, loaded_by, ingested_at_utc) "
                    "VALUES (:load_id, :source_file, :h, :firm_id, :recipe, "
                    ":target, :read, :written, :rejected, :status, :message, "
                    ":by, :ts)"
                ),
                {
                    "load_id": load_id,
                    "source_file": f"{plan.path.name}::{sheet.sheet_name}",
                    "h": plan.file_hash,
                    "firm_id": firm_id,
                    "recipe": sheet.recipe_name,
                    "target": sheet.target_table,
                    "read": sheet.result.rows_read,
                    "written": written,
                    "rejected": sheet.result.rows_read - written,
                    "status": status,
                    "message": message,
                    "by": loaded_by,
                    "ts": timestamp,
                },
            )

            for finding in sheet.result.findings:
                conn.execute(
                    text(
                        "INSERT INTO dq_result (load_id, check_name, severity, "
                        "row_index, column_name, detail, checked_at_utc) "
                        "VALUES (:l, :c, :s, :r, :col, :d, :ts)"
                    ),
                    {
                        "l": load_id,
                        "c": finding.check_name,
                        "s": finding.severity,
                        "r": finding.row_index,
                        "col": finding.column_name,
                        "d": finding.detail,
                        "ts": timestamp,
                    },
                )

        summaries.append(
            {
                "sheet": sheet.sheet_name,
                "table": sheet.target_table,
                "rows_written": written,
                "status": status,
                "message": message,
                "load_id": load_id,
            }
        )

    return summaries


def _upsert(
    engine: Engine,
    table: str,
    rows: list[dict[str, Any]],
    load_id: str,
    source_file: str,
    timestamp: str,
) -> int:
    """Insert rows, updating any that already exist on the natural key."""
    if not rows:
        return 0

    key = NATURAL_KEYS.get(table) or _extra_natural_key(table)
    columns = list(rows[0].keys()) + ["load_id", "source_file", "ingested_at_utc"]
    payload = [
        {**row, "load_id": load_id, "source_file": source_file,
         "ingested_at_utc": timestamp}
        for row in rows
    ]

    placeholders = ", ".join(f":{c}" for c in columns)
    column_list = ", ".join(columns)

    # SQLite and Postgres share ON CONFLICT ... DO UPDATE, so the same
    # idempotent upsert works against a local file or Supabase unchanged.
    native_upsert = engine.dialect.name in ("sqlite", "postgresql", "postgres")

    if key and native_upsert:
        updates = ", ".join(f"{c} = excluded.{c}" for c in columns if c not in key)
        statement = (
            f"INSERT INTO {table} ({column_list}) VALUES ({placeholders}) "
            f"ON CONFLICT ({', '.join(key)}) DO UPDATE SET {updates}"
        )
    else:  # SQL Server: delete-then-insert inside the same transaction
        statement = f"INSERT INTO {table} ({column_list}) VALUES ({placeholders})"

    with engine.begin() as conn:
        if key and not native_upsert:
            where = " AND ".join(f"{c} = :{c}" for c in key)
            for row in payload:
                conn.execute(
                    text(f"DELETE FROM {table} WHERE {where}"),
                    {c: row[c] for c in key},
                )
        conn.execute(text(statement), payload)

    return len(payload)


def _extra_natural_key(table: str) -> list[str] | None:
    return {
        "cas_case_ledger": ["firm_id", "case_number"],
        "dd_responses": ["firm_id", "question"],
        "cas_economics": ["firm_id", "case_ref"],
    }.get(table)


def recent_loads(engine: Engine, limit: int = 50) -> list[dict]:
    with engine.connect() as conn:
        return [
            dict(r)
            for r in conn.execute(
                text(
                    "SELECT ingested_at_utc, source_file, firm_id, target_table, "
                    "rows_written, status, message FROM load_log "
                    "ORDER BY ingested_at_utc DESC LIMIT :n"
                ),
                {"n": limit},
            ).mappings()
        ]
