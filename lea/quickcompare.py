"""Quick Compare — screen an incoming firm without adding it to the database.

Distinct from the Load flow, which persists a firm. Here the dropped files are
parsed into a throwaway local database, the firm-level features are computed,
those features are scored against the real portfolio baseline, and the scratch
database is deleted. Nothing about the incoming firm is written to the live
(Supabase) database — it is a look, not a commit.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from sqlalchemy.engine import Engine

from .db import get_engine
from .demo import ensure_ready
from .detect import Screening, screen_values
from .features import read_features
from .firms import register_firm
from .load import commit_plan, plan_file
from .metrics import _compute


def quick_compare(
    main_engine: Engine, file_paths: list[str | Path], firm_name: str = "Incoming firm"
) -> tuple[Screening, dict, list[dict]]:
    """Return (screening, target_feature_values, per_sheet_summaries).

    The incoming firm is never written to `main_engine`; only the portfolio
    baseline is read from it.
    """
    scratch_path = tempfile.mktemp(suffix=".db", prefix="lea_quickcompare_")
    scratch = get_engine(f"sqlite:///{scratch_path}")
    try:
        ensure_ready(scratch, seed=False)
        firm = register_firm(scratch, firm_name)

        summaries: list[dict] = []
        for path in file_paths:
            plan = plan_file(scratch, path, firm.firm_id)
            summaries += commit_plan(scratch, plan, firm.firm_id, "quickcompare")

        values, _dominant = _compute(scratch, firm.firm_id)
        portfolio = read_features(main_engine, in_portfolio=True)
        screening = screen_values(values, portfolio, firm.firm_id, firm_name)
        return screening, values, summaries
    finally:
        scratch.dispose()
        try:
            os.unlink(scratch_path)
        except OSError:
            pass


def portfolio_available(main_engine: Engine) -> int:
    """How many baseline firms exist to compare against."""
    return len(read_features(main_engine, in_portfolio=True))
