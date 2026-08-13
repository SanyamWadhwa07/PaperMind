"""Base agent class with async execution, memory integration, and message bus communication.

All specialized agents inherit from BaseAgent to get:
- Async task execution
- Access to experience database
- Inter-agent messaging
- State management
- Confidence scoring
"""

import asyncio
import structlog
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timezone
import time

from core.agents.message_bus import Message, MessageType, MessagePriority
# Note: message_bus and experience_store are set by orchestrator via setters

logger = structlog.get_logger(__name__)


class AgentState:
    """Agent execution state."""
    IDLE = "idle"
    PROCESSING = "processing"
    WAITING = "waiting"
    COMPLETED = "completed"
    ERROR = "error"


class BaseAgent(ABC):
    """
    Base class for all extraction agents.
    
    Provides:
    - Async execution framework
    - Message bus communication
    - Experience database queries
    - Confidence scoring
    - Error handling
    """
    
    def __init__(self, name: str, patterns: Optional[Dict] = None):
        """
        Initialize base agent.
        
        Args:
            name: Unique agent identifier
            patterns: Pattern dictionary from patterns.json
        """
        self.name = name
        self.patterns = patterns or {}
        self.state = AgentState.IDLE
        self.confidence_threshold = 0.5  # Minimum confidence to accept extraction
        
        # Will be set by orchestrator
        self.message_bus = None
        self.experience = None
        
        # Execution tracking
        self.execution_stats = {
            'total_runs': 0,
            'successful_runs': 0,
            'total_time_ms': 0,
            'avg_confidence': 0.0,
            'items_extracted': 0
        }
        
        # Current task context
        self.current_paper_id: Optional[str] = None
        self.current_task: Optional[asyncio.Task] = None
    
    def set_message_bus(self, message_bus):
        """Set the message bus instance (for orchestrator setup)."""
        self.message_bus = message_bus
        if hasattr(message_bus, 'register_agent'):
            message_bus.register_agent(self.name)
    
    def set_experience_store(self, experience_store):
        """Set the experience store instance (for orchestrator setup)."""
        self.experience = experience_store
    
    @abstractmethod
    async def process(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Main processing method - must be implemented by subclass.
        
        Args:
            input_data: Input data for processing (varies by agent)
        
        Returns:
            Dict with:
                - extractions: List of extracted items
                - confidence_scores: Dict mapping item -> confidence
                - metadata: Additional info
        """
        pass
    
    async def execute(self, input_data: Dict[str, Any], 
                     paper_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Execute agent with timing, error handling, and logging.
        
        Args:
            input_data: Input data for processing
            paper_id: Optional paper ID for tracking
        
        Returns:
            Processing results with metadata
        """
        self.state = AgentState.PROCESSING
        self.current_paper_id = paper_id
        start_time = time.time()
        
        try:
            # Run main processing
            result = await self.process(input_data)
            
            # Calculate statistics
            execution_time_ms = int((time.time() - start_time) * 1000)
            items_count = len(result.get('extractions', []))
            avg_confidence = self._calculate_avg_confidence(result)
            
            # Update stats
            self.execution_stats['total_runs'] += 1
            self.execution_stats['successful_runs'] += 1
            self.execution_stats['total_time_ms'] += execution_time_ms
            self.execution_stats['items_extracted'] += items_count
            self.execution_stats['avg_confidence'] = (
                (self.execution_stats['avg_confidence'] * (self.execution_stats['total_runs'] - 1) + avg_confidence)
                / self.execution_stats['total_runs']
            )
            
            # Log to experience database
            if self.experience and self.experience.enabled:
                await self.experience.log_agent_execution(
                    agent_name=self.name,
                    execution_time_ms=execution_time_ms,
                    status='success',
                    items_extracted=items_count,
                    confidence_avg=avg_confidence,
                    paper_id=paper_id
                )
            
            self.state = AgentState.COMPLETED
            
            # Add execution metadata
            result['execution_metadata'] = {
                'agent': self.name,
                'execution_time_ms': execution_time_ms,
                'items_extracted': items_count,
                'avg_confidence': avg_confidence,
                'timestamp': datetime.now(timezone.utc).isoformat()
            }
            
            return result
            
        except Exception as e:
            self.state = AgentState.ERROR
            error_time_ms = int((time.time() - start_time) * 1000)
            
            # Log error
            if self.experience and self.experience.enabled:
                await self.experience.log_agent_execution(
                    agent_name=self.name,
                    execution_time_ms=error_time_ms,
                    status='failed',
                    items_extracted=0,
                    confidence_avg=0.0,
                    error_msg=str(e),
                    paper_id=paper_id
                )
            
            return {
                'extractions': [],
                'confidence_scores': {},
                'error': str(e),
                'execution_metadata': {
                    'agent': self.name,
                    'execution_time_ms': error_time_ms,
                    'status': 'error'
                }
            }
    
    async def query_experience(self, query_type: str, **kwargs) -> Any:
        """
        Query experience database.
        
        Args:
            query_type: Type of query ('entity', 'pattern', 'baseline', etc.)
            **kwargs: Query parameters
        
        Returns:
            Query result or None
        """
        if not self.experience or not self.experience.enabled:
            return None
        
        try:
            if query_type == 'entity':
                return await self.experience.query_entity(
                    kwargs['entity_name'],
                    kwargs['entity_type']
                )
            elif query_type == 'high_confidence_entities':
                return await self.experience.get_high_confidence_entities(
                    kwargs['entity_type'],
                    kwargs.get('min_confidence', 0.8)
                )
            elif query_type == 'pattern_performance':
                return await self.experience.get_pattern_performance(
                    kwargs['pattern_id'],
                    kwargs['pattern_type']
                )
            elif query_type == 'result_baseline':
                return await self.experience.get_result_baseline(
                    kwargs['dataset'],
                    kwargs['metric'],
                    kwargs.get('model')
                )
            elif query_type == 'outlier':
                # Returns (is_outlier, reason) — callers must unpack, since a
                # two-tuple is truthy even when the answer is "not an outlier".
                return await self.experience.is_outlier(
                    kwargs['dataset'],
                    kwargs['metric'],
                    kwargs['value'],
                    kwargs.get('model')
                )
            elif query_type == 'related_entities':
                return await self.experience.get_related_entities(
                    kwargs['entity_name'],
                    kwargs['entity_type'],
                    kwargs.get('relationship_type')
                )
            else:
                return None
        except Exception as e:
            logger.exception("experience_query_failed", agent=self.name, query_type=query_type, error=str(e))
            return None
    
    async def update_experience(self, update_type: str, **kwargs) -> bool:
        """
        Update experience database with new learnings.
        
        Args:
            update_type: Type of update ('entity', 'pattern', 'baseline', etc.)
            **kwargs: Update parameters
        
        Returns:
            Success status
        """
        if not self.experience or not self.experience.enabled:
            return False
        
        try:
            if update_type == 'entity':
                return await self.experience.update_entity_knowledge(
                    kwargs['entity_name'],
                    kwargs['entity_type'],
                    # Optional so that a caller with nothing better to say still
                    # records the occurrence. Experience is a background signal:
                    # losing a nuance is acceptable, losing the write is not.
                    kwargs.get('confidence', 0.6),
                    kwargs.get('context', ''),
                    self.name
                )
            elif update_type == 'pattern':
                return await self.experience.update_pattern_performance(
                    kwargs['pattern_id'],
                    kwargs['pattern_type'],
                    kwargs['success'],
                    kwargs.get('domain', 'general')
                )
            elif update_type in ('baseline', 'result'):
                return await self.experience.update_result_baseline(
                    kwargs['dataset'],
                    kwargs['metric'],
                    kwargs['value'],
                    kwargs.get('model')
                )
            elif update_type == 'relationship':
                return await self.experience.update_entity_relationship(
                    kwargs['entity_1'],
                    kwargs['type_1'],
                    kwargs['entity_2'],
                    kwargs['type_2'],
                    kwargs['relationship'],
                    kwargs.get('confidence', 0.7)
                )
            else:
                return False
        except Exception as e:
            logger.exception("experience_update_failed", agent=self.name, update_type=update_type, error=str(e))
            return False
    
    async def ask_agent(self, recipient: str, question: str, 
                       context: Optional[Dict] = None, timeout: float = 3.0) -> Optional[Dict]:
        """
        Send a question to another agent and wait for response.
        
        Args:
            recipient: Name of agent to ask
            question: Question to ask
            context: Optional context data
            timeout: Response timeout
        
        Returns:
            Response payload or None
        """
        payload = {
            'question': question,
            'context': context or {},
            'sender': self.name
        }
        
        return await self.message_bus.request(
            sender=self.name,
            recipient=recipient,
            payload=payload,
            timeout=timeout
        )
    
    async def broadcast_finding(self, finding_type: str, data: Dict[str, Any]):
        """
        Broadcast a finding to all agents.
        
        Args:
            finding_type: Type of finding ('entity', 'result', 'claim', etc.)
            data: Finding data
        """
        await self.message_bus.announce_consensus(
            sender=self.name,
            payload={
                'finding_type': finding_type,
                'data': data,
                'agent': self.name,
                'confidence': data.get('confidence', 0.0)
            }
        )
    
    async def request_validation(self, item: str, item_type: str, 
                                 context: str, confidence: float) -> Tuple[bool, float]:
        """
        Request validation from other agents via consensus.
        
        Args:
            item: Item to validate
            item_type: Type of item
            context: Context where item was found
            confidence: Current confidence score
        
        Returns:
            (is_valid, adjusted_confidence)
        """
        # First check experience database
        known_entity = await self.query_experience(
            'entity',
            entity_name=item,
            entity_type=item_type
        )
        
        if known_entity and known_entity['confidence_score'] >= 0.8:
            # High confidence from experience - validate immediately
            return True, max(confidence, known_entity['confidence_score'])
        
        # If low confidence, ask another agent
        if confidence < self.confidence_threshold:
            # Ask ReasoningAgent to validate via context
            validation = await self.ask_agent(
                'ReasoningAgent',
                f"Is '{item}' a valid {item_type}?",
                {'item': item, 'context': context, 'current_confidence': confidence}
            )
            
            if validation:
                return validation.get('is_valid', False), validation.get('confidence', confidence)
        
        return confidence >= self.confidence_threshold, confidence
    
    def _calculate_avg_confidence(self, result: Dict[str, Any]) -> float:
        """Calculate average confidence from result."""
        scores = result.get('confidence_scores', {})
        if not scores:
            return 0.0
        return sum(scores.values()) / len(scores)
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get agent execution statistics."""
        stats = self.execution_stats.copy()
        if stats['total_runs'] > 0:
            stats['avg_time_ms'] = stats['total_time_ms'] / stats['total_runs']
            stats['success_rate'] = stats['successful_runs'] / stats['total_runs']
        else:
            stats['avg_time_ms'] = 0
            stats['success_rate'] = 0.0
        
        stats['current_state'] = self.state
        return stats
    
    async def listen_for_messages(self, timeout: float = 0.1) -> Optional[Message]:
        """Check for incoming messages."""
        return await self.message_bus.get_next_message(self.name, timeout)
    
    async def handle_message(self, message: Message):
        """
        Handle incoming message - can be overridden by subclasses.
        
        Default behavior: respond with agent capabilities.
        """
        if message.msg_type == MessageType.REQUEST:
            # Default response
            response = {
                'agent': self.name,
                'capabilities': self.get_capabilities(),
                'status': self.state
            }
            await self.message_bus.respond(
                original_msg_id=message.msg_id,
                sender=self.name,
                recipient=message.sender,
                payload=response
            )
    
    @abstractmethod
    def get_capabilities(self) -> List[str]:
        """Return list of agent capabilities - must be implemented by subclass."""
        pass
    
    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name='{self.name}', state='{self.state}')"
