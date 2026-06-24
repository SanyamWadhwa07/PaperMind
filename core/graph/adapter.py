"""Adapter: run the LangGraph summarizer and return SummaryAgent-compatible output.

This lets the new graph engine drop into the existing orchestrator / frontend
without changing their contract. It also surfaces the graph's *own* domain-agnostic
entity and result extraction (under `graph_entities` / `graph_results`) so callers
can prefer those over the legacy regex output.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import structlog

from core.graph.summary_graph import summarize_paper

logger = structlog.get_logger(__name__)


def _legacy_entities(graph_entities: Dict[str, Any]) -> Dict[str, List[str]]:
    """Map domain-agnostic kinds onto the legacy models/datasets/metrics buckets.

    method      -> models      (algorithms / techniques / interventions)
    material    -> datasets    (datasets / cohorts / corpora)
    measurement -> metrics     (metrics / clinical outcomes)
    tool        -> frameworks
    """
    mapping = {"method": "models", "material": "datasets",
               "measurement": "metrics", "tool": "frameworks"}
    buckets: Dict[str, List[str]] = {"models": [], "datasets": [], "metrics": [],
                                     "frameworks": [], "tasks": []}
    for e in (graph_entities or {}).get("entities", []):
        key = mapping.get(e.get("kind", ""))
        name = (e.get("name") or "").strip()
        if key and name and name not in buckets[key]:
            buckets[key].append(name)
    return buckets


async def run_graph_summary(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """Run the graph and shape its output like SummaryAgent.process().

    Expected input_data keys (same as SummaryAgent): sections, metadata, domain,
    and optionally tables_md.
    """
    metadata = input_data.get("metadata", {}) or {}
    sections = input_data.get("sections", {}) or {}
    domain = (input_data.get("domain")
              or metadata.get("domain")
              or metadata.get("domain_match")
              or "general")
    title = metadata.get("title", "") or input_data.get("title", "")
    abstract = sections.get("abstract", "")
    tables_md = input_data.get("tables_md") or metadata.get("tables_md") or []

    state = await summarize_paper(
        title=title,
        sections=sections,
        tables_md=tables_md,
        domain=domain,
        abstract=abstract,
    )

    synthesis = state.get("synthesis", {}) or {}
    grade = state.get("grade", {}) or {}
    summary_text = synthesis.get("summary", "") or ""

    section_summaries = {
        d["section"]: d["summary"]
        for d in state.get("digests", []) if d.get("summary")
    }

    graph_entities = state.get("entities", {}) or {}
    graph_results = state.get("results", []) or []

    from core.llm.providers import resolve_provider, get_provider_info
    provider_info = get_provider_info()

    return {
        # SummaryAgent-compatible keys
        "extractions": [summary_text],
        "confidence_scores": {"main": float(grade.get("score", 0.0))},
        "summaries": {"main": summary_text},
        "key_findings": synthesis.get("key_findings", []),
        "limitations": synthesis.get("limitations", []),
        "future_work": synthesis.get("future_work", []),
        "section_summaries": section_summaries,
        # new, richer outputs
        "contributions": synthesis.get("contributions", []),
        "graph_entities": graph_entities,                 # domain-agnostic typed
        "graph_entities_legacy": _legacy_entities(graph_entities),
        "graph_results": graph_results,
        "grade": grade,
        "metadata": {
            "engine": "langgraph",
            "llm_provider": provider_info["provider"],
            "llm_model": provider_info["models"]["smart"],
            "domain": domain,
            "summary_quality": float(grade.get("score", 0.0)),
            "validation_passed": bool(summary_text and len(summary_text.split()) > 50),
            "faithful": grade.get("faithful"),
            "specific": grade.get("specific"),
        },
    }
