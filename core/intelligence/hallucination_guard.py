"""Hallucination guard — verifies each LLM-generated claim has textual grounding.

A claim can come back in three states, and keeping them distinct is the whole
point of this module:

    grounded=True   — checked, and supported by the source text
    grounded=False  — checked, and NOT supported (a likely hallucination)
    grounded=None   — could not be checked

The third must never be reported as the first. An earlier version returned
``grounded=True`` with ``best_similarity=1.0`` — the maximum — on every failure
path, so a green "grounded" badge carried strictly negative information. It also
imported an ``EmbeddingService`` class this project never defined, so that
failure path was the *only* path that ever ran.
"""

from typing import Dict, List, Tuple

import numpy as np
import structlog

logger = structlog.get_logger(__name__)

# Calibrated against all-MiniLM-L6-v2 cosine scores on real paper text. Because
# the broken import meant this code never executed, the previous 0.75 was never
# exercised — and it sits *inside* the genuine-claim range, so it would have
# flagged faithful claims as hallucinations. Observed on a worked example:
#   supported, near-verbatim ....... 0.92
#   supported, paraphrased ......... 0.72
#   supported, abstractive ......... 0.52
#   unrelated (invented) ........... 0.09
#   unrelated (nonsense) ........... 0.04
# 0.45 sits in the empty band between the two clusters. Worth re-checking
# against a larger labelled sample before treating it as settled.
SIMILARITY_THRESHOLD = 0.45

# Sentences shorter than this carry too little signal to match against.
_MIN_CHUNK_CHARS = 20


def _unverified(claim: str, reason: str) -> Dict:
    """A claim that could not be checked — distinct from one checked and found grounded."""
    return {
        "claim": claim,
        "grounded": None,
        "best_similarity": None,
        "source_section": None,
        "unverified_reason": reason,
    }


def _split_sentences(text: str) -> List[str]:
    return [
        s.strip()
        for s in text.replace("\n", " ").split(". ")
        if len(s.strip()) >= _MIN_CHUNK_CHARS
    ]


def verify_claims(
    claims: List[str],
    source_sections: Dict[str, str],
) -> List[Dict]:
    """Check each claim's cosine similarity against the paper's own sentences.

    Returns a list of ``{claim, grounded, best_similarity, source_section}``.
    Claims below ``SIMILARITY_THRESHOLD`` get ``grounded=False``; claims that
    could not be checked get ``grounded=None`` plus an ``unverified_reason``.
    """
    if not claims:
        return []

    try:
        from core.knowledge import embedding_service
    except Exception as e:
        logger.warning("hallucination_guard_embedding_unavailable", error=str(e))
        return [_unverified(c, f"embedding service unavailable: {type(e).__name__}")
                for c in claims]

    # Sentence-level source chunks, remembering which section each came from.
    source_chunks: List[Tuple[str, str]] = []
    for section, text in (source_sections or {}).items():
        if text:
            source_chunks.extend((section, s) for s in _split_sentences(text))

    if not source_chunks:
        return [_unverified(c, "no source text available to verify against") for c in claims]

    try:
        chunk_emb = np.asarray(embedding_service.batch_embed([c[1] for c in source_chunks]))
        claim_emb = np.asarray(embedding_service.batch_embed(list(claims)))
    except Exception as e:
        logger.warning("hallucination_guard_embedding_failed", error=str(e))
        return [_unverified(c, f"embedding failed: {type(e).__name__}") for c in claims]

    # batch_embed normalises its output, so the dot product is the cosine similarity.
    sims = claim_emb @ chunk_emb.T          # (n_claims, n_chunks)

    results: List[Dict] = []
    for claim, row in zip(claims, sims):
        best_idx = int(np.argmax(row))
        best_sim = float(row[best_idx])
        results.append({
            "claim": claim,
            "grounded": bool(best_sim >= SIMILARITY_THRESHOLD),
            "best_similarity": round(best_sim, 4),
            "source_section": source_chunks[best_idx][0],
        })
    return results


def _cosine_similarity(a: List[float], b: List[float]) -> float:
    """Retained for callers outside this module."""
    if a is None or b is None or len(a) != len(b) or not len(a):
        return 0.0
    va, vb = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    na, nb = np.linalg.norm(va), np.linalg.norm(vb)
    if na == 0 or nb == 0:
        return 0.0
    return float(va @ vb / (na * nb))
