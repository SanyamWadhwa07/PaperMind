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
            'max_tokens': config.get('llm_max_tokens', 512),
            'temperature': config.get('llm_temperature', 0.7)
        }
        self.summary_agent = SummaryAgent(patterns=patterns, llm_config=llm_config)
        
        # Register all agents with message bus and experience store
        self.all_agents = [
            self.structure_agent,
            self.entity_agent,
            self.results_agent,
            self.figure_agent,
            self.reasoning_agent,
            self.summary_agent
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
        self.message_bus_task = asyncio.create_task(self.message_bus._process_messages())
        
        try:
            # Phase 1: Structure extraction (sequential - needed by others)
            print("Phase 1: Extracting structure...")
            structure_result = await self.structure_agent.execute({
                'pdf_path': pdf_path
            })
            
            sections = structure_result['sections']
            domain = structure_result['metadata']['domain_match']
            
            # Phase 2: Parallel extraction
            print("Phase 2: Parallel extraction (entities, results, figures, reasoning)...")
            parallel_tasks = [
                self.entity_agent.execute({
                    'sections': sections,
                    'domain': domain
                }),
                self.results_agent.execute({
                    'sections': sections,
                    'domain': domain
                }),
                self.figure_agent.execute({
                    'pdf_path': pdf_path,
                    'sections': sections
                }),
                self.reasoning_agent.execute({
                    'sections': sections
                })
            ]
            
            # Wait for all parallel tasks
            parallel_results = await asyncio.gather(*parallel_tasks, return_exceptions=True)
            
            # Unpack results (handle exceptions)
            entity_result = parallel_results[0] if not isinstance(parallel_results[0], Exception) else {}
            results_result = parallel_results[1] if not isinstance(parallel_results[1], Exception) else {}
            figure_result = parallel_results[2] if not isinstance(parallel_results[2], Exception) else {}
            reasoning_result = parallel_results[3] if not isinstance(parallel_results[3], Exception) else {}
            
            # Phase 3: Cross-validation and consensus
            print("Phase 3: Cross-validation...")
            await self._cross_validate(
                entity_result, 
                results_result, 
                reasoning_result
            )
            
            # Re-run ResultsAgent with entity context for better validation
            if entity_result.get('entities'):
                print("Phase 3b: Re-running results extraction with entity context...")
                results_result = await self.results_agent.execute({
                    'sections': sections,
                    'domain': domain,
                    'entities': entity_result['entities']
                })
            
            # Phase 4: Generate summary
            print("Phase 4: Generating summary...")
            summary_result = await self.summary_agent.execute({
                'sections': sections,
                'entities': entity_result.get('entities', {}),
                'results': results_result.get('results', {}).get('table_results', []) + 
                          results_result.get('results', {}).get('inline_results', []),
                'reasoning': reasoning_result.get('reasoning', {}),
                'figures': figure_result.get('figures', []),
                'metadata': structure_result.get('metadata', {})
            })
            
            # Aggregate results
            total_time = (time.time() - start_time) * 1000
            
            aggregated = {
                'structure': structure_result,
                'entities': entity_result,
                'results': results_result,
                'figures': figure_result,
                'reasoning': reasoning_result,
                'summary': summary_result,
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
            # Stop message bus
            if self.message_bus_task:
                self.message_bus_task.cancel()
                try:
                    await self.message_bus_task
                except asyncio.CancelledError:
                    pass
    
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
                print(f"  Warning: Dataset '{dataset}' in results not found in entities")
            
            if model and model not in extracted_entities:
                print(f"  Warning: Model '{model}' in results not found in entities")
        
        # Check reasoning claims against results
        claims = reasoning_result.get('reasoning', {}).get('claims', [])
        unsupported = reasoning_result.get('reasoning', {}).get('unsupported_claims', [])
        
        if unsupported:
            print(f"  Warning: {len(unsupported)} unsupported claims detected")
            for claim in unsupported[:3]:  # Show first 3
                print(f"    - {claim[:100]}...")
    
    def _get_agent_times(self) -> Dict[str, float]:
        """Get execution time for each agent."""
        return {
            agent.name: agent.execution_stats.get('avg_time_ms', 0)
            for agent in self.all_agents
        }
    
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
        print("Warning: Could not initialize experience store")
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
        print(f"Processing: {pdf_path}")
        result = await orchestrator.process_paper(pdf_path)
        
        print("\n=== RESULTS ===")
        print(f"Total time: {result['metadata']['total_time_ms']:.2f}ms")
        print(f"Speedup: {result['metadata']['parallel_speedup']:.2f}x")
        print(f"\nSummary:\n{result['summary']['summary']['text'][:500]}...")
    else:
        print(f"PDF not found: {pdf_path}")
    
    await orchestrator.cleanup()


if __name__ == '__main__':
    asyncio.run(main_demo())
