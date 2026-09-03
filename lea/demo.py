"""One-call demo bootstrap so the app works out of the box.

Ensures the database exists, seeds a synthetic portfolio and two demo targets,
and — if the real Ellis Law sample files happen to be sitting next to the
project — loads them and computes their features as a third, real target. In
the cloud, where those files are absent, the demo still runs on synthetic data
alone.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Engine

from .cases import cases_ddl, generate_cases
from .db import DEFAULT_SQLITE, dialect_name, init_db
from .features import features_ddl
from .firms import register_firm
from .load import commit_plan, plan_file
from .metrics import compute_and_store
from .synth import generate_demo_targets, generate_portfolio

SAMPLE_DIR = Path(__file__).resolve().parent.parent.parent  # the LEA_database folder
ELLIS_FILES = [
    "Census.xlsx",
    "Copy of closed_cases_by_type.xlsx",
    "List of Software Tools.xlsx",
    "Project Palm - Commercial DD Questions.xlsx",
]


def ensure_ready(engine: Engine, seed: bool | None = None) -> None:
    """Create the schema; optionally seed synthetic demo data.

    Idempotent and safe to call on every app start. By default the local
    SQLite file is seeded (so the demo works out of the box) while a real
    database — Supabase/Postgres — gets the empty tables only, keeping it clean
    and keeping first-connect light. Call seed_demo() to add sample data.
    """
    dialect = dialect_name(engine)
    init_db(engine)
    with engine.begin() as conn:
        conn.execute(text(features_ddl(dialect)))
        for statement in cases_ddl(dialect).split(";"):
            if statement.strip():
                conn.execute(text(statement))
    _migrate_cas_economics(engine)

    if seed is None:
        seed = dialect == "sqlite"
    if seed:
        seed_demo(engine)


def seed_demo(engine: Engine) -> None:
    """Load the synthetic portfolio and case book (used on demand)."""
    if _portfolio_empty(engine):
        generate_portfolio(engine)
        generate_demo_targets(engine)
        _try_load_ellis(engine)
    if _cases_empty(engine):
        generate_cases(engine)


def _portfolio_empty(engine: Engine) -> bool:
    with engine.connect() as conn:
        return not conn.execute(
            text("SELECT COUNT(*) FROM firm_features WHERE in_portfolio = 1")
        ).scalar()


def _cases_empty(engine: Engine) -> bool:
    with engine.connect() as conn:
        return not conn.execute(text("SELECT COUNT(*) FROM cas_economics")).scalar()


def _migrate_cas_economics(engine: Engine) -> None:
    """Add audit columns to a cas_economics table created before they existed.

    A plain ALTER ADD COLUMN is valid on both SQLite and Postgres and is a
    no-op once the column is present, so this safely patches a database that
    was set up by an earlier version.
    """
    from sqlalchemy import inspect

    existing = {c["name"] for c in inspect(engine).get_columns("cas_economics")}
    for name in ("load_id", "source_file", "ingested_at_utc", "attorney"):
        if name not in existing:
            with engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE cas_economics ADD COLUMN {name} TEXT"))
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_cas_economics "
            "ON cas_economics (firm_id, case_ref)"
        ))


def _try_load_ellis(engine: Engine) -> str | None:
    """Load the real sample files as a target, if they are present."""
    present = [SAMPLE_DIR / name for name in ELLIS_FILES]
    if not all(p.exists() for p in present):
        return None

    with engine.connect() as conn:
        existing = conn.execute(
            text("SELECT firm_id FROM firms WHERE LOWER(firm_name) LIKE 'ellis%'")
        ).scalar()

    if existing:
        firm_id = existing
    else:
        firm = register_firm(
            engine, "Ellis Law Corporation (real sample data)",
            state="CA", city="Downey", primary_practice="Personal Injury",
        )
        firm_id = firm.firm_id
        for path in present:
            commit_plan(engine, plan_file(engine, path, firm_id), firm_id, "demo")

    compute_and_store(
        engine, firm_id, "Ellis Law Corporation (real sample data)",
        in_portfolio=False,
    )
    return firm_id


def reset(engine: Engine) -> None:
    """Wipe the demo so it can be regenerated from scratch."""
    if DEFAULT_SQLITE.exists() and str(engine.url).startswith("sqlite"):
        engine.dispose()
        DEFAULT_SQLITE.unlink()
