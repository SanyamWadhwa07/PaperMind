"""Unit tests for core/pipeline/text_cleaner.py"""
import pytest
from core.pipeline.text_cleaner import (
    fix_hyphenation,
    fix_sentence_fragmentation,
    remove_page_artifacts,
    normalize_whitespace,
    deduplicate_sentences,
    clean_section,
    clean_all_sections,
)


def test_fix_hyphenation_basic():
    text = "The trans-\nformer model achieves state-of-the-art results."
    result = fix_hyphenation(text)
    assert "trans-\nformer" not in result
    assert "transformer" in result.lower()


def test_fix_hyphenation_preserves_inline_hyphens():
    text = "State-of-the-art results are reported."
    result = fix_hyphenation(text)
    assert "state-of-the-art" in result.lower()


def test_fix_hyphenation_soft_hyphen():
    text = "atten\u00adtion mechanism"
    result = fix_hyphenation(text)
    assert "\u00ad" not in result


def test_fix_sentence_fragmentation_joins_continuation():
    text = "The model was trained on\na large dataset containing\nmillions of examples."
    result = fix_sentence_fragmentation(text)
    # Lines not ending with period should be joined
    assert "\na large" not in result


def test_fix_sentence_fragmentation_preserves_paragraph_breaks():
    text = "First paragraph ends here.\n\nSecond paragraph starts here."
    result = fix_sentence_fragmentation(text)
    assert "\n\n" in result


def test_remove_page_artifacts_strips_repeated_headers():
    header = "Journal of Machine Learning Research\n"
    text = header * 3 + "Actual content about neural networks."
    result = remove_page_artifacts(text)
    assert result.count("Journal of Machine Learning Research") <= 1


def test_remove_page_artifacts_strips_page_numbers():
    text = "Some content.\n12\nMore content.\n13\nEnd."
    result = remove_page_artifacts(text)
    assert "\n12\n" not in result
    assert "\n13\n" not in result


def test_normalize_whitespace_collapses_spaces():
    text = "Too   many    spaces   here."
    result = normalize_whitespace(text)
    assert "  " not in result
    assert "Too many spaces here." == result


def test_normalize_whitespace_unicode():
    text = "caf\u00e9  model"
    result = normalize_whitespace(text)
    assert "  " not in result


def test_deduplicate_sentences_removes_near_duplicates():
    sentence = "The Transformer achieves state-of-the-art results on NMT benchmarks."
    text = sentence + " " + sentence + " Additional finding here."
    result = deduplicate_sentences(text, threshold=0.85)
    count = result.count("Transformer achieves")
    assert count == 1


def test_deduplicate_sentences_keeps_distinct():
    text = (
        "The model uses attention. "
        "The dataset contains images. "
        "Results show improvement."
    )
    result = deduplicate_sentences(text, threshold=0.85)
    assert "attention" in result
    assert "images" in result
    assert "improvement" in result


def test_clean_section_empty_string():
    assert clean_section("") == ""


def test_clean_section_runs_all_steps():
    text = "Re-\nsults show that BERT   outperforms LSTM.\n12\n"
    result = clean_section(text)
    assert "Re-\nsults" not in result
    assert "  " not in result


def test_clean_all_sections_applies_to_each():
    sections = {
        "abstract": "Short ab-\nstract.",
        "results": "Good re-\nsults here.",
        "__references__": "[1] Some reference.",
    }
    cleaned = clean_all_sections(sections)
    assert "ab-\nstract" not in cleaned["abstract"]
    assert "re-\nsults" not in cleaned["results"]
    # References section should be preserved unchanged
    assert "__references__" in cleaned
