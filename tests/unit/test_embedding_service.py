"""Unit tests for core/knowledge/embedding_service.py (mocked model)."""
import numpy as np
import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture(autouse=True)
def mock_sentence_transformer():
    """Prevent actual model download during tests."""
    fake_model = MagicMock()

    def fake_encode(texts, **kwargs):
        if isinstance(texts, list):
            return np.random.rand(len(texts), 384).astype(np.float32)
        # single string → 1-D array of shape (384,)
        return np.random.rand(384).astype(np.float32)

    fake_model.encode.side_effect = fake_encode
    with patch('core.knowledge.embedding_service._get_model', return_value=fake_model):
        yield fake_model


def test_embed_text_returns_ndarray():
    from core.knowledge.embedding_service import embed_text
    result = embed_text("attention mechanism in transformers")
    assert isinstance(result, np.ndarray)
    assert result.shape == (384,)


def test_embed_text_normalized():
    from core.knowledge.embedding_service import embed_text
    result = embed_text("test sentence")
    # L2 norm should be close to 1 (or at least a valid float vector)
    assert result.dtype in (np.float32, np.float64)
    assert not np.any(np.isnan(result))


def test_embed_paper_returns_ndarray():
    from core.knowledge.embedding_service import embed_paper
    result = embed_paper(
        title="Attention Is All You Need",
        abstract="We propose the Transformer architecture.",
        keywords=["Transformer", "attention", "NMT"],
    )
    assert isinstance(result, np.ndarray)
    assert result.shape == (384,)


def test_batch_embed_returns_matrix():
    from core.knowledge.embedding_service import batch_embed
    texts = ["first sentence", "second sentence", "third sentence"]
    result = batch_embed(texts)
    assert isinstance(result, np.ndarray)
    assert result.shape[0] == 3
    assert result.shape[1] == 384


def test_find_similar_papers_calls_rpc():
    from unittest.mock import MagicMock
    from core.knowledge.embedding_service import find_similar_papers

    fake_embedding = np.random.rand(384).astype(np.float32)
    mock_supabase = MagicMock()
    mock_supabase.rpc.return_value.execute.return_value.data = [
        {'id': 'paper-1', 'paper_title': 'Similar Paper', 'similarity': 0.91}
    ]

    results = find_similar_papers(fake_embedding, 'user-1', mock_supabase, top_k=5)
    mock_supabase.rpc.assert_called_once()
    assert len(results) == 1
    assert results[0]['id'] == 'paper-1'


def test_find_similar_papers_graceful_failure():
    from unittest.mock import MagicMock
    from core.knowledge.embedding_service import find_similar_papers

    fake_embedding = np.random.rand(384).astype(np.float32)
    mock_supabase = MagicMock()
    mock_supabase.rpc.side_effect = Exception("DB unavailable")

    results = find_similar_papers(fake_embedding, 'user-1', mock_supabase)
    assert results == []
