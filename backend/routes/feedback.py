"""User feedback routes — star ratings and error reports for summaries."""

from flask import Blueprint, request, jsonify
from supabase import create_client
from database.config import SUPABASE_URL, SUPABASE_SERVICE_KEY
from auth.utils import token_required
from datetime import datetime

feedback_bp = Blueprint('feedback', __name__)
supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

VALID_TYPES = {'rating', 'error_report', 'flag_hallucination'}


@feedback_bp.route('/feedback/summary/<summary_id>', methods=['POST'])
@token_required
def submit_feedback(summary_id):
    """Submit a star rating + optional comment for a summary.

    Body: {"rating": 4, "comment": "Great summary", "feedback_type": "rating"}
    """
    data = request.get_json() or {}
    rating = data.get('rating')
    comment = str(data.get('comment', ''))[:1000]
    feedback_type = data.get('feedback_type', 'rating')

    if rating is not None and (not isinstance(rating, int) or not 1 <= rating <= 5):
        return jsonify({'error': 'rating must be an integer between 1 and 5'}), 400

    if feedback_type not in VALID_TYPES:
        feedback_type = 'rating'

    try:
        row = {
            'summary_id': summary_id,
            'user_id': request.user_id,
            'rating': rating,
            'feedback_type': feedback_type,
            'comment': comment or None,
            'created_at': datetime.utcnow().isoformat(),
        }
        supabase.table('summary_feedback') \
            .upsert(row, on_conflict='summary_id,user_id') \
            .execute()
        return jsonify({'message': 'Feedback saved'}), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@feedback_bp.route('/feedback/summary/<summary_id>', methods=['GET'])
@token_required
def get_feedback(summary_id):
    """Get aggregate rating and feedback count for a summary."""
    try:
        result = supabase.table('summary_feedback') \
            .select('rating, feedback_type, comment, created_at') \
            .eq('summary_id', summary_id) \
            .execute()

        rows = result.data or []
        ratings = [r['rating'] for r in rows if r.get('rating') is not None]
        avg_rating = round(sum(ratings) / len(ratings), 2) if ratings else None

        return jsonify({
            'summary_id': summary_id,
            'average_rating': avg_rating,
            'rating_count': len(ratings),
            'total_feedback': len(rows),
            'feedback': rows,
        }), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500
