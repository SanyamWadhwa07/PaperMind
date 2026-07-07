# Pipeline Benchmarks

Real end-to-end runs of the 10-agent pipeline against **real arXiv papers**
(not synthetic fixtures), measured by [`evals/run_benchmark.py`](../evals/run_benchmark.py).
Raw results: [`evals/results/benchmark_20260707_095717.json`](../evals/results/benchmark_20260707_095717.json).

```bash
pip install -r requirements-dev.txt
python evals/run_benchmark.py --limit 8          # quick run
python evals/run_benchmark.py                    # full corpus (backend/arxiv_papers)
```

## Headline numbers (8-paper run, Groq `llama-3.3-70b-versatile`)

| Metric | Value |
|---|---|
| Pipeline success rate | **8/8 (100%)** — no crashes across 10 agents × 8 papers |
| Summary quality (ROUGE-1 F1 vs. paper's own abstract) | **0.64 mean** (0.45–0.92 range) |
| Summary quality (ROUGE-L F1) | **0.43 mean** |
| Median end-to-end latency | **182s/paper** (free-tier LLM, rate-limit-paced) |
| Extraction-only latency (no LLM) | **23–34s/paper** median |
| Parallel speedup (4-agent concurrent phase) | **1.05–2.51×** vs. sequential |
| Entities extracted | **13/paper** median (models, datasets, metrics, frameworks) |
| Figures extracted + classified | **8.5/paper** median (type + auto-generated insight) |
| Section-detection rate | **87.5%** (intro/results/conclusion) — **50%** (abstract/methodology) on papers with non-standard headings |

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
  requests; production use should either raise the Groq tier or add a
  legacy-path fallback when the graph engine returns a suspiciously short
  summary (currently only checked for *empty*, not *short*).
- **Parallel speedup is modest most of the time** (1.03–1.07×) because the
  concurrent phase (Entity/Results/Reasoning/ResearchGap/Ablation agents) is
  fast (<5s) relative to the sequential Structure + Summary phases. Speedup
  jumps to 2.51× when FigureAgent's classification work (CLIP/DePlot, minutes
  on a cold model cache) becomes the long pole inside the parallel phase.
- Results extraction has high variance (0–180 per paper) — driven by how many
  ablation/comparison tables a given paper has, not extraction failures.
