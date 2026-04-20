"""Collections routes — user-defined paper folders."""

from flask import Blueprint, request, jsonify
from supabase import create_client
from database.config import SUPABASE_URL, SUPABASE_SERVICE_KEY
from auth.utils import token_required
from datetime import datetime
import re

collections_bp = Blueprint('collections', __name__)
supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

_HEX_COLOR = re.compile(r'^#[0-9a-fA-F]{6}$')


@collections_bp.route('/collections', methods=['GET'])
@token_required
def list_collections():
    result = supabase.table('collections').select('*').eq('user_id', request.user_id).execute()
    return jsonify({'collections': result.data or []}), 200


@collections_bp.route('/collections', methods=['POST'])
@token_required
def create_collection():
    data = request.get_json() or {}
    name = str(data.get('name', '')).strip()[:255]
    if not name:
        return jsonify({'error': 'name is required'}), 400

    color = data.get('color', '#6366f1')
    if not _HEX_COLOR.match(str(color)):
        color = '#6366f1'

    row = {
        'user_id': request.user_id,
        'name': name,
        'description': str(data.get('description', ''))[:500] or None,
        'color': color,
        'created_at': datetime.utcnow().isoformat(),
        'updated_at': datetime.utcnow().isoformat(),
    }
    result = supabase.table('collections').insert(row).execute()
    return jsonify({'collection': result.data[0] if result.data else {}}), 201


@collections_bp.route('/collections/<collection_id>', methods=['DELETE'])
@token_required
def delete_collection(collection_id):
    supabase.table('collections') \
        .delete() \
        .eq('id', collection_id) \
        .eq('user_id', request.user_id) \
        .execute()
    return jsonify({'message': 'Deleted'}), 200


@collections_bp.route('/collections/<collection_id>/papers', methods=['POST'])
@token_required
def add_paper_to_collection(collection_id):
    data = request.get_json() or {}
    summary_id = data.get('summary_id')
    if not summary_id:
        return jsonify({'error': 'summary_id is required'}), 400

    # Verify collection belongs to user
    col = supabase.table('collections') \
        .select('id') \
        .eq('id', collection_id) \
        .eq('user_id', request.user_id) \
        .execute()
    if not col.data:
        return jsonify({'error': 'Collection not found'}), 404

    supabase.table('collection_papers') \
        .upsert({'collection_id': collection_id, 'summary_id': summary_id,
                 'added_at': datetime.utcnow().isoformat()}) \
        .execute()
    return jsonify({'message': 'Paper added to collection'}), 201


@collections_bp.route('/collections/<collection_id>/papers/<summary_id>', methods=['DELETE'])
@token_required
def remove_paper_from_collection(collection_id, summary_id):
    # Verify ownership
    col = supabase.table('collections') \
        .select('id') \
        .eq('id', collection_id) \
        .eq('user_id', request.user_id) \
        .execute()
    if not col.data:
        return jsonify({'error': 'Collection not found'}), 404

    supabase.table('collection_papers') \
        .delete() \
        .eq('collection_id', collection_id) \
        .eq('summary_id', summary_id) \
        .execute()
    return jsonify({'message': 'Removed'}), 200


@collections_bp.route('/collections/<collection_id>/papers', methods=['GET'])
@token_required
def get_collection_papers(collection_id):
    # Verify ownership
    col = supabase.table('collections') \
        .select('id, name') \
        .eq('id', collection_id) \
        .eq('user_id', request.user_id) \
        .execute()
    if not col.data:
        return jsonify({'error': 'Collection not found'}), 404

    result = supabase.table('collection_papers') \
        .select('summary_id, added_at, summaries(paper_title, arxiv_id, created_at)') \
        .eq('collection_id', collection_id) \
        .execute()
    return jsonify({
        'collection': col.data[0],
        'papers': result.data or [],
    }), 200
