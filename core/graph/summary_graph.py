"""LangGraph summarization engine.

Replaces the old single-call, 4000-char-truncated SummaryAgent with structured
extraction over the whole paper.

There are two reading strategies, chosen per paper by ``prepare``:

    START
      → prepare              clean sections, drop references, measure the paper
      │
      ├─ single pass (paper fits the provider's per-request budget)
      │    → read_paper      ONE call: every section digest + entities + results
      │
      └─ map-reduce (paper too long)
           → map_sections    digest each section concurrently (fast LLM)
           ├─ extract_entities   typed entities        (fast LLM, structured)
           └─ extract_results    quantitative results  (fast LLM, structured)

      → synthesize           long-form summary + findings/limitations/… (smart LLM)
      → grade                LLM-as-judge; if weak & retries left → synthesize
      → END

Single pass exists because free tiers meter *requests* far more tightly than
context, and because a model that sees the whole paper can match a number in a
table to the method that produced it — something per-section calls structurally
cannot do. It costs ~3 requests per paper against map-reduce's ~16. A failed
single-pass read falls back to map-reduce rather than losing the paper.

Every LLM call degrades explicitly rather than crashing: see the ``_structured``
helper and the ``degraded`` flag on section digests. Providers come from
core.llm.providers (Gemini → Groq → Ollama), selected by env.
"""

from __future__ import annotations

import asyncio
import os
import re
from typing import Any, Dict, List, Optional, TypedDict

import structlog

from core.llm.providers import context_budget_chars, get_model_chain
from core.llm.response import message_text
from core.graph.schemas import (
    PaperEntities,
    PaperReading,
    PaperResults,
    PaperSynthesis,
    SectionDigest,
    SummaryGrade,
)

logger = structlog.get_logger(__name__)

# ── Tunables ──────────────────────────────────────────────────────────────────
MAP_SECTION_CHAR_LIMIT = 12000    # per-section text sent to the map step
MAX_MAP_SECTIONS = 24             # cap concurrent section calls
EXTRACTION_CHAR_LIMIT = 60000     # digest text carried into synthesis
MAX_SYNTH_ATTEMPTS = 2            # synthesize → grade → maybe one retry
GRADE_PASS_SCORE = 0.6

# Below this the synthesis collapsed rather than summarised. Kept well under the
# schema's 800-1200 word target so a merely terse summary isn't failed.
MIN_SUMMARY_WORDS = 150

# Sections we never summarize (noise / handled elsewhere). Dropping references is
# also the single largest token saving available: a bibliography is routinely
# 20-30% of a paper's characters and contributes nothing to a summary.
_SKIP_SECTIONS = {
    "references", "__references__", "bibliography", "reference",
    "acknowledgment", "acknowledgments", "acknowledgements",
    "conflict_of_interest", "funding", "author_contributions",
    "competing_interests", "supplementary_material", "appendix_references",
}

# A heading that starts the bibliography. Backends that don't split sections
# cleanly leave the reference list glued to the tail of the last real section,
# where the name-based skip above can't see it.
_REFERENCES_HEADING_RE = re.compile(
    r"^\s*(?:#+\s*)?(?:\d+\.?\s*)?(?:references|bibliography|works\s+cited|literature\s+cited)\s*:?\s*$",
    re.IGNORECASE | re.MULTILINE,
)

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
    chunks: List[Dict[str, str]]          # [{name, text}] — map-reduce path only
    paper_text: str                       # whole cleaned paper — single-pass path only
    single_pass: bool                     # which strategy prepare() chose
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
        # `.content` is a list of blocks for some providers, where `.strip()`
        # raises and the whole call silently degrades to an empty summary.
        return message_text(resp).strip()
    except Exception as e:
        logger.warning("text_call_failed", error=str(e))
        return ""


def _section_rank(name: str) -> int:
    nl = name.lower()
    for i, p in enumerate(_SECTION_PRIORITY):
        if p in nl:
            return i
    return len(_SECTION_PRIORITY)


def strip_references(text: str) -> str:
    """Cut a trailing bibliography off a section body.

    Reference lists are pure cost: they are long, they contain no claims about
    this paper, and their author names and years actively pollute entity
    extraction.
    """
    match = _REFERENCES_HEADING_RE.search(text)
    # Only trust a heading in the last part of the text — "References" can appear
    # early as a cross-reference or subsection title.
    if match and match.start() > len(text) * 0.4:
        return text[:match.start()].rstrip()
    return text


def usable_sections(sections: Dict[str, str]) -> List[tuple]:
    """Ordered (name, text) pairs worth sending to a model.

    Drops boilerplate sections, strips trailing bibliographies, and skips stubs.
    Ordering is by :data:`_SECTION_PRIORITY` so that when a budget forces a cut,
    the least important sections go first.
    """
    out: List[tuple] = []
    for name, text in sorted(sections.items(), key=lambda kv: _section_rank(kv[0])):
        if not text or name.lower() in _SKIP_SECTIONS:
            continue
        cleaned = strip_references(text).strip()
        if len(cleaned) < 120:          # stubs, stray headings
            continue
        out.append((name, cleaned))
    return out


# ── Nodes ───────────────────────────────────────────────────────────────────────

def prepare(state: SummaryState) -> Dict[str, Any]:
    """Clean the paper, then choose how to read it.

    Two strategies, picked by whether the whole paper fits the primary
    provider's per-request budget:

    * **single pass** — one call sees the entire paper. Better output (results in
      a table can be matched to the method that produced them) and far fewer
      requests, which is what free tiers actually meter.
    * **map-reduce** — section-by-section, for papers too long to fit.
    """
    usable = usable_sections(state.get("sections") or {})

    chunks = [
        {"name": name, "text": text[:MAP_SECTION_CHAR_LIMIT]}
        for name, text in usable[:MAX_MAP_SECTIONS]
    ]

    budget = context_budget_chars()
    tables_text = "\n\n".join(state.get("tables_md") or [])
    paper_text = "\n\n".join(
        f"## {name.replace('_', ' ').title()}\n{text}" for name, text in usable
    )
    total_chars = len(paper_text) + len(tables_text)
    single_pass = bool(paper_text) and total_chars <= budget

    logger.info(
        "summary_strategy_selected",
        strategy="single_pass" if single_pass else "map_reduce",
        paper_chars=total_chars,
        budget_chars=budget,
        sections=len(usable),
    )

    # The abstract is repeated into the synthesis prompt as framing, so it stays
    # short deliberately even when the whole paper is available.
    abstract = state.get("abstract") or dict(usable).get("abstract", "")
    return {
        "chunks": chunks,
        "paper_text": paper_text,
        "abstract": abstract[:2000],
        "single_pass": single_pass,
        "attempts": 0,
    }


def _route_after_prepare(state: SummaryState) -> str:
    return "single_pass" if state.get("single_pass") else "map_reduce"


async def read_paper(state: SummaryState) -> Dict[str, Any]:
    """Read the entire paper in one structured call.

    Replaces the map step plus both extraction steps — roughly a dozen requests
    with one. Returns ``single_pass=False`` on failure so the graph falls back to
    map-reduce rather than losing the paper.
    """
    tables = "\n\n".join(state.get("tables_md") or [])
    system = (
        "You are an expert research analyst. You will be given the full text of an "
        "academic paper, and its tables. Produce: (1) a faithful digest of EVERY "
        "substantive section, in order; (2) the salient named concepts, classified as "
        "method, material, measurement, or tool; (3) every quantitative result, taken "
        "from both the tables and the prose. Work for ANY field — medicine, physics, "
        "social science, ML. Report names and numbers exactly as written. Never invent "
        "a method, dataset, or number that is not in the text."
    )
    user = (
        f"Paper title: {state.get('title', '')}\n\n"
        + (f"Tables extracted from the paper:\n{tables}\n\n" if tables else "")
        + f"Full paper text:\n{state.get('paper_text', '')}"
    )

    parsed = await _structured("smart", PaperReading, system, user, max_tokens=8192)
    if parsed is None:
        logger.warning("single_pass_read_failed", fallback="map_reduce")
        return {"single_pass": False}

    digests = [
        {"section": s.section, "summary": s.summary, "facts": s.facts, "degraded": False}
        for s in parsed.sections
    ]
    return {
        "digests": digests,
        "digest_text": _build_digest_text(digests),
        "entities": {"entities": [e.model_dump() for e in parsed.entities]},
        "results": [r.model_dump() for r in parsed.results],
    }


def _route_after_read(state: SummaryState) -> str:
    """Fall through to map-reduce if the whole-paper read didn't produce digests."""
    return "synthesize" if state.get("digests") else "map_reduce"


def _build_digest_text(digests: List[Dict[str, Any]]) -> str:
    """Flatten section digests into the text the synthesis and grader read."""
    lines: List[str] = []
    for d in digests:
        header = d["section"].replace("_", " ").title()
        lines.append(f"## {header}\n{d['summary']}")
        lines.extend(f"- {f}" for f in d.get("facts", []))
    return "\n".join(lines)[:EXTRACTION_CHAR_LIMIT]


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
            # Keep the raw head of the section so downstream coverage isn't lost,
            # but flag it: this is unsummarised paper text, and labelling it as a
            # section "summary" without saying so shows users verbatim PDF prose
            # in a field that claims to be model output.
            return {
                "section": chunk["name"],
                "summary": chunk["text"][:600],
                "facts": [],
                "degraded": True,
            }
        return {"section": chunk["name"], "summary": digest.summary,
                "facts": digest.facts, "degraded": False}

    digests = await asyncio.gather(*[_one(c) for c in chunks]) if chunks else []
    digests = [d for d in digests if d]

    return {"digests": digests, "digest_text": _build_digest_text(digests)}


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
        f"{kind}s: {', '.join(v[:25])}" for kind, v in by_kind.items() if v
    )


def _results_brief(results: List[Dict[str, Any]]) -> str:
    out = []
    for r in (results or [])[:40]:
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
        "rigorous, self-contained account of a paper for a knowledgeable reader. Your summary "
        "should be complete enough that they do not need to open the PDF: explain how the method "
        "actually works, what was measured against what, and what the numbers were. Prefer "
        "specific names and figures over general description. Base everything strictly on the "
        "provided digests, entities, and results — never introduce outside facts or invent "
        "numbers. Write prose (no bullets, no headers) for the prose fields."
    )
    user = (
        f"Paper title: {state.get('title', '')}\n\n"
        f"Abstract:\n{state.get('abstract', '')}\n\n"
        f"Key entities:\n{_entity_brief(state.get('entities', {}))}\n\n"
        f"Quantitative results:\n{_results_brief(state.get('results', []))}\n\n"
        f"Section digests:\n{state.get('digest_text', '')}"
        f"{retry_note}"
    )
    # Generous ceiling: the schema asks for ~1200 words of summary plus method and
    # setup sections, which does not fit in the old 3072.
    parsed = await _structured("smart", PaperSynthesis, system, user, max_tokens=8192)

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
    if not summary or len(summary.split()) < MIN_SUMMARY_WORDS:
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
        # Grading failed (rate limit, parse error). Accept the synthesis rather
        # than loop, but record that it was never graded — previously this
        # returned a synthetic score of exactly GRADE_PASS_SCORE, which was
        # written to the summaries.quality_score column and shown to users as a
        # real measurement, indistinguishable from a genuine 0.6.
        return {"grade": {"graded": False, "faithful": None, "specific": None,
                          "score": None, "issues": []}}

    graded = parsed.model_dump()
    graded["graded"] = True
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
    if state.get("attempts", 0) >= MAX_SYNTH_ATTEMPTS:
        return "done"
    # An ungraded synthesis (judge unavailable) can't be assessed, so retrying
    # would burn quota without evidence it would help — accept and mark it.
    if grade_obj.get("graded") is False:
        return "done"
    score = grade_obj.get("score")
    if score is None or float(score) >= GRADE_PASS_SCORE:
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
    g.add_node("read_paper", read_paper)
    g.add_node("map_sections", map_sections)
    g.add_node("extract_entities", extract_entities)
    g.add_node("extract_results", extract_results)
    g.add_node("synthesize", synthesize)
    g.add_node("grade", grade)

    g.add_edge(START, "prepare")
    # Whole-paper read when it fits, section-by-section when it doesn't.
    g.add_conditional_edges(
        "prepare", _route_after_prepare,
        {"single_pass": "read_paper", "map_reduce": "map_sections"},
    )
    # A failed single-pass read falls back rather than losing the paper.
    g.add_conditional_edges(
        "read_paper", _route_after_read,
        {"synthesize": "synthesize", "map_reduce": "map_sections"},
    )
    # Map-reduce path: entities + results extracted in parallel after mapping…
    g.add_edge("map_sections", "extract_entities")
    g.add_edge("map_sections", "extract_results")
    # …and synthesis waits for both branches.
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
