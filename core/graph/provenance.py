"""Run provenance for the summarization graph: what actually produced a summary.

Two problems this solves, both of which make a quality regression unattributable.

**1. The stored model id could be a lie.** `get_provider_info()` reports the
*configured* primary provider. The graph runs behind `with_fallbacks`, so when
Gemini is rate-limited and Groq answers, "gemini-flash-latest" is what got
written to the database anyway. Provenance that is wrong is worse than absent —
it sends you looking for a Gemini regression that never happened. `UsageCollector`
records the model that *responded*, observed from the callback, not the one that
was asked first.

**2. Prompt versions rot.** A hand-bumped `PROMPT_VERSION = 3` constant is
correct exactly until the first person who edits a prompt and forgets. So the
fingerprint is *computed* from the prompt-bearing content itself:

  - the JSON schema of every structured-output model, because
    `schemas.py` states outright that "the field descriptions are part of the
    prompt … they materially affect extraction quality"; and
  - the source of the node functions that build the system/user messages.

Hashing function source means a non-prompt edit inside one of those functions
also bumps the fingerprint. That is the deliberate trade: a false "prompt
changed" costs one re-measurement, while a missed one silently invalidates every
comparison made across it.

Nothing here may fail a run. Telemetry that can break the pipeline it measures is
worse than no telemetry.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import time
from contextvars import ContextVar
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger(__name__)

# One accumulator per graph run. A ContextVar rather than a global because
# several papers are summarized concurrently in the same process (the job worker
# and the batch routes both do this), and a global would blend their token counts.
_current_run: ContextVar[Optional["RunRecorder"]] = ContextVar("papermind_run", default=None)


class RunRecorder:
    """Accumulates per-call telemetry for a single paper's summarization."""

    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []
        self.started_at = time.time()

    def record(self, **fields: Any) -> None:
        self.calls.append(fields)

    def summary(self) -> Dict[str, Any]:
        ok = [c for c in self.calls if c.get("ok")]
        models = [c.get("model") for c in ok if c.get("model")]
        # Ordered, de-duplicated: which models actually served this paper, and in
        # what order the chain fell through to them.
        observed: List[str] = []
        for m in models:
            if m not in observed:
                observed.append(m)
        return {
            "llm_calls": len(self.calls),
            "llm_calls_failed": len(self.calls) - len(ok),
            "input_tokens": sum(int(c.get("input_tokens") or 0) for c in self.calls),
            "output_tokens": sum(int(c.get("output_tokens") or 0) for c in self.calls),
            "models_observed": observed,
            "wall_seconds": round(time.time() - self.started_at, 2),
            "by_node": self._by_node(),
        }

    def _by_node(self) -> Dict[str, Dict[str, Any]]:
        out: Dict[str, Dict[str, Any]] = {}
        for c in self.calls:
            node = c.get("node") or "unknown"
            agg = out.setdefault(node, {"calls": 0, "input_tokens": 0,
                                        "output_tokens": 0, "seconds": 0.0})
            agg["calls"] += 1
            agg["input_tokens"] += int(c.get("input_tokens") or 0)
            agg["output_tokens"] += int(c.get("output_tokens") or 0)
            agg["seconds"] = round(agg["seconds"] + float(c.get("seconds") or 0.0), 2)
        return out


def start_run() -> RunRecorder:
    recorder = RunRecorder()
    _current_run.set(recorder)
    return recorder


def current_run() -> Optional[RunRecorder]:
    return _current_run.get()


def _model_name_from_message(message: Any) -> Optional[str]:
    """Dig the responding model id out of whatever shape the provider returned."""
    meta = getattr(message, "response_metadata", None) or {}
    for key in ("model_name", "model", "model_id"):
        value = meta.get(key)
        if value:
            return str(value)
    return None


def _usage_from_message(message: Any) -> Dict[str, Optional[int]]:
    usage = getattr(message, "usage_metadata", None) or {}
    return {
        "input_tokens": usage.get("input_tokens"),
        "output_tokens": usage.get("output_tokens"),
    }


def make_collector(node: str, tier: str):
    """A LangChain callback that records the model and token usage per LLM call.

    A callback is used rather than `with_structured_output(include_raw=True)`
    because `include_raw` stops the structured-output wrapper from *raising* on a
    parse failure — which is precisely the signal `with_fallbacks` needs in order
    to try the next provider. Collecting usage must not quietly disable the
    provider cascade.
    """
    try:
        from langchain_core.callbacks import BaseCallbackHandler
    except Exception:                                  # pragma: no cover
        return None

    class _UsageCollector(BaseCallbackHandler):
        def __init__(self) -> None:
            self._t0 = time.time()

        def on_llm_end(self, response: Any, **kwargs: Any) -> None:
            recorder = current_run()
            if recorder is None:
                return
            try:
                message = response.generations[0][0].message
            except Exception:
                message = None
            entry = {
                "node": node,
                "tier": tier,
                "ok": True,
                "seconds": round(time.time() - self._t0, 3),
                "model": _model_name_from_message(message) if message is not None else None,
            }
            if message is not None:
                entry.update(_usage_from_message(message))
            recorder.record(**entry)

        def on_llm_error(self, error: BaseException, **kwargs: Any) -> None:
            recorder = current_run()
            if recorder is None:
                return
            recorder.record(
                node=node, tier=tier, ok=False,
                seconds=round(time.time() - self._t0, 3),
                error=type(error).__name__,
            )

    return _UsageCollector()


def callback_config(node: str, tier: str) -> Dict[str, Any]:
    """`config=` kwarg for ainvoke. Empty dict if callbacks are unavailable."""
    collector = make_collector(node, tier)
    return {"callbacks": [collector]} if collector is not None else {}


# ── Prompt fingerprint ────────────────────────────────────────────────────────

_FINGERPRINT_CACHE: Optional[str] = None


def prompt_fingerprint() -> str:
    """Short stable hash over everything that behaves as a prompt.

    Cached: the inputs cannot change within a process's lifetime.
    """
    global _FINGERPRINT_CACHE
    if _FINGERPRINT_CACHE is not None:
        return _FINGERPRINT_CACHE

    digest = hashlib.sha256()
    try:
        from core.graph import schemas as _schemas

        for name in sorted(dir(_schemas)):
            obj = getattr(_schemas, name)
            # Only models *defined here*. `dir()` also returns the imported
            # `BaseModel`, whose model_json_schema() raises, and any other
            # third-party model that happens to be in the namespace — neither is
            # part of this project's prompt.
            if (isinstance(obj, type)
                    and hasattr(obj, "model_json_schema")
                    and getattr(obj, "__module__", None) == _schemas.__name__):
                digest.update(name.encode())
                digest.update(json.dumps(obj.model_json_schema(), sort_keys=True).encode())

        from core.graph import summary_graph as _graph

        for fn_name in ("read_paper", "map_sections", "extract_entities",
                        "extract_results", "synthesize", "grade"):
            fn = getattr(_graph, fn_name, None)
            if fn is not None:
                try:
                    digest.update(inspect.getsource(fn).encode())
                except (OSError, TypeError):
                    pass
    except Exception as e:
        # A fingerprint that cannot be computed must announce itself, not pose as
        # a real one — an "unknown" that compares equal across two different
        # prompt versions would silently validate a bogus A/B comparison.
        logger.warning("prompt_fingerprint_failed", error=str(e))
        return "unknown"

    _FINGERPRINT_CACHE = digest.hexdigest()[:12]
    return _FINGERPRINT_CACHE
