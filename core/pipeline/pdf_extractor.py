"""Layered PDF extraction pipeline.

Backends are tried in order and the first to produce a usable result wins:

1. MinerU (magic-pdf)  — layout model: figures, equations, tables, OCR.
   Opt-in only (``PAPERMIND_ENABLE_MINERU=true``) — its local model install is
   a common source of silent breakage (missing/version-mismatched weights
   make it exit 0 having written nothing), and there is no per-document
   signal that distinguishes "broken install" from "this PDF"; every paper
   fails the same way until the install is fixed. See ``_extract_mineru``.
2. pymupdf4llm         — fast, born-digital PDFs, clean Markdown
3. PyMuPDF fitz        — always available, basic text fallback

They share the :class:`PdfBackend` protocol and all return an
:class:`ExtractionResult`, so callers never learn which one ran, and adding a
backend does not touch the selection logic.

Concerns that are the same for every backend live in their own modules and are
applied once, in :func:`_enrich_result`:
:mod:`core.pipeline.metadata_extractor` (title/authors),
:mod:`core.pipeline.table_extractor` (tables),
:mod:`core.pipeline.text_cleaner` (section cleanup).
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, Sequence, Tuple

import structlog

from core.pipeline.metadata_extractor import extract_title_authors
from core.pipeline.table_extractor import (
    TableInfo, extract_tables_with_status, tables_to_markdown,
)

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
    tables: List[TableInfo] = field(default_factory=list)  # structured, with captions
    tables_md: List[str] = field(default_factory=list)    # rendered Markdown, for prompts
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


_HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(\S.*?)[ \t]*$", re.MULTILINE)

# A heading level has to appear at least this many times to be treated as the
# document's section level (papers have intro/method/results/conclusion at minimum).
_MIN_HEADINGS_FOR_LEVEL = 3

# Leading section numbering: "3", "3.1", "IV.", "A." — stripped from section keys
# so downstream substring matching (summary_graph._section_rank, _SKIP_SECTIONS)
# sees "method" rather than "3_method".
_LEADING_NUMBER_RE = re.compile(r"^(?:\d+(?:\.\d+)*|[IVXLC]+|[A-Z])[.)]?\s+", re.IGNORECASE)


def _pick_heading_level(md_text: str) -> int:
    """Choose which Markdown heading level delimits sections in this document.

    Extractors disagree on depth: MinerU emits level-1 ``#`` for every heading,
    while pymupdf4llm assigns depth by font-size rank, so sections may land on
    ``##`` or ``###`` depending on how many distinct sizes exceed the body text.
    Hardcoding one level silently discards the other extractors' output.

    Returns the shallowest level that occurs often enough to be a section level,
    or 0 when the text has no Markdown headings at all.
    """
    counts: Dict[int, int] = {}
    for m in _HEADING_RE.finditer(md_text):
        level = len(m.group(1))
        counts[level] = counts.get(level, 0) + 1

    if not counts:
        return 0

    for level in sorted(counts):
        if counts[level] >= _MIN_HEADINGS_FOR_LEVEL:
            return level

    # No level clears the bar (very short or oddly formatted paper) — use whichever
    # is most common, preferring shallower on a tie.
    return max(counts, key=lambda lvl: (counts[lvl], -lvl))


def _section_key(heading: str) -> str:
    """Normalise a heading into a section key: '## **3.1 Model Architecture**' → 'model_architecture'."""
    # pymupdf4llm wraps headings in Markdown emphasis ('## **1 Introduction**'),
    # which would otherwise block the section-number strip below.
    heading = heading.strip().strip("*_`~ \t")
    heading = _LEADING_NUMBER_RE.sub("", heading)
    return re.sub(r"[^a-z0-9]+", "_", heading.lower()).strip("_")


def _split_markdown_sections(md_text: str) -> Dict[str, str]:
    """Split pymupdf4llm / MinerU Markdown output into named sections."""
    level = _pick_heading_level(md_text)
    sections: Dict[str, str] = {}

    if not level:
        text = md_text.strip()
        if text:
            key = "abstract" if re.search(r"\babstract\b", text[:400], re.IGNORECASE) else "preamble"
            sections[key] = text
        return sections

    # Split on the chosen level and anything shallower — a shallower heading is
    # also a section boundary (e.g. the paper title above ## sections).
    split_re = re.compile(rf"^#{{1,{level}}}[ \t]+\S.*$", re.MULTILINE)
    matches = list(split_re.finditer(md_text))

    preamble = md_text[: matches[0].start()].strip() if matches else md_text.strip()
    if preamble:
        if re.search(r"\babstract\b", preamble[:400], re.IGNORECASE):
            sections["abstract"] = preamble
        else:
            sections["preamble"] = preamble

    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(md_text)
        key = _section_key(m.group(0).lstrip("#"))
        body = md_text[m.end():end].strip()
        if not key or not body:
            continue
        # Papers repeat headings (e.g. per-experiment "Results") — keep both.
        sections[key] = f"{sections[key]}\n\n{body}" if key in sections else body

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


# Set once a MinerU attempt has failed with the "ran, but wrote nothing"
# signature — a broken model install, not a per-document fluke. Retrying it on
# the next paper reproduces the exact same failure, so it just re-pays a
# ~5-minute subprocess (and the CPU it eats fighting the rest of the pipeline
# for cycles) for a result we already know is None. Cleared on process
# restart, so a fixed install is picked back up without a code change.
_mineru_broken = False


def _extract_mineru(pdf_path: str, output_dir: Path) -> Optional[ExtractionResult]:
    """Run MinerU CLI as a subprocess and parse its output."""
    import subprocess, json, sys

    global _mineru_broken
    if _mineru_broken:
        logger.debug("mineru_skipped", reason="known-broken install this process")
        return None

    exe = _find_mineru_exe()
    if not exe:
        logger.debug("mineru_not_found", reason="magic-pdf CLI not on PATH")
        return None

    output_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(pdf_path).stem

    stderr = ""
    try:
        result = subprocess.run(
            [exe, "-p", pdf_path, "-o", str(output_dir), "-m", "auto"],
            capture_output=True, text=True, timeout=300,
        )
        stderr = result.stderr or ""
        # NOTE: magic-pdf exits 0 even on a fatal error (e.g. missing model
        # weights), so the return code alone cannot be trusted — the real check
        # is whether it produced Markdown, below.
        if result.returncode != 0:
            logger.warning("mineru_subprocess_failed", stderr=stderr[-500:])
            return None
    except subprocess.TimeoutExpired:
        logger.warning("mineru_timeout", seconds=300)
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
        # magic-pdf exited 0 but wrote nothing — almost always missing or
        # version-mismatched model weights, and reproducible on every document,
        # not a one-off. Stop paying the ~5-minute subprocess for the rest of
        # this process's lifetime rather than repeating the same failure per paper.
        _mineru_broken = True
        missing_weights = re.search(r"No such file or directory: '([^']*\.(?:pth|pt|bin))'", stderr)
        logger.warning(
            "mineru_produced_no_output_disabling",
            output_dir=str(output_dir),
            missing_model=missing_weights.group(1) if missing_weights else None,
            hint="model weights are missing or version-mismatched; MinerU is "
                 "disabled for the rest of this process — restart after fixing "
                 "the local model install to retry it",
            stderr=stderr[-300:],
        )
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
                        page_idx = item.get("page_idx")
                        figures.append(FigureInfo(
                            path=str(img_path),
                            caption=item.get("img_caption", ""),
                            # MinerU's page_idx is 0-based; every other backend in
                            # this module reports 1-based page numbers, and
                            # FiguresDisplay.jsx treats page <= 0 as "unknown" — so
                            # a MinerU page-1 figure silently lost its label, and
                            # every other one showed one page early.
                            page_number=(page_idx + 1) if isinstance(page_idx, int) else 0,
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
# Figure recovery (shared by the non-MinerU backends)
#
# `page.get_images()` returns embedded raster XObjects and nothing else, but
# academic figures are overwhelmingly *vector*: matplotlib, TikZ and PGF emit
# path operators, so a paper with six plots can contain zero bitmaps. Asking for
# images therefore reports "1 figure" on a paper that visibly has several.
#
# The fix is to render the figure's region instead. Captions anchor it — a paper
# that prints "Fig. 3." has a figure directly above that line — and the vector
# ink in the same column tells us how far up it extends.
# ---------------------------------------------------------------------------

_FIG_CAPTION_RE = re.compile(r"^\s*fig(?:ure)?\s*\.?\s*(\d+)\s*[.:]?\s*(.*)", re.IGNORECASE | re.DOTALL)


def _parse_figure_number(label: Optional[str]) -> Optional[int]:
    """Extract the integer out of a "Figure 3"-shaped label, or None."""
    if not label:
        return None
    m = re.search(r"(\d+)", label)
    return int(m.group(1)) if m else None

# A text block longer than this is body prose, not an axis label or a legend, so
# it marks where the figure stops and the paper resumes.
_PROSE_WORDS = 25

# Ink separated by a bigger vertical gap than this belongs to another object.
_INK_GAP_PT = 40.0

# Smaller than this in either axis and it's a rule or a stray glyph box.
_MIN_FIGURE_PT = 55.0

# 200 dpi keeps axis tick labels legible without producing megabyte PNGs.
_FIGURE_DPI = 200


def _page_ink_rects(page) -> List[tuple]:
    """Bounding boxes of everything drawn on the page — vector paths and bitmaps."""
    rects: List[tuple] = []

    for drawing in page.get_drawings():
        r = drawing.get("rect")
        if r and r.width > 1 and r.height > 1:
            rects.append((r.x0, r.y0, r.x1, r.y1))

    for info in page.get_images(full=True):
        try:
            for r in page.get_image_rects(info[0]):
                rects.append((r.x0, r.y0, r.x1, r.y1))
        except Exception:
            continue

    return rects


def _prose_blocks(page) -> List[tuple]:
    """Bounding boxes of text blocks long enough to be body paragraphs."""
    blocks: List[tuple] = []
    try:
        data = page.get_text("dict")
    except Exception:
        return blocks

    for block in data.get("blocks", []):
        if block.get("type") != 0:
            continue
        text = " ".join(
            span.get("text", "")
            for line in block.get("lines", [])
            for span in line.get("spans", [])
        )
        if len(text.split()) >= _PROSE_WORDS:
            blocks.append(tuple(block["bbox"]))
    return blocks


def _caption_blocks(page) -> List[tuple]:
    """(bbox, figure_number, caption_text) for every 'Fig. N' line on the page."""
    found: List[tuple] = []
    try:
        data = page.get_text("dict")
    except Exception:
        return found

    for block in data.get("blocks", []):
        if block.get("type") != 0:
            continue
        text = " ".join(
            span.get("text", "")
            for line in block.get("lines", [])
            for span in line.get("spans", [])
        ).strip()
        m = _FIG_CAPTION_RE.match(text)
        if m:
            found.append((tuple(block["bbox"]), int(m.group(1)), re.sub(r"\s+", " ", m.group(2)).strip()))

    return sorted(found, key=lambda item: item[0][1])


def _figure_region(caption_bbox: tuple, ink: Sequence[tuple],
                   prose: Sequence[tuple]) -> Optional[tuple]:
    """Grow a figure region upward from its caption.

    Bounded on three sides by the caption's own column, and on top by whichever
    comes first: a vertical gap in the ink, or the body paragraph the figure sits
    below. Both bounds matter — the gap alone would swallow the plot above it in
    a single-column paper, and the paragraph alone would swallow a figure's own
    whitespace in a two-column one.
    """
    cx0, cy0, cx1, _ = caption_bbox
    # Captions are typeset to the column, and a figure is often a little wider
    # than its caption's text block, so allow some overhang either side.
    pad = 24.0
    lo, hi = cx0 - pad, cx1 + pad

    above = [
        r for r in ink
        if r[3] <= cy0 + 2 and r[0] >= lo - pad and r[2] <= hi + pad and r[3] > cy0 - 700
    ]
    if not above:
        return None

    # Walk up from the caption, absorbing ink while it stays contiguous.
    above.sort(key=lambda r: r[3], reverse=True)
    x0, y0, x1, y1 = above[0]
    for rx0, ry0, rx1, ry1 in above[1:]:
        if y0 - ry1 > _INK_GAP_PT:
            break
        x0, y0 = min(x0, rx0), min(y0, ry0)
        x1, y1 = max(x1, rx1), max(y1, ry1)

    # Don't reach back over a paragraph that ends inside the region.
    for px0, _, px1, py1 in prose:
        if py1 <= y1 and py1 > y0 and not (px1 < x0 or px0 > x1):
            y0 = max(y0, py1 + 2)

    if x1 - x0 < _MIN_FIGURE_PT or y1 - y0 < _MIN_FIGURE_PT:
        return None
    return (x0, y0, x1, y1)


def _render_figures(pdf_path: str, image_dir: Path) -> Tuple[List[FigureInfo], set]:
    """Render every captioned figure region to a PNG.

    Returns ``(figures, fallback_pages)``, where ``fallback_pages`` is every
    0-based page index that produced nothing here — no caption was found on it,
    or a caption was found but its region couldn't be grown or rendered. The
    caller runs the raster fallback on exactly those pages rather than the whole
    document, so a paper where every figure but one is captioned still gets that
    one figure instead of losing it because the rest of the paper rendered fine.
    """
    import fitz  # type: ignore

    figures: List[FigureInfo] = []
    fallback_pages: set = set()
    image_dir.mkdir(parents=True, exist_ok=True)

    doc = fitz.open(pdf_path)
    try:
        for page_index, page in enumerate(doc):
            captions = _caption_blocks(page)
            if not captions:
                fallback_pages.add(page_index)
                continue

            ink = _page_ink_rects(page)
            prose = _prose_blocks(page)
            rendered_any = False

            for caption_bbox, number, caption_text in captions:
                region = _figure_region(caption_bbox, ink, prose)
                if not region:
                    continue
                out_path = image_dir / f"fig_{number:03d}_p{page_index + 1}.png"
                try:
                    pix = page.get_pixmap(clip=fitz.Rect(*region), dpi=_FIGURE_DPI)
                    pix.save(str(out_path))
                except Exception as exc:
                    logger.debug("figure_render_failed", page=page_index + 1,
                                 figure=number, error=str(exc))
                    continue

                figures.append(FigureInfo(
                    path=str(out_path),
                    caption=caption_text,
                    page_number=page_index + 1,
                    figure_number=f"Figure {number}",
                    width=pix.width,
                    height=pix.height,
                ))
                rendered_any = True

            if not rendered_any:
                fallback_pages.add(page_index)
    finally:
        doc.close()

    # A figure spanning a column break is captioned once but drawn twice; keep
    # the first rendering of each number.
    seen: set = set()
    unique: List[FigureInfo] = []
    for fig in figures:
        if fig.figure_number in seen:
            continue
        seen.add(fig.figure_number)
        unique.append(fig)
    return unique, fallback_pages


def _extract_raster_figures(
    pdf_path: str, image_dir: Path, pages: Optional[Sequence[int]] = None,
) -> List[FigureInfo]:
    """Pull embedded bitmaps out of a PDF.

    `pages`, when given, restricts extraction to those 0-based page indices —
    used to fill in exactly the pages `_render_figures` couldn't caption-anchor,
    rather than re-scanning (and duplicating figures already rendered on) every
    page in the document.
    """
    import fitz  # type: ignore

    figures: List[FigureInfo] = []
    image_dir.mkdir(parents=True, exist_ok=True)
    page_filter = set(pages) if pages is not None else None

    doc = fitz.open(pdf_path)
    try:
        fig_index = 0
        for page_num, page in enumerate(doc):
            if page_filter is not None and page_num not in page_filter:
                continue
            for img_info in page.get_images(full=True):
                xref = img_info[0]
                try:
                    base_image = doc.extract_image(xref)
                    if base_image["ext"] not in ("png", "jpeg", "jpg"):
                        continue
                    w, h = base_image["width"], base_image["height"]
                    if w < 80 or h < 80:      # icons, bullets, rules
                        continue
                    out_path = image_dir / f"raster_{fig_index:03d}.png"
                    try:
                        from PIL import Image  # type: ignore
                        import io
                        Image.open(io.BytesIO(base_image["image"])).save(str(out_path), "PNG")
                    except Exception:
                        out_path.write_bytes(base_image["image"])
                    figures.append(FigureInfo(
                        path=str(out_path),
                        page_number=page_num + 1,
                        width=w,
                        height=h,
                    ))
                    fig_index += 1
                except Exception:
                    continue
    finally:
        doc.close()

    return figures


def _extract_figures(pdf_path: str, image_dir: Path) -> List[FigureInfo]:
    """Recover figures: caption-anchored regions first, embedded bitmaps for
    whichever pages didn't produce one.

    This used to be all-or-nothing per document — any successfully rendered
    figure anywhere in the paper skipped the raster pass entirely, so a paper
    with one captioned figure and five uncaptioned ones only ever showed the
    one. Now the raster fallback runs on exactly the pages that didn't render,
    and the two lists are merged.
    """
    rendered: List[FigureInfo] = []
    fallback_pages: Optional[set] = None
    try:
        rendered, fallback_pages = _render_figures(pdf_path, image_dir)
    except Exception as exc:
        logger.warning("figure_render_pass_failed", error=str(exc))
        # The render pass didn't get far enough to say which pages failed —
        # raster the whole document rather than silently returning nothing.
        rendered, fallback_pages = [], None

    if fallback_pages is not None and not fallback_pages:
        return rendered

    try:
        raster = _extract_raster_figures(
            pdf_path, image_dir,
            pages=sorted(fallback_pages) if fallback_pages is not None else None,
        )
    except Exception as exc:
        logger.warning("figure_raster_pass_failed", error=str(exc))
        raster = []

    return rendered + raster


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

        image_dir = output_dir / "images"
        figures = _extract_figures(pdf_path, image_dir)

        # Captions come from the rendered pass already. Fall back to the Markdown
        # text only for figures recovered as bare bitmaps, which carry none.
        if any(not f.caption for f in figures):
            caption_pattern = re.compile(
                r"(?:Figure|Fig\.?)\s+(\d+)[.:]?\s+(.*?)(?:\n|$)",
                re.IGNORECASE,
            )
            # Keyed by the figure's own printed number, not by list position.
            # Raster figures come out in page/xref order, which is not
            # figure-number order (and _render_figures dedupes, shifting
            # positions further), so a caption attached by index landed on the
            # wrong image whenever there was a gap. A missing caption is a fine
            # outcome here; a mismatched one is worse, so figures whose number
            # can't be determined are left uncaptioned rather than guessed at.
            caption_map: Dict[int, str] = {}
            for m in caption_pattern.finditer(md_text):
                caption_map[int(m.group(1))] = m.group(2).strip()
            for fig in figures:
                if fig.caption:
                    continue
                number = _parse_figure_number(fig.figure_number)
                if number is not None and number in caption_map:
                    fig.caption = caption_map[number]

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
# Backend protocol and registry
#
# Backends are ordered, interchangeable strategies behind one interface, so
# adding one (Docling, GROBID, a hosted parser) means writing a class and
# registering it — not editing the selection logic below.
# ---------------------------------------------------------------------------

# A backend has to find at least this many sections to be considered usable;
# below it, the next backend gets a turn.
MIN_USABLE_SECTIONS = 3


class PdfBackend(Protocol):
    """One strategy for turning a PDF into an :class:`ExtractionResult`."""

    name: str

    def is_available(self) -> bool:
        """True if this backend's dependencies are present on this machine."""

    def extract(self, pdf_path: str, workdir: Path) -> Optional[ExtractionResult]:
        """Extract, or return None if this backend cannot handle the document."""


class MinerUBackend:
    """Tier 1 — layout-model extraction: figures, equations, tables, OCR."""

    name = "mineru"

    def is_available(self) -> bool:
        return _find_mineru_exe() is not None

    def extract(self, pdf_path: str, workdir: Path) -> Optional[ExtractionResult]:
        return _extract_mineru(pdf_path, workdir / self.name)


class PyMuPdf4LlmBackend:
    """Tier 2 — fast Markdown extraction for born-digital PDFs."""

    name = "pymupdf4llm"

    def is_available(self) -> bool:
        try:
            import pymupdf4llm  # noqa: F401
            return True
        except ImportError:
            return False

    def extract(self, pdf_path: str, workdir: Path) -> Optional[ExtractionResult]:
        return _extract_pymupdf4llm(pdf_path, workdir / self.name)


class FitzBackend:
    """Tier 3 — always available, and always returns something."""

    name = "fitz"

    def is_available(self) -> bool:
        return True

    def extract(self, pdf_path: str, workdir: Path) -> Optional[ExtractionResult]:
        return _extract_fitz(pdf_path)


#: Tried in order; the first to return enough sections wins.
DEFAULT_BACKENDS: List[PdfBackend] = [
    MinerUBackend(),
    PyMuPdf4LlmBackend(),
    FitzBackend(),
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_pdf(
    pdf_path: str,
    prefer_mineru: Optional[bool] = None,
    backends: Optional[Sequence[PdfBackend]] = None,
) -> ExtractionResult:
    """Extract sections, figures, tables and metadata from an academic PDF.

    Args:
        pdf_path: Absolute path to the PDF.
        prefer_mineru: If False, skip the (slow, model-backed) MinerU tier. If
            None (the default), read ``PAPERMIND_ENABLE_MINERU`` — MinerU's
            local model install is a common source of silent breakage (missing
            or version-mismatched weights that make it exit 0 having written
            nothing), so it's opt-in rather than attempted by default. Set the
            env var once your local ``magic-pdf`` install is verified working.
        backends: Override the backend chain. Mainly for tests — production
            callers should use the default registry.

    Returns:
        An :class:`ExtractionResult`. Always returns a result; the final backend
        is a fallback that cannot decline.
    """
    if prefer_mineru is None:
        prefer_mineru = os.environ.get("PAPERMIND_ENABLE_MINERU", "").lower() in ("1", "true", "yes")

    chain = list(backends if backends is not None else DEFAULT_BACKENDS)
    if not prefer_mineru:
        chain = [b for b in chain if b.name != "mineru"]

    # Unique per call, not keyed by content hash. No backend here ever checks
    # for pre-existing output before writing — extraction always runs fresh —
    # so the hash-keyed name bought no caching benefit while creating a real
    # race: two calls on byte-identical content (a well-known paper uploaded by
    # two users close together, or the same PDF reprocessed) shared one
    # directory, and MinerU/pymupdf4llm's own `work_dir.glob("*.md")` /
    # `*_content_list.json` lookups could pick up a stale or partially-written
    # file left by the other call. Content hash is kept in the name only as a
    # debugging aid in logs/paths, not for identity.
    workdir = (
        Path(tempfile.gettempdir()) / "papermind_extract"
        / f"{_pdf_hash(pdf_path)}-{uuid.uuid4().hex[:8]}"
    )
    workdir.mkdir(parents=True, exist_ok=True)

    result: Optional[ExtractionResult] = None
    for backend in chain:
        if not backend.is_available():
            logger.debug("pdf_backend_unavailable", backend=backend.name)
            continue
        try:
            candidate = backend.extract(pdf_path, workdir)
        except Exception as exc:
            logger.warning("pdf_backend_raised", backend=backend.name, error=str(exc))
            continue

        if candidate and len(candidate.sections) >= MIN_USABLE_SECTIONS:
            result = candidate
            break
        logger.debug("pdf_backend_insufficient", backend=backend.name,
                     sections=len(candidate.sections) if candidate else 0)

    if result is None:
        # Every backend declined — fall back to the one that never can.
        logger.warning("pdf_extraction_all_backends_insufficient")
        result = FitzBackend().extract(pdf_path, workdir)

    _enrich_result(result, pdf_path)

    logger.info("pdf_extraction_backend",
                backend=result.backend,
                sections=len(result.sections),
                figures=len(result.figures),
                tables=len(result.tables_md),
                has_title=bool(result.metadata.get("title")))
    return result


def _enrich_result(result: ExtractionResult, pdf_path: str) -> None:
    """Fill in what the winning backend didn't provide, in place.

    Applied uniformly so downstream agents see the same shape regardless of
    which extractor won.
    """
    # Title / authors — layout-derived, so identical across backends.
    if not result.metadata.get("title"):
        title, authors = extract_title_authors(pdf_path)
        if title:
            result.metadata["title"] = title
        if authors:
            result.metadata["authors"] = authors

    # Tables. MinerU emits its own; every other backend needs these detected
    # separately, and without them the summariser's results extraction has no
    # tabular input and falls back to scraping prose.
    if not result.tables:
        result.tables, table_error = extract_tables_with_status(pdf_path)
        if table_error:
            # Surfaced through structure_agent.py's metadata and, from there,
            # pipeline_status — so the UI can render "table extraction failed"
            # instead of the identical-looking "no tables in this paper".
            result.metadata["table_extraction_error"] = table_error
    if not result.tables_md:
        result.tables_md = tables_to_markdown(result.tables)

    # Text cleaning previously ran only inside the legacy AdvancedSectionExtractor,
    # so MinerU/pymupdf4llm/fitz sections kept hyphenation breaks and running headers.
    if result.sections:
        try:
            from core.pipeline.text_cleaner import clean_all_sections
            result.sections = clean_all_sections(result.sections)
        except Exception as exc:
            logger.debug("section_cleaning_failed", error=str(exc))

    result.metadata["section_count"] = len(result.sections)
    # Two different counts, kept under distinct names rather than one shared
    # `table_count` key: `tables` is the structured re-extraction the UI renders;
    # `tables_md` is what the summariser reads, and on a MinerU paper it's MinerU's
    # own markdown extraction, not this one — the two can genuinely disagree in
    # both content and count. A single overwritten key previously let whichever
    # wrote last (structure_agent.py) silently redefine what "table_count" meant.
    result.metadata["structured_table_count"] = len(result.tables)
    result.metadata["table_markdown_count"] = len(result.tables_md)
