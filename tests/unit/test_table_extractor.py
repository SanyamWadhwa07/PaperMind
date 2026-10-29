"""Table extraction: grid cleanup, table/prose discrimination, and rendering.

The detector's hard problem is not finding grids — it is deciding which grids
are tables. The borderless strategy grids an entire page, so body paragraphs
arrive looking structurally identical to data rows. Most of these tests pin that
boundary.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from core.pipeline import table_extractor
from core.pipeline.table_extractor import (
    TableInfo,
    _is_plausible_table,
    _isolate_table_block,
    _looks_like_data,
    _merge_split_columns,
    _normalise,
    _split_caption,
    _split_wrapped_rows,
    _to_markdown,
    _trim_to_numeric_signature,
    tables_to_markdown,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


# ── Grid normalisation ────────────────────────────────────────────────────────

def test_normalise_drops_empty_rows_and_columns():
    grid = [
        ['Model', '', 'BLEU', ''],
        ['', '', '', ''],
        ['ByteNet', '', '23.75', ''],
    ]
    assert _normalise(grid) == [['Model', 'BLEU'], ['ByteNet', '23.75']]


def test_normalise_pads_ragged_rows():
    assert _normalise([['a', 'b', 'c'], ['d']]) == [['a', 'b', 'c'], ['d', '', '']]


def test_normalise_escapes_pipes_so_markdown_survives():
    assert _normalise([['a|b', 'c'], ['1', '2']])[0][0] == r'a\|b'


# ── Caption handling ──────────────────────────────────────────────────────────

def test_split_caption_recovers_caption_sliced_across_columns():
    """The text strategy cuts the caption into cells; joining recovers it."""
    grid = [
        ['Table 2: The Trans', 'former achieves', 'better BLEU scores'],
        ['Model', 'EN-DE', 'EN-FR'],
        ['ByteNet', '23.75', '39.2'],
    ]
    caption, body = _split_caption(grid)
    assert caption.startswith('Table 2:')
    assert 'BLEU' in caption
    assert body[0] == ['Model', 'EN-DE', 'EN-FR']


def test_split_caption_leaves_data_alone():
    grid = [['Model', 'EN-DE'], ['ByteNet', '23.75']]
    caption, body = _split_caption(grid)
    assert caption == ''
    assert body == grid


def test_label_falls_back_to_page_when_uncaptioned():
    assert TableInfo(markdown='', caption='Table 4: Results', page_number=9).label == 'Table 4'
    assert TableInfo(markdown='', caption='', page_number=9).label == 'Table (page 9)'


# ── Table vs prose ────────────────────────────────────────────────────────────

def test_data_row_recognised():
    assert _looks_like_data(['ByteNet [18]', '23.75', '39.2'])


def test_prose_row_rejected():
    assert not _looks_like_data([
        'We apply dropout to the output of each sub-layer before it is added',
        'and normalised, following prior work on regularisation [33]',
    ])


def test_single_value_row_is_not_data():
    assert not _looks_like_data(['23.75', '', ''])


@pytest.mark.parametrize('grid, reason', [
    ([['a', 'b']], 'only one row'),
    ([['only'], ['one']], 'only one column'),
    ([['h'] * 25, ['v'] * 25], 'absurdly wide'),
    ([['Model', 'Score'], ['BERT', 'good']], 'no numbers anywhere'),
])
def test_implausible_grids_rejected(grid, reason):
    assert not _is_plausible_table(_normalise(grid)), reason


def test_plausible_result_table_accepted():
    grid = _normalise([['Model', 'BLEU'], ['ByteNet', '23.75'], ['ConvS2S', '25.16']])
    assert _is_plausible_table(grid)


# ── Cutting the table out of a page-sized grid ────────────────────────────────

def test_isolate_table_block_discards_surrounding_prose():
    page_grid = [
        ['The dominant sequence transduction', 'models are based on complex', 'recurrent networks'],
        ['We propose the Transformer, based', 'solely on attention mechanisms', 'dispensing with recurrence'],
        ['Model', 'EN-DE', 'EN-FR'],
        ['ByteNet', '23.75', '39.2'],
        ['ConvS2S', '25.16', '40.46'],
        ['Transformer', '28.4', '41.8'],
        ['Residual Dropout We apply', 'dropout [33] to the output', 'of each sub-layer'],
    ]
    block = _isolate_table_block(page_grid)

    flat = ' '.join(c for row in block for c in row)
    assert 'ByteNet' in flat and 'Transformer' in flat
    assert 'dominant sequence' not in flat, 'leading prose leaked into the table'
    assert 'Residual Dropout' not in flat, 'trailing prose leaked into the table'


def test_isolate_keeps_header_above_data():
    grid = [
        ['Some introductory sentence about the method', 'that runs on for a while here', 'and continues'],
        ['Model', 'Accuracy', 'F1'],
        ['BERT', '0.91', '0.89'],
        ['RoBERTa', '0.93', '0.92'],
    ]
    assert _isolate_table_block(grid)[0] == ['Model', 'Accuracy', 'F1']


def test_trim_uses_numeric_column_signature():
    """A prose row split into short cells still lacks numbers in the value columns."""
    block = [
        ['ByteNet', '23.75', '39.2'],
        ['ConvS2S', '25.16', '40.46'],
        ['We apply dropout [33] t', 'o the output', 'of each sub'],
    ]
    trimmed = _trim_to_numeric_signature(block)
    assert len(trimmed) == 2
    assert all('dropout' not in c for row in trimmed for c in row)


# ── Column repair ─────────────────────────────────────────────────────────────

def test_merge_split_columns_rejoins_broken_tokens():
    """Whitespace column detection slices tokens: 'PosU' | 'nk [39]'."""
    rows = [
        ['Deep-Att + PosU', 'nk [39]', '39.2'],
        ['GNMT + RL En', 'semble [38]', '41.16'],
        ['ConvS2S Ensem', 'ble [9]', '41.29'],
    ]
    merged = _merge_split_columns(rows)
    assert merged[0][0] == 'Deep-Att + PosUnk [39]'
    assert merged[1][0] == 'GNMT + RL Ensemble [38]'
    assert merged[2][1] == '41.29', 'value column must survive intact'


def test_merge_leaves_genuine_columns_alone():
    rows = [['EN-DE', 'EN-FR'], ['23.75', '39.2'], ['25.16', '40.46']]
    assert _merge_split_columns(rows) == rows


# ── Rendering ─────────────────────────────────────────────────────────────────

def test_markdown_has_header_separator_and_all_rows():
    md = _to_markdown([['Model', 'BLEU'], ['ByteNet', '23.75']])
    lines = md.splitlines()
    assert lines[0] == '| Model | BLEU |'
    assert lines[1] == '| --- | --- |'
    assert lines[2] == '| ByteNet | 23.75 |'


def test_markdown_numbers_blank_header_columns():
    """An all-empty header renders as an unreadable blank row otherwise."""
    md = _to_markdown([['', ''], ['ByteNet', '23.75']])
    assert md.splitlines()[0] == '| col 1 | col 2 |'


def test_tables_to_markdown_prefixes_caption_once():
    t = TableInfo(markdown='| a |\n| --- |', caption='Table 1: Results', page_number=3)
    block = tables_to_markdown([t])[0]
    assert block.startswith('Table 1: Results')
    assert block.count('Table 1') == 1, 'caption must not be duplicated'


# ── Wrapped-row splitting (booktabs tables merged into one line by the rules) ──

def test_split_wrapped_rows_explodes_stacked_cells():
    """A ruled booktabs table: the header rule and bottom rule bound one middle
    band, so a line-based detector returns every data row merged into it, with
    the original row breaks surviving only as \\n inside each cell."""
    grid = [
        ['Model', 'BLEU', 'COMET'],
        ['LAION-CLAP\nSALM-s\nSALM', '2.3\n7.9\n8.4', '-\n4.2\n1.8'],
    ]
    assert _split_wrapped_rows(grid) == [
        ['Model', 'BLEU', 'COMET'],
        ['LAION-CLAP', '2.3', '-'],
        ['SALM-s', '7.9', '4.2'],
        ['SALM', '8.4', '1.8'],
    ]


def test_split_wrapped_rows_anchors_single_line_label_to_first_row():
    """A label cell that didn't wrap (one line) next to cells that stacked N
    values is a span across the block, not data repeated N times."""
    grid = [['Ours', 'A\nB\nC', 'X\nY\nZ']]
    assert _split_wrapped_rows(grid) == [
        ['Ours', 'A', 'X'],
        ['', 'B', 'Y'],
        ['', 'C', 'Z'],
    ]


def test_split_wrapped_rows_leaves_unwrapped_rows_alone():
    grid = [['a', 'b'], ['c', 'd']]
    assert _split_wrapped_rows(grid) == grid


def test_split_wrapped_rows_requires_agreement_before_splitting():
    """One stacked cell against two single-line cells isn't enough agreement to
    infer the row's real height — could just as easily be a cell that itself
    wraps for width, not height."""
    grid = [['a\nb', 'c', 'd']]
    assert _split_wrapped_rows(grid) == grid


# ── Subprocess isolation (core/pipeline/table_extractor.py:_process_is_polluted,
#    _extract_in_subprocess, extract_tables, _main) ────────────────────────────
#
# pymupdf4llm corrupts PyMuPDF cell geometry process-wide on import, so table
# extraction re-runs in a clean subprocess whenever that import has already
# happened. These tests cover the isolation machinery itself — the part with no
# prior coverage — not the extraction logic already covered above.

def test_process_is_polluted_reflects_pymupdf4llm_import(monkeypatch):
    monkeypatch.delitem(sys.modules, 'pymupdf4llm', raising=False)
    assert table_extractor._process_is_polluted() is False

    monkeypatch.setitem(sys.modules, 'pymupdf4llm', object())
    assert table_extractor._process_is_polluted() is True


def test_extract_in_subprocess_returns_none_when_run_raises(monkeypatch):
    def _raise(*args, **kwargs):
        raise OSError('no interpreter')

    monkeypatch.setattr(table_extractor.subprocess, 'run', _raise)
    assert table_extractor._extract_in_subprocess('irrelevant.pdf', 10) is None


def test_extract_in_subprocess_returns_none_on_nonzero_exit(monkeypatch):
    class _Completed:
        returncode = 1
        stdout = ''
        stderr = 'boom'

    monkeypatch.setattr(table_extractor.subprocess, 'run', lambda *a, **k: _Completed())
    assert table_extractor._extract_in_subprocess('irrelevant.pdf', 10) is None


def test_extract_in_subprocess_returns_none_on_bad_json(monkeypatch):
    """The regression case: a log line landed on stdout ahead of the payload."""
    class _Completed:
        returncode = 0
        stdout = '2026-08-15 [debug] table_strategy_failed\n[]'
        stderr = ''

    monkeypatch.setattr(table_extractor.subprocess, 'run', lambda *a, **k: _Completed())
    assert table_extractor._extract_in_subprocess('irrelevant.pdf', 10) is None


_ROW = {
    'markdown': '| a |\n| --- |\n| b |', 'caption': 'Table 1', 'page_number': 1,
    'n_rows': 2, 'n_cols': 1, 'bbox': [0, 0, 1, 1],
}


def _fake_run(monkeypatch, stdout, returncode=0):
    class _Completed:
        pass
    _Completed.returncode = returncode
    _Completed.stdout = stdout
    _Completed.stderr = ''
    monkeypatch.setattr(table_extractor.subprocess, 'run', lambda *a, **k: _Completed())


def test_extract_in_subprocess_parses_legacy_list_payload(monkeypatch):
    """A bare list is the pre-v2 shape, kept working for one rolling deploy."""
    _fake_run(monkeypatch, json.dumps([_ROW]))
    outcome = table_extractor._extract_in_subprocess('irrelevant.pdf', 10)
    assert outcome is not None
    tables, error = outcome
    assert len(tables) == 1
    assert tables[0].caption == 'Table 1'
    assert error is None


def test_extract_in_subprocess_parses_valid_payload(monkeypatch):
    _fake_run(monkeypatch, json.dumps({'tables': [_ROW], 'error': None}))
    outcome = table_extractor._extract_in_subprocess('irrelevant.pdf', 10)
    assert outcome is not None
    tables, error = outcome
    assert len(tables) == 1
    assert tables[0].caption == 'Table 1'
    assert error is None


def test_extract_in_subprocess_surfaces_child_extraction_error(monkeypatch):
    """The child catches its own errors and still exits 0.

    ``_extract_tables_impl`` returns its exception as the status half of a tuple
    rather than raising, so a hard failure leaves returncode 0, empty stderr and
    an empty table list. Dropping the error half here is what made every table
    failure reach the UI as the reassuring "No tables detected" empty state.
    """
    _fake_run(monkeypatch, json.dumps({'tables': [], 'error': "no such file: 'x.pdf'"}))
    outcome = table_extractor._extract_in_subprocess('x.pdf', 10)
    assert outcome is not None
    tables, error = outcome
    assert tables == []
    assert error == "no such file: 'x.pdf'"


def test_extract_tables_with_status_propagates_child_error(monkeypatch):
    """End of the same wire: the error must reach the caller, not be zeroed."""
    monkeypatch.setitem(sys.modules, 'pymupdf4llm', object())
    monkeypatch.setattr(table_extractor, '_extract_in_subprocess',
                        lambda *a, **k: ([], 'boom'))
    tables, error = table_extractor.extract_tables_with_status('irrelevant.pdf')
    assert tables == []
    assert error == 'boom'


def test_extract_tables_uses_subprocess_result_when_process_polluted(monkeypatch):
    monkeypatch.setitem(sys.modules, 'pymupdf4llm', object())
    sentinel = [TableInfo(markdown='| x |\n| --- |\n| y |', caption='', page_number=1,
                          n_rows=2, n_cols=1, bbox=(0, 0, 1, 1))]
    monkeypatch.setattr(table_extractor, '_extract_in_subprocess',
                        lambda *a, **k: (sentinel, None))
    assert table_extractor.extract_tables('irrelevant.pdf') is sentinel


def test_extract_tables_falls_back_in_process_when_subprocess_unavailable(
    monkeypatch, test_pdf_path,
):
    monkeypatch.setitem(sys.modules, 'pymupdf4llm', object())
    monkeypatch.setattr(table_extractor, '_extract_in_subprocess', lambda *a, **k: None)
    # Degraded but not absent: falls through to in-process extraction rather than
    # raising, even though the pymupdf4llm import means the geometry may be off.
    result = table_extractor.extract_tables(test_pdf_path)
    assert isinstance(result, list)


def test_main_subprocess_stdout_is_pure_json_and_logs_go_to_stderr(test_pdf_path, tmp_path):
    """End-to-end regression test for the stdout/log collision.

    ``_main`` used to leave structlog on its unconfigured default
    (``PrintLoggerFactory()`` -> stdout), so any ``logger.debug``/``.warning`` call
    inside ``_extract_tables_impl`` — routine on a per-page strategy failure —
    corrupted the JSON payload the parent process parses from stdout, silently
    falling back to in-process extraction on the corrupted pymupdf4llm geometry
    this subprocess exists to avoid. This drives the real ``python -m
    core.pipeline.table_extractor`` entry point in a genuine child process (so a
    passing assertion here can't be explained by test-process state) and confirms
    a log call after extraction lands on stderr, never stdout.
    """
    driver = tmp_path / 'driver.py'
    driver.write_text(
        "import sys\n"
        f"sys.path.insert(0, {str(REPO_ROOT)!r})\n"
        "from core.pipeline.table_extractor import _main\n"
        "import structlog\n"
        f"code = _main([{str(test_pdf_path)!r}])\n"
        "structlog.get_logger('core.pipeline.table_extractor').warning(\n"
        "    'table_extraction_failed', error='synthetic')\n"
        "sys.exit(code)\n",
        encoding='utf-8',
    )
    proc = subprocess.run(
        [sys.executable, str(driver)], capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr

    payload = json.loads(proc.stdout)  # must parse cleanly — the whole point of the fix
    assert isinstance(payload, dict)
    assert isinstance(payload['tables'], list)
    assert payload['error'] is None  # this fixture is a readable PDF
    assert 'table_extraction_failed' not in proc.stdout
    assert 'table_extraction_failed' in proc.stderr
