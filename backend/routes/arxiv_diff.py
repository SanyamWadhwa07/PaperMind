"""ArXiv version diff routes."""

import asyncio
import logging

from fastapi import APIRouter, HTTPException
from supabase import create_client

from auth.dependencies import CurrentUser
from database.config import SUPABASE_URL, SUPABASE_SERVICE_KEY

logger = logging.getLogger(__name__)
router = APIRouter()
supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


@router.get("/arxiv/versions/{arxiv_id}")
async def list_arxiv_versions(arxiv_id: str, current_user: CurrentUser):
    """List all ingested versions of an arXiv paper in the user's library."""
    user_id = current_user["user_id"]
    try:
        from core.knowledge.arxiv_diff_service import get_arxiv_versions
        versions = await asyncio.to_thread(get_arxiv_versions, arxiv_id, user_id, supabase)
        return {"arxiv_id": arxiv_id, "versions": versions}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/arxiv/diff/{id1}/{id2}")
async def diff_arxiv_versions(id1: str, id2: str, current_user: CurrentUser):
    """Compute structured diff between two summary IDs (typically different arXiv versions)."""
    user_id = current_user["user_id"]
    try:
        from core.knowledge.arxiv_diff_service import diff_summaries
        result = await asyncio.to_thread(diff_summaries, id1, id2, user_id, supabase)
        if "error" in result:
            raise HTTPException(status_code=404, detail=result["error"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
