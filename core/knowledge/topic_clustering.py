"""BERTopic-based topic clustering using pre-computed embeddings from Supabase."""

import structlog
from typing import Any, Dict, List, Optional

logger = structlog.get_logger(__name__)

try:
    from bertopic import BERTopic
    from umap import UMAP
    from hdbscan import HDBSCAN
    BERTOPIC_AVAILABLE = True
except ImportError:
    BERTOPIC_AVAILABLE = False
    logger.warning(
        "BERTopic not installed — topic clustering unavailable. "
        "Install with: pip install bertopic hdbscan umap-learn"
    )


def compute_topic_clusters(user_id: str, supabase_client: Any) -> Dict[str, Any]:
    """
    Fetch all embeddings for a user's papers, run BERTopic,
    and write cluster assignments to paper_topic_clusters.
    Returns a summary dict.
    """
    if not BERTOPIC_AVAILABLE:
        return {"error": "BERTopic not installed", "clusters": []}

    # Fetch papers + embeddings
    resp = (
        supabase_client.table("summaries")
        .select("id, paper_title, abstract_text, embedding")
        .eq("user_id", user_id)
        .limit(500)
        .execute()
    )
    papers = [p for p in (resp.data or []) if p.get("embedding")]

    if len(papers) < 3:
        return {"error": "Need at least 3 papers with embeddings", "clusters": []}

    import numpy as np

    from .graph_service import _as_vector

    # Same pgvector-returns-text quirk as the similarity cache: the column comes
    # back as "[0.1,-0.2,…]", which numpy cannot read as floats.
    embeddings = np.stack([_as_vector(p["embedding"]) for p in papers])
    docs = [
        f"{p.get('paper_title', '')} {(p.get('abstract_text') or '')[:200]}"
        for p in papers
    ]

    try:
        # Use low-dimension UMAP to fit in 4GB RAM
        umap_model = UMAP(n_neighbors=min(15, len(papers) - 1), n_components=5,
                          metric="cosine", random_state=42)
        hdbscan_model = HDBSCAN(min_cluster_size=max(2, len(papers) // 15),
                                 metric="euclidean", prediction_data=True)
        topic_model = BERTopic(
            umap_model=umap_model,
            hdbscan_model=hdbscan_model,
            embedding_model=None,  # pass pre-computed embeddings
            verbose=False,
        )
        topics, _ = topic_model.fit_transform(docs, embeddings)
    except Exception as e:
        logger.error("bertopic_fit_failed", error=str(e))
        return {"error": str(e), "clusters": []}

    # Persist to DB
    rows = []
    for paper, topic_id in zip(papers, topics):
        if topic_id == -1:
            continue  # outlier / noise
        topic_info = topic_model.get_topic(topic_id)
        keywords = [w for w, _ in topic_info[:5]] if topic_info else []
        rows.append({
            "summary_id": paper["id"],
            "user_id": user_id,
            "cluster_id": int(topic_id),
            "cluster_label": f"Topic {topic_id}: {', '.join(keywords[:3])}",
            "cluster_keywords": keywords,
            "probability": 0.8,  # BERTopic does return probs but we keep it simple
        })

    if rows:
        try:
            supabase_client.table("paper_topic_clusters") \
                .upsert(rows, on_conflict="summary_id,cluster_id") \
                .execute()
        except Exception as e:
            logger.warning("topic_cluster_persist_failed", error=str(e))

    num_topics = len(set(topics)) - (1 if -1 in topics else 0)
    return {
        "num_papers": len(papers),
        "num_topics": num_topics,
        "rows_written": len(rows),
    }


def get_topic_landscape(user_id: str, supabase_client: Any) -> Dict[str, Any]:
    """
    Read pre-computed topic clusters and return a vis-network compatible graph.
    Cluster nodes + paper membership edges.
    """
    nodes: List[Dict] = []
    edges: List[Dict] = []

    try:
        clusters_resp = (
            supabase_client.table("paper_topic_clusters")
            .select("summary_id, cluster_id, cluster_label, cluster_keywords, probability, "
                    "summaries(paper_title, primary_category)")
            .eq("user_id", user_id)
            .execute()
        )
        rows = clusters_resp.data or []

        seen_clusters: Dict[int, str] = {}
        seen_papers: Dict[str, str] = {}

        for row in rows:
            cid = row["cluster_id"]
            sid = row["summary_id"]
            label = row.get("cluster_label") or f"Topic {cid}"

            # Cluster node
            cluster_node_id = f"cluster_{cid}"
            if cid not in seen_clusters:
                seen_clusters[cid] = cluster_node_id
                nodes.append({
                    "id": cluster_node_id,
                    "label": label[:40],
                    "title": ", ".join(row.get("cluster_keywords") or []),
                    "group": "cluster",
                    "color": _cluster_color(cid),
                    "shape": "diamond",
                    "size": 25,
                })

            # Paper node
            paper_node_id = f"paper_{sid}"
            if sid not in seen_papers:
                seen_papers[sid] = paper_node_id
                paper = row.get("summaries") or {}
                nodes.append({
                    "id": paper_node_id,
                    "label": (paper.get("paper_title") or "Untitled")[:35],
                    "title": paper.get("paper_title", ""),
                    "group": "paper",
                    "summary_id": sid,
                    "color": "#64748b",
                    "size": 10,
                })

            edges.append({
                "from": cluster_node_id,
                "to": paper_node_id,
                "value": float(row.get("probability") or 0.5),
                "group": "membership",
                "color": "#e2e8f0",
            })

    except Exception as e:
        logger.error("topic_landscape_build_failed", error=str(e))

    return {"nodes": nodes, "edges": edges}


def _cluster_color(cluster_id: int) -> str:
    colors = ["#6366f1", "#ec4899", "#f59e0b", "#10b981", "#3b82f6",
              "#8b5cf6", "#ef4444", "#06b6d4", "#84cc16", "#f97316"]
    return colors[cluster_id % len(colors)]
