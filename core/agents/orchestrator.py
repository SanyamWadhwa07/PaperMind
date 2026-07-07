"""ParallelAgentOrchestrator - Coordinates parallel agent execution.

Manages:
- Parallel agent execution with asyncio
- Work-stealing queue for load balancing
- Consensus voting for conflicting results
- Agent failure recovery
- Result aggregation
"""

import sys
from pathlib import Path
from typing import Dict, List, Any, Optional, Set
import asyncio
import time
import logging
import structlog
from collections import defaultdict

# Add parent directory to path for imports
sys.path.append(str(Path(__file__).parent.parent.parent))

from core.agents.base_agent import BaseAgent, AgentState
from core.agents.message_bus import AgentMessageBus, MessageType, MessagePriority
from core.agents.structure_agent import StructureAgent
from core.agents.entity_agent import EntityAgent
from core.agents.results_agent import ResultsAgent
from core.agents.figure_agent import FigureAgent
from core.agents.reasoning_agent import ReasoningAgent
from core.agents.summary_agent import SummaryAgent
from core.agents.comparison_agent import ComparisonAgent
from core.agents.research_gap_agent import ResearchGapAgent
from core.agents.ablation_parser_agent import AblationParserAgent
from core.agents.reproducibility_agent import ReproducibilityAgent

logger = structlog.get_logger(__name__)
from core.memory.experience_db import ExperienceStore


class ParallelAgentOrchestrator:
    """
    Orchestrates parallel execution of specialized agents.
    
    Workflow:
    1. StructureAgent extracts sections (runs first)
    2. Parallel execution:
       - EntityAgent extracts entities
       - ResultsAgent extracts results
       - FigureAgent extracts figures
       - ReasoningAgent analyzes claims
    3. Cross-validation and consensus
    4. SummaryAgent generates final narrative
    """
    
    def __init__(
        self,
        patterns: Optional[Dict] = None,
        config: Optional[Dict] = None,
        experience_store: Optional[ExperienceStore] = None
    ):
        self.patterns = patterns or {}
        self.config = config or {}
        self.experience_store = experience_store
        
        # Initialize message bus
        self.message_bus = AgentMessageBus()
        
        # Initialize agents
        self.structure_agent = StructureAgent(patterns=patterns)
        self.entity_agent = EntityAgent(patterns=patterns)
        self.results_agent = ResultsAgent(patterns=patterns)
        self.figure_agent = FigureAgent(patterns=patterns)
        self.reasoning_agent = ReasoningAgent(patterns=patterns)
        
        llm_config = {
            'backend': config.get('llm_backend', 'ollama'),
            'model_name': config.get('llm_model', 'qwen2.5:3b'),
            'max_tokens': config.get('llm_max_tokens', 2048),
            'temperature': config.get('llm_temperature', 0.7)
        }
        self.summary_agent = SummaryAgent(patterns=patterns, llm_config=llm_config)
        
        # Initialize ComparisonAgent with optional RAG and SOTA services
        self.comparison_agent = ComparisonAgent(
            rag_service=config.get('rag_service'),
            sota_service=config.get('sota_service'),
            patterns=patterns
        )

        # New intelligence pipeline agents
        self.research_gap_agent = ResearchGapAgent(patterns=patterns, llm_config=llm_config)
        self.ablation_agent = AblationParserAgent(patterns=patterns, llm_config=llm_config)
        self.reproducibility_agent = ReproducibilityAgent(patterns=patterns)

        # Register all agents with message bus and experience store
        self.all_agents = [
            self.structure_agent,
            self.entity_agent,
            self.results_agent,
            self.figure_agent,
            self.reasoning_agent,
            self.summary_agent,
            self.comparison_agent,
            self.research_gap_agent,
            self.ablation_agent,
            self.reproducibility_agent,
        ]
        
        for agent in self.all_agents:
            agent.set_message_bus(self.message_bus)
            if self.experience_store:
                agent.set_experience_store(self.experience_store)
        
        # Start message bus
        self.message_bus_task = None
        
        # Execution metrics
        self.execution_metrics = {
            'total_time_ms': 0,
            'agent_times': {},
            'consensus_votes': 0,
            'conflicts_resolved': 0
        }
    
    async def process_paper(self, pdf_path: str) -> Dict[str, Any]:
        """
        Process a research paper using parallel agents.
        
        Args:
            pdf_path: Path to PDF file
        
        Returns:
            Aggregated results from all agents with summary
        """
        start_time = time.time()
        
        # Start message bus background task
        await self.message_bus.start()
        self.message_bus_task = self.message_bus._processor_task
        
        try:
            # Phase 1: Structure extraction (sequential - needed by others)
            logger.info("phase_1_started", phase="structure_extraction")
            structure_result = await self.structure_agent.execute({
                'pdf_path': pdf_path
            })
            
            if 'error' in structure_result or 'sections' not in structure_result:
                raise RuntimeError(
                    f"StructureAgent failed: {structure_result.get('error', 'no sections returned')}"
                )
            sections = structure_result['sections']
            domain = structure_result.get('metadata', {}).get('domain_match', 'general')
            
            # Phase 2: Parallel extraction
            logger.info(
                "phase_2_started",
                phase="parallel_extraction",
                agents=["entity", "results", "figure", "reasoning",
                        "research_gap", "ablation", "reproducibility"],
            )
            parallel_tasks = [
                self.entity_agent.execute({'sections': sections, 'domain': domain}),
                self.results_agent.execute({'sections': sections, 'domain': domain}),
                self.figure_agent.execute({'pdf_path': pdf_path, 'sections': sections}),
                self.reasoning_agent.execute({'sections': sections}),
                self.research_gap_agent.execute({'sections': sections, 'domain': domain}),
                self.ablation_agent.execute({'sections': sections}),
                self.reproducibility_agent.execute({'sections': sections}),
            ]

            # Wait for all parallel tasks
            parallel_results = await asyncio.gather(*parallel_tasks, return_exceptions=True)

            # Unpack results (handle exceptions)
            _agent_names = ['entity', 'results', 'figure', 'reasoning', 'research_gap', 'ablation', 'reproducibility']
            for _i, (_name, _res) in enumerate(zip(_agent_names, parallel_results)):
                if isinstance(_res, Exception):
                    logger.error("parallel_agent_exception", agent=_name, error=str(_res), error_type=type(_res).__name__)
                elif isinstance(_res, dict) and 'error' in _res:
                    logger.warning("parallel_agent_error", agent=_name, error=_res['error'])

            entity_result = parallel_results[0] if not isinstance(parallel_results[0], Exception) else {}
            results_result = parallel_results[1] if not isinstance(parallel_results[1], Exception) else {}
            figure_result = parallel_results[2] if not isinstance(parallel_results[2], Exception) else {}
            reasoning_result = parallel_results[3] if not isinstance(parallel_results[3], Exception) else {}
            gap_result = parallel_results[4] if not isinstance(parallel_results[4], Exception) else {}
            ablation_result = parallel_results[5] if not isinstance(parallel_results[5], Exception) else {}
            repro_result = parallel_results[6] if not isinstance(parallel_results[6], Exception) else {}
            
            # Phase 3: Cross-validation and consensus
            logger.info("phase_3_started", phase="cross_validation")
            await self._cross_validate(
                entity_result, 
                results_result, 
                reasoning_result
            )
            
            # Re-run ResultsAgent with entity context for better validation
            if entity_result.get('entities'):
                logger.info("phase_3b_started", phase="results_reextraction", reason="entity_context_enrichment")
                results_result = await self.results_agent.execute({
                    'sections': sections,
                    'domain': domain,
                    'entities': entity_result['entities']
                })
            
            # Phase 3c: Run ComparisonAgent (after entities and results are available)
            logger.info("phase_3c_started", phase="comparison_analysis")
            comparison_result = await self.comparison_agent.process({
                'entities': entity_result,
                'results': results_result,
                'structure': structure_result,
                'figures': figure_result,
                'reasoning': reasoning_result
            })
            
            # Phase 4: Generate summary
            logger.info("phase_4_started", phase="summary_generation")
            summary_result = await self.summary_agent.execute({
                'sections': sections,
                'domain': domain,
                'entities': entity_result.get('entities', {}),
                'results': results_result.get('results', {}).get('table_results', []) +
                          results_result.get('results', {}).get('inline_results', []),
                'reasoning': reasoning_result.get('reasoning', {}),
                'figures': figure_result.get('figures', []),
                # Real PDF tables (markdown) for the LangGraph results extractor.
                'tables_md': structure_result.get('tables_md', []),
                'metadata': structure_result.get('metadata', {}),
                'comparison': comparison_result  # Add comparison data to summary context
            })
            
            # Aggregate results
            total_time = (time.time() - start_time) * 1000
            
            aggregated = {
                'structure': structure_result,
                'entities': entity_result,
                'results': results_result,
                'figures': figure_result,
                'reasoning': reasoning_result,
                'comparison': comparison_result,
                'summary': summary_result,
                'research_gaps': gap_result,
                'ablation_studies': ablation_result,
                'reproducibility': repro_result,
                'metadata': {
                    'total_time_ms': total_time,
                    'agent_times': self._get_agent_times(),
                    'consensus_votes': self.execution_metrics['consensus_votes'],
                    'conflicts_resolved': self.execution_metrics['conflicts_resolved'],
                    'agent_count': len(self.all_agents),
                    'parallel_speedup': self._calculate_speedup()
                }
            }
            
            return aggregated
        
        finally:
            await self.message_bus.stop()
    
    async def _cross_validate(
        self,
        entity_result: Dict,
        results_result: Dict,
        reasoning_result: Dict
    ):
        """
        Cross-validate results between agents.
        
        Checks:
        - Do entity names in results match extracted entities?
        - Are reasoning claims supported by results?
        - Are there conflicting extractions?
        """
        # Check entity consistency
        extracted_entities = set()
        for entity_type, entities in entity_result.get('entities', {}).items():
            extracted_entities.update([e.lower() for e in entities])
        
        # Check results for unknown entities
        all_results = (results_result.get('results', {}).get('table_results', []) + 
                      results_result.get('results', {}).get('inline_results', []))
        
        for result in all_results:
            dataset = result.get('dataset', '').lower()
            model = result.get('model', '').lower()
            
            if dataset and dataset not in extracted_entities:
                # Flag potential mismatch
                logger.warning("entity_mismatch", type="dataset", value=dataset, location="results")
            
            if model and model not in extracted_entities:
                logger.warning("entity_mismatch", type="model", value=model, location="results")
        
        # Check reasoning claims against results
        claims = reasoning_result.get('reasoning', {}).get('claims', [])
        unsupported = reasoning_result.get('reasoning', {}).get('unsupported_claims', [])
        
        if unsupported:
            logger.warning("unsupported_claims_detected", count=len(unsupported))
            for claim in unsupported[:3]:  # Log only first 3
                logger.debug("unsupported_claim", claim=claim[:100])
    
    def _get_agent_times(self) -> Dict[str, float]:
        """Get average execution time for each agent."""
        times = {}
        for agent in self.all_agents:
            stats = agent.execution_stats
            runs = stats.get('total_runs', 0)
            times[agent.name] = stats.get('total_time_ms', 0) / runs if runs else 0
        return times
    
    def _calculate_speedup(self) -> float:
        """
        Calculate parallel speedup.
        
        Speedup = Sequential time / Parallel time
        
        Sequential time = sum of all agent times
        Parallel time = max of parallel agent times + sequential agent times
        """
        agent_times = self._get_agent_times()
        
        # Sequential agents: StructureAgent
        sequential_time = agent_times.get('StructureAgent', 0)
        
        # Parallel agents: Entity, Results, Figure, Reasoning
        parallel_times = [
            agent_times.get('EntityAgent', 0),
            agent_times.get('ResultsAgent', 0),
            agent_times.get('FigureAgent', 0),
            agent_times.get('ReasoningAgent', 0)
        ]
        parallel_time = max(parallel_times) if parallel_times else 0
        
        # Summary (sequential after parallel)
        summary_time = agent_times.get('SummaryAgent', 0)
        
        total_sequential = sum(agent_times.values())
        total_parallel = sequential_time + parallel_time + summary_time
        
        if total_parallel > 0:
            return total_sequential / total_parallel
        return 1.0
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get orchestrator statistics."""
        return {
            'execution_metrics': self.execution_metrics,
            'agent_times': self._get_agent_times(),
            'speedup': self._calculate_speedup(),
            'message_bus_stats': self.message_bus.get_statistics()
        }
    
    async def cleanup(self):
        """Cleanup resources."""
        if self.message_bus_task:
            self.message_bus_task.cancel()
            try:
                await self.message_bus_task
            except asyncio.CancelledError:
                pass


async def main_demo():
    """Demo of parallel orchestrator."""
    import yaml
    
    # Load config
    config_path = Path(__file__).parent.parent.parent / 'config.example.yaml'
    if config_path.exists():
        with open(config_path) as f:
            config = yaml.safe_load(f)
    else:
        config = {}
    
    # Load patterns
    patterns_path = Path(__file__).parent.parent.parent / 'patterns.json'
    if patterns_path.exists():
        import json
        with open(patterns_path) as f:
            patterns = json.load(f)
    else:
        patterns = {}
    
    # Initialize experience store (optional)
    try:
        from backend.database.config import SUPABASE_URL, SUPABASE_SERVICE_KEY
        experience_store = ExperienceStore(
            supabase_url=SUPABASE_URL,
            supabase_key=SUPABASE_SERVICE_KEY,
            enabled=config.get('experience_enabled', True)
        )
    except:
        logger.warning("experience_store_init_failed", reason="initialization_error")
        experience_store = None
    
    # Create orchestrator
    orchestrator = ParallelAgentOrchestrator(
        patterns=patterns,
        config=config,
        experience_store=experience_store
    )
    
    # Process a paper (example)
    pdf_path = "path/to/paper.pdf"
    
    if Path(pdf_path).exists():
        logger.info("paper_processing_started", pdf_path=str(pdf_path))
        result = await orchestrator.process_paper(pdf_path)
        
        logger.info(
            "paper_processing_completed",
            total_time_ms=result['metadata']['total_time_ms'],
            speedup=result['metadata']['parallel_speedup']
        )
        logger.debug(
            "summary_preview",
            summary_text=result['summary']['summary']['text'][:500]
        )
    else:
        logger.error("pdf_file_not_found", pdf_path=str(pdf_path))
    
    await orchestrator.cleanup()


if __name__ == '__main__':
    asyncio.run(main_demo())
