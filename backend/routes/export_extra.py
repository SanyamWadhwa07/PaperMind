"""Extra export routes — slide deck generation."""

import asyncio
import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from supabase import create_client

from auth.dependencies import CurrentUser
from database.config import SUPABASE_URL, SUPABASE_SERVICE_KEY

logger = logging.getLogger(__name__)
router = APIRouter()
supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


@router.post("/export/slides/{summary_id}")
async def export_slides(summary_id: str, current_user: CurrentUser):
    """Generate a 5-slide HTML presentation from a paper's analysis."""
    user_id = current_user["user_id"]

    # Verify ownership
    resp = (
        supabase.table("summaries")
        .select("id")
        .eq("id", summary_id)
        .eq("user_id", user_id)
        .execute()
    )
    if not resp.data:
        raise HTTPException(status_code=404, detail="Paper not found")

    try:
        from core.intelligence.slide_generator import generate_slides
        html = await generate_slides(
            summary_id=summary_id,
            user_id=user_id,
            supabase_client=supabase,
        )
        return HTMLResponse(
            content=html,
            headers={"Content-Disposition": f'attachment; filename="slides_{summary_id[:8]}.html"'},
        )
    except Exception as e:
        logger.error("slide_generation_error", error=str(e), summary_id=summary_id)
        raise HTTPException(status_code=500, detail=f"Slide generation failed: {e}")
