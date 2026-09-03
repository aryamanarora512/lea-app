"""Firm registry: minting and looking up the 4-digit firm_id.

No incoming Excel file contains a firm identifier, so firm_id can never be
inferred from file contents. It is assigned here, sequentially in the order
firms are registered (0001, 0002, ...), and the GUI forces the user to pick a
firm before any load can proceed.

Deal codenames matter: the sample data alone contains "Project Palm",
"Project Wolf", and "Ellis Law Corporation". Storing the codename alongside the
legal name keeps a target's files from being loaded under two different ids.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.engine import Engine

FIRM_ID_WIDTH = 4


@dataclass
class Firm:
    firm_id: str
    firm_name: str
    state: str | None = None
    city: str | None = None
    primary_practice: str | None = None
    notes: str | None = None

    @property
    def label(self) -> str:
        location = f" ({self.city}, {self.state})" if self.state else ""
        return f"{self.firm_id} — {self.firm_name}{location}"


def list_firms(engine: Engine) -> list[Firm]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT firm_id, firm_name, state, city, primary_practice, notes "
                "FROM firms ORDER BY firm_id"
            )
        ).all()
    return [Firm(*row) for row in rows]


def next_firm_id(engine: Engine) -> str:
    """Return the next unused id, zero-padded to 4 digits."""
    with engine.connect() as conn:
        existing = conn.execute(text("SELECT firm_id FROM firms")).scalars().all()

    numeric = [int(v) for v in existing if str(v).isdigit()]
    return str(max(numeric, default=0) + 1).zfill(FIRM_ID_WIDTH)


def register_firm(
    engine: Engine,
    firm_name: str,
    state: str | None = None,
    city: str | None = None,
    primary_practice: str | None = None,
    notes: str | None = None,
) -> Firm:
    """Create a new firm and return it with its freshly minted id."""
    firm_name = firm_name.strip()
    if not firm_name:
        raise ValueError("Firm name is required.")

    with engine.connect() as conn:
        clash = conn.execute(
            text("SELECT firm_id FROM firms WHERE LOWER(firm_name) = LOWER(:n)"),
            {"n": firm_name},
        ).scalar()
    if clash:
        raise ValueError(f"'{firm_name}' is already registered as firm {clash}.")

    firm = Firm(
        firm_id=next_firm_id(engine),
        firm_name=firm_name,
        state=(state or None),
        city=(city or None),
        primary_practice=(primary_practice or None),
        notes=(notes or None),
    )

    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO firms "
                "(firm_id, firm_name, state, city, primary_practice, notes, "
                " ingested_at_utc) "
                "VALUES (:firm_id, :firm_name, :state, :city, :primary_practice, "
                ":notes, :ts)"
            ),
            {**firm.__dict__, "ts": _utcnow()},
        )
    return firm


def _utcnow() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")
