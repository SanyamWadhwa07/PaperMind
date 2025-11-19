"""
User-specific summary routes with authentication
"""
from flask import Blueprint, request, jsonify
from supabase import create_client
from database.config import SUPABASE_URL, SUPABASE_SERVICE_KEY
from auth.utils import token_required
from datetime import datetime

summaries_bp = Blueprint('summaries', __name__)
supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

@summaries_bp.route('/summaries', methods=['GET'])
@token_required
def get_user_summaries():
    """Get all summaries for the authenticated user"""
    try:
        # Query parameters for filtering and pagination
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 10))
        sort_by = request.args.get('sort_by', 'created_at')
        order = request.args.get('order', 'desc')
        search = request.args.get('search', '')
        
        # Calculate offset
        offset = (page - 1) * per_page
        
        # Build query
        query = supabase.table('summaries').select('*', count='exact').eq('user_id', request.user_id)
        
        # Add search if provided
        if search:
            query = query.or_(f'paper_title.ilike.%{search}%,arxiv_id.ilike.%{search}%')
        
        # Add sorting
        query = query.order(sort_by, desc=(order == 'desc'))
        
        # Add pagination
        query = query.range(offset, offset + per_page - 1)
        
        result = query.execute()
        
        return jsonify({
            'summaries': result.data,
            'total': result.count,
            'page': page,
            'per_page': per_page,
            'total_pages': (result.count + per_page - 1) // per_page
        }), 200
        
    except Exception as e:
        return jsonify({'error': f'Failed to fetch summaries: {str(e)}'}), 500

@summaries_bp.route('/summaries/<summary_id>', methods=['GET'])
@token_required
def get_summary(summary_id):
    """Get a specific summary by ID"""
    try:
        result = supabase.table('summaries').select('*').eq('id', summary_id).eq('user_id', request.user_id).execute()
        
        if not result.data:
            return jsonify({'error': 'Summary not found'}), 404
        
        return jsonify({'summary': result.data[0]}), 200
        
    except Exception as e:
        return jsonify({'error': f'Failed to fetch summary: {str(e)}'}), 500

@summaries_bp.route('/summaries', methods=['POST'])
@token_required
def create_summary():
    """Save a new summary for the authenticated user"""
    try:
        data = request.get_json()
        
        summary_data = {
            'user_id': request.user_id,
            'paper_title': data.get('paper_title', ''),
            'paper_authors': data.get('paper_authors', []),
            'paper_url': data.get('paper_url'),
            'arxiv_id': data.get('arxiv_id'),
            'summary_data': data.get('summary_data', {}),
            'model_used': data.get('model_used', 'LED'),
            'processing_time_seconds': data.get('processing_time_seconds'),
            'word_count': data.get('word_count'),
            'created_at': datetime.utcnow().isoformat()
        }
        
        result = supabase.table('summaries').insert(summary_data).execute()
        
        if not result.data:
            return jsonify({'error': 'Failed to save summary'}), 500
        
        # Log activity
        supabase.table('user_activity').insert({
            'user_id': request.user_id,
            'activity_type': 'summarize',
            'activity_data': {'summary_id': result.data[0]['id'], 'paper_title': summary_data['paper_title']},
            'created_at': datetime.utcnow().isoformat()
        }).execute()
        
        return jsonify({
            'message': 'Summary saved successfully',
            'summary': result.data[0]
        }), 201
        
    except Exception as e:
        return jsonify({'error': f'Failed to save summary: {str(e)}'}), 500

@summaries_bp.route('/summaries/<summary_id>', methods=['DELETE'])
@token_required
def delete_summary(summary_id):
    """Delete a summary"""
    try:
        # Verify ownership
        check_result = supabase.table('summaries').select('id').eq('id', summary_id).eq('user_id', request.user_id).execute()
        
        if not check_result.data:
            return jsonify({'error': 'Summary not found or unauthorized'}), 404
        
        supabase.table('summaries').delete().eq('id', summary_id).execute()
        
        return jsonify({'message': 'Summary deleted successfully'}), 200
        
    except Exception as e:
        return jsonify({'error': f'Failed to delete summary: {str(e)}'}), 500

@summaries_bp.route('/dashboard/stats', methods=['GET'])
@token_required
def get_dashboard_stats():
    """Get dashboard statistics for the authenticated user"""
    try:
        # Get user stats from view
        stats_result = supabase.table('user_summary_stats').select('*').eq('user_id', request.user_id).execute()
        
        # Get recent activity
        activity_result = supabase.table('user_activity').select('*').eq('user_id', request.user_id).order('created_at', desc=True).limit(10).execute()
        
        # Get summaries by month (last 6 months)
        from datetime import datetime, timedelta
        six_months_ago = (datetime.utcnow() - timedelta(days=180)).isoformat()
        
        monthly_result = supabase.table('summaries').select('created_at').eq('user_id', request.user_id).gte('created_at', six_months_ago).execute()
        
        # Process monthly data
        monthly_counts = {}
        for summary in monthly_result.data:
            month_key = summary['created_at'][:7]  # YYYY-MM
            monthly_counts[month_key] = monthly_counts.get(month_key, 0) + 1
        
        stats = stats_result.data[0] if stats_result.data else {}
        
        return jsonify({
            'stats': {
                'total_summaries': stats.get('total_summaries', 0),
                'avg_processing_time': float(stats.get('avg_processing_time', 0)) if stats.get('avg_processing_time') else 0,
                'total_words_processed': stats.get('total_words_processed', 0),
                'last_summary_date': stats.get('last_summary_date'),
                'active_days': stats.get('active_days', 0)
            },
            'recent_activity': activity_result.data,
            'monthly_summaries': monthly_counts
        }), 200
        
    except Exception as e:
        return jsonify({'error': f'Failed to fetch stats: {str(e)}'}), 500
