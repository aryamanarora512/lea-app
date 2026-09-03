"""Database target configuration — local file vs Supabase (Postgres).

The whole app talks to whatever `get_engine()` returns, which is driven by one
connection string. This module lets a non-technical user point that string at
their Supabase project (or leave it on the bundled local file) and see, at a
glance, which database is live and whether it is reachable.

Credentials are the user's own and are stored only in a local `.env` file next
to the app. Nothing is transmitted anywhere except to the database they name.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Engine

from .db import get_engine

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
_URL_KEY = "LEA_DB_URL"


@dataclass
class ConnectionStatus:
    kind: str          # "Supabase" | "Local file" | "SQL Server"
    reachable: bool
    detail: str


def current_url() -> str | None:
    return os.environ.get(_URL_KEY) or _read_env().get(_URL_KEY)


def is_supabase(url: str | None) -> bool:
    return bool(url) and ("supabase" in url or url.startswith("postgresql"))


def normalise_supabase_url(url: str) -> str:
    """Make a pasted Supabase string safe for SQLAlchemy + psycopg2.

    Supabase shows the URL with a bare `postgres://` prefix; SQLAlchemy needs
    an explicit driver, so we rewrite it to `postgresql+psycopg2://`. We also
    strip any `prepare_threshold` option — that belongs to psycopg v3, and
    psycopg2 rejects it. The session pooler needs no prepared-statement tuning.
    """
    url = strip_unsupported_params(url.strip())
    if url.startswith("postgres://"):
        url = "postgresql+psycopg2://" + url[len("postgres://"):]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg2://" + url[len("postgresql://"):]
    return url


def strip_unsupported_params(url: str) -> str:
    """Remove connection options psycopg2 does not accept (e.g. prepare_threshold)."""
    if "?" not in url:
        return url
    base, _, query = url.partition("?")
    kept = [
        part for part in query.split("&")
        if part and part.split("=")[0] not in {"prepare_threshold", "prepared_statement_cache_size"}
    ]
    return base + ("?" + "&".join(kept) if kept else "")


def save_url(url: str) -> None:
    """Persist the connection string to the local .env (write-only to disk)."""
    env = _read_env()
    if is_supabase(url):
        url = normalise_supabase_url(url)
    env[_URL_KEY] = url
    ENV_PATH.write_text(
        "\n".join(f"{k}={v}" for k, v in env.items()) + "\n", encoding="utf-8"
    )
    os.environ[_URL_KEY] = url


def clear_url() -> None:
    env = _read_env()
    env.pop(_URL_KEY, None)
    ENV_PATH.write_text(
        "\n".join(f"{k}={v}" for k, v in env.items()) + ("\n" if env else ""),
        encoding="utf-8",
    )
    os.environ.pop(_URL_KEY, None)


def check(engine: Engine) -> ConnectionStatus:
    url = str(engine.url)
    if engine.dialect.name in ("postgresql", "postgres"):
        kind = "Supabase" if "supabase" in url or "pooler" in url else "Postgres"
    elif engine.dialect.name == "mssql":
        kind = "SQL Server"
    else:
        kind = "Local file"

    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return ConnectionStatus(kind, True, "Connected")
    except Exception as exc:  # surface the reason, don't crash the app
        return ConnectionStatus(kind, False, _short_error(exc))


def _short_error(exc: Exception) -> str:
    message = str(exc).splitlines()[0]
    if "psycopg2" in message and "No module" in message:
        return "Postgres driver missing — run: pip install psycopg2-binary"
    return message[:160]


def _read_env() -> dict[str, str]:
    if not ENV_PATH.exists():
        return {}
    out = {}
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            key, _, value = line.partition("=")
            out[key.strip()] = value.strip()
    return out


def _load_secrets_into_env() -> None:
    """Bridge Streamlit Cloud secrets into environment variables.

    On a hosted deployment (Streamlit Community Cloud) there is no writable
    `.env` on disk, and secrets must never live in the repo. Streamlit stores
    them separately and exposes them as `st.secrets`. We copy any of our known
    config keys from there into the process environment so the rest of the app
    — which only reads os.environ — works unchanged, locally or hosted.

    Safe when Streamlit is absent (tests) or no secrets are set (local dev).
    """
    try:
        import streamlit as st
        secrets = st.secrets
    except Exception:
        return
    for key in (
        "LEA_DB_URL", "LEA_LLM_BASE_URL", "LEA_LLM_API_KEY",
        "LEA_LLM_MODEL", "LEA_PII_SALT",
    ):
        try:
            value = secrets[key]
        except Exception:
            continue
        if value:
            os.environ.setdefault(key, str(value))


def load_env_into_process() -> None:
    """Call once at startup so saved config drives get_engine().

    A local `.env` (developer laptop) wins; Streamlit Cloud secrets fill in
    anything not already set. Either way the app is configured before it opens
    its first database connection.
    """
    for key, value in _read_env().items():
        os.environ.setdefault(key, value)
    _load_secrets_into_env()


def set_env(values: dict[str, str]) -> None:
    """Persist arbitrary keys to the local .env and current process."""
    env = _read_env()
    for key, value in values.items():
        if value:
            env[key] = value
            os.environ[key] = value
        else:
            env.pop(key, None)
            os.environ.pop(key, None)
    ENV_PATH.write_text(
        "\n".join(f"{k}={v}" for k, v in env.items()) + ("\n" if env else ""),
        encoding="utf-8",
    )


def get_env(key: str) -> str | None:
    return os.environ.get(key) or _read_env().get(key)
