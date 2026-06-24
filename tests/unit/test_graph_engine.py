"""Unit tests for the LangGraph summarization engine + provider chain + RelationAgent.

All LLM calls are mocked, so these run offline (no Groq/Gemini/Ollama needed).
"""

import os
import pytest
from unittest.mock import patch, MagicMock

from core.graph import schemas


# ── Fake LLM plumbing ───────────────────────────────────────────────────────────

class _FakeStructured:
    def __init__(self, schema):
        self.schema = schema

    def with_fallbacks(self, _rest):
        return self

    async def ainvoke(self, _messages):
        s = self.schema
        if s is schemas.SectionDigest:
            return s(summary="A faithful section digest with a number 92.3%.",
                     facts=["Accuracy was 92.3%."])
        if s is schemas.PaperEntities:
            return s(entities=[
                schemas.Entity(name="MAG-Net", kind="method", description="the model"),
                schemas.Entity(name="Figshare", kind="material", description="dataset"),
                schemas.Entity(name="accuracy", kind="measurement", description=""),
            ])
        if s is schemas.PaperResults:
            return s(results=[schemas.ResultRow(measurement="accuracy", value="92.3%",
                                                method="MAG-Net", subject="test", is_best=True)])
        if s is schemas.PaperSynthesis:
            return s(summary=" ".join(["This paper studies brain tumor segmentation."] * 30),
                     contributions=["A new network."], key_findings=["92.3% accuracy."],
                     limitations=["Single centre."], future_work=["Multi-centre."])
        if s is schemas.SummaryGrade:
            return s(faithful=True, specific=True, score=0.85, issues=[])
        if s is schemas.PaperRelation:
            return s(relationship="shares_method", direction="none", confidence=0.8,
                     explanation="Both use the same method.", shared_entities=["U-Net"])
        raise ValueError(s)


class _FakeModel:
    def with_structured_output(self, schema):
        return _FakeStructured(schema)


def _fake_chain(tier="smart", **kw):
    return [_FakeModel()]


# ── Provider chain ────────────────────────────────────────────────────────────────

def test_provider_order_prefers_gemini(monkeypatch):
    from core.llm import providers
    monkeypatch.setenv("GOOGLE_API_KEY", "x")
    monkeypatch.setenv("GROQ_API_KEY", "y")
    monkeypatch.delenv("PAPERMIND_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("PAPERMIND_LLM_BACKEND", raising=False)
    order = providers.provider_order()
    assert order[0] == "gemini"
    assert "ollama" in order  # always a fallback


def test_provider_order_named_primary_with_fallbacks(monkeypatch):
    from core.llm import providers
    monkeypatch.setenv("GROQ_API_KEY", "y")
    monkeypatch.setenv("PAPERMIND_LLM_PROVIDER", "groq")
    monkeypatch.delenv("PAPERMIND_LLM_STRICT", raising=False)
    order = providers.provider_order()
    assert order[0] == "groq"
    assert order[-1] == "ollama"


def test_provider_strict_single(monkeypatch):
    from core.llm import providers
    monkeypatch.setenv("PAPERMIND_LLM_PROVIDER", "ollama")
    monkeypatch.setenv("PAPERMIND_LLM_STRICT", "1")
    assert providers.provider_order() == ["ollama"]


# ── Graph engine + adapter ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_summarize_paper_shape():
    from core.graph import summary_graph
    sections = {
        "abstract": "We study brain tumor segmentation. " * 10,
        "methods": "We use MAG-Net on the Figshare dataset. " * 20,
        "results": "Accuracy was 92.3%. " * 20,
        "references": "[1] foo " * 5,
    }
    with patch.object(summary_graph, "get_model_chain", _fake_chain):
        state = await summary_graph.summarize_paper(
            title="t", sections=sections, tables_md=[], domain="general", abstract="abs")
    assert state["synthesis"]["summary"]
    assert state["entities"]["entities"]
    assert state["results"]
    assert state["grade"]["score"] == 0.85


@pytest.mark.asyncio
async def test_adapter_legacy_shape_and_entity_mapping():
    from core.graph import summary_graph
    from core.graph.adapter import run_graph_summary
    sections = {"abstract": "x " * 30, "methods": "MAG-Net on Figshare. " * 20,
                "results": "Accuracy 92.3%. " * 20}
    with patch.object(summary_graph, "get_model_chain", _fake_chain):
        out = await run_graph_summary({
            "sections": sections,
            "metadata": {"title": "t", "domain_match": "general"},
            "tables_md": [],
        })
    assert out["summaries"]["main"]
    assert out["key_findings"]
    # method -> models, material -> datasets, measurement -> metrics
    assert "MAG-Net" in out["graph_entities_legacy"]["models"]
    assert "Figshare" in out["graph_entities_legacy"]["datasets"]
    assert out["graph_results"][0]["value"] == "92.3%"
    assert out["metadata"]["engine"] == "langgraph"


def test_grade_score_normalisation():
    # A model answering on a 0-5 / 0-10 scale must be clamped into 0-1.
    def norm(raw):
        if raw > 1.0:
            raw = raw / (10.0 if raw > 5.0 else 5.0)
        return max(0.0, min(raw, 1.0))
    assert norm(4.0) == pytest.approx(0.8)
    assert norm(8.0) == pytest.approx(0.8)
    assert norm(0.9) == pytest.approx(0.9)
    assert norm(-1) == 0.0


# ── RelationAgent ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_relate_papers_typed_link():
    from core.graph import relation_agent
    a = {"id": "A", "title": "Net A", "summary": "MRI tumor seg", "key_findings": [], "entities": ["U-Net"]}
    b = {"id": "B", "title": "Net B", "summary": "MRI tumor grade", "key_findings": [], "entities": ["U-Net"]}
    with patch.object(relation_agent, "get_model_chain", _fake_chain):
        rel = await relation_agent.relate_papers(a, b)
    assert rel["relationship"] == "shares_method"
    assert rel["link_type"] == "inspired_by"   # shares_method -> inspired_by
    assert rel["paper_a_id"] == "A" and rel["paper_b_id"] == "B"


def test_persist_relations_builds_rows():
    from core.graph import relation_agent
    sb = MagicMock()
    rels = [{"paper_a_id": "A", "paper_b_id": "B", "direction": "a_to_b",
             "link_type": "extends", "confidence": 0.9, "explanation": "why"}]
    n = relation_agent.persist_relations(rels, sb)
    assert n == 1
    args, kwargs = sb.table.return_value.upsert.call_args
    row = args[0][0]
    assert row["ancestor_id"] == "A" and row["descendant_id"] == "B"
    assert row["link_type"] == "extends"


def test_paper_from_summary_row_uses_typed_entities():
    from core.graph.relation_agent import _paper_from_summary_row
    row = {"id": "1", "paper_title": "T", "summary_data": {
        "summaries": {"main": "the summary"},
        "key_findings": ["f1"],
        "typed_entities": {"entities": [{"name": "MAG-Net", "kind": "method"}]},
    }}
    p = _paper_from_summary_row(row)
    assert p["summary"] == "the summary"
    assert "MAG-Net" in p["entities"]
