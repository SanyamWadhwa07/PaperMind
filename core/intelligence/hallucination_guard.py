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

import re
from typing import Dict, List, Tuple

import numpy as np
import structlog

logger = structlog.get_logger(__name__)

# Semantic similarity separates a claim about *this* paper from one about some
# other paper. It does NOT separate a true number from a false one, and measuring
# it settled that: over the labelled claim set in `evals/golden/`, cosine
# similarity classified close negatives at chance — accuracy 0.500 at every
# threshold from 0.05 to 0.50, peaking at 0.625. "The model reaches 28.4 BLEU"
# and "…31.7 BLEU" are near-identical vectors, because they *are* near-identical
# sentences; only one digit carries the falsehood.
#
# So the guard is two rules, not one:
#   1. numeric  — deterministic, and decisive when it fires. A claim asserting a
#                 number the paper never states is unsupported no matter how
#                 similar it reads.
#   2. semantic — cosine similarity, for everything the first rule cannot judge.
#
# Re-derive this constant with: python evals/golden_eval.py calibrate
SIMILARITY_THRESHOLD = 0.45

# Sentences shorter than this carry too little signal to match against.
_MIN_CHUNK_CHARS = 20

# pymupdf4llm renders a decimal point in prose as `_._`, so "28.4" reaches this
# module as "28 _._ 4". Comparing numbers without repairing that first would
# flag every correctly-extracted decimal as a hallucination.
_DECIMAL_ARTEFACT_RE = re.compile(r"(\d)\s*_\.\_\s*(\d)")
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")

# Numbers too generic to carry evidence. A year or a small ordinal appears in
# almost any paper, so requiring it to match adds no signal and costs recall.
_UNINFORMATIVE_NUMBERS = {str(y) for y in range(1900, 2100)}


def normalise_numbers(text: str) -> str:
    """Repair extractor artefacts so numbers can be compared as numbers."""
    if not text:
        return ""
    repaired = _DECIMAL_ARTEFACT_RE.sub(r"\1.\2", text)
    return re.sub(r"\s+", " ", repaired.replace("_", ""))


def numbers_in(text: str) -> List[str]:
    """Every number in `text`, normalised, with trailing zeros trimmed.

    `28.40` and `28.4` are the same measurement; comparing the raw strings would
    make a correct extraction indistinguishable from an invented one.
    """
    out: List[str] = []
    for raw in _NUMBER_RE.findall(normalise_numbers(text)):
        value = raw.rstrip("0").rstrip(".") if "." in raw else raw
        out.append(value or "0")
    return out


def _numeric_verdict(claim: str, source_numbers: set) -> Tuple[bool, List[str]]:
    """Do the numbers this claim asserts actually occur in the paper?

    Returns ``(decided, missing)``. `decided` is False when the claim asserts no
    informative number, in which case the semantic rule takes over.

    Deliberately conservative in one direction: a number the summary *derived*
    (a delta, a mean) will not appear verbatim and gets flagged. Surfacing a
    correct-but-derived figure for review is the safe error; silently blessing a
    fabricated one is not.
    """
    asserted = [n for n in numbers_in(claim) if n not in _UNINFORMATIVE_NUMBERS]
    if not asserted:
        return False, []
    missing = [n for n in asserted if n not in source_numbers]
    return True, missing


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

    # Every number the paper actually states, gathered once.
    source_numbers = set()
    for _, sentence in source_chunks:
        source_numbers.update(numbers_in(sentence))

    results: List[Dict] = []
    for claim, row in zip(claims, sims):
        best_idx = int(np.argmax(row))
        best_sim = float(row[best_idx])

        decided, missing = _numeric_verdict(claim, source_numbers)
        if decided:
            grounded = not missing
            rule = "numeric"
        else:
            grounded = bool(best_sim >= SIMILARITY_THRESHOLD)
            rule = "semantic"

        entry = {
            "claim": claim,
            "grounded": grounded,
            "best_similarity": round(best_sim, 4),
            "source_section": source_chunks[best_idx][0],
            "rule": rule,
        }
        if missing:
            # Naming the offending value makes the flag actionable instead of a
            # bare red badge the reader has to re-derive.
            entry["unsupported_numbers"] = missing
        results.append(entry)
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
