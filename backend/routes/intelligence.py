"""Intelligence layer API routes — on-demand reasoning agents."""

import asyncio
import structlog
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from db import supabase as _shared_supabase

from api.errors import ExternalServiceError
from auth.dependencies import CurrentUser

logger = structlog.get_logger(__name__)

router = APIRouter()
supabase = _shared_supabase


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
    except Exception as e:
        logger.warning("intelligence_cache_read_failed",
                       summary_id=summary_id, analysis_type=analysis_type, error=str(e))
        raise ExternalServiceError("Could not read cached analysis.") from e


def _check_paper_ownership(summary_id: str, user_id: str) -> bool:
    """True if the user owns this paper.

    Raises on infrastructure failure instead of returning False — returning
    False surfaced to the user as 404 "Paper not found" for a paper they own,
    whenever the database was merely unreachable.
    """
    try:
        resp = (
            supabase.table("summaries")
            .select("id")
            .eq("id", summary_id)
            .eq("user_id", user_id)
            .execute()
        )
        return bool(resp.data)
    except Exception as e:
        logger.warning("ownership_check_failed", summary_id=summary_id, error=str(e))
        raise ExternalServiceError("Could not verify paper ownership.") from e


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


@router.get("/intelligence/sota/{summary_id}")
async def get_state_of_the_art(summary_id: str, current_user: CurrentUser):
    """Suggest the papers that currently define the state of the art near this one.

    Read-only and uncached: the answer is a property of the outside world, not
    of the paper, so it changes without anything in this database changing.
    """
    user_id = current_user["user_id"]

    try:
        resp = (
            supabase.table("summaries")
            .select("paper_title, published_date, primary_category, abstract_text, summary_data")
            .eq("id", summary_id)
            .eq("user_id", user_id)
            .execute()
        )
    except Exception as e:
        logger.warning("sota_paper_lookup_failed", summary_id=summary_id, error=str(e))
        raise ExternalServiceError("Could not read this paper.") from e

    if not resp.data:
        raise HTTPException(status_code=404, detail="Paper not found")

    paper = resp.data[0]
    summary_data = paper.get("summary_data") or {}
    entities = summary_data.get("entities") or {}

    published_year = None
    published = paper.get("published_date") or ""
    if len(published) >= 4 and published[:4].isdigit():
        published_year = int(published[:4])

    try:
        from core.knowledge.paper_search import find_state_of_the_art
        result = await asyncio.to_thread(
            find_state_of_the_art,
            paper.get("paper_title") or "",
            entities,
            published_year,
            paper.get("abstract_text") or "",
            paper.get("primary_category"),
        )
    except Exception as e:
        logger.warning("sota_search_failed", summary_id=summary_id, error=str(e))
        raise HTTPException(
            status_code=503,
            detail="Paper search is unavailable right now. Please try again shortly.",
        )

    return result


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
            return resp.data["summary_data"].get("research_gaps", {}) or {}
        return {}
    except Exception as e:
        # Previously swallowed, so a failed lookup rendered as "no research gaps found".
        logger.warning("research_gaps_lookup_failed", summary_id=summary_id, error=str(e))
        raise ExternalServiceError("Could not load research gaps for this paper.") from e


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
            return resp.data["summary_data"].get("reproducibility", {}) or {}
        return {}
    except Exception as e:
        # Previously swallowed, so a failed lookup rendered as "no reproducibility found".
        logger.warning("reproducibility_lookup_failed", summary_id=summary_id, error=str(e))
        raise ExternalServiceError("Could not load reproducibility for this paper.") from e


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
