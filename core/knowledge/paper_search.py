"""Free-text paper search across the two public catalogues, with failover.

Semantic Scholar is the better source — it carries citation counts, which is
what makes ranking by influence possible at all — but unauthenticated access is
rate-limited hard enough that a 429 is the common case rather than the
exceptional one. arXiv has no such limit and no key requirement, so it backs S2
up. Both are normalised to one shape here so callers never branch on source.

The `source` field rides along on every result so the UI can say where the
answer came from, and so a degraded search is visible instead of looking like a
thin catalogue.
"""

from __future__ import annotations

import math
import re
import structlog
from typing import Any, Dict, List

logger = structlog.get_logger(__name__)


def _normalise_arxiv(result: Any) -> Dict[str, Any]:
    """Shape an `arxiv.Result` like `normalize_s2_paper` does."""
    entry_id = getattr(result, "entry_id", "") or ""
    arxiv_id = entry_id.rsplit("/", 1)[-1] if entry_id else ""
    published = getattr(result, "published", None)
    summary = (getattr(result, "summary", "") or "").strip().replace("\n", " ")

    return {
        "s2_id": None,
        "title": (getattr(result, "title", "") or "").strip().replace("\n", " "),
        "authors": [a.name for a in (getattr(result, "authors", None) or [])][:6],
        "year": published.year if published else None,
        "abstract": summary[:400],
        "arxiv_id": arxiv_id,
        # arXiv exposes no citation data. None, not 0 — the UI must be able to
        # tell "uncited" from "unknown" and hide the field rather than claim a
        # paper has never been cited.
        "citation_count": None,
        "open_access_pdf": getattr(result, "pdf_url", None),
        "url": f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else None,
        "primary_category": getattr(result, "primary_category", None),
        "source": "arxiv",
        "can_import": bool(arxiv_id),
    }


def search_arxiv(query: str, limit: int = 10, sort: str = "relevance") -> List[Dict[str, Any]]:
    """Search arXiv. `sort` is 'relevance' or 'date' (newest first)."""
    import arxiv

    criterion = (
        arxiv.SortCriterion.SubmittedDate if sort == "date"
        else arxiv.SortCriterion.Relevance
    )
    client = arxiv.Client(page_size=min(limit, 50), delay_seconds=0, num_retries=2)
    search = arxiv.Search(query=query, max_results=limit, sort_by=criterion)
    return [_normalise_arxiv(r) for r in client.results(search)]


def _try_arxiv(query: str, limit: int, sort: str = "relevance") -> List[Dict[str, Any]]:
    """`search_arxiv` that returns [] instead of raising, for speculative queries."""
    try:
        return search_arxiv(query, limit=limit, sort=sort)
    except Exception as e:
        logger.warning("arxiv_search_failed", query=query, error=str(e))
        return []


def search_papers(query: str, limit: int = 10) -> Dict[str, Any]:
    """Search for papers, preferring Semantic Scholar and falling back to arXiv.

    Returns `{"papers": [...], "source": ..., "degraded": bool}`. Raises only
    when both catalogues fail — an empty `papers` list means the query genuinely
    matched nothing.
    """
    from .semantic_scholar_service import (
        SemanticScholarUnavailable, normalize_s2_paper, search_papers as s2_search,
    )

    try:
        raw = s2_search(query, limit)
        return {
            "papers": [normalize_s2_paper(p) for p in raw],
            "source": "semantic_scholar",
            "degraded": False,
        }
    except SemanticScholarUnavailable as e:
        logger.info("s2_unavailable_falling_back_to_arxiv", query=query, reason=str(e))

    try:
        return {"papers": search_arxiv(query, limit), "source": "arxiv", "degraded": True}
    except Exception as e:
        logger.error("paper_search_failed", query=query, error=str(e))
        raise RuntimeError("Both Semantic Scholar and arXiv are unreachable right now.") from e


# ── State-of-the-art suggestions ──────────────────────────────────────────────

# Words that appear in every paper's title and carry no topical signal, so they
# only dilute a search built out of one.
_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in", "into",
    "is", "it", "its", "of", "on", "or", "that", "the", "to", "via", "with",
    "using", "towards", "toward", "approach", "method", "methods", "novel",
    "new", "learning", "deep", "neural", "network", "networks", "model",
    "models", "paper", "study", "analysis", "framework", "system",
}


def _topic_terms(title: str, entities: Dict[str, List[str]], limit: int = 5) -> List[str]:
    """Pick the words that describe what a paper is *about*.

    The title, not the entities. This looked like a job for `tasks` and
    `datasets` — they name the problem and the benchmark — but benchmark names
    are proper nouns that collide wildly across fields: "I-Haze O-Haze
    Denoising" as a query returns papers on atmospheric haze on exoplanets, and
    "GLUE SQuAD ImageNet" returns a software-quality dataset. A title states the
    topic in ordinary words, which is what a keyword index can actually match.

    `tasks` is still worth having when the pipeline extracted any, since it
    names the problem more directly than a title sometimes does.
    """
    terms: List[str] = []

    def add(value: str) -> None:
        for word in re.findall(r"[A-Za-z][A-Za-z\-]{2,}", str(value or "")):
            lowered = word.lower()
            if lowered in _STOPWORDS or lowered in {t.lower() for t in terms}:
                continue
            terms.append(word)

    for task in (entities.get("tasks") or [])[:2]:
        add(task)

    # Strip a leading "NAME:" — an acronym the rest of the world has not heard
    # of narrows a search to the one paper that coined it.
    add(re.sub(r"^\s*[A-Za-z0-9\-]{2,12}\s*:\s*", "", title or ""))

    return terms[:limit]


def _sota_candidates(terms: List[str], primary_category: str | None, want: int) -> Dict[str, Any]:
    """Gather a wide candidate pool to re-rank. Prefers S2, falls back to arXiv."""
    from .semantic_scholar_service import (
        SemanticScholarUnavailable, normalize_s2_paper, search_papers as s2_search,
    )

    plain_query = " ".join(terms)

    try:
        raw = s2_search(plain_query, want)
        if raw:
            return {
                "papers": [normalize_s2_paper(p) for p in raw],
                "source": "semantic_scholar",
                "degraded": False,
                "query": plain_query,
            }
    except SemanticScholarUnavailable as e:
        logger.info("s2_unavailable_for_sota", reason=str(e))

    # arXiv wants a field-qualified boolean query. ANDing the topical words
    # keeps results on-topic where a bare string matches any of them, and the
    # category clause stops a word like "attention" or "transformer" from
    # dragging in every field that also uses it.
    clauses = [f'all:"{term}"' for term in terms]
    query = " AND ".join(clauses)
    if primary_category:
        query = f"cat:{primary_category} AND ({query})"

    papers = _try_arxiv(query, limit=want)

    # Too narrow is the common failure: every extra ANDed term shrinks the pool,
    # and a paper with a long specific title can AND itself down to nothing.
    # Widen a step at a time rather than giving up.
    if len(papers) < 5 and len(clauses) > 2:
        query = " AND ".join(clauses[:2])
        if primary_category:
            query = f"cat:{primary_category} AND ({query})"
        papers = _try_arxiv(query, limit=want)

    if len(papers) < 5:
        query = plain_query
        papers = _try_arxiv(query, limit=want)

    return {"papers": papers, "source": "arxiv", "degraded": True, "query": query}


def find_state_of_the_art(
    title: str,
    entities: Dict[str, List[str]],
    published_year: int | None = None,
    abstract: str = "",
    primary_category: str | None = None,
    limit: int = 8,
) -> Dict[str, Any]:
    """Suggest the papers that currently define the state of the art nearby.

    "State of the art" is approximated as: same topic, no older than the paper
    in hand, and ranked by influence. Two deliberate choices:

    Ranking uses citations *per year*, not raw citations. Raw counts rank the
    oldest famous paper in a field first every time, which is the opposite of
    what "what is the state of the art now" asks for.

    Candidates are re-ranked against the paper's own embedding rather than
    trusted in the order the catalogue returned them. Keyword relevance is what
    is available to query with, but it is a poor judge of topic — the same
    vectors that already power recommendations are a much better one, and
    re-ranking is what keeps an unlucky keyword collision out of the results.
    """
    terms = _topic_terms(title, entities)
    if not terms:
        return {"papers": [], "query": "", "source": None, "degraded": False}

    # Over-fetch: the year filter and re-ranking both discard a lot.
    found = _sota_candidates(terms, primary_category, want=40)
    candidates = found["papers"]

    from datetime import datetime
    this_year = datetime.now().year

    kept = []
    for paper in candidates:
        year = paper.get("year")
        # Same paper, different catalogue entry — never suggest the paper the
        # reader is already looking at.
        if paper.get("title", "").strip().lower() == (title or "").strip().lower():
            continue
        # Keep undated results; a missing year is a metadata gap, not evidence
        # the paper is old.
        if published_year and year and year < published_year:
            continue
        kept.append(paper)

    if not kept:
        return {
            "papers": [], "query": found["query"],
            "source": found["source"], "degraded": found["degraded"],
        }

    similarity = _similarity_to_source(title, abstract, kept)

    ranked = []
    for index, paper in enumerate(kept):
        citations = paper.get("citation_count")
        if citations is None:
            # No citation data (arXiv). Recency alone, on the same 0–1 scale as
            # the impact term below so one source is not systematically ranked
            # above the other.
            age = max(0, this_year - (paper.get("year") or this_year))
            impact = max(0.0, 1.0 - age / 10.0)
        else:
            age = max(1, this_year - (paper.get("year") or this_year) + 1)
            per_year = citations / age
            # Citation counts are heavy-tailed, so compress before mixing —
            # otherwise one 50k-citation paper makes every other score zero.
            impact = min(1.0, math.log10(1 + per_year) / 3.0)

        topical = similarity[index] if similarity is not None else 0.5
        # Topic dominates. A hugely cited paper about something else is not an
        # answer to "what is the state of the art in *this*".
        ranked.append((0.7 * topical + 0.3 * impact, paper))

    ranked.sort(key=lambda pair: pair[0], reverse=True)

    papers = []
    for score, paper in ranked[:limit]:
        papers.append({**paper, "relevance": round(float(score), 3)})

    return {
        "papers": papers,
        "query": found["query"],
        "source": found["source"],
        "degraded": found["degraded"],
    }


def _similarity_to_source(title: str, abstract: str, candidates: List[Dict[str, Any]]):
    """Cosine similarity of each candidate to the source paper, in [0, 1].

    Returns None if the embedding model is unavailable, in which case ranking
    falls back to impact alone rather than failing the request.
    """
    try:
        import numpy as np
        from .embedding_service import embed_paper, batch_embed

        source = embed_paper(title=title, abstract=abstract or "")
        texts = [
            f"{c.get('title', '')} {(c.get('abstract') or '')[:400]}"
            for c in candidates
        ]
        matrix = batch_embed(texts)

        source_norm = source / (np.linalg.norm(source) + 1e-9)
        rows = matrix / (np.linalg.norm(matrix, axis=1, keepdims=True) + 1e-9)
        # Cosine runs [-1, 1]; shift to [0, 1] so it mixes with impact cleanly.
        return ((rows @ source_norm) + 1.0) / 2.0
    except Exception as e:
        logger.warning("sota_rerank_unavailable", error=str(e))
        return None
