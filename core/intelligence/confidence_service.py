"""Confidence aggregation across all agent outputs."""

from typing import Dict, Any, Optional


def aggregate_confidence(summary_data: Dict[str, Any]) -> Dict[str, Optional[float]]:
    """
    Walk summary_data and pull per-agent confidence_scores into a flat map.
    Also computes an overall_confidence as the mean of available agent scores.
    """
    confidence_map: Dict[str, float] = {}

    agent_keys = [
        "entities", "results", "figures", "reasoning",
        "research_gaps", "reproducibility", "ablation_studies",
    ]

    scores = []
    for key in agent_keys:
        agent_data = summary_data.get(key, {})
        if isinstance(agent_data, dict):
            agent_scores = agent_data.get("confidence_scores", {})
            if isinstance(agent_scores, dict):
                for item_id, score in agent_scores.items():
                    qualified = f"{key}.{item_id}"
                    confidence_map[qualified] = float(score)
                    scores.append(float(score))
            # Top-level confidence for the agent
            if "confidence" in agent_data:
                confidence_map[key] = float(agent_data["confidence"])
                scores.append(float(agent_data["confidence"]))

    # None, not a fabricated 0.5, when nothing was scored — indistinguishable from a
    # genuinely computed midpoint otherwise.
    confidence_map["overall_confidence"] = round(sum(scores) / len(scores), 4) if scores else None
    return confidence_map
