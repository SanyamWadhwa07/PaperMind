"""PaperMind benchmark harness.

Runs the full 10-agent pipeline over a corpus of real arXiv PDFs and measures:

  - Reliability .... pipeline success rate (no crash, summary produced)
  - Latency ........ end-to-end wall time per paper (p50 / p95), split into
                     extraction time (agents, no LLM) vs summary time (LLM)
  - Parallelism .... speedup of the parallel phase vs simulated sequential
  - Extraction ..... section-detection coverage, entities / results / figures per paper
  - Summary quality  ROUGE-1/2/L F1 of the generated summary against the
                     paper's own abstract (standard reference-based eval),
                     plus compression ratio and keyword coverage

Usage:
    python evals/run_benchmark.py                    # all PDFs in backend/arxiv_papers
    python evals/run_benchmark.py --limit 5          # quick run
    python evals/run_benchmark.py --papers-dir path  # custom corpus

Outputs evals/results/benchmark_<timestamp>.json and prints a markdown report.
"""

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'backend'))

CANONICAL_SECTIONS = ['abstract', 'introduction', 'methodology', 'results', 'conclusion']
SECTION_ALIASES = {
    'methodology': ('methodology', 'methods', 'method', 'approach'),
    'results': ('results', 'experiments', 'evaluation'),
}


def _load_env():
    """Load backend/.env so GROQ_API_KEY etc. are available."""
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / 'backend' / '.env')
    except ImportError:
        pass


def _load_patterns():
    for candidate in (ROOT / 'backend' / 'patterns.json', ROOT / 'patterns.json'):
        if candidate.exists():
            with open(candidate, encoding='utf-8') as f:
                return json.load(f)
    return {}


def _find_section(sections, canonical):
    """Return text of a canonical section, tolerating alias/substring keys."""
    aliases = SECTION_ALIASES.get(canonical, (canonical,))
    for key, text in sections.items():
        key_l = key.lower()
        if any(alias in key_l for alias in aliases):
            return text or ''
    return ''


# A run only counts as a success if it produced a real summary. Mirrors the
# save gate in backend/routes/process_paper.py so the benchmark and the product
# agree on what "worked" means.
MIN_SUMMARY_WORDS = 60

_PLACEHOLDER_PREFIXES = (
    'summary generation in progress',
    'summary unavailable',
    'analysis complete. see extracted data for details.',
    'this paper presents a novel approach to the problem.',
)


def _summary_is_usable(summary_text):
    """Return (ok, failure_reason) for a generated summary."""
    text = (summary_text or '').strip()
    if not text:
        return False, 'empty_summary'
    normalised = text.lower().rstrip('.') + '.'
    if any(normalised.startswith(p) for p in _PLACEHOLDER_PREFIXES):
        return False, 'placeholder_summary'
    words = len(text.split())
    if words < MIN_SUMMARY_WORDS:
        return False, f'summary_too_short ({words} words)'
    return True, None


def _keyword_coverage(summary, entities):
    """Fraction of extracted entity names that the summary mentions."""
    names = []
    for values in (entities or {}).values():
        if isinstance(values, list):
            names.extend(str(v) for v in values)
    names = [n for n in names if len(n) > 2]
    if not names or not summary:
        return None
    summary_l = summary.lower()
    hits = sum(1 for n in names if n.lower() in summary_l)
    return hits / len(names)


async def _run_one(pdf_path, patterns, config):
    """Process one paper with a fresh orchestrator; return metrics dict."""
    from core.agents.orchestrator import ParallelAgentOrchestrator
    from rouge_score import rouge_scorer

    record = {'paper': pdf_path.name, 'success': False}
    orchestrator = ParallelAgentOrchestrator(patterns=patterns, config=config,
                                             experience_store=None)
    start = time.time()
    try:
        result = await orchestrator.process_paper(str(pdf_path))
    except Exception as e:
        record['error'] = f'{type(e).__name__}: {e}'
        record['wall_time_s'] = round(time.time() - start, 2)
        return record
    finally:
        await orchestrator.cleanup()

    wall = time.time() - start
    meta = result.get('metadata', {})
    agent_times = meta.get('agent_times', {})
    summary_block = result.get('summary', {}) or {}
    summary_text = (summary_block.get('summaries') or {}).get('main', '') or ''
    sections = (result.get('structure') or {}).get('sections', {}) or {}
    entities = (result.get('entities') or {}).get('entities', {}) or {}
    results_block = (result.get('results') or {}).get('results', {}) or {}
    figures = (result.get('figures') or {}).get('figures', []) or []

    n_results = len(results_block.get('table_results', []) or []) + \
                len(results_block.get('inline_results', []) or [])
    summary_time_s = agent_times.get('SummaryAgent', 0) / 1000.0

    sections_found = {c: bool(_find_section(sections, c)) for c in CANONICAL_SECTIONS}
    full_text = ' '.join(sections.values())

    content_ok, failure_reason = _summary_is_usable(summary_text)

    record.update({
        # A non-empty string is not success. Under `bool(summary_text)` the two
        # two-word summaries in the committed 8-paper run both counted toward a
        # headline "100% success rate", which is how a known degradation stayed
        # invisible in the top-line number.
        'success': content_ok,
        'failure_reason': failure_reason,
        'produced_output': bool(summary_text),
        'wall_time_s': round(wall, 2),
        'summary_time_s': round(summary_time_s, 2),
        'extraction_time_s': round(max(wall - summary_time_s, 0), 2),
        'parallel_speedup': round(meta.get('parallel_speedup', 1.0), 2),
        'agent_times_ms': {k: round(v, 1) for k, v in agent_times.items()},
        'sections_detected': len(sections),
        'canonical_sections_found': sections_found,
        'entities_total': sum(len(v) for v in entities.values() if isinstance(v, list)),
        'entities_by_type': {k: len(v) for k, v in entities.items() if isinstance(v, list)},
        'results_extracted': n_results,
        'figures_extracted': len(figures),
        'paper_words': len(full_text.split()),
        'summary_words': len(summary_text.split()),
        'llm_backend': (summary_block.get('metadata') or {}).get('llm_provider')
                       or (summary_block.get('metadata') or {}).get('llm_backend', 'unknown'),
    })

    if record['paper_words']:
        record['compression_ratio'] = round(
            record['summary_words'] / record['paper_words'], 4)

    abstract = _find_section(sections, 'abstract')
    if abstract and summary_text:
        scorer = rouge_scorer.RougeScorer(['rouge1', 'rouge2', 'rougeL'],
                                          use_stemmer=True)
        scores = scorer.score(abstract, summary_text)
        record['rouge'] = {k: round(v.fmeasure, 4) for k, v in scores.items()}

    coverage = _keyword_coverage(summary_text, entities)
    if coverage is not None:
        record['entity_keyword_coverage'] = round(coverage, 4)

    return record


def _pctl(values, p):
    if not values:
        return None
    values = sorted(values)
    idx = min(int(round(p / 100 * (len(values) - 1))), len(values) - 1)
    return values[idx]


def _aggregate(records):
    ok = [r for r in records if r['success']]
    failures = {}
    for r in records:
        if not r['success']:
            reason = (r.get('failure_reason') or 'unknown').split(' (')[0]
            failures[reason] = failures.get(reason, 0) + 1

    agg = {
        'papers_total': len(records),
        'papers_succeeded': len(ok),
        'success_rate': round(len(ok) / len(records), 4) if records else None,
        # Broken out so a degraded run can't hide inside the headline rate.
        'failure_reasons': failures,
    }

    def stats_for(key):
        vals = [r[key] for r in ok if r.get(key) is not None]
        if not vals:
            return None
        return {
            'mean': round(statistics.mean(vals), 3),
            'median': round(statistics.median(vals), 3),
            'p95': round(_pctl(vals, 95), 3),
            'min': round(min(vals), 3),
            'max': round(max(vals), 3),
        }

    for key in ('wall_time_s', 'extraction_time_s', 'summary_time_s',
                'parallel_speedup', 'entities_total', 'results_extracted',
                'figures_extracted', 'summary_words', 'compression_ratio',
                'entity_keyword_coverage'):
        s = stats_for(key)
        if s:
            agg[key] = s

    for metric in ('rouge1', 'rouge2', 'rougeL'):
        vals = [r['rouge'][metric] for r in ok if r.get('rouge')]
        if vals:
            agg[f'{metric}_f1_mean'] = round(statistics.mean(vals), 4)

    section_hits = {c: 0 for c in CANONICAL_SECTIONS}
    for r in ok:
        for c, found in r.get('canonical_sections_found', {}).items():
            section_hits[c] += int(found)
    if ok:
        agg['section_detection_rate'] = {
            c: round(hits / len(ok), 4) for c, hits in section_hits.items()}

    backends = {}
    for r in ok:
        backends[r.get('llm_backend', 'unknown')] = \
            backends.get(r.get('llm_backend', 'unknown'), 0) + 1
    agg['llm_backends_used'] = backends
    return agg


def _print_report(records, agg):
    print('\n## Per-paper results\n')
    print('| Paper | OK | Wall (s) | Extract (s) | Speedup | Sections | Entities | Results | Figures | ROUGE-1 | ROUGE-L |')
    print('|---|---|---|---|---|---|---|---|---|---|---|')
    for r in records:
        rouge = r.get('rouge', {})
        print('| {} | {} | {} | {} | {} | {} | {} | {} | {} | {} | {} |'.format(
            r['paper'], 'Y' if r['success'] else 'N',
            r.get('wall_time_s', '-'), r.get('extraction_time_s', '-'),
            r.get('parallel_speedup', '-'), r.get('sections_detected', '-'),
            r.get('entities_total', '-'), r.get('results_extracted', '-'),
            r.get('figures_extracted', '-'),
            rouge.get('rouge1', '-'), rouge.get('rougeL', '-')))

    print('\n## Aggregate\n')
    print(json.dumps(agg, indent=2))


async def main():
    parser = argparse.ArgumentParser(description='PaperMind pipeline benchmark')
    parser.add_argument('--papers-dir', default=str(ROOT / 'backend' / 'arxiv_papers'))
    parser.add_argument('--limit', type=int, default=0, help='max papers (0 = all)')
    parser.add_argument('--out-dir', default=str(ROOT / 'evals' / 'results'))
    parser.add_argument('--rps', type=float, default=0.5,
                        help='LLM requests/second pacing (free-tier friendly)')
    parser.add_argument('--no-graph', action='store_true',
                        help='disable the LangGraph summary engine')
    args = parser.parse_args()

    _load_env()
    if not args.no_graph:
        os.environ.setdefault('PAPERMIND_USE_GRAPH', '1')
    if args.rps:
        os.environ.setdefault('PAPERMIND_LLM_RPS', str(args.rps))
    # Benchmark must not depend on / write to Supabase.
    config = {'experience_enabled': False}

    pdfs = sorted(Path(args.papers_dir).glob('*.pdf'))
    if args.limit:
        pdfs = pdfs[:args.limit]
    if not pdfs:
        print(f'No PDFs found in {args.papers_dir}', file=sys.stderr)
        sys.exit(1)

    patterns = _load_patterns()
    print(f'Benchmarking {len(pdfs)} papers from {args.papers_dir}')
    print(f'LangGraph engine: {os.environ.get("PAPERMIND_USE_GRAPH", "0")}, '
          f'LLM pacing: {os.environ.get("PAPERMIND_LLM_RPS", "off")} rps\n')

    records = []
    for i, pdf in enumerate(pdfs, 1):
        print(f'[{i}/{len(pdfs)}] {pdf.name} ...', flush=True)
        record = await _run_one(pdf, patterns, config)
        status = 'ok' if record['success'] else f'FAILED ({record.get("error", "empty summary")})'
        print(f'    {status} in {record.get("wall_time_s", "?")}s', flush=True)
        records.append(record)

    agg = _aggregate(records)
    _print_report(records, agg)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
    out_path = out_dir / f'benchmark_{stamp}.json'
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump({'generated_at': stamp, 'aggregate': agg, 'papers': records},
                  f, indent=2)
    print(f'\nSaved: {out_path}')


if __name__ == '__main__':
    asyncio.run(main())
