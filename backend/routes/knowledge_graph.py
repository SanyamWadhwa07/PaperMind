"""Knowledge graph routes — semantic search, recommendations, timeline, ancestry."""

from flask import Blueprint, request, jsonify
from supabase import create_client
from database.config import SUPABASE_URL, SUPABASE_SERVICE_KEY
from auth.utils import token_required
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from core.knowledge.graph_service import get_knowledge_graph, get_paper_recommendations
from core.knowledge.lineage_service import get_ancestry_tree, build_timeline_graph
from core.knowledge.embedding_service import embed_text, find_similar_papers

knowledge_graph_bp = Blueprint('knowledge_graph', __name__)
supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


@knowledge_graph_bp.route('/graph/paper/<summary_id>', methods=['GET'])
@token_required
def paper_knowledge_graph(summary_id):
    """Return knowledge graph nodes + edges centred on a paper."""
    graph = get_knowledge_graph(
        user_id=request.user_id,
        supabase_client=supabase,
        anchor_summary_id=summary_id,
    )
    return jsonify(graph), 200


@knowledge_graph_bp.route('/graph/recommendations/<summary_id>', methods=['GET'])
@token_required
def paper_recommendations(summary_id):
    """Return top-5 similar papers for a given summary."""
    top_k = min(int(request.args.get('k', 5)), 20)
    recs = get_paper_recommendations(summary_id, supabase, top_k=top_k)
    return jsonify({'recommendations': recs}), 200


@knowledge_graph_bp.route('/graph/search', methods=['POST'])
@token_required
def semantic_search():
    """Semantic vector search across the user's paper library.

    Body: {"query": "attention mechanism transformers", "top_k": 10}
    """
    data = request.get_json() or {}
    query = str(data.get('query', ''))[:500]
    top_k = min(int(data.get('top_k', 10)), 50)

    if not query:
        return jsonify({'error': 'query is required'}), 400

    try:
        embedding = embed_text(query)
        results = find_similar_papers(
            embedding=embedding,
            user_id=request.user_id,
            supabase_client=supabase,
            top_k=top_k,
        )
        return jsonify({'results': results, 'query': query}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@knowledge_graph_bp.route('/graph/timeline', methods=['GET'])
@token_required
def research_timeline():
    """Return all user papers with publication dates and lineage edges."""
    data = build_timeline_graph(request.user_id, supabase)
    return jsonify(data), 200


@knowledge_graph_bp.route('/graph/ancestry/<summary_id>', methods=['GET'])
@token_required
def paper_ancestry(summary_id):
    """Return the ancestry/descendant tree for a paper (up to depth 3)."""
    depth = min(int(request.args.get('depth', 3)), 5)
    tree = get_ancestry_tree(summary_id, supabase, depth=depth)
    return jsonify(tree), 200
