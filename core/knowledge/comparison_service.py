"""Cross-paper comparison service.

Aggregates metrics, entity overlap, and key findings across a set of papers
for the ComparisonTable frontend component.
"""

from __future__ import annotations
import re
from difflib import SequenceMatcher
from typing import List, Dict, Any, Optional

# structlog, not stdlib logging: every logger call in this project passes
# keyword fields, and `logging.Logger.warning` raises TypeError on those — which
# turns a handled failure into an unhandled one. See CLAUDE.md.
import structlog

logger = structlog.get_logger(__name__)

# Entity buckets worth comparing, in display order. Read from whatever the
# summary actually carries rather than hardcoded: `frameworks` was in the old
# fixed tuple but is never written by the pipeline, while `tasks` — which is
# written on every paper — was not in it, so task overlap never appeared.
_ENTITY_ORDER = ('datasets', 'models', 'metrics', 'tasks', 'frameworks')

MAX_PAPERS = 10
MIN_PAPERS = 2


class ComparisonError(ValueError):
    """The request cannot be compared — bad ID count, or nothing readable."""

# Normalize common metric name aliases
_METRIC_ALIASES = {
    r'\bacc(uracy)?\b': 'Accuracy',
    r'\btop-?1\b': 'Accuracy',
    r'\bf-?1\b': 'F1',
    r'\bmap\b': 'mAP',
    r'\bmean average precision\b': 'mAP',
    r'\bbleu\b': 'BLEU',
    r'\brouge\b': 'ROUGE',
    r'\bprecision\b': 'Precision',
    r'\brecall\b': 'Recall',
    r'\biou\b': 'IoU',
    r'\bauc\b': 'AUC',
    r'\bperplexity\b': 'Perplexity',
}


def _normalize_metric(name: str) -> str:
    lower = name.lower().strip()
    for pattern, canonical in _METRIC_ALIASES.items():
        if re.search(pattern, lower):
            return canonical
    return name.title()


def compare_papers(
    summary_ids: List[str],
    supabase_client,
    rows: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Build a full comparison object for the given paper IDs.

    `rows` lets a caller that has already loaded the summaries pass them in.
    The route ahead of this one queries the same table to check ownership, so
    without it every comparison read the corpus twice.
    """
    if not (MIN_PAPERS <= len(summary_ids) <= MAX_PAPERS):
        # Raised, not returned. This used to be `{'error': ...}` handed straight
        # back by the route, so the client received HTTP 200 with a body the
        # comparison table could not read and rendered "No comparison data
        # available" — a validation failure presented as an empty result.
        raise ComparisonError(f'Provide {MIN_PAPERS}–{MAX_PAPERS} paper IDs')

    if rows is None:
        result = supabase_client.table('summaries') \
            .select('id, paper_title, arxiv_id, published_date, quality_score, summary_data') \
            .in_('id', summary_ids) \
            .execute()
        rows = result.data or []

    papers_raw = {r['id']: r for r in rows}

    missing = [pid for pid in summary_ids if pid not in papers_raw]
    if missing:
        logger.warning('comparison_papers_missing', count=len(missing))
    if len(papers_raw) < MIN_PAPERS:
        raise ComparisonError(
            'Fewer than two of those papers could be loaded, so there is '
            'nothing to compare.'
        )

    paper_meta = []
    metrics_matrix: Dict[str, Dict[str, Optional[str]]] = {}
    entity_overlap: Dict[str, Dict[str, List[str]]] = {}
    all_findings: Dict[str, List[str]] = {}

    # Only the papers that actually loaded — a missing row must not become a
    # column of dashes implying the paper was compared and had no data.
    present_ids = [pid for pid in summary_ids if pid in papers_raw]

    for pid in present_ids:
        row = papers_raw[pid]
        sd = row.get('summary_data') or {}

        paper_meta.append({
            'id': pid,
            'title': row.get('paper_title') or 'Untitled',
            'arxiv_id': row.get('arxiv_id'),
            'date': row.get('published_date'),
            'quality_score': row.get('quality_score'),
        })

        # --- Metrics ---
        results_data = sd.get('results', {})
        raw_metrics = results_data.get('metrics', []) if isinstance(results_data, dict) else []
        for m in raw_metrics:
            if not isinstance(m, dict):
                continue
            metric_name = _normalize_metric(m.get('metric') or '')
            val = m.get('value')
            if not metric_name or val in (None, ''):
                continue
            row_cells = metrics_matrix.setdefault(metric_name, {})
            # A paper can report the same measurement several times (per model,
            # per dataset). Keep the one it marked best, else the first — the
            # previous version let the last row silently overwrite the rest.
            if pid not in row_cells or m.get('is_best'):
                row_cells[pid] = str(val)

        # --- Entity overlap ---
        entities = sd.get('entities') or {}
        if isinstance(entities, dict):
            for etype, values in entities.items():
                if not isinstance(values, list):
                    continue
                bucket = entity_overlap.setdefault(etype, {})
                for ent in values:
                    ent_str = str(ent).strip()
                    if not ent_str:
                        continue
                    papers_with = bucket.setdefault(ent_str, [])
                    if pid not in papers_with:
                        papers_with.append(pid)

        # --- Key findings ---
        all_findings[pid] = [str(f) for f in (sd.get('key_findings') or [])[:5]]

    # Fill in nulls so every metric row has a cell per paper — the table reads
    # position, and a short row would shift the remaining values left.
    for cells in metrics_matrix.values():
        for pid in present_ids:
            cells.setdefault(pid, None)

    # Buckets in a stable display order, with anything unrecognised after the
    # known ones rather than dropped.
    ordered_overlap = {
        etype: entity_overlap[etype]
        for etype in _ENTITY_ORDER
        if entity_overlap.get(etype)
    }
    ordered_overlap.update({
        etype: values
        for etype, values in entity_overlap.items()
        if etype not in _ENTITY_ORDER and values
    })

    findings_clusters = _cluster_findings(all_findings)

    # Oldest first, so reading down the columns follows the field's progression.
    paper_meta.sort(key=lambda p: (p.get('date') or ''))

    logger.info(
        'comparison_built',
        papers=len(paper_meta),
        metrics=len(metrics_matrix),
        clusters=len(findings_clusters),
    )

    return {
        'papers': paper_meta,
        'metrics_matrix': metrics_matrix,
        'entity_overlap': ordered_overlap,
        'findings_clusters': findings_clusters,
        'temporal_progression': [p['date'] for p in paper_meta],
        'missing_ids': missing,
    }


def _cluster_findings(all_findings: Dict[str, List[str]]) -> List[Dict]:
    """Group findings from different papers that are semantically similar."""
    clusters: List[Dict] = []
    used: set = set()

    items = [(pid, i, text) for pid, findings in all_findings.items() for i, text in enumerate(findings)]

    for idx, (pid, fi, text) in enumerate(items):
        key = (pid, fi)
        if key in used:
            continue

        cluster_papers = [pid]
        cluster_texts = [text]
        used.add(key)

        for jdx, (other_pid, other_fi, other_text) in enumerate(items):
            if jdx <= idx:
                continue
            other_key = (other_pid, other_fi)
            if other_key in used:
                continue
            if SequenceMatcher(None, text.lower(), other_text.lower()).ratio() > 0.45:
                cluster_papers.append(other_pid)
                cluster_texts.append(other_text)
                used.add(other_key)

        clusters.append({
            'representative': text[:200],
            'papers': list(set(cluster_papers)),
            'unique_to': cluster_papers[0] if len(set(cluster_papers)) == 1 else None,
        })

    return clusters[:30]
