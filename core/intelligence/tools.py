"""LangGraph tool definitions for intelligence agents.

Tools receive user_id and supabase_client via closure so tool signatures stay
clean for LLM invocation.
"""

import json
import asyncio
import structlog
from typing import List, Optional, Any

import httpx

logger = structlog.get_logger(__name__)

try:
    from langchain_core.tools import tool
    LANGCHAIN_AVAILABLE = True
except ImportError:
    LANGCHAIN_AVAILABLE = False
    # Stub decorator so the module still loads without langchain installed.
    def tool(func):  # type: ignore
        return func


def make_corpus_tools(user_id: str, supabase_client: Any):
    """Return tool callables closed over user_id + supabase_client."""

    @tool
    def search_corpus(query: str, limit: int = 5) -> str:
        """Search the user's paper corpus by semantic similarity. Returns JSON list of {id, title, similarity}."""
        try:
            from core.knowledge.embedding_service import EmbeddingService
            svc = EmbeddingService()
            loop = asyncio.new_event_loop()
            results = loop.run_until_complete(
                svc.find_similar_papers(query, user_id=user_id, top_k=limit)
            )
            loop.close()
            return json.dumps(results)
        except Exception as e:
            logger.error("search_corpus_error", exc_info=e)
            return json.dumps([])

    @tool
    def get_paper_summary(summary_id: str) -> str:
        """Fetch the summary_data JSONB for a given summary_id. Returns JSON."""
        try:
            resp = (
                supabase_client.table("summaries")
                .select("id, paper_title, paper_authors, summary_data, created_at")
                .eq("id", summary_id)
                .eq("user_id", user_id)
                .single()
                .execute()
            )
            if resp.data:
                return json.dumps(resp.data)
            return json.dumps({})
        except Exception as e:
            logger.error("get_paper_summary_error", exc_info=e)
            return json.dumps({})

    @tool
    def get_paper_gaps(summary_id: str) -> str:
        """Fetch the research gap analysis for a paper. Returns JSON."""
        try:
            resp = (
                supabase_client.table("paper_intelligence")
                .select("analysis_data, confidence_score")
                .eq("summary_id", summary_id)
                .eq("analysis_type", "gaps")
                .execute()
            )
            if resp.data:
                return json.dumps(resp.data[0])
            # Fall back to summary_data if intelligence row not yet present
            sum_resp = (
                supabase_client.table("summaries")
                .select("summary_data")
                .eq("id", summary_id)
                .single()
                .execute()
            )
            if sum_resp.data:
                sd = sum_resp.data.get("summary_data", {})
                return json.dumps({"analysis_data": sd.get("research_gaps", {})})
            return json.dumps({})
        except Exception as e:
            logger.error("get_paper_gaps_error", exc_info=e)
            return json.dumps({})

    @tool
    def list_corpus_papers(limit: int = 20) -> str:
        """List the user's papers with title, date, and category. Returns JSON list."""
        try:
            resp = (
                supabase_client.table("summaries")
                .select("id, paper_title, paper_authors, primary_category, published_date, quality_score")
                .eq("user_id", user_id)
                .order("created_at", desc=True)
                .limit(limit)
                .execute()
            )
            return json.dumps(resp.data or [])
        except Exception as e:
            logger.error("list_corpus_papers_error", exc_info=e)
            return json.dumps([])

    @tool
    def search_semantic_scholar(query: str, limit: int = 5) -> str:
        """Search Semantic Scholar for papers related to a query. Returns JSON list."""
        try:
            url = "https://api.semanticscholar.org/graph/v1/paper/search"
            params = {
                "query": query,
                "limit": limit,
                "fields": "title,authors,year,abstract,externalIds,citationCount",
            }
            resp = httpx.get(url, params=params, timeout=10)
            if resp.status_code == 200:
                data = resp.json().get("data", [])
                return json.dumps(data)
            return json.dumps([])
        except Exception as e:
            logger.error("semantic_scholar_error", exc_info=e)
            return json.dumps([])

    return [search_corpus, get_paper_summary, get_paper_gaps, list_corpus_papers, search_semantic_scholar]
