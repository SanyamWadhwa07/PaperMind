"""Layered PDF extraction pipeline.

Backends are tried in order and the first to produce a usable result wins:

1. MinerU (magic-pdf)  — layout model: figures, equations, tables, OCR
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
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, Sequence

import structlog

from core.pipeline.metadata_extractor import extract_title_authors
from core.pipeline.table_extractor import TableInfo, extract_tables, tables_to_markdown

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


def _extract_mineru(pdf_path: str, output_dir: Path) -> Optional[ExtractionResult]:
    """Run MinerU CLI as a subprocess and parse its output."""
    import subprocess, json, sys

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
        # version-mismatched model weights. Surface the cause, not just the symptom.
        missing_weights = re.search(r"No such file or directory: '([^']*\.(?:pth|pt|bin))'", stderr)
        logger.warning(
            "mineru_produced_no_output",
            output_dir=str(output_dir),
            missing_model=missing_weights.group(1) if missing_weights else None,
            hint="run 'python -m magic_pdf.tools.common download_models' to repair model weights",
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
    prefer_mineru: bool = True,
    backends: Optional[Sequence[PdfBackend]] = None,
) -> ExtractionResult:
    """Extract sections, figures, tables and metadata from an academic PDF.

    Args:
        pdf_path: Absolute path to the PDF.
        prefer_mineru: If False, skip the (slow, model-backed) MinerU tier.
        backends: Override the backend chain. Mainly for tests — production
            callers should use the default registry.

    Returns:
        An :class:`ExtractionResult`. Always returns a result; the final backend
        is a fallback that cannot decline.
    """
    chain = list(backends if backends is not None else DEFAULT_BACKENDS)
    if not prefer_mineru:
        chain = [b for b in chain if b.name != "mineru"]

    workdir = Path(tempfile.gettempdir()) / "papermind_extract" / _pdf_hash(pdf_path)
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
        result.tables = extract_tables(pdf_path)
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
    result.metadata["table_count"] = len(result.tables)
