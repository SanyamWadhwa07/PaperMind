"""Batch comparison routes — cross-paper metrics/entity comparison."""

from flask import Blueprint, request, jsonify
from supabase import create_client
from database.config import SUPABASE_URL, SUPABASE_SERVICE_KEY
from auth.utils import token_required
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from core.knowledge.comparison_service import compare_papers

batch_compare_bp = Blueprint('batch_compare', __name__)
supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


@batch_compare_bp.route('/batch/compare', methods=['POST'])
@token_required
def compare_papers_endpoint():
    """Compare metrics, entities, and findings across multiple papers.

    Body: {"summary_ids": ["uuid1", "uuid2", ...]}  (2–10 IDs)
    """
    data = request.get_json() or {}
    summary_ids = data.get('summary_ids', [])

    if not isinstance(summary_ids, list) or len(summary_ids) < 2:
        return jsonify({'error': 'Provide at least 2 summary IDs'}), 400

    if len(summary_ids) > 10:
        return jsonify({'error': 'Maximum 10 papers per comparison'}), 400

    # Verify all papers belong to the requesting user
    result = supabase.table('summaries') \
        .select('id') \
        .in_('id', summary_ids) \
        .eq('user_id', request.user_id) \
        .execute()

    owned_ids = {r['id'] for r in (result.data or [])}
    unauthorized = [pid for pid in summary_ids if pid not in owned_ids]
    if unauthorized:
        return jsonify({'error': 'Some paper IDs not found or not owned by you'}), 403

    try:
        comparison = compare_papers(summary_ids, supabase)
        return jsonify(comparison), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500
