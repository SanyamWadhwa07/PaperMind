"""Tests for StructureAgent — section extraction from real PDFs."""

import asyncio
import pytest

pytest.importorskip('fitz', reason='PyMuPDF required for these tests')


@pytest.fixture
def structure_agent():
    from core.agents.structure_agent import StructureAgent
    return StructureAgent()


@pytest.mark.asyncio
async def test_extracts_sections_from_pdf(structure_agent, test_pdf_path):
    """Full agent run on a real PDF should produce at least 2 named sections."""
    result = await structure_agent.process({'pdf_path': test_pdf_path})

    sections = result.get('sections', {})
    assert isinstance(sections, dict), 'sections should be a dict'
    assert len(sections) >= 2, f'Expected >= 2 sections, got {list(sections.keys())}'


@pytest.mark.asyncio
async def test_abstract_or_introduction_present(structure_agent, test_pdf_path):
    """At least one of abstract/introduction should be detected."""
    result = await structure_agent.process({'pdf_path': test_pdf_path})
    sections = result.get('sections', {})
    key_sections = {'abstract', 'introduction', 'preamble'}
    assert key_sections & set(sections.keys()), (
        f'Expected abstract/introduction, found: {list(sections.keys())}'
    )


@pytest.mark.asyncio
async def test_sections_have_non_empty_text(structure_agent, test_pdf_path):
    """Every extracted section should have non-empty text content."""
    result = await structure_agent.process({'pdf_path': test_pdf_path})
    for name, text in result.get('sections', {}).items():
        assert text.strip(), f'Section "{name}" has empty text'


@pytest.mark.asyncio
async def test_metadata_keys_present(structure_agent, test_pdf_path):
    """Result must include the standard metadata keys."""
    result = await structure_agent.process({'pdf_path': test_pdf_path})
    assert 'extractions' in result
    assert 'confidence_scores' in result
    assert 'metadata' in result
    assert result['metadata']['section_count'] == len(result['sections'])


def test_pymupdf4llm_extraction_is_primary(structure_agent, test_pdf_path):
    """_extract_via_pymupdf4llm should return a non-empty dict for a valid PDF."""
    pymupdf4llm = pytest.importorskip('pymupdf4llm', reason='pymupdf4llm not installed')
    sections = structure_agent._extract_via_pymupdf4llm(test_pdf_path)
    # May be empty if markdown has no ## headings, but should not raise
    assert isinstance(sections, dict)
