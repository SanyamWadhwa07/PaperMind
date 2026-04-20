"""Cross-paper comparison service.

Aggregates metrics, entity overlap, and key findings across a set of papers
for the ComparisonTable frontend component.
"""

from __future__ import annotations
import logging
import re
from difflib import SequenceMatcher
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

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
    supabase_client
) -> Dict[str, Any]:
    """Build a full comparison object for the given paper IDs."""
    if not summary_ids or len(summary_ids) > 10:
        return {'error': 'Provide 2–10 paper IDs'}

    # Fetch all papers
    result = supabase_client.table('summaries') \
        .select('id, paper_title, arxiv_id, published_date, quality_score, summary_data') \
        .in_('id', summary_ids) \
        .execute()

    papers_raw = {r['id']: r for r in (result.data or [])}

    paper_meta = []
    metrics_matrix: Dict[str, Dict[str, Optional[str]]] = {}
    entity_overlap: Dict[str, Dict[str, List[str]]] = {
        'datasets': {}, 'models': {}, 'metrics': {}, 'frameworks': {}
    }
    all_findings: Dict[str, List[str]] = {}

    for pid in summary_ids:
        if pid not in papers_raw:
            continue
        row = papers_raw[pid]
        sd = row.get('summary_data') or {}

        paper_meta.append({
            'id': pid,
            'title': row.get('paper_title', 'Untitled'),
            'arxiv_id': row.get('arxiv_id'),
            'date': row.get('published_date'),
            'quality_score': row.get('quality_score'),
        })

        # --- Metrics ---
        results_data = sd.get('results', {})
        raw_metrics = results_data.get('metrics', []) if isinstance(results_data, dict) else []
        for m in raw_metrics:
            metric_name = _normalize_metric(m.get('metric', ''))
            val = m.get('value')
            if metric_name and val:
                if metric_name not in metrics_matrix:
                    metrics_matrix[metric_name] = {}
                metrics_matrix[metric_name][pid] = str(val)

        # --- Entity overlap ---
        entities = sd.get('entities', {})
        for etype in ('datasets', 'models', 'metrics', 'frameworks'):
            for ent in (entities.get(etype) or []):
                ent_str = str(ent)
                if ent_str not in entity_overlap[etype]:
                    entity_overlap[etype][ent_str] = []
                if pid not in entity_overlap[etype][ent_str]:
                    entity_overlap[etype][ent_str].append(pid)

        # --- Key findings ---
        all_findings[pid] = [str(f) for f in (sd.get('key_findings') or [])[:5]]

    # Fill in nulls for missing metric/paper combos
    for metric_name in metrics_matrix:
        for pid in summary_ids:
            if pid not in metrics_matrix[metric_name]:
                metrics_matrix[metric_name][pid] = None

    # Cluster findings by semantic similarity
    findings_clusters = _cluster_findings(all_findings)

    # Sort by date for temporal progression
    paper_meta.sort(key=lambda p: (p.get('date') or ''), reverse=False)

    return {
        'papers': paper_meta,
        'metrics_matrix': metrics_matrix,
        'entity_overlap': entity_overlap,
        'findings_clusters': findings_clusters,
        'temporal_progression': [p['date'] for p in paper_meta],
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
