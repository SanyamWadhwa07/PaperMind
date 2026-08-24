"""Validation rules for the golden set (`evals/label.py`).

The golden set is the reference every quality number will be measured against,
so a defect here is worse than a defect in the pipeline: it silently redefines
what "correct" means. These tests cover the two ways that happens — a claim set
that cannot calibrate anything, and mined candidates that are not results.
"""

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _load_label_module():
    """`evals/` is a script directory, not a package."""
    spec = importlib.util.spec_from_file_location(
        "papermind_eval_label", REPO_ROOT / "evals" / "label.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


label = _load_label_module()


def _doc(**overrides):
    base = {
        "domain": "ml",
        "status": "labelled",
        "sections": {s: s.title() for s in label.CANONICAL_SECTIONS},
        "headline_results": ["28.4 BLEU on WMT 2014 EN-DE"],
        "key_findings": ["The model reaches 28.4 BLEU."],
        "claims": [{"text": "a", "supported": True}, {"text": "b", "supported": False}],
    }
    base.update(overrides)
    return base


# ── The claim set must be able to calibrate a threshold ───────────────────────

def test_all_supported_claim_set_is_rejected():
    """A guard hardcoded to `grounded=True` scores 100% on an all-supported set.

    That is not hypothetical — it is the exact bug that shipped in
    hallucination_guard.py, and an eval built on positives only would have
    ratified it.
    """
    problems = label._validate(_doc(claims=[
        {"text": "a", "supported": True},
        {"text": "b", "supported": True},
    ]))
    assert any("both classes" in p for p in problems), problems


def test_all_unsupported_claim_set_is_rejected():
    problems = label._validate(_doc(claims=[
        {"text": "a", "supported": False},
        {"text": "b", "supported": False},
    ]))
    assert any("both classes" in p for p in problems), problems


def test_badly_imbalanced_claim_set_is_rejected():
    claims = [{"text": f"s{i}", "supported": True} for i in range(10)]
    claims.append({"text": "u", "supported": False})
    problems = label._validate(_doc(claims=claims))
    assert any("imbalanced" in p for p in problems), problems


def test_balanced_claim_set_passes():
    claims = ([{"text": f"s{i}", "supported": True} for i in range(5)]
              + [{"text": f"u{i}", "supported": False} for i in range(5)])
    assert label._validate(_doc(claims=claims)) == []


def test_non_boolean_supported_is_rejected():
    """`"true"` is not `True`; a truthy string would silently label every claim
    supported."""
    problems = label._validate(_doc(claims=[
        {"text": "a", "supported": "true"},
        {"text": "b", "supported": False},
    ]))
    assert any("must be true/false" in p for p in problems), problems


# ── The rest of the record has to be scorable ─────────────────────────────────

def test_missing_headline_results_is_rejected():
    problems = label._validate(_doc(headline_results=[]))
    assert any("numeric fidelity" in p for p in problems), problems


def test_unmapped_sections_are_rejected():
    problems = label._validate(_doc(sections={s: None for s in label.CANONICAL_SECTIONS}))
    assert any("vacuous" in p for p in problems), problems


def test_unknown_domain_is_rejected():
    assert any("domain" in p for p in label._validate(_doc(domain="astrology")))


def test_canonical_sections_match_the_benchmark_harness():
    """Two files define this vocabulary. If they drift, section-detection scores
    silently stop being comparable between the harness and the golden set."""
    text = (REPO_ROOT / "evals" / "run_benchmark.py").read_text(encoding="utf-8")
    line = next(l for l in text.splitlines() if l.startswith("CANONICAL_SECTIONS"))
    harness_sections = eval(line.split("=", 1)[1].strip())      # noqa: S307 - literal list
    assert harness_sections == label.CANONICAL_SECTIONS


# ── Candidate mining ──────────────────────────────────────────────────────────

def test_extractor_placeholders_are_not_mined_as_results():
    """`picture [220 x 323]` is a dropped figure, not a measurement. Six of the
    first thirteen candidates on the Transformer paper used to be these."""
    sections = {"results": (
        "**==> picture [220 x 323] intentionally omitted <==** Figure 1: architecture. "
        "Our model achieves 28.4 BLEU on the WMT 2014 English-to-German task."
    )}
    found = label._numeric_candidates(sections)
    assert any("28.4 BLEU" in c for c in found)
    assert not any("intentionally omitted" in c for c in found)


def test_table_rows_are_mined():
    """A paper's headline numbers usually live in a table, not in prose."""
    tables = ["| Model | BLEU | Cost |\n|---|---|---|\n| ConvS2S | 25.16 | 9.6 |\n"]
    found = label._numeric_candidates({}, tables_md=tables)
    assert any("25.16" in c for c in found), found


def test_bare_dimension_units_do_not_count_as_measurements():
    sections = {"methods": "We resize every input image to 224 x 224 pixels before training."}
    assert label._numeric_candidates(sections) == []


def test_candidates_are_deduplicated():
    sentence = "Our model achieves 28.4 BLEU on the WMT 2014 English-to-German task."
    found = label._numeric_candidates({"results": sentence, "conclusion": sentence})
    assert len(found) == 1
