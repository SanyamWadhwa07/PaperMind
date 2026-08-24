"""DiagramProcessor — Classify and understand extracted paper figures.

4-layer pipeline:
  1. CLIP zero-shot classifier (or caption-keyword fallback)
  2. Type-specific understanding:
       architecture_diagram → Groq vision (llama-4-scout)
       result_chart         → DePlot (Pix2Struct) → data table → LLM summary
       table                → re-use MinerU/pymupdf table already in Markdown
       equation             → pix2tex → LaTeX
       qualitative_result   → caption only
       other                → caption only
  3. Return enriched FigureDict list ready for Supabase storage

All heavy models are lazy-loaded and optional — the processor degrades
gracefully to caption-only if a model isn't available.
"""

from __future__ import annotations

import asyncio
import base64
import io
import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Any

import structlog

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Figure type labels and caption-keyword heuristics (no model required)
# ---------------------------------------------------------------------------

FIGURE_TYPES = [
    "architecture_diagram",
    "result_chart",
    "table",
    "equation",
    "dataset_sample",
    "qualitative_result",
    "other",
]

_KEYWORD_MAP: Dict[str, List[str]] = {
    "architecture_diagram": [
        "architecture", "model overview", "framework", "pipeline", "network",
        "block diagram", "flowchart", "module", "encoder", "decoder",
        "attention", "transformer", "overview of", "system design",
    ],
    "result_chart": [
        "accuracy", "loss curve", "performance", "comparison", "benchmark",
        "vs.", " vs ", "epoch", "iteration", "convergence", "recall",
        "precision", "f1", "roc", "pr curve", "ablation result",
    ],
    "table": [
        "table", "ablation", "comparison table", "results table",
        "benchmark results", "state-of-the-art",
    ],
    "equation": [
        "equation", "formula", "loss function", "objective", "optimization",
        "gradient", "theorem", "proof",
    ],
    "dataset_sample": [
        "example", "sample", "dataset", "input image", "visualization",
        "ground truth", "annotation",
    ],
    "qualitative_result": [
        "qualitative", "visual result", "generated", "output", "prediction",
        "segmentation map", "heat map", "attention map",
    ],
}


def _classify_by_caption(caption: str) -> str:
    """Fast keyword-based classifier — no model download needed."""
    caption_lower = caption.lower()
    scores: Dict[str, int] = {t: 0 for t in FIGURE_TYPES}
    for fig_type, keywords in _KEYWORD_MAP.items():
        for kw in keywords:
            if kw in caption_lower:
                scores[fig_type] += 1
    best = max(scores, key=lambda t: scores[t])
    return best if scores[best] > 0 else "other"


# ---------------------------------------------------------------------------
# CLIP zero-shot classifier (optional — ~600 MB download on first use)
# ---------------------------------------------------------------------------

_clip_model = None
_clip_processor = None


def _load_clip() -> bool:
    global _clip_model, _clip_processor
    if _clip_model is not None:
        return True
    try:
        from transformers import CLIPModel, CLIPProcessor  # type: ignore
        _clip_processor = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32")
        _clip_model = CLIPModel.from_pretrained("openai/clip-vit-base-patch32")
        _clip_model.eval()
        return True
    except Exception as exc:
        logger.debug("clip_unavailable", reason=str(exc))
        return False


def _classify_clip(image_path: str, caption: str) -> str:
    """CLIP zero-shot classification over FIGURE_TYPES."""
    if not _load_clip():
        return _classify_by_caption(caption)
    try:
        import torch  # type: ignore
        from PIL import Image  # type: ignore

        labels = [
            "a deep learning model architecture diagram with blocks and arrows",
            "a line chart or bar chart showing experimental results",
            "a data table with rows and columns of numbers",
            "a mathematical equation or formula",
            "example images from a dataset",
            "qualitative visual outputs or prediction examples",
            "other academic paper figure",
        ]
        image = Image.open(image_path).convert("RGB")
        inputs = _clip_processor(text=labels, images=image, return_tensors="pt", padding=True)
        with torch.no_grad():
            outputs = _clip_model(**inputs)
        probs = outputs.logits_per_image.softmax(dim=1).squeeze().tolist()
        best_idx = max(range(len(probs)), key=lambda i: probs[i])
        return FIGURE_TYPES[best_idx]
    except Exception as exc:
        logger.debug("clip_classify_failed", error=str(exc))
        return _classify_by_caption(caption)


# ---------------------------------------------------------------------------
# DePlot — chart → data table (optional, ~1 GB download)
# ---------------------------------------------------------------------------

_deplot_model = None
_deplot_processor = None


def _load_deplot() -> bool:
    global _deplot_model, _deplot_processor
    if _deplot_model is not None:
        return True
    try:
        from transformers import (  # type: ignore
            Pix2StructProcessor,
            Pix2StructForConditionalGeneration,
        )
        _deplot_processor = Pix2StructProcessor.from_pretrained("google/deplot")
        _deplot_model = Pix2StructForConditionalGeneration.from_pretrained("google/deplot")
        _deplot_model.eval()
        return True
    except Exception as exc:
        logger.debug("deplot_unavailable", reason=str(exc))
        return False


def _extract_chart_data(image_path: str) -> Optional[str]:
    """Use DePlot to extract data table from a result chart image."""
    if not _load_deplot():
        return None
    try:
        import torch  # type: ignore
        from PIL import Image  # type: ignore

        image = Image.open(image_path).convert("RGB")
        inputs = _deplot_processor(
            images=image,
            text="Generate underlying data table of the figure below:",
            return_tensors="pt",
        )
        with torch.no_grad():
            preds = _deplot_model.generate(**inputs, max_new_tokens=512)
        return _deplot_processor.decode(preds[0], skip_special_tokens=True)
    except Exception as exc:
        logger.debug("deplot_failed", error=str(exc))
        return None


# ---------------------------------------------------------------------------
# pix2tex — equation image → LaTeX (optional, ~250 MB download)
# ---------------------------------------------------------------------------

_latex_ocr = None


def _load_pix2tex() -> bool:
    global _latex_ocr
    if _latex_ocr is not None:
        return True
    try:
        from pix2tex.cli import LatexOCR  # type: ignore
        _latex_ocr = LatexOCR()
        return True
    except Exception as exc:
        logger.debug("pix2tex_unavailable", reason=str(exc))
        return False


def _extract_equation_latex(image_path: str) -> Optional[str]:
    if not _load_pix2tex():
        return None
    try:
        from PIL import Image  # type: ignore
        img = Image.open(image_path)
        return _latex_ocr(img)  # type: ignore[call-arg]
    except Exception as exc:
        logger.debug("pix2tex_failed", error=str(exc))
        return None


# ---------------------------------------------------------------------------
# VLM call — architecture diagram → structured description
# ---------------------------------------------------------------------------

_ARCH_PROMPT = """You are analysing an architecture diagram from an academic research paper.
Caption: {caption}

Extract and return a JSON object with these fields:
{{
  "components": ["list of named modules or blocks shown"],
  "data_flow": "brief description of how data moves through the architecture",
  "inputs": ["what goes in"],
  "outputs": ["what comes out"],
  "novel_vs_standard": "which parts are novel contributions vs standard building blocks",
  "one_sentence_summary": "concise summary of the architecture"
}}
Return only valid JSON."""

_CHART_PROMPT = """You are analysing a results chart from an academic research paper.
Caption: {caption}
The underlying data table extracted from the chart:
{data_table}

Summarise the key findings in 2–3 sentences. Focus on:
- Which method performs best and by how much
- Any notable trends (convergence, degradation, etc.)
- What claim this figure supports in the paper"""


async def _understand_architecture(image_path: str, caption: str) -> Optional[str]:
    """Call Groq vision (llama-4-scout) to understand an architecture diagram."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        return None
    try:
        from openai import AsyncOpenAI  # type: ignore

        client = AsyncOpenAI(api_key=api_key, base_url="https://api.groq.com/openai/v1")
        img_b64 = base64.b64encode(Path(image_path).read_bytes()).decode()

        response = await client.chat.completions.create(
            model="meta-llama/llama-4-scout-17b-16e-instruct",
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{img_b64}"},
                    },
                    {
                        "type": "text",
                        "text": _ARCH_PROMPT.format(caption=caption),
                    },
                ],
            }],
            max_tokens=512,
            temperature=0.1,
        )
        return response.choices[0].message.content
    except Exception as exc:
        logger.debug("vlm_architecture_failed", error=str(exc))
        return None


# ---------------------------------------------------------------------------
# Main DiagramProcessor
# ---------------------------------------------------------------------------

class DiagramProcessor:
    """
    Enrich a list of FigureInfo objects with type classification and
    type-specific understanding.

    Usage:
        processor = DiagramProcessor(use_clip=True)
        enriched = await processor.process_figures(figures)
    """

    def __init__(self, use_clip: bool = True, use_deplot: bool = True,
                 use_pix2tex: bool = False, use_vlm: bool = True):
        self.use_clip = use_clip
        self.use_deplot = use_deplot
        self.use_pix2tex = use_pix2tex
        self.use_vlm = use_vlm

    def classify(self, image_path: str, caption: str) -> str:
        """Classify a figure — CLIP if available, keyword fallback."""
        if self.use_clip and Path(image_path).exists():
            return _classify_clip(image_path, caption)
        return _classify_by_caption(caption)

    async def understand(self, image_path: str, caption: str,
                         figure_type: str) -> Dict[str, Any]:
        """
        Run type-specific understanding and return an insight dict.

        Always returns at minimum:
          {"figure_type": str, "caption": str, "insight": str}
        """
        result: Dict[str, Any] = {
            "figure_type": figure_type,
            "caption": caption,
            "insight": "",
            "structured_data": None,
        }

        if not Path(image_path).exists():
            return result

        if figure_type == "architecture_diagram" and self.use_vlm:
            vlm_output = await _understand_architecture(image_path, caption)
            if vlm_output:
                result["insight"] = vlm_output
                result["structured_data"] = {"vlm_description": vlm_output}

        elif figure_type == "result_chart" and self.use_deplot:
            data_table = _extract_chart_data(image_path)
            if data_table:
                result["structured_data"] = {"data_table": data_table}
                # Summarise with LLM
                result["insight"] = await self._summarise_chart(caption, data_table)
            else:
                result["insight"] = f"Chart showing {caption}" if caption else ""

        elif figure_type == "equation" and self.use_pix2tex:
            latex = _extract_equation_latex(image_path)
            if latex:
                result["insight"] = f"Equation: ${latex}$"
                result["structured_data"] = {"latex": latex}

        elif figure_type in ("qualitative_result", "dataset_sample", "other"):
            result["insight"] = caption

        else:
            result["insight"] = caption

        return result

    async def _summarise_chart(self, caption: str, data_table: str) -> str:
        """Ask the configured LLM to summarise chart data in plain English."""
        try:
            from core.llm.llm_interface import get_llm  # type: ignore
            llm = get_llm()
            prompt = _CHART_PROMPT.format(caption=caption, data_table=data_table)
            return await llm.generate(prompt, max_tokens=200, temperature=0.2)
        except Exception as exc:
            logger.debug("chart_summarise_failed", error=str(exc))
            return f"Chart: {caption}"

    async def process_figures(
        self,
        figures: list,  # List[FigureInfo] — avoid circular import
        max_figures: int = 15,
        concurrency: int = 3,
    ) -> List[Dict[str, Any]]:
        """
        Classify and understand up to max_figures figures concurrently.

        Returns list of enriched dicts (one per figure) with at minimum:
            id, path, caption, figure_type, page_number,
            figure_number, insight, structured_data
        """
        sem = asyncio.Semaphore(concurrency)
        results: List[Dict[str, Any]] = []

        async def _process_one(idx: int, fig) -> Dict[str, Any]:
            async with sem:
                fig_type = self.classify(fig.path, fig.caption)
                insight_data = await self.understand(fig.path, fig.caption, fig_type)
                return {
                    "id": f"fig_{idx:03d}",
                    "path": fig.path,
                    "caption": fig.caption,
                    "figure_type": fig_type,
                    "page_number": fig.page_number,
                    "figure_number": fig.figure_number or f"Figure {idx + 1}",
                    "width": getattr(fig, "width", 0),
                    "height": getattr(fig, "height", 0),
                    **insight_data,
                }

        tasks = [
            _process_one(i, fig)
            for i, fig in enumerate(figures[:max_figures])
        ]
        # One unreadable PNG must not cost the paper every other figure:
        # return_exceptions=False propagated the first failure out of gather and
        # zeroed the whole batch, which the UI then rendered as "no figures".
        results = await asyncio.gather(*tasks, return_exceptions=True)
        out: List[Dict[str, Any]] = []
        for i, res in enumerate(results):
            if isinstance(res, BaseException):
                logger.warning("figure_processing_failed", index=i,
                               error=str(res), error_type=type(res).__name__)
                continue
            out.append(res)
        return out

    def process_figures_sync(
        self, figures: list, max_figures: int = 15
    ) -> List[Dict[str, Any]]:
        """Synchronous wrapper for contexts without a running event loop."""
        return asyncio.run(self.process_figures(figures, max_figures))
