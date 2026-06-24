"""Knowledge graph routes — semantic search, recommendations, timeline, ancestry."""

import asyncio
import sys
import structlog
from pathlib import Path
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from supabase import create_client

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from core.knowledge.graph_service import get_knowledge_graph, get_paper_recommendations
from core.knowledge.lineage_service import get_ancestry_tree, build_timeline_graph
from core.knowledge.embedding_service import embed_text, find_similar_papers

from database.config import SUPABASE_URL, SUPABASE_SERVICE_KEY
from auth.dependencies import CurrentUser
from schemas import SemanticSearchRequest

logger = structlog.get_logger(__name__)
router = APIRouter()
supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


@router.get('/graph/paper/{summary_id}')
async def paper_knowledge_graph(summary_id: str, current_user: CurrentUser):
    """Knowledge graph nodes + edges centred on a paper."""
    user_id = current_user['user_id']
    try:
        graph = await asyncio.to_thread(
            lambda: get_knowledge_graph(
                user_id=user_id,
                supabase_client=supabase,
                anchor_summary_id=summary_id,
            )
        )
        return graph
    except Exception as e:
        logger.exception('knowledge_graph_error', summary_id=summary_id, error=str(e))
        return JSONResponse(status_code=500, content={'error': str(e)})


@router.get('/graph/recommendations/{summary_id}')
async def paper_recommendations(
    summary_id: str, current_user: CurrentUser, k: int = Query(default=5, le=20)
):
    """Top-K similar papers for a given summary."""
    try:
        recs = await asyncio.to_thread(
            lambda: get_paper_recommendations(summary_id, supabase, top_k=k)
        )
        return {'recommendations': recs}
    except Exception as e:
        logger.exception('recommendations_error', summary_id=summary_id, error=str(e))
        return JSONResponse(status_code=500, content={'error': str(e)})


@router.post('/graph/search')
async def semantic_search(data: SemanticSearchRequest, current_user: CurrentUser):
    """Semantic vector search across the user's paper library."""
    user_id = current_user['user_id']
    try:
        embedding = await asyncio.to_thread(embed_text, data.query)
        results = await asyncio.to_thread(
            lambda: find_similar_papers(
                embedding=embedding,
                user_id=user_id,
                supabase_client=supabase,
                top_k=data.top_k,
            )
        )
        return {'results': results, 'query': data.query}
    except Exception as e:
        logger.exception('semantic_search_error', query=data.query, error=str(e))
        return JSONResponse(status_code=500, content={'error': str(e)})


@router.get('/graph/timeline')
async def research_timeline(current_user: CurrentUser):
    """All user papers with publication dates and lineage edges."""
    user_id = current_user['user_id']
    try:
        data = await asyncio.to_thread(build_timeline_graph, user_id, supabase)
        return data
    except Exception as e:
        logger.exception('timeline_error', error=str(e))
        return JSONResponse(status_code=500, content={'error': str(e)})


@router.get('/graph/ancestry/{summary_id}')
async def paper_ancestry(
    summary_id: str, current_user: CurrentUser, depth: int = Query(default=3, le=5)
):
    """Ancestry/descendant tree for a paper."""
    try:
        tree = await asyncio.to_thread(get_ancestry_tree, summary_id, supabase, depth)
        return tree
    except Exception as e:
        logger.exception('ancestry_error', summary_id=summary_id, error=str(e))
        return JSONResponse(status_code=500, content={'error': str(e)})


@router.get('/graph/citation-network')
async def citation_network(current_user: CurrentUser):
    """Directed citation graph for the user's entire library."""
    user_id = current_user['user_id']
    try:
        from core.knowledge.graph_service import get_citation_network
        graph = await asyncio.to_thread(get_citation_network, user_id, supabase)
        return graph
    except Exception as e:
        logger.exception('citation_network_error', error=str(e))
        return JSONResponse(status_code=500, content={'error': str(e)})


@router.get('/graph/author-graph')
async def author_graph(current_user: CurrentUser):
    """Co-authorship graph for the user's library."""
    user_id = current_user['user_id']
    try:
        from core.knowledge.graph_service import get_author_graph
        graph = await asyncio.to_thread(get_author_graph, user_id, supabase)
        return graph
    except Exception as e:
        logger.exception('author_graph_error', error=str(e))
        return JSONResponse(status_code=500, content={'error': str(e)})


@router.get('/graph/discover')
async def discover_papers(current_user: CurrentUser, q: str = Query(..., min_length=2), limit: int = Query(default=10, le=20)):
    """Search Semantic Scholar for external papers."""
    try:
        from core.knowledge.semantic_scholar_service import search_papers, normalize_s2_paper
        raw = await asyncio.to_thread(search_papers, q, limit)
        return {'results': [normalize_s2_paper(p) for p in raw], 'query': q}
    except Exception as e:
        logger.exception('discover_error', query=q, error=str(e))
        return JSONResponse(status_code=500, content={'error': str(e)})


@router.get('/graph/semantic-scholar/{s2_id}')
async def semantic_scholar_paper(s2_id: str, current_user: CurrentUser):
    """Fetch details for a single Semantic Scholar paper."""
    try:
        from core.knowledge.semantic_scholar_service import get_paper_details, normalize_s2_paper
        paper = await asyncio.to_thread(get_paper_details, s2_id)
        if not paper:
            return JSONResponse(status_code=404, content={'error': 'Paper not found'})
        return normalize_s2_paper(paper)
    except Exception as e:
        logger.exception('s2_paper_error', s2_id=s2_id, error=str(e))
        return JSONResponse(status_code=500, content={'error': str(e)})
