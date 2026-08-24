"""Build the golden set: hand-labelled ground truth for the eval harness.

Why this tool exists
--------------------
40-60 papers x (a section map + ~10 headline numbers + ~20 labelled claims) is
not finishable by typing into a prompt loop. So labelling is *correction*, not
composition: `init` extracts a paper and writes a pre-filled JSON stub; a human
edits it; `check` validates it. That turns each paper into minutes of editing.

The one rule that makes the whole set worth having
--------------------------------------------------
**Stubs are pre-filled from the paper's own text, never from PaperMind's
output.** It would be easy — and much faster — to seed the stub with the
pipeline's extracted entities and findings and let the labeller tick them off.
That produces a benchmark the pipeline cannot fail, because the ground truth was
copied from the thing being measured. Anchoring the labeller on the system's own
answers is the most common way an in-house eval quietly becomes decorative, so
nothing here imports the agents, the graph, or a summary.

Claim labelling protocol
------------------------
Each paper needs both classes, or the groundedness threshold cannot be
calibrated — a set of only-supported claims is satisfied by a guard that returns
`True` unconditionally, which is exactly the bug that shipped before.

  supported=true   a faithful paraphrase of something the paper states. Vary the
                   wording; near-verbatim copies only measure string overlap.
  supported=false  plausible but wrong. The useful negatives are *close* ones:
                   keep the sentence and change the number, swap the dataset,
                   attribute the result to the baseline, or state a limitation
                   the paper never claims. "The authors prove P=NP" is a
                   negative no system would ever get wrong, and teaches nothing.

Aim for roughly half of each, ~20 per paper.

Usage
-----
    python evals/label.py init 1706.03762 --domain ml
    python evals/label.py init path/to/paper.pdf --domain bio
    python evals/label.py check
    python evals/label.py stats
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

# Windows consoles default to cp1252, which cannot encode the status glyphs (or
# the section headings of a paper with an accented author name). Without this the
# tool raises UnicodeEncodeError on the primary development platform while
# passing in Linux CI — so the crash only ever reaches the person using it.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):               # pragma: no cover
        pass

GOLDEN_DIR = ROOT / "evals" / "golden"
PDF_DIR = ROOT / "backend" / "arxiv_papers"

# Canonical section names the pipeline is scored against. `run_benchmark.py`
# uses the same vocabulary; keep them in step.
CANONICAL_SECTIONS = ["abstract", "introduction", "methodology", "results", "conclusion"]

DOMAINS = ["ml", "nlp", "cv", "bio", "med", "physics", "hci", "other"]

# A number carrying a unit that is unambiguously a *measurement*. An earlier
# version also accepted bare `x`, `s`, `M` and `B`, which made
# "picture [220 x 323] intentionally omitted" — the PDF extractor's own figure
# placeholder — read as a result. Six of the first thirteen candidates mined
# from the Transformer paper were figure placeholders.
_STRONG_UNIT_RE = re.compile(
    r"[^.]*?\b\d+(?:[.,]\d+)?\s*(?:%|percent|BLEU|F1|AUC|mAP|ROUGE|dB|ms|PPL|perplexity)\b[^.]*\.",
    re.IGNORECASE,
)
# …or a decimal sitting next to a word that means "we measured something".
_METRIC_WORD_RE = re.compile(
    r"[^.]*?\b\d+\.\d+\b[^.]*?\b(?:accuracy|error|score|precision|recall|speedup|"
    r"improvement|reduction|AUROC|dice|IoU)\b[^.]*\.",
    re.IGNORECASE,
)
# Markers the extraction backends leave behind for content they dropped. A
# candidate containing one is describing a figure, not reporting a number.
_PLACEHOLDER_RE = re.compile(r"intentionally omitted|picture \[|<==|==>", re.IGNORECASE)


# ── init ──────────────────────────────────────────────────────────────────────

def _resolve_pdf(target: str) -> Path:
    """A local path, or an arXiv id to fetch into backend/arxiv_papers/."""
    candidate = Path(target)
    if candidate.suffix.lower() == ".pdf" and candidate.exists():
        return candidate

    arxiv_id = target.strip()
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    dest = PDF_DIR / f"{arxiv_id}.pdf"
    if dest.exists():
        print(f"  using cached {dest}")
        return dest

    print(f"  fetching arXiv:{arxiv_id} …")
    import arxiv                                     # same client the app uses
    import requests

    result = next(arxiv.Client().results(arxiv.Search(id_list=[arxiv_id])))
    # arxiv 4.x dropped Result.download_pdf; fetch pdf_url directly, as
    # backend/main.py's ArxivFetcher already does.
    response = requests.get(result.pdf_url, timeout=60,
                            headers={"User-Agent": "PaperMind-eval/1.0"})
    response.raise_for_status()
    dest.write_bytes(response.content)
    return dest


def _numeric_candidates(sections: Dict[str, str],
                        tables_md: Optional[List[str]] = None,
                        limit: int = 60) -> List[str]:
    """Sentences and table rows carrying a measurement, from the paper's own text.

    Deliberately over-inclusive and unranked: the labeller deletes the noise and
    keeps the headline numbers. Ranking these would be a model's opinion about
    what matters, which is exactly the judgement the golden set exists to supply.

    Tables are mined as well as prose, because a paper's headline numbers usually
    live in one — mining prose alone pulled nothing from the Transformer paper's
    results table, which is the only place its cost/BLEU comparison appears.
    """
    hits: List[str] = []

    def _add(text: str, min_chars: int = 40) -> bool:
        """Append if usable; returns False once the limit is reached.

        `min_chars` is lower for table rows: a prose fragment under ~40 chars
        carries no context to judge a number by, but `ConvS2S | 25.16 | 40.46`
        is a complete, quotable result in 24.
        """
        candidate = " ".join(text.split())
        if not (min_chars <= len(candidate) <= 300):
            return True
        if _PLACEHOLDER_RE.search(candidate) or candidate in hits:
            return True
        hits.append(candidate)
        return len(hits) < limit

    # Results-ish sections first, so the most quotable numbers land at the top.
    preferred = [n for n in sections if re.search(r"result|experiment|evaluat|variation", n, re.I)]
    for name in preferred + [n for n in sections if n not in preferred]:
        body = sections.get(name) or ""
        for pattern in (_STRONG_UNIT_RE, _METRIC_WORD_RE):
            for match in pattern.finditer(body):
                if not _add(match.group(0)):
                    return hits

    for table in (tables_md or []):
        for row in table.splitlines():
            # A data row: has cells, and at least one decimal number in them.
            if row.count("|") >= 2 and re.search(r"\d+\.\d+", row):
                if not _add(row.strip("| ").replace("|", " | "), min_chars=12):
                    return hits
    return hits


def cmd_init(args: argparse.Namespace) -> int:
    from core.pipeline.pdf_extractor import extract_pdf

    pdf_path = _resolve_pdf(args.target)
    paper_id = args.paper_id or pdf_path.stem

    print(f"  extracting {pdf_path.name} …")
    result = extract_pdf(str(pdf_path))
    sections = result.sections or {}

    out_path = GOLDEN_DIR / f"{paper_id}.json"
    if out_path.exists() and not args.force:
        print(f"! {out_path} exists — pass --force to overwrite (this discards labels)")
        return 1

    stub: Dict[str, Any] = {
        "paper_id": paper_id,
        "source_pdf": str(pdf_path.relative_to(ROOT)) if pdf_path.is_relative_to(ROOT) else str(pdf_path),
        "domain": args.domain,
        "title": (result.metadata or {}).get("title", ""),
        "labelled_on": date.today().isoformat(),
        "labelled_by": args.by,
        "status": "draft",

        "_instructions": {
            "sections": (
                "Map each canonical name to the heading AS PRINTED in the paper, or "
                "null if the paper genuinely has no such section. Detected headings "
                "are listed under _detected_sections to copy from."
            ),
            "headline_results": (
                "The ~10 numbers a reader would quote. Copy from _numeric_candidates "
                "and delete the rest; add any the regex missed (especially from tables)."
            ),
            "key_findings": "5-8 findings YOU would expect a good summary to contain.",
            "claims": "~20, roughly half supported=true and half false. See the module docstring.",
        },

        "_detected_sections": sorted(sections.keys()),
        "_numeric_candidates": _numeric_candidates(sections, result.tables_md),

        # ── fill these in ──
        "sections": {name: None for name in CANONICAL_SECTIONS},
        "headline_results": [],
        "key_findings": [],
        "claims": [],
        "notes": "",
    }

    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(stub, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"✓ {out_path.relative_to(ROOT)}")
    print(f"  backend={result.backend}  sections={len(sections)}  "
          f"numeric candidates={len(stub['_numeric_candidates'])}")
    print("  Now edit the file, set status to 'labelled', then: python evals/label.py check")
    return 0


# ── check ─────────────────────────────────────────────────────────────────────

def _validate(doc: Dict[str, Any]) -> List[str]:
    """Structural problems that would make a paper useless or misleading to score."""
    problems: List[str] = []

    if doc.get("domain") not in DOMAINS:
        problems.append(f"domain {doc.get('domain')!r} not one of {DOMAINS}")

    sections = doc.get("sections") or {}
    missing = [s for s in CANONICAL_SECTIONS if s not in sections]
    if missing:
        problems.append(f"sections missing keys: {missing}")
    if not any(sections.get(s) for s in CANONICAL_SECTIONS):
        problems.append("no section was mapped — the section-detection score would be vacuous")

    if not doc.get("key_findings"):
        problems.append("no key_findings")
    if not doc.get("headline_results"):
        problems.append("no headline_results — numeric fidelity cannot be scored")

    claims = doc.get("claims") or []
    for i, claim in enumerate(claims):
        if not isinstance(claim, dict) or "text" not in claim or "supported" not in claim:
            problems.append(f"claims[{i}] needs both 'text' and 'supported'")
            continue
        if not isinstance(claim["supported"], bool):
            problems.append(f"claims[{i}].supported must be true/false, not {claim['supported']!r}")

    supported = sum(1 for c in claims if isinstance(c, dict) and c.get("supported") is True)
    unsupported = sum(1 for c in claims if isinstance(c, dict) and c.get("supported") is False)
    if claims:
        # Both classes are required. A guard that always answers "grounded" scores
        # perfectly on an all-supported set, which is how the original bug hid.
        if supported == 0 or unsupported == 0:
            problems.append(
                f"claims need both classes (supported={supported}, unsupported={unsupported}) — "
                "a one-class set cannot calibrate a threshold"
            )
        elif min(supported, unsupported) / max(supported, unsupported) < 0.4:
            problems.append(
                f"claim classes badly imbalanced ({supported} supported / {unsupported} unsupported)"
            )
    return problems


def _load_golden() -> List[tuple]:
    if not GOLDEN_DIR.exists():
        return []
    out = []
    for path in sorted(GOLDEN_DIR.glob("*.json")):
        try:
            out.append((path, json.loads(path.read_text(encoding="utf-8"))))
        except json.JSONDecodeError as e:
            out.append((path, {"_parse_error": str(e)}))
    return out


def cmd_check(args: argparse.Namespace) -> int:
    docs = _load_golden()
    if not docs:
        print(f"! no golden files in {GOLDEN_DIR.relative_to(ROOT)}")
        return 1

    labelled, drafts, bad = 0, 0, 0
    for path, doc in docs:
        name = path.name
        if "_parse_error" in doc:
            print(f"✗ {name}: invalid JSON — {doc['_parse_error']}")
            bad += 1
            continue
        if doc.get("status") != "labelled":
            drafts += 1
            if args.verbose:
                print(f"· {name}: draft (status={doc.get('status')!r})")
            continue

        problems = _validate(doc)
        if problems:
            bad += 1
            print(f"✗ {name}")
            for p in problems:
                print(f"    - {p}")
        else:
            labelled += 1
            if args.verbose:
                claims = doc.get("claims") or []
                print(f"✓ {name}: {len(doc['key_findings'])} findings, "
                      f"{len(doc['headline_results'])} results, {len(claims)} claims")

    print(f"\n{labelled} labelled · {drafts} draft · {bad} invalid  "
          f"(of {len(docs)} files)")
    if args.strict and (bad or not labelled):
        return 1
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    docs = [d for _, d in _load_golden() if d.get("status") == "labelled"]
    if not docs:
        print("no labelled papers yet")
        return 0

    by_domain: Dict[str, int] = {}
    claims_total = supported_total = 0
    for doc in docs:
        by_domain[doc.get("domain", "?")] = by_domain.get(doc.get("domain", "?"), 0) + 1
        for claim in doc.get("claims") or []:
            claims_total += 1
            supported_total += 1 if claim.get("supported") else 0

    print(f"labelled papers ....... {len(docs)}")
    print(f"labelled claims ....... {claims_total} "
          f"({supported_total} supported / {claims_total - supported_total} unsupported)")
    print("by domain:")
    for domain, count in sorted(by_domain.items(), key=lambda kv: -kv[1]):
        print(f"  {domain:<9} {count}")

    # The set is meant to test the domain-agnostic claim in schemas.py, which a
    # pile of ML papers cannot do.
    non_ml = sum(c for d, c in by_domain.items() if d not in ("ml", "nlp", "cv"))
    if non_ml < max(1, len(docs) // 4):
        print(f"\n! only {non_ml} non-ML papers — the domain-agnostic claim is untested")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="extract a paper and write a labelling stub")
    p_init.add_argument("target", help="arXiv id or path to a PDF")
    p_init.add_argument("--domain", default="other", choices=DOMAINS)
    p_init.add_argument("--paper-id", default=None)
    p_init.add_argument("--by", default="", help="labeller name, for provenance")
    p_init.add_argument("--force", action="store_true", help="overwrite an existing file")
    p_init.set_defaults(func=cmd_init)

    p_check = sub.add_parser("check", help="validate every golden file")
    p_check.add_argument("--strict", action="store_true", help="exit 1 on any problem (CI)")
    p_check.add_argument("-v", "--verbose", action="store_true")
    p_check.set_defaults(func=cmd_check)

    p_stats = sub.add_parser("stats", help="corpus composition")
    p_stats.set_defaults(func=cmd_stats)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
