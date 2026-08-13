"""ResultsAgent - Extracts experimental results with outlier detection.

Wraps existing ResultsExtractor with agent capabilities:
- Table and inline results extraction
- Experience-based outlier detection
- Cross-validation with entity agent
"""

import re
import sys
from pathlib import Path
from typing import Dict, List, Any, Optional, Set, Tuple

# Add parent directory to path for imports
sys.path.append(str(Path(__file__).parent.parent.parent))

from core.agents.base_agent import BaseAgent, AgentState
from backend.main import ResultsExtractor


def _as_baseline_number(raw: Any) -> Optional[float]:
    """Parse an extracted result value into a number, or None if it isn't one.

    Values reach here as display strings — "94.2", "80%", "1.5x" — because the
    UI renders them verbatim. `result_baselines.mean_value` is a DECIMAL, so
    passing the string through raised `invalid input syntax for type numeric:
    "0%"` on Postgres, once per extracted metric.

    A trailing percent sign is dropped rather than divided out: a metric
    reported as "80%" in one paper and "0.80" in another cannot be reconciled
    here anyway, and rescaling would silently invent the wrong baseline. Only a
    clean leading number is accepted; anything with unresolved units is skipped.
    """
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return float(raw)

    text = str(raw or "").strip().replace(",", "")
    if not text:
        return None

    match = re.fullmatch(r"([+-]?\d+(?:\.\d+)?)\s*%?", text)
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def _is_recordable_baseline(metric: Any, dataset: Any) -> bool:
    """True when (dataset, metric) is specific enough for a baseline to mean anything.

    Two guards, both from real extractor output:

    A baseline is per-dataset by definition — accuracy on SQuAD and accuracy on
    ImageNet share no range — so an empty `dataset` produces a "baseline" that
    averages unrelated numbers together. The regex extractor leaves it empty
    often.

    And a metric name has to name something. The extractor also emits stray
    table cells as metrics: `8`, `1`, `10`. Requiring at least one letter drops
    those while keeping the short real names — `F1`, `AP`, `mAP`, `BLEU` — that
    a stricter threshold would have thrown out with them.
    """
    metric_text = str(metric or "").strip()
    dataset_text = str(dataset or "").strip()

    if not dataset_text or not metric_text:
        return False
    return bool(re.search(r"[A-Za-z]", metric_text))


class ResultsAgent(BaseAgent):
    """
    Agent responsible for experimental results extraction and validation.
    
    Capabilities:
    - Extract tables and inline results
    - Detect outliers using experience baselines
    - Validate metric values
    - Learn expected result ranges by domain
    """
    
    def __init__(self, patterns: Optional[Dict] = None):
        super().__init__(name="ResultsAgent", patterns=patterns)
        self.results_extractor = ResultsExtractor()
        self.extracted_results: List[Dict] = []
        self.outlier_results: List[Dict] = []
    
    async def process(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract and validate results from sections.
        
        Args:
            input_data: {
                'sections': Dict[str, str] - Section name -> content
                'domain': str - Optional paper domain
                'entities': Dict - Optional entities from EntityAgent
            }
        
        Returns:
            {
                'extractions': List of result dictionaries,
                'confidence_scores': Dict mapping result_id -> confidence,
                'results': {
                    'table_results': List[Dict],
                    'inline_results': List[Dict]
                },
                'metadata': {
                    'total_results': int,
                    'outliers_detected': int,
                    'validated_count': int,
                    'outlier_details': List[Dict]
                }
            }
        """
        sections = input_data.get('sections', {})
        domain = input_data.get('domain', 'general')
        entities = input_data.get('entities', {})
        
        if not sections:
            raise ValueError("sections required")
        
        # Search all sections whose key contains results/experiment/evaluation keywords
        result_keywords = ('result', 'experiment', 'evaluat', 'perform', 'ablat', 'benchmark', 'measur', 'compar')
        matching = {k: v for k, v in sections.items()
                    if any(kw in k.lower() for kw in result_keywords)}
        # Fallback: search all sections if none matched
        if not matching:
            matching = sections
        combined_text = ' '.join(matching.values())
        
        # Extract results using existing extractor — use text method (no PDF path needed)
        raw = self.results_extractor._extract_from_text(combined_text, 'results')
        table_results = [
            {'metric': r.metric, 'value': str(r.value), 'dataset': r.dataset or '', 'context': r.context or ''}
            for r in raw
        ]
        inline_results = []
        
        all_results = table_results + inline_results
        self.extracted_results = all_results
        self.outlier_results.clear()
        
        # Validate results and detect outliers
        confidence_scores = {}
        validated_count = 0
        
        for i, result in enumerate(all_results):
            result_id = f"result_{i}"
            metric = result.get('metric', '')
            value = result.get('value', 0.0)
            dataset = result.get('dataset', '')
            
            # Query experience DB for expected baseline
            baseline = await self.query_experience(
                'result_baseline',
                metric=metric,
                dataset=dataset,
                task=domain
            )
            
            if baseline:
                # Check if result is an outlier
                # (is_outlier, reason) — unpacked, because the tuple itself is
                # truthy even for `(False, None)`, which would flag every result.
                is_outlier_result, _outlier_reason = await self.query_experience(
                    'outlier',
                    value=value,
                    metric=metric,
                    dataset=dataset
                ) or (False, None)

                if is_outlier_result:
                    confidence_scores[result_id] = 0.4  # Low confidence for outliers
                    self.outlier_results.append({
                        'result': result,
                        'baseline': baseline,
                        'reason': f"{metric} value {value} deviates from expected range"
                    })
                else:
                    confidence_scores[result_id] = 0.9  # High confidence
                    validated_count += 1
            else:
                # No baseline - moderate confidence
                confidence_scores[result_id] = 0.6
                validated_count += 1
            
            # Update experience DB with this result. Both guards are required:
            # the store writes into typed numeric columns, and a baseline keyed
            # on an empty dataset or a metric called "8" is noise that later
            # skews outlier detection for everything else.
            if confidence_scores.get(result_id, 0) >= 0.6 and _is_recordable_baseline(metric, dataset):
                numeric_value = _as_baseline_number(value)
                if numeric_value is not None:
                    await self.update_experience(
                        'baseline',
                        metric=metric,
                        dataset=dataset,
                        model=result.get('model'),
                        value=numeric_value
                    )
        
        # Cross-validate with EntityAgent for dataset/model names
        if entities and self.message_bus:
            await self._cross_validate_entities(all_results, entities)
        
        return {
            'extractions': all_results,
            'confidence_scores': confidence_scores,
            'results': {
                'table_results': table_results,
                'inline_results': inline_results
            },
            'metadata': {
                'total_results': len(all_results),
                'outliers_detected': len(self.outlier_results),
                'validated_count': validated_count,
                'outlier_details': self.outlier_results
            }
        }
    
    async def _cross_validate_entities(self, results: List[Dict], known_entities: Dict):
        """
        Cross-validate dataset/model names in results against EntityAgent.
        
        Flags mismatches for review.
        """
        for result in results:
            dataset = result.get('dataset', '')
            model = result.get('model', '')
            
            # Check if dataset is known
            if dataset and dataset not in known_entities.get('datasets', []):
                # Ask EntityAgent if this is a known entity
                response = await self.ask_agent(
                    recipient="EntityAgent",
                    question=f"Is {dataset} a known dataset?",
                    context={'entity': dataset, 'type': 'datasets'}
                )
                
                if response and not response.get('is_known', False):
                    # Flag as potential typo or unknown dataset
                    result['flags'] = result.get('flags', []) + ['unknown_dataset']
            
            # Check if model is known
            if model and model not in known_entities.get('models', []):
                response = await self.ask_agent(
                    recipient="EntityAgent",
                    question=f"Is {model} a known model?",
                    context={'entity': model, 'type': 'models'}
                )
                
                if response and not response.get('is_known', False):
                    result['flags'] = result.get('flags', []) + ['unknown_model']
    
    async def handle_message(self, message):
        """Handle requests from other agents."""
        from core.agents.message_bus import MessageType
        
        if message.msg_type == MessageType.REQUEST:
            question = message.payload.get('question', '')
            
            # Handle "Get results for dataset X" queries
            if 'get results' in question.lower():
                dataset = message.payload.get('context', {}).get('dataset', '')
                filtered_results = [
                    r for r in self.extracted_results 
                    if r.get('dataset', '').lower() == dataset.lower()
                ]
                
                response = {
                    'results': filtered_results,
                    'count': len(filtered_results),
                    'confidence': 0.8,
                    'agent': self.name
                }
                
                await self.message_bus.respond(
                    original_msg_id=message.msg_id,
                    sender=self.name,
                    recipient=message.sender,
                    payload=response
                )
            
            # Handle "Are there outliers?" queries
            elif 'outlier' in question.lower():
                response = {
                    'has_outliers': len(self.outlier_results) > 0,
                    'outlier_count': len(self.outlier_results),
                    'outliers': self.outlier_results,
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
            'extract_table_results',
            'extract_inline_results',
            'detect_outliers',
            'validate_metric_values',
            'learn_result_baselines'
        ]
    
    def get_all_results(self) -> List[Dict]:
        """Get all extracted results."""
        return self.extracted_results.copy()
    
    def get_outliers(self) -> List[Dict]:
        """Get results flagged as outliers."""
        return self.outlier_results.copy()
    
    def get_results_by_dataset(self, dataset: str) -> List[Dict]:
        """Get results filtered by dataset."""
        return [r for r in self.extracted_results if r.get('dataset', '') == dataset]
    
    def get_results_by_metric(self, metric: str) -> List[Dict]:
        """Get results filtered by metric."""
        return [r for r in self.extracted_results if r.get('metric', '') == metric]
