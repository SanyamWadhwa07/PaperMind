"""Table extraction: grid cleanup, table/prose discrimination, and rendering.

The detector's hard problem is not finding grids — it is deciding which grids
are tables. The borderless strategy grids an entire page, so body paragraphs
arrive looking structurally identical to data rows. Most of these tests pin that
boundary.
"""

import pytest

from core.pipeline.table_extractor import (
    TableInfo,
    _is_plausible_table,
    _isolate_table_block,
    _looks_like_data,
    _merge_split_columns,
    _normalise,
    _split_caption,
    _to_markdown,
    _trim_to_numeric_signature,
    tables_to_markdown,
)


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
