"""Paper annotation routes — highlight and annotate sections."""

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from db import supabase as _shared_supabase

from auth.dependencies import CurrentUser

logger = logging.getLogger(__name__)
router = APIRouter()
supabase = _shared_supabase


class CreateAnnotationRequest(BaseModel):
    section_key: Optional[str] = None
    highlighted_text: Optional[str] = None
    annotation_text: str
    color: Optional[str] = "#fbbf24"


class UpdateAnnotationRequest(BaseModel):
    annotation_text: Optional[str] = None
    color: Optional[str] = None


@router.get("/annotations/{summary_id}")
async def get_annotations(summary_id: str, current_user: CurrentUser):
    """Return all annotations for a paper."""
    user_id = current_user["user_id"]
    try:
        resp = (
            supabase.table("paper_annotations")
            .select("*")
            .eq("summary_id", summary_id)
            .eq("user_id", user_id)
            .order("created_at")
            .execute()
        )
        return resp.data or []
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/annotations/{summary_id}", status_code=201)
async def create_annotation(summary_id: str, body: CreateAnnotationRequest, current_user: CurrentUser):
    """Create a new annotation on a paper section."""
    user_id = current_user["user_id"]
    try:
        resp = (
            supabase.table("paper_annotations")
            .insert({
                "summary_id": summary_id,
                "user_id": user_id,
                "section_key": body.section_key,
                "highlighted_text": body.highlighted_text,
                "annotation_text": body.annotation_text,
                "color": body.color or "#fbbf24",
            })
            .execute()
        )
        return resp.data[0] if resp.data else {}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/annotations/{annotation_id}")
async def update_annotation(annotation_id: str, body: UpdateAnnotationRequest, current_user: CurrentUser):
    """Update annotation text or color."""
    user_id = current_user["user_id"]
    updates = {}
    if body.annotation_text is not None:
        updates["annotation_text"] = body.annotation_text
    if body.color is not None:
        updates["color"] = body.color
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    updates["updated_at"] = datetime.now(timezone.utc).isoformat()
    try:
        resp = (
            supabase.table("paper_annotations")
            .update(updates)
            .eq("id", annotation_id)
            .eq("user_id", user_id)
            .execute()
        )
        return resp.data[0] if resp.data else {}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/annotations/{annotation_id}", status_code=204)
async def delete_annotation(annotation_id: str, current_user: CurrentUser):
    """Delete an annotation."""
    user_id = current_user["user_id"]
    try:
        supabase.table("paper_annotations").delete() \
            .eq("id", annotation_id).eq("user_id", user_id).execute()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
