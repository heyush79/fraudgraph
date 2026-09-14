from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Settings:
    # --- where the facts come from -------------------------------------------------
    case_service_url: str = os.environ.get("FRAUDGRAPH_CASE_SERVICE_URL", "http://localhost:8082")
    http_timeout_s: float = float(os.environ.get("FRAUDGRAPH_HTTP_TIMEOUT", "5"))

    # --- the model -----------------------------------------------------------------
    # groq | ollama | gemini. The graph, the tools and the verify node are all
    # provider-independent; only agent/llm.py knows which one is in use.
    provider: str = os.environ.get("FRAUDGRAPH_LLM_PROVIDER", "groq")
    # Groq retires model ids as new ones land, and the set differs per account, so this is
    # a default rather than a guarantee: `llama-3.3-70b-versatile` was already gone when this
    # was first wired up. A wrong id is reported with the account's actual model list, see
    # available_models() in llm.py. 120B with a 131k context and solid tool calling.
    model: str = os.environ.get("FRAUDGRAPH_LLM_MODEL", "openai/gpt-oss-120b")
    temperature: float = float(os.environ.get("FRAUDGRAPH_LLM_TEMPERATURE", "0"))
    ollama_base_url: str = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")

    # --- budgets -------------------------------------------------------------------
    # LLD §6.1 sets the ceiling at 8. The default is 4 because the conversation is resent on
    # every turn, so cost grows quadratically in tool calls, and Groq's free tier allows
    # 8,000 tokens per minute for every model that supports tool calling. Four calls lets the
    # agent use each of its four tools once and keeps a whole case inside one minute of
    # budget; raise it on a paid tier.
    max_tool_calls: int = int(os.environ.get("FRAUDGRAPH_MAX_TOOL_CALLS", "4"))
    # How much of one tool result the model is shown. A user history is 50 decisions and a
    # graph neighbourhood can be large; the model needs the shape and the numbers, not every row.
    max_payload_chars: int = int(os.environ.get("FRAUDGRAPH_MAX_PAYLOAD_CHARS", "900"))
    # Recent decisions returned by get_user_history. Ten is enough to see a pattern.
    history_limit: int = int(os.environ.get("FRAUDGRAPH_HISTORY_LIMIT", "10"))
    # Investigations that may run at once. One, because they share a per-minute token budget
    # and running two concurrently makes both slow instead of one fast.
    max_concurrent: int = int(os.environ.get("FRAUDGRAPH_MAX_CONCURRENT", "1"))
    max_verify_attempts: int = int(os.environ.get("FRAUDGRAPH_MAX_VERIFY_ATTEMPTS", "2"))
    similar_k: int = int(os.environ.get("FRAUDGRAPH_SIMILAR_K", "3"))

    # --- similar-case memory -------------------------------------------------------
    chroma_path: str = os.environ.get("FRAUDGRAPH_CHROMA_PATH", "./chroma")
    chroma_collection: str = os.environ.get("FRAUDGRAPH_CHROMA_COLLECTION", "fraudgraph-reports")

    server_port: int = int(os.environ.get("FRAUDGRAPH_AGENT_PORT", "8000"))
    # How often closed cases are pulled into the similar-case index. Cases close on human
    # timescales, so minutes is the right cadence.
    index_refresh_secs: float = float(os.environ.get("FRAUDGRAPH_INDEX_REFRESH_SECS", "120"))
