"""Table extraction from academic PDFs.

Academic tables come in two flavours and need different detection:

* **Ruled** — drawn with visible lines. Common in clinical, biological and
  social-science papers. Detected precisely by following the rules themselves.
* **Borderless** — aligned by whitespace only, no rules at all. The house style
  of arXiv/NeurIPS/ACL papers, and the reason a line-based extractor reports
  zero tables on most CS papers.

Both strategies run and their results are merged, because a single paper often
contains both. Output serves two consumers with different needs:

* the LLM, which reads ``markdown`` to pull out quantitative results — minor
  column-splitting noise is harmless here;
* the UI, which renders the same Markdown, so captions and empty rows/columns
  are stripped rather than passed through.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import List, Optional, Sequence

import structlog

logger = structlog.get_logger(__name__)

# Grids outside these bounds are page furniture or mis-detected prose, not tables.
_MIN_ROWS = 2
_MIN_COLS = 2
_MAX_COLS = 20

# Fraction of cells that must be non-empty. The text strategy legitimately
# produces sparse grids, so this is deliberately lower than it would be for
# ruled tables.
_MIN_DENSITY = 0.3

# "Table 3:", "TABLE IV -", "Table 2." — the caption often bleeds into the grid
# as leading rows, so the same pattern both detects and removes it.
_CAPTION_RE = re.compile(
    r"^\s*(?:table|tab\.)\s*([0-9]+|[IVXLC]+)"
    r"(?:\s*[.:\-–—)]\s*|\s+(?=[A-Z]))"      # separator, or a capitalised continuation
    r"(.*)$",
    re.IGNORECASE,
)

# Two tables found by different strategies are the same table if their boxes
# overlap by more than this fraction of the smaller box.
_OVERLAP_THRESHOLD = 0.5

# Table detection is CPU-bound and local; anything slower than this is a hang.
_SUBPROCESS_TIMEOUT_S = 120


@dataclass
class TableInfo:
    """One extracted table, ready for both LLM consumption and display."""

    markdown: str
    caption: str = ""
    page_number: int = 0            # 1-based, as printed
    n_rows: int = 0
    n_cols: int = 0
    bbox: tuple = field(default=(0.0, 0.0, 0.0, 0.0), repr=False)

    @property
    def label(self) -> str:
        """'Table 2' when the caption names it, else a page reference."""
        m = _CAPTION_RE.match(self.caption)
        return f"Table {m.group(1)}" if m else f"Table (page {self.page_number})"


# How many cells must agree on a line count before a grid row is treated as a
# stack of rows. One cell agreeing with itself proves nothing: a single long
# value that merely wrapped also arrives as two lines.
_MIN_AGREEING_CELLS = 2


def _split_wrapped_rows(
    grid: Sequence[Sequence[Optional[str]]],
) -> List[List[str]]:
    """Explode grid rows whose cells each hold a whole column of stacked values.

    Academic papers rule their tables with booktabs — ``\\toprule``, one
    ``\\midrule`` under the header, ``\\bottomrule`` — and draw nothing between
    data rows. A line-based detector derives row boundaries from those rules, so
    it sees three horizontal bands and returns every data row merged into the
    middle one::

        ['LAION-CLAP\\nSALM-s\\nSALM', '2.3%\\n7.9%\\n8.4%', '-\\n4.2°\\n1.8°']

    The original row breaks survive only as newlines inside each cell, and
    :func:`_normalise` collapses those to spaces — which is what turned a
    four-row results table into one run-on line. Splitting here, before
    normalisation, is the last point at which the structure is still readable.
    """
    out: List[List[str]] = []

    for row in grid or []:
        cells = [(c or "") for c in (row or [])]
        parts = [c.split("\n") for c in cells]
        counts = [len(p) for p, c in zip(parts, cells) if c.strip()]

        if not counts:
            out.append(cells)
            continue

        # The row's real height is the line count most cells agree on; ties go to
        # the taller reading, since a cell that wrapped is a subset of one that
        # stacked.
        target = max(set(counts), key=lambda n: (counts.count(n), n))
        if target < 2 or counts.count(target) < _MIN_AGREEING_CELLS:
            out.append(cells)
            continue

        for i in range(target):
            new_row: List[str] = []
            for cell, piece in zip(cells, parts):
                if not cell.strip():
                    new_row.append("")
                elif len(piece) == 1:
                    # One line where its neighbours have many: a label spanning
                    # the block. Anchor it to the first row rather than repeating
                    # it down every one.
                    new_row.append(piece[0] if i == 0 else "")
                else:
                    new_row.append(piece[i] if i < len(piece) else "")
            out.append(new_row)

    return out


def _normalise(grid: Sequence[Sequence[Optional[str]]]) -> List[List[str]]:
    """Collapse whitespace, escape pipes, and drop empty rows and columns."""
    rows: List[List[str]] = []
    for row in grid or []:
        cells = [re.sub(r"\s+", " ", (c or "").replace("|", r"\|")).strip() for c in (row or [])]
        if any(cells):
            rows.append(cells)

    if not rows:
        return []

    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]

    keep = [i for i in range(width) if any(r[i] for r in rows)]
    return [[r[i] for i in keep] for r in rows]


def _split_caption(rows: List[List[str]]) -> tuple[str, List[List[str]]]:
    """Peel caption rows off the top of a grid.

    The text strategy has no way to know a caption isn't data, so it slices the
    caption across however many columns it detected. Joining the row back
    together recovers it — which both yields the caption and removes it from the
    table body.
    """
    caption_parts: List[str] = []
    body = list(rows)

    while body:
        joined = re.sub(r"\s+", " ", " ".join(body[0])).strip()
        # A caption row starts with "Table N", or continues one already started
        # and carries no numeric data of its own.
        starts_caption = bool(_CAPTION_RE.match(joined)) and not _looks_like_data(body[0])
        continues_caption = bool(caption_parts) and not _looks_like_data(body[0]) and len(joined) > 40
        if starts_caption or continues_caption:
            caption_parts.append(joined)
            body = body[1:]
            continue
        break

    return " ".join(caption_parts).strip(), body


# A cell longer than this is a sentence, not a table value.
_MAX_CELL_WORDS = 6

# A reported value is terse — "23.75", "O(n2 · d)", "3.5 days". Anything wordier
# is a description of a value, not the value itself.
_MAX_VALUE_WORDS = 4

# Bracketed reference markers — "[33]", "[1, 2]", "[4–7]". These are the reason a
# plain "does this cell contain a digit?" test cannot tell a results row from a
# body paragraph, and why "Table 2: …" captions were read as data.
_CITATION_RE = re.compile(r"\[\s*\d+(?:\s*[,;–—-]\s*\d+)*\s*\]")


def _is_value_cell(cell: str) -> bool:
    """True if the cell reports a measurement rather than naming or describing one.

    Digits alone are not enough — reference markers and table numbers put digits
    into prose. But a digit/letter ratio is too blunt in the other direction: a
    complexity column of ``O(n²·d)`` and ``O(log n)`` is all values and mostly
    letters. What actually separates them is length: values are terse, prose is
    not.
    """
    stripped = _CITATION_RE.sub("", cell).strip()
    if not stripped or _CAPTION_RE.match(stripped):
        return False
    if len(stripped.split()) > _MAX_VALUE_WORDS:
        return False
    return any(ch.isdigit() for ch in stripped)


def _looks_like_data(row: Sequence[str]) -> bool:
    """True if the row holds several short cells and reports at least one value."""
    filled = [c for c in row if c]
    if len(filled) < 2:
        return False
    if sum(1 for c in filled if len(c.split()) > _MAX_CELL_WORDS) >= 2:
        return False
    if not any(_is_value_cell(c) for c in filled):
        return False
    return sum(1 for c in filled if len(c) <= 25) >= len(filled) * 0.6


def _looks_like_header(row: Sequence[str]) -> bool:
    """A column-label row: short cells, no prose, not necessarily numeric."""
    filled = [c for c in row if c]
    if not filled:
        return False
    return all(len(c.split()) <= 5 for c in filled)


def _isolate_table_block(rows: List[List[str]]) -> List[List[str]]:
    """Cut the actual table out of a page-sized grid.

    The borderless ("text") strategy grids an entire page, so a detected region
    covers the surrounding body paragraphs as well as the table. The table is the
    longest run of consecutive data rows; the label row immediately above it is
    the header.
    """
    if not rows:
        return []

    flags = [_looks_like_data(r) for r in rows]

    best_start, best_len = 0, 0
    run_start = None
    for i, is_data in enumerate([*flags, False]):        # sentinel closes a trailing run
        if is_data and run_start is None:
            run_start = i
        elif not is_data and run_start is not None:
            if i - run_start > best_len:
                best_start, best_len = run_start, i - run_start
            run_start = None

    if best_len < _MIN_ROWS:
        return []

    body = _trim_to_numeric_signature(rows[best_start:best_start + best_len])
    if len(body) < _MIN_ROWS:
        return []
    best_len = len(body)

    # Absorb up to two header rows directly above the data block.
    start = best_start
    for _ in range(2):
        if start > 0 and _looks_like_header(rows[start - 1]):
            start -= 1
        else:
            break

    block = rows[start:best_start] + body
    # Re-drop columns that are empty within this narrower slice.
    return _normalise(block)


def _trim_to_numeric_signature(block: List[List[str]]) -> List[List[str]]:
    """Drop edge rows that don't report numbers where the table's value columns are.

    A body paragraph adjacent to the table survives the run detection when the
    grid splits it into short cells and it happens to contain a citation marker
    like "[33]". Real value rows all carry numbers in the same few columns, so
    that shared signature separates them from neighbouring prose.
    """
    if not block:
        return block

    width = len(block[0])
    numeric_cols = {
        col for col in range(width)
        if sum(1 for row in block if _is_value_cell(row[col])) >= len(block) * 0.5
    }
    if not numeric_cols:
        return block

    def carries_values(row: List[str]) -> bool:
        return any(_is_value_cell(row[col]) for col in numeric_cols)

    start, end = 0, len(block)
    while start < end and not carries_values(block[start]):
        start += 1
    while end > start and not carries_values(block[end - 1]):
        end -= 1
    return block[start:end]


def _is_plausible_table(rows: List[List[str]]) -> bool:
    """Reject grids that are really figures, headers, or multi-column body text."""
    if len(rows) < _MIN_ROWS:
        return False
    n_cols = len(rows[0])
    if not _MIN_COLS <= n_cols <= _MAX_COLS:
        return False

    filled = sum(1 for row in rows for c in row if c)
    if filled / (len(rows) * n_cols) < _MIN_DENSITY:
        return False

    # A result table always reports numbers somewhere below its header.
    return any(re.search(r"\d", c) for row in rows[1:] for c in row)


def _merge_split_columns(rows: List[List[str]]) -> List[List[str]]:
    """Rejoin columns that cut through the middle of a word.

    Whitespace-based column detection places a boundary wherever a gap happens to
    line up, which on ragged label columns slices tokens in half —
    ``Deep-Att + PosU`` | ``nk [39]``. A boundary is spurious when the left cell
    ends mid-token and the right cell resumes mid-token on most rows.
    """
    if not rows or len(rows[0]) < 2:
        return rows

    width = len(rows[0])
    merge_after = set()
    for col in range(width - 1):
        pairs = [(r[col], r[col + 1]) for r in rows if r[col] and r[col + 1]]
        if len(pairs) < 2:
            continue
        # Left ends on a word character, right resumes lowercase or with closing
        # punctuation — i.e. the two halves belong to one token.
        splits = sum(
            1 for left, right in pairs
            if re.search(r"\w$", left) and re.match(r"[a-z)\]]", right)
        )
        if splits >= len(pairs) * 0.5:
            merge_after.add(col)

    # Merging is a repair, not a restructure: collapsing every boundary would
    # destroy a table rather than fix it.
    if not merge_after or width - len(merge_after) < _MIN_COLS:
        return rows

    merged: List[List[str]] = []
    for row in rows:
        out: List[str] = []
        buffer = row[0]
        for col in range(1, width):
            if col - 1 in merge_after:
                buffer = f"{buffer}{row[col]}" if buffer and row[col] else (buffer or row[col])
            else:
                out.append(buffer)
                buffer = row[col]
        out.append(buffer)
        merged.append(out)
    return merged


def _to_markdown(rows: List[List[str]]) -> str:
    header, body = rows[0], rows[1:]
    n = len(header)
    # A blank header renders as an unreadable empty row; number the columns instead.
    if not any(header):
        header = [f"col {i + 1}" for i in range(n)]
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(["---"] * n) + " |",
    ]
    lines.extend("| " + " | ".join(r) + " |" for r in body)
    return "\n".join(lines)


def _overlaps(a: tuple, b: tuple) -> bool:
    """True if two bounding boxes cover substantially the same region."""
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    ix = max(0.0, min(ax1, bx1) - max(ax0, bx0))
    iy = max(0.0, min(ay1, by1) - max(ay0, by0))
    inter = ix * iy
    if inter <= 0:
        return False
    smaller = min((ax1 - ax0) * (ay1 - ay0), (bx1 - bx0) * (by1 - by0))
    return smaller > 0 and inter / smaller >= _OVERLAP_THRESHOLD


def _caption_near(page, bbox: tuple) -> str:
    """Find a 'Table N: …' line just above or below the table on the page."""
    try:
        x0, y0, x1, y1 = bbox
        margin = 60.0
        band = (max(x0 - 20, 0), max(y0 - margin, 0), x1 + 20, y1 + margin)
        text = page.get_textbox(band) or ""
    except Exception:
        return ""

    for line in text.splitlines():
        line = re.sub(r"\s+", " ", line).strip()
        if _CAPTION_RE.match(line) and len(line) > 8:
            return line
    return ""


def _process_is_polluted() -> bool:
    """True if something in this process has already altered PyMuPDF's geometry.

    ``pymupdf4llm`` calls ``TOOLS.unset_quad_corrections(True)`` at *import* time
    (``helpers/pymupdf_rag.py``, module level), which changes character bounding
    boxes process-wide and cannot be undone by resetting the flag — the effect
    survives. Table detection clusters cells by geometry, so once that import has
    happened, ``23.75`` comes back as ``2375\\n.``.

    Since the Markdown backend is normally imported before enrichment runs, the
    common path is the polluted one.
    """
    return "pymupdf4llm" in sys.modules


def _extract_in_subprocess(
    pdf_path: str, max_tables: int,
) -> Optional[tuple[List[TableInfo], Optional[str]]]:
    """Run extraction in a clean interpreter.

    Returns ``(tables, error)`` — where ``error`` is the child's *own* extraction
    error, not a failure to run the child — or ``None`` if the subprocess could
    not be run or its output could not be read. Those are different outcomes:
    ``None`` means "retry, then fall back in-process"; ``([], "no such file")``
    means the extraction genuinely failed and no fallback will do better.
    """
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "core.pipeline.table_extractor", pdf_path, str(max_tables)],
            capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT_S,
            cwd=str(Path(__file__).resolve().parents[2]),
        )
    except subprocess.TimeoutExpired:
        # Not a crash — the subprocess was still running. On a machine under
        # concurrent load (other pipeline agents, a stalled MinerU model-load
        # attempt) this is far more likely to fire than on an idle box, which is
        # exactly the gap that made this look like a code regression rather than
        # a load-dependent timeout.
        logger.warning("table_subprocess_timeout", timeout_s=_SUBPROCESS_TIMEOUT_S)
        return None
    except Exception as exc:
        logger.warning("table_subprocess_failed", error=str(exc))
        return None

    if proc.returncode != 0:
        logger.warning("table_subprocess_nonzero", returncode=proc.returncode,
                       stderr=(proc.stderr or "")[-300:])
        return None

    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        logger.warning("table_subprocess_bad_json", error=str(exc))
        return None

    # A bare list is the pre-v2 payload shape. Accepted for one release so a
    # rolling deploy — where a new parent can meet an old child module on a
    # half-updated image — degrades to the old behaviour instead of hard-failing.
    if isinstance(payload, list):
        return [TableInfo(**row) for row in payload], None

    if not isinstance(payload, dict):
        logger.warning("table_subprocess_bad_payload", payload_type=type(payload).__name__)
        return None

    rows = payload.get("tables") or []
    error = payload.get("error")
    if error:
        # The child caught this itself and still exited 0, so neither the return
        # code nor stderr carries it. Without this branch the parent reads a
        # crashed extraction as "this paper has no tables" and the UI renders the
        # calm empty state — the bug this whole return shape exists to fix.
        logger.warning("table_subprocess_extraction_error", error=error)
    return [TableInfo(**row) for row in rows], error


def extract_tables(pdf_path: str, max_tables: int = 40) -> List[TableInfo]:
    """Extract tables from a PDF, ruled and borderless alike.

    Runs in a subprocess when this process has already imported ``pymupdf4llm``,
    because that import silently corrupts cell geometry (see
    :func:`_process_is_polluted`). Falls back to in-process extraction — degraded
    but not absent — if the subprocess cannot run.

    Returns an empty list rather than raising: "no tables" and "extraction
    failed" are both the caller's to handle, and the failure is logged. Use
    :func:`extract_tables_with_status` when the caller needs to tell those two
    apart — a bare empty list can't.
    """
    tables, _ = extract_tables_with_status(pdf_path, max_tables)
    return tables


def extract_tables_with_status(
    pdf_path: str, max_tables: int = 40,
) -> tuple[List[TableInfo], Optional[str]]:
    """Like :func:`extract_tables`, but also reports a hard failure.

    "No tables in this paper" and "table extraction crashed" both currently
    render as the same reassuring empty state in the UI — see
    ``pipeline_status`` in ``core/agent_integration.py`` and
    ``TablesDisplay.jsx``. This is the source of that distinction for the
    extraction step itself: ``error`` is set only when the extraction loop
    itself raised, not merely because a page or a strategy failed (those are
    routine and already logged per-occurrence at debug/warning level).
    """
    if _process_is_polluted():
        outcome = _extract_in_subprocess(pdf_path, max_tables)
        if outcome is None:
            # One retry: the common failure here is a timeout caused by
            # transient contention (a sibling agent's LLM call, a MinerU
            # model-load attempt), not a deterministic crash, so trying again
            # clears most of them.
            logger.info("table_subprocess_retrying")
            outcome = _extract_in_subprocess(pdf_path, max_tables)

        if outcome is not None:
            # The child's own extraction error travels back with the rows. It
            # used to be dropped here, which is what turned every hard failure
            # into an indistinguishable "no tables in this paper".
            return outcome

        # Both attempts failed. Falling back to in-process extraction on
        # possibly-corrupted geometry (see _process_is_polluted) used to return
        # here as plain (tables, None) — indistinguishable from "this paper has
        # no tables". A degraded result is reported as a degraded result, even
        # when the fallback happens to find something, since corrupted geometry
        # can silently drop rows/tables rather than raising.
        logger.warning("table_extraction_degraded",
                       reason="subprocess unavailable after retry; cell geometry may be corrupted")
        try:
            import fitz  # type: ignore
        except ImportError:
            logger.warning("table_extraction_unavailable", reason="PyMuPDF not installed")
            return [], "PyMuPDF is not installed"
        tables, impl_error = _extract_tables_impl(fitz, pdf_path, max_tables)
        error = impl_error or "table extraction subprocess failed twice; result may be degraded"
        return tables, error

    try:
        import fitz  # type: ignore
    except ImportError:
        logger.warning("table_extraction_unavailable", reason="PyMuPDF not installed")
        return [], "PyMuPDF is not installed"

    return _extract_tables_impl(fitz, pdf_path, max_tables)


def _extract_tables_impl(
    fitz, pdf_path: str, max_tables: int,
) -> tuple[List[TableInfo], Optional[str]]:
    tables: List[TableInfo] = []
    try:
        doc = fitz.open(pdf_path)
        for page_index, page in enumerate(doc):
            # Ruled tables first: higher precision, so they win any overlap.
            found: List[tuple] = []
            for strategy in ("lines_strict", "text"):
                try:
                    detected = page.find_tables(strategy=strategy).tables
                except Exception as exc:
                    logger.debug("table_strategy_failed", strategy=strategy,
                                 page=page_index + 1, error=str(exc))
                    continue

                for table in detected:
                    bbox = tuple(table.bbox)
                    if any(_overlaps(bbox, seen) for seen, _, _ in found):
                        continue
                    found.append((bbox, table, strategy))

            for bbox, table, strategy in found:
                try:
                    rows = _normalise(_split_wrapped_rows(table.extract()))
                except Exception as exc:
                    logger.debug("table_extract_failed", page=page_index + 1, error=str(exc))
                    continue

                grid_caption, rows = _split_caption(rows)
                # Prefer the caption read from page text: rebuilding it from grid
                # cells reinserts a space at every column boundary, giving
                # "Transform er achieves better BL EU scores".
                caption = _caption_near(page, bbox) or grid_caption

                if strategy == "text":
                    # This strategy grids whole pages, so it needs both a caption
                    # to confirm a table is present and a block cut to find it.
                    # Without these it reports body paragraphs as 40-row tables.
                    if not caption:
                        continue
                    rows = _isolate_table_block(rows)

                rows = _merge_split_columns(rows)
                if not _is_plausible_table(rows):
                    continue

                tables.append(TableInfo(
                    markdown=_to_markdown(rows),
                    caption=caption,
                    page_number=page_index + 1,
                    n_rows=len(rows),
                    n_cols=len(rows[0]),
                    bbox=bbox,
                ))
                if len(tables) >= max_tables:
                    doc.close()
                    return tables, None
        doc.close()
    except Exception as exc:
        logger.warning("table_extraction_failed", error=str(exc), pdf=pdf_path)
        return tables, str(exc)

    return tables, None


def tables_to_markdown(tables: Sequence[TableInfo]) -> List[str]:
    """Render tables as captioned Markdown blocks for the summarisation prompt."""
    blocks = []
    for t in tables:
        head = t.caption or f"{t.label}"
        blocks.append(f"{head}\n{t.markdown}")
    return blocks


def _main(argv: Sequence[str]) -> int:
    """Emit tables as JSON. Used by :func:`_extract_in_subprocess`.

    Exists so extraction can run in an interpreter that has never imported
    ``pymupdf4llm``; see :func:`_process_is_polluted`.

    The parent reads ``proc.stdout`` and parses it as JSON, so stdout carries
    *only* the payload. This process is never configured by
    ``backend/api/logging_config.py`` (it's a bare ``python -m`` invocation), so
    structlog falls back to its own default — ``PrintLoggerFactory()``, which also
    writes to stdout. Any ``logger.debug``/``logger.warning`` call inside
    ``_extract_tables_impl`` (there are several, on a per-page strategy failure)
    used to prepend a log line to the payload, making it fail to parse as JSON and
    silently falling back to in-process extraction on the corrupted geometry this
    subprocess exists to avoid. Logs go to stderr instead, which the parent already
    captures and excerpts on a non-zero exit.

    The payload is ``{"tables": [...], "error": <str|null>}``. It carries the
    error half because ``_extract_tables_impl`` catches its own exceptions and
    returns them rather than raising — so a hard failure still exits 0 with an
    empty list, and the parent has no other way to tell it apart from a paper
    that genuinely has no tables. Emitting only the list is what made every
    table failure surface in the UI as the reassuring "No tables detected".
    """
    if not argv:
        print("usage: python -m core.pipeline.table_extractor <pdf> [max_tables]",
              file=sys.stderr)
        return 2

    structlog.configure(
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
    )

    pdf_path = argv[0]
    max_tables = int(argv[1]) if len(argv) > 1 else 40

    import fitz  # type: ignore
    tables, error = _extract_tables_impl(fitz, pdf_path, max_tables)
    json.dump({"tables": [asdict(t) for t in tables], "error": error}, sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
