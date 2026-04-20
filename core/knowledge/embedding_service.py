"""Sentence embedding service using all-MiniLM-L6-v2.

Provides a lazy-loaded singleton for generating 384-dimensional embeddings.
Used for paper-to-paper similarity search via Supabase pgvector.
"""

from __future__ import annotations
import logging
from typing import List, Optional, Dict, Any
import numpy as np

logger = logging.getLogger(__name__)

_model_instance = None


def _get_model():
    global _model_instance
    if _model_instance is None:
        try:
            from sentence_transformers import SentenceTransformer
            _model_instance = SentenceTransformer('all-MiniLM-L6-v2')
            logger.info("embedding_model_loaded: all-MiniLM-L6-v2")
        except Exception as e:
            logger.error("embedding_model_load_failed: %s", str(e))
            raise
    return _model_instance


def embed_text(text: str) -> np.ndarray:
    """Generate a 384-dim embedding for arbitrary text."""
    model = _get_model()
    return model.encode(text, normalize_embeddings=True)


def embed_paper(title: str, abstract: str, keywords: Optional[List[str]] = None) -> np.ndarray:
    """Generate a composite embedding for a paper (title + abstract + keywords)."""
    parts = [title, abstract]
    if keywords:
        parts.append(', '.join(keywords[:20]))
    combined = ' '.join(filter(None, parts))[:2048]  # cap at 2k chars
    return embed_text(combined)


def batch_embed(texts: List[str]) -> np.ndarray:
    """Generate embeddings for a list of texts efficiently."""
    model = _get_model()
    return model.encode(texts, normalize_embeddings=True, batch_size=32, show_progress_bar=False)


def find_similar_papers(
    embedding: np.ndarray,
    user_id: str,
    supabase_client,
    top_k: int = 10,
    min_similarity: float = 0.5
) -> List[Dict[str, Any]]:
    """Query Supabase with pgvector cosine distance to find similar papers.

    Returns list of dicts with keys: id, paper_title, similarity_score.
    """
    try:
        vector_list = embedding.tolist()
        result = supabase_client.rpc(
            'match_papers',
            {
                'query_embedding': vector_list,
                'p_user_id': user_id,
                'match_count': top_k,
                'min_similarity': min_similarity,
            }
        ).execute()
        return result.data or []
    except Exception as e:
        logger.warning("similarity_search_failed: %s", str(e))
        return []
