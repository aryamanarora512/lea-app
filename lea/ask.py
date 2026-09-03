"""Ask-a-question layer for the incoming-firm comparison.

The user asks in plain language ("how does the attorney salary compare to the
database?"); the system maps that to one monitored metric, computes the
incoming firm's value against the portfolio baseline, and answers with the real
numbers. The model — when used — only picks the metric and phrases the result;
it never produces a number. Offline, keyword matching picks the metric and a
template phrases it, so the feature works with no API key.
"""

from __future__ import annotations

import os

from .detect import AMBER, GREEN, NO_BASELINE, NO_DATA, RED, _score_metric
from .features import METRICS, Metric

# Extra words that should point at a given metric, beyond its label.
_SYNONYMS: dict[str, set[str]] = {
    "headcount": {"headcount", "size", "employees", "staff", "people", "big", "grow"},
    "attorney_to_staff_ratio": {"ratio", "leverage", "support"},
    "avg_attorney_salary": {"salary", "pay", "compensation", "comp", "wage"},
    "comp_concentration_pct": {"concentrat", "rainmaker", "key person", "top earner"},
    "pct_contractors": {"contractor", "1099", "contract", "freelance"},
    "total_cases": {"cases", "caseload", "volume", "book", "matters"},
    "settlement_rate": {"settlement rate", "settle", "settled", "win"},
    "drop_rate": {"drop", "dropped", "attrition", "abandon"},
    "practice_concentration_pct": {"practice", "diversification", "special"},
    "software_tool_count": {"software", "tools", "tech", "technology", "systems"},
    "diligence_completeness_pct": {"diligence", "questions", "answered", "complete"},
    "office_count": {"office", "offices", "real estate", "location", "footprint", "property"},
}


def _tokens(text: str) -> set[str]:
    import re
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def resolve_metric(question: str) -> Metric | None:
    """Best-matching monitored metric for a question, or None."""
    q_tokens = _tokens(question)
    q_lower = question.lower()
    best, best_score = None, 0

    for metric in METRICS:
        label_tokens = _tokens(metric.label)
        score = len(label_tokens & q_tokens)
        for syn in _SYNONYMS.get(metric.key, set()):
            if syn in q_lower:
                # Weight specific/multi-word synonyms above short generic ones.
                score += 2 if (" " in syn or len(syn) >= 8) else 1
        if score > best_score:
            best, best_score = metric, score
    return best if best_score > 0 else None


def _verdict_phrase(flag: str) -> str:
    return {
        RED: "outside the portfolio's range — a red flag worth investigating",
        AMBER: "in the tail of the portfolio — worth a look",
        GREEN: "in line with the portfolio",
    }.get(flag, "")


# Phrases that ask for a whole-firm verdict rather than one metric.
_ASSESSMENT_TRIGGERS = (
    "red flag", "redflag", "anomal", "concern", "worth", "acquir", "buy",
    "overall", "overview", "assessment", "should we", "of note", "notable",
    "risk", "worried", "summary", "anything wrong", "any issues", "any flags",
    "before we", "diligence overall",
)


def is_assessment(question: str) -> bool:
    q = question.lower()
    return any(t in q for t in _ASSESSMENT_TRIGGERS)


def full_assessment(target_values: dict, portfolio: list[dict],
                    firm_name: str, use_ai: bool) -> str:
    """A conversational whole-firm verdict: red flags and what to investigate."""
    from . import narrate
    from .detect import screen_values

    screening = screen_values(target_values, portfolio, "incoming", firm_name)
    verdict_line = {
        "investigate": f"**Yes — {firm_name} has red flags to investigate before "
                       "LEA proceeds with an acquisition.**",
        "review": f"**A few things about {firm_name} are worth a closer look "
                  "before acquiring.**",
        "in line": f"**No red flags — every measured metric for {firm_name} is in "
                   "line with the portfolio.**",
    }[screening.verdict]

    body, _ = narrate.summarize(screening, use_ai=use_ai)
    return f"{verdict_line}\n\n{body}"


def answer(question: str, target_values: dict, portfolio: list[dict],
           use_ai: bool = False, firm_name: str = "the incoming firm") -> str:
    if is_assessment(question):
        return full_assessment(target_values, portfolio, firm_name, use_ai)

    metric = resolve_metric(question)
    if metric is None:
        names = ", ".join(m.label.lower() for m in METRICS)
        return ("I can compare any of these for the incoming firm: "
                f"{names}. Try naming one — for example, \"attorney salary\".")

    result = _score_metric(metric, target_values.get(metric.key), portfolio)

    if result.flag == NO_DATA:
        return (f"The incoming firm's files don't include {metric.label.lower()}, "
                "so there's nothing to compare on that one.")
    if result.flag == NO_BASELINE or result.median is None:
        return (f"The incoming firm's {metric.label.lower()} is "
                f"{metric.format(result.value)}, but there's no portfolio "
                "baseline loaded to compare against yet. Add portfolio firms, or "
                "use Load sample data on the Settings page.")

    direction = "above" if result.value > result.median else "below"
    core = (
        f"The incoming firm's {metric.label.lower()} is "
        f"{metric.format(result.value)}, {direction} the portfolio median of "
        f"{metric.format(result.median)} (range {metric.format(result.vmin)}–"
        f"{metric.format(result.vmax)} across {result.n} firms). "
        f"That's {_verdict_phrase(result.flag)}."
    )
    if result.flag in (RED, AMBER):
        core += f" {metric.why}"

    if use_ai:
        return _maybe_ai_polish(question, core)
    return core


def _maybe_ai_polish(question: str, grounded_answer: str) -> str:
    """Optionally let the model reword the grounded answer — numbers unchanged."""
    import re

    from . import llm
    if not llm.is_configured():
        return grounded_answer

    allowed = set(re.findall(r"[\d,.]+", grounded_answer))
    prompt = (
        "Reword this answer to a deal-team member's question in one or two "
        "natural sentences. Keep every number and figure EXACTLY as given — do "
        "not add, drop, or change any number.\n\n"
        f"Question: {question}\nAnswer to reword: {grounded_answer}"
    )
    text = llm.complete(prompt, max_tokens=800)
    if not text:
        return grounded_answer
    text = text.strip()

    produced = set(re.findall(r"[\d,.]+", text))
    if text and produced.issubset(allowed | {","}):
        return text
    return grounded_answer  # a number didn't trace back — keep the grounded one
