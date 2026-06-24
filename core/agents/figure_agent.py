"""FigureAgent - Extracts figures then classifies and understands them.

Extraction path (in priority order):
  1. Pre-extracted figures from StructureAgent (MinerU / pymupdf4llm output)
  2. FigureExtractor from backend.main (PyMuPDF-based)

Understanding:
  DiagramProcessor classifies each figure (CLIP or caption keywords) then
  applies type-specific models (VLM, DePlot, pix2tex) to produce insights.
"""

import sys
from pathlib import Path
from typing import Dict, List, Any, Optional

sys.path.append(str(Path(__file__).parent.parent.parent))

from core.agents.base_agent import BaseAgent, AgentState
from core.pipeline.diagram_processor import DiagramProcessor


class FigureAgent(BaseAgent):
    """
    Agent responsible for figure and table extraction and understanding.

    Capabilities:
    - Extract figures with captions (from pre-extracted PNGs or direct PDF)
    - Classify figure type (architecture, chart, table, equation, …)
    - Generate type-specific insights via VLM / DePlot / pix2tex
    - Rank by relevance using section cross-reference
    """

    def __init__(
        self,
        patterns: Optional[Dict] = None,
        use_clip: bool = True,
        use_deplot: bool = True,
        use_vlm: bool = True,
    ):
        super().__init__(name="FigureAgent", patterns=patterns)
        self.diagram_processor = DiagramProcessor(
            use_clip=use_clip,
            use_deplot=use_deplot,
            use_vlm=use_vlm,
        )
        self.extracted_figures: List[Dict] = []

        # Lazy fallback extractor (backend.main)
        self._legacy_extractor = None

    def _get_legacy_extractor(self):
        if self._legacy_extractor is None:
            try:
                from backend.main import FigureExtractor  # type: ignore
                self._legacy_extractor = FigureExtractor()
            except Exception:
                self._legacy_extractor = None
        return self._legacy_extractor

    async def process(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract and understand figures from a PDF.

        Args:
            input_data: {
                'pdf_path': str — path to PDF,
                'sections': Dict[str, str] — section text for relevance scoring,
                'pre_extracted_figures': List[FigureInfo] — optional, from
                    StructureAgent when MinerU/pymupdf4llm already ran,
            }

        Returns:
            {
                'extractions': List[Dict] — raw figure metadata,
                'confidence_scores': Dict[str, float],
                'figures': List[Dict] — enriched with type + insight,
                'metadata': {
                    'total_figures': int,
                    'by_type': Dict[str, int],
                    'ranked_figures': List[str],
                }
            }
        """
        pdf_path = input_data.get("pdf_path")
        sections = input_data.get("sections", {})
        pre_extracted = input_data.get("pre_extracted_figures")

        if not pdf_path and not pre_extracted:
            raise ValueError("pdf_path or pre_extracted_figures required")

        # ── Step 1: get raw figure list ───────────────────────────────────
        if pre_extracted:
            # FigureInfo objects from new extraction pipeline
            raw_figures = pre_extracted
        else:
            # Legacy path: extract via backend.main.FigureExtractor
            extractor = self._get_legacy_extractor()
            if extractor and pdf_path:
                raw_figures = extractor.extract_figures(pdf_path, sections)
            else:
                raw_figures = []

        # ── Step 2: classify + understand with DiagramProcessor ───────────
        if raw_figures:
            enriched = await self.diagram_processor.process_figures(raw_figures)
        else:
            enriched = []

        # ── Step 3: rank by relevance (section cross-reference) ───────────
        ranked = self._rank_figures(enriched, sections)
        self.extracted_figures = ranked

        # ── Step 4: build confidence scores ───────────────────────────────
        confidence_scores: Dict[str, float] = {}
        for i, fig in enumerate(ranked):
            fig_id = fig.get("id", f"fig_{i:03d}")
            score = 0.5
            if fig.get("caption"):
                score += 0.15
            if fig.get("insight") and fig["insight"] != fig.get("caption", ""):
                score += 0.2    # VLM / DePlot added real understanding
            if fig.get("references", 0) > 0:
                score += 0.1
            if i < 3:
                score += 0.05
            confidence_scores[fig_id] = min(score, 1.0)

        # ── Step 5: type breakdown ─────────────────────────────────────────
        by_type: Dict[str, int] = {}
        for fig in ranked:
            ft = fig.get("figure_type", "other")
            by_type[ft] = by_type.get(ft, 0) + 1

        return {
            "extractions": ranked,
            "confidence_scores": confidence_scores,
            "figures": ranked,
            "metadata": {
                "total_figures": len(ranked),
                "by_type": by_type,
                "ranked_figures": [f.get("id", f"fig_{i:03d}") for i, f in enumerate(ranked[:5])],
            },
        }

    # ------------------------------------------------------------------
    # Relevance ranking
    # ------------------------------------------------------------------

    def _rank_figures(self, figures: List[Dict], sections: Dict[str, str]) -> List[Dict]:
        """Score figures by section cross-reference and position."""
        all_text = " ".join(sections.values()).lower()
        abstract = sections.get("abstract", "").lower()
        introduction = sections.get("introduction", "").lower()
        results = sections.get("results", "").lower()

        for i, fig in enumerate(figures):
            score = 0.0
            fig_id = (fig.get("id", "") or f"figure {i + 1}").lower()
            caption_lower = fig.get("caption", "").lower()

            references = all_text.count(fig_id)
            fig["references"] = references
            score += references * 2

            if fig_id in abstract or fig_id in introduction:
                score += 10
            if fig_id in results:
                score += 5

            if caption_lower:
                score += min(len(caption_lower.split()) / 10, 5)

            # Architecture diagrams and result charts get a bonus
            if fig.get("figure_type") in ("architecture_diagram", "result_chart"):
                score += 3

            # Position bonus (earlier = more likely to be overview/key figure)
            score += (len(figures) - i) * 0.5

            fig["relevance_score"] = score

        return sorted(figures, key=lambda x: x.get("relevance_score", 0), reverse=True)

    # ------------------------------------------------------------------
    # Message bus handlers
    # ------------------------------------------------------------------

    async def handle_message(self, message):
        from core.agents.message_bus import MessageType

        if message.msg_type == MessageType.REQUEST:
            question = message.payload.get("question", "")

            if "top" in question.lower() and "figure" in question.lower():
                count = message.payload.get("context", {}).get("count", 3)
                response = {
                    "figures": self.extracted_figures[:count],
                    "count": min(count, len(self.extracted_figures)),
                    "confidence": 0.9,
                    "agent": self.name,
                }
                await self.message_bus.respond(
                    original_msg_id=message.msg_id,
                    sender=self.name,
                    recipient=message.sender,
                    payload=response,
                )

            elif "get figure" in question.lower():
                fig_id = message.payload.get("context", {}).get("figure_id", "")
                figure = next(
                    (f for f in self.extracted_figures if f.get("id", "") == fig_id), None
                )
                response = {
                    "figure": figure,
                    "found": figure is not None,
                    "confidence": 1.0 if figure else 0.0,
                    "agent": self.name,
                }
                await self.message_bus.respond(
                    original_msg_id=message.msg_id,
                    sender=self.name,
                    recipient=message.sender,
                    payload=response,
                )

            else:
                await super().handle_message(message)

    def get_capabilities(self) -> List[str]:
        return [
            "extract_figures",
            "classify_figure_type",
            "understand_architecture_diagrams",
            "extract_chart_data",
            "extract_equation_latex",
            "rank_by_relevance",
            "cross_reference_text",
        ]

    # ------------------------------------------------------------------
    # Convenience accessors
    # ------------------------------------------------------------------

    def get_top_figures(self, count: int = 3) -> List[Dict]:
        return self.extracted_figures[:count]

    def get_figures_by_type(self, figure_type: str) -> List[Dict]:
        return [f for f in self.extracted_figures if f.get("figure_type") == figure_type]

    def get_all_figures(self) -> List[Dict]:
        return self.extracted_figures.copy()

    def get_figure_by_id(self, fig_id: str) -> Optional[Dict]:
        return next((f for f in self.extracted_figures if f.get("id", "") == fig_id), None)
