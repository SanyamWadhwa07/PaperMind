"""Summary CRUD, export, and dashboard statistics.

Controllers only — persistence lives in `SummaryRepository`, rules in
`SummaryService`.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Query
from fastapi.responses import Response

from api.deps import SummaryServiceDep
from auth.dependencies import CurrentUser

logger = structlog.get_logger(__name__)
router = APIRouter()


@router.get('/summaries')
async def list_summaries(
    current_user: CurrentUser,
    summaries: SummaryServiceDep,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=10, ge=1, le=100),
    sort_by: str = Query(default='created_at'),
    order: str = Query(default='desc', pattern='^(asc|desc)$'),
    search: str = Query(default='', max_length=200),
):
    result = await summaries.list_summaries(
        current_user['user_id'],
        page=page,
        per_page=per_page,
        sort_by=sort_by,
        order=order,
        search=search,
    )
    return result.to_dict('summaries')


@router.get('/summaries/{summary_id}')
async def get_summary(
    summary_id: str, current_user: CurrentUser, summaries: SummaryServiceDep
):
    return {'summary': await summaries.get_summary(summary_id, current_user['user_id'])}


@router.delete('/summaries/{summary_id}')
async def delete_summary(
    summary_id: str, current_user: CurrentUser, summaries: SummaryServiceDep
):
    await summaries.delete_summary(summary_id, current_user['user_id'])
    return {'message': 'Summary deleted successfully'}


@router.get('/dashboard/stats')
async def dashboard_stats(current_user: CurrentUser, summaries: SummaryServiceDep):
    return await summaries.dashboard_stats(current_user['user_id'])


@router.get('/export/{summary_id}')
async def export_summary(
    summary_id: str,
    current_user: CurrentUser,
    summaries: SummaryServiceDep,
    format: str = Query(default='json'),
):
    content, media_type, filename = await summaries.export(
        summary_id, current_user['user_id'], format
    )
    return Response(
        content=content,
        media_type=media_type,
        headers={'Content-Disposition': f'attachment; filename="{filename}"'},
    )
