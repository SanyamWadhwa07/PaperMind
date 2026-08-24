"""Score PaperMind against the hand-labelled golden set.

This is the metric layer the project was missing. The existing harness
(`run_benchmark.py`) measures ROUGE against each paper's own abstract, which a
good full-paper summary is *supposed* to diverge from — so a higher score there
partly rewards the failure mode. Nothing measured whether an extracted number
was real, whether a claim was supported, or how often the pipeline returned
near-empty text.

Metrics, and what each needs
----------------------------
                          | needs PDF | needs LLM | needs predictions
  grounding (P/R/F1)      |     no    |    no     |       no
  threshold calibration   |     no    |    no     |       no
  section detection       |    yes    |    no     |       no
  numeric fidelity        |     no    |    no     |      yes
  headline-result recall  |     no    |    no     |      yes
  degenerate rate         |     no    |    no     |      yes

The first two need only the labelled claims and a local embedding model, which
is why they can gate CI without an API key. Prediction-backed metrics activate
when `--predictions` points at saved pipeline output.

Usage
-----
    python evals/golden_eval.py score
    python evals/golden_eval.py score --predictions evals/predictions/
    python evals/golden_eval.py calibrate
    python evals/golden_eval.py gate            # exits 1 on regression (CI)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):               # pragma: no cover
        pass

GOLDEN_DIR = ROOT / "evals" / "golden"
RESULTS_DIR = ROOT / "evals" / "results"
THRESHOLDS_PATH = ROOT / "evals" / "thresholds.json"

CANONICAL_SECTIONS = ["abstract", "introduction", "methodology", "results", "conclusion"]
# Same vocabulary run_benchmark.py uses, so the two agree on what a hit is.
SECTION_ALIASES = {
    "methodology": ("methodology", "methods", "method", "approach", "architecture", "model"),
    "results": ("results", "experiment", "evaluation", "evaluat"),
}

# A summary shorter than this collapsed rather than summarised. Mirrors
# `_MIN_SUMMARY_WORDS` in backend/services/paper_processing_service.py so the
# eval and the product agree on what "degenerate" means.
MIN_SUMMARY_WORDS = 60


# ── Number handling ───────────────────────────────────────────────────────────

# Number handling lives in the guard itself, so the eval measures exactly the
# normalisation production uses. A second copy here would drift, and the metric
# would slowly stop describing the shipped behaviour.
from core.intelligence.hallucination_guard import normalise_numbers, numbers_in  # noqa: E402


# ── Loading ───────────────────────────────────────────────────────────────────

def load_golden(only_labelled: bool = True) -> List[Dict[str, Any]]:
    if not GOLDEN_DIR.exists():
        return []
    docs = []
    for path in sorted(GOLDEN_DIR.glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        if only_labelled and doc.get("status") != "labelled":
            continue
        docs.append(doc)
    return docs


def load_predictions(directory: Optional[Path]) -> Dict[str, Dict[str, Any]]:
    """Saved pipeline output, keyed by paper_id. One JSON per paper."""
    if not directory or not directory.exists():
        return {}
    out = {}
    for path in sorted(directory.glob("*.json")):
        out[path.stem] = json.loads(path.read_text(encoding="utf-8"))
    return out


# ── Grounding ─────────────────────────────────────────────────────────────────

def _paper_sections(doc: Dict[str, Any]) -> Dict[str, str]:
    """The paper's own text, for verifying claims against."""
    from core.pipeline.pdf_extractor import extract_pdf

    pdf = ROOT / doc["source_pdf"]
    if not pdf.exists():
        raise FileNotFoundError(f"{pdf} — re-fetch with: python evals/label.py init {doc['paper_id']}")
    return extract_pdf(str(pdf)).sections or {}


def grounding_scores(docs: List[Dict[str, Any]],
                     threshold: Optional[float] = None) -> Dict[str, Any]:
    """Run the guard over every labelled claim and score it as a classifier.

    Reports similarity per claim so a threshold sweep needs only one embedding
    pass over the corpus rather than one per candidate threshold.
    """
    from core.graph.summary_graph import usable_sections
    from core.intelligence import hallucination_guard

    if threshold is None:
        threshold = hallucination_guard.SIMILARITY_THRESHOLD

    scored: List[Tuple[float, bool]] = []          # (similarity, gold) — semantic sweep
    verdicts: List[Tuple[bool, bool]] = []         # (shipped grounded, gold)
    by_rule: Dict[str, Dict[str, int]] = {}
    unverifiable = 0

    for doc in docs:
        claims = doc.get("claims") or []
        if not claims:
            continue
        sources = dict(usable_sections(_paper_sections(doc)))
        checked = hallucination_guard.verify_claims([c["text"] for c in claims], sources)
        for gold, result in zip(claims, checked):
            if result.get("grounded") is None:
                unverifiable += 1
                continue
            gold_supported = bool(gold["supported"])
            verdicts.append((bool(result["grounded"]), gold_supported))

            rule = result.get("rule", "semantic")
            stats = by_rule.setdefault(rule, {"claims": 0, "correct": 0})
            stats["claims"] += 1
            stats["correct"] += 1 if bool(result["grounded"]) == gold_supported else 0

            similarity = result.get("best_similarity")
            if similarity is not None:
                scored.append((float(similarity), gold_supported))

    return {
        "threshold": threshold,
        "unverifiable": unverifiable,
        "claims_scored": len(verdicts),
        # The shipped decision — the hybrid numeric+semantic verdict, which is
        # what a user actually sees. Scoring the similarity alone would report a
        # rule the product does not use.
        **_classify_verdicts(verdicts),
        "by_rule": by_rule,
        # Kept separately for the sweep: a threshold sweep can only ever describe
        # the semantic rule, since the numeric rule has no threshold.
        "similarities": scored,
    }


def _classify_verdicts(verdicts: List[Tuple[bool, bool]]) -> Dict[str, Any]:
    tp = sum(1 for pred, gold in verdicts if pred and gold)
    fp = sum(1 for pred, gold in verdicts if pred and not gold)
    fn = sum(1 for pred, gold in verdicts if not pred and gold)
    tn = sum(1 for pred, gold in verdicts if not pred and not gold)
    return _rates(tp, fp, fn, tn)


def _classify(scored: List[Tuple[float, bool]], threshold: float) -> Dict[str, Any]:
    """Semantic rule only: what cosine similarity alone would decide."""
    tp = sum(1 for sim, gold in scored if sim >= threshold and gold)
    fp = sum(1 for sim, gold in scored if sim >= threshold and not gold)
    fn = sum(1 for sim, gold in scored if sim < threshold and gold)
    tn = sum(1 for sim, gold in scored if sim < threshold and not gold)
    return _rates(tp, fp, fn, tn)


def _rates(tp: int, fp: int, fn: int, tn: int) -> Dict[str, Any]:
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    total = tp + fp + fn + tn
    return {
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "accuracy": round((tp + tn) / total, 4) if total else 0.0,
    }


def sweep_threshold(scored: List[Tuple[float, bool]],
                    lo: float = 0.05, hi: float = 0.95,
                    step: float = 0.01) -> List[Dict[str, Any]]:
    rows = []
    value = lo
    while value <= hi + 1e-9:
        rows.append({"threshold": round(value, 2), **_classify(scored, value)})
        value += step
    return rows


# ── Section detection ─────────────────────────────────────────────────────────

def _matches_canonical(detected_keys: List[str], canonical: str) -> bool:
    aliases = SECTION_ALIASES.get(canonical, (canonical,))
    return any(alias in key.lower() for key in detected_keys for alias in aliases)


def section_detection(docs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """How many sections the labeller says exist does the extractor actually find?

    Scored only over sections the golden record maps to a real heading — a paper
    with no Conclusion must not count as a miss.
    """
    expected = found = 0
    per_section: Dict[str, Dict[str, int]] = {
        s: {"expected": 0, "found": 0} for s in CANONICAL_SECTIONS
    }

    for doc in docs:
        detected = doc.get("_detected_sections") or []
        for canonical, printed in (doc.get("sections") or {}).items():
            if not printed:                        # paper genuinely lacks it
                continue
            expected += 1
            per_section.setdefault(canonical, {"expected": 0, "found": 0})
            per_section[canonical]["expected"] += 1
            if _matches_canonical(detected, canonical):
                found += 1
                per_section[canonical]["found"] += 1

    return {
        "expected": expected,
        "found": found,
        "rate": round(found / expected, 4) if expected else None,
        "per_section": per_section,
    }


# ── Prediction-backed metrics ─────────────────────────────────────────────────

def _summary_text(prediction: Dict[str, Any]) -> str:
    return (prediction.get("summaries", {}) or {}).get("main", "") or ""


def prediction_scores(docs: List[Dict[str, Any]],
                      predictions: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Numeric fidelity, headline recall, and degenerate rate over saved output."""
    fidelity_num = fidelity_den = 0
    recall_num = recall_den = 0
    degenerate = evaluated = 0
    per_paper = []

    for doc in docs:
        prediction = predictions.get(doc["paper_id"])
        if prediction is None:
            continue
        evaluated += 1

        summary = _summary_text(prediction)
        is_degenerate = len(summary.split()) < MIN_SUMMARY_WORDS
        degenerate += 1 if is_degenerate else 0

        # Numeric fidelity: of the numbers the model asserts in its findings, how
        # many actually occur in the paper? This is the metric that directly
        # tests the schema's own demand that a finding carry a real number.
        source_numbers = set()
        for value in doc.get("headline_results", []):
            source_numbers.update(numbers_in(value))
        for candidate in doc.get("_numeric_candidates", []):
            source_numbers.update(numbers_in(candidate))

        asserted = []
        for finding in prediction.get("key_findings", []) or []:
            asserted.extend(numbers_in(finding))
        supported = [n for n in asserted if n in source_numbers]
        fidelity_num += len(supported)
        fidelity_den += len(asserted)

        # Headline recall: of the numbers a reader would quote, how many surfaced?
        gold_numbers = set()
        for value in doc.get("headline_results", []):
            gold_numbers.update(numbers_in(value))
        predicted_blob = " ".join(
            [summary] + list(prediction.get("key_findings", []) or [])
        )
        predicted_numbers = set(numbers_in(predicted_blob))
        hit = gold_numbers & predicted_numbers
        recall_num += len(hit)
        recall_den += len(gold_numbers)

        per_paper.append({
            "paper_id": doc["paper_id"],
            "degenerate": is_degenerate,
            "summary_words": len(summary.split()),
            "numeric_fidelity": round(len(supported) / len(asserted), 4) if asserted else None,
            "headline_recall": round(len(hit) / len(gold_numbers), 4) if gold_numbers else None,
        })

    return {
        "papers_evaluated": evaluated,
        "numeric_fidelity": round(fidelity_num / fidelity_den, 4) if fidelity_den else None,
        "numbers_asserted": fidelity_den,
        "headline_recall": round(recall_num / recall_den, 4) if recall_den else None,
        "degenerate_rate": round(degenerate / evaluated, 4) if evaluated else None,
        "per_paper": per_paper,
    }


# ── Report ────────────────────────────────────────────────────────────────────

def build_report(predictions_dir: Optional[Path] = None) -> Dict[str, Any]:
    docs = load_golden()
    report: Dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "golden_papers": len(docs),
        "golden_claims": sum(len(d.get("claims") or []) for d in docs),
        "domains": sorted({d.get("domain", "?") for d in docs}),
    }
    if not docs:
        report["error"] = "no labelled golden papers — run: python evals/label.py init <id>"
        return report

    try:
        from core.graph.provenance import prompt_fingerprint
        report["prompt_fingerprint"] = prompt_fingerprint()
    except Exception:
        report["prompt_fingerprint"] = "unknown"

    report["section_detection"] = section_detection(docs)

    grounding = grounding_scores(docs)
    similarities = grounding.pop("similarities")
    report["grounding"] = grounding

    predictions = load_predictions(predictions_dir)
    if predictions:
        report["predictions"] = prediction_scores(docs, predictions)
    else:
        report["predictions"] = None

    best = max(sweep_threshold(similarities), key=lambda r: r["f1"]) if similarities else None
    report["grounding_best_threshold"] = best
    return report


def _fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    return f"{value:.3f}" if isinstance(value, float) else str(value)


def print_report(report: Dict[str, Any]) -> None:
    if report.get("error"):
        print(f"! {report['error']}")
        return

    print(f"\nGolden set: {report['golden_papers']} papers, "
          f"{report['golden_claims']} claims, domains={report['domains']}")
    print(f"Prompt fingerprint: {report['prompt_fingerprint']}\n")

    print("| Metric | Value | Notes |")
    print("|---|---|---|")

    sec = report["section_detection"]
    print(f"| Section detection | {_fmt(sec['rate'])} | {sec['found']}/{sec['expected']} "
          f"sections the paper has and the extractor found |")

    g = report["grounding"]
    print(f"| Grounding F1 | {_fmt(g['f1'])} | at threshold {g['threshold']}, "
          f"{g['claims_scored']} claims |")
    print(f"| Grounding precision | {_fmt(g['precision'])} | "
          f"a false positive is a hallucination shown as verified |")
    print(f"| Grounding recall | {_fmt(g['recall'])} | "
          f"a false negative flags a true claim |")
    if g["unverifiable"]:
        print(f"| Unverifiable claims | {g['unverifiable']} | "
              f"reported grounded=None, not counted either way |")
    # Which rule decided what. The split matters more than the headline: the
    # numeric rule is deterministic, the semantic rule is near chance on close
    # negatives, and an aggregate F1 hides that.
    for rule, stats in sorted((g.get("by_rule") or {}).items()):
        share = stats["correct"] / stats["claims"] if stats["claims"] else 0.0
        print(f"| Rule: {rule} | {share:.3f} | decided {stats['claims']} claims, "
              f"{stats['correct']} correct |")

    pred = report.get("predictions")
    if pred:
        print(f"| Numeric fidelity | {_fmt(pred['numeric_fidelity'])} | "
              f"{pred['numbers_asserted']} numbers asserted in key_findings |")
        print(f"| Headline recall | {_fmt(pred['headline_recall'])} | "
              f"quotable numbers that surfaced |")
        print(f"| Degenerate rate | {_fmt(pred['degenerate_rate'])} | "
              f"summaries under {MIN_SUMMARY_WORDS} words |")
    else:
        print("| Numeric fidelity | n/a | no --predictions supplied |")
        print("| Headline recall | n/a | no --predictions supplied |")
        print("| Degenerate rate | n/a | no --predictions supplied |")

    best = report.get("grounding_best_threshold")
    if best:
        current = report["grounding"]["threshold"]
        print(f"\nThreshold sweep: best F1 {best['f1']:.3f} at {best['threshold']} "
              f"(currently {current}).")
        if abs(best["threshold"] - current) > 0.05:
            print(f"  -> SIMILARITY_THRESHOLD in core/intelligence/hallucination_guard.py "
                  f"is off by {abs(best['threshold'] - current):.2f}; "
                  f"re-derive it before trusting grounded flags.")


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_score(args: argparse.Namespace) -> int:
    report = build_report(Path(args.predictions) if args.predictions else None)
    print_report(report)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out = RESULTS_DIR / f"golden_{stamp}.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nwrote {out.relative_to(ROOT)}")
    return 0 if not report.get("error") else 1


def cmd_calibrate(args: argparse.Namespace) -> int:
    docs = load_golden()
    if not docs:
        print("! no labelled golden papers")
        return 1

    grounding = grounding_scores(docs)
    scored = grounding["similarities"]
    if not scored:
        print("! no verifiable claims")
        return 1

    rows = sweep_threshold(scored)
    best = max(rows, key=lambda r: r["f1"])

    from core.intelligence import hallucination_guard
    current = hallucination_guard.SIMILARITY_THRESHOLD

    print(f"\n{len(scored)} labelled claims "
          f"({sum(1 for _, g in scored if g)} supported / "
          f"{sum(1 for _, g in scored if not g)} unsupported)\n")
    print("| threshold | precision | recall | F1 | accuracy |")
    print("|---|---|---|---|---|")
    for row in rows:
        if abs(row["threshold"] * 100 % 5) < 1e-6:      # every 0.05
            marker = ""
            if abs(row["threshold"] - current) < 1e-9:
                marker = "  <- current"
            elif row["threshold"] == best["threshold"]:
                marker = "  <- best F1"
            print(f"| {row['threshold']:.2f} | {row['precision']:.3f} | {row['recall']:.3f} "
                  f"| {row['f1']:.3f} | {row['accuracy']:.3f} |{marker}")

    print(f"\ncurrent {current} -> F1 {_classify(scored, current)['f1']:.3f}")
    print(f"best    {best['threshold']} -> F1 {best['f1']:.3f}")
    print("\nThis sweep describes the SEMANTIC rule alone — the numeric rule has no "
          "threshold to tune. Compare it against the shipped hybrid verdict from "
          "`golden_eval.py score`, which is what a user actually sees.")
    print("A sweep over one small corpus also overfits: read it as evidence that the "
          "threshold needs revisiting, not as the new constant.")
    return 0


def cmd_gate(args: argparse.Namespace) -> int:
    """CI gate. Fails on regression; refuses to pass silently on missing data."""
    thresholds = json.loads(THRESHOLDS_PATH.read_text(encoding="utf-8")) \
        if THRESHOLDS_PATH.exists() else {}
    if not thresholds:
        print(f"! no {THRESHOLDS_PATH.name} — nothing to gate on")
        return 0

    report = build_report(Path(args.predictions) if args.predictions else None)
    if report.get("error"):
        print(f"! {report['error']}")
        return 0 if args.allow_empty else 1

    print_report(report)

    values = {
        "grounding_f1": report["grounding"]["f1"],
        "grounding_precision": report["grounding"]["precision"],
        "grounding_recall": report["grounding"]["recall"],
        "section_detection": report["section_detection"]["rate"],
    }
    if report.get("predictions"):
        values.update({
            "numeric_fidelity": report["predictions"]["numeric_fidelity"],
            "headline_recall": report["predictions"]["headline_recall"],
            "degenerate_rate": report["predictions"]["degenerate_rate"],
        })

    failures, skipped = [], []
    print("\n--- gate ---")
    for name, rule in thresholds.items():
        if name.startswith("_"):               # documentation keys, not metrics
            continue
        value = values.get(name)
        if value is None:
            skipped.append(name)
            continue
        if "min" in rule and value < rule["min"]:
            failures.append(f"{name} {value:.3f} < min {rule['min']}")
        elif "max" in rule and value > rule["max"]:
            failures.append(f"{name} {value:.3f} > max {rule['max']}")
        else:
            bound = f"min {rule['min']}" if "min" in rule else f"max {rule['max']}"
            print(f"  ok   {name}: {value:.3f} ({bound})")

    for name in skipped:
        # Loud, because a metric that quietly stops being computed is a gate that
        # quietly stops gating.
        print(f"  SKIP {name}: not computed in this run")
    for failure in failures:
        print(f"  FAIL {failure}")

    if failures:
        print(f"\n{len(failures)} threshold(s) regressed.")
        return 1
    print("\nall computed thresholds met.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    p_score = sub.add_parser("score", help="full metric report")
    p_score.add_argument("--predictions", default=None,
                         help="directory of saved pipeline output, one JSON per paper_id")
    p_score.set_defaults(func=cmd_score)

    p_cal = sub.add_parser("calibrate", help="sweep the groundedness threshold")
    p_cal.set_defaults(func=cmd_calibrate)

    p_gate = sub.add_parser("gate", help="fail on regression past evals/thresholds.json")
    p_gate.add_argument("--predictions", default=None)
    p_gate.add_argument("--allow-empty", action="store_true",
                        help="pass when the golden set is empty (bootstrap only)")
    p_gate.set_defaults(func=cmd_gate)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
