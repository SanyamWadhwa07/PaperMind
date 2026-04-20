"""SummaryAgent - Generates narrative summaries using LLM.

Uses LocalLLM to create coherent summaries from extracted facts:
- Receives structured data from all agents
- Uses LLM to generate 4 distinct summary types independently
- Includes key findings, results, and methodology
- Validates summary quality and applies length constraints
"""

import sys
from pathlib import Path
from typing import Dict, List, Any, Optional
import json
from difflib import SequenceMatcher

# Add parent directory to path for imports
sys.path.append(str(Path(__file__).parent.parent.parent))

from core.agents.base_agent import BaseAgent, AgentState
from core.llm.llm_interface import LocalLLM

try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False


class SummaryAgent(BaseAgent):
    """
    Agent responsible for generating final narrative summary.
    
    Capabilities:
    - Generate coherent summary from structured data
    - Use LLM for natural language generation
    - Structure summary with introduction, findings, results
    - Include key figures and claims
    """
    
    def __init__(self, patterns: Optional[Dict] = None, llm_config: Optional[Dict] = None, 
                 summary_config: Optional[Dict] = None):
        super().__init__(name="SummaryAgent", patterns=patterns)
        
        # Initialize LLM
        self.llm_config = llm_config or {
            'backend': 'ollama',
            'model_name': 'qwen2.5:3b',
            'max_tokens': 512,
            'temperature': 0.7
        }
        self.llm = LocalLLM(**self.llm_config)
        
        # Load summary configuration
        self.summary_config = summary_config or self._load_default_config()
        
        # Store all generated summaries
        self.generated_summaries: Dict[str, str] = {}
        self.generation_attempts: Dict[str, int] = {}
    
    async def process(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Generate 4 distinct narrative summaries from agent outputs."""
        import time
        total_start = time.time()
        
        domain = input_data.get('metadata', {}).get('domain', 'general')
        
        # Generate all 4 summary types independently
        simple_summary, simple_conf = await self._generate_simple_summary(input_data, domain)
        detailed_summary, detailed_conf = await self._generate_detailed_summary(input_data, domain)
        eli5_summary, eli5_conf = await self._generate_eli5_summary(input_data, domain)
        technical_summary, technical_conf = await self._generate_technical_summary(input_data, domain)

        # Generate per-section summaries
        sections = input_data.get('sections', {})
        section_summaries = await self._generate_section_summaries(sections, domain)

        total_time = (time.time() - total_start) * 1000

        validation_passed = self._validate_summaries(simple_summary, detailed_summary, eli5_summary, technical_summary)
        overall_quality = round(
            (simple_conf + detailed_conf + eli5_conf + technical_conf) / 4, 4
        )

        return {
            'extractions': [simple_summary, detailed_summary, eli5_summary, technical_summary],
            'confidence_scores': {
                'simple': simple_conf, 'detailed': detailed_conf,
                'eli5': eli5_conf, 'technical': technical_conf
            },
            'summaries': {
                'simple': simple_summary, 'detailed': detailed_summary,
                'eli5': eli5_summary, 'technical': technical_summary
            },
            'section_summaries': section_summaries,
            'metadata': {
                'llm_backend': self.llm.backend.value,
                'llm_model': self.llm.model_name,
                'total_generation_time_ms': total_time,
                'validation_passed': validation_passed,
                'summary_quality': overall_quality,
                'domain': domain,
            }
        }
    
    def _load_default_config(self) -> Dict[str, Any]:
        config_path = Path(__file__).parent.parent.parent / 'config.yaml'
        if config_path.exists() and YAML_AVAILABLE:
            try:
                with open(config_path, 'r') as f:
                    return yaml.safe_load(f).get('summary_config', self._get_hardcoded_defaults())
            except: pass
        return self._get_hardcoded_defaults()
    
    def _get_hardcoded_defaults(self) -> Dict[str, Any]:
        return {
            'simple': {'min_tokens': 50, 'max_tokens': 150},
            'detailed': {'min_tokens': 200, 'max_tokens': 600},
            'eli5': {'min_tokens': 100, 'max_tokens': 200},
            'technical': {'min_tokens': 150, 'max_tokens': 500},
            'domain_overrides': {}
        }
    
    def _get_token_limits(self, summary_type: str, domain: str) -> Dict[str, int]:
        base_limits = self.summary_config.get(summary_type, {'min_tokens': 100, 'max_tokens': 300})
        overrides = self.summary_config.get('domain_overrides', {}).get(domain, {})
        if f'{summary_type}_max' in overrides: base_limits['max_tokens'] = overrides[f'{summary_type}_max']
        if f'{summary_type}_min' in overrides: base_limits['min_tokens'] = overrides[f'{summary_type}_min']
        return base_limits
    
    def _get_domain_system_prompt(self, domain: str) -> str:
        """Return a domain-tailored system prompt for the LLM."""
        prompts = {
            'cv': (
                "You are an expert in computer vision. When summarizing, emphasize: "
                "architecture choices (CNNs, ViT, CLIP), benchmark datasets (ImageNet, COCO, CIFAR), "
                "evaluation metrics (mAP, IoU, top-1 accuracy), and visual understanding tasks."
            ),
            'nlp': (
                "You are an expert in natural language processing. When summarizing, emphasize: "
                "model architectures (transformers, BERT variants, LLMs), benchmark datasets (GLUE, SQuAD, WMT), "
                "evaluation metrics (BLEU, ROUGE, perplexity, F1), and language understanding tasks."
            ),
            'ml': (
                "You are an expert in machine learning. When summarizing, emphasize: "
                "training methodology, optimization techniques, convergence behavior, "
                "generalization analysis, and theoretical contributions alongside empirical results."
            ),
            'general': (
                "You are an expert academic researcher. Summarize papers clearly, emphasizing "
                "the core contribution, methodology, key results, and broader significance."
            ),
        }
        return prompts.get(domain, prompts['general'])

    def _score_summary_quality(self, text: str, source_sections: Dict[str, str]) -> float:
        """Score summary quality 0.0–1.0 across three dimensions."""
        if not text or not text.strip():
            return 0.0

        words = text.split()
        score = 0.0

        # 1. Length score (40%): penalise very short or truncated summaries
        word_count = len(words)
        if word_count >= 80:
            score += 0.4
        elif word_count >= 40:
            score += 0.2
        else:
            score += 0.05

        # 2. Coverage score (40%): key terms from abstract appear in summary
        abstract = source_sections.get('abstract', '')
        if abstract:
            # Extract meaningful words (≥5 chars) from abstract
            abstract_words = {w.lower().strip('.,;:()[]') for w in abstract.split() if len(w) >= 5}
            summary_words = {w.lower().strip('.,;:()[]') for w in words}
            overlap = abstract_words & summary_words
            coverage = min(len(overlap) / max(len(abstract_words), 1), 1.0)
            score += coverage * 0.4
        else:
            score += 0.2  # partial credit when no abstract

        # 3. Coherence score (20%): adjacent sentence pairs shouldn't be near-identical
        sentences = [s.strip() for s in text.split('.') if len(s.split()) > 3]
        if len(sentences) < 2:
            score += 0.1
        else:
            similarities = [
                SequenceMatcher(None, sentences[i], sentences[i + 1]).ratio()
                for i in range(len(sentences) - 1)
            ]
            avg_sim = sum(similarities) / len(similarities)
            # Low similarity between neighbours = more coherent diversity
            coherence = 1.0 - min(avg_sim, 0.8)
            score += coherence * 0.2

        return round(min(score, 1.0), 4)

    async def _generate_section_summaries(
        self, sections: Dict[str, str], domain: str
    ) -> Dict[str, str]:
        """Generate a 1–2 sentence summary for each paper section."""
        result: Dict[str, str] = {}
        system_prompt = self._get_domain_system_prompt(domain)
        skip = {'__references__', 'references'}
        for section_name, text in sections.items():
            if section_name in skip or not text or len(text.split()) < 30:
                continue
            prompt = (
                f"In 1-2 sentences, summarise the '{section_name}' section of this paper:\n\n"
                f"{text[:1200]}"
            )
            try:
                summary = await self.llm.generate(
                    prompt, system_prompt=system_prompt, max_tokens=120
                )
                result[section_name] = summary.strip()
            except Exception:
                result[section_name] = text[:200].strip() + '...'
        return result

    async def _generate_simple_summary(self, input_data: Dict[str, Any], domain: str):
        limits = self._get_token_limits('simple', domain)
        sections = input_data.get('sections', {})
        metadata = input_data.get('metadata', {})
        reasoning = input_data.get('reasoning', {})
        title = metadata.get('title', 'Research Paper')
        abstract = sections.get('abstract', '')[:800]
        # Include top-3 key findings when available
        findings = reasoning.get('reasoning', {}).get('claims', [])[:3]
        findings_str = '\n'.join(f"- {c.get('text', '')}" for c in findings if c.get('text'))
        system_prompt = self._get_domain_system_prompt(domain)
        prompt = (
            f"Summarize this research paper in 2-3 clear sentences for a general audience.\n\n"
            f"Title: {title}\n"
            f"Abstract: {abstract}\n"
            + (f"\nKey findings:\n{findings_str}\n" if findings_str else '')
            + f"\nWrite {limits['min_tokens']}-{limits['max_tokens']} words explaining the problem, "
              f"main contribution, and why it matters."
        )
        try:
            summary = await self.llm.generate(prompt, system_prompt=system_prompt, max_tokens=limits['max_tokens'])
            summary = summary.strip()
            self.generated_summaries['simple'] = summary
            quality = self._score_summary_quality(summary, sections)
            return summary, quality
        except Exception:
            return f"This paper addresses {abstract[:100]}...", 0.5
    
    async def _generate_detailed_summary(self, input_data: Dict[str, Any], domain: str):
        limits = self._get_token_limits('detailed', domain)
        sections = input_data.get('sections', {})
        entities = input_data.get('entities', {})
        results = input_data.get('results', [])
        reasoning = input_data.get('reasoning', {})
        metadata = input_data.get('metadata', {})
        system_prompt = self._get_domain_system_prompt(domain)
        prompt = self._build_detailed_prompt(sections, entities, results, reasoning, metadata, limits)
        try:
            summary = await self.llm.generate(prompt, system_prompt=system_prompt, max_tokens=limits['max_tokens'])
            summary = summary.strip()
            self.generated_summaries['detailed'] = summary
            return summary, self._score_summary_quality(summary, sections)
        except Exception:
            return self._fallback_summary(sections, entities, results, reasoning), 0.6
    
    async def _generate_eli5_summary(self, input_data: Dict[str, Any], domain: str):
        limits = self._get_token_limits('eli5', domain)
        sections = input_data.get('sections', {})
        metadata = input_data.get('metadata', {})
        title = metadata.get('title', 'Research Paper')
        abstract = sections.get('abstract', '')[:600]
        prompt = (
            f"Explain this research paper as if talking to a curious 10-year-old.\n\n"
            f"Title: {title}\n"
            f"Context: {abstract}\n\n"
            f"In {limits['min_tokens']}-{limits['max_tokens']} words: explain the problem they solved, "
            f"how they solved it, and what cool thing they discovered. Use simple words and analogies."
        )
        try:
            summary = await self.llm.generate(prompt, max_tokens=limits['max_tokens'])
            summary = summary.strip()
            self.generated_summaries['eli5'] = summary
            return summary, self._score_summary_quality(summary, sections)
        except Exception:
            return f"Scientists studied {abstract[:80]}. They found interesting results.", 0.4
    
    async def _generate_technical_summary(self, input_data: Dict[str, Any], domain: str):
        limits = self._get_token_limits('technical', domain)
        sections = input_data.get('sections', {})
        entities = input_data.get('entities', {})
        results = input_data.get('results', [])
        reasoning = input_data.get('reasoning', {})
        metadata = input_data.get('metadata', {})
        system_prompt = self._get_domain_system_prompt(domain)
        prompt = self._build_technical_prompt(sections, entities, results, reasoning, metadata, limits)
        try:
            summary = await self.llm.generate(prompt, system_prompt=system_prompt, max_tokens=limits['max_tokens'])
            summary = summary.strip()
            self.generated_summaries['technical'] = summary
            return summary, self._score_summary_quality(summary, sections)
        except Exception:
            methodology = sections.get('methodology', sections.get('method', ''))[:limits['max_tokens'] * 5]
            return methodology.strip() or "Technical details not available.", 0.5
    
    def _validate_summaries(self, simple: str, detailed: str, eli5: str, technical: str) -> bool:
        summaries = {'simple': simple, 'detailed': detailed, 'eli5': eli5, 'technical': technical}
        for summary_type, text in summaries.items():
            min_len = self.summary_config.get(summary_type, {}).get('min_tokens', 50)
            if len(text.split()) < min_len: return False
            placeholders = ['not available', 'no summary', 'error', 'failed to generate']
            if any(ph in text.lower() for ph in placeholders): return False
        summary_list = [simple, detailed, eli5, technical]
        for i in range(len(summary_list)):
            for j in range(i + 1, len(summary_list)):
                if SequenceMatcher(None, summary_list[i], summary_list[j]).ratio() > 0.7: return False
        return True
    
    def _build_detailed_prompt(self, sections: Dict[str, str], entities: Dict, results: List[Dict], reasoning: Dict, metadata: Dict, limits: Dict[str, int]) -> str:
        title = metadata.get('title', 'Research Paper')
        abstract = sections.get('abstract', '')[:500]
        models = entities.get('entities', {}).get('models', [])[:5]
        datasets = entities.get('entities', {}).get('datasets', [])[:5]
        result_str = '\\n'.join([f"- {r.get('metric')}: {r.get('value')} on {r.get('dataset')}" for r in results[:5]])
        claims = reasoning.get('reasoning', {}).get('claims', [])[:3]
        claim_str = '\\n'.join([f"- {c.get('text', '')}" for c in claims])
        return f"Write a comprehensive academic summary ({limits['min_tokens']}-{limits['max_tokens']} words).\\n\\nTitle: {title}\\nAbstract: {abstract}\\n\\nModels: {', '.join(models)}\\nDatasets: {', '.join(datasets)}\\nResults:\\n{result_str}\\nClaims:\\n{claim_str}\\n\\nCover: problem, approach, findings, significance. Professional tone."
    
    def _build_technical_prompt(self, sections: Dict[str, str], entities: Dict, results: List[Dict], reasoning: Dict, metadata: Dict, limits: Dict[str, int]) -> str:
        title = metadata.get('title', 'Research Paper')
        methodology = sections.get('methodology', sections.get('method', ''))[:800]
        models = entities.get('entities', {}).get('models', [])[:5]
        return f"Write technical summary ({limits['min_tokens']}-{limits['max_tokens']} words) for experts.\\n\\nTitle: {title}\\nMethodology: {methodology}\\nModels: {', '.join(models)}\\n\\nFocus: innovations, implementation, setup, quantitative improvements. Use technical terminology."
    
    def _build_prompt(
        self,
        sections: Dict[str, str],
        entities: Dict,
        results: List[Dict],
        reasoning: Dict,
        figures: List[Dict],
        metadata: Dict
    ) -> str:
        """
        Build structured prompt for LLM.
        
        Format:
        - Paper context
        - Key entities (models, datasets)
        - Main results
        - Causal claims
        - Request for coherent summary
        """
        # Extract key info
        title = metadata.get('title', 'Research Paper')
        abstract = sections.get('abstract', '')[:500]  # First 500 chars
        
        models = entities.get('models', [])[:5]
        datasets = entities.get('datasets', [])[:5]
        
        top_results = results[:5] if results else []
        result_str = '\n'.join([
            f"- {r.get('metric', 'metric')}: {r.get('value', 'N/A')} on {r.get('dataset', 'dataset')}"
            for r in top_results
        ])
        
        claims = reasoning.get('claims', [])[:3]
        claim_str = '\n'.join([f"- {c.get('text', '')}" for c in claims])
        
        top_figures = figures[:3] if figures else []
        figure_str = '\n'.join([
            f"- {f.get('id', 'Figure')}: {f.get('caption', 'No caption')[:100]}"
            for f in top_figures
        ])
        
        prompt = f"""You are summarizing a research paper titled: "{title}"

Abstract excerpt: {abstract}

Key entities:
- Models: {', '.join(models) if models else 'None extracted'}
- Datasets: {', '.join(datasets) if datasets else 'None extracted'}

Main results:
{result_str if result_str else 'No results extracted'}

Key claims:
{claim_str if claim_str else 'No claims extracted'}

Key figures:
{figure_str if figure_str else 'No figures extracted'}

Generate a concise summary (300-400 words) covering:
1. What problem does this paper address?
2. What is the proposed approach/method?
3. What are the main findings and results?
4. What is the significance of this work?

Write in clear, professional academic style. Focus on concrete contributions."""
        
        return prompt
    
    def _fallback_summary(
        self,
        sections: Dict[str, str],
        entities: Dict,
        results: List[Dict],
        reasoning: Dict
    ) -> str:
        """
        Template-based summary fallback.
        
        Used when LLM fails or unavailable.
        """
        abstract = sections.get('abstract', '')[:300]
        models = entities.get('models', [])[:3]
        datasets = entities.get('datasets', [])[:3]
        
        summary_parts = []
        
        # Introduction
        summary_parts.append("SUMMARY")
        summary_parts.append(abstract if abstract else "This paper presents research in machine learning.")
        
        # Methodology
        if models:
            summary_parts.append(f"\nThe paper uses {', '.join(models)} as the primary model(s).")
        if datasets:
            summary_parts.append(f"Experiments are conducted on {', '.join(datasets)}.")
        
        # Results
        if results:
            top_result = results[0]
            summary_parts.append(
                f"\nKey result: {top_result.get('metric', 'metric')} of "
                f"{top_result.get('value', 'N/A')} on {top_result.get('dataset', 'benchmark')}."
            )
        
        # Claims
        claims = reasoning.get('claims', [])
        if claims:
            summary_parts.append(f"\nThe authors claim: {claims[0].get('text', '')}")
        
        summary_parts.append("\nThis work contributes to the field through novel methodology and improved results.")
        
        return ' '.join(summary_parts)
    
    def _parse_summary_structure(self, summary_text: str) -> Dict[str, str]:
        """
        Parse summary into structured sections.
        
        Simple heuristic: split by paragraph/sentences
        """
        paragraphs = [p.strip() for p in summary_text.split('\n\n') if p.strip()]
        
        structure = {
            'introduction': paragraphs[0] if len(paragraphs) > 0 else '',
            'methodology': paragraphs[1] if len(paragraphs) > 1 else '',
            'findings': paragraphs[2] if len(paragraphs) > 2 else '',
            'significance': paragraphs[3] if len(paragraphs) > 3 else ''
        }
        
        return structure
    
    async def handle_message(self, message):
        """Handle requests from other agents."""
        from core.agents.message_bus import MessageType
        
        if message.msg_type == MessageType.REQUEST:
            question = message.payload.get('question', '')
            
            # Handle "Get summary" queries
            if 'summary' in question.lower():
                response = {
                    'summary': self.generated_summary,
                    'word_count': len(self.generated_summary.split()),
                    'confidence': 0.9,
                    'agent': self.name
                }
                
                await self.message_bus.respond(
                    original_msg_id=message.msg_id,
                    sender=self.name,
                    recipient=message.sender,
                    payload=response
                )
            else:
                await super().handle_message(message)
    
    def get_capabilities(self) -> List[str]:
        """Return agent capabilities."""
        return [
            'generate_4_summary_types',
            'simple_summary_generation',
            'detailed_summary_generation',
            'eli5_summary_generation',
            'technical_summary_generation',
            'summary_validation',
            'use_local_llm',
            'configurable_token_limits',
            'domain_specific_overrides'
        ]
    
    def get_summary(self) -> str:
        """Get generated summary."""
        return self.generated_summary
    
    def get_llm_info(self) -> Dict[str, Any]:
        """Get LLM backend information."""
        return self.llm.get_info()
