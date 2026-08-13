"""SummaryAgent - Generates a single comprehensive LLM summary with structured extraction.

Produces one high-quality analysis instead of 4 truncated variants:
- Main narrative summary (400-700 words, no token cap)
- LLM-extracted key_findings list
- LLM-extracted limitations list
- LLM-extracted future_work list
"""

import asyncio
import sys
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from difflib import SequenceMatcher

sys.path.append(str(Path(__file__).parent.parent.parent))

from core.agents.base_agent import BaseAgent, AgentState
from core.llm.llm_interface import LocalLLM

try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False


def _get_section(sections: Dict[str, str], *keywords: str) -> str:
    """Fuzzy section lookup: return first section whose key contains any keyword."""
    kws = [k.lower() for k in keywords]
    for key, val in sections.items():
        key_lower = key.lower()
        if any(kw in key_lower for kw in kws):
            return val
    return ''


def _build_paper_context(sections: Dict[str, str], max_chars: int = 8000) -> str:
    """Concatenate all meaningful sections into a single context string."""
    # Priority order: abstract first, then introduction, then rest
    priority = ['abstract', 'introduction', 'method', 'result', 'experiment',
                'discussion', 'conclusion', 'dataset', 'evaluat']

    def section_priority(key: str) -> int:
        kl = key.lower()
        for i, p in enumerate(priority):
            if p in kl:
                return i
        return len(priority)

    ordered = sorted(sections.items(), key=lambda kv: section_priority(kv[0]))

    parts = []
    total = 0
    for key, text in ordered:
        if not text or key in ('__references__', 'references', 'acknowledgment',
                                'acknowledgements', 'conflict_of_interest'):
            continue
        # Clean up section header
        header = key.replace('_', ' ').strip().title()
        snippet = text[:3000] if total == 0 else text[:1500]
        chunk = f"[{header}]\n{snippet}\n"
        if total + len(chunk) > max_chars:
            remaining = max_chars - total
            if remaining > 200:
                parts.append(chunk[:remaining])
            break
        parts.append(chunk)
        total += len(chunk)

    return '\n'.join(parts)


class SummaryAgent(BaseAgent):
    """Produces the paper's long-form summary and structured extractions.

    A thin adapter over :mod:`core.graph.summary_graph`: the orchestrator's agent
    protocol on the outside, the LangGraph engine underneath. It holds no LLM
    client of its own — providers, retries and fallbacks all live in
    :mod:`core.llm.providers`, reached through the graph.
    """

    def get_capabilities(self):
        return ['summary_generation', 'key_findings_extraction', 'limitations_extraction', 'future_work_extraction']

    def __init__(self, patterns: Optional[Dict] = None, llm_config: Optional[Dict] = None,
                 summary_config: Optional[Dict] = None):
        super().__init__(name="SummaryAgent", patterns=patterns)
        # Retained so existing callers keep working; the graph engine reads its
        # provider configuration from the environment rather than from here.
        self.llm_config = llm_config or {}
        self.generated_summaries: Dict[str, str] = {}

    async def process(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Summarise the paper with the LangGraph engine.

        This is the only summarisation path. The former fallback assembled a
        summary from templates ("The paper employs the following models: …")
        whenever the LLM was unreachable, which is indistinguishable from a real
        summary once persisted. Failing here is correct: the caller records the
        stage as failed and the save gate refuses to store the paper.
        """
        from core.graph.adapter import run_graph_summary

        result = await run_graph_summary(input_data)
        if not (result.get('summaries') or {}).get('main'):
            raise RuntimeError(
                'Summarisation produced no summary. Check LLM provider health: '
                'GET /api/health?probe_llm=true'
            )
        return result

    def _score_quality(self, summary: str, abstract: str) -> float:
        """Simple quality score 0–1."""
        words = summary.split()
        score = 0.0
        # Length
        if len(words) >= 200:
            score += 0.4
        elif len(words) >= 80:
            score += 0.25
        else:
            score += 0.1
        # Coverage against abstract
        if abstract:
            abs_words = {w.lower().strip('.,;:()[]') for w in abstract.split() if len(w) >= 5}
            sum_words = {w.lower().strip('.,;:()[]') for w in words}
            coverage = min(len(abs_words & sum_words) / max(len(abs_words), 1), 1.0)
            score += coverage * 0.4
        else:
            score += 0.2
        # Coherence
        sentences = [s.strip() for s in summary.split('.') if len(s.split()) > 3]
        if len(sentences) >= 3:
            sims = [
                SequenceMatcher(None, sentences[i], sentences[i + 1]).ratio()
                for i in range(min(len(sentences) - 1, 5))
            ]
            score += (1.0 - min(sum(sims) / len(sims), 0.8)) * 0.2
        else:
            score += 0.1
        return round(min(score, 1.0), 4)
