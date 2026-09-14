"""The only module that knows which model provider is in use.

The graph, the tools, the report schema and the verify node are all provider-independent,
so switching provider is one environment variable and no code change. That matters here
because the project runs on free tiers: Groq today, Ollama offline, Gemini if the limits
bite.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from .settings import Settings

log = logging.getLogger(__name__)

_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


def available_models(provider: str) -> list[str]:
    """What the account can actually use. A model id that has been retired is the single most
    likely reason a correctly configured agent fails, and the provider knows the answer, so
    the error message should carry it rather than sending the operator to a docs page."""
    try:
        import os

        import httpx

        if provider == "groq":
            r = httpx.get("https://api.groq.com/openai/v1/models",
                          headers={"Authorization": "Bearer " + os.environ.get("GROQ_API_KEY", "")},
                          timeout=15)
            r.raise_for_status()
            return sorted(m["id"] for m in r.json().get("data", []) if m.get("active", True))
    except Exception:  # noqa: BLE001 - a failed lookup must not mask the original error
        pass
    return []


def check_model(settings: Settings) -> str | None:
    """Returns a problem description, or None when the configured model is usable."""
    models = available_models(settings.provider.lower())
    if models and settings.model not in models:
        return (f"model {settings.model!r} is not available on this account. "
                f"Set FRAUDGRAPH_LLM_MODEL to one of: {', '.join(models)}")
    return None


def build_llm(settings: Settings):
    """Returns a LangChain chat model. Raises with an actionable message if the provider
    package or its credential is missing, rather than failing deep inside the graph."""
    provider = settings.provider.lower()

    if provider == "groq":
        try:
            from langchain_groq import ChatGroq
        except ImportError as e:  # pragma: no cover
            raise RuntimeError("provider 'groq' needs langchain-groq: uv sync") from e
        import os
        if not os.environ.get("GROQ_API_KEY"):
            raise RuntimeError(
                "GROQ_API_KEY is not set. Get a free key at console.groq.com and export it. "
                "To run without any key, set FRAUDGRAPH_LLM_PROVIDER=ollama."
            )
        return ChatGroq(model=settings.model, temperature=settings.temperature, max_retries=3)

    if provider == "ollama":
        try:
            from langchain_ollama import ChatOllama
        except ImportError as e:  # pragma: no cover
            raise RuntimeError("provider 'ollama' needs langchain-ollama: uv sync --extra ollama") from e
        return ChatOllama(model=settings.model, temperature=settings.temperature,
                          base_url=settings.ollama_base_url)

    if provider == "gemini":
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI
        except ImportError as e:  # pragma: no cover
            raise RuntimeError("provider 'gemini' needs langchain-google-genai: uv sync --extra gemini") from e
        return ChatGoogleGenerativeAI(model=settings.model, temperature=settings.temperature)

    raise RuntimeError(f"unknown FRAUDGRAPH_LLM_PROVIDER {settings.provider!r}; use groq, ollama or gemini")


def parse_json_object(text: str) -> dict[str, Any] | None:
    """Last-resort extraction of a JSON object from a model's prose.

    Mid-tier models on free tiers wrap JSON in markdown fences or add a sentence before it
    often enough that failing the whole run over it would be a waste of a rate-limited
    call. The report is validated against the schema either way, so a lenient parse cannot
    let a malformed report through.
    """
    if not text:
        return None
    stripped = text.strip()
    for candidate in (stripped, _fenced(stripped)):
        if not candidate:
            continue
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            continue
    match = _JSON_BLOCK.search(stripped)
    if match:
        try:
            parsed = json.loads(match.group(0))
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None
    return None


def _fenced(text: str) -> str | None:
    if "```" not in text:
        return None
    parts = text.split("```")
    if len(parts) < 2:
        return None
    body = parts[1]
    if body.startswith("json"):
        body = body[4:]
    return body.strip()
