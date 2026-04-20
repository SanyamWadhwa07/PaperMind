"""Agent message bus for inter-agent communication with priority queuing.

Enables asynchronous message passing between agents with support for:
- Priority-based message routing
- Request-response patterns
- Conflict resolution via voting
- Consensus building
- Timeout handling
- Cycle detection
"""

import asyncio
import structlog
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List, Set
from enum import Enum
from datetime import datetime
import uuid

logger = structlog.get_logger(__name__)


class MessageType(Enum):
    """Types of messages agents can exchange."""
    REQUEST = "request"           # Agent asks another agent for information
    RESPONSE = "response"          # Reply to a request
    CONFLICT = "conflict"          # Signal disagreement between agents
    CONSENSUS = "consensus"        # Result of voting/agreement
    STATUS = "status"              # Agent status update
    ERROR = "error"                # Error notification


class MessagePriority(Enum):
    """Message priority levels for queue ordering."""
    HIGH = 1      # Conflicts, critical errors
    MEDIUM = 2    # Requests, responses
    LOW = 3       # Status updates


@dataclass(order=True)
class Message:
    """Message passed between agents."""
    priority: int = field(compare=True)
    msg_type: MessageType = field(compare=False)
    sender: str = field(compare=False)
    recipient: str = field(compare=False)
    payload: Dict[str, Any] = field(compare=False)
    msg_id: str = field(default_factory=lambda: str(uuid.uuid4()), compare=False)
    timestamp: datetime = field(default_factory=datetime.utcnow, compare=False)
    reply_to: Optional[str] = field(default=None, compare=False)
    timeout_seconds: float = field(default=3.0, compare=False)
    
    def __post_init__(self):
        """Convert MessageType and MessagePriority enums if needed."""
        if isinstance(self.msg_type, str):
            self.msg_type = MessageType(self.msg_type)


class AgentMessageBus:
    """
    Centralized message bus for agent communication.
    
    Features:
    - Priority queue for message ordering
    - Request-response tracking
    - Timeout handling
    - Conversation history (for cycle detection)
    - Message batching support
    """
    
    def __init__(self, max_queue_size: int = 1000):
        self.queue: asyncio.PriorityQueue = asyncio.PriorityQueue(maxsize=max_queue_size)
        self.pending_requests: Dict[str, asyncio.Future] = {}  # msg_id -> Future
        self.conversation_graph: Dict[str, Set[str]] = {}  # sender -> {recipients}
        self.message_history: List[Message] = []
        self.max_history = 1000
        self._running = False
        self._processor_task: Optional[asyncio.Task] = None
        
        # Agent mailboxes (for targeted delivery)
        self.mailboxes: Dict[str, asyncio.Queue] = {}
        
        # Statistics
        self.stats = {
            'total_messages': 0,
            'requests': 0,
            'responses': 0,
            'conflicts': 0,
            'timeouts': 0,
            'cycles_detected': 0
        }
    
    def register_agent(self, agent_name: str):
        """Register an agent and create its mailbox."""
        if agent_name not in self.mailboxes:
            self.mailboxes[agent_name] = asyncio.Queue()
            self.conversation_graph[agent_name] = set()
    
    async def send_message(self, message: Message) -> Optional[str]:
        """
        Send a message to the bus.
        
        Returns:
            Message ID for tracking
        """
        if not self._running:
            raise RuntimeError("Message bus not started. Call start() first.")
        
        # Check for conversation cycles
        if self._would_create_cycle(message.sender, message.recipient):
            self.stats['cycles_detected'] += 1
            # Break cycle by using cached response if available
            cached = self._get_cached_response(message.sender, message.recipient, message.payload)
            if cached:
                return cached
        
        # Update conversation graph
        self.conversation_graph[message.sender].add(message.recipient)
        
        # Add to global queue
        await self.queue.put(message)
        
        # Track statistics
        self.stats['total_messages'] += 1
        if message.msg_type == MessageType.REQUEST:
            self.stats['requests'] += 1
        elif message.msg_type == MessageType.RESPONSE:
            self.stats['responses'] += 1
        elif message.msg_type == MessageType.CONFLICT:
            self.stats['conflicts'] += 1
        
        return message.msg_id
    
    async def request(self, sender: str, recipient: str, payload: Dict[str, Any],
                     timeout: float = 3.0) -> Optional[Dict[str, Any]]:
        """
        Send a request and wait for response.
        
        Returns:
            Response payload or None if timeout
        """
        message = Message(
            priority=MessagePriority.MEDIUM.value,
            msg_type=MessageType.REQUEST,
            sender=sender,
            recipient=recipient,
            payload=payload,
            timeout_seconds=timeout
        )
        
        # Create future for response
        response_future = asyncio.Future()
        self.pending_requests[message.msg_id] = response_future
        
        # Send message
        await self.send_message(message)
        
        # Wait for response with timeout
        try:
            response = await asyncio.wait_for(response_future, timeout=timeout)
            return response
        except asyncio.TimeoutError:
            self.stats['timeouts'] += 1
            del self.pending_requests[message.msg_id]
            return None
    
    async def respond(self, original_msg_id: str, sender: str, 
                     recipient: str, payload: Dict[str, Any]):
        """Send a response to a previous request."""
        message = Message(
            priority=MessagePriority.MEDIUM.value,
            msg_type=MessageType.RESPONSE,
            sender=sender,
            recipient=recipient,
            payload=payload,
            reply_to=original_msg_id
        )
        
        await self.send_message(message)
    
    async def raise_conflict(self, sender: str, payload: Dict[str, Any]):
        """Raise a conflict for multi-agent resolution."""
        message = Message(
            priority=MessagePriority.HIGH.value,
            msg_type=MessageType.CONFLICT,
            sender=sender,
            recipient="orchestrator",  # Conflicts go to orchestrator
            payload=payload
        )
        
        await self.send_message(message)
    
    async def announce_consensus(self, sender: str, payload: Dict[str, Any]):
        """Broadcast consensus decision."""
        message = Message(
            priority=MessagePriority.HIGH.value,
            msg_type=MessageType.CONSENSUS,
            sender=sender,
            recipient="broadcast",
            payload=payload
        )
        
        await self.send_message(message)
    
    async def get_next_message(self, agent_name: str, timeout: float = 0.1) -> Optional[Message]:
        """
        Get next message for a specific agent.
        
        Args:
            agent_name: Name of the agent
            timeout: How long to wait for message
        
        Returns:
            Message or None if timeout
        """
        if agent_name not in self.mailboxes:
            self.register_agent(agent_name)
        
        try:
            message = await asyncio.wait_for(
                self.mailboxes[agent_name].get(),
                timeout=timeout
            )
            return message
        except asyncio.TimeoutError:
            return None
    
    async def _process_messages(self):
        """Background task to route messages to agent mailboxes."""
        while self._running:
            try:
                # Get message from global queue
                message = await asyncio.wait_for(self.queue.get(), timeout=0.1)
                
                # Add to history
                self.message_history.append(message)
                if len(self.message_history) > self.max_history:
                    self.message_history.pop(0)
                
                # Handle responses
                if message.msg_type == MessageType.RESPONSE and message.reply_to:
                    if message.reply_to in self.pending_requests:
                        future = self.pending_requests.pop(message.reply_to)
                        if not future.done():
                            future.set_result(message.payload)
                        continue
                
                # Route to recipient's mailbox
                if message.recipient == "broadcast":
                    # Broadcast to all agents
                    for mailbox in self.mailboxes.values():
                        await mailbox.put(message)
                elif message.recipient in self.mailboxes:
                    await self.mailboxes[message.recipient].put(message)
                else:
                    # Unknown recipient - log and discard
                    pass
                
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.exception("message_processing_error", error=str(e))
    
    def _would_create_cycle(self, sender: str, recipient: str) -> bool:
        """
        Check if sending message would create a conversation cycle.
        
        Uses DFS to detect cycles in conversation graph.
        """
        if sender not in self.conversation_graph:
            return False
        
        visited = set()
        stack = [sender]
        
        while stack:
            current = stack.pop()
            if current == recipient:
                return True
            
            if current in visited:
                continue
            visited.add(current)
            
            if current in self.conversation_graph:
                stack.extend(self.conversation_graph[current])
        
        return False
    
    def _get_cached_response(self, sender: str, recipient: str, 
                            payload: Dict[str, Any]) -> Optional[str]:
        """Get cached response to break cycle."""
        # Look for similar past conversation
        for msg in reversed(self.message_history[-100:]):
            if (msg.sender == sender and 
                msg.recipient == recipient and
                msg.msg_type == MessageType.REQUEST):
                # Find response
                for resp in self.message_history:
                    if (resp.reply_to == msg.msg_id and 
                        resp.msg_type == MessageType.RESPONSE):
                        return resp.msg_id
        return None
    
    async def batch_requests(self, sender: str, 
                           requests: List[Dict[str, Any]],
                           timeout: float = 5.0) -> List[Optional[Dict[str, Any]]]:
        """
        Send multiple requests in parallel and collect responses.
        
        Args:
            sender: Requesting agent name
            requests: List of dicts with 'recipient' and 'payload'
            timeout: Total timeout for all requests
        
        Returns:
            List of responses (None for timeouts)
        """
        tasks = []
        for req in requests:
            task = self.request(
                sender=sender,
                recipient=req['recipient'],
                payload=req['payload'],
                timeout=timeout
            )
            tasks.append(task)
        
        responses = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Convert exceptions to None
        return [r if not isinstance(r, Exception) else None for r in responses]
    
    def get_conversation_history(self, agent_name: str, limit: int = 50) -> List[Message]:
        """Get recent conversation history for an agent."""
        history = [
            msg for msg in self.message_history
            if msg.sender == agent_name or msg.recipient == agent_name
        ]
        return history[-limit:]
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get message bus statistics."""
        return {
            **self.stats,
            'queue_size': self.queue.qsize(),
            'pending_requests': len(self.pending_requests),
            'registered_agents': len(self.mailboxes),
            'history_size': len(self.message_history)
        }
    
    async def start(self):
        """Start the message bus processor."""
        if self._running:
            return
        
        self._running = True
        self._processor_task = asyncio.create_task(self._process_messages())
    
    async def stop(self):
        """Stop the message bus processor."""
        self._running = False
        if self._processor_task:
            self._processor_task.cancel()
            try:
                await self._processor_task
            except asyncio.CancelledError:
                pass
    
    def clear_history(self):
        """Clear conversation history and reset conversation graph."""
        self.message_history.clear()
        self.conversation_graph = {name: set() for name in self.conversation_graph}


# Singleton instance
_message_bus: Optional[AgentMessageBus] = None


def get_message_bus() -> AgentMessageBus:
    """Get global message bus instance."""
    global _message_bus
    if _message_bus is None:
        _message_bus = AgentMessageBus()
    return _message_bus
