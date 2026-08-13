"""Topic clustering over the pre-computed embeddings already stored in Supabase.

Two engines, same output. BERTopic is used when it imports; otherwise an
equivalent pipeline built on scikit-learn runs instead.

`bertopic`, `hdbscan` and `umap-learn` are commented out of requirements.txt on
purpose — between them they pull numba, llvmlite and a C toolchain, which is a
heavy and Windows-hostile dependency for one optional view. Before this
fallback existed that choice disabled the whole Explore → Topics tab, and all
the UI could say was "BERTopic not installed".

The import is also guarded against more than a missing package. numba and
llvmlite initialise lazily and can fail inside a server process that has
already loaded torch even when the same import succeeds in a fresh shell, so
catching only ImportError turned a working install into a 500. The reason is
recorded either way, because "unavailable" and "not installed" are not the same
thing and the difference is otherwise invisible.

scikit-learn is already a dependency, and on a personal library (tens of
papers, not tens of thousands) the two engines agree closely: UMAP's
dimensionality reduction earns its keep at a scale this data never reaches, and
HDBSCAN needs more points than a reading list has to estimate density at all —
on a small corpus it labels nearly everything an outlier and the graph comes
out empty. Agglomerative clustering directly on the 384-dim vectors has neither
problem.
"""

import math
import structlog
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = structlog.get_logger(__name__)

try:
    from bertopic import BERTopic
    from umap import UMAP
    from hdbscan import HDBSCAN
    BERTOPIC_AVAILABLE = True
    BERTOPIC_UNAVAILABLE_REASON = None
except Exception as _bertopic_error:  # noqa: BLE001 — see module docstring
    BERTOPIC_AVAILABLE = False
    BERTOPIC_UNAVAILABLE_REASON = f"{type(_bertopic_error).__name__}: {_bertopic_error}"
    logger.info(
        "bertopic_unavailable_using_sklearn",
        reason=BERTOPIC_UNAVAILABLE_REASON,
        detail="Topic clustering falls back to scikit-learn; the view still works.",
    )

# Enough papers to make "these group together" a claim worth drawing at all.
MIN_PAPERS = 3

# Cosine distance below which two papers are considered the same topic. Picked
# against all-MiniLM-L6-v2 title+abstract vectors, where unrelated papers in
# the same broad field still sit around 0.6–0.7 apart.
_MERGE_DISTANCE = 0.55


def _keywords_per_cluster(
    docs: Sequence[str],
    topics: Sequence[int],
    top_n: int = 5,
) -> Dict[int, List[str]]:
    """Label each cluster with the terms that distinguish it from the others.

    This is BERTopic's c-TF-IDF idea: treat each cluster as one concatenated
    document, so a term scores highly when it is frequent inside its cluster
    and rare across the rest — which is what makes a label a label rather than
    a list of the corpus's most common words.
    """
    from sklearn.feature_extraction.text import TfidfVectorizer

    grouped: Dict[int, List[str]] = {}
    for doc, topic in zip(docs, topics):
        if topic == -1:
            continue
        grouped.setdefault(int(topic), []).append(doc)

    if not grouped:
        return {}

    cluster_ids = sorted(grouped)
    joined = [" ".join(grouped[c]) for c in cluster_ids]

    try:
        vectorizer = TfidfVectorizer(
            stop_words="english",
            # Bigrams catch the phrases that actually name a field — "image
            # enhancement", "language model" — where either word alone is noise.
            ngram_range=(1, 2),
            max_features=5000,
            # Papers are written to sound alike; a term in every cluster
            # describes the library, not any one group inside it.
            max_df=0.9 if len(cluster_ids) > 2 else 1.0,
        )
        matrix = vectorizer.fit_transform(joined)
        terms = vectorizer.get_feature_names_out()
    except ValueError as e:
        # Empty vocabulary — every document was stop words or blank.
        logger.warning("cluster_keyword_extraction_failed", error=str(e))
        return {c: [] for c in cluster_ids}

    keywords: Dict[int, List[str]] = {}
    for row, cluster_id in enumerate(cluster_ids):
        scores = matrix[row].toarray()[0]
        ranked = scores.argsort()[::-1][: top_n * 3]
        picked: List[str] = []
        for idx in ranked:
            if scores[idx] <= 0:
                continue
            term = terms[idx]
            # "image" right after "image enhancement" adds nothing to a label.
            if any(term in kept or kept in term for kept in picked):
                continue
            picked.append(term)
            if len(picked) == top_n:
                break
        keywords[cluster_id] = picked
    return keywords


def _fit_bertopic(docs: Sequence[str], embeddings: Any) -> Tuple[List[int], Dict[int, List[str]]]:
    """Cluster with BERTopic. Only reachable when the extras are installed."""
    umap_model = UMAP(
        n_neighbors=min(15, len(docs) - 1), n_components=5,
        metric="cosine", random_state=42,
    )
    hdbscan_model = HDBSCAN(
        min_cluster_size=max(2, len(docs) // 15),
        metric="euclidean", prediction_data=True,
    )
    topic_model = BERTopic(
        umap_model=umap_model,
        hdbscan_model=hdbscan_model,
        embedding_model=None,  # pass pre-computed embeddings
        verbose=False,
    )
    topics, _ = topic_model.fit_transform(list(docs), embeddings)
    topics = [int(t) for t in topics]

    keywords = {}
    for topic_id in set(topics):
        if topic_id == -1:
            continue
        info = topic_model.get_topic(topic_id)
        keywords[topic_id] = [w for w, _ in info[:5]] if info else []
    return topics, keywords


def _fit_sklearn(docs: Sequence[str], embeddings: Any) -> Tuple[List[int], Dict[int, List[str]]]:
    """Cluster with agglomerative clustering over the raw embeddings.

    Every paper is assigned — there is no outlier label. On a corpus this size
    dropping "noise" points is how the old path produced an empty graph from a
    perfectly good library, and a reader looking at their own reading list is
    better served by a loose grouping than by a blank panel.
    """
    import numpy as np
    from sklearn.cluster import AgglomerativeClustering

    n = len(docs)

    # Cut the dendrogram by distance rather than by a guessed cluster count:
    # how many topics a library holds is exactly what is being asked, so it
    # should not be an input.
    model = AgglomerativeClustering(
        n_clusters=None,
        distance_threshold=_MERGE_DISTANCE,
        metric="cosine",
        linkage="average",
    )
    labels = [int(x) for x in model.fit_predict(np.asarray(embeddings, dtype=np.float64))]

    # A threshold that splits everything into singletons has described nothing.
    # Fall back to a fixed count — roughly four papers a topic — so the view
    # still says something about a library of near-identical papers.
    if len(set(labels)) == n and n >= 4:
        k = max(2, min(10, round(math.sqrt(n))))
        model = AgglomerativeClustering(n_clusters=k, metric="cosine", linkage="average")
        labels = [int(x) for x in model.fit_predict(np.asarray(embeddings, dtype=np.float64))]

    return labels, _keywords_per_cluster(docs, labels)


def compute_topic_clusters(user_id: str, supabase_client: Any) -> Dict[str, Any]:
    """
    Fetch all embeddings for a user's papers, cluster them, and write the
    assignments to paper_topic_clusters. Returns a summary dict.
    """
    # Fetch papers + embeddings
    resp = (
        supabase_client.table("summaries")
        .select("id, paper_title, abstract_text, embedding")
        .eq("user_id", user_id)
        .limit(500)
        .execute()
    )
    papers = [p for p in (resp.data or []) if p.get("embedding")]

    if len(papers) < MIN_PAPERS:
        return {
            "error": f"Need at least {MIN_PAPERS} papers with embeddings, found {len(papers)}",
            "clusters": [],
        }

    import numpy as np

    from .graph_service import _as_vector

    # Same pgvector-returns-text quirk as the similarity cache: the column comes
    # back as "[0.1,-0.2,…]", which numpy cannot read as floats.
    embeddings = np.stack([_as_vector(p["embedding"]) for p in papers])
    docs = [
        f"{p.get('paper_title', '')} {(p.get('abstract_text') or '')[:200]}"
        for p in papers
    ]

    engine = "sklearn"
    topics: List[int] = []
    keywords: Dict[int, List[str]] = {}

    # A BERTopic failure demotes to the fallback rather than failing the
    # request. Its own fit can raise on a small corpus for the same reason its
    # import can — the heavy numerical stack underneath it — and there is no
    # reason to lose the view over an engine the user never chose.
    if BERTOPIC_AVAILABLE:
        try:
            topics, keywords = _fit_bertopic(docs, embeddings)
            engine = "bertopic"
        except Exception as e:
            logger.warning("bertopic_fit_failed_using_sklearn", error=str(e))

    if engine == "sklearn":
        try:
            topics, keywords = _fit_sklearn(docs, embeddings)
        except Exception as e:
            logger.error("topic_clustering_fit_failed", engine=engine, error=str(e))
            return {"error": str(e), "clusters": []}

    # Persist to DB
    rows = []
    for paper, topic_id in zip(papers, topics):
        if topic_id == -1:
            continue  # outlier / noise
        words = keywords.get(int(topic_id), [])
        label = ", ".join(words[:3]) if words else "Unlabelled"
        rows.append({
            "summary_id": paper["id"],
            "user_id": user_id,
            "cluster_id": int(topic_id),
            "cluster_label": f"Topic {topic_id}: {label}",
            "cluster_keywords": words,
            "probability": 0.8,
        })

    # A recompute has to replace the previous assignments, not add to them:
    # cluster ids are positional, so yesterday's "Topic 3" and today's are
    # unrelated, and upserting alone left papers attached to clusters that the
    # new run never produced.
    try:
        supabase_client.table("paper_topic_clusters") \
            .delete().eq("user_id", user_id).execute()
    except Exception as e:
        logger.warning("topic_cluster_clear_failed", error=str(e))

    if rows:
        try:
            supabase_client.table("paper_topic_clusters") \
                .upsert(rows, on_conflict="summary_id,cluster_id") \
                .execute()
        except Exception as e:
            logger.warning("topic_cluster_persist_failed", error=str(e))
            return {"error": f"Could not save clusters: {e}", "clusters": []}

    num_topics = len(set(topics)) - (1 if -1 in topics else 0)
    return {
        "engine": engine,
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
