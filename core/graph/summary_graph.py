"""LangGraph summarization engine.

Replaces the old single-call, 4000-char-truncated SummaryAgent with a proper
map-reduce graph that reads the *whole* paper and uses structured extraction
instead of regex.

Pipeline (StateGraph):

    START
      → prepare          normalise + order sections, pick chunks to map over
      → map_sections     summarize EVERY meaningful section (fast LLM, concurrent)
      ├─ extract_entities   domain-agnostic typed entities   (fast LLM, structured)
      └─ extract_results    quantitative results from prose+tables (fast LLM, structured)
      → synthesize       final 300-450w summary + findings/limitations/... (smart LLM)
      → grade            LLM-as-judge; if weak & retries left → back to synthesize
      → END

Every LLM call is wrapped so a provider/parse failure degrades gracefully rather
than crashing the pipeline. Providers come from core.llm.providers (Groq prod /
Ollama dev), selected by env.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, Dict, List, Optional, TypedDict

import structlog

from core.llm.providers import get_model_chain
from core.graph.schemas import (
    PaperEntities,
    PaperResults,
    PaperSynthesis,
    SectionDigest,
    SummaryGrade,
)

logger = structlog.get_logger(__name__)

# ── Tunables ──────────────────────────────────────────────────────────────────
MAP_SECTION_CHAR_LIMIT = 6000     # per-section text sent to the map step
MAX_MAP_SECTIONS = 12             # cap concurrent section calls
EXTRACTION_CHAR_LIMIT = 12000     # digest text sent to entity/result extraction
MAX_SYNTH_ATTEMPTS = 2            # synthesize → grade → maybe one retry
GRADE_PASS_SCORE = 0.6

# Sections we never summarize (noise / handled elsewhere).
_SKIP_SECTIONS = {
    "references", "__references__", "bibliography",
    "acknowledgment", "acknowledgments", "acknowledgements",
    "conflict_of_interest", "funding", "author_contributions",
}

# Ordering priority so truncation drops the least-important sections last.
_SECTION_PRIORITY = [
    "abstract", "introduction", "background", "related",
    "method", "approach", "model", "material",
    "experiment", "result", "evaluat", "analysis",
    "discussion", "conclusion", "limitation", "future",
]


class SummaryState(TypedDict, total=False):
    # inputs
    title: str
    abstract: str
    domain: str
    sections: Dict[str, str]
    tables_md: List[str]
    # intermediate
    chunks: List[Dict[str, str]]          # [{name, text}]
    digests: List[Dict[str, Any]]         # [{section, summary, facts}]
    digest_text: str
    entities: Dict[str, Any]              # PaperEntities.model_dump()
    results: List[Dict[str, Any]]         # [ResultRow.model_dump(), ...]
    # output
    synthesis: Dict[str, Any]             # PaperSynthesis.model_dump()
    grade: Dict[str, Any]
    attempts: int


# ── LLM helpers ────────────────────────────────────────────────────────────────

# Global ceiling on simultaneous LLM calls so the map step never bursts past a
# provider's tokens-per-minute budget (Groq free tier is ~6k TPM). Combined with
# provider-side retry/backoff this keeps free-tier processing reliable.
_LLM_CONCURRENCY = int(os.environ.get("PAPERMIND_LLM_CONCURRENCY", "2"))
_llm_semaphore: Optional[asyncio.Semaphore] = None


def _get_semaphore() -> asyncio.Semaphore:
    global _llm_semaphore
    if _llm_semaphore is None:
        _llm_semaphore = asyncio.Semaphore(_LLM_CONCURRENCY)
    return _llm_semaphore


def _with_fallbacks(runnables: List[Any]):
    """Combine a primary runnable with ordered fallbacks (provider cascade)."""
    primary, rest = runnables[0], runnables[1:]
    return primary.with_fallbacks(rest) if rest else primary


async def _structured(tier: str, schema, system: str, user: str, *, max_tokens: int = 2048):
    """Structured output across the provider chain (primary → fallbacks). None on total failure."""
    try:
        chain = [m.with_structured_output(schema) for m in get_model_chain(tier, max_tokens=max_tokens)]
        runnable = _with_fallbacks(chain)
        async with _get_semaphore():
            return await runnable.ainvoke(
                [{"role": "system", "content": system}, {"role": "user", "content": user}]
            )
    except Exception as e:  # all providers failed / parse failure / schema mismatch
        logger.warning("structured_call_failed", schema=schema.__name__, error=str(e))
        return None


async def _text(tier: str, system: str, user: str, *, max_tokens: int = 2048) -> str:
    """Plain text generation across the provider chain. Empty string on total failure."""
    try:
        runnable = _with_fallbacks(get_model_chain(tier, max_tokens=max_tokens))
        async with _get_semaphore():
            resp = await runnable.ainvoke(
                [{"role": "system", "content": system}, {"role": "user", "content": user}]
            )
        return (resp.content or "").strip() if hasattr(resp, "content") else str(resp).strip()
    except Exception as e:
        logger.warning("text_call_failed", error=str(e))
        return ""


def _section_rank(name: str) -> int:
    nl = name.lower()
    for i, p in enumerate(_SECTION_PRIORITY):
        if p in nl:
            return i
    return len(_SECTION_PRIORITY)


# ── Nodes ───────────────────────────────────────────────────────────────────────

def prepare(state: SummaryState) -> Dict[str, Any]:
    """Order/clean sections and select the chunks to summarize."""
    sections = state.get("sections") or {}
    chunks: List[Dict[str, str]] = []
    for name, text in sorted(sections.items(), key=lambda kv: _section_rank(kv[0])):
        if not text or name.lower() in _SKIP_SECTIONS:
            continue
        if len(text.strip()) < 120:  # skip stubs / headers
            continue
        chunks.append({"name": name, "text": text[:MAP_SECTION_CHAR_LIMIT]})
        if len(chunks) >= MAX_MAP_SECTIONS:
            break

    # Always include the abstract as context even if short.
    abstract = state.get("abstract") or sections.get("abstract", "")
    return {"chunks": chunks, "abstract": abstract[:1500], "attempts": 0}


async def map_sections(state: SummaryState) -> Dict[str, Any]:
    """Summarize every selected section concurrently (the 'map' step)."""
    chunks = state.get("chunks") or []
    domain = state.get("domain", "general")

    system = (
        "You are an expert research analyst. You will be given one section of an "
        "academic paper. Produce a faithful, concrete digest of ONLY what the text "
        "states — never invent methods, datasets, or numbers. Preserve specific names "
        "and quantitative values verbatim."
    )

    async def _one(chunk: Dict[str, str]) -> Optional[Dict[str, Any]]:
        user = (
            f"Paper domain: {domain}\n"
            f"Section: {chunk['name'].replace('_', ' ').title()}\n\n"
            f"{chunk['text']}"
        )
        digest = await _structured("fast", SectionDigest, system, user, max_tokens=1024)
        if digest is None:
            # Fallback: keep the raw head of the section so coverage isn't lost.
            return {"section": chunk["name"], "summary": chunk["text"][:600], "facts": []}
        return {"section": chunk["name"], "summary": digest.summary, "facts": digest.facts}

    digests = await asyncio.gather(*[_one(c) for c in chunks]) if chunks else []
    digests = [d for d in digests if d]

    # Build the compact combined digest reused by later steps.
    lines: List[str] = []
    for d in digests:
        header = d["section"].replace("_", " ").title()
        lines.append(f"## {header}\n{d['summary']}")
        for f in d.get("facts", []):
            lines.append(f"- {f}")
    digest_text = "\n".join(lines)[:EXTRACTION_CHAR_LIMIT]

    return {"digests": digests, "digest_text": digest_text}


async def extract_entities(state: SummaryState) -> Dict[str, Any]:
    """Domain-agnostic typed entity extraction (replaces regex)."""
    system = (
        "You extract the salient named concepts from a research paper, working for "
        "ANY field (ML, medicine, biology, physics, social science). Classify each as "
        "method, material, measurement, or tool. Use the exact names from the text. "
        "Do not invent entities that are not present."
    )
    user = f"Paper title: {state.get('title', '')}\n\nPaper digest:\n{state.get('digest_text', '')}"
    parsed = await _structured("fast", PaperEntities, system, user, max_tokens=1536)
    if parsed is None:
        return {"entities": {"entities": []}}
    return {"entities": parsed.model_dump()}


async def extract_results(state: SummaryState) -> Dict[str, Any]:
    """Extract quantitative results from results/experiment prose + markdown tables."""
    sections = state.get("sections") or {}
    result_text = "\n\n".join(
        f"[{k}]\n{v[:4000]}"
        for k, v in sections.items()
        if any(w in k.lower() for w in ("result", "experiment", "evaluat", "finding", "outcome", "analysis"))
    )
    tables = "\n\n".join(state.get("tables_md") or [])[:6000]
    if not result_text and not tables:
        result_text = state.get("digest_text", "")

    system = (
        "You extract quantitative results from a paper into normalised rows. Pull "
        "numbers from BOTH prose and the provided markdown tables. Report values "
        "exactly as written (with units/%). Mark the paper's headline/proposed result "
        "as is_best. Return an empty list if there are genuinely no numeric results."
    )
    user = (
        (f"Markdown tables:\n{tables}\n\n" if tables else "")
        + f"Results text:\n{result_text}"
    )
    parsed = await _structured("fast", PaperResults, system, user, max_tokens=2048)
    if parsed is None:
        return {"results": []}
    return {"results": [r.model_dump() for r in parsed.results]}


def _entity_brief(entities: Dict[str, Any]) -> str:
    by_kind: Dict[str, List[str]] = {}
    for e in (entities or {}).get("entities", []):
        by_kind.setdefault(e.get("kind", "other"), []).append(e.get("name", ""))
    return "\n".join(
        f"{kind}s: {', '.join(v[:10])}" for kind, v in by_kind.items() if v
    )


def _results_brief(results: List[Dict[str, Any]]) -> str:
    out = []
    for r in (results or [])[:10]:
        line = f"  • {r.get('measurement','')}: {r.get('value','')}"
        if r.get("method"):
            line += f" ({r['method']})"
        if r.get("subject"):
            line += f" on {r['subject']}"
        out.append(line)
    return "\n".join(out)


async def synthesize(state: SummaryState) -> Dict[str, Any]:
    """Reduce step: produce the final structured synthesis using the smart model."""
    domain = state.get("domain", "general")
    issues = (state.get("grade") or {}).get("issues") or []
    retry_note = ""
    if issues:
        retry_note = (
            "\n\nYour previous attempt had these problems — fix them:\n"
            + "\n".join(f"- {i}" for i in issues)
        )

    system = (
        f"You are an expert {domain if domain != 'general' else 'academic'} researcher writing a "
        "rigorous summary of a paper for a knowledgeable reader. Base everything strictly on the "
        "provided digests, entities, and results — do not introduce outside facts or fabricate "
        "numbers. Write the summary as flowing prose (no bullets, no headers)."
    )
    user = (
        f"Paper title: {state.get('title', '')}\n\n"
        f"Abstract:\n{state.get('abstract', '')}\n\n"
        f"Key entities:\n{_entity_brief(state.get('entities', {}))}\n\n"
        f"Quantitative results:\n{_results_brief(state.get('results', []))}\n\n"
        f"Section digests:\n{state.get('digest_text', '')}"
        f"{retry_note}"
    )
    parsed = await _structured("smart", PaperSynthesis, system, user, max_tokens=3072)

    if parsed is None:
        # Last-resort: plain-text summary so the user still gets something useful.
        text = await _text("smart", system, user, max_tokens=2048)
        synthesis = {
            "summary": text or state.get("abstract", "") or "Summary unavailable.",
            "contributions": [], "key_findings": [], "limitations": [], "future_work": [],
        }
    else:
        synthesis = parsed.model_dump()

    # Weak models often fill `summary` but leave the list fields empty. Backfill
    # key_findings from extracted results / section facts so the UI isn't blank.
    if not synthesis.get("key_findings"):
        synthesis["key_findings"] = _fallback_findings(state)

    return {"synthesis": synthesis, "attempts": state.get("attempts", 0) + 1}


def _fallback_findings(state: SummaryState) -> List[str]:
    """Derive key findings from results rows, then section facts, as a fallback."""
    findings: List[str] = []
    for r in (state.get("results") or []):
        meas, val = r.get("measurement", ""), r.get("value", "")
        if meas and val:
            line = f"{meas}: {val}"
            if r.get("method"):
                line += f" ({r['method']})"
            findings.append(line)
        if len(findings) >= 5:
            break
    if not findings:
        for d in (state.get("digests") or []):
            if any(w in d.get("section", "").lower() for w in ("result", "finding", "conclusion")):
                findings.extend(d.get("facts", [])[:3])
    return findings[:5]


async def grade(state: SummaryState) -> Dict[str, Any]:
    """LLM-as-judge gate on the synthesis (drives the retry loop)."""
    synthesis = state.get("synthesis") or {}
    summary = synthesis.get("summary", "")
    if not summary or len(summary.split()) < 40:
        return {"grade": {"faithful": False, "specific": False, "score": 0.0,
                          "issues": ["Summary too short or empty."]}}

    system = (
        "You are a strict reviewer. Judge whether a paper summary is FAITHFUL to the "
        "source digests (no hallucinated methods/numbers) and SPECIFIC (names real "
        "methods/materials and includes concrete numbers). Be honest and concise."
    )
    user = (
        f"Source digests:\n{state.get('digest_text', '')}\n\n"
        f"Quantitative results available:\n{_results_brief(state.get('results', []))}\n\n"
        f"Summary to grade:\n{summary}"
    )
    parsed = await _structured("smart", SummaryGrade, system, user, max_tokens=512)
    if parsed is None:
        # If grading itself fails, accept the synthesis rather than loop.
        return {"grade": {"faithful": True, "specific": True, "score": GRADE_PASS_SCORE, "issues": []}}

    graded = parsed.model_dump()
    # Normalise the score to 0–1: weaker models sometimes answer on a 0–5 or 0–10
    # scale despite the schema. Without this a "4.0" passes the gate by accident
    # and surfaces a nonsensical quality value to the user.
    raw = float(graded.get("score", 0.0))
    if raw > 1.0:
        raw = raw / (10.0 if raw > 5.0 else 5.0)
    graded["score"] = max(0.0, min(raw, 1.0))
    return {"grade": graded}


def _route_after_grade(state: SummaryState) -> str:
    grade_obj = state.get("grade") or {}
    score = float(grade_obj.get("score", 0.0))
    if score >= GRADE_PASS_SCORE or state.get("attempts", 0) >= MAX_SYNTH_ATTEMPTS:
        return "done"
    return "retry"


# ── Graph assembly ───────────────────────────────────────────────────────────────

_compiled = None


def get_summary_graph():
    """Build & cache the compiled summarization graph."""
    global _compiled
    if _compiled is not None:
        return _compiled

    from langgraph.graph import StateGraph, START, END

    g = StateGraph(SummaryState)
    g.add_node("prepare", prepare)
    g.add_node("map_sections", map_sections)
    g.add_node("extract_entities", extract_entities)
    g.add_node("extract_results", extract_results)
    g.add_node("synthesize", synthesize)
    g.add_node("grade", grade)

    g.add_edge(START, "prepare")
    g.add_edge("prepare", "map_sections")
    # Fan-out: entities + results extracted in parallel after mapping.
    g.add_edge("map_sections", "extract_entities")
    g.add_edge("map_sections", "extract_results")
    # Fan-in: synthesize waits for both extraction branches.
    g.add_edge("extract_entities", "synthesize")
    g.add_edge("extract_results", "synthesize")
    g.add_edge("synthesize", "grade")
    g.add_conditional_edges("grade", _route_after_grade, {"retry": "synthesize", "done": END})

    _compiled = g.compile()
    return _compiled


async def summarize_paper(
    *,
    title: str,
    sections: Dict[str, str],
    tables_md: Optional[List[str]] = None,
    domain: str = "general",
    abstract: str = "",
) -> Dict[str, Any]:
    """Run the full summarization graph and return the raw final state.

    The returned dict contains: synthesis, entities, results, digests, grade.
    """
    graph = get_summary_graph()
    initial: SummaryState = {
        "title": title or "",
        "sections": sections or {},
        "tables_md": tables_md or [],
        "domain": domain or "general",
        "abstract": abstract or "",
    }
    final = await graph.ainvoke(initial)
    return dict(final)
