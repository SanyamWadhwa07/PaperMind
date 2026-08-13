"""HypothesisGenerator — suggests novel research directions from a paper cluster."""

import json
import structlog
from core.llm.json_parse import parse_json_object
from typing import Any, Dict, List, Optional

from core.intelligence.base_intelligence_agent import BackendAwareReActAgent

logger = structlog.get_logger(__name__)


class HypothesisGenerator(BackendAwareReActAgent):

    def get_system_prompt(self) -> str:
        return (
            "You are a senior AI researcher. Given a set of papers and their research gaps, "
            "generate 3-5 concrete, novel research hypotheses that no existing paper has addressed. "
            "Each hypothesis must be falsifiable, specific, and grounded in the provided papers."
        )

    def format_query(self, input_data: Dict) -> str:
        paper_ids = input_data.get("paper_ids", [])
        focus = input_data.get("research_focus", "")
        return (
            f"Research focus: {focus or 'general AI/ML'}\n"
            f"Paper IDs to analyze: {paper_ids}\n\n"
            "Step 1: Use get_paper_summary and get_paper_gaps for each paper.\n"
            "Step 2: Use search_corpus to find related work.\n"
            "Step 3: Identify gaps across all papers.\n"
            "Step 4: Generate 3-5 novel, actionable research hypotheses.\n"
            "Return as JSON: {\"hypotheses\": [{\"statement\": ..., \"rationale\": ..., "
            "\"supporting_papers\": [...], \"novelty_score\": 0.0-1.0}]}"
        )

    def parse_result(self, final_answer: str, input_data: Dict) -> Dict:
        parsed = parse_json_object(final_answer)
        if parsed:
            return parsed
        # Fallback: wrap raw text as a single hypothesis
        return {
            "hypotheses": [
                {
                    "statement": final_answer[:500],
                    "rationale": "Generated from corpus analysis",
                    "supporting_papers": input_data.get("paper_ids", []),
                    "novelty_score": 0.5,
                }
            ]
        }


async def generate_hypotheses(
    paper_ids: List[str],
    user_id: str,
    supabase_client: Any,
    research_focus: Optional[str] = None,
    llm_config: Optional[Dict] = None,
) -> Dict:
    from core.intelligence.tools import make_corpus_tools

    agent = HypothesisGenerator(llm_config=llm_config)
    agent.set_tools(make_corpus_tools(user_id, supabase_client))

    result = await agent.arun({
        "paper_ids": paper_ids,
        "user_id": user_id,
        "research_focus": research_focus,
    })

    # Persist to intelligence_sessions
    try:
        supabase_client.table("intelligence_sessions").insert({
            "user_id": user_id,
            "session_type": "hypothesis",
            "input_context": {"paper_ids": paper_ids, "research_focus": research_focus},
            "result_data": result,
        }).execute()
    except Exception as e:
        logger.warning("hypothesis_persist_failed", error=str(e))

    return result
