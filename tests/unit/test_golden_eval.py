"""Scoring logic for the golden-set harness (`evals/golden_eval.py`).

The metrics these back are the ones a reviewer will read, so an error here
misreports quality rather than breaking a build. Number normalisation gets the
most attention because `pymupdf4llm` mangles decimals in prose — and a naive
comparison would score every correctly-extracted decimal as a hallucination,
producing a confidently wrong fidelity number.
"""

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _load(name, relative):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ge = _load("papermind_golden_eval", "evals/golden_eval.py")


# ── Number normalisation ──────────────────────────────────────────────────────

def test_pymupdf_decimal_artefact_is_repaired():
    """`28 _._ 4` is how "28.4" survives extraction. Treating it as 28 and 4
    would score a correct number as two wrong ones."""
    assert "28.4" in ge.normalise_numbers("a BLEU score of 28 _._ 4.")
    assert ge.numbers_in("a BLEU score of 28 _._ 4.") == ["28.4"]


def test_trailing_zeros_do_not_create_false_mismatches():
    assert ge.numbers_in("28.40 BLEU") == ge.numbers_in("28.4 BLEU")


def test_integers_are_preserved():
    assert ge.numbers_in("trained for 8 days and 12 hours") == ["8", "12"]


def test_digits_inside_hardware_names_are_extracted_too():
    """`P100` yields `100`. That is deliberate: it errs toward *matching*, so a
    model name repeated faithfully from the paper is never flagged invented."""
    assert ge.numbers_in("8 P100 GPUs") == ["8", "100"]


def test_normalising_empty_text_is_safe():
    assert ge.normalise_numbers("") == ""
    assert ge.numbers_in("") == []


# ── Classifier rates ──────────────────────────────────────────────────────────

def test_rates_on_a_perfect_classifier():
    out = ge._rates(tp=5, fp=0, fn=0, tn=5)
    assert (out["precision"], out["recall"], out["f1"], out["accuracy"]) == (1.0, 1.0, 1.0, 1.0)


def test_a_guard_that_passes_everything_scores_half_precision():
    """The failure mode actually observed: recall 1.0 looks excellent until you
    read precision next to it."""
    out = ge._rates(tp=8, fp=8, fn=0, tn=0)
    assert out["recall"] == 1.0
    assert out["precision"] == 0.5
    assert out["accuracy"] == 0.5


def test_rates_do_not_divide_by_zero():
    out = ge._rates(tp=0, fp=0, fn=0, tn=0)
    assert out["precision"] == 0.0 and out["f1"] == 0.0


def test_verdict_scoring_uses_the_shipped_decision():
    verdicts = [(True, True), (True, False), (False, False), (False, True)]
    out = ge._classify_verdicts(verdicts)
    assert (out["tp"], out["fp"], out["tn"], out["fn"]) == (1, 1, 1, 1)


# ── Section detection ─────────────────────────────────────────────────────────

def test_a_section_the_paper_lacks_is_not_counted_as_a_miss():
    """Scoring a null mapping as a failure would penalise the extractor for a
    section that does not exist."""
    docs = [{
        "sections": {"abstract": "Abstract", "conclusion": None},
        "_detected_sections": ["abstract"],
    }]
    out = ge.section_detection(docs)
    assert out["expected"] == 1
    assert out["rate"] == 1.0


def test_a_missed_section_is_counted():
    docs = [{
        "sections": {"abstract": "Abstract", "results": "Results"},
        "_detected_sections": ["abstract", "introduction"],
    }]
    out = ge.section_detection(docs)
    assert out["expected"] == 2 and out["found"] == 1
    assert out["rate"] == 0.5


def test_section_aliases_match_real_headings():
    docs = [{
        "sections": {"methodology": "Model Architecture"},
        "_detected_sections": ["model_architecture"],
    }]
    assert ge.section_detection(docs)["found"] == 1


# ── Prediction metrics ────────────────────────────────────────────────────────

def _golden_doc():
    return {
        "paper_id": "p1",
        "headline_results": ["28.4 BLEU on WMT 2014 English-to-German"],
        "_numeric_candidates": ["Training took 3.5 days on 8 P100 GPUs."],
        "claims": [],
    }


def test_numeric_fidelity_counts_invented_numbers_against_the_summary():
    predictions = {"p1": {
        "summaries": {"main": "word " * 100},
        "key_findings": ["Reaches 28.4 BLEU.", "Reaches 99.9 BLEU."],
    }}
    out = ge.prediction_scores([_golden_doc()], predictions)
    assert out["numeric_fidelity"] == 0.5          # 28.4 real, 99.9 invented


def test_degenerate_summary_is_flagged():
    predictions = {"p1": {"summaries": {"main": "Too short."}, "key_findings": []}}
    out = ge.prediction_scores([_golden_doc()], predictions)
    assert out["degenerate_rate"] == 1.0
    assert out["per_paper"][0]["degenerate"] is True


def test_headline_recall_measures_quotable_numbers_that_surfaced():
    predictions = {"p1": {
        "summaries": {"main": "The model reaches 28.4 BLEU. " + "word " * 100},
        "key_findings": [],
    }}
    out = ge.prediction_scores([_golden_doc()], predictions)
    # "28.4" and "2014" are both in headline_results; only 28.4 was reproduced.
    assert 0.0 < out["headline_recall"] <= 1.0


def test_papers_without_predictions_are_skipped_not_scored_as_zero():
    out = ge.prediction_scores([_golden_doc()], {})
    assert out["papers_evaluated"] == 0
    assert out["degenerate_rate"] is None


# ── The shipped golden set stays valid ────────────────────────────────────────

def test_committed_golden_files_parse_and_validate():
    label = _load("papermind_eval_label", "evals/label.py")
    docs = ge.load_golden(only_labelled=True)
    for doc in docs:
        problems = label._validate(doc)
        assert not problems, f"{doc.get('paper_id')}: {problems}"
