"""User summary CRUD, export, and dashboard stats."""

import asyncio
import structlog
import tempfile
from datetime import datetime, timedelta
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse, FileResponse
from supabase import create_client

from database.config import SUPABASE_URL, SUPABASE_SERVICE_KEY
from auth.dependencies import CurrentUser

logger = structlog.get_logger(__name__)
router = APIRouter()
supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

_SORTABLE = {'created_at', 'paper_title', 'processing_time_seconds', 'word_count'}


@router.get('/summaries')
async def get_user_summaries(
    current_user: CurrentUser,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=10, ge=1, le=100),
    sort_by: str = Query(default='created_at'),
    order: str = Query(default='desc'),
    search: str = Query(default=''),
):
    user_id = current_user['user_id']
    if sort_by not in _SORTABLE:
        sort_by = 'created_at'
    search = search[:200]
    offset = (page - 1) * per_page

    try:
        query = (
            supabase.table('summaries')
            .select('*', count='exact')
            .eq('user_id', user_id)
        )
        if search:
            query = query.or_(f'paper_title.ilike.%{search}%,arxiv_id.ilike.%{search}%')
        query = query.order(sort_by, desc=(order == 'desc')).range(offset, offset + per_page - 1)

        result = await asyncio.to_thread(query.execute)
        return {
            'summaries': result.data,
            'total': result.count,
            'page': page,
            'per_page': per_page,
            'total_pages': (result.count + per_page - 1) // per_page if result.count else 0,
        }
    except Exception as e:
        logger.exception('get_summaries_error', error=str(e))
        return JSONResponse(status_code=500, content={'error': 'Failed to fetch summaries'})


@router.get('/summaries/{summary_id}')
async def get_summary(summary_id: str, current_user: CurrentUser):
    user_id = current_user['user_id']
    try:
        result = await asyncio.to_thread(
            lambda: supabase.table('summaries')
            .select('*')
            .eq('id', summary_id)
            .eq('user_id', user_id)
            .execute()
        )
        if not result.data:
            return JSONResponse(status_code=404, content={'error': 'Summary not found'})
        return {'summary': result.data[0]}
    except Exception as e:
        logger.exception('get_summary_error', summary_id=summary_id, error=str(e))
        return JSONResponse(status_code=500, content={'error': 'Failed to fetch summary'})


@router.delete('/summaries/{summary_id}')
async def delete_summary(summary_id: str, current_user: CurrentUser):
    user_id = current_user['user_id']
    try:
        check = await asyncio.to_thread(
            lambda: supabase.table('summaries')
            .select('id')
            .eq('id', summary_id)
            .eq('user_id', user_id)
            .execute()
        )
        if not check.data:
            return JSONResponse(status_code=404, content={'error': 'Summary not found or unauthorized'})

        await asyncio.to_thread(
            lambda: supabase.table('summaries').delete().eq('id', summary_id).execute()
        )
        return {'message': 'Summary deleted successfully'}
    except Exception as e:
        logger.exception('delete_summary_error', summary_id=summary_id, error=str(e))
        return JSONResponse(status_code=500, content={'error': 'Failed to delete summary'})


@router.get('/dashboard/stats')
async def get_dashboard_stats(current_user: CurrentUser):
    user_id = current_user['user_id']
    try:
        stats_result = await asyncio.to_thread(
            lambda: supabase.table('user_summary_stats').select('*').eq('user_id', user_id).execute()
        )
        activity_result = await asyncio.to_thread(
            lambda: supabase.table('user_activity')
            .select('*')
            .eq('user_id', user_id)
            .order('created_at', desc=True)
            .limit(10)
            .execute()
        )
        six_months_ago = (datetime.utcnow() - timedelta(days=180)).isoformat()
        monthly_result = await asyncio.to_thread(
            lambda: supabase.table('summaries')
            .select('created_at')
            .eq('user_id', user_id)
            .gte('created_at', six_months_ago)
            .execute()
        )

        monthly_counts: dict[str, int] = {}
        for s in (monthly_result.data or []):
            key = s['created_at'][:7]
            monthly_counts[key] = monthly_counts.get(key, 0) + 1

        stats = stats_result.data[0] if stats_result.data else {}
        return {
            'stats': {
                'total_summaries':       stats.get('total_summaries', 0),
                'avg_processing_time':   float(stats.get('avg_processing_time', 0) or 0),
                'total_words_processed': stats.get('total_words_processed', 0),
                'last_summary_date':     stats.get('last_summary_date'),
                'active_days':           stats.get('active_days', 0),
            },
            'recent_activity':   activity_result.data,
            'monthly_summaries': monthly_counts,
        }
    except Exception as e:
        logger.exception('dashboard_stats_error', error=str(e))
        return JSONResponse(status_code=500, content={'error': 'Failed to fetch stats'})


@router.get('/export/{summary_id}')
async def export_summary(summary_id: str, current_user: CurrentUser, format: str = 'json'):
    user_id = current_user['user_id']
    try:
        result = await asyncio.to_thread(
            lambda: supabase.table('summaries')
            .select('*')
            .eq('id', summary_id)
            .eq('user_id', user_id)
            .execute()
        )
        if not result.data:
            return JSONResponse(status_code=404, content={'error': 'Summary not found'})

        row = result.data[0]

        if format == 'markdown':
            title = row.get('paper_title', 'Untitled')
            authors = ', '.join(row.get('paper_authors') or [])
            sdata = row.get('summary_data') or {}
            summaries = sdata.get('summaries', {})
            md = f"# {title}\n\n**Authors:** {authors}\n\n**arXiv:** {row.get('arxiv_id', '')}\n\n"
            for stype, text in summaries.items():
                md += f"## {stype.title()} Summary\n\n{text}\n\n"

            tmp = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.md', encoding='utf-8')
            tmp.write(md)
            tmp.close()
            arxiv_id = row.get('arxiv_id', 'paper')
            return FileResponse(
                tmp.name,
                media_type='text/markdown',
                filename=f'{arxiv_id}.md',
                headers={'Content-Disposition': f'attachment; filename="{arxiv_id}.md"'},
            )

        if format == 'bibtex':
            arxiv_id = row.get('arxiv_id', '')
            title = row.get('paper_title', 'Unknown')
            authors = ' and '.join(row.get('paper_authors') or [])
            year = (row.get('published_date') or '')[:4] or '2024'
            bib = (
                f"@article{{{arxiv_id},\n"
                f"  title   = {{{title}}},\n"
                f"  author  = {{{authors}}},\n"
                f"  year    = {{{year}}},\n"
                f"  archivePrefix = {{arXiv}},\n"
                f"  eprint  = {{{arxiv_id}}},\n"
                f"}}\n"
            )
            tmp = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.bib', encoding='utf-8')
            tmp.write(bib)
            tmp.close()
            return FileResponse(tmp.name, media_type='text/plain', filename=f'{arxiv_id}.bib')

        return row
    except Exception as e:
        logger.exception('export_error', summary_id=summary_id, error=str(e))
        return JSONResponse(status_code=500, content={'error': str(e)})
