"""Database connection and schema initialisation.

One connection string switches the whole pipeline between a local SQLite file
(dev, demos, and the publishable version) and the production SQL Server
instance. Nothing else in the codebase knows which one it is talking to.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from .dbml import parse_dbml, schema_ddl

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DBML = PROJECT_ROOT.parent / "Table firms {.go"
DEFAULT_SQLITE = PROJECT_ROOT / "data" / "lea_portfolio.db"


def get_engine(url: str | None = None) -> Engine:
    """Build the engine. Set LEA_DB_URL to point at SQL Server.

    SQL Server example:
        mssql+pyodbc://user:pass@host/LEA?driver=ODBC+Driver+18+for+SQL+Server
    """
    url = url or os.environ.get("LEA_DB_URL") or _url_from_env_file()
    if not url:
        DEFAULT_SQLITE.parent.mkdir(parents=True, exist_ok=True)
        url = f"sqlite:///{DEFAULT_SQLITE}"
    url = _clean_url(url)
    kwargs: dict = {"future": True, "pool_pre_ping": True}
    if url.startswith("postgresql"):
        # Keep a small, capped pool so the Supabase pooler's circuit breaker
        # never sees a connection storm from this app.
        kwargs.update(pool_size=2, max_overflow=3, pool_recycle=1800, pool_timeout=15)
        _return_floats_not_decimals()
    return create_engine(url, **kwargs)


_DECIMAL_CASTER_DONE = False


def _return_floats_not_decimals() -> None:
    """Make psycopg2 return NUMERIC columns as float, not Decimal.

    Postgres NUMERIC comes back as Python Decimal by default, and Decimal does
    not mix with the float constants used throughout the analytics (percentiles,
    MAD). SQLite already returns floats, so this aligns the two backends. The
    database still stores exact NUMERIC; only the Python read is float.
    """
    global _DECIMAL_CASTER_DONE
    if _DECIMAL_CASTER_DONE:
        return
    try:
        from psycopg2 import extensions
        caster = extensions.new_type(
            extensions.DECIMAL.values, "DEC2FLOAT",
            lambda value, curs: float(value) if value is not None else None,
        )
        extensions.register_type(caster)
        _DECIMAL_CASTER_DONE = True
    except Exception:
        pass  # driver missing or already handled — coercion at call sites covers it


def _clean_url(url: str) -> str:
    """Drop connection options psycopg2 rejects, so a stale saved URL still works."""
    if "postgres" not in url or "?" not in url:
        return url
    base, _, query = url.partition("?")
    kept = [
        p for p in query.split("&")
        if p and p.split("=")[0] not in {"prepare_threshold", "prepared_statement_cache_size"}
    ]
    return base + ("?" + "&".join(kept) if kept else "")


def _url_from_env_file() -> str | None:
    """Read LEA_DB_URL from a local .env, so a saved Supabase target sticks."""
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return None
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("LEA_DB_URL=") and not line.strip().startswith("#"):
            return line.partition("=")[2].strip() or None
    return None


def dialect_name(engine: Engine) -> str:
    if engine.dialect.name == "mssql":
        return "mssql"
    if engine.dialect.name in ("postgresql", "postgres"):
        return "postgres"
    return "sqlite"


# Tables that support the pipeline itself rather than the business domain.
# `load_log` is what makes re-running safe: every file is hashed on arrival,
# and a hash already present means the file has been loaded before.
META_DDL = {
    "sqlite": """
CREATE TABLE IF NOT EXISTS load_log (
    load_id           TEXT NOT NULL PRIMARY KEY,
    source_file       TEXT NOT NULL,
    content_sha256    TEXT NOT NULL,
    firm_id           TEXT,
    recipe            TEXT,
    target_table      TEXT,
    rows_read         INTEGER,
    rows_written      INTEGER,
    rows_rejected     INTEGER,
    status            TEXT NOT NULL,
    message           TEXT,
    loaded_by         TEXT,
    ingested_at_utc   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_load_log_hash ON load_log (content_sha256);

CREATE TABLE IF NOT EXISTS bronze_raw_cells (
    load_id     TEXT NOT NULL,
    sheet_name  TEXT NOT NULL,
    row_index   INTEGER NOT NULL,
    col_index   INTEGER NOT NULL,
    cell_value  TEXT,
    value_type  TEXT
);
CREATE INDEX IF NOT EXISTS ix_bronze_load ON bronze_raw_cells (load_id);

CREATE TABLE IF NOT EXISTS dq_result (
    load_id      TEXT NOT NULL,
    check_name   TEXT NOT NULL,
    severity     TEXT NOT NULL,
    row_index    INTEGER,
    column_name  TEXT,
    detail       TEXT,
    checked_at_utc TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_dq_load ON dq_result (load_id);
""",
}
META_DDL["mssql"] = (
    META_DDL["sqlite"]
    .replace("TEXT NOT NULL PRIMARY KEY", "NVARCHAR(64) NOT NULL PRIMARY KEY")
    .replace("TEXT", "NVARCHAR(MAX)")
    .replace("INTEGER", "INT")
)
# Postgres accepts the SQLite DDL almost verbatim (TEXT, INTEGER, and
# CREATE INDEX IF NOT EXISTS are all valid), so it maps cleanly.
META_DDL["postgres"] = META_DDL["sqlite"]


def init_db(engine: Engine, dbml_path: str | Path | None = None) -> list[str]:
    """Create every table: the 33 from DBML plus the pipeline's own."""
    from .schema_map import DISPOSITION_CODES, EXTRA_TABLES_DDL

    dialect = dialect_name(engine)
    tables = parse_dbml(dbml_path or DEFAULT_DBML)

    statements = (
        _split(schema_ddl(tables, dialect))
        + _split(EXTRA_TABLES_DDL[dialect])
        + _split(META_DDL[dialect])
    )
    with engine.begin() as conn:
        for statement in statements:
            conn.execute(text(statement))

        for code, label, is_settled, description in DISPOSITION_CODES:
            conn.execute(
                text(
                    "INSERT INTO ref_disposition_code "
                    "(code, label, is_settled, description) "
                    "SELECT :c, :l, :s, :d WHERE NOT EXISTS "
                    "(SELECT 1 FROM ref_disposition_code WHERE code = :c)"
                ),
                {"c": code, "l": label, "s": is_settled, "d": description},
            )

    return sorted(tables)


def _split(script: str) -> list[str]:
    return [s.strip() for s in script.split(";") if s.strip()]
