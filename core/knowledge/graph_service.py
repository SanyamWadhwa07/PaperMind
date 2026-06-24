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


def get_citation_network(user_id: str, supabase_client) -> Dict[str, Any]:
    """
    Build a directed citation graph for all papers in the user's library.

    Node types: foundational (in-degree >= 3), frontier (recent, in-degree < 2), bridge (both).
    Edge direction: source_summary_id → cited paper.
    """
    nodes: List[Dict] = []
    edges: List[Dict] = []

    try:
        # Fetch all papers
        papers_resp = supabase_client.table("summaries") \
            .select("id, paper_title, arxiv_id, published_date, primary_category") \
            .eq("user_id", user_id) \
            .limit(200) \
            .execute()
        papers = {p["id"]: p for p in (papers_resp.data or [])}
        paper_ids = list(papers.keys())

        # Fetch citation lineage rows
        lineage_resp = supabase_client.table("paper_lineage") \
            .select("ancestor_id, descendant_id, link_type, link_confidence") \
            .in_("ancestor_id", paper_ids) \
            .execute()

        in_degree: Dict[str, int] = {pid: 0 for pid in paper_ids}
        for row in (lineage_resp.data or []):
            if row["descendant_id"] in in_degree:
                in_degree[row["descendant_id"]] = in_degree.get(row["descendant_id"], 0) + 1
            edges.append({
                "from": f"paper_{row['ancestor_id']}",
                "to": f"paper_{row['descendant_id']}",
                "arrows": "to",
                "link_type": row.get("link_type", "cites"),
                "value": float(row.get("link_confidence") or 0.7),
                "title": row.get("link_type", "cites"),
                "color": _link_type_color(row.get("link_type", "cites")),
                "group": "citation",
            })

        # Also fetch paper_citations for cross-referencing
        cite_resp = supabase_client.table("paper_citations") \
            .select("source_summary_id, cited_arxiv_id, cited_title, confidence") \
            .in_("source_summary_id", paper_ids) \
            .execute()

        # Build arxiv_id → paper_id map
        arxiv_to_id = {p.get("arxiv_id"): pid for pid, p in papers.items() if p.get("arxiv_id")}

        for cite in (cite_resp.data or []):
            target_id = arxiv_to_id.get(cite.get("cited_arxiv_id"))
            src = cite["source_summary_id"]
            if target_id and target_id != src and target_id in papers:
                in_degree[target_id] = in_degree.get(target_id, 0) + 1
                edge_id = f"{src}_{target_id}"
                edges.append({
                    "from": f"paper_{src}",
                    "to": f"paper_{target_id}",
                    "arrows": "to",
                    "link_type": "cites",
                    "value": float(cite.get("confidence") or 0.6),
                    "title": "cites",
                    "color": "#94a3b8",
                    "group": "citation",
                })

        # Build nodes
        for pid, paper in papers.items():
            degree = in_degree.get(pid, 0)
            if degree >= 3:
                node_type = "foundational"
                color = "#ef4444"
            elif degree <= 1:
                node_type = "frontier"
                color = "#22c55e"
            else:
                node_type = "bridge"
                color = "#f59e0b"

            nodes.append({
                "id": f"paper_{pid}",
                "label": (paper.get("paper_title") or "Untitled")[:35],
                "title": paper.get("paper_title"),
                "group": "paper",
                "node_type": node_type,
                "in_degree": degree,
                "published_date": paper.get("published_date"),
                "category": paper.get("primary_category", "general"),
                "summary_id": pid,
                "color": color,
                "size": 15 + min(degree * 5, 35),
            })

    except Exception as e:
        logger.error("citation_network_build_failed", error=str(e))

    return {"nodes": nodes, "edges": edges}


def _link_type_color(link_type: str) -> str:
    return {
        "cites": "#94a3b8",
        "extends": "#3b82f6",
        "replicates": "#8b5cf6",
        "contradicts": "#ef4444",
        "inspired_by": "#f59e0b",
    }.get(link_type, "#94a3b8")


def get_author_graph(user_id: str, supabase_client) -> Dict[str, Any]:
    """
    Build a co-authorship graph from the user's paper library.
    Nodes = authors, edges = co-authored at least one paper (weight = paper count).
    """
    nodes: List[Dict] = []
    edges: List[Dict] = []

    try:
        resp = supabase_client.table("summaries") \
            .select("id, paper_title, paper_authors") \
            .eq("user_id", user_id) \
            .limit(200) \
            .execute()
        papers = resp.data or []

        author_papers: Dict[str, List[str]] = {}
        co_weight: Dict[tuple, int] = {}

        for paper in papers:
            authors = paper.get("paper_authors") or []
            pid = paper["id"]
            for a in authors[:8]:  # cap per paper to avoid explosion
                author_papers.setdefault(a, []).append(pid)

            for i, a1 in enumerate(authors[:8]):
                for a2 in authors[i + 1:8]:
                    key = (min(a1, a2), max(a1, a2))
                    co_weight[key] = co_weight.get(key, 0) + 1

        # Build nodes — size proportional to paper count
        for author, pids in author_papers.items():
            nodes.append({
                "id": f"author_{author}",
                "label": author[:30],
                "title": f"{author} ({len(pids)} papers)",
                "group": "author",
                "paper_count": len(pids),
                "size": 10 + min(len(pids) * 4, 30),
                "color": "#6366f1",
            })

        # Build edges
        for (a1, a2), weight in co_weight.items():
            edges.append({
                "from": f"author_{a1}",
                "to": f"author_{a2}",
                "value": weight,
                "title": f"{weight} co-authored paper(s)",
                "group": "coauthorship",
                "color": "#c4b5fd",
            })

    except Exception as e:
        logger.error("author_graph_build_failed", error=str(e))

    return {"nodes": nodes, "edges": edges}
