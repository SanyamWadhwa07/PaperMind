"""Knowledge graph service — similarity caching, graph queries, recommendations."""

from __future__ import annotations
import json
import structlog
from typing import List, Dict, Any, Optional
import numpy as np

logger = structlog.get_logger(__name__)


def _as_vector(embedding: Any) -> np.ndarray:
    """Coerce a stored embedding into a float array.

    PostgREST serialises a pgvector column as its text form — `"[0.1,-0.2,…]"` —
    not as a JSON array, so the value arrives as a string on the read path even
    though it was written as a list. Feeding that straight to numpy raised
    `could not convert string to float`, which killed similarity caching for
    every paper and left the recommendation table empty.
    """
    if isinstance(embedding, str):
        embedding = json.loads(embedding)
    return np.array(embedding, dtype=np.float32)


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

        new_embedding = _as_vector(row.data['embedding'])

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


# `summary_data.entities` buckets, mapped to the singular kind the UI colours by.
ENTITY_KINDS = {
    'models': 'model',
    'datasets': 'dataset',
    'metrics': 'metric',
    'tasks': 'task',
    'frameworks': 'framework',
}

# Per paper, so one over-extracted paper cannot bury the rest of the graph.
MAX_ENTITIES_PER_PAPER = 10


def _entity_id(name: str, kind: str) -> str:
    return f'entity_{kind}_{name.strip().lower()}'


def _authors_label(authors: Any) -> str:
    """Cite-style author line: one name, two names, or 'First et al.'."""
    if isinstance(authors, str):
        authors = [a.strip() for a in authors.split(',') if a.strip()]
    if not isinstance(authors, list) or not authors:
        return ''
    names = [str(a).strip() for a in authors if str(a).strip()]
    if not names:
        return ''
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f'{names[0]} & {names[1]}'
    return f'{names[0]} et al.'


def _paper_entities(row: Dict[str, Any]) -> List[tuple]:
    """Yield (name, kind) for one paper's extracted entities, deduplicated."""
    entities = row.get('entities')
    if isinstance(entities, str):
        try:
            entities = json.loads(entities)
        except ValueError:
            entities = None
    if not isinstance(entities, dict):
        return []

    out: List[tuple] = []
    seen: set = set()
    for bucket, kind in ENTITY_KINDS.items():
        for name in (entities.get(bucket) or [])[:MAX_ENTITIES_PER_PAPER]:
            if not isinstance(name, str):
                continue
            name = name.strip()
            key = (name.lower(), kind)
            if not name or key in seen:
                continue
            seen.add(key)
            out.append((name, kind))
    return out


def get_knowledge_graph(
    user_id: str,
    supabase_client,
    anchor_summary_id: Optional[str] = None,
    max_nodes: int = 80
) -> Dict[str, Any]:
    """Build a graph dict (nodes + edges) for vis-network rendering.

    If `anchor_summary_id` is given the graph is that paper's neighbourhood: the
    paper, the things it talks about, and the library papers that share them.
    Otherwise it is the whole library.

    Entities come from each paper's own `summary_data.entities`. They used to be
    read from `entity_relationships`, which is the cross-paper *experience*
    store — a global table with no user_id and no summary_id. Every graph
    therefore showed up to 300 relationships belonging to whichever users had
    processed papers most recently, connected to nothing on screen: a privacy
    leak that also happened to be the reason the graph looked like noise.
    `anchor_summary_id` was accepted and then ignored, so "this paper's graph"
    and "the whole library" rendered identically.
    """
    nodes: List[Dict] = []
    edges: List[Dict] = []

    try:
        # `->` selects inside the JSONB blob so the whole summary payload does
        # not cross the wire for every paper in the library.
        columns = (
            'id, paper_title, paper_authors, arxiv_id, primary_category, '
            'published_date, quality_score, summary_data->entities'
        )
        papers = supabase_client.table('summaries') \
            .select(columns) \
            .eq('user_id', user_id) \
            .order('created_at', desc=True) \
            .limit(max_nodes) \
            .execute().data or []

        by_id = {p['id']: p for p in papers}

        # --- Similarity edges, scoped to papers we actually hold ---------------
        paper_ids = list(by_id)
        similarity: List[Dict[str, Any]] = []
        if paper_ids:
            similarity = supabase_client.table('paper_similarity') \
                .select('paper_a_id, paper_b_id, similarity_score') \
                .in_('paper_a_id', paper_ids) \
                .gte('similarity_score', 0.5) \
                .limit(200) \
                .execute().data or []
            similarity = [r for r in similarity if r['paper_b_id'] in by_id]

        # --- Decide which papers belong on screen ------------------------------
        if anchor_summary_id and anchor_summary_id in by_id:
            neighbours = {
                r['paper_b_id'] if r['paper_a_id'] == anchor_summary_id else r['paper_a_id']
                for r in similarity
                if anchor_summary_id in (r['paper_a_id'], r['paper_b_id'])
            }
            visible = {anchor_summary_id} | neighbours
        else:
            visible = set(by_id)

        for pid in visible:
            p = by_id[pid]
            nodes.append({
                'id': f'paper_{pid}',
                'label': (p.get('paper_title') or 'Untitled')[:40],
                'title': p.get('paper_title'),
                # Rendered under the title, so a node says which paper it is
                # and whose. "et al." after the first two, the way a citation
                # would — the full list does not fit beside a 20px circle.
                'authors': _authors_label(p.get('paper_authors')),
                'arxiv_id': p.get('arxiv_id'),
                'group': 'paper',
                'category': p.get('primary_category') or 'general',
                'published_date': p.get('published_date'),
                'quality_score': p.get('quality_score'),
                'summary_id': pid,
                'is_anchor': pid == anchor_summary_id,
            })

        for row in similarity:
            if row['paper_a_id'] in visible and row['paper_b_id'] in visible:
                score = float(row['similarity_score'])
                edges.append({
                    'from': f"paper_{row['paper_a_id']}",
                    'to': f"paper_{row['paper_b_id']}",
                    'value': score,
                    'title': f'{score * 100:.0f}% similar',
                    'group': 'similarity',
                })

        # --- Entity nodes, from the papers on screen ---------------------------
        # An entity earns a node when it is the anchor's, or when it is shared by
        # more than one paper. A term mentioned by exactly one non-anchor paper
        # adds a leaf and no information.
        mentions: Dict[str, Dict[str, Any]] = {}
        for pid in visible:
            for name, kind in _paper_entities(by_id[pid]):
                eid = _entity_id(name, kind)
                entry = mentions.setdefault(
                    eid, {'name': name, 'kind': kind, 'papers': set()}
                )
                entry['papers'].add(pid)

        for eid, entry in mentions.items():
            shared = len(entry['papers']) > 1
            anchored = anchor_summary_id in entry['papers']
            if not (shared or anchored):
                continue

            nodes.append({
                'id': eid,
                'label': entry['name'][:30],
                'title': f"{entry['name']} · {entry['kind']}",
                'group': 'entity',
                'entity_type': entry['kind'],
                'shape': 'box',
                'paper_count': len(entry['papers']),
            })
            for pid in entry['papers']:
                edges.append({
                    'from': f'paper_{pid}',
                    'to': eid,
                    'value': 1,
                    'title': f"mentions {entry['name']}",
                    'group': 'mentions',
                })

    except Exception as e:
        logger.exception("knowledge_graph_build_failed", error=str(e))

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

    ``title``/``size``/``color`` used to be set here for the old vis-network
    renderer, which read colour and size directly off each node. The graph is
    now drawn by `KnowledgeGraph.jsx` (d3-force + design-system tokens), which
    derives colour from `group`/`entity_type` and radius from `paper_count`
    itself — those three fields were silently never read, so clicking a node
    surfaced an empty, un-styled badge instead of anything useful. `papers` is
    new: without it there was no way to show *which* papers an author's node
    represents, only a bare count.
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
        titles_by_id = {p["id"]: (p.get("paper_title") or "Untitled") for p in papers}

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

        for author, pids in author_papers.items():
            nodes.append({
                "id": f"author_{author}",
                "label": author[:30],
                "group": "author",
                "paper_count": len(pids),
                # Capped so a prolific author's node doesn't balloon the
                # payload — the click-through only ever shows a short list.
                "papers": [
                    {"id": pid, "title": titles_by_id.get(pid, "Untitled")}
                    for pid in pids[:5]
                ],
            })

        for (a1, a2), weight in co_weight.items():
            edges.append({
                "from": f"author_{a1}",
                "to": f"author_{a2}",
                "value": weight,
                "group": "coauthorship",
            })

    except Exception as e:
        logger.error("author_graph_build_failed", error=str(e))

    return {"nodes": nodes, "edges": edges}
