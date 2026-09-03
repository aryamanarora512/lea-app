"""Anomaly detection against the portfolio baseline.

The method adapts to how many portfolio firms exist, because that is the honest
thing to do:

* With a healthy baseline (>= MIN_ROBUST_N firms) it uses the modified
  z-score — median plus MAD (median absolute deviation). Median and MAD are
  used instead of mean and standard deviation because a single outlier — the
  very thing we are hunting — corrupts the mean and inflates the standard
  deviation, letting the outlier hide itself. The median barely moves.

* With a small baseline (the current reality: fewer than ten firms) a z-score
  would be statistical theatre. Instead it reports the target's rank and
  whether it falls outside the range every portfolio firm sits in — a
  distribution-free statement a partner can act on ("below all 8 of our
  firms") without pretending eight numbers define a normal distribution.

Either way the output carries the sample size, so nothing is ever presented as
more certain than the data supports.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

from sqlalchemy.engine import Engine

from .features import METRICS, Metric, read_features, read_one

MIN_ROBUST_N = 8  # below this, use rank/range instead of a z-score
MAD_SCALE = 1.4826  # makes MAD a consistent estimator of the std dev under normality

RED = "red"      # outside the portfolio's experience — investigate
AMBER = "amber"  # in the tail — worth a note
GREEN = "green"  # in line with the portfolio
NO_DATA = "no_data"        # the target has no value for this metric
NO_BASELINE = "no_baseline"  # the portfolio has too few values to compare


@dataclass
class MetricResult:
    metric: Metric
    value: float | None
    n: int
    median: float | None
    mad: float | None
    vmin: float | None
    vmax: float | None
    percentile: float | None  # share of portfolio at or below the target
    mod_z: float | None
    method: str
    flag: str

    @property
    def direction(self) -> str:
        if self.value is None or self.median is None:
            return "—"
        return "above" if self.value > self.median else "below"


@dataclass
class Screening:
    firm_id: str
    firm_name: str
    results: list[MetricResult]

    @property
    def reds(self) -> list[MetricResult]:
        return [r for r in self.results if r.flag == RED]

    @property
    def ambers(self) -> list[MetricResult]:
        return [r for r in self.results if r.flag == AMBER]

    @property
    def verdict(self) -> str:
        if self.reds:
            return "investigate"
        if self.ambers:
            return "review"
        return "in line"

    @property
    def headline(self) -> str:
        r, a = len(self.reds), len(self.ambers)
        if r:
            return f"{r} metric{'s' if r != 1 else ''} outside the portfolio range"
        if a:
            return f"{a} metric{'s' if a != 1 else ''} in the tail — worth a look"
        return "Every measured metric is in line with the portfolio"


def screen_values(
    target_values: dict, portfolio: list[dict], firm_id: str, firm_name: str
) -> Screening:
    """Score a feature vector against a portfolio — works for stored or
    freshly-computed (quick-compare) firms alike."""
    results = [
        _score_metric(metric, target_values.get(metric.key), portfolio)
        for metric in METRICS
    ]
    return Screening(firm_id, firm_name, results)


def screen_firm(engine: Engine, target_firm_id: str) -> Screening:
    target = read_one(engine, target_firm_id)
    if target is None:
        raise ValueError(f"No features computed for firm {target_firm_id}.")

    portfolio = [
        f for f in read_features(engine, in_portfolio=True)
        if f["firm_id"] != target_firm_id
    ]
    return screen_values(
        target, portfolio, target_firm_id, target.get("firm_name") or target_firm_id
    )


def _score_metric(metric: Metric, value, portfolio: list[dict]) -> MetricResult:
    # float() guards against Postgres returning Decimal for NUMERIC columns,
    # which will not mix with the float constants used in the robust scoring.
    values = sorted(
        float(f[metric.key]) for f in portfolio if f.get(metric.key) is not None
    )
    if value is not None:
        value = float(value)
    n = len(values)

    base = MetricResult(
        metric=metric, value=value, n=n, median=None, mad=None,
        vmin=None, vmax=None, percentile=None, mod_z=None,
        method="none", flag=NO_DATA,
    )

    if value is None:
        return base  # coverage gap — reported honestly, never guessed
    if n < 2:
        base.flag = NO_BASELINE
        return base

    median = statistics.median(values)
    vmin, vmax = values[0], values[-1]
    at_or_below = sum(1 for v in values if v <= value)
    percentile = 100 * at_or_below / n

    base.median, base.vmin, base.vmax, base.percentile = median, vmin, vmax, percentile

    if n >= MIN_ROBUST_N:
        return _robust_score(base, values, median)
    return _rank_score(base, value, vmin, vmax, percentile)


def _robust_score(r: MetricResult, values: list[float], median: float) -> MetricResult:
    """Modified z-score on median + MAD; IQR as a fallback when MAD is zero."""
    mad = statistics.median(abs(v - median) for v in values) * MAD_SCALE
    r.mad = mad
    r.method = "modified_zscore"

    if mad > 0:
        r.mod_z = 0.6745 * (r.value - median) / (mad / MAD_SCALE)
        magnitude = abs(r.mod_z)
        r.flag = RED if magnitude > 3.5 else AMBER if magnitude > 2.5 else GREEN
        return r

    # MAD collapses when most firms share a value — fall back to the spread.
    q1, q3 = _quartiles(values)
    iqr = q3 - q1
    r.method = "iqr"
    if iqr > 0:
        if r.value < q1 - 1.5 * iqr or r.value > q3 + 1.5 * iqr:
            r.flag = RED
        elif r.value < q1 or r.value > q3:
            r.flag = AMBER
        else:
            r.flag = GREEN
    else:
        r.flag = GREEN if r.value == median else RED
    return r


def _rank_score(r: MetricResult, value, vmin, vmax, percentile) -> MetricResult:
    """Small-baseline path: distribution-free rank and range containment."""
    r.method = "rank_range"
    if value < vmin or value > vmax:
        r.flag = RED  # outside the experience of every portfolio firm
    elif percentile <= 12.5 or percentile >= 87.5:
        r.flag = AMBER  # in the outer eighth of the observed spread
    else:
        r.flag = GREEN
    return r


def _quartiles(values: list[float]) -> tuple[float, float]:
    mid = len(values) // 2
    lower = values[:mid]
    upper = values[mid + 1:] if len(values) % 2 else values[mid:]
    return statistics.median(lower), statistics.median(upper)


# --- validation harness ---------------------------------------------------


def run_validation(engine: Engine, perturbations=(1.0, 2.0, 3.0, 4.0)) -> dict:
    """Leave-one-out injection test: how often would we catch a known shift?

    Take each portfolio firm out, push one metric by a multiple of the
    baseline spread, and check whether the detector flags it. Reported
    alongside a false-positive rate on the untouched firms so a reviewer can
    judge how much to trust a flag — and tune sensitivity to their tolerance.
    """
    portfolio = read_features(engine, in_portfolio=True)
    if len(portfolio) < 3:
        return {"n_firms": len(portfolio), "note": "Too few firms to validate."}

    detected = {p: 0 for p in perturbations}
    trials = {p: 0 for p in perturbations}
    false_positives = 0
    fp_trials = 0

    from .features import METRIC_BY_KEY

    for metric in METRIC_BY_KEY.values():
        values = sorted(
            f[metric.key] for f in portfolio if f.get(metric.key) is not None
        )
        if len(values) < 4:
            continue
        median = statistics.median(values)
        spread = statistics.median(abs(v - median) for v in values) * MAD_SCALE
        if spread <= 0:
            continue

        others = [{metric.key: v} for v in values]

        # False-positive rate: score untouched firms against their peers.
        for i, actual in enumerate(values):
            peers = others[:i] + others[i + 1:]
            res = _score_metric(metric, actual, peers)
            fp_trials += 1
            false_positives += res.flag in (RED, AMBER)

        # Detection rate: shift a firm by k * spread and see if we catch it.
        for k in perturbations:
            for i, actual in enumerate(values):
                peers = others[:i] + others[i + 1:]
                res = _score_metric(metric, actual + k * spread, peers)
                trials[k] += 1
                detected[k] += res.flag in (RED, AMBER)

    return {
        "n_firms": len(portfolio),
        "false_positive_rate": round(100 * false_positives / max(fp_trials, 1), 1),
        "detection_rate": {
            f"{k:g}x spread": round(100 * detected[k] / max(trials[k], 1), 1)
            for k in perturbations
        },
    }
