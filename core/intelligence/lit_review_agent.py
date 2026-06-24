"""LiteratureReviewDrafter — writes a structured lit review from the corpus."""

import json
import logging
from typing import Any, Dict, List, Optional

from core.intelligence.base_intelligence_agent import BackendAwareReActAgent

logger = logging.getLogger(__name__)

LIT_REVIEW_SYSTEM = """You are an expert academic writer. Write a structured literature review
in the style of a survey paper. Be precise, cite specific papers by title, and organize
thematically not chronologically. Return ONLY valid JSON."""

LIT_REVIEW_QUERY = """Topic: {topic}
Available papers (titles + summaries will be retrieved via tools):
{paper_ids_hint}

Steps:
1. Use list_corpus_papers to discover all relevant papers.
2. For each relevant paper use get_paper_summary to read its contribution.
3. Use search_semantic_scholar to find 2-3 additional external references.
4. Group papers into 2-4 thematic sections.
5. Write the literature review.

Return JSON:
{{
  "title": "Literature Review: {topic}",
  "sections": [
    {{"heading": "...", "content": "...", "papers_cited": ["<title>", ...]}}
  ],
  "references": [{{"title": "...", "authors": "...", "year": ...}}]
}}"""


class LiteratureReviewDrafter(BackendAwareReActAgent):

    def get_system_prompt(self) -> str:
        return LIT_REVIEW_SYSTEM

    def format_query(self, input_data: Dict) -> str:
        paper_ids = input_data.get("paper_ids") or []
        return LIT_REVIEW_QUERY.format(
            topic=input_data.get("topic", ""),
            paper_ids_hint=", ".join(paper_ids[:10]) if paper_ids else "discover from corpus",
        )

    def parse_result(self, final_answer: str, input_data: Dict) -> Dict:
        try:
            m = __import__("re").search(r"\{.*\}", final_answer, __import__("re").DOTALL)
            if m:
                return json.loads(m.group())
        except Exception:
            pass
        return {
            "title": f"Literature Review: {input_data.get('topic', '')}",
            "sections": [{"heading": "Overview", "content": final_answer[:2000], "papers_cited": []}],
            "references": [],
        }


async def draft_literature_review(
    topic: str,
    user_id: str,
    supabase_client: Any,
    paper_ids: Optional[List[str]] = None,
    llm_config: Optional[Dict] = None,
) -> Dict:
    from core.intelligence.tools import make_corpus_tools

    agent = LiteratureReviewDrafter(llm_config=llm_config)
    agent.set_tools(make_corpus_tools(user_id, supabase_client))

    result = await agent.arun({"topic": topic, "user_id": user_id, "paper_ids": paper_ids})

    try:
        supabase_client.table("intelligence_sessions").insert({
            "user_id": user_id,
            "session_type": "lit_review",
            "input_context": {"topic": topic, "paper_ids": paper_ids},
            "result_data": result,
        }).execute()
    except Exception as e:
        logger.warning("lit_review_persist_failed", error=str(e))

    return result
