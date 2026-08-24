"""ResearchGapAgent — extracts explicit and implicit research gaps from a paper."""

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

# Hedge language patterns that signal an explicit gap
EXPLICIT_GAP_PATTERNS = [
    r"(?:we |the authors? )?leave[s]? (?P<gap>.+?) (?:for future|as future)",
    r"(?:remains?|is) (?:an? )?open (?:problem|question|challenge)[:\s]?(?P<gap>[^.]+)",
    r"(?:a|one) limitation (?:of|is)[:\s]?(?P<gap>[^.]+)",
    r"future work (?:could|should|may|might|will)[:\s]?(?P<gap>[^.]+)",
    r"(?:not addressed|not explored|not investigated|out of scope)[:\s]?(?P<gap>[^.]*)",
    r"(?:beyond the scope)[:\s]?(?P<gap>[^.]*)",
    r"(?:a|the) (?:key )?(?:challenge|difficulty|limitation)[:\s]?(?P<gap>[^.]+)",
]

_GAP_SECTIONS = {"conclusion", "conclusions", "limitations", "discussion",
                 "future_work", "future work", "abstract"}

RESEARCH_GAP_SYSTEM = (
    "You are a research analyst. Read the provided paper sections and identify:\n"
    "1. EXPLICIT gaps: problems the authors themselves admit remain unsolved.\n"
    "2. IMPLICIT gaps: things the paper evaluates on but misses (e.g., only tested on one dataset, "
    "no ablation, no efficiency analysis).\n"
    "3. FUTURE directions: concrete next steps suggested by the work.\n\n"
    "Return ONLY valid JSON:\n"
    '{"explicit_gaps": ["..."], "implicit_gaps": ["..."], "future_directions": ["..."]}'
)


class ResearchGapAgent(BaseAgent):
    """Identifies research gaps — both explicit (stated by authors) and implicit."""

    def __init__(self, patterns: Optional[Dict] = None, llm_config: Optional[Dict] = None):
        super().__init__(name="ResearchGapAgent", patterns=patterns)
        self._llm_config = llm_config or {}

    async def process(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        sections: Dict[str, str] = input_data.get("sections", {})
        domain: str = input_data.get("domain", "general")

        explicit_gaps = self._extract_regex_gaps(sections)
        llm_result = await self._llm_extract(sections)

        # Merge: regex explicit gaps + LLM output
        all_explicit = list(dict.fromkeys(explicit_gaps + llm_result.get("explicit_gaps", [])))
        implicit = llm_result.get("implicit_gaps", [])
        future = llm_result.get("future_directions", [])

        gaps_data = {
            "explicit_gaps": all_explicit[:10],
            "implicit_gaps": implicit[:10],
            "future_directions": future[:8],
        }

        confidence = 0.85 if all_explicit or implicit else 0.5

        return {
            "extractions": all_explicit + implicit + future,
            "confidence_scores": {"gaps": confidence},
            "gaps": gaps_data,
            "metadata": {
                "domain": domain,
                "explicit_count": len(all_explicit),
                "implicit_count": len(implicit),
                "future_count": len(future),
            },
        }

    def _extract_regex_gaps(self, sections: Dict[str, str]) -> List[str]:
        gaps: List[str] = []
        target_text = " ".join(
            v for k, v in sections.items()
            if any(s in k.lower() for s in _GAP_SECTIONS)
        )
        for pattern in EXPLICIT_GAP_PATTERNS:
            for m in re.finditer(pattern, target_text, re.IGNORECASE):
                gap = m.group("gap").strip() if "gap" in m.groupdict() else m.group(0).strip()
                if len(gap) > 10:
                    gaps.append(gap[:200])
        return gaps

    async def _llm_extract(self, sections: Dict[str, str]) -> Dict[str, List[str]]:
        try:
            from core.llm.llm_interface import get_llm
            # get_llm() returns a process-wide singleton that ignores `config` after
            # first construction (core/llm/llm_interface.py:641-647), and generate()
            # always routes through the "smart" tier regardless of model_name
            # (_generate_via_providers hardcodes tier="smart") — so overriding
            # model_name here was a no-op; every call already goes through whatever
            # backend SummaryAgent initialized first.
            llm = get_llm(self._llm_config)
            # Focus on high-signal sections; cap at ~1200 chars total
            target_keys = ["conclusion", "conclusions", "limitations", "discussion",
                           "future_work", "abstract"]
            text_parts = []
            for key in target_keys:
                for k, v in sections.items():
                    if any(t in k.lower() for t in [key]):
                        text_parts.append(f"[{k}]\n{v[:400]}")
            context = "\n\n".join(text_parts[:5])
            if not context:
                return {}
            raw = await llm.generate(context, system_prompt=RESEARCH_GAP_SYSTEM, max_tokens=512)
            return parse_json_object(raw)
        except Exception as e:
            logger.warning("research_gap_llm_error", error=str(e))
        return {}

    def get_capabilities(self) -> List[str]:
        return ["extract_explicit_gaps", "extract_implicit_gaps", "identify_future_directions"]
