"""Experience database using Supabase PostgreSQL for cross-paper learning.

This module provides async access to the agent experience database,
enabling agents to query historical knowledge and update their learnings.
"""

import asyncio
import structlog
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timezone
from pathlib import Path
import sys

# Add backend to path for imports
sys.path.append(str(Path(__file__).parent.parent.parent / 'backend'))

logger = structlog.get_logger(__name__)

try:
    from supabase import create_client, Client
    from backend.database.config import SUPABASE_URL, SUPABASE_SERVICE_KEY
    SUPABASE_AVAILABLE = True
except ImportError:
    SUPABASE_AVAILABLE = False
    logger.warning("supabase_unavailable", reason="import_error")


# Events already reported as a missing schema object, so the same absent table,
# view or function is described once rather than on every call.
_reported_schema_gaps: set = set()


def _log_store_failure(event: str, error: Any, **fields) -> None:
    """Log a failed experience-store call at a severity that matches its cause.

    A missing table, view or function is a provisioning gap: it is not going to
    resolve itself, every subsequent call fails identically, and a stack trace
    says nothing the message does not. Emitting `logger.exception` for it
    produced one full traceback *per extracted metric* — hundreds per paper —
    which buried the real errors this module also has to report.

    Anything else keeps its traceback, because anything else might be a bug.
    """
    detail = str(error)
    # PGRST202/PGRST205: PostgREST could not find the function/table. The
    # string check backs it up for drivers that do not surface the code.
    is_schema_gap = (
        "PGRST202" in detail or "PGRST205" in detail or "schema cache" in detail
    )

    if not is_schema_gap:
        logger.exception(event, error=detail, **fields)
        return

    if event in _reported_schema_gaps:
        return
    _reported_schema_gaps.add(event)
    logger.warning(
        event,
        error=detail,
        reason="missing_schema_object",
        fix="Run backend/database/migrations/ in filename order "
            "(010_missing_experience_functions.sql adds the experience RPCs). "
            "Cross-paper learning is disabled until then; nothing else is affected.",
        **fields,
    )


class ExperienceStore:
    """
    Manages agent experience data in Supabase PostgreSQL.
    
    Provides methods for:
    - Querying entity knowledge (validated entities with confidence scores)
    - Tracking pattern performance (regex success rates)
    - Retrieving section templates (common paper structures)
    - Checking result baselines (expected metric ranges)
    - Logging agent execution metrics
    - Recording consensus decisions
    """
    
    def __init__(self, supabase_url: str = None, supabase_key: str = None):
        """Initialize connection to Supabase experience database."""
        if not SUPABASE_AVAILABLE:
            self.client = None
            self.enabled = False
            return
        
        self.url = supabase_url or SUPABASE_URL
        self.key = supabase_key or SUPABASE_SERVICE_KEY
        
        if not self.url or not self.key:
            logger.warning("supabase_credentials_not_configured", reason="missing_credentials")
            self.client = None
            self.enabled = False
        else:
            self.client: Client = create_client(self.url, self.key)
            self.enabled = True
    
    # ==================== Entity Knowledge ====================
    
    async def query_entity(self, entity_name: str, entity_type: str) -> Optional[Dict]:
        """
        Query if an entity is known and validated.
        
        Returns:
            Dict with: entity_name, frequency_count, confidence_score, typical_contexts
            None if entity not found or confidence < 0.5
        """
        if not self.enabled:
            return None
        
        try:
            response = self.client.table('entity_knowledge')\
                .select('*')\
                .eq('entity_name', entity_name)\
                .eq('entity_type', entity_type)\
                .gte('confidence_score', 0.5)\
                .execute()
            
            if response.data:
                return response.data[0]
            return None
        except Exception as e:
            _log_store_failure("entity_query_failed", entity_name=entity_name, entity_type=entity_type, error=str(e))
            return None
    
    async def get_high_confidence_entities(self, entity_type: str, min_confidence: float = 0.8) -> List[str]:
        """Get list of highly validated entities of a type."""
        if not self.enabled:
            return []
        
        try:
            response = self.client.table('entity_knowledge')\
                .select('entity_name')\
                .eq('entity_type', entity_type)\
                .gte('confidence_score', min_confidence)\
                .gte('frequency_count', 5)\
                .order('confidence_score', desc=True)\
                .execute()
            
            return [row['entity_name'] for row in response.data]
        except Exception as e:
            _log_store_failure("high_confidence_entities_query_failed", entity_type=entity_type, error=str(e))
            return []
    
    async def update_entity_knowledge(self, entity_name: str, entity_type: str, 
                                     confidence: float, context: str, 
                                     validating_agent: str) -> bool:
        """Update entity knowledge with new occurrence."""
        if not self.enabled:
            return False
        
        try:
            # Use the PostgreSQL function we defined
            self.client.rpc('update_entity_knowledge', {
                'p_entity_name': entity_name,
                'p_entity_type': entity_type,
                'p_confidence': confidence,
                'p_context': context,
                'p_validating_agent': validating_agent
            }).execute()
            return True
        except Exception as e:
            _log_store_failure("entity_knowledge_update_failed", entity_name=entity_name, entity_type=entity_type, error=str(e))
            return False
    
    # ==================== Pattern Performance ====================
    
    async def get_pattern_performance(self, pattern_id: str, pattern_type: str) -> Optional[Dict]:
        """Get performance metrics for a pattern."""
        if not self.enabled:
            return None
        
        try:
            response = self.client.table('pattern_performance')\
                .select('*')\
                .eq('pattern_id', pattern_id)\
                .eq('pattern_type', pattern_type)\
                .execute()
            
            if response.data:
                return response.data[0]
            return None
        except Exception as e:
            _log_store_failure("pattern_performance_query_failed", pattern_id=pattern_id, pattern_type=pattern_type, error=str(e))
            return None
    
    async def get_best_patterns(self, pattern_type: str, limit: int = 10) -> List[Dict]:
        """Get top-performing patterns of a type."""
        if not self.enabled:
            return []
        
        try:
            response = self.client.table('pattern_performance')\
                .select('*')\
                .eq('pattern_type', pattern_type)\
                .gte('total_attempts', 10)\
                .order('precision_score', desc=True)\
                .limit(limit)\
                .execute()
            
            return response.data
        except Exception as e:
            _log_store_failure("best_patterns_query_failed", pattern_type=pattern_type, error=str(e))
            return []
    
    async def update_pattern_performance(self, pattern_id: str, pattern_type: str,
                                        success: bool, domain: str = 'general') -> bool:
        """Update pattern performance metrics."""
        if not self.enabled:
            return False
        
        try:
            self.client.rpc('update_pattern_performance', {
                'p_pattern_id': pattern_id,
                'p_pattern_type': pattern_type,
                'p_success': success,
                'p_domain': domain
            }).execute()
            return True
        except Exception as e:
            _log_store_failure("pattern_performance_update_failed", pattern_id=pattern_id, pattern_type=pattern_type, error=str(e))
            return False
    
    # ==================== Section Templates ====================
    
    async def get_section_template(self, domain: str = 'general') -> Optional[Dict]:
        """Get most common section structure for a domain."""
        if not self.enabled:
            return None
        
        try:
            response = self.client.table('section_templates')\
                .select('*')\
                .eq('domain', domain)\
                .order('frequency_count', desc=True)\
                .limit(1)\
                .execute()
            
            if response.data:
                return response.data[0]
            return None
        except Exception as e:
            _log_store_failure("section_template_query_failed", domain=domain, error=str(e))
            return None
    
    # ==================== Result Baselines ====================
    
    async def get_result_baseline(self, dataset: str, metric: str, 
                                  model: Optional[str] = None) -> Optional[Dict]:
        """Get expected range for a metric on a dataset."""
        if not self.enabled:
            return None
        
        try:
            query = self.client.table('result_baselines')\
                .select('*')\
                .eq('dataset_name', dataset)\
                .eq('metric_name', metric)\
                .gte('sample_count', 3)
            
            if model:
                query = query.eq('model_name', model)
            else:
                query = query.is_('model_name', 'null')
            
            response = query.execute()
            
            if response.data:
                return response.data[0]
            return None
        except Exception as e:
            _log_store_failure("result_baseline_query_failed", dataset=dataset, metric=metric, error=str(e))
            return None
    
    async def is_outlier(self, dataset: str, metric: str, value: float, 
                        model: Optional[str] = None) -> Tuple[bool, Optional[str]]:
        """
        Check if a result value is an outlier.
        
        Returns:
            (is_outlier, reason) where reason is 'too_low', 'too_high', or None
        """
        baseline = await self.get_result_baseline(dataset, metric, model)
        if not baseline:
            return False, None
        
        if value < baseline['outlier_threshold_low']:
            return True, 'too_low'
        elif value > baseline['outlier_threshold_high']:
            return True, 'too_high'
        return False, None
    
    async def update_result_baseline(self, dataset: str, metric: str, 
                                    value: float, model: Optional[str] = None) -> bool:
        """Update result baseline with new data point."""
        if not self.enabled:
            return False
        
        try:
            self.client.rpc('update_result_baseline', {
                'p_dataset': dataset,
                'p_metric': metric,
                'p_model': model,
                'p_value': value
            }).execute()
            return True
        except Exception as e:
            _log_store_failure("result_baseline_update_failed", dataset=dataset, metric=metric, error=str(e))
            return False
    
    # ==================== Entity Relationships ====================
    
    async def get_related_entities(self, entity_name: str, entity_type: str, 
                                   relationship_type: Optional[str] = None) -> List[Dict]:
        """Get entities commonly associated with given entity."""
        if not self.enabled:
            return []
        
        try:
            query = self.client.table('entity_relationships')\
                .select('*')\
                .eq('entity_1', entity_name)\
                .eq('entity_1_type', entity_type)\
                .gte('frequency_count', 3)\
                .gte('confidence_score', 0.6)
            
            if relationship_type:
                query = query.eq('relationship_type', relationship_type)
            
            response = query.order('frequency_count', desc=True).execute()
            return response.data
        except Exception as e:
            _log_store_failure("related_entities_query_failed", entity_name=entity_name, entity_type=entity_type, error=str(e))
            return []
    
    async def update_entity_relationship(self, entity_1: str, type_1: str,
                                        entity_2: str, type_2: str,
                                        relationship: str, confidence: float = 0.7) -> bool:
        """Record or update entity relationship."""
        if not self.enabled:
            return False
        
        try:
            # Check if relationship exists
            existing = self.client.table('entity_relationships')\
                .select('id, frequency_count, confidence_score')\
                .eq('entity_1', entity_1)\
                .eq('entity_1_type', type_1)\
                .eq('entity_2', entity_2)\
                .eq('entity_2_type', type_2)\
                .eq('relationship_type', relationship)\
                .execute()
            
            if existing.data:
                # Update existing
                current = existing.data[0]
                new_freq = current['frequency_count'] + 1
                new_conf = (current['confidence_score'] * current['frequency_count'] + confidence) / new_freq
                
                self.client.table('entity_relationships')\
                    .update({
                        'frequency_count': new_freq,
                        'confidence_score': new_conf,
                        'last_seen': datetime.now(timezone.utc).isoformat()
                    })\
                    .eq('id', current['id'])\
                    .execute()
            else:
                # Insert new
                self.client.table('entity_relationships')\
                    .insert({
                        'entity_1': entity_1,
                        'entity_1_type': type_1,
                        'entity_2': entity_2,
                        'entity_2_type': type_2,
                        'relationship_type': relationship,
                        'frequency_count': 1,
                        'confidence_score': confidence
                    })\
                    .execute()
            
            return True
        except Exception as e:
            _log_store_failure("entity_relationship_update_failed", entity_1=entity_1, entity_2=entity_2, error=str(e))
            return False
    
    # ==================== Agent Logging ====================
    
    async def log_agent_execution(self, agent_name: str, execution_time_ms: int,
                                  status: str, items_extracted: int, 
                                  confidence_avg: float, error_msg: Optional[str] = None,
                                  paper_id: Optional[str] = None) -> bool:
        """Log agent execution metrics."""
        if not self.enabled:
            return False
        
        try:
            self.client.table('agent_execution_log')\
                .insert({
                    'agent_name': agent_name,
                    'execution_time_ms': execution_time_ms,
                    'status': status,
                    'items_extracted': items_extracted,
                    'confidence_avg': confidence_avg,
                    'error_message': error_msg,
                    'paper_id': paper_id
                })\
                .execute()
            return True
        except Exception as e:
            _log_store_failure("agent_execution_logging_failed", agent_name=agent_name, error=str(e))
            return False
    
    async def log_consensus(self, extraction_type: str, extracted_value: str,
                           agents_voting: Dict[str, str], consensus_reached: bool,
                           final_confidence: float, paper_id: Optional[str] = None) -> bool:
        """Log multi-agent consensus decision."""
        if not self.enabled:
            return False
        
        try:
            self.client.table('agent_consensus_history')\
                .insert({
                    'extraction_type': extraction_type,
                    'extracted_value': extracted_value,
                    'agents_voting': agents_voting,
                    'consensus_reached': consensus_reached,
                    'final_confidence': final_confidence,
                    'paper_id': paper_id
                })\
                .execute()
            return True
        except Exception as e:
            _log_store_failure("consensus_logging_failed", extraction_type=extraction_type, error=str(e))
            return False
    
    async def get_agent_performance(self, agent_name: Optional[str] = None) -> List[Dict]:
        """Get agent performance metrics."""
        if not self.enabled:
            return []
        
        try:
            if agent_name:
                response = self.client.table('agent_performance_metrics')\
                    .select('*')\
                    .eq('agent_name', agent_name)\
                    .execute()
            else:
                response = self.client.table('agent_performance_metrics')\
                    .select('*')\
                    .execute()
            
            return response.data
        except Exception as e:
            _log_store_failure("agent_performance_query_failed", agent_name=agent_name, error=str(e))
            return []


# Singleton instance
_experience_store: Optional[ExperienceStore] = None


def get_experience_store() -> ExperienceStore:
    """Get global experience store instance."""
    global _experience_store
    if _experience_store is None:
        _experience_store = ExperienceStore()
    return _experience_store
