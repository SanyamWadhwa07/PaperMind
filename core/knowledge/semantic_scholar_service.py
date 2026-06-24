"""Semantic Scholar API integration (free, no key required)."""

import logging
from typing import List, Dict, Any, Optional

import httpx

logger = logging.getLogger(__name__)

S2_BASE = "https://api.semanticscholar.org/graph/v1"
DEFAULT_FIELDS = "title,authors,year,abstract,externalIds,citationCount,openAccessPdf"
TIMEOUT = 10


def search_papers(query: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Search Semantic Scholar for papers matching a free-text query."""
    try:
        resp = httpx.get(
            f"{S2_BASE}/paper/search",
            params={"query": query, "limit": min(limit, 20), "fields": DEFAULT_FIELDS},
            timeout=TIMEOUT,
        )
        if resp.status_code == 200:
            return resp.json().get("data", [])
        logger.warning("s2_search_non_200", status=resp.status_code)
    except Exception as e:
        logger.error("s2_search_error", error=str(e))
    return []


def get_paper_details(paper_id: str) -> Optional[Dict[str, Any]]:
    """Fetch a single paper's details from Semantic Scholar by S2 paper ID or arXiv ID."""
    try:
        resp = httpx.get(
            f"{S2_BASE}/paper/{paper_id}",
            params={"fields": DEFAULT_FIELDS + ",references,citations"},
            timeout=TIMEOUT,
        )
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        logger.error("s2_paper_details_error", paper_id=paper_id, error=str(e))
    return None


def get_citations(paper_id: str, limit: int = 20) -> List[Dict]:
    """Fetch papers that cite the given paper."""
    try:
        resp = httpx.get(
            f"{S2_BASE}/paper/{paper_id}/citations",
            params={"fields": "title,authors,year,externalIds", "limit": limit},
            timeout=TIMEOUT,
        )
        if resp.status_code == 200:
            raw = resp.json().get("data", [])
            return [r.get("citingPaper", r) for r in raw]
    except Exception as e:
        logger.error("s2_citations_error", error=str(e))
    return []


def normalize_s2_paper(paper: Dict) -> Dict:
    """Normalise a S2 paper dict for frontend display."""
    arxiv_id = paper.get("externalIds", {}).get("ArXiv")
    return {
        "s2_id": paper.get("paperId", ""),
        "title": paper.get("title", ""),
        "authors": [a.get("name", "") for a in (paper.get("authors") or [])[:6]],
        "year": paper.get("year"),
        "abstract": (paper.get("abstract") or "")[:400],
        "arxiv_id": arxiv_id,
        "citation_count": paper.get("citationCount"),
        "open_access_pdf": paper.get("openAccessPdf", {}).get("url") if paper.get("openAccessPdf") else None,
        "can_import": bool(arxiv_id),
    }
