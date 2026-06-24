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
    """
    Generates one comprehensive summary and structured extractions using a single LLM call.
    """

    def get_capabilities(self):
        return ['summary_generation', 'key_findings_extraction', 'limitations_extraction', 'future_work_extraction']

    def __init__(self, patterns: Optional[Dict] = None, llm_config: Optional[Dict] = None,
                 summary_config: Optional[Dict] = None):
        super().__init__(name="SummaryAgent", patterns=patterns)
        self.llm_config = llm_config or {
            'backend': 'ollama',
            'model_name': 'qwen2.5:3b',
            'max_tokens': 1024,
            'temperature': 0.7
        }
        self.llm = LocalLLM(**self.llm_config)
        self.generated_summaries: Dict[str, str] = {}

    async def process(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Generate a single comprehensive summary + structured field extraction."""
        import time
        import os as _os
        total_start = time.time()

        # New LangGraph engine (map-reduce over full paper + structured extraction).
        # Enable with PAPERMIND_USE_GRAPH=1. Falls back to the legacy path on error.
        if _os.environ.get('PAPERMIND_USE_GRAPH', '').strip() in ('1', 'true', 'yes'):
            try:
                from core.graph.adapter import run_graph_summary
                result = await run_graph_summary(input_data)
                if result.get('summaries', {}).get('main'):
                    return result
                import sys as _sys
                print("[SummaryAgent] graph engine returned empty summary, "
                      "using legacy path", file=_sys.stderr, flush=True)
            except Exception as e:
                import sys as _sys
                print(f"[SummaryAgent] graph engine failed, using legacy: "
                      f"{type(e).__name__}: {e}", file=_sys.stderr, flush=True)

        domain = input_data.get('metadata', {}).get('domain', 'general')
        sections = input_data.get('sections', {})
        entities = input_data.get('entities', {})
        results = input_data.get('results', [])
        reasoning = input_data.get('reasoning', {})
        metadata = input_data.get('metadata', {})

        paper_context = _build_paper_context(sections, max_chars=4000)

        # Single LLM call → structured JSON (reduces 4 calls to 1, avoids rate limits)
        summary_text, summary_conf, key_findings, limitations, future_work = \
            await self._generate_all_in_one(
                paper_context, sections, entities, results, reasoning, metadata, domain
            )

        self.generated_summaries['main'] = summary_text
        total_time = (time.time() - total_start) * 1000

        return {
            'extractions': [summary_text],
            'confidence_scores': {'main': summary_conf},
            'summaries': {'main': summary_text},
            'key_findings': key_findings,
            'limitations': limitations,
            'future_work': future_work,
            'section_summaries': {},
            'metadata': {
                'llm_backend': self.llm.backend.value,
                'llm_model': self.llm.model_name,
                'total_generation_time_ms': total_time,
                'validation_passed': bool(summary_text and len(summary_text.split()) > 50),
                'summary_quality': summary_conf,
                'domain': domain,
            }
        }

    def _get_system_prompt(self, domain: str) -> str:
        domain_focus = {
            'cv': (
                "You are an expert computer vision researcher. "
                "Emphasise architecture choices, benchmark datasets, evaluation metrics (mAP, IoU, top-1 accuracy), "
                "and what the visual understanding advance means in practice."
            ),
            'nlp': (
                "You are an expert NLP researcher. "
                "Emphasise model architecture, benchmark datasets (GLUE, SQuAD, WMT), metrics (BLEU, ROUGE, F1), "
                "and the practical language understanding advance."
            ),
            'ml': (
                "You are an expert machine learning researcher. "
                "Emphasise training methodology, optimisation, convergence, generalisation, and theoretical contributions."
            ),
            'general': (
                "You are an expert academic researcher with broad scientific knowledge. "
                "Summarise clearly and accurately, highlighting core contributions and their real-world implications."
            ),
        }
        base = domain_focus.get(domain, domain_focus['general'])
        return (
            base + "\n\n"
            "Write in flowing prose — no bullet lists, no headers, no markdown. "
            "Be concrete: name specific models, datasets, and numbers from the paper. "
            "Never fabricate details; if something is not mentioned in the paper, do not include it."
        )

    async def _generate_all_in_one(
        self,
        paper_context: str,
        sections: Dict[str, str],
        entities: Dict,
        results,
        reasoning: Dict,
        metadata: Dict,
        domain: str,
    ):
        """Single LLM call → summary + key_findings + limitations + future_work.

        Returns (summary_text, quality, key_findings, limitations, future_work).
        Using one call instead of four avoids Groq rate limits during parallel pipeline.
        """
        import re
        import json as _json

        title = metadata.get('title', 'this paper')
        abstract = _get_section(sections, 'abstract')[:800]
        models = entities.get('entities', {}).get('models', [])[:6]
        datasets = entities.get('entities', {}).get('datasets', [])[:6]
        metrics_list = entities.get('entities', {}).get('metrics', [])[:5]

        inline = []
        if isinstance(results, dict):
            inline = (results.get('results', {}).get('table_results', []) +
                      results.get('results', {}).get('inline_results', []))

        result_lines = []
        for r in inline[:6]:
            m, v, d = r.get('metric', ''), r.get('value', ''), r.get('dataset', '')
            if m and v:
                result_lines.append(f"  • {m}: {v}" + (f" on {d}" if d else ''))

        entity_block = ''
        if models:      entity_block += f"Models: {', '.join(models)}\n"
        if datasets:    entity_block += f"Datasets: {', '.join(datasets)}\n"
        if metrics_list: entity_block += f"Metrics: {', '.join(metrics_list)}\n"
        if result_lines: entity_block += "Results:\n" + '\n'.join(result_lines) + '\n'

        system_prompt = self._get_system_prompt(domain)
        prompt = (
            f"Analyze the following research paper and return a JSON object with EXACTLY these keys in this order:\n"
            f"  findings   - array of 3-5 specific key findings with numbers from paper\n"
            f"  limitations - array of 2-3 limitations (empty array [] if none)\n"
            f"  future_work - array of 2-3 future directions (empty array [] if none)\n"
            f"  summary    - 350-400 word analysis covering problem, method, results, contributions\n\n"
            f"IMPORTANT: Put summary LAST. Return ONLY valid JSON, no markdown fences.\n\n"
            f"Paper title: {title}\n\n"
            + (f"Abstract:\n{abstract}\n\n" if abstract else '')
            + (entity_block + '\n' if entity_block else '')
            + f"Paper content:\n{paper_context}"
        )

        # Use a non-reasoning model for summary generation — reasoning models spend most
        # of their token budget on hidden thinking, leaving too few tokens for long prose.
        # llama-3.3-70b-versatile: 30k TPM on Groq free tier, no reasoning overhead.
        _REASONING_MODELS_SUMMARY = frozenset({
            'qwen/qwen3-32b', 'qwen/qwen3-8b', 'qwen/qwen3-14b', 'qwen/qwen3-72b',
            'qwq-32b', 'deepseek-r1', 'deepseek-r1-distill-llama-70b',
        })
        import os as _os
        summary_llm = self.llm
        if (self.llm.model_name in _REASONING_MODELS_SUMMARY and
                self.llm.backend.value == 'groq'):
            override_model = _os.environ.get('PAPERMIND_SUMMARY_MODEL', 'llama-3.3-70b-versatile')
            from core.llm.llm_interface import LocalLLM as _LLM, LLMBackend as _Backend
            # Temporarily unset PAPERMIND_LLM_MODEL so LocalLLM uses our model_name arg
            _saved = _os.environ.pop('PAPERMIND_LLM_MODEL', None)
            try:
                summary_llm = _LLM(
                    backend=_Backend.GROQ.value,
                    model_name=override_model,
                    max_tokens=4096,
                    temperature=0.4,
                )
            finally:
                if _saved is not None:
                    _os.environ['PAPERMIND_LLM_MODEL'] = _saved

        try:
            raw = await summary_llm.generate(
                prompt,
                system_prompt=system_prompt,
                max_tokens=6000,
                temperature=0.4,
            )
            raw = raw.strip()

            # ── JSON extraction ──────────────────────────────────────────────
            parsed = None
            # Strip ```json ... ``` fences if present
            fence_match = re.search(r'```(?:json)?\s*([\s\S]+?)\s*```', raw)
            if fence_match:
                candidate = fence_match.group(1).strip()
            else:
                candidate = raw

            # Try whole response first, then first {...} block
            for attempt in (candidate, re.search(r'\{[\s\S]+\}', candidate)):
                text = attempt if isinstance(attempt, str) else (attempt.group(0) if attempt else None)
                if not text:
                    continue
                try:
                    parsed = _json.loads(text)
                    break
                except Exception:
                    pass

            # Truncated JSON recovery: findings/limitations/future_work appear FIRST in our prompt
            # so even if summary is cut off, we can still recover the structured fields.
            if not parsed and ('"findings"' in candidate or '"summary"' in candidate):
                partial: dict = {}
                # Recover array fields (findings, limitations, future_work appear before summary)
                for field in ('findings', 'limitations', 'future_work'):
                    fm = re.search(rf'"{field}"\s*:\s*\[([^\]]*)\]', candidate, re.DOTALL)
                    if fm:
                        items = re.findall(r'"((?:[^"\\]|\\.)*)"', fm.group(1))
                        partial[field] = [x.replace('\\"', '"') for x in items if x.strip()]
                    else:
                        partial[field] = []
                # Recover summary (may be truncated — use greedy match up to end)
                sm = re.search(r'"summary"\s*:\s*"(.+)', candidate, re.DOTALL)
                if sm:
                    raw_sum = sm.group(1)
                    # Strip trailing JSON artifacts (incomplete escape, stray quotes)
                    raw_sum = re.sub(r'\\["\\/]?$', '', raw_sum).strip().rstrip('"').strip()
                    partial['summary'] = raw_sum.replace('\\"', '"').replace('\\n', '\n')
                if partial.get('findings') or partial.get('summary'):
                    parsed = partial


            if parsed and isinstance(parsed, dict):
                summary_text = str(parsed.get('summary', '')).strip()
                key_findings = [str(x).strip() for x in parsed.get('findings', []) if str(x).strip()]
                limitations  = [str(x).strip() for x in parsed.get('limitations', []) if str(x).strip()]
                future_work  = [str(x).strip() for x in parsed.get('future_work', []) if str(x).strip()]
            else:
                # JSON parse failed entirely: treat response as plain summary if it doesn't look like JSON
                if raw.startswith('{'):
                    summary_text = self._fallback_summary(sections, entities, abstract)
                else:
                    summary_text = raw
                key_findings = []
                limitations = []
                future_work = []

            if not summary_text or len(summary_text.split()) < 30:
                summary_text = self._fallback_summary(sections, entities, abstract)

            quality = self._score_quality(summary_text, abstract)
            return summary_text, quality, key_findings, limitations, future_work

        except Exception as e:
            import sys as _sys
            print(f"[SummaryAgent] _generate_all_in_one error: {type(e).__name__}: {e}", file=_sys.stderr, flush=True)
            fallback = self._fallback_summary(sections, entities, abstract)
            return fallback, 0.3, [], [], []

    def _parse_list(self, raw: str) -> List[str]:
        """Parse a numbered/bulleted list from LLM output into a Python list."""
        import re
        lines = raw.strip().splitlines()
        items = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            # Strip leading numbering or bullets
            cleaned = re.sub(r'^[\d]+[.)]\s*', '', line)
            cleaned = re.sub(r'^[-•*]\s*', '', cleaned).strip()
            if cleaned and len(cleaned) > 5:
                items.append(cleaned)
        return items[:6]  # cap at 6

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

    def _fallback_summary(self, sections: Dict, entities: Dict, abstract: str) -> str:
        models = entities.get('entities', {}).get('models', [])
        datasets = entities.get('entities', {}).get('datasets', [])
        parts = []
        if abstract:
            parts.append(abstract[:400])
        if models:
            parts.append(f"The paper employs the following models: {', '.join(models)}.")
        if datasets:
            parts.append(f"Experiments are conducted on: {', '.join(datasets)}.")
        return ' '.join(parts) or "Summary not available."
