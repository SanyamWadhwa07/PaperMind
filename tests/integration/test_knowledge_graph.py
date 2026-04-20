"""Integration tests for core/knowledge/graph_service.py (mocked Supabase)."""
import pytest
import numpy as np
from unittest.mock import MagicMock, patch


@pytest.fixture
def mock_supabase():
    client = MagicMock()
    # Default: empty results
    client.table.return_value.select.return_value \
        .eq.return_value.execute.return_value.data = []
    client.table.return_value.upsert.return_value.execute.return_value.data = []
    client.rpc.return_value.execute.return_value.data = []
    return client


def test_compute_and_cache_similarity_calls_pgvector(mock_supabase):
    from core.knowledge.graph_service import compute_and_cache_similarity

    # Mock the embedding lookup for the new summary
    mock_supabase.table.return_value.select.return_value \
        .eq.return_value.execute.return_value.data = [{
            'id': 'new-id',
            'embedding': np.random.rand(384).tolist(),
        }]
    # pgvector search returns one similar paper
    mock_supabase.rpc.return_value.execute.return_value.data = [{
        'id': 'other-id',
        'paper_title': 'Similar Paper',
        'similarity': 0.87,
    }]

    compute_and_cache_similarity('new-id', 'user-1', mock_supabase)

    # Should have called rpc for similarity search
    mock_supabase.rpc.assert_called()


def test_get_paper_recommendations_returns_list(mock_supabase):
    from core.knowledge.graph_service import get_paper_recommendations

    mock_supabase.table.return_value.select.return_value \
        .eq.return_value.order.return_value.limit.return_value \
        .execute.return_value.data = [
            {'paper_b_id': 'rec-1', 'similarity_score': 0.92},
            {'paper_b_id': 'rec-2', 'similarity_score': 0.85},
        ]

    result = get_paper_recommendations('anchor-id', mock_supabase, top_k=5)
    assert isinstance(result, list)


def test_get_knowledge_graph_structure(mock_supabase):
    from core.knowledge.graph_service import get_knowledge_graph

    # Papers
    mock_supabase.table.return_value.select.return_value \
        .eq.return_value.limit.return_value \
        .execute.return_value.data = [
            {'id': 'p1', 'paper_title': 'Paper A', 'primary_category': 'nlp'},
            {'id': 'p2', 'paper_title': 'Paper B', 'primary_category': 'ml'},
        ]

    result = get_knowledge_graph('user-1', mock_supabase)
    assert 'nodes' in result
    assert 'edges' in result
    assert isinstance(result['nodes'], list)
    assert isinstance(result['edges'], list)


def test_compute_and_cache_similarity_handles_missing_embedding(mock_supabase):
    from core.knowledge.graph_service import compute_and_cache_similarity

    # No embedding stored
    mock_supabase.table.return_value.select.return_value \
        .eq.return_value.execute.return_value.data = [{
            'id': 'new-id',
            'embedding': None,
        }]

    # Should not raise even if embedding is None
    compute_and_cache_similarity('new-id', 'user-1', mock_supabase)
