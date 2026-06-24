"""Layered PDF extraction pipeline.

Priority order:
1. MinerU (magic-pdf)  — best for academic papers: figures, equations, tables, OCR
2. pymupdf4llm         — fast, native PDFs, clean Markdown
3. PyMuPDF fitz        — always available, basic text fallback

All backends return a consistent ExtractionResult so agents never need to
know which extractor ran.
"""

from __future__ import annotations

import hashlib
import logging
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Any

import structlog

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class FigureInfo:
    path: str                      # absolute path to the extracted PNG
    caption: str = ""
    page_number: int = 0
    figure_number: str = ""        # "Fig. 1", "Figure 2", …
    figure_type: str = "unknown"   # filled in later by DiagramProcessor
    width: int = 0
    height: int = 0


@dataclass
class ExtractionResult:
    sections: Dict[str, str] = field(default_factory=dict)
    figures: List[FigureInfo] = field(default_factory=list)
    equations: List[str] = field(default_factory=list)    # raw LaTeX strings
    tables_md: List[str] = field(default_factory=list)    # Markdown tables
    backend: str = "unknown"
    figures_dir: Optional[str] = None   # temp dir holding PNG files
    metadata: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _pdf_hash(pdf_path: str) -> str:
    """SHA-256 hex of file content (first 64 KB for speed)."""
    h = hashlib.sha256()
    with open(pdf_path, "rb") as f:
        h.update(f.read(65536))
    return h.hexdigest()[:16]


def _split_markdown_sections(md_text: str) -> Dict[str, str]:
    """Split pymupdf4llm / MinerU Markdown output into named sections."""
    parts = re.split(r"\n(?=##\s)", md_text)
    sections: Dict[str, str] = {}

    if parts and not parts[0].strip().startswith("##"):
        preamble = parts[0].strip()
        if preamble:
            if re.search(r"\babstract\b", preamble[:400], re.IGNORECASE):
                sections["abstract"] = preamble
            else:
                sections["preamble"] = preamble
        parts = parts[1:]

    for part in parts:
        lines = part.strip().splitlines()
        if not lines:
            continue
        key = re.sub(r"[^a-z0-9]+", "_", lines[0].lstrip("#").strip().lower()).strip("_")
        body = "\n".join(lines[1:]).strip()
        if key and body:
            sections[key] = body

    return sections


# ---------------------------------------------------------------------------
# Backend 1 — MinerU (magic-pdf) via subprocess
#
# MinerU hard-pins pydantic<2.11 and PyMuPDF<1.25, conflicting with
# FastAPI/Supabase.  We run it as a subprocess so the host venv stays clean.
#
# MinerU CLI: magic-pdf -p <pdf> -o <output_dir> -m auto
# Output structure:
#   <output_dir>/auto/<stem>/
#     <stem>.md                    — full Markdown
#     images/                      — extracted figure PNGs
#     <stem>_content_list.json     — structured content with captions
# ---------------------------------------------------------------------------

def _find_mineru_exe() -> Optional[str]:
    """Return path to the magic-pdf CLI if available."""
    import shutil, sys
    # 1. Same venv's Scripts/ (if MinerU is in this venv)
    venv_script = Path(sys.executable).parent / "magic-pdf"
    if venv_script.exists():
        return str(venv_script)
    venv_script_win = Path(sys.executable).parent / "magic-pdf.exe"
    if venv_script_win.exists():
        return str(venv_script_win)
    # 2. PATH
    found = shutil.which("magic-pdf")
    if found:
        return found
    return None


def _extract_mineru(pdf_path: str, output_dir: Path) -> Optional[ExtractionResult]:
    """Run MinerU CLI as a subprocess and parse its output."""
    import subprocess, json, sys

    exe = _find_mineru_exe()
    if not exe:
        logger.debug("mineru_not_found", reason="magic-pdf CLI not on PATH")
        return None

    output_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(pdf_path).stem

    try:
        result = subprocess.run(
            [exe, "-p", pdf_path, "-o", str(output_dir), "-m", "auto"],
            capture_output=True, text=True, timeout=300,
        )
        if result.returncode != 0:
            logger.warning("mineru_subprocess_failed",
                           stderr=result.stderr[-500:] if result.stderr else "")
            return None
    except subprocess.TimeoutExpired:
        logger.warning("mineru_timeout")
        return None
    except Exception as exc:
        logger.warning("mineru_subprocess_error", error=str(exc))
        return None

    # Locate MinerU output: auto/<stem>/ or just <output_dir>/<stem>/
    candidates = [
        output_dir / "auto" / stem,
        output_dir / stem,
        output_dir,
    ]
    work_dir: Optional[Path] = None
    for c in candidates:
        if c.is_dir() and any(c.glob("*.md")):
            work_dir = c
            break

    if not work_dir:
        logger.warning("mineru_output_not_found", output_dir=str(output_dir))
        return None

    # --- Markdown → sections ---
    md_files = list(work_dir.glob("*.md"))
    md_text = md_files[0].read_text(encoding="utf-8", errors="replace") if md_files else ""
    sections = _split_markdown_sections(md_text)

    # --- Figure PNGs ---
    image_dir = work_dir / "images"
    figures: List[FigureInfo] = []
    equations: List[str] = []
    tables_md: List[str] = []

    json_files = list(work_dir.glob("*_content_list.json"))
    if json_files:
        try:
            items = json.loads(json_files[0].read_text(encoding="utf-8"))
            for item in items:
                t = item.get("type", "")
                if t == "image":
                    img_path = work_dir / item.get("img_path", "")
                    if img_path.exists():
                        figures.append(FigureInfo(
                            path=str(img_path),
                            caption=item.get("img_caption", ""),
                            page_number=item.get("page_idx", 0),
                        ))
                elif t == "equation":
                    latex = item.get("text", "")
                    if latex:
                        equations.append(latex)
                elif t == "table":
                    md = item.get("text", "")
                    if md:
                        tables_md.append(md)
        except Exception as exc:
            logger.debug("mineru_content_json_parse_error", error=str(exc))

    # Fallback: scan images dir
    if not figures and image_dir.is_dir():
        for img_file in sorted(image_dir.glob("*.png")):
            figures.append(FigureInfo(path=str(img_file), caption=""))

    logger.info("mineru_extraction_done",
                sections=len(sections), figures=len(figures), equations=len(equations))
    return ExtractionResult(
        sections=sections,
        figures=figures,
        equations=equations,
        tables_md=tables_md,
        backend="mineru",
        figures_dir=str(image_dir) if image_dir.is_dir() else None,
        metadata={"source": pdf_path, "section_count": len(sections)},
    )


# ---------------------------------------------------------------------------
# Backend 2 — pymupdf4llm
# ---------------------------------------------------------------------------

def _extract_pymupdf4llm(pdf_path: str, output_dir: Path) -> Optional[ExtractionResult]:
    try:
        import pymupdf4llm  # type: ignore
        import fitz         # type: ignore
    except ImportError:
        return None

    try:
        md_text: str = pymupdf4llm.to_markdown(pdf_path)
        sections = _split_markdown_sections(md_text)

        if len(sections) < 2:
            return None

        # Extract figures as PNGs using fitz
        figures: List[FigureInfo] = []
        image_dir = output_dir / "images"
        image_dir.mkdir(parents=True, exist_ok=True)

        doc = fitz.open(pdf_path)
        fig_index = 0
        for page_num, page in enumerate(doc):
            for img_info in page.get_images(full=True):
                xref = img_info[0]
                try:
                    base_image = doc.extract_image(xref)
                    ext = base_image["ext"]
                    if ext not in ("png", "jpeg", "jpg"):
                        continue
                    img_bytes = base_image["image"]
                    w, h = base_image["width"], base_image["height"]
                    # Skip tiny images (icons, bullets, etc.)
                    if w < 80 or h < 80:
                        continue
                    out_path = image_dir / f"fig_{fig_index:03d}.png"
                    # Convert to PNG via pillow if needed
                    try:
                        from PIL import Image  # type: ignore
                        import io
                        img = Image.open(io.BytesIO(img_bytes))
                        img.save(str(out_path), "PNG")
                    except Exception:
                        out_path.write_bytes(img_bytes)
                    figures.append(FigureInfo(
                        path=str(out_path),
                        caption="",
                        page_number=page_num,
                        width=w,
                        height=h,
                    ))
                    fig_index += 1
                except Exception:
                    continue
        doc.close()

        # Try to match captions from Markdown text
        caption_pattern = re.compile(
            r"(?:Figure|Fig\.?|TABLE)\s+(\d+)[.:]?\s+(.*?)(?:\n|$)",
            re.IGNORECASE,
        )
        caption_map: Dict[int, str] = {}
        for m in caption_pattern.finditer(md_text):
            idx = int(m.group(1)) - 1
            caption_map[idx] = m.group(2).strip()
        for i, fig in enumerate(figures):
            if i in caption_map:
                fig.caption = caption_map[i]
                fig.figure_number = f"Figure {i + 1}"

        return ExtractionResult(
            sections=sections,
            figures=figures,
            backend="pymupdf4llm",
            figures_dir=str(image_dir),
            metadata={"source": pdf_path, "section_count": len(sections)},
        )

    except Exception as exc:
        logger.warning("pymupdf4llm_extraction_failed", error=str(exc))
        return None


# ---------------------------------------------------------------------------
# Backend 3 — PyMuPDF fitz (always available fallback)
# ---------------------------------------------------------------------------

def _extract_fitz(pdf_path: str) -> ExtractionResult:
    try:
        import fitz  # type: ignore

        doc = fitz.open(pdf_path)
        full_text = "\n".join(page.get_text() for page in doc)
        doc.close()

        # Crude section splitter: look for ALL-CAPS or Title-Cased short lines
        sections: Dict[str, str] = {}
        current_key = "preamble"
        current_lines: List[str] = []
        section_re = re.compile(r"^(?:[A-Z][A-Z\s]{2,30}|[IVX]+\.?\s+[A-Z].{2,30})$")

        for line in full_text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if section_re.match(stripped) and len(stripped) < 60:
                if current_lines:
                    key = re.sub(r"[^a-z0-9]+", "_", current_key.lower()).strip("_")
                    sections[key] = " ".join(current_lines)
                current_key = stripped
                current_lines = []
            else:
                current_lines.append(stripped)

        if current_lines:
            key = re.sub(r"[^a-z0-9]+", "_", current_key.lower()).strip("_")
            sections[key] = " ".join(current_lines)

        return ExtractionResult(
            sections=sections or {"full_text": full_text[:50000]},
            backend="fitz",
            metadata={"source": pdf_path, "section_count": len(sections)},
        )
    except Exception as exc:
        logger.error("fitz_extraction_failed", error=str(exc))
        return ExtractionResult(
            sections={},
            backend="fitz_failed",
            metadata={"error": str(exc)},
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_pdf(pdf_path: str, prefer_mineru: bool = True) -> ExtractionResult:
    """
    Extract text sections and figures from an academic PDF.

    Tries backends in order: MinerU → pymupdf4llm → fitz.
    Falls through to the next backend if one fails or returns too few sections.

    Args:
        pdf_path: Absolute path to the PDF file.
        prefer_mineru: If False, skip MinerU even if installed (e.g. for speed).

    Returns:
        ExtractionResult with sections, figures, equations, tables_md, backend.
    """
    pdf_hash = _pdf_hash(pdf_path)
    tmp_root = Path(tempfile.gettempdir()) / "papermind_extract" / pdf_hash
    tmp_root.mkdir(parents=True, exist_ok=True)

    # --- MinerU ---
    if prefer_mineru:
        result = _extract_mineru(pdf_path, tmp_root / "mineru")
        if result and len(result.sections) >= 3:
            logger.info("pdf_extraction_backend", backend="mineru",
                        sections=len(result.sections), figures=len(result.figures))
            return result

    # --- pymupdf4llm ---
    result = _extract_pymupdf4llm(pdf_path, tmp_root / "pymupdf4llm")
    if result and len(result.sections) >= 3:
        logger.info("pdf_extraction_backend", backend="pymupdf4llm",
                    sections=len(result.sections), figures=len(result.figures))
        return result

    # --- fitz fallback ---
    logger.warning("pdf_extraction_backend", backend="fitz_fallback",
                   reason="all primary extractors insufficient")
    return _extract_fitz(pdf_path)
