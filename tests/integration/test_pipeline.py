"""Integration tests for the 7-agent parallel pipeline.

Uses a real PDF fixture but mocks the LLM so Ollama isn't required.
Verifies the end-to-end orchestrator output shape.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, patch

pytest.importorskip('fitz', reason='PyMuPDF required for pipeline tests')


CANNED_SUMMARY = (
    'This paper proposes the Transformer, a novel sequence transduction model. '
    'The key innovation is replacing recurrence with multi-head self-attention. '
    'Experiments on WMT 2014 demonstrate strong performance on machine translation.'
)


@pytest.fixture
def mock_llm_generate():
    """Patch LocalLLM.generate to return a canned summary without Ollama."""
    with patch('core.llm.llm_interface.LocalLLM.generate', new_callable=AsyncMock) as m:
        m.return_value = CANNED_SUMMARY
        yield m


@pytest.fixture
def orchestrator():
    from core.agents.orchestrator import ParallelAgentOrchestrator
    return ParallelAgentOrchestrator(patterns={}, config={}, experience_store=None)


@pytest.mark.asyncio
async def test_pipeline_returns_summaries(orchestrator, test_pdf_path, mock_llm_generate):
    """Full orchestrator run should produce a non-empty summary.

    The current SummaryAgent yields a single comprehensive summary under the
    'main' key (not the legacy simple/detailed/eli5/technical quartet).
    """
    result = await orchestrator.process_paper(test_pdf_path)
    summary = result.get('summary', {})
    summaries = summary.get('summaries', {})
    assert summaries, 'summaries should not be empty'
    assert any(isinstance(v, str) and len(v) > 20 for v in summaries.values()), \
        f'expected a non-trivial summary, got {summaries!r}'


@pytest.mark.asyncio
async def test_pipeline_returns_structure(orchestrator, test_pdf_path, mock_llm_generate):
    """Orchestrator should return a structure dict with sections."""
    result = await orchestrator.process_paper(test_pdf_path)
    structure = result.get('structure', {})
    sections = structure.get('sections', {})
    assert isinstance(sections, dict), 'sections must be a dict'
    assert len(sections) >= 2, f'Expected >= 2 sections, got {list(sections.keys())}'


@pytest.mark.asyncio
async def test_pipeline_returns_entities(orchestrator, test_pdf_path, mock_llm_generate):
    """Orchestrator should return entities with at least the standard keys."""
    result = await orchestrator.process_paper(test_pdf_path)
    entities = result.get('entities', {}).get('entities', {})
    for key in ('models', 'datasets', 'metrics'):
        assert key in entities, f'Missing entity key: {key}'
        assert isinstance(entities[key], list)


@pytest.mark.asyncio
async def test_pipeline_metadata_present(orchestrator, test_pdf_path, mock_llm_generate):
    """Orchestrator metadata should include timing and agent count."""
    result = await orchestrator.process_paper(test_pdf_path)
    meta = result.get('metadata', {})
    assert 'total_time_ms' in meta, 'total_time_ms missing from metadata'
    assert 'agent_count' in meta, 'agent_count missing from metadata'
    assert meta['agent_count'] > 0


@pytest.mark.asyncio
async def test_pipeline_cleanup(orchestrator, test_pdf_path, mock_llm_generate):
    """Orchestrator cleanup should complete without raising."""
    await orchestrator.process_paper(test_pdf_path)
    await orchestrator.cleanup()  # must not raise


@pytest.mark.asyncio
async def test_agent_integration_wrapper(test_pdf_path, mock_llm_generate):
    """AgentPaperProcessor.process_paper should return the legacy-format dict."""
    from core.agent_integration import AgentPaperProcessor
    processor = AgentPaperProcessor(patterns={}, config={})
    try:
        result = await processor.process_paper(test_pdf_path)
        assert 'summaries' in result, 'summaries missing from AgentPaperProcessor output'
        assert 'entities' in result or 'models' in result, 'entity data missing from output'
    finally:
        await processor.cleanup()
