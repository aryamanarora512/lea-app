"""Turn detection results into plain language for a non-technical reader.

Two modes, same guarantee: the numbers are never invented.

* Template mode (default, no API key needed) fills a sentence per flagged
  metric from the computed result. Runs offline; nothing can hallucinate
  because there is no model.

* AI mode (optional, needs an Anthropic key) asks Claude Haiku to weave the
  same facts into a short paragraph. The model is given ONLY the computed
  numbers and is forbidden from introducing any others. Every number in its
  output is then checked against the allowed set; if a single one fails to
  match, the AI text is discarded and the template is used instead.

So the statistics are always ground truth; the model, when used, only phrases.
"""

from __future__ import annotations

import os
import re

from .detect import AMBER, NO_DATA, RED, MetricResult, Screening

_TOLERANCE = 0.05  # 5% rounding tolerance when matching numbers back to source


def _position_phrase(r: MetricResult) -> str:
    if r.method == "rank_range":
        if r.value < (r.vmin or 0):
            return f"below all {r.n} portfolio firms"
        if r.value > (r.vmax or 0):
            return f"above all {r.n} portfolio firms"
        return f"in the {'top' if r.direction == 'above' else 'bottom'} of the range"
    if r.percentile is not None:
        if r.direction == "above":
            return f"higher than {r.percentile:.0f}% of the portfolio"
        return f"lower than {100 - r.percentile:.0f}% of the portfolio"
    return "outside the usual range"


def bullet(r: MetricResult) -> str:
    m = r.metric
    value = m.format(r.value)
    median = m.format(r.median)
    return (
        f"**{m.label}: {value}** — {_position_phrase(r)} "
        f"(portfolio median {median}, across {r.n} firms). {m.why}"
    )


def template_summary(screening: Screening) -> str:
    flagged = screening.reds + screening.ambers
    if not flagged:
        return (
            f"Every measured metric for **{screening.firm_name}** sits within the "
            f"range of the current portfolio. Nothing stands out as anomalous on "
            f"the data loaded so far."
        )

    lead = (
        f"**{screening.firm_name}** has {len(screening.reds)} metric(s) outside the "
        f"portfolio's range and {len(screening.ambers)} in the tail. The items "
        f"most worth a closer look:"
    )
    lines = [lead, ""]
    for r in sorted(flagged, key=lambda x: (x.flag != RED, x.metric.label)):
        lines.append("- " + bullet(r))

    gaps = [r for r in screening.results if r.flag == NO_DATA]
    if gaps:
        names = ", ".join(r.metric.label.lower() for r in gaps)
        lines += ["", f"_Not assessed (no source data): {names}._"]
    return "\n".join(lines)


# --- optional AI phrasing -------------------------------------------------


def _allowed_numbers(screening: Screening) -> set[float]:
    allowed: set[float] = set()
    for r in screening.reds + screening.ambers:
        for candidate in (r.value, r.median, r.vmin, r.vmax, r.percentile, r.n):
            if candidate is not None:
                allowed.add(round(float(candidate), 2))
    return allowed


def _numbers_in(sentence: str) -> list[float]:
    found = []
    for token in re.findall(r"-?\d[\d,]*\.?\d*", sentence):
        try:
            found.append(float(token.replace(",", "")))
        except ValueError:
            continue
    return found


def _grounded(text: str, allowed: set[float]) -> bool:
    """Every number in the text must correspond to a computed value."""
    for number in _numbers_in(text):
        ok = any(
            abs(number - a) <= max(_TOLERANCE * abs(a), 0.5) or
            abs(number - a * 100) <= 0.5 or abs(number - a / 100) <= 0.5
            for a in allowed
        )
        if not ok and number not in {y for y in range(1990, 2031)}:
            return False
    return True


def ai_summary(screening: Screening) -> tuple[str, str]:
    """Return (text, source) where source is 'ai' or 'template' after fallback."""
    from . import llm
    if not llm.is_configured():
        return template_summary(screening), "template"

    facts = "\n".join(bullet(r) for r in screening.reds + screening.ambers)
    if not facts:
        return template_summary(screening), "template"

    prompt = (
        "You are briefing a private-equity deal team on an incoming law-firm "
        "acquisition target. Below are the metrics our system flagged as unusual "
        "versus our existing portfolio, with the exact numbers.\n\n"
        "Write 3-5 sentences a non-technical reader can act on. Use ONLY the "
        "numbers given — never introduce a number that is not below. Lead with "
        "what to investigate first. Do not invent context.\n\n"
        f"Target: {screening.firm_name}\n\n{facts}"
    )
    text = llm.complete(prompt, max_tokens=1000)
    if not text:
        return template_summary(screening), "template"
    text = text.strip()

    if not _grounded(text, _allowed_numbers(screening)):
        # A number the model produced does not trace to our data — do not trust it.
        return template_summary(screening), "template"
    return text, "ai"


def summarize(screening: Screening, use_ai: bool = False) -> tuple[str, str]:
    if use_ai:
        return ai_summary(screening)
    return template_summary(screening), "template"
