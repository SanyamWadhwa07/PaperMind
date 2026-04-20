"""ComparisonAgent — optional SOTA benchmarking agent (Phase 3)."""

from typing import Dict, Optional
from core.agents.base_agent import BaseAgent


class ComparisonAgent(BaseAgent):
    def __init__(self, patterns: Optional[Dict] = None, config: Optional[Dict] = None,
                 rag_service=None, sota_service=None):
        super().__init__("ComparisonAgent", patterns)
        self.config = config or {}
        self.rag_service = rag_service
        self.sota_service = sota_service

    def get_capabilities(self):
        return ['sota_comparison', 'metric_extraction', 'benchmark_analysis']

    async def process(self, input_data: Dict) -> Dict:
        results = input_data.get("quantitative_results", [])
        entities = input_data.get("entities", {})
        comparisons = []

        for res in results[:10]:
            metric = res.get("metric", "")
            value = res.get("value")
            model = res.get("model", "")
            dataset = res.get("dataset", "")
            if metric and value is not None:
                comparisons.append({
                    "metric": metric,
                    "value": value,
                    "model": model,
                    "dataset": dataset,
                    "note": "Extracted from paper results section"
                })

        return {
            "sota_comparisons": comparisons,
            "models_compared": entities.get("models", [])[:5],
            "datasets_used": entities.get("datasets", [])[:5],
        }
