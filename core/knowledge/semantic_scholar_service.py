"""Semantic Scholar API integration.

The API works without a key, but unauthenticated calls share one global pool
and are rate-limited aggressively — a 429 on the very first search of the day
is normal, not a sign of trouble. Every function here therefore retries with
backoff, and raises `SemanticScholarUnavailable` rather than returning an empty
list when it finally gives up: callers need to tell "the service refused us"
apart from "there are no such papers", and returning `[]` for both made a
rate-limited search read as "No matches" in the UI.

Set SEMANTIC_SCHOLAR_API_KEY (free, from the link in the 429 body) for a
private quota.
"""

import os
import random
import time
import structlog
from typing import List, Dict, Any, Optional

import httpx

logger = structlog.get_logger(__name__)

S2_BASE = "https://api.semanticscholar.org/graph/v1"
DEFAULT_FIELDS = "title,authors,year,abstract,externalIds,citationCount,openAccessPdf,url"
TIMEOUT = 10
MAX_ATTEMPTS = 3


class SemanticScholarUnavailable(RuntimeError):
    """Semantic Scholar could not be reached, or refused the request."""


def _headers() -> Dict[str, str]:
    key = os.environ.get("SEMANTIC_SCHOLAR_API_KEY", "").strip()
    return {"x-api-key": key} if key else {}


def _get(path: str, params: Dict[str, Any]) -> Any:
    """GET with backoff on the statuses S2 uses for load-shedding."""
    last_detail = "unknown error"

    for attempt in range(MAX_ATTEMPTS):
        try:
            resp = httpx.get(
                f"{S2_BASE}{path}",
                params=params,
                headers=_headers(),
                timeout=TIMEOUT,
            )
        except Exception as e:
            last_detail = str(e)
            logger.warning("s2_request_error", path=path, attempt=attempt, error=last_detail)
        else:
            if resp.status_code == 200:
                return resp.json()

            last_detail = f"HTTP {resp.status_code}"
            if resp.status_code not in (429, 500, 502, 503, 504):
                # A 400 or 404 will not improve by being asked again.
                logger.warning("s2_request_rejected", path=path, status=resp.status_code)
                raise SemanticScholarUnavailable(last_detail)
            logger.warning("s2_request_throttled", path=path, status=resp.status_code, attempt=attempt)

        if attempt < MAX_ATTEMPTS - 1:
            # Jittered backoff — the shared pool is busiest exactly when
            # everyone's clients retry in lockstep.
            time.sleep((2 ** attempt) + random.uniform(0, 0.5))

    raise SemanticScholarUnavailable(last_detail)


def search_papers(query: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Search Semantic Scholar for papers matching a free-text query."""
    data = _get(
        "/paper/search",
        {"query": query, "limit": min(limit, 20), "fields": DEFAULT_FIELDS},
    )
    return data.get("data", []) or []


def get_paper_details(paper_id: str) -> Optional[Dict[str, Any]]:
    """Fetch a single paper's details by S2 paper ID or `arXiv:<id>`."""
    try:
        return _get(f"/paper/{paper_id}", {"fields": DEFAULT_FIELDS + ",references,citations"})
    except SemanticScholarUnavailable:
        return None


def get_citations(paper_id: str, limit: int = 20) -> List[Dict]:
    """Fetch papers that cite the given paper, newest and most-cited first."""
    try:
        data = _get(
            f"/paper/{paper_id}/citations",
            {"fields": "title,authors,year,externalIds,citationCount,url", "limit": limit},
        )
    except SemanticScholarUnavailable:
        return []
    return [r.get("citingPaper", r) for r in (data.get("data", []) or [])]


def normalize_s2_paper(paper: Dict) -> Dict:
    """Normalise a S2 paper dict for frontend display."""
    arxiv_id = (paper.get("externalIds") or {}).get("ArXiv")
    open_access = paper.get("openAccessPdf") or {}
    return {
        "s2_id": paper.get("paperId", ""),
        "title": paper.get("title", ""),
        "authors": [a.get("name", "") for a in (paper.get("authors") or [])[:6]],
        "year": paper.get("year"),
        "abstract": (paper.get("abstract") or "")[:400],
        "arxiv_id": arxiv_id,
        "citation_count": paper.get("citationCount"),
        "open_access_pdf": open_access.get("url"),
        # Somewhere to send the reader even when there is no PDF: the arXiv
        # abstract page if we have an id, else the S2 record itself.
        "url": (
            f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id
            else paper.get("url") or (
                f"https://www.semanticscholar.org/paper/{paper['paperId']}"
                if paper.get("paperId") else None
            )
        ),
        "source": "semantic_scholar",
        "can_import": bool(arxiv_id),
    }
