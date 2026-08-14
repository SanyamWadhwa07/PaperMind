"""Corpus-level analysis routes — topic clusters, contradiction map, recompute triggers."""

import asyncio
import structlog
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from db import supabase as _shared_supabase

from api import response_cache
from auth.dependencies import CurrentUser

logger = structlog.get_logger(__name__)
router = APIRouter()
supabase = _shared_supabase


@router.get("/corpus/topic-clusters")
async def get_topic_clusters(current_user: CurrentUser):
    """Return pre-computed topic cluster landscape for the user's library."""
    user_id = current_user["user_id"]
    try:
        from core.knowledge.topic_clustering import get_topic_landscape
        return await response_cache.cached_view(
            "topic-clusters",
            user_id,
            lambda: asyncio.to_thread(get_topic_landscape, user_id, supabase),
        )
    except Exception as e:
        logger.error("topic_clusters_error", error=str(e))
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.post("/corpus/recompute-clusters")
async def recompute_clusters(current_user: CurrentUser):
    """Cluster the user's library by topic and store the assignments.

    Runs inline rather than as a background task. Clustering a personal library
    is a few seconds of CPU on already-computed embeddings, and firing it into
    the background meant the only honest thing the response could say was "check
    back in a minute" — so a failure surfaced as a permanently empty graph, and
    a success looked identical until the user reloaded and guessed. Waiting for
    the answer lets the button report what actually happened.
    """
    user_id = current_user["user_id"]
    try:
        from core.knowledge.topic_clustering import compute_topic_clusters
        result = await asyncio.to_thread(compute_topic_clusters, user_id, supabase)
    except Exception as e:
        logger.exception("topic_clustering_failed", user_id=user_id, error=str(e))
        raise HTTPException(status_code=500, detail="Topic clustering failed.")

    if result.get("error"):
        # A library too small to cluster is the user's situation, not a fault.
        raise HTTPException(status_code=400, detail=result["error"])

    # The cluster assignments this view is built from have just been rewritten.
    response_cache.invalidate_user(user_id)

    logger.info("topic_clustering_complete", user_id=user_id, result=result)
    return result


@router.post("/corpus/relate-papers", status_code=202)
async def relate_papers_route(current_user: CurrentUser):
    """Run the RelationAgent across the user's library (background).

    Writes typed, explained links into paper_lineage, which the citation /
    knowledge graph endpoints already render. Poll /corpus/citation-network after.
    """
    user_id = current_user["user_id"]

    async def _run():
        try:
            from core.graph.relation_agent import relate_library
            result = await relate_library(user_id, supabase)
            # New lineage edges — the citation network and contradiction map are
            # both built from them, so drop the cached versions now that the
            # work has actually finished.
            response_cache.invalidate_user(user_id)
            logger.info("relate_papers_complete", user_id=user_id, result=result)
        except Exception as e:
            logger.error("relate_papers_failed", user_id=user_id, error=str(e))

    asyncio.create_task(_run())
    return {"message": "Relation mapping started. Check /corpus/citation-network shortly."}


@router.get("/corpus/citation-network")
async def corpus_citation_network(current_user: CurrentUser):
    """Directed citation graph for the entire corpus."""
    user_id = current_user["user_id"]
    try:
        from core.knowledge.graph_service import get_citation_network
        return await response_cache.cached_view(
            "citation-network",
            user_id,
            lambda: asyncio.to_thread(get_citation_network, user_id, supabase),
        )
    except Exception as e:
        logger.error("citation_network_error", error=str(e))
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.get("/corpus/author-graph")
async def corpus_author_graph(current_user: CurrentUser):
    """Co-authorship graph for the entire corpus."""
    user_id = current_user["user_id"]
    try:
        from core.knowledge.graph_service import get_author_graph
        return await response_cache.cached_view(
            "author-graph",
            user_id,
            lambda: asyncio.to_thread(get_author_graph, user_id, supabase),
        )
    except Exception as e:
        logger.error("author_graph_error", error=str(e))
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.get("/corpus/contradiction-map")
async def corpus_contradiction_map(current_user: CurrentUser):
    """Papers connected by 'contradicts' lineage edges."""
    user_id = current_user["user_id"]
    try:
        return await response_cache.cached_view(
            "contradiction-map",
            user_id,
            lambda: asyncio.to_thread(_build_contradiction_map, user_id),
        )
    except Exception as e:
        logger.error("contradiction_map_error", error=str(e))
        return JSONResponse(status_code=500, content={"error": str(e)})


def _build_contradiction_map(user_id: str) -> dict:
    """Blocking Supabase work behind the contradiction map.

    Split out of the route so it can run in a worker thread — inline, these
    three synchronous Supabase calls blocked the event loop for the whole
    request, stalling every other in-flight one.
    """
    papers_resp = (
        supabase.table("summaries")
        .select("id, paper_title")
        .eq("user_id", user_id)
        .execute()
    )
    papers = {p["id"]: p["paper_title"] for p in (papers_resp.data or [])}
    paper_ids = list(papers.keys())

    if not paper_ids:
        return {"nodes": [], "edges": []}

    lineage_resp = (
        supabase.table("paper_lineage")
        .select("ancestor_id, descendant_id, link_confidence")
        .in_("ancestor_id", paper_ids)
        .eq("link_type", "contradicts")
        .execute()
    )

    nodes = []
    edges = []
    seen = set()

    for row in (lineage_resp.data or []):
        src = row["ancestor_id"]
        dst = row["descendant_id"]
        for pid in [src, dst]:
            if pid not in seen and pid in papers:
                seen.add(pid)
                nodes.append({
                    "id": f"paper_{pid}",
                    "label": (papers.get(pid) or "")[:35],
                    "group": "paper",
                    "summary_id": pid,
                    "color": "#ef4444",
                })
        if src in papers and dst in papers:
            edges.append({
                "from": f"paper_{src}",
                "to": f"paper_{dst}",
                "arrows": "to",
                "title": "contradicts",
                "color": "#ef4444",
                "group": "contradiction",
            })

    return {"nodes": nodes, "edges": edges}
