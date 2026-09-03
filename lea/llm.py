"""Provider-agnostic LLM adapter (OpenAI-compatible chat completions).

One code path talks to any OpenAI-compatible endpoint — Inworld, Google Gemini,
Groq, OpenAI, a local model — selected purely by configuration:

    LEA_LLM_BASE_URL   e.g. https://api.inworld.ai/v1
                            https://generativelanguage.googleapis.com/v1beta/openai
                            https://api.groq.com/openai/v1
    LEA_LLM_API_KEY    the provider key
    LEA_LLM_MODEL      e.g. inworld/<router-id>, gemini-2.0-flash, llama-3.3-70b-versatile

Every call returns None on any failure (missing config, network, bad JSON) so
the callers fall back to their deterministic offline behaviour. The LLM is
always an optional accelerator, never a hard dependency.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request

_TIMEOUT = 45
_RETRIES = 3  # free tiers (e.g. Gemini) return transient 503s under load


def config() -> tuple[str | None, str | None, str | None]:
    return (
        os.environ.get("LEA_LLM_BASE_URL") or None,
        os.environ.get("LEA_LLM_API_KEY") or None,
        os.environ.get("LEA_LLM_MODEL") or None,
    )


def is_configured() -> bool:
    return all(config())


def provider_label() -> str:
    base, _, model = config()
    if not base:
        return "Not configured (offline mode)"
    host = re.sub(r"^https?://", "", base).split("/")[0]
    return f"{host} · {model or 'no model set'}"


def complete(prompt: str, system: str | None = None, max_tokens: int = 800) -> str | None:
    base, key, model = config()
    if not (base and key and model):
        return None

    messages = ([{"role": "system", "content": system}] if system else [])
    messages.append({"role": "user", "content": prompt})
    body = json.dumps({"model": model, "messages": messages, "max_tokens": max_tokens})

    request = urllib.request.Request(
        base.rstrip("/") + "/chat/completions",
        data=body.encode("utf-8"),
        method="POST",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    for attempt in range(_RETRIES):
        try:
            with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
                data = json.load(response)
            return data["choices"][0]["message"].get("content")
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 500, 502, 503, 529) and attempt < _RETRIES - 1:
                time.sleep(0.6 * (attempt + 1))  # brief backoff, then retry
                continue
            return None
        except Exception:
            if attempt < _RETRIES - 1:
                time.sleep(0.6 * (attempt + 1))
                continue
            return None
    return None  # exhausted retries → caller uses its offline fallback


def complete_json(prompt: str, system: str | None = None, max_tokens: int = 1500):
    """Return parsed JSON from the model, or None if unavailable/unparseable."""
    text = complete(
        prompt + "\n\nReturn ONLY valid JSON — no prose, no markdown fences.",
        system, max_tokens,
    )
    if not text:
        return None
    match = re.search(r"\{.*\}|\[.*\]", text, re.DOTALL)
    try:
        return json.loads(match.group(0) if match else text)
    except Exception:
        return None


def health_check() -> tuple[bool, str]:
    """A tiny live call to confirm the configured provider works."""
    if not is_configured():
        return False, "Not configured — set base URL, key, and model."
    result = complete("Reply with the single word: ok", max_tokens=5)
    if result is None:
        return False, "No response — check the key, model string, and any required credits."
    return True, f"Working — model replied: {result.strip()[:40]}"


# Ready-made settings for the common free/compatible providers.
PROVIDER_PRESETS = {
    "Google Gemini (free tier)": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "model": "gemini-flash-latest",
        "note": "Free API key at aistudio.google.com. 'flash-latest' stays current "
                "so it won't retire out from under you.",
    },
    "Groq (free tier)": {
        "base_url": "https://api.groq.com/openai/v1",
        "model": "llama-3.3-70b-versatile",
        "note": "Free key at console.groq.com. Very fast.",
    },
    "Inworld (needs credits)": {
        "base_url": "https://api.inworld.ai/v1",
        "model": "inworld/<your-router-id>",
        "note": "Create a Router in the Inworld portal and add credits; put its id in the model.",
    },
}
