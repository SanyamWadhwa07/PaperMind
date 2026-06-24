"""LangChain chat-model provider layer for the summarization graph.

Hybrid, multi-provider strategy with automatic fallback:
  - Gemini  : Google AI free tier — most generous free limits (primary in prod)
  - Groq    : free tier, ultra-fast — overflow when Gemini is rate-limited
  - Ollama  : local, offline, private — last-resort floor (runs on a small GPU)

Selection / ordering is driven by environment so the same graph runs everywhere:

    PAPERMIND_LLM_PROVIDER = gemini | groq | ollama | auto   (default: auto)
        also reads the legacy PAPERMIND_LLM_BACKEND.
        auto  -> ordered by availability: gemini (if key) → groq (if key) → ollama
        named -> that provider is PRIMARY; the others become fallbacks
        PAPERMIND_LLM_STRICT=1 -> use ONLY the named provider (no fallback)

Two tiers spend latency/quota wisely:
    - "fast"  : per-section map summaries + extraction
    - "smart" : final synthesis / reduce

Model ids per provider/tier are overridable via
    PAPERMIND_<PROVIDER>_<TIER>_MODEL   e.g. PAPERMIND_GROQ_SMART_MODEL.

Public API:
    get_model_chain(tier)  -> [BaseChatModel, ...]  primary first, then fallbacks
    get_chat_model(tier)   -> primary BaseChatModel (back-compat)
    get_provider_info()    -> diagnostics
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Literal, Optional, Dict, Any, List, Tuple

import structlog

logger = structlog.get_logger(__name__)

Tier = Literal["fast", "smart"]

PROVIDER_PRIORITY: Tuple[str, ...] = ("gemini", "groq", "ollama")

# ── Defaults (override any of these via env) ───────────────────────────────────
DEFAULTS: Dict[str, Dict[str, str]] = {
    "gemini": {
        # Gemini free tier is the most generous; flash is fast + strong enough.
        "smart": "gemini-2.0-flash",
        "fast": "gemini-2.0-flash",
    },
    "groq": {
        "smart": "llama-3.3-70b-versatile",
        "fast": "llama-3.1-8b-instant",
    },
    "ollama": {
        # Tuned for a ~4GB GPU.
        "smart": "qwen2.5:7b-instruct-q4_K_M",
        "fast": "qwen2.5:3b",
    },
}

_TIER_TEMPERATURE: Dict[Tier, float] = {"fast": 0.2, "smart": 0.3}


# ── Availability + ordering ─────────────────────────────────────────────────────

def _gemini_key() -> Optional[str]:
    return os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")


def _provider_available(provider: str) -> bool:
    if provider == "gemini":
        return bool(_gemini_key())
    if provider == "groq":
        return bool(os.environ.get("GROQ_API_KEY"))
    if provider == "ollama":
        return True  # best-effort; may be down, but acts as last-resort
    return False


def _explicit_provider() -> Optional[str]:
    for var in ("PAPERMIND_LLM_PROVIDER", "PAPERMIND_LLM_BACKEND"):
        choice = (os.environ.get(var) or "").strip().lower()
        if choice in PROVIDER_PRIORITY:
            return choice
    return None


def provider_order() -> List[str]:
    """Ordered list of providers to try: primary first, then fallbacks."""
    explicit = _explicit_provider()
    strict = (os.environ.get("PAPERMIND_LLM_STRICT") or "").strip() in ("1", "true", "yes")

    if explicit:
        if strict:
            return [explicit]
        rest = [p for p in PROVIDER_PRIORITY if p != explicit and _provider_available(p)]
        return [explicit] + rest

    order = [p for p in PROVIDER_PRIORITY if _provider_available(p)]
    return order or ["ollama"]


def resolve_provider() -> str:
    """Primary provider name (first in the chain)."""
    return provider_order()[0]


def _model_id(provider: str, tier: Tier) -> str:
    env_key = f"PAPERMIND_{provider.upper()}_{tier.upper()}_MODEL"
    return os.environ.get(env_key) or DEFAULTS[provider][tier]


# ── Rate limiting (optional) ─────────────────────────────────────────────────────

def _maybe_rate_limiter():
    """Optional client-side request pacing for tight free-tier limits.

    Set PAPERMIND_LLM_RPS (requests/second) to enable, e.g. 1.0.
    """
    rps = os.environ.get("PAPERMIND_LLM_RPS")
    if not rps:
        return None
    try:
        from langchain_core.rate_limiters import InMemoryRateLimiter

        return InMemoryRateLimiter(
            requests_per_second=float(rps),
            check_every_n_seconds=0.1,
            max_bucket_size=int(float(rps) * 2) or 1,
        )
    except Exception:
        return None


# ── Model construction ───────────────────────────────────────────────────────────

@lru_cache(maxsize=32)
def _build_model(provider: str, tier: Tier, temperature: float, max_tokens: int):
    """Construct (and cache) a LangChain chat model for the given knobs."""
    model_id = _model_id(provider, tier)
    rate_limiter = _maybe_rate_limiter()
    max_retries = int(os.environ.get("PAPERMIND_LLM_MAX_RETRIES", "6"))

    if provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI

        # ChatGoogleGenerativeAI reads GOOGLE_API_KEY; mirror GEMINI_API_KEY if needed.
        if not os.environ.get("GOOGLE_API_KEY") and os.environ.get("GEMINI_API_KEY"):
            os.environ["GOOGLE_API_KEY"] = os.environ["GEMINI_API_KEY"]
        model = ChatGoogleGenerativeAI(
            model=model_id,
            temperature=temperature,
            max_output_tokens=max_tokens,
            max_retries=max_retries,
            timeout=120,
            rate_limiter=rate_limiter,
        )
        logger.info("llm_provider_init", provider="gemini", tier=tier, model=model_id)
        return model

    if provider == "groq":
        from langchain_groq import ChatGroq

        model = ChatGroq(
            model=model_id,
            temperature=temperature,
            max_tokens=max_tokens,
            max_retries=max_retries,
            timeout=120,
            rate_limiter=rate_limiter,
        )
        logger.info("llm_provider_init", provider="groq", tier=tier, model=model_id)
        return model

    if provider == "ollama":
        from langchain_ollama import ChatOllama

        base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
        model = ChatOllama(
            model=model_id,
            temperature=temperature,
            num_predict=max_tokens,
            num_ctx=int(os.environ.get("OLLAMA_NUM_CTX", "8192")),
            base_url=base_url,
            rate_limiter=rate_limiter,
        )
        logger.info("llm_provider_init", provider="ollama", tier=tier, model=model_id)
        return model

    raise ValueError(f"Unknown LLM provider: {provider!r}")


def get_model_chain(
    tier: Tier = "smart",
    *,
    temperature: Optional[float] = None,
    max_tokens: int = 4096,
) -> List[Any]:
    """Return chat models in priority order: [primary, *fallbacks].

    Models that fail to construct (e.g. missing optional dep) are skipped.
    """
    temp = _TIER_TEMPERATURE[tier] if temperature is None else float(temperature)
    chain: List[Any] = []
    for provider in provider_order():
        try:
            chain.append(_build_model(provider, tier, temp, int(max_tokens)))
        except Exception as e:
            logger.warning("provider_build_skipped", provider=provider, error=str(e))
    if not chain:
        # Absolute last resort so callers always get *something*.
        chain.append(_build_model("ollama", tier, temp, int(max_tokens)))
    return chain


def get_chat_model(
    tier: Tier = "smart",
    *,
    provider: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: int = 4096,
):
    """Return the primary chat model (back-compat single-model accessor)."""
    if provider:
        temp = _TIER_TEMPERATURE[tier] if temperature is None else float(temperature)
        return _build_model(provider.lower(), tier, temp, int(max_tokens))
    return get_model_chain(tier, temperature=temperature, max_tokens=max_tokens)[0]


def get_provider_info() -> Dict[str, Any]:
    """Diagnostic snapshot — surfaced via /api/health and logs."""
    order = provider_order()
    primary = order[0]
    return {
        "provider": primary,
        "chain": order,
        "available": {p: _provider_available(p) for p in PROVIDER_PRIORITY},
        "gemini_key_present": bool(_gemini_key()),
        "groq_key_present": bool(os.environ.get("GROQ_API_KEY")),
        "models": {
            "fast": _model_id(primary, "fast"),
            "smart": _model_id(primary, "smart"),
        },
        "ollama_base_url": os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434"),
    }
