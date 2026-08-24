"""Batch comparison routes — cross-paper metrics/entity comparison."""

import asyncio
import sys
import structlog
from pathlib import Path
from fastapi import APIRouter, Request, Response
from db import supabase as _shared_supabase

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from core.knowledge.comparison_service import ComparisonError, compare_papers

from api.errors import NotFoundError, UnprocessableError
from api.rate_limit import limit
from auth.dependencies import CurrentUser
from schemas import BatchCompareRequest

logger = structlog.get_logger(__name__)
router = APIRouter()
supabase = _shared_supabase

# Every column the comparison needs. Fetched once here and passed through, so
# the ownership check and the comparison share a single read — this route used
# to query `summaries` twice per request, the second time pulling the full
# `summary_data` JSONB for up to ten papers.
_COMPARE_COLUMNS = 'id, paper_title, arxiv_id, published_date, quality_score, summary_data'


@router.post('/batch/compare')
@limit('expensive')
async def compare_papers_endpoint(
    request: Request,
    response: Response,  # receives the RateLimit-* headers
    data: BatchCompareRequest,
    current_user: CurrentUser,
):
    """Compare metrics, entities, and findings across 2–10 papers."""
    user_id = current_user['user_id']
    summary_ids = data.summary_ids

    result = await asyncio.to_thread(
        lambda: supabase.table('summaries')
        .select(_COMPARE_COLUMNS)
        .in_('id', summary_ids)
        .eq('user_id', user_id)
        .execute()
    )
    rows = result.data or []

    owned_ids = {r['id'] for r in rows}
    unauthorized = [pid for pid in summary_ids if pid not in owned_ids]
    if unauthorized:
        # 404 rather than 403: replying "forbidden" for an id the caller does
        # not own confirms that it exists, which turns this endpoint into an
        # oracle for probing other users' summary ids.
        raise NotFoundError(
            'Some paper IDs were not found in your library.',
            details={'missing_count': len(unauthorized)},
        )

    try:
        comparison = await asyncio.to_thread(
            compare_papers, summary_ids, supabase, rows
        )
    except ComparisonError as e:
        raise UnprocessableError(str(e)) from e

    return comparison
