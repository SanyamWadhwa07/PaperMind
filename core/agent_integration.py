"""Agent mode integration for main.py

This module provides a wrapper that integrates the parallel agent system
into the existing main.py without breaking backward compatibility.

Usage:
    python main.py --agent-mode --config config.yaml
"""

import asyncio
import json
import re
import structlog
from pathlib import Path
from typing import Dict, Any, Optional

from core.agents.orchestrator import ParallelAgentOrchestrator
from core.memory.experience_db import ExperienceStore

logger = structlog.get_logger(__name__)


class AgentPaperProcessor:
    """
    Wrapper that processes papers using the parallel agent system.
    
    Compatible with existing main.py interface but uses agents internally.
    """
    
    def __init__(
        self,
        patterns: Optional[Dict] = None,
        config: Optional[Dict] = None
    ):
        self.patterns = patterns or {}
        self.config = config or {}
        
        # Initialize experience store
        self.experience_store = self._init_experience_store()
        
        # Initialize orchestrator
        self.orchestrator = ParallelAgentOrchestrator(
            patterns=self.patterns,
            config=self.config,
            experience_store=self.experience_store
        )
    
    def _init_experience_store(self) -> Optional[ExperienceStore]:
        """Initialize Supabase experience store."""
        if not self.config.get('experience_enabled', True):
            logger.info("experience_disabled", reason="config")
            return None
        
        try:
            # Try to import Supabase config
            from backend.database.config import SUPABASE_URL, SUPABASE_SERVICE_KEY
            
            store = ExperienceStore(
                supabase_url=SUPABASE_URL,
                supabase_key=SUPABASE_SERVICE_KEY
            )
            
            if store.enabled:
                logger.info("experience_store_initialized", backend="supabase")
            return store
        
        except ImportError:
            logger.warning("supabase_import_failed", reason="config_not_found")
            return None
        except Exception as e:
            logger.exception("experience_store_init_error", error=str(e))
            return None
    
    async def process_paper(self, pdf_path: str) -> Dict[str, Any]:
        """
        Process a paper using the parallel agent system.
        
        Args:
            pdf_path: Path to PDF file
        
        Returns:
            Result dictionary compatible with existing main.py format
        """
        # Run orchestrator
        agent_result = await self.orchestrator.process_paper(pdf_path)
        
        # Transform to main.py-compatible format
        compatible_result = self._transform_to_legacy_format(agent_result)
        
        return compatible_result
    
    def _transform_to_legacy_format(self, agent_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        Transform agent system output to match existing JSON schema.
        
        Existing schema has:
        - arxiv_id, title, authors, abstract
        - summaries (simple, detailed, eli5, technical)
        - key_findings, methodology, results, limitations
        - datasets, models, metrics, tasks
        - figures, tables
        - citations, references
        """
        # Extract components
        structure = agent_result.get('structure', {})
        entities = agent_result.get('entities', {})
        results_data = agent_result.get('results', {})
        figures = agent_result.get('figures', {})
        reasoning = agent_result.get('reasoning', {})
        summary = agent_result.get('summary', {})
        gap_data = agent_result.get('research_gaps', {})
        ablation_data = agent_result.get('ablation_studies', {})
        repro_data = agent_result.get('reproducibility', {})
        
        # Log agent results with structured data
        logger.debug(
            "agent_results_aggregated",
            structure_sections=list(structure.get('sections', {}).keys()),
            entity_keys=list(entities.keys()),
            figure_count=len(figures.get('figures', [])),
            has_summary=bool(summary)
        )
        
        # Get sections
        sections = structure.get('sections', {})
        sections_found = list(sections.keys())  # Extract section names for frontend

        # When the LangGraph engine ran, prefer its domain-agnostic extraction over
        # the regex EntityAgent / ResultsAgent output (works for non-ML domains too).
        graph_engine = summary.get('metadata', {}).get('engine') == 'langgraph'
        graph_entities_legacy = summary.get('graph_entities_legacy') or {}
        graph_results = summary.get('graph_results') or []

        regex_entities = entities.get('entities', {})

        def _pick_entities(key: str):
            g = graph_entities_legacy.get(key) or []
            return g if (graph_engine and g) else regex_entities.get(key, [])

        out_models = _pick_entities('models')
        out_datasets = _pick_entities('datasets')
        out_metrics = _pick_entities('metrics')
        out_tasks = _pick_entities('tasks')

        # Normalise graph result rows into the legacy metric shape the frontend reads.
        legacy_results_metrics = (
            results_data.get('results', {}).get('table_results', []) +
            results_data.get('results', {}).get('inline_results', [])
        )
        if graph_engine and graph_results:
            out_results_metrics = [
                {
                    'metric': r.get('measurement', ''),
                    'value': r.get('value', ''),
                    'model': r.get('method', ''),
                    'dataset': r.get('subject', ''),
                    'is_best': r.get('is_best', False),
                }
                for r in graph_results
            ]
        else:
            out_results_metrics = legacy_results_metrics

        # Build compatible output
        output = {
            # Metadata (would come from arxiv API in real usage)
            'arxiv_id': 'unknown',
            'title': 'Research Paper',
            'authors': [],
            'abstract': sections.get('abstract', ''),
            'published': '',
            'updated': '',
            
            # Single comprehensive summary (new) with backward-compat keys
            'summaries': summary.get('summaries', {'main': 'Summary generation in progress'}),

            # Key findings — prefer LLM-extracted from SummaryAgent, fall back to ReasoningAgent claims
            'key_findings': (
                summary.get('key_findings')
                or [claim.get('text', '') for claim in reasoning.get('reasoning', {}).get('claims', [])[:5]]
            ),
            
            # Methodology (NO TRUNCATION - let SummaryAgent handle length)
            'methodology': {
                'approach': sections.get('methodology', ''),
                'models': out_models,
                'datasets': out_datasets
            },

            # Results (NO TRUNCATION - full section content)
            'results': {
                'summary': sections.get('results', ''),
                'metrics': out_results_metrics,
                'comparison': self._extract_comparisons(
                    reasoning.get('reasoning', {}).get('claims', [])
                )
            },

            # Entities
            'datasets': out_datasets,
            'models': out_models,
            'metrics': out_metrics,
            'tasks': out_tasks,

            # Contributions + per-section summaries (graph engine fills these)
            'contributions': summary.get('contributions', []),
            'section_summaries': summary.get('section_summaries', {}),
            # Domain-agnostic typed entities (method/material/measurement/tool)
            'typed_entities': summary.get('graph_entities', {}),
            
            # Figures
            'figures': [
                {
                    'figure_number': i + 1,
                    'id': fig.get('id', f'figure_{i+1}'),
                    'caption': fig.get('caption', ''),
                    'page': fig.get('page', 0),
                    'relevance': fig.get('relevance_score', 0),
                    'section': fig.get('section', 'unknown')
                }
                for i, fig in enumerate(figures.get('figures', [])[:10])
            ],
            
            # Sections found (for frontend display)
            'sections_found': sections_found,
            'section_count': len(sections_found),
            
            # Limitations — prefer LLM-extracted from SummaryAgent, fall back to regex
            'limitations': (
                summary.get('limitations')
                or self._extract_limitations(sections)
            ),

            # Future work — prefer LLM-extracted from SummaryAgent, fall back to regex
            'future_work': (
                summary.get('future_work')
                or self._extract_future_work(sections)
            ),
            
            # Agent-specific metadata (extension to schema)
            'agent_metadata': {
                'processing_mode': 'langgraph' if graph_engine else 'parallel_agents',
                'total_time_ms': agent_result.get('metadata', {}).get('total_time_ms', 0),
                'speedup': agent_result.get('metadata', {}).get('parallel_speedup', 1.0),
                'agent_count': agent_result.get('metadata', {}).get('agent_count', 0),
                # Graph engine reports provider/model under metadata; legacy reports llm_backend.
                'llm_backend': (summary.get('metadata', {}).get('llm_backend')
                                or summary.get('metadata', {}).get('llm_provider', 'unknown')),
                'llm_model': summary.get('metadata', {}).get('llm_model'),
                'summary_quality': summary.get('metadata', {}).get('summary_quality'),
                'experience_applied': self.experience_store is not None,
                'agent_timeline': self._build_agent_timeline(agent_result),
                'consensus_votes': agent_result.get('metadata', {}).get('consensus_votes', 0),
                'conflicts_resolved': agent_result.get('metadata', {}).get('conflicts_resolved', 0)
            },
            
            # Flagged uncertainties (extension to schema)
            'flagged_uncertainties': {
                'uncertain_entities': entities.get('metadata', {}).get('uncertain_entities', []),
                'outlier_results': results_data.get('metadata', {}).get('outlier_details', []),
                'unsupported_claims': reasoning.get('reasoning', {}).get('unsupported_claims', [])
            },

            # New intelligence pipeline outputs
            'research_gaps': gap_data.get('gaps', {}),
            'ablation_studies': ablation_data.get('ablation_studies', []),
            'reproducibility': repro_data.get('reproducibility', {}),

            # Raw sections (needed for post-save tasks)
            'sections': structure.get('sections', {}),
        }

        return output
    
    def _extract_comparisons(self, claims: list) -> list:
        """Extract comparison statements from claims."""
        comparisons = []
        
        comparison_keywords = ['outperform', 'exceed', 'surpass', 'better than', 'improve over']
        
        for claim in claims:
            claim_text = claim.get('text', '').lower()
            if any(kw in claim_text for kw in comparison_keywords):
                comparisons.append(claim.get('text', ''))
        
        return comparisons[:3]
    
    def _extract_limitations(self, sections: Dict[str, str]) -> list:
        """Extract limitations from conclusion/discussion using fuzzy section matching."""
        limitations = []

        keywords = ('conclusion', 'conclud', 'discussion', 'limitation', 'future')
        parts = [v for k, v in sections.items() if any(kw in k.lower() for kw in keywords)]
        combined = ' '.join(parts)
        if not combined:
            combined = ' '.join(sections.values())

        # Simple pattern matching
        import re
        limitation_patterns = [
            r'limitation[s]?[:\s]+([^.]+)',
            r'however[,\s]+([^.]+)',
            r'(?:one|a)\s+drawback[:\s]+([^.]+)'
        ]
        
        for pattern in limitation_patterns:
            matches = re.finditer(pattern, combined, re.IGNORECASE)
            for match in matches:
                limitations.append(match.group(1).strip())
        
        return limitations[:3]
    
    def _extract_future_work(self, sections: Dict[str, str]) -> list:
        """Extract future work from conclusion/discussion using fuzzy section matching."""
        future_work = []

        keywords = ('conclusion', 'conclud', 'future', 'discussion')
        parts = [v for k, v in sections.items() if any(kw in k.lower() for kw in keywords)]
        conclusion = ' '.join(parts) if parts else ' '.join(sections.values())

        import re
        future_patterns = [
            r'future work[:\s]+([^.]+)',
            r'plan to[:\s]+([^.]+)',
            r'will[:\s]+(?:explore|investigate|study)[:\s]+([^.]+)'
        ]
        
        for pattern in future_patterns:
            matches = re.finditer(pattern, conclusion, re.IGNORECASE)
            for match in matches:
                future_work.append(match.group(1).strip())
        
        return future_work[:3]
    
    def _build_agent_timeline(self, agent_result: Dict[str, Any]) -> list:
        """Build execution timeline for agents."""
        agent_times = agent_result.get('metadata', {}).get('agent_times', {})
        
        timeline = []
        for agent_name, time_ms in agent_times.items():
            timeline.append({
                'agent': agent_name,
                'time_ms': time_ms,
                'status': 'completed'
            })
        
        return sorted(timeline, key=lambda x: x['time_ms'], reverse=True)
    
    async def cleanup(self):
        """Cleanup resources."""
        await self.orchestrator.cleanup()


async def process_with_agents(pdf_path: str, config: Dict, patterns: Dict) -> Dict[str, Any]:
    """
    Convenience function to process a paper with agents.
    
    Args:
        pdf_path: Path to PDF
        config: Configuration dict
        patterns: Patterns dict
    
    Returns:
        Processed paper result
    """
    processor = AgentPaperProcessor(patterns=patterns, config=config)
    
    try:
        result = await processor.process_paper(pdf_path)
        return result
    finally:
        await processor.cleanup()


def run_agent_mode(pdf_path: str, config: Dict, patterns: Dict) -> Dict[str, Any]:
    """
    Synchronous wrapper for agent mode (for compatibility with main.py).
    
    Args:
        pdf_path: Path to PDF
        config: Configuration dict
        patterns: Patterns dict
    
    Returns:
        Processed paper result
    """
    return asyncio.run(process_with_agents(pdf_path, config, patterns))
