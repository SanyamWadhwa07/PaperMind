"""Extra export routes — slide deck generation."""

import asyncio
import structlog

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from db import supabase as _shared_supabase

from auth.dependencies import CurrentUser

logger = structlog.get_logger(__name__)
router = APIRouter()
supabase = _shared_supabase


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
