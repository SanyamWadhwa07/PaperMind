"""Temporal paper lineage service.

Builds and queries paper_lineage — the directed graph connecting
older papers (ancestors) to newer ones (descendants).
"""

from __future__ import annotations
import logging
from typing import Dict, List, Any, Optional
from collections import deque

logger = logging.getLogger(__name__)


def infer_lineage_from_citations(
    summary_id: str,
    citations: List[Dict],
    supabase_client
) -> int:
    """Insert paper_lineage rows for citations that match existing library papers."""
    matched = [c for c in citations if c.get('matched_summary_id')]
    if not matched:
        return 0

    rows = []
    for c in matched:
        ancestor = c['matched_summary_id']
        descendant = summary_id
        if ancestor == descendant:
            continue
        rows.append({
            'ancestor_id': ancestor,
            'descendant_id': descendant,
            'link_type': 'cites',
            'link_confidence': c.get('confidence', 0.7),
            'inferred_by': 'citation',
        })

    if not rows:
        return 0

    try:
        supabase_client.table('paper_lineage') \
            .upsert(rows, on_conflict='ancestor_id,descendant_id') \
            .execute()
        return len(rows)
    except Exception as e:
        logger.warning("lineage_citation_insert_failed", error=str(e))
        return 0


def infer_lineage_from_similarity(
    summary_id: str,
    supabase_client,
    threshold: float = 0.75
) -> int:
    """Create 'inspired_by' lineage links for highly similar papers
    where no direct citation link already exists."""
    try:
        # Get highly similar papers
        sim_result = supabase_client.table('paper_similarity') \
            .select('paper_b_id, similarity_score') \
            .eq('paper_a_id', summary_id) \
            .gte('similarity_score', threshold) \
            .execute()

        existing_result = supabase_client.table('paper_lineage') \
            .select('ancestor_id, descendant_id') \
            .or_(f'ancestor_id.eq.{summary_id},descendant_id.eq.{summary_id}') \
            .execute()

        existing_pairs = {
            (r['ancestor_id'], r['descendant_id']) for r in (existing_result.data or [])
        }

        rows = []
        for row in (sim_result.data or []):
            other_id = row['paper_b_id']
            pair = (summary_id, other_id)
            reverse = (other_id, summary_id)
            if pair not in existing_pairs and reverse not in existing_pairs:
                rows.append({
                    'ancestor_id': summary_id,
                    'descendant_id': other_id,
                    'link_type': 'inspired_by',
                    'link_confidence': float(row['similarity_score']),
                    'inferred_by': 'similarity',
                })

        if rows:
            supabase_client.table('paper_lineage') \
                .upsert(rows, on_conflict='ancestor_id,descendant_id') \
                .execute()
        return len(rows)
    except Exception as e:
        logger.warning("lineage_similarity_infer_failed", error=str(e))
        return 0


def get_ancestry_tree(
    summary_id: str,
    supabase_client,
    depth: int = 3
) -> Dict[str, Any]:
    """BFS up and down the lineage graph from a given paper.

    Returns {nodes: [...], edges: [...]} for vis-network rendering.
    """
    nodes: List[Dict] = []
    edges: List[Dict] = []
    visited: set = set()
    queue: deque = deque([(summary_id, 0)])
    visited.add(summary_id)

    while queue:
        current_id, current_depth = queue.popleft()
        if current_depth > depth:
            continue

        # Fetch paper info
        try:
            row = supabase_client.table('summaries') \
                .select('id, paper_title, published_date, primary_category') \
                .eq('id', current_id) \
                .single() \
                .execute()
            if row.data:
                is_anchor = current_id == summary_id
                nodes.append({
                    'id': current_id,
                    'label': (row.data.get('paper_title') or 'Untitled')[:35],
                    'title': row.data.get('paper_title', ''),
                    'published_date': row.data.get('published_date'),
                    'category': row.data.get('primary_category', 'general'),
                    'is_anchor': is_anchor,
                    'depth': current_depth,
                })
        except Exception:
            pass

        if current_depth >= depth:
            continue

        # Fetch ancestors (older papers this paper cites)
        try:
            anc_result = supabase_client.table('paper_lineage') \
                .select('ancestor_id, link_type, link_confidence') \
                .eq('descendant_id', current_id) \
                .execute()
            for r in (anc_result.data or []):
                aid = r['ancestor_id']
                edges.append({
                    'from': aid, 'to': current_id,
                    'link_type': r['link_type'],
                    'confidence': r['link_confidence'],
                })
                if aid not in visited:
                    visited.add(aid)
                    queue.append((aid, current_depth + 1))
        except Exception:
            pass

        # Fetch descendants (newer papers citing this paper)
        try:
            desc_result = supabase_client.table('paper_lineage') \
                .select('descendant_id, link_type, link_confidence') \
                .eq('ancestor_id', current_id) \
                .execute()
            for r in (desc_result.data or []):
                did = r['descendant_id']
                edges.append({
                    'from': current_id, 'to': did,
                    'link_type': r['link_type'],
                    'confidence': r['link_confidence'],
                })
                if did not in visited:
                    visited.add(did)
                    queue.append((did, current_depth + 1))
        except Exception:
            pass

    return {'nodes': nodes, 'edges': edges}


def build_timeline_graph(user_id: str, supabase_client) -> Dict[str, Any]:
    """Return all user papers ordered by date with lineage edges."""
    try:
        papers_result = supabase_client.table('summaries') \
            .select('id, paper_title, published_date, primary_category, quality_score') \
            .eq('user_id', user_id) \
            .order('published_date', desc=False) \
            .execute()

        paper_ids = [p['id'] for p in (papers_result.data or [])]

        lineage_result = supabase_client.table('paper_lineage') \
            .select('ancestor_id, descendant_id, link_type, link_confidence') \
            .in_('ancestor_id', paper_ids) \
            .execute()

        return {
            'papers': papers_result.data or [],
            'lineage': lineage_result.data or [],
        }
    except Exception as e:
        logger.error("timeline_build_failed", error=str(e))
        return {'papers': [], 'lineage': []}
