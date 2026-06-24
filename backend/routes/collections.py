"""Collections routes — user-defined paper folders."""

import asyncio
import structlog
from datetime import datetime
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from supabase import create_client

from database.config import SUPABASE_URL, SUPABASE_SERVICE_KEY
from auth.dependencies import CurrentUser
from schemas import CollectionCreateRequest, AddPaperToCollectionRequest

logger = structlog.get_logger(__name__)
router = APIRouter()
supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


@router.get('/collections')
async def list_collections(current_user: CurrentUser):
    user_id = current_user['user_id']
    result = await asyncio.to_thread(
        lambda: supabase.table('collections').select('*').eq('user_id', user_id).execute()
    )
    return {'collections': result.data or []}


@router.post('/collections', status_code=201)
async def create_collection(data: CollectionCreateRequest, current_user: CurrentUser):
    user_id = current_user['user_id']
    now = datetime.utcnow().isoformat()
    row = {
        'user_id':     user_id,
        'name':        data.name,
        'description': data.description,
        'color':       data.color,
        'created_at':  now,
        'updated_at':  now,
    }
    try:
        result = await asyncio.to_thread(
            lambda: supabase.table('collections').insert(row).execute()
        )
        return {'collection': result.data[0] if result.data else {}}
    except Exception as e:
        logger.exception('create_collection_error', error=str(e))
        return JSONResponse(status_code=500, content={'error': str(e)})


@router.delete('/collections/{collection_id}')
async def delete_collection(collection_id: str, current_user: CurrentUser):
    user_id = current_user['user_id']
    await asyncio.to_thread(
        lambda: supabase.table('collections')
        .delete()
        .eq('id', collection_id)
        .eq('user_id', user_id)
        .execute()
    )
    return {'message': 'Deleted'}


@router.post('/collections/{collection_id}/papers', status_code=201)
async def add_paper_to_collection(
    collection_id: str, data: AddPaperToCollectionRequest, current_user: CurrentUser
):
    user_id = current_user['user_id']
    col = await asyncio.to_thread(
        lambda: supabase.table('collections')
        .select('id')
        .eq('id', collection_id)
        .eq('user_id', user_id)
        .execute()
    )
    if not col.data:
        return JSONResponse(status_code=404, content={'error': 'Collection not found'})

    await asyncio.to_thread(
        lambda: supabase.table('collection_papers')
        .upsert({
            'collection_id': collection_id,
            'summary_id':    data.summary_id,
            'added_at':      datetime.utcnow().isoformat(),
        })
        .execute()
    )
    return {'message': 'Paper added to collection'}


@router.delete('/collections/{collection_id}/papers/{summary_id}')
async def remove_paper_from_collection(
    collection_id: str, summary_id: str, current_user: CurrentUser
):
    user_id = current_user['user_id']
    col = await asyncio.to_thread(
        lambda: supabase.table('collections')
        .select('id')
        .eq('id', collection_id)
        .eq('user_id', user_id)
        .execute()
    )
    if not col.data:
        return JSONResponse(status_code=404, content={'error': 'Collection not found'})

    await asyncio.to_thread(
        lambda: supabase.table('collection_papers')
        .delete()
        .eq('collection_id', collection_id)
        .eq('summary_id', summary_id)
        .execute()
    )
    return {'message': 'Removed'}


@router.get('/collections/{collection_id}/papers')
async def get_collection_papers(collection_id: str, current_user: CurrentUser):
    user_id = current_user['user_id']
    col = await asyncio.to_thread(
        lambda: supabase.table('collections')
        .select('id, name')
        .eq('id', collection_id)
        .eq('user_id', user_id)
        .execute()
    )
    if not col.data:
        return JSONResponse(status_code=404, content={'error': 'Collection not found'})

    result = await asyncio.to_thread(
        lambda: supabase.table('collection_papers')
        .select('summary_id, added_at, summaries(paper_title, arxiv_id, created_at)')
        .eq('collection_id', collection_id)
        .execute()
    )
    return {'collection': col.data[0], 'papers': result.data or []}
