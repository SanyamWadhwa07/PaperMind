"""Unit tests for summary quality scoring in core/agents/summary_agent.py"""
import sys
import types
import pytest


@pytest.fixture(autouse=True)
def mock_heavy_deps_summary():
    """Prevent importing heavy ML deps (nltk, torch, transformers) at test time."""
    # Create a minimal nltk mock with __spec__ set to satisfy importlib checks
    nltk_mock = types.ModuleType('nltk')
    nltk_mock.__spec__ = types.ModuleType.__new__(types.ModuleType)
    sys.modules.setdefault('nltk', nltk_mock)
    sys.modules.setdefault('fitz', types.ModuleType('fitz'))
    backend_main_mock = types.ModuleType('backend.main')
    backend_main_mock.EnhancedEntityExtractor = object
    sys.modules.setdefault('backend.main', backend_main_mock)
    yield


@pytest.fixture
def summary_agent():
    from unittest.mock import MagicMock
    from core.agents.summary_agent import SummaryAgent
    agent = SummaryAgent.__new__(SummaryAgent)
    agent.llm = MagicMock()
    agent.name = "SummaryAgent"
    agent.experience = None
    agent.message_bus = None
    return agent


def test_quality_score_good_summary(summary_agent, sample_sections):
    text = (
        "This paper proposes the Transformer, a novel sequence transduction model based on "
        "attention mechanisms. The authors introduce multi-head self-attention and position-wise "
        "feed-forward layers, dispensing with recurrence entirely. On WMT 2014 English-to-German "
        "translation the model achieves 28.4 BLEU, establishing a new state of the art. "
        "The approach is more parallelizable and requires less training time than recurrent models."
    )
    score = summary_agent._score_quality(text, sample_sections['abstract'])
    poor = summary_agent._score_quality("The paper is good.", sample_sections['abstract'])
    assert score >= 0.4, f"Expected a respectable quality for a good summary, got {score}"
    assert score > poor, "A detailed summary should outscore a trivial one"


def test_quality_score_poor_summary(summary_agent, sample_sections):
    text = "The paper is good."
    score = summary_agent._score_quality(text, sample_sections['abstract'])
    assert score < 0.5, f"Expected quality < 0.5 for poor summary, got {score}"


def test_quality_score_range(summary_agent, sample_sections):
    text = "A reasonable summary of the work done in this paper."
    score = summary_agent._score_quality(text, sample_sections['abstract'])
    assert 0.0 <= score <= 1.0


def test_quality_score_empty_text(summary_agent, sample_sections):
    score = summary_agent._score_quality("", sample_sections['abstract'])
    assert 0.0 <= score <= 0.3, f"Empty summary should score low, got {score}"


def test_quality_score_rewards_keyword_coverage(summary_agent, sample_sections):
    # Summary mentioning domain keywords should score higher
    rich = (
        "The Transformer architecture uses attention mechanisms trained on WMT 2014 dataset. "
        "It achieves 28.4 BLEU outperforming LSTM and ConvS2S baselines significantly."
    )
    sparse = "The paper presents a new model for language tasks."
    rich_score = summary_agent._score_quality(rich, sample_sections['abstract'])
    sparse_score = summary_agent._score_quality(sparse, sample_sections['abstract'])
    assert rich_score >= sparse_score


def test_summary_agent_has_no_template_fallback():
    """The legacy path assembled summaries from templates when the LLM was
    unreachable ("The paper employs the following models: ..."), which is
    indistinguishable from a real summary once persisted. The graph engine is
    now the only path, and it raises instead."""
    from core.agents.summary_agent import SummaryAgent

    for removed in ('_generate_all_in_one', '_fallback_summary', '_get_system_prompt'):
        assert not hasattr(SummaryAgent, removed), f'{removed} should be gone'
