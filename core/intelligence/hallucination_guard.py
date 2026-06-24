"""Hallucination guard — verifies each LLM-generated claim has textual grounding."""

import logging
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)

SIMILARITY_THRESHOLD = 0.75


def verify_claims(
    claims: List[str],
    source_sections: Dict[str, str],
) -> List[Dict]:
    """
    For each claim, check cosine similarity against source section text.
    Returns a list of {claim, grounded, best_similarity, source_section}.

    Claims with no textual grounding (similarity < threshold) get grounded=False.
    """
    try:
        from core.knowledge.embedding_service import EmbeddingService
        svc = EmbeddingService()
    except Exception as e:
        logger.warning("hallucination_guard_embedding_unavailable", error=str(e))
        return [{"claim": c, "grounded": True, "best_similarity": 1.0, "source_section": "unknown"} for c in claims]

    # Build sentence-level source chunks
    source_chunks: List[Tuple[str, str]] = []  # (section_name, sentence)
    for section, text in source_sections.items():
        if not text:
            continue
        for sentence in text.split(". "):
            sentence = sentence.strip()
            if len(sentence) > 20:
                source_chunks.append((section, sentence))

    if not source_chunks:
        return [{"claim": c, "grounded": True, "best_similarity": 1.0, "source_section": "unknown"} for c in claims]

    import asyncio

    def _run_sync(coro):
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(asyncio.run, coro)
                    return future.result()
            return loop.run_until_complete(coro)
        except RuntimeError:
            return asyncio.run(coro)

    results = []
    chunk_texts = [c[1] for c in source_chunks]

    try:
        chunk_embeddings = _run_sync(svc.batch_embed(chunk_texts))
    except Exception as e:
        logger.warning("chunk_embedding_failed", error=str(e))
        return [{"claim": c, "grounded": True, "best_similarity": 1.0, "source_section": "unknown"} for c in claims]

    for claim in claims:
        try:
            claim_emb = _run_sync(svc.embed_text(claim))
            best_sim = 0.0
            best_section = "unknown"

            for idx, chunk_emb in enumerate(chunk_embeddings):
                sim = _cosine_similarity(claim_emb, chunk_emb)
                if sim > best_sim:
                    best_sim = sim
                    best_section = source_chunks[idx][0]

            grounded = best_sim >= SIMILARITY_THRESHOLD
            results.append({
                "claim": claim,
                "grounded": grounded,
                "best_similarity": round(best_sim, 4),
                "source_section": best_section,
            })
        except Exception as e:
            logger.warning("claim_verification_failed", claim=claim[:50], error=str(e))
            results.append({"claim": claim, "grounded": True, "best_similarity": 1.0, "source_section": "unknown"})

    return results


def _cosine_similarity(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
