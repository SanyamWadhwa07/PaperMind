"""PeerReviewSimulator — critiques a paper as a reviewer would."""

import json
import structlog
from core.llm.json_parse import parse_json_object
import re
from typing import Any, Dict, Optional

logger = structlog.get_logger(__name__)

PEER_REVIEW_SYSTEM = """You are an expert peer reviewer for top AI/ML conferences (NeurIPS, ICML, ICLR).
Evaluate the paper rigorously and objectively. Score each dimension 1-10.
Return ONLY a JSON object with this exact schema:
{
  "novelty": <int 1-10>,
  "soundness": <int 1-10>,
  "clarity": <int 1-10>,
  "significance": <int 1-10>,
  "recommendation": "<accept|minor_revision|major_revision|reject>",
  "major_concerns": ["<concern 1>", "..."],
  "minor_concerns": ["<concern 1>", "..."],
  "summary": "<2-3 sentence review summary>"
}"""

PEER_REVIEW_PROMPT = """Paper: {title}
Authors: {authors}
Abstract / Key contribution: {abstract}
Methodology: {methodology}
Key results: {results}
Reproducibility score: {repro_score}/10

Write a rigorous peer review of this paper."""


async def simulate_peer_review(
    summary_id: str,
    user_id: str,
    supabase_client: Any,
    llm_config: Optional[Dict] = None,
) -> Dict:
    from core.llm.llm_interface import get_llm

    # Fetch paper data
    try:
        resp = (
            supabase_client.table("summaries")
            .select("paper_title, paper_authors, summary_data")
            .eq("id", summary_id)
            .eq("user_id", user_id)
            .single()
            .execute()
        )
        paper = resp.data or {}
    except Exception as e:
        logger.error("peer_review_fetch_error", exc_info=e)
        paper = {}

    sd = paper.get("summary_data", {})
    repro_score = sd.get("reproducibility", {}).get("score", "N/A")

    # Build concise context (cap to avoid token overrun)
    abstract = sd.get("summaries", {}).get("simple", "")[:800]
    methodology = str(sd.get("sections", {}).get("methodology", ""))[:600]
    results_text = json.dumps(sd.get("results", {}).get("table_results", [])[:3])[:400]

    prompt = PEER_REVIEW_PROMPT.format(
        title=paper.get("paper_title", "Unknown"),
        authors=", ".join(paper.get("paper_authors", [])[:5]),
        abstract=abstract,
        methodology=methodology,
        results=results_text,
        repro_score=repro_score,
    )

    llm = get_llm(llm_config)
    raw = await llm.generate(prompt, system_prompt=PEER_REVIEW_SYSTEM, max_tokens=2048)

    # Raises PeerReviewUnavailableError rather than persisting a fabricated review.
    result = _parse_review(raw)

    # Persist
    try:
        supabase_client.table("paper_intelligence").upsert({
            "summary_id": summary_id,
            "user_id": user_id,
            "analysis_type": "peer_review",
            "analysis_data": result,
            "llm_backend": llm.backend.value if llm.backend else "unknown",
        }, on_conflict="summary_id,analysis_type").execute()
    except Exception as e:
        logger.warning("peer_review_persist_failed", error=str(e))

    return result


class PeerReviewUnavailableError(RuntimeError):
    """The model did not return a parseable review."""


#: The score card is built entirely from these. A review missing any of them
#: renders as a card of blank bars, which is worse than no card at all.
REQUIRED_SCORES = ("novelty", "soundness", "clarity", "significance")


def _parse_review(raw: str) -> Dict:
    """Parse the model's JSON review, or raise.

    This used to return straight 5s on every axis with a
    "major_revision" recommendation. That fabricated review was then written to
    paper_intelligence and served from cache forever, so a single parse failure
    permanently became the paper's review — with the only hint buried in
    major_concerns where a score card would never show it.

    The scores are checked rather than merely the parse, because the parser will
    now recover a partial object from a reply that was cut off at the token
    ceiling. Recovering half a review is right for research gaps, where every
    item found is worth keeping; it is wrong here, where the missing half is
    the score card itself.
    """
    parsed = parse_json_object(raw)
    if not parsed:
        raise PeerReviewUnavailableError(
            "model returned no parseable JSON object; cannot produce a review"
        )

    missing = [k for k in REQUIRED_SCORES if not isinstance(parsed.get(k), (int, float))]
    if missing:
        raise PeerReviewUnavailableError(
            f"review is missing required scores: {', '.join(missing)}"
        )
    return parsed
