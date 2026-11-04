"""Caption-anchored figure recovery in core/pipeline/pdf_extractor.py.

Each test pins a layout that used to lose a figure on a real arXiv paper:
sub-panel labels in the caption's block (2001.08844), a thin strip of samples
(1406.2661), a figure overhanging the gutter (2001.08844), a page-wide grid
under a short centred caption, section numbering ("Figure 3.1", 2005.14165),
and stacked figures whose regions ran into each other.
"""

import pytest

from core.pipeline import pdf_extractor as px

fitz = pytest.importorskip("fitz", reason="PyMuPDF (fitz) required")

PROSE = ("This paragraph is long enough to be body text rather than a label, so "
         "it bounds a figure region the way a real paragraph does on a page of a "
         "paper. ") * 2


def _page(draw):
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    draw(page)
    return doc, page


def _labels(page):
    return [label for _, label, _ in px._caption_blocks(page)]


# ── Caption detection ─────────────────────────────────────────────────────────

def test_caption_after_subpanel_label_in_same_block():
    doc, page = _page(lambda p: p.insert_text((72, 400), "(c)\nFigure 5: The confusion matrices."))
    assert _labels(page) == ["5"]
    doc.close()


@pytest.mark.parametrize("text", [
    "Figure 3 shows that the model converges.",
    "results improve further as shown in the next experiment and in\nFigure 2. We then ablate.",
])
def test_references_are_not_captions(text):
    doc, page = _page(lambda p: p.insert_text((72, 400), text))
    assert _labels(page) == []
    doc.close()


@pytest.mark.parametrize("text, label", [
    ("Figure 3.1: Smooth scaling of performance.", "3.1"),
    ("Figure G.12: Formatted dataset example.", "G.12"),
    ("Fig. 4 Overview of the network", "4"),
])
def test_caption_labels_keep_section_numbering(text, label):
    doc, page = _page(lambda p: p.insert_text((72, 400), text))
    assert _labels(page) == [label]
    doc.close()


def test_dotted_reference_does_not_backtrack_to_a_shorter_label():
    doc, page = _page(lambda p: p.insert_text((72, 400), "Figure 4.2 shows contamination."))
    assert _labels(page) == []
    doc.close()


# ── Region growth ─────────────────────────────────────────────────────────────

def test_thin_strip_is_a_figure():
    # A row of interpolated samples: 340pt wide, 19pt tall.
    region = px._figure_region((125, 115, 487, 125), [(135, 82, 477, 101)], [])
    assert region == (135, 82, 477, 101)


def test_rule_is_not_a_figure():
    assert px._figure_region((125, 115, 487, 125), [(135, 100, 477, 104)], []) is None


def test_figure_centred_over_a_short_caption():
    # A chart 50pt wider than its caption on each side.
    region = px._figure_region((216, 266, 396, 276), [(166, 72, 446, 259)], [])
    assert region == (166, 72, 446, 259)


def test_next_columns_prose_trims_the_side_not_the_top():
    # 2001.08844 Fig. 3: a left-column diagram whose side boxes reach x=338,
    # past where the right column's text starts at x=323.
    caption = (43, 478, 292, 490)
    ink = [(43, 113, 300, 466), (300, 200, 338, 260)]
    right_column_prose = [(323, 287, 580, 349), (323, 359, 571, 442)]
    assert px._figure_region(caption, ink, right_column_prose) == (43, 113, 321, 466)


def test_same_column_prose_still_bounds_the_top():
    caption = (72, 400, 540, 410)
    ink = [(72, 100, 540, 200), (72, 250, 540, 390)]
    region = px._figure_region(caption, ink, [(72, 205, 540, 245)])
    assert region[1] > 245


def test_render_page_wide_grid_and_stacked_figures(tmp_path):
    def draw(page):
        # A 3x2 grid of panels under one short centred caption...
        for col in range(3):
            for row in range(2):
                x, y = 80 + col * 160, 80 + row * 90
                page.draw_rect(fitz.Rect(x, y, x + 130, y + 75), fill=(0.2, 0.4, 0.8))
        page.insert_text((250, 270), "Figure 1: All results.")
        # ...and a second figure directly below it, captioned separately.
        page.draw_rect(fitz.Rect(150, 290, 460, 400), fill=(0.8, 0.3, 0.2))
        page.insert_text((250, 420), "Figure 2: Another result.")
        page.insert_textbox(fitz.Rect(72, 460, 540, 560), PROSE, fontsize=10)

    doc, _ = _page(draw)
    pdf = tmp_path / "grid.pdf"
    doc.save(str(pdf))
    doc.close()

    figures, _ = px._render_figures(str(pdf), tmp_path / "out")
    by_label = {f.figure_number: f for f in figures}
    assert set(by_label) == {"Figure 1", "Figure 2"}
    # Figure 1 spans all three columns of panels (80..530pt at 200 dpi).
    assert by_label["Figure 1"].width >= (530 - 80) * 200 / 72 - 10
    # Figure 2 stops at Figure 1's caption instead of absorbing the grid.
    assert by_label["Figure 2"].height <= (400 - 270) * 200 / 72
