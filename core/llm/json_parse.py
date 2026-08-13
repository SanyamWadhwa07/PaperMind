"""Recover a JSON object from free-form LLM output.

Every agent that asks an LLM for JSON was doing the same two things: match
`\\{.*\\}` greedily and hand the result to `json.loads`. Both steps are wrong
often enough to matter.

The greedy match spans from the first `{` anywhere in the reply — including one
inside a ``<think>`` block, a LaTeX fragment, or a sentence of preamble — to the
last `}` in the reply, so the "JSON" handed to the parser is frequently prose
with braces at each end. And when the span *is* the object, models still emit
dialects `json.loads` rejects: single-quoted keys, `True`/`None`, trailing
commas. Each failure was caught and logged as a warning, then swallowed — which
is how the ablation and research-gap agents ran for weeks returning nothing at
all while looking healthy in the logs.

This module scans for a *balanced* object and repairs the common dialects. It
returns `{}` when there is genuinely nothing to read, so callers keep their
"no data" path.
"""

from __future__ import annotations

import ast
import json
import re
from typing import Any, Dict, Iterator

__all__ = ["parse_json_object", "extract_json_span", "iter_json_spans"]

# Reasoning models narrate before answering; the narration is not the answer.
_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_FENCE = re.compile(r"```(?:json|javascript|js)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)
# `{"a": 1,}` / `[1, 2, ]` — legal in JS, rejected by json.loads.
_TRAILING_COMMA = re.compile(r",\s*([}\]])")
# Bare keys: `{key: 1}`. Matched only right after `{` or `,` so that a colon
# inside a string value is left alone.
_BARE_KEY = re.compile(r"([{,]\s*)([A-Za-z_][A-Za-z0-9_]*)(\s*:)")


def iter_json_spans(text: str) -> Iterator[str]:
    """Yield each balanced `{...}` span in `text`, left to right.

    Brace-counting rather than regex, because the object we want routinely
    contains nested objects and the reply routinely contains braces that are not
    JSON. Quoted strings are tracked so a `}` inside a caption cannot end the
    span early.

    Several spans are yielded rather than just the first because balanced is not
    the same as parseable — a LaTeX `{\\alpha}` earlier in the reply is balanced
    and would otherwise shadow the real object behind it.
    """
    start = text.find("{")
    while start != -1:
        depth = 0
        in_string = False
        escaped = False
        end = -1

        for i in range(start, len(text)):
            char = text[i]

            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue

            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break

        if end == -1:
            # Unbalanced from here on; nothing later can close either.
            return

        yield text[start : end + 1]
        # Continue after this span — a nested object is already inside it.
        start = text.find("{", end + 1)


def extract_json_span(text: str) -> str:
    """Return the first balanced `{...}` span in `text`, or `''` if there is none."""
    return next(iter_json_spans(text), "")


def _repair(span: str) -> str:
    """Nudge a near-JSON dialect towards strict JSON."""
    span = _TRAILING_COMMA.sub(r"\1", span)
    span = _BARE_KEY.sub(r'\1"\2"\3', span)
    return span


def _salvage_truncated(text: str) -> Dict[str, Any]:
    """Recover the complete prefix of an object that was cut off mid-write.

    A model that hits its token ceiling stops mid-array or mid-string, so the
    object never closes and no balanced span exists at all — the reply is
    discarded entirely even though nearly all of it arrived. That is how a peer
    review with four scores and three concerns became "no parseable JSON".

    Strategy: walk forward remembering every point where a value had just been
    completed, then from the last such point backwards, close the structures
    still open and try to parse. The result is the honest prefix of what the
    model said, with the half-written element dropped.
    """
    start = text.find("{")
    if start == -1:
        return {}

    stack: list[str] = []
    in_string = False
    escaped = False
    # (index just past a completed value, depth stack at that moment)
    boundaries: list[tuple[int, list[str]]] = []

    for i in range(start, len(text)):
        char = text[i]

        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
                boundaries.append((i + 1, list(stack)))
            continue

        if char == '"':
            in_string = True
        elif char in "{[":
            stack.append("}" if char == "{" else "]")
        elif char in "}]":
            if stack:
                stack.pop()
            boundaries.append((i + 1, list(stack)))
        elif char in "0123456789truefalsn" and not stack:
            continue
        elif char == ",":
            boundaries.append((i, list(stack)))

    # Newest boundary first: keep as much of the reply as will parse.
    for end, open_stack in reversed(boundaries):
        candidate = text[start:end].rstrip().rstrip(",")
        closing = "".join(reversed(open_stack))
        for attempt in (candidate + closing, _repair(candidate) + closing):
            try:
                parsed = json.loads(attempt)
            except (ValueError, TypeError):
                continue
            if isinstance(parsed, dict) and parsed:
                return parsed

    return {}


def parse_json_object(raw: str) -> Dict[str, Any]:
    """Best-effort parse of an LLM reply into a dict. Never raises.

    Tried in order: the raw reply, any fenced block, the first balanced span,
    that span repaired, and finally a Python-literal read for single-quoted
    output. Returns `{}` when every attempt fails.
    """
    if not raw or not isinstance(raw, str):
        return {}

    text = _THINK_BLOCK.sub("", raw).strip()

    candidates = []
    fenced = _FENCE.search(text)
    if fenced:
        candidates.append(fenced.group(1).strip())
    candidates.append(text)

    for candidate in candidates:
        for span in iter_json_spans(candidate):
            for attempt in (span, _repair(span)):
                try:
                    parsed = json.loads(attempt)
                except (ValueError, TypeError):
                    pass
                else:
                    if isinstance(parsed, dict):
                        return parsed

            # Single-quoted output is a Python dict literal, not JSON.
            # `literal_eval` reads it without the `eval` foot-gun — it evaluates
            # literals only.
            try:
                parsed = ast.literal_eval(span)
            except (ValueError, SyntaxError, MemoryError, RecursionError):
                continue
            if isinstance(parsed, dict):
                return parsed

    # Nothing balanced anywhere — most likely the reply was cut off at the
    # token ceiling, so try to keep the part that did arrive.
    for candidate in candidates:
        salvaged = _salvage_truncated(candidate)
        if salvaged:
            return salvaged

    return {}
