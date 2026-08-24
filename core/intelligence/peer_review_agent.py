"""PeerReviewSimulator — critiques a paper as a reviewer would."""

import json
import structlog
from core.llm.json_parse import parse_json_object
import re
from typing import Any, Dict, Optional

logger = structlog.get_logger(__name__)

PEER_REVIEW_SYSTEM = """You are an expert peer reviewer for top AI/ML conferences (NeurIPS, ICML, ICLR).
Evaluate the paper rigorously but fairly, the way an actual conference reviewer would.

Calibration: score 6 is roughly a borderline accept at a top venue, and most papers that
made it to publication score 6-8. A score below 4 must be justified by a specific defect
you can point to in the text provided below — never by the mere absence of detail, since
you are shown an excerpt, not the full paper.

You must list genuine strengths before any concerns — a paper that reached publication has
some. If the context given to you is too sparse to judge a dimension (e.g. no methodology
text was provided), say so explicitly in `summary` rather than inferring a weakness from
the gap. Never list a concern you cannot ground in the text actually given to you below.

Return ONLY a JSON object with this exact schema:
{
  "strengths": ["<strength 1>", "..."],
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

Abstract / key contribution:
{abstract}

Methodology and experimental setup:
{methodology}

Reported results:
{results}

Reproducibility score (automated rubric, out of 10): {repro_score}

Write a rigorous, fair peer review of this paper based on the material above."""

#: Below this, the assembled context is too thin to review honestly — a model asked to
#: "review rigorously" on a title alone will invent weaknesses to fill the request rather
#: than say it doesn't have enough to go on. Roughly two short paragraphs.
_MIN_CONTEXT_CHARS = 200


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
        raise PeerReviewUnavailableError(
            "could not load the paper to review"
        ) from e

    if not paper:
        raise PeerReviewUnavailableError("could not load the paper to review")

    sd = paper.get("summary_data") or {}
    repro_score = (sd.get("reproducibility") or {}).get("score", "N/A")

    # Build the reviewer's context from the keys the pipeline actually persists
    # (see backend/routes/process_paper.py's _build_summary_record). This agent used to
    # read `summaries.simple`, `sections.methodology` and `results.table_results` — none
    # of which exist in a saved record — so every review before this fix was written from
    # a title and an author list alone, with `results` always rendering as `[]`, which
    # reads to the model as "this paper reports no results."
    summaries = sd.get("summaries") or {}
    abstract = (
        sd.get("abstract_original")
        or summaries.get("main", "")
        or sd.get("methods_detail", "")
    )[:8000]

    methodology_bits = [
        sd.get("methods_detail", ""),
        (sd.get("methodology") or {}).get("approach", ""),
        sd.get("experimental_setup", ""),
    ]
    methodology = "\n".join(b for b in methodology_bits if b)[:6000]

    results = sd.get("results") or {}
    results_payload = {
        "summary": results.get("summary", ""),
        "metrics": (results.get("metrics") or [])[:20],
        "comparison": (results.get("comparison") or [])[:10],
    }
    results_text = json.dumps(results_payload)[:4000]

    # A few more persisted-but-otherwise-unused fields that materially help a reviewer
    # judge novelty and significance without inventing anything.
    extra_bits = []
    if sd.get("contributions"):
        extra_bits.append("Stated contributions: " + "; ".join(sd["contributions"][:6]))
    if sd.get("key_findings"):
        extra_bits.append("Key findings: " + "; ".join(str(f) for f in sd["key_findings"][:6]))
    if sd.get("limitations"):
        extra_bits.append("Author-stated limitations: " + "; ".join(str(l) for l in sd["limitations"][:6]))
    if extra_bits:
        methodology = (methodology + "\n\n" + "\n".join(extra_bits))[:7000]

    context_length = len(abstract) + len(methodology) + len(results_text)
    if context_length < _MIN_CONTEXT_CHARS:
        raise PeerReviewUnavailableError(
            "this paper has too little extracted content to review honestly "
            f"({context_length} chars of context)"
        )

    prompt = PEER_REVIEW_PROMPT.format(
        title=paper.get("paper_title", "Unknown"),
        authors=", ".join((paper.get("paper_authors") or [])[:5]),
        abstract=abstract or "(not extracted)",
        methodology=methodology or "(not extracted)",
        results=results_text,
        repro_score=repro_score,
    )

    llm = get_llm(llm_config)
    # Scoring is a low-variance task: the same paper should not flip between accept and
    # reject across runs. The default (inherited from LocalLLM) is 0.7, tuned for prose
    # generation, not judgment.
    raw = await llm.generate(prompt, system_prompt=PEER_REVIEW_SYSTEM,
                              max_tokens=2048, temperature=0.15)

    # Raises PeerReviewUnavailableError rather than persisting a fabricated review.
    result = _parse_review(raw)
    _reconcile_recommendation(result)

    # llm.backend reflects LocalLLM's legacy init path, not the provider that actually
    # answered — generate() routes through the Gemini -> Groq -> Ollama provider chain
    # first (core/llm/llm_interface.py), so the true backend comes from there.
    try:
        from core.llm.providers import get_provider_info
        llm_backend = get_provider_info()["provider"]
    except Exception:
        llm_backend = llm.backend.value if llm.backend else "unknown"

    # Persist
    try:
        supabase_client.table("paper_intelligence").upsert({
            "summary_id": summary_id,
            "user_id": user_id,
            "analysis_type": "peer_review",
            "analysis_data": result,
            "llm_backend": llm_backend,
        }, on_conflict="summary_id,analysis_type").execute()
    except Exception as e:
        logger.warning("peer_review_persist_failed", error=str(e))

    return result


class PeerReviewUnavailableError(RuntimeError):
    """The model did not return a parseable review, or there wasn't enough to review."""


#: The score card is built entirely from these. A review missing any of them
#: renders as a card of blank bars, which is worse than no card at all.
REQUIRED_SCORES = ("novelty", "soundness", "clarity", "significance")

#: recommendation is presumed roughly monotonic in the mean score. A model saying
#: "reject" over an 8/8/8/8 card (or "accept" over a 2/2/2/2 one) is a contradiction in
#: its own output, not a nuanced judgment — reconcile it rather than persist it verbatim.
_RECOMMENDATION_BANDS = (
    (7.0, "accept"),
    (5.5, "minor_revision"),
    (3.5, "major_revision"),
)


def _reconcile_recommendation(parsed: Dict) -> None:
    mean_score = sum(parsed[k] for k in REQUIRED_SCORES) / len(REQUIRED_SCORES)
    implied = "reject"
    for threshold, label in _RECOMMENDATION_BANDS:
        if mean_score >= threshold:
            implied = label
            break

    current = parsed.get("recommendation")
    order = ["reject", "major_revision", "minor_revision", "accept"]
    is_contradiction = (
        current not in order
        or abs(order.index(current) - order.index(implied)) >= 2
    )
    if is_contradiction:
        logger.warning("peer_review_inconsistent", mean_score=mean_score,
                       stated_recommendation=current, implied_recommendation=implied)
        parsed["recommendation"] = implied


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
    parsed.setdefault("strengths", [])
    parsed.setdefault("major_concerns", [])
    parsed.setdefault("minor_concerns", [])
    return parsed
