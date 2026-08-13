"""EntityAgent - Extracts entities with experience-based validation.

Wraps existing EnhancedEntityExtractor with agent capabilities:
- Pattern-based extraction with confidence tracking
- Experience DB validation for known entities
- Cross-agent entity verification
"""

import re
import sys
from pathlib import Path
from typing import Dict, List, Any, Optional, Set, Tuple

# Add parent directory to path for imports
sys.path.append(str(Path(__file__).parent.parent.parent))

from core.agents.base_agent import BaseAgent, AgentState
from backend.main import EnhancedEntityExtractor


class EntityAgent(BaseAgent):
    """
    Agent responsible for entity extraction and validation.
    
    Capabilities:
    - Extract datasets, models, metrics, tasks from text
    - Validate entities against experience database
    - Flag unknown entities for review
    - Learn new entities from validated papers
    """
    
    def __init__(self, patterns: Optional[Dict] = None):
        super().__init__(name="EntityAgent", patterns=patterns)
        self.entity_extractor = EnhancedEntityExtractor()
        self.extracted_entities: Dict[str, List[str]] = {}
        self.uncertain_entities: Set[str] = set()
    
    async def process(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract entities from sections.
        
        Args:
            input_data: {
                'sections': Dict[str, str] - Section name -> content
                'domain': str - Optional paper domain
            }
        
        Returns:
            {
                'extractions': List of all entities found,
                'confidence_scores': Dict mapping entity -> confidence,
                'entities': {
                    'datasets': List[str],
                    'models': List[str],
                    'metrics': List[str],
                    'tasks': List[str]
                },
                'metadata': {
                    'total_entities': int,
                    'validated_count': int,
                    'uncertain_entities': List[str]
                }
            }
        """
        sections = input_data.get('sections', {})
        domain = input_data.get('domain', 'general')
        
        if not sections:
            return {
                'extractions': [],
                'confidence_scores': {},
                'entities': {'datasets': [], 'models': [], 'metrics': [], 'tasks': [], 'frameworks': []},
                'relationships': [],
                'metadata': {'total_entities': 0, 'validated_count': 0, 'uncertain_entities': [], 'by_type': {}, 'relationships_inferred': 0},
            }
        
        # Extract entities using existing extractor
        try:
            combined_text = ' '.join(sections.values())
            entities = self.entity_extractor.extract_entities(combined_text)
        except Exception as e:
            raise ValueError(f"Entity extraction failed: {str(e)}")
        
        self.extracted_entities = entities
        self.uncertain_entities.clear()
        
        # Validate entities against experience database
        validated_entities = {}
        confidence_scores = {}
        all_extractions = []
        validated_count = 0
        
        for entity_type, entity_list in entities.items():
            validated_entities[entity_type] = []
            
            for entity in entity_list:
                all_extractions.append(entity)
                
                # Query experience DB to check if entity is known
                known_entity = await self.query_experience(
                    'entity',
                    entity_name=entity,
                    entity_type=entity_type
                )
                
                if known_entity and known_entity.get('confidence', 0) >= 0.7:
                    # High-confidence known entity
                    confidence_scores[entity] = known_entity['confidence']
                    validated_entities[entity_type].append(entity)
                    validated_count += 1
                elif self._is_likely_valid_entity(entity, entity_type):
                    # Pattern-based validation for new entities
                    confidence_scores[entity] = 0.6
                    validated_entities[entity_type].append(entity)
                else:
                    # Uncertain entity - flag for review
                    confidence_scores[entity] = 0.3
                    self.uncertain_entities.add(entity)
                    validated_entities[entity_type].append(entity)
        
        # For uncertain entities, request validation from other agents
        if self.uncertain_entities and len(self.uncertain_entities) <= 5:
            await self._request_entity_validation(list(self.uncertain_entities))
        
        # Update experience DB with validated entities
        for entity_type, entity_list in validated_entities.items():
            for entity in entity_list:
                confidence = confidence_scores.get(entity, 0)
                if confidence >= 0.6:
                    await self.update_experience(
                        'entity',
                        entity_name=entity,
                        entity_type=entity_type,
                        # The score this run arrived at — what makes the running
                        # cross-paper average move. Omitting it used to raise a
                        # KeyError for every validated entity, so nothing the
                        # agent learned was ever written back.
                        confidence=confidence,
                        context=entity_type,
                    )

        # Infer semantic relationships from section context
        inferred_relationships = self._infer_relationships(sections, validated_entities)

        # Persist inferred relationships to experience DB
        for rel in inferred_relationships:
            await self.update_experience(
                'relationship',
                entity_1=rel['entity_1'],
                type_1=rel['type_1'],
                entity_2=rel['entity_2'],
                type_2=rel['type_2'],
                relationship=rel['relationship_type'],
                confidence=rel['confidence'],
            )

        # Ensure all expected keys are always present
        for _key in ('models', 'datasets', 'metrics', 'tasks', 'frameworks'):
            validated_entities.setdefault(_key, [])

        return {
            'extractions': all_extractions,
            'confidence_scores': confidence_scores,
            'entities': validated_entities,
            'relationships': inferred_relationships,
            'metadata': {
                'total_entities': len(all_extractions),
                'validated_count': validated_count,
                'uncertain_entities': list(self.uncertain_entities),
                'by_type': {k: len(v) for k, v in validated_entities.items()},
                'relationships_inferred': len(inferred_relationships),
            }
        }
    
    def _infer_relationships(
        self,
        sections: Dict[str, str],
        entities: Dict[str, List[str]],
    ) -> List[Dict[str, Any]]:
        """Infer semantic relationship types from section context.

        Rules:
        - model + dataset in same sentence → 'uses'
        - metric + dataset in same sentence → 'evaluated-on'
        - model vs model in results/comparison section → 'compared-to'
        - model + task in same sentence → 'applied-to'
        """
        relationships: List[Dict[str, Any]] = []
        seen: Set[Tuple[str, str, str]] = set()

        models = entities.get('models', [])
        datasets = entities.get('datasets', [])
        metrics = entities.get('metrics', [])
        tasks = entities.get('tasks', [])

        def _sentences(text: str) -> List[str]:
            return re.split(r'(?<=[.!?])\s+', text)

        def _add(e1: str, t1: str, e2: str, t2: str, rel: str, conf: float) -> None:
            key = (e1.lower(), e2.lower(), rel)
            if key not in seen:
                seen.add(key)
                relationships.append({
                    'entity_1': e1, 'type_1': t1,
                    'entity_2': e2, 'type_2': t2,
                    'relationship_type': rel, 'confidence': conf,
                })

        results_sections = {
            k: v for k, v in sections.items()
            if any(w in k.lower() for w in ('result', 'experiment', 'comparison', 'evaluat', 'ablat'))
        }
        all_text = ' '.join(sections.values())

        for sentence in _sentences(all_text):
            s_lower = sentence.lower()
            present_models = [m for m in models if m.lower() in s_lower]
            present_datasets = [d for d in datasets if d.lower() in s_lower]
            present_metrics = [m for m in metrics if m.lower() in s_lower]
            present_tasks = [t for t in tasks if t.lower() in s_lower]

            # model uses dataset
            for model in present_models:
                for dataset in present_datasets:
                    _add(model, 'models', dataset, 'datasets', 'uses', 0.75)

            # metric evaluated-on dataset
            for metric in present_metrics:
                for dataset in present_datasets:
                    _add(metric, 'metrics', dataset, 'datasets', 'evaluated-on', 0.70)

            # model applied-to task
            for model in present_models:
                for task in present_tasks:
                    _add(model, 'models', task, 'tasks', 'applied-to', 0.70)

        # model compared-to model: only in results/comparison sections
        for text in results_sections.values():
            for sentence in _sentences(text):
                s_lower = sentence.lower()
                # require comparison signal words
                if not re.search(r'\b(vs\.?|versus|compared|outperform|baseline|beats?|surpass)\b', s_lower):
                    continue
                present_models = [m for m in models if m.lower() in s_lower]
                for i, m1 in enumerate(present_models):
                    for m2 in present_models[i + 1:]:
                        _add(m1, 'models', m2, 'models', 'compared-to', 0.80)

        return relationships

    def _is_likely_valid_entity(self, entity: str, entity_type: str) -> bool:
        """
        Pattern-based validation for entities.
        
        Checks:
        - Proper capitalization
        - Reasonable length
        - Type-specific patterns
        """
        if not entity or len(entity) < 2:
            return False
        
        if entity_type == 'datasets':
            # Datasets often: ALL CAPS, CamelCase, or have numbers
            return (entity.isupper() or 
                    entity[0].isupper() or 
                    any(c.isdigit() for c in entity))
        
        elif entity_type == 'models':
            # Models often: have hyphens, acronyms, or version numbers
            return (any(c.isupper() for c in entity) or 
                    '-' in entity or 
                    any(c.isdigit() for c in entity))
        
        elif entity_type == 'metrics':
            # Metrics often: lowercase, acronyms, or compound words
            common_metrics = {'accuracy', 'precision', 'recall', 'f1', 'loss', 'error', 'score'}
            return (entity.lower() in common_metrics or 
                    entity.isupper() or
                    any(word in entity.lower() for word in common_metrics))
        
        elif entity_type == 'tasks':
            # Tasks often: descriptive phrases, lowercase
            task_keywords = {'classification', 'detection', 'segmentation', 'translation', 
                           'recognition', 'generation', 'prediction', 'estimation'}
            return any(kw in entity.lower() for kw in task_keywords)
        
        return True
    
    async def _request_entity_validation(self, uncertain_entities: List[str]):
        """Request validation from StructureAgent or ResultsAgent."""
        if not self.message_bus:
            return
        
        # Ask StructureAgent: "Where is X mentioned?"
        for entity in uncertain_entities[:3]:  # Limit to avoid spam
            response = await self.ask_agent(
                recipient="StructureAgent",
                question=f"Where is {entity} mentioned?",
                context={'entity': entity, 'validation_request': True}
            )
            
            if response and len(response.get('sections', [])) >= 2:
                # Entity mentioned in multiple sections -> likely valid
                if entity in self.uncertain_entities:
                    self.uncertain_entities.remove(entity)
    
    async def handle_message(self, message):
        """Handle requests from other agents."""
        from core.agents.message_bus import MessageType
        
        if message.msg_type == MessageType.REQUEST:
            question = message.payload.get('question', '')
            
            # Handle "Is X a known entity?" queries
            if 'is' in question.lower() and 'known' in question.lower():
                entity_name = message.payload.get('context', {}).get('entity', '')
                entity_type = message.payload.get('context', {}).get('type', 'models')
                
                known_entity = await self.query_experience(
                    'entity',
                    entity_name=entity_name,
                    entity_type=entity_type
                )
                
                response = {
                    'is_known': known_entity is not None,
                    'confidence': known_entity.get('confidence', 0.0) if known_entity else 0.0,
                    'entity': entity_name,
                    'agent': self.name
                }
                
                await self.message_bus.respond(
                    original_msg_id=message.msg_id,
                    sender=self.name,
                    recipient=message.sender,
                    payload=response
                )
            
            # Handle "Get all entities of type X" queries
            elif 'get' in question.lower() and 'entities' in question.lower():
                entity_type = message.payload.get('context', {}).get('type', 'models')
                entities = self.extracted_entities.get(entity_type, [])
                
                response = {
                    'entities': entities,
                    'count': len(entities),
                    'confidence': 0.8,
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
            'extract_entities',
            'validate_entities',
            'query_entity_knowledge',
            'flag_uncertain_entities',
            'learn_new_entities'
        ]
    
    def get_entities_by_type(self, entity_type: str) -> List[str]:
        """Get all entities of a specific type."""
        return self.extracted_entities.get(entity_type, [])
    
    def get_all_entities(self) -> Dict[str, List[str]]:
        """Get all extracted entities."""
        return self.extracted_entities.copy()
    
    def get_uncertain_entities(self) -> Set[str]:
        """Get entities flagged as uncertain."""
        return self.uncertain_entities.copy()
