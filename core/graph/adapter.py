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

    # What the run actually did — models observed, tokens, per-node timing, and
    # the prompt fingerprint. `llm_model` below is the *configured* primary and
    # can differ from what answered whenever the fallback chain fires, so
    # `models_observed` is the field to trust when attributing a regression.
    run_meta = state.get("run_meta", {}) or {}

    # None when the judge never ran — kept as None all the way to the DB column
    # so an ungraded summary is not shown as a real score.
    raw_score = grade.get("score")
    quality = float(raw_score) if raw_score is not None else None

    degraded_sections = [
        d["section"] for d in state.get("digests", []) if d.get("degraded")
    ]

    # Per-claim groundedness from the graph's verify step. Three-valued on
    # purpose: `grounded=None` means the claim could not be checked, and must
    # never be rolled up as if it had passed.
    claims = state.get("claims", []) or []
    grounding = {
        "checked": len(claims),
        "grounded": sum(1 for c in claims if c.get("grounded") is True),
        "ungrounded": sum(1 for c in claims if c.get("grounded") is False),
        "unverified": sum(1 for c in claims if c.get("grounded") is None),
    }

    return {
        # SummaryAgent-compatible keys
        "extractions": [summary_text],
        "confidence_scores": {"main": quality if quality is not None else 0.0},
        "summaries": {"main": summary_text},
        "key_findings": synthesis.get("key_findings", []),
        "limitations": synthesis.get("limitations", []),
        "future_work": synthesis.get("future_work", []),
        "section_summaries": section_summaries,
        # Long-form detail so a reader doesn't need the PDF for the method or
        # the experimental design.
        "methods_detail": synthesis.get("methods_detail", ""),
        "experimental_setup": synthesis.get("experimental_setup", ""),
        # new, richer outputs
        "contributions": synthesis.get("contributions", []),
        "graph_entities": graph_entities,                 # domain-agnostic typed
        "graph_entities_legacy": _legacy_entities(graph_entities),
        "graph_results": graph_results,
        "grade": grade,
        "claims": claims,
        "metadata": {
            "engine": "langgraph",
            "llm_provider": provider_info["provider"],          # configured primary
            "llm_model": provider_info["models"]["smart"],      # configured, not observed
            "run_meta": run_meta,
            "domain": domain,
            "summary_quality": quality,
            "graded": grade.get("graded", True),
            "validation_passed": bool(summary_text and len(summary_text.split()) > 50),
            "faithful": grade.get("faithful"),
            "specific": grade.get("specific"),
            # Sections where the map step failed and raw paper text stood in.
            "degraded_sections": degraded_sections,
            "grounding": grounding,
        },
    }
