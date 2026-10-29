# Pipeline Benchmarks

Real end-to-end runs of the 10-agent pipeline against **real arXiv papers**
(not synthetic fixtures), measured by [`evals/run_benchmark.py`](../evals/run_benchmark.py).
Raw results: [`evals/results/benchmark_20260707_095717.json`](../evals/results/benchmark_20260707_095717.json).

> **Provenance:** every number on this page comes from a single run on
> **2026-07-07**, n=8, and has not been re-measured since. Several pipeline
> fixes have landed after it. Treat these as a dated snapshot, not as the
> current state of the system.

```bash
pip install -r requirements-dev.txt
python evals/run_benchmark.py --limit 8          # quick run
python evals/run_benchmark.py                    # full corpus (backend/arxiv_papers)
```

## Golden-set metrics

Measured by [`evals/golden_eval.py`](../evals/golden_eval.py) against
hand-labelled ground truth in [`evals/golden/`](../evals/golden/). Unlike the
pipeline benchmark below, this needs no LLM API key and runs on every PR
([`.github/workflows/evals.yml`](../.github/workflows/evals.yml)).

> ⚠️ **The golden set currently holds one paper (16 labelled claims).** One paper
> is not a benchmark. What follows demonstrates the harness end-to-end and
> establishes the format; the thresholds in `evals/thresholds.json` are
> placeholders until the set reaches 40+ papers across several fields.

Run: 2026-08-25 · prompt fingerprint `b4ccfed3693e` · corpus: 1 paper (nlp)

| Metric | Value | Notes |
|---|---|---|
| Grounding recall | **1.000** | of 8 supported claims, 8 passed |
| Grounding precision | **0.533** | of 15 claims passed, 8 were genuinely supported |
| Grounding F1 | **0.696** | shipped hybrid verdict, not similarity alone |
| — numeric rule | **0.714** | decided 7 claims, 5 correctly |
| — semantic rule | **0.444** | decided 9 claims, 4 correctly |
| Section detection | **0.800** | 4 of 5 sections the paper demonstrably has |
| Numeric fidelity | n/a | needs `--predictions`; no saved prediction set yet |
| Headline-result recall | n/a | needs `--predictions` |
| Degenerate-output rate | n/a | needs `--predictions` |

### What these numbers say

**Precision is the number that matters, and it is poor.** A false positive here
is a fabricated claim displayed to the reader as verified. At 0.533 the guard
still passes roughly half the claims it should reject.

**The semantic rule is worse than a coin flip.** Sweeping the cosine threshold
from 0.05 to 0.95 never beat 0.625 accuracy, and sat at exactly 0.500 for every
value up to 0.50:

| threshold | precision | recall | F1 | accuracy |
|---|---|---|---|---|
| 0.05–0.50 | 0.500 | 1.000 | 0.667 | 0.500 |
| 0.55 | 0.467 | 0.875 | 0.609 | 0.438 |
| 0.75 | 0.600 | 0.750 | 0.667 | 0.625 |
| 0.85 | 1.000 | 0.250 | 0.400 | 0.625 |
| 0.95 | 0.000 | 0.000 | 0.000 | 0.500 |

This is not a tuning problem. "…reaches 28.4 BLEU" and "…reaches 31.7 BLEU" are
near-identical sentences, so all-MiniLM-L6-v2 maps them to near-identical
vectors — the falsehood is one digit, which contributes almost nothing to the
embedding. **No threshold separates them**, which is why the guard now runs a
deterministic numeric rule ahead of the semantic one.

**The numeric rule only fires on digits.** It caught the fabricated `31.7`, but
the remaining negatives in this set are word-spelled numbers ("sixty-four GPUs"),
sign flips ("improves" for "is worse"), and entity swaps ("English-to-Russian").
Those fall through to the semantic rule, which cannot see them either. Closing
that gap needs entailment (NLI), not similarity — the direction current
attribution work (ResearchQA, L-CiteEval) takes.

### What building this found

1. **The guard was dead code.** `verify_claims` had no production call site while
   the README advertised claim-level groundedness. Now wired in as the graph's
   `verify` node, with `test_guard_has_a_production_call_site` failing the build
   if it regresses.
2. **`pymupdf4llm` corrupts decimals in prose.** "28.4" is emitted as
   `28 _._ 4`. Comparing numbers without repairing that would have scored every
   correctly-extracted decimal as invented — a confidently wrong fidelity metric.
3. **Section detection misses whole sections on canonical papers.** On
   *Attention Is All You Need* the extractor produced 27 "sections" including a
   formula (`ffn_x_max_0_xw_1_b_1_w_2_b_2`) and the paper's own title — and no
   `Results` heading at all.

---

## Headline numbers (8-paper run, Groq `llama-3.3-70b-versatile`)

| Metric | Value |
|---|---|
| Pipeline crash rate | **0/8** — no crashes across 10 agents × 8 papers |
| Degenerate-summary rate | **2/8 (25%)** — near-empty output under free-tier rate-limit pressure (see Known limitations) |
| Summary quality (ROUGE-1 F1 vs. paper's own abstract) | **0.64 mean** (0.45–0.92 range) |
| Summary quality (ROUGE-L F1) | **0.43 mean** |
| Median end-to-end latency | **182s/paper** (free-tier LLM, rate-limit-paced) |
| Extraction-only latency (no LLM) | **23–34s/paper** median |
| Parallel speedup (4-agent concurrent phase) | **1.05–2.51×** vs. sequential |
| Entities extracted | **13/paper** median (models, datasets, metrics, frameworks) |
| Figures extracted + classified | **8.5/paper** median (type + auto-generated insight) |
| Section-detection rate | **87.5%** (intro/results/conclusion) — **50%** (abstract/methodology) on papers with non-standard headings |

⚠️ **Read the two rows above together.** "No crashes" is a reliability
number, not a quality one: a quarter of this run produced degenerate summaries
*without* crashing. Both are reported here because reporting only the first is
how a 100% success rate gets claimed for a pipeline that silently returned
near-empty text for two papers.

ROUGE against the paper's own abstract is a proxy, not ground truth — a good
full-paper summary legitimately diverges from the abstract (it covers results
and limitations the abstract omits). It's included because it's a standard,
reproducible reference-based metric a reviewer can independently verify.

## Per-paper detail

| Paper | Wall (s) | Extract (s) | Speedup | Entities | Results | Figures | ROUGE-1 | ROUGE-L |
|---|---|---|---|---|---|---|---|---|
| 2001.08844 | 199.0 | 32.4 | 1.07× | 6 | 180 | 10 | 0.637 | 0.238 |
| 2012.12410 | 149.6 | 24.4 | 1.04× | 7 | 9 | 6 | 0.455 | 0.257 |
| 2107.12321 | 151.8 | 24.9 | 1.04× | 22 | 0 | 4 | 0.546 | 0.306 |
| 2212.13599 | 110.9 | 18.1 | 1.05× | 20 | 2 | 10 | – * | – * |
| 2304.10039 | 566.1 | 446.6 | 2.51× | 13 | 0 | 5 | – * | – * |
| 2305.00257 | 165.6 | 34.5 | 1.05× | 16 | 0 | 10 | – † | – † |
| 2402.05975 | 287.3 | 166.8 | 1.73× | 5 | 5 | 10 | – † | – † |
| 2503.09474 | 207.4 | 53.8 | 1.03× | 14 | 18 | 7 | 0.916 | 0.916 |

\* No literal "Abstract" heading detected (non-standard section titles), so
ROUGE has no reference to score against — not a pipeline failure.

† Produced degenerate near-empty summaries in this specific run (see
**Known limitations** below) — excluded from the ROUGE mean.

## What this benchmark caught

Building the harness surfaced two real issues in the pipeline, both since fixed
or documented:

1. **Figure extraction silently returned 0 figures** — `FigureAgent`'s legacy
   PyMuPDF fallback produced figure objects with only raw image bytes, but
   `DiagramProcessor` (CLIP/DePlot/VLM classification) requires a file path on
   disk. The mismatch threw inside the enrichment step on every paper, and the
   orchestrator's error handling swallowed it silently — 91 raw images
   extracted, 0 reaching the final summary. Fixed in
   [`core/agents/figure_agent.py`](../core/agents/figure_agent.py) by
   materializing the bytes to a temp PNG before enrichment. Verified before/after:
   0 → 8.5 figures/paper median.

2. **Section-detection gaps on non-standard papers** — two of eight papers use
   numbered/idiosyncratic headings (`I Introduction`, `XVI Limitations`, no
   literal "Abstract") that the structure extractor doesn't map to canonical
   section names. Not a crash, but a real robustness gap worth tracking.

## Known limitations

- **Free-tier rate limiting degrades summary quality under sustained load.**
  Two papers in the 8-paper run returned 2-word degenerate summaries instead
  of the usual ~200-word output. Reproducing the same paper in isolation (no
  concurrent rate-limit pressure) produced a normal, high-quality summary —
  the LangGraph reduce step doesn't currently fall back cleanly when Groq's
  free-tier TPM limit is exhausted mid-run. Workaround: `--rps` flag paces
  requests; production use should raise the Groq tier or prefer Gemini.

  **Since this run**, short output is no longer accepted silently: the graph
  rejects a synthesis under `MIN_SUMMARY_WORDS` (150) and
  `_reject_degenerate_summary` in
  [`paper_processing_service.py`](../backend/services/paper_processing_service.py)
  refuses to persist one under 60 words. The failure mode is now a raised error
  rather than a stored 2-word summary — but **these numbers predate that fix and
  have not been re-measured**, which is exactly the gap the golden-set harness is
  meant to close.
- **Parallel speedup is modest most of the time** (1.03–1.07×) because the
  concurrent phase (Entity/Results/Reasoning/ResearchGap/Ablation agents) is
  fast (<5s) relative to the sequential Structure + Summary phases. Speedup
  jumps to 2.51× when FigureAgent's classification work (CLIP/DePlot, minutes
  on a cold model cache) becomes the long pole inside the parallel phase.
- Results extraction has high variance (0–180 per paper) — driven by how many
  ablation/comparison tables a given paper has, not extraction failures.
