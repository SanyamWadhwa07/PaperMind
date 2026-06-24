"""RelationAgent — explains how two papers relate, using the LLM provider chain.

Why this exists: the knowledge graph today connects papers by raw cosine
similarity (a number) or arXiv-id citation matching. That tells you papers are
*close*, not *how* they relate. The RelationAgent reads compact representations
of two papers and returns a typed, explained relationship
(extends / replicates / contradicts / applies_to_domain / shares_method / ...).

It plugs into existing infrastructure:
  - candidate pairs come from `paper_similarity` (pgvector top-K) — no O(N²) blowup
  - results are persisted to `paper_lineage` (ancestor_id, descendant_id, link_type,
    link_confidence), which `graph_service.get_citation_network()` already renders
    with per-relation colors.

Provider chain (Gemini → Groq → Ollama) and rate-limit handling come from
core.llm.providers, same as the summarizer.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

import structlog

from core.llm.providers import get_model_chain
from core.graph.schemas import PaperRelation

logger = structlog.get_logger(__name__)

# RelationType → paper_lineage.link_type (graph_service colors: cites/extends/
# replicates/contradicts/inspired_by). We map onto that existing vocabulary.
_LINK_TYPE = {
    "extends": "extends",
    "replicates": "replicates",
    "contradicts": "contradicts",
    "applies_to_domain": "extends",
    "shares_method": "inspired_by",
    "shares_dataset": "inspired_by",
    "compares_against": "cites",
    "unrelated": None,
}


def _paper_brief(p: Dict[str, Any], label: str) -> str:
    """Compact, token-cheap representation of a paper for the relation prompt."""
    ents = p.get("entities") or []
    if ents and isinstance(ents[0], dict):
        ents = [e.get("name", "") for e in ents]
    findings = p.get("key_findings") or []
    return (
        f"=== Paper {label} ===\n"
        f"Title: {p.get('title','')}\n"
        f"Summary: {(p.get('summary') or '')[:900]}\n"
        f"Key findings: {'; '.join(findings[:4])}\n"
        f"Entities: {', '.join([e for e in ents if e][:15])}\n"
    )


async def relate_papers(paper_a: Dict[str, Any], paper_b: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Return a typed relationship between two papers, or None on failure.

    Each paper dict: {id?, title, summary, key_findings, entities}.
    """
    system = (
        "You are a research librarian who identifies how two papers relate. Pick the "
        "SINGLE most salient relationship and justify it with concrete shared specifics.\n\n"
        "Decision guidance:\n"
        "- If they share a core method/architecture (e.g. both use U-Net/CNN/transformers "
        "on the same problem) → shares_method.\n"
        "- If they evaluate on the same dataset/benchmark/cohort → shares_dataset.\n"
        "- If one applies the other's method to a different dataset/domain → applies_to_domain.\n"
        "- If one reproduces/confirms the other's results → replicates; if results conflict → contradicts.\n"
        "- If one uses the other as a baseline → compares_against.\n"
        "- Reserve 'unrelated' for papers in genuinely DIFFERENT fields with no shared method, "
        "modality, dataset, or task (e.g. brain-tumor imaging vs legal-text summarization). "
        "Sharing a method, modality, or problem area is NOT unrelated."
    )
    user = _paper_brief(paper_a, "A") + "\n" + _paper_brief(paper_b, "B")

    try:
        chain = [m.with_structured_output(PaperRelation)
                 for m in get_model_chain("smart", max_tokens=800)]
        runnable = chain[0].with_fallbacks(chain[1:]) if len(chain) > 1 else chain[0]
        parsed: PaperRelation = await runnable.ainvoke(
            [{"role": "system", "content": system}, {"role": "user", "content": user}]
        )
    except Exception as e:
        logger.warning("relate_papers_failed", error=str(e))
        return None

    rel = parsed.model_dump()
    # Normalise confidence scale (some models answer 0-10 / 0-5).
    c = float(rel.get("confidence", 0.0))
    if c > 1.0:
        c = c / (10.0 if c > 5.0 else 5.0)
    rel["confidence"] = max(0.0, min(c, 1.0))
    rel["link_type"] = _LINK_TYPE.get(rel.get("relationship"), None)
    rel["paper_a_id"] = paper_a.get("id")
    rel["paper_b_id"] = paper_b.get("id")
    return rel


async def relate_pairs(pairs: List[tuple], *, concurrency: int = 2) -> List[Dict[str, Any]]:
    """Relate many (paper_a, paper_b) dict pairs, bounded concurrency. Skips 'unrelated'."""
    sem = asyncio.Semaphore(concurrency)

    async def _one(a, b):
        async with sem:
            return await relate_papers(a, b)

    results = await asyncio.gather(*[_one(a, b) for a, b in pairs])
    return [r for r in results
            if r and r.get("relationship") != "unrelated" and r.get("link_type")]


def _paper_from_summary_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """Build a RelationAgent paper dict from a summaries table row."""
    data = row.get("summary_data") or {}
    summary = ""
    if isinstance(data.get("summaries"), dict):
        summary = data["summaries"].get("main", "")
    summary = summary or data.get("summary", "")

    # Prefer domain-agnostic typed entities; fall back to legacy buckets.
    ent_names: List[str] = []
    typed = (data.get("typed_entities") or {}).get("entities") or []
    if typed:
        ent_names = [e.get("name", "") for e in typed]
    else:
        for k in ("models", "datasets", "metrics"):
            ent_names += data.get(k, []) or []

    return {
        "id": row.get("id"),
        "title": row.get("paper_title") or data.get("title", ""),
        "summary": summary,
        "key_findings": data.get("key_findings", []) or [],
        "entities": [e for e in ent_names if e],
    }


async def relate_library(user_id: str, supabase_client, *, top_k: int = 5,
                         max_pairs: int = 60) -> Dict[str, Any]:
    """Compute and persist LLM relationships across a user's library.

    Candidate pairs come from the pre-computed pgvector `paper_similarity` cache
    (top-K neighbours) to avoid an O(N²) explosion. Falls back to all-pairs for
    small libraries that have no similarity rows yet.
    """
    rows = (supabase_client.table("summaries")
            .select("id, paper_title, summary_data")
            .eq("user_id", user_id).limit(300).execute()).data or []
    papers = {r["id"]: _paper_from_summary_row(r) for r in rows}
    if len(papers) < 2:
        return {"related": 0, "persisted": 0, "reason": "need >= 2 papers"}

    # Candidate pairs from similarity cache.
    ids = list(papers.keys())
    seen = set()
    pairs: List[tuple] = []
    sim = (supabase_client.table("paper_similarity")
           .select("paper_a_id, paper_b_id")
           .in_("paper_a_id", ids).execute()).data or []
    for s in sim:
        a, b = s["paper_a_id"], s["paper_b_id"]
        if a in papers and b in papers:
            key = tuple(sorted((a, b)))
            if key not in seen:
                seen.add(key)
                pairs.append((papers[a], papers[b]))

    # Fallback: small library with no cached similarity → all unique pairs.
    if not pairs and len(papers) <= 8:
        for i, a in enumerate(ids):
            for b in ids[i + 1:]:
                pairs.append((papers[a], papers[b]))

    pairs = pairs[:max_pairs]
    relations = await relate_pairs(pairs)
    persisted = persist_relations(relations, supabase_client)
    return {"candidate_pairs": len(pairs), "related": len(relations), "persisted": persisted}


def persist_relations(relations: List[Dict[str, Any]], supabase_client) -> int:
    """Upsert relations into paper_lineage so the citation/knowledge graph renders them.

    Direction maps to ancestor → descendant:
      a_to_b: A is ancestor, B descendant
      b_to_a: B is ancestor, A descendant
      bidirectional: store A → B (graph treats it as an edge regardless)
    """
    rows = []
    for r in relations:
        a, b = r.get("paper_a_id"), r.get("paper_b_id")
        if not a or not b:
            continue
        if r.get("direction") == "b_to_a":
            ancestor, descendant = b, a
        else:
            ancestor, descendant = a, b
        rows.append({
            "ancestor_id": ancestor,
            "descendant_id": descendant,
            "link_type": r["link_type"],
            "link_confidence": r["confidence"],
            "rationale": r.get("explanation", "")[:500],
        })
    if not rows:
        return 0

    # paper_lineage unique key is (ancestor_id, descendant_id). `rationale` is added
    # by migration 009 — if it isn't present yet, retry without it so persistence
    # still works on an un-migrated DB.
    try:
        supabase_client.table("paper_lineage").upsert(
            rows, on_conflict="ancestor_id,descendant_id"
        ).execute()
        return len(rows)
    except Exception as e:
        logger.warning("persist_relations_retry_without_rationale", error=str(e))
        for row in rows:
            row.pop("rationale", None)
        try:
            supabase_client.table("paper_lineage").upsert(
                rows, on_conflict="ancestor_id,descendant_id"
            ).execute()
            return len(rows)
        except Exception as e2:
            logger.error("persist_relations_failed", error=str(e2))
            return 0
