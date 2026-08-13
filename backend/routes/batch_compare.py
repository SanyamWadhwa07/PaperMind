"""Batch comparison routes — cross-paper metrics/entity comparison."""

import asyncio
import sys
import structlog
from pathlib import Path
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from db import supabase as _shared_supabase

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from core.knowledge.comparison_service import compare_papers

from auth.dependencies import CurrentUser
from schemas import BatchCompareRequest

logger = structlog.get_logger(__name__)
router = APIRouter()
supabase = _shared_supabase


@router.post('/batch/compare')
async def compare_papers_endpoint(data: BatchCompareRequest, current_user: CurrentUser):
    """Compare metrics, entities, and findings across 2–10 papers."""
    user_id = current_user['user_id']
    summary_ids = data.summary_ids

    result = await asyncio.to_thread(
        lambda: supabase.table('summaries')
        .select('id')
        .in_('id', summary_ids)
        .eq('user_id', user_id)
        .execute()
    )
    owned_ids = {r['id'] for r in (result.data or [])}
    unauthorized = [pid for pid in summary_ids if pid not in owned_ids]
    if unauthorized:
        return JSONResponse(
            status_code=403,
            content={'error': 'Some paper IDs not found or not owned by you'},
        )

    try:
        comparison = await asyncio.to_thread(compare_papers, summary_ids, supabase)
        return comparison
    except Exception as e:
        logger.exception('batch_compare_error', error=str(e))
        return JSONResponse(status_code=500, content={'error': str(e)})
