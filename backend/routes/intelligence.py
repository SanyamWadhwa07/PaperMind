"""Intelligence layer API routes — on-demand reasoning agents."""

import asyncio
import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from supabase import create_client

from auth.dependencies import CurrentUser
from database.config import SUPABASE_URL, SUPABASE_SERVICE_KEY

logger = logging.getLogger(__name__)

router = APIRouter()
supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


# ── Request schemas ────────────────────────────────────────────────────────────

class HypothesisRequest(BaseModel):
    paper_ids: List[str]
    research_focus: Optional[str] = None


class LitReviewRequest(BaseModel):
    topic: str
    paper_ids: Optional[List[str]] = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_cached(summary_id: str, analysis_type: str):
    try:
        resp = (
            supabase.table("paper_intelligence")
            .select("analysis_data, confidence_score, created_at, llm_backend")
            .eq("summary_id", summary_id)
            .eq("analysis_type", analysis_type)
            .execute()
        )
        return resp.data[0] if resp.data else None
    except Exception:
        return None


def _check_paper_ownership(summary_id: str, user_id: str) -> bool:
    try:
        resp = (
            supabase.table("summaries")
            .select("id")
            .eq("id", summary_id)
            .eq("user_id", user_id)
            .execute()
        )
        return bool(resp.data)
    except Exception:
        return False


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/intelligence/paper/{summary_id}")
async def get_paper_intelligence(summary_id: str, current_user: CurrentUser):
    """Return all cached intelligence analysis for a paper."""
    user_id = current_user["user_id"]
    if not _check_paper_ownership(summary_id, user_id):
        raise HTTPException(status_code=404, detail="Paper not found")

    try:
        resp = (
            supabase.table("paper_intelligence")
            .select("analysis_type, analysis_data, confidence_score, created_at, llm_backend")
            .eq("summary_id", summary_id)
            .execute()
        )
        result = {}
        for row in (resp.data or []):
            result[row["analysis_type"]] = {
                "data": row["analysis_data"],
                "confidence": row["confidence_score"],
                "cached_at": row["created_at"],
                "llm_backend": row["llm_backend"],
            }
        return result
    except Exception as e:
        logger.error("get_intelligence_error", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to fetch intelligence data")


@router.get("/intelligence/gaps/{summary_id}")
async def get_research_gaps(summary_id: str, current_user: CurrentUser):
    """Return research gap analysis for a paper (from ingest-time cache)."""
    user_id = current_user["user_id"]
    if not _check_paper_ownership(summary_id, user_id):
        raise HTTPException(status_code=404, detail="Paper not found")

    cached = _get_cached(summary_id, "gaps")
    if cached:
        return cached["analysis_data"]

    # Fall back to summary_data JSONB if not separately cached
    try:
        resp = (
            supabase.table("summaries")
            .select("summary_data")
            .eq("id", summary_id)
            .single()
            .execute()
        )
        if resp.data:
            return resp.data["summary_data"].get("research_gaps", {})
    except Exception:
        pass
    return {}


@router.get("/intelligence/reproducibility/{summary_id}")
async def get_reproducibility(summary_id: str, current_user: CurrentUser):
    """Return reproducibility score for a paper."""
    user_id = current_user["user_id"]
    if not _check_paper_ownership(summary_id, user_id):
        raise HTTPException(status_code=404, detail="Paper not found")

    cached = _get_cached(summary_id, "reproducibility")
    if cached:
        return cached["analysis_data"]

    try:
        resp = (
            supabase.table("summaries")
            .select("summary_data")
            .eq("id", summary_id)
            .single()
            .execute()
        )
        if resp.data:
            return resp.data["summary_data"].get("reproducibility", {})
    except Exception:
        pass
    return {}


@router.post("/intelligence/peer-review/{summary_id}", status_code=201)
async def simulate_peer_review(summary_id: str, current_user: CurrentUser):
    """
    Run a peer review simulation for a paper.
    Results are cached to paper_intelligence for future retrieval.
    """
    user_id = current_user["user_id"]
    if not _check_paper_ownership(summary_id, user_id):
        raise HTTPException(status_code=404, detail="Paper not found")

    # Return cached result if available
    cached = _get_cached(summary_id, "peer_review")
    if cached:
        return {"cached": True, **cached["analysis_data"]}

    try:
        from core.intelligence.peer_review_agent import simulate_peer_review as _run
        result = await _run(summary_id=summary_id, user_id=user_id, supabase_client=supabase)
        return result
    except Exception as e:
        logger.error("peer_review_error", error=str(e), summary_id=summary_id)
        raise HTTPException(status_code=500, detail=f"Peer review failed: {e}")


@router.post("/intelligence/hypothesis", status_code=201)
async def generate_hypotheses(body: HypothesisRequest, current_user: CurrentUser):
    """
    Generate novel research hypotheses from a set of papers.
    Requires LangGraph + an LLM backend for best results.
    """
    user_id = current_user["user_id"]
    if not body.paper_ids:
        raise HTTPException(status_code=400, detail="paper_ids required")

    try:
        from core.intelligence.hypothesis_agent import generate_hypotheses as _run
        result = await _run(
            paper_ids=body.paper_ids,
            user_id=user_id,
            supabase_client=supabase,
            research_focus=body.research_focus,
        )
        return result
    except Exception as e:
        logger.error("hypothesis_error", error=str(e))
        raise HTTPException(status_code=500, detail=f"Hypothesis generation failed: {e}")


@router.post("/intelligence/lit-review", status_code=201)
async def draft_literature_review(body: LitReviewRequest, current_user: CurrentUser):
    """Draft a structured literature review for a topic from the user's corpus."""
    user_id = current_user["user_id"]
    if not body.topic:
        raise HTTPException(status_code=400, detail="topic required")

    try:
        from core.intelligence.lit_review_agent import draft_literature_review as _run
        result = await _run(
            topic=body.topic,
            user_id=user_id,
            supabase_client=supabase,
            paper_ids=body.paper_ids,
        )
        return result
    except Exception as e:
        logger.error("lit_review_error", error=str(e))
        raise HTTPException(status_code=500, detail=f"Literature review failed: {e}")


@router.get("/intelligence/sessions")
async def list_intelligence_sessions(current_user: CurrentUser, session_type: Optional[str] = None):
    """List the user's past intelligence sessions (hypotheses, lit reviews, etc.)."""
    user_id = current_user["user_id"]
    try:
        query = (
            supabase.table("intelligence_sessions")
            .select("id, session_type, input_context, created_at")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .limit(20)
        )
        if session_type:
            query = query.eq("session_type", session_type)
        resp = query.execute()
        return resp.data or []
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/intelligence/sessions/{session_id}")
async def get_intelligence_session(session_id: str, current_user: CurrentUser):
    """Fetch the full result of a past intelligence session."""
    user_id = current_user["user_id"]
    try:
        resp = (
            supabase.table("intelligence_sessions")
            .select("*")
            .eq("id", session_id)
            .eq("user_id", user_id)
            .single()
            .execute()
        )
        if not resp.data:
            raise HTTPException(status_code=404, detail="Session not found")
        return resp.data
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
