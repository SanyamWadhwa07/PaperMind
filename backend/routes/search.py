"""arXiv search endpoints.

The frontend has always called `/api/search`; it 404'd because the route was
lost in the Flask-to-FastAPI migration. Restored here on the service layer.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, Request, Response

from api.rate_limit import limit
from auth.dependencies import CurrentUser
from schemas import ArxivSearchRequest
from services.arxiv_service import ArxivService

logger = structlog.get_logger(__name__)
router = APIRouter()


def get_arxiv_service() -> ArxivService:
    return ArxivService()


@router.post('/search')
@limit('expensive')
async def search_arxiv(
    request: Request,
    response: Response,  # slowapi writes X-RateLimit-* headers here
    data: ArxivSearchRequest,
    current_user: CurrentUser,
    arxiv: ArxivService = Depends(get_arxiv_service),
):
    """Free-text search over arXiv."""
    papers = await arxiv.search(data.query, data.max_results)
    logger.info('arxiv_search', query=data.query, results=len(papers))
    return {'papers': papers, 'count': len(papers), 'query': data.query}


@router.get('/search/{arxiv_id}')
async def get_arxiv_metadata(
    arxiv_id: str,
    current_user: CurrentUser,
    arxiv: ArxivService = Depends(get_arxiv_service),
):
    """Metadata for a single arXiv paper, without processing it."""
    return {'paper': await arxiv.get_metadata(arxiv_id)}
