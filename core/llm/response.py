"""Get the text out of an LLM response, whatever shape the provider used.

`AIMessage.content` is not always a string. Depending on the provider and the
model, it can also be a list of content blocks — `[{"type": "text", "text": ...,
"extras": {...}}, ...]` — and both shapes arrive through the same
`get_model_chain` cascade, so a call site cannot assume either one.

Both call sites used to assume `str`:

    raw if isinstance(raw, str) else str(raw)      # llm_interface
    (resp.content or "").strip()                    # summary_graph

The first stringified the *Python list* — `"[{'type': 'text', 'text': '{...}'}]"`
— and handed that on as the model's answer. Downstream JSON parsing then
succeeded on the envelope rather than failing, so a peer review was persisted as
`{"type": ..., "text": ..., "extras": ...}` with the actual review trapped as a
string inside `text`, and the UI rendered a card with every field undefined. The
second raised `AttributeError` on a list, which was caught and turned into an
empty summary.

One helper, used by both, so the shape is handled once.
"""

from __future__ import annotations

from typing import Any

__all__ = ["message_text"]


def message_text(response: Any) -> str:
    """Return the plain text of an LLM response. Never raises."""
    content = getattr(response, "content", response)

    if isinstance(content, str):
        return content

    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                # Skip non-text blocks (tool calls, images, reasoning traces):
                # concatenating those would corrupt the answer.
                if block.get("type") in (None, "text"):
                    text = block.get("text")
                    if isinstance(text, str):
                        parts.append(text)
            else:
                text = getattr(block, "text", None)
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)

    if content is None:
        return ""

    return str(content)
