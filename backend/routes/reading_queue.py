"""Reading queue routes — prioritize and manage a personal paper reading list."""

import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from supabase import create_client

from auth.dependencies import CurrentUser
from database.config import SUPABASE_URL, SUPABASE_SERVICE_KEY

logger = logging.getLogger(__name__)
router = APIRouter()
supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


class AddToQueueRequest(BaseModel):
    summary_id: str
    priority_score: Optional[float] = 0.5


class UpdateQueueStatusRequest(BaseModel):
    status: str  # pending | reading | done


@router.get("/queue")
async def get_reading_queue(
    current_user: CurrentUser,
    status: Optional[str] = Query(default=None),
    limit: int = Query(default=20, le=50),
):
    """Return the user's reading queue, ordered by priority."""
    user_id = current_user["user_id"]
    try:
        query = (
            supabase.table("reading_queue")
            .select("id, summary_id, priority_score, status, added_at, "
                    "summaries(paper_title, paper_authors, primary_category, quality_score)")
            .eq("user_id", user_id)
            .order("priority_score", desc=True)
            .limit(limit)
        )
        if status:
            query = query.eq("status", status)
        resp = query.execute()
        return resp.data or []
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/queue", status_code=201)
async def add_to_queue(body: AddToQueueRequest, current_user: CurrentUser):
    """Add a paper to the reading queue."""
    user_id = current_user["user_id"]
    try:
        resp = (
            supabase.table("reading_queue")
            .upsert({
                "user_id": user_id,
                "summary_id": body.summary_id,
                "priority_score": body.priority_score,
                "status": "pending",
            }, on_conflict="user_id,summary_id")
            .execute()
        )
        return resp.data[0] if resp.data else {}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/queue/{item_id}")
async def update_queue_item(item_id: str, body: UpdateQueueStatusRequest, current_user: CurrentUser):
    """Update the status of a reading queue item (pending → reading → done)."""
    user_id = current_user["user_id"]
    if body.status not in ("pending", "reading", "done"):
        raise HTTPException(status_code=400, detail="status must be pending, reading, or done")
    try:
        resp = (
            supabase.table("reading_queue")
            .update({"status": body.status})
            .eq("id", item_id)
            .eq("user_id", user_id)
            .execute()
        )
        return resp.data[0] if resp.data else {}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/queue/{item_id}", status_code=204)
async def remove_from_queue(item_id: str, current_user: CurrentUser):
    """Remove a paper from the reading queue."""
    user_id = current_user["user_id"]
    try:
        supabase.table("reading_queue").delete().eq("id", item_id).eq("user_id", user_id).execute()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/queue/auto-populate", status_code=201)
async def auto_populate_queue(current_user: CurrentUser, top_n: int = Query(default=10, le=20)):
    """
    Embed the user's research_focus and find the most relevant unread papers,
    then add them to the queue with computed priority scores.
    """
    user_id = current_user["user_id"]
    try:
        # Fetch user research_focus
        user_resp = (
            supabase.table("users")
            .select("research_focus")
            .eq("id", user_id)
            .single()
            .execute()
        )
        focus = user_resp.data.get("research_focus") or [] if user_resp.data else []
        if not focus:
            raise HTTPException(
                status_code=400,
                detail="Set research_focus in your profile first (PUT /api/profile)",
            )

        focus_text = " ".join(focus)
        from core.knowledge.embedding_service import embed_text, find_similar_papers
        embedding = await asyncio.to_thread(embed_text, focus_text)
        similar = await asyncio.to_thread(find_similar_papers, embedding, user_id, supabase, top_n * 2)

        # Get already-queued summary_ids
        queued_resp = (
            supabase.table("reading_queue")
            .select("summary_id")
            .eq("user_id", user_id)
            .execute()
        )
        already_queued = {r["summary_id"] for r in (queued_resp.data or [])}

        rows = []
        for paper in similar:
            sid = paper.get("id")
            if sid and sid not in already_queued:
                rows.append({
                    "user_id": user_id,
                    "summary_id": sid,
                    "priority_score": round(float(paper.get("similarity", 0.5)), 4),
                    "status": "pending",
                })
            if len(rows) >= top_n:
                break

        if rows:
            supabase.table("reading_queue").upsert(rows, on_conflict="user_id,summary_id").execute()

        return {"added": len(rows), "message": f"Added {len(rows)} papers to reading queue"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
