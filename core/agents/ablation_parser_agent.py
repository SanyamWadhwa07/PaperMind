"""AblationParserAgent — parses ablation study tables and summarizes component contributions."""

import sys
import re
import json
import structlog
from pathlib import Path
from typing import Dict, Any, Optional, List

sys.path.append(str(Path(__file__).parent.parent.parent))

from core.agents.base_agent import BaseAgent
from core.llm.json_parse import parse_json_object

logger = structlog.get_logger(__name__)

# Patterns that indicate ablation column/row headers
ABLATION_COL_PATTERNS = [
    r"\bw/?o\b", r"\bwithout\b", r"\bw/?\s*-\s*\w", r"\bno\s+\w",
    r"\bremov(?:e|ing|al)\b", r"\bminus\s+\w",
]
ABLATION_ROW_PATTERNS = [
    r"\bfull\s+model\b", r"\bours\b", r"\bbaseline\b", r"\bcomplete\b",
]

ABLATION_SYSTEM = (
    "You are a machine learning researcher parsing an ablation study. "
    "Given raw text from the ablation section, extract each component and its effect "
    "when removed. Return ONLY valid JSON:\n"
    '{"ablation_studies": [{"component": "...", "metric": "...", "delta": <float or null>, '
    '"baseline": <float or null>, "description": "..."}]}'
)


class AblationParserAgent(BaseAgent):
    """Identifies ablation tables and quantifies each component's contribution."""

    def __init__(self, patterns: Optional[Dict] = None, llm_config: Optional[Dict] = None):
        super().__init__(name="AblationParserAgent", patterns=patterns)
        self._llm_config = llm_config or {}

    async def process(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        sections: Dict[str, str] = input_data.get("sections", {})
        # ResultsAgent output may be passed for enrichment
        existing_results: Dict = input_data.get("results", {})

        ablation_text = self._find_ablation_text(sections)

        if not ablation_text:
            return {
                "extractions": [],
                "confidence_scores": {"ablation": 0.0},
                "ablation_studies": [],
                "metadata": {"found": False},
            }

        llm_result = await self._llm_parse(ablation_text)
        studies = llm_result.get("ablation_studies", [])

        # Enrich with numeric deltas from regex if LLM missed them
        studies = self._enrich_deltas(studies, ablation_text)

        return {
            "extractions": [s.get("component", "") for s in studies],
            "confidence_scores": {"ablation": 0.8 if studies else 0.3},
            "ablation_studies": studies[:20],
            "metadata": {
                "found": True,
                "component_count": len(studies),
            },
        }

    def _find_ablation_text(self, sections: Dict[str, str]) -> str:
        for key, text in sections.items():
            if any(kw in key.lower() for kw in ["ablat", "component", "analysis", "discussion"]):
                if self._looks_like_ablation(text):
                    return text[:3000]
        # Broader fallback: scan all sections for ablation-like content
        for key, text in sections.items():
            if self._looks_like_ablation(text):
                return text[:3000]
        return ""

    def _looks_like_ablation(self, text: str) -> bool:
        ablation_hits = sum(
            1 for p in ABLATION_COL_PATTERNS
            if re.search(p, text, re.IGNORECASE)
        )
        return ablation_hits >= 2

    async def _llm_parse(self, text: str) -> Dict:
        try:
            from core.llm.llm_interface import get_llm
            # Use a fast non-reasoning model to avoid rate-limit contention with SummaryAgent
            fast_config = dict(self._llm_config or {})
            fast_config['model_name'] = 'llama-3.1-8b-instant'
            llm = get_llm(fast_config)
            raw = await llm.generate(text[:2000], system_prompt=ABLATION_SYSTEM, max_tokens=512)
            return parse_json_object(raw)
        except Exception as e:
            logger.warning("ablation_llm_error", error=str(e))
        return {}

    def _enrich_deltas(self, studies: List[Dict], text: str) -> List[Dict]:
        """Attempt to fill numeric delta from inline patterns like '+1.2' or '-0.5%'."""
        delta_re = re.compile(r"([+-]?\d+\.?\d*)\s*%?")
        for study in studies:
            if study.get("delta") is None and study.get("component"):
                comp = re.escape(study["component"])
                segment = re.search(rf"{comp}.{{0,80}}", text, re.IGNORECASE)
                if segment:
                    m = delta_re.search(segment.group())
                    if m:
                        try:
                            study["delta"] = float(m.group(1))
                        except ValueError:
                            pass
        return studies

    def get_capabilities(self) -> List[str]:
        return ["parse_ablation_tables", "quantify_component_contributions"]
