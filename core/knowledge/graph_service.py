"""Knowledge graph service — similarity caching, graph queries, recommendations."""

from __future__ import annotations
import logging
from typing import List, Dict, Any, Optional
import numpy as np

logger = logging.getLogger(__name__)


def compute_and_cache_similarity(
    new_summary_id: str,
    user_id: str,
    supabase_client,
    top_k: int = 10
) -> int:
    """Compute cosine similarity between a new paper and existing library papers.

    Inserts top-K pairs into paper_similarity table.
    Returns the number of rows inserted.
    """
    try:
        # Fetch embedding of new paper
        row = supabase_client.table('summaries') \
            .select('embedding') \
            .eq('id', new_summary_id) \
            .single() \
            .execute()

        if not row.data or not row.data.get('embedding'):
            logger.warning("no_embedding_for_paper", summary_id=new_summary_id)
            return 0

        new_embedding = np.array(row.data['embedding'], dtype=np.float32)

        # Find similar papers via pgvector
        result = supabase_client.rpc('match_papers', {
            'query_embedding': new_embedding.tolist(),
            'p_user_id': user_id,
            'match_count': top_k + 1,  # +1 to exclude self
            'min_similarity': 0.3,
        }).execute()

        similar = [r for r in (result.data or []) if r['id'] != new_summary_id][:top_k]

        if not similar:
            return 0

        rows = [
            {
                'paper_a_id': new_summary_id,
                'paper_b_id': r['id'],
                'similarity_score': round(r['similarity'], 5),
            }
            for r in similar
        ]

        supabase_client.table('paper_similarity').upsert(rows, on_conflict='paper_a_id,paper_b_id').execute()
        return len(rows)

    except Exception as e:
        logger.error("similarity_cache_failed", error=str(e), summary_id=new_summary_id)
        return 0


def get_paper_recommendations(
    summary_id: str,
    supabase_client,
    top_k: int = 5
) -> List[Dict[str, Any]]:
    """Return top-K similar papers from the pre-computed similarity cache."""
    try:
        result = supabase_client.table('paper_similarity') \
            .select('paper_b_id, similarity_score, summaries!paper_b_id(paper_title, arxiv_id, created_at)') \
            .eq('paper_a_id', summary_id) \
            .order('similarity_score', desc=True) \
            .limit(top_k) \
            .execute()

        return result.data or []
    except Exception as e:
        logger.warning("recommendations_failed", error=str(e))
        return []


def get_knowledge_graph(
    user_id: str,
    supabase_client,
    anchor_summary_id: Optional[str] = None,
    depth: int = 2,
    max_nodes: int = 80
) -> Dict[str, Any]:
    """Build a graph dict (nodes + edges) for vis-network rendering.

    If anchor_summary_id is given, returns the local neighbourhood.
    Otherwise returns the full user library graph.
    """
    nodes: List[Dict] = []
    edges: List[Dict] = []
    seen_paper_ids: set = set()
    seen_entity_ids: set = set()

    try:
        # --- Paper nodes ---
        query = supabase_client.table('summaries') \
            .select('id, paper_title, arxiv_id, primary_category, published_date, quality_score') \
            .eq('user_id', user_id) \
            .limit(max_nodes)

        result = query.execute()
        papers = result.data or []

        for p in papers:
            pid = p['id']
            seen_paper_ids.add(pid)
            nodes.append({
                'id': f'paper_{pid}',
                'label': (p['paper_title'] or 'Untitled')[:40],
                'title': p['paper_title'],
                'group': 'paper',
                'category': p.get('primary_category', 'general'),
                'published_date': p.get('published_date'),
                'quality_score': p.get('quality_score'),
                'summary_id': pid,
            })

        # --- Similarity edges ---
        paper_ids = list(seen_paper_ids)
        if paper_ids:
            sim_result = supabase_client.table('paper_similarity') \
                .select('paper_a_id, paper_b_id, similarity_score') \
                .in_('paper_a_id', paper_ids) \
                .gte('similarity_score', 0.5) \
                .limit(200) \
                .execute()

            for row in (sim_result.data or []):
                if row['paper_b_id'] in seen_paper_ids:
                    edges.append({
                        'from': f"paper_{row['paper_a_id']}",
                        'to': f"paper_{row['paper_b_id']}",
                        'value': float(row['similarity_score']),
                        'title': f"Similarity: {row['similarity_score']:.2f}",
                        'group': 'similarity',
                        'color': '#94a3b8',
                    })

        # --- Entity nodes (from entity_relationships) ---
        if paper_ids:
            ent_result = supabase_client.table('entity_relationships') \
                .select('entity_1, entity_1_type, entity_2, entity_2_type, relationship_type, frequency_count, confidence_score') \
                .limit(300) \
                .execute()

            entity_color = {
                'model': '#8b5cf6', 'dataset': '#3b82f6',
                'metric': '#10b981', 'framework': '#f59e0b',
            }

            for row in (ent_result.data or []):
                for ent, etype in [(row['entity_1'], row['entity_1_type']), (row['entity_2'], row['entity_2_type'])]:
                    eid = f'entity_{ent}_{etype}'
                    if eid not in seen_entity_ids:
                        seen_entity_ids.add(eid)
                        nodes.append({
                            'id': eid,
                            'label': ent[:30],
                            'group': 'entity',
                            'entity_type': etype,
                            'color': entity_color.get(etype, '#64748b'),
                            'shape': 'box',
                        })

                edges.append({
                    'from': f"entity_{row['entity_1']}_{row['entity_1_type']}",
                    'to': f"entity_{row['entity_2']}_{row['entity_2_type']}",
                    'value': row.get('frequency_count', 1),
                    'title': row.get('relationship_type', 'co-occurs'),
                    'group': 'entity_rel',
                    'color': '#cbd5e1',
                })

    except Exception as e:
        logger.error("knowledge_graph_build_failed", error=str(e))

    return {'nodes': nodes, 'edges': edges}
