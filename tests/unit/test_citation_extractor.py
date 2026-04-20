"""Unit tests for core/knowledge/citation_extractor.py"""
import pytest
from core.knowledge.citation_extractor import (
    extract_citations,
    extract_citation_contexts,
    match_arxiv_ids_to_library,
)

SAMPLE_REFERENCES = """
[1] Vaswani, A., Shazeer, N., Parmar, N., et al. Attention is all you need. NeurIPS 2017.
[2] Devlin, J., Chang, M., Lee, K., Toutanova, K. BERT: Pre-training of deep bidirectional transformers. arXiv:1810.04805.
[3] He, K., Zhang, X., Ren, S., Sun, J. Deep residual learning for image recognition. CVPR 2016.
"""

NUMBERED_REFERENCES = """
1. Brown, T., et al. Language models are few-shot learners. NeurIPS 2020.
2. Dosovitskiy, A., et al. An image is worth 16x16 words. arXiv:2010.11929.
"""


def test_extract_citations_bracket_style():
    citations = extract_citations(SAMPLE_REFERENCES)
    assert len(citations) == 3


def test_extract_citations_numbered_style():
    citations = extract_citations(NUMBERED_REFERENCES)
    assert len(citations) == 2


def test_extract_citations_title_heuristic():
    citations = extract_citations(SAMPLE_REFERENCES)
    titles = [c.get('cited_title') or '' for c in citations]
    titles_lower = [t.lower() for t in titles]
    # At least one citation should have a non-empty title
    assert any(t for t in titles)


def test_extract_citations_arxiv_id():
    citations = extract_citations(SAMPLE_REFERENCES)
    arxiv_ids = [c.get('cited_arxiv_id') for c in citations if c.get('cited_arxiv_id')]
    assert any('1810.04805' in aid for aid in arxiv_ids)


def test_extract_citations_empty():
    citations = extract_citations("")
    assert citations == []


def test_extract_citation_contexts_returns_list():
    full_text = (
        "Our work builds on [1] which proposed the Transformer architecture. "
        "The baseline [2] uses BERT embeddings."
    )
    citations = [
        {'raw': '[1] Vaswani et al. Attention is all you need.', 'cited_arxiv_id': None},
        {'raw': '[2] Devlin et al. BERT.', 'cited_arxiv_id': None},
    ]
    result = extract_citation_contexts(full_text, citations)
    # Should return same number of citations (with context added where found)
    assert isinstance(result, list)
    assert len(result) == len(citations)


def test_match_arxiv_ids_to_library_matches():
    from unittest.mock import MagicMock
    mock_supabase = MagicMock()
    # chain: .table().select().eq().in_().execute()
    mock_supabase.table.return_value.select.return_value \
        .eq.return_value.in_.return_value \
        .execute.return_value.data = [{'id': 'abc-123', 'arxiv_id': '1810.04805'}]

    citations = [{'cited_arxiv_id': '1810.04805', 'cited_title': 'BERT'}]
    result = match_arxiv_ids_to_library(citations, mock_supabase, user_id='user-1')
    matched = [c for c in result if c.get('matched_summary_id')]
    assert len(matched) == 1
    assert matched[0]['matched_summary_id'] == 'abc-123'


def test_match_arxiv_ids_to_library_no_match():
    from unittest.mock import MagicMock
    mock_supabase = MagicMock()
    mock_supabase.table.return_value.select.return_value \
        .eq.return_value.in_.return_value \
        .execute.return_value.data = []

    citations = [{'cited_arxiv_id': '9999.99999', 'cited_title': 'Unknown paper'}]
    result = match_arxiv_ids_to_library(citations, mock_supabase, user_id='user-1')
    assert all(not c.get('matched_summary_id') for c in result)
