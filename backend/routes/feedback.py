"""Feedback routes — star ratings and error reports for summaries."""

import asyncio
import structlog
from datetime import datetime
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from supabase import create_client

from database.config import SUPABASE_URL, SUPABASE_SERVICE_KEY
from auth.dependencies import CurrentUser
from schemas import FeedbackRequest

logger = structlog.get_logger(__name__)
router = APIRouter()
supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

VALID_TYPES = {'rating', 'error_report', 'flag_hallucination'}


@router.post('/feedback/summary/{summary_id}', status_code=201)
async def submit_feedback(summary_id: str, data: FeedbackRequest, current_user: CurrentUser):
    user_id = current_user['user_id']
    feedback_type = data.feedback_type if data.feedback_type in VALID_TYPES else 'rating'

    try:
        row = {
            'summary_id':    summary_id,
            'user_id':       user_id,
            'rating':        data.rating,
            'feedback_type': feedback_type,
            'comment':       data.comment,
            'created_at':    datetime.utcnow().isoformat(),
        }
        await asyncio.to_thread(
            lambda: supabase.table('summary_feedback')
            .upsert(row, on_conflict='summary_id,user_id')
            .execute()
        )
        return {'message': 'Feedback saved'}
    except Exception as e:
        logger.exception('submit_feedback_error', summary_id=summary_id, error=str(e))
        return JSONResponse(status_code=500, content={'error': str(e)})


@router.get('/feedback/summary/{summary_id}')
async def get_feedback(summary_id: str, current_user: CurrentUser):
    try:
        result = await asyncio.to_thread(
            lambda: supabase.table('summary_feedback')
            .select('rating, feedback_type, comment, created_at')
            .eq('summary_id', summary_id)
            .execute()
        )
        rows = result.data or []
        ratings = [r['rating'] for r in rows if r.get('rating') is not None]
        avg_rating = round(sum(ratings) / len(ratings), 2) if ratings else None

        return {
            'summary_id':     summary_id,
            'average_rating': avg_rating,
            'rating_count':   len(ratings),
            'total_feedback': len(rows),
            'feedback':       rows,
        }
    except Exception as e:
        logger.exception('get_feedback_error', summary_id=summary_id, error=str(e))
        return JSONResponse(status_code=500, content={'error': str(e)})
