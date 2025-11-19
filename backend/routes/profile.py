"""
Profile and avatar management routes
"""
from flask import Blueprint, request, jsonify
from werkzeug.utils import secure_filename
from supabase import create_client
from database.config import SUPABASE_URL, SUPABASE_SERVICE_KEY
from auth.utils import token_required
from datetime import datetime
from pathlib import Path
import uuid

profile_bp = Blueprint('profile', __name__)
supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@profile_bp.route('/profile', methods=['GET'])
@token_required
def get_profile():
    """Get user profile"""
    try:
        result = supabase.table('users').select('*').eq('id', request.user_id).execute()
        
        if not result.data:
            return jsonify({'error': 'Profile not found'}), 404
        
        return jsonify({'profile': result.data[0]}), 200
        
    except Exception as e:
        return jsonify({'error': f'Failed to fetch profile: {str(e)}'}), 500

@profile_bp.route('/profile', methods=['PUT'])
@token_required
def update_profile():
    """Update user profile"""
    try:
        data = request.get_json()
        
        update_data = {}
        if 'full_name' in data:
            update_data['full_name'] = data['full_name'].strip()
        if 'bio' in data:
            update_data['bio'] = data['bio'].strip()
        
        if not update_data:
            return jsonify({'error': 'No data to update'}), 400
        
        update_data['updated_at'] = datetime.utcnow().isoformat()
        
        result = supabase.table('users').update(update_data).eq('id', request.user_id).execute()
        
        if not result.data:
            return jsonify({'error': 'Failed to update profile'}), 500
        
        return jsonify({
            'message': 'Profile updated successfully',
            'profile': result.data[0]
        }), 200
        
    except Exception as e:
        return jsonify({'error': f'Failed to update profile: {str(e)}'}), 500

@profile_bp.route('/profile/avatar', methods=['POST'])
@token_required
def upload_avatar():
    """Upload user avatar to Supabase Storage"""
    try:
        if 'avatar' not in request.files:
            return jsonify({'error': 'No file provided'}), 400
        
        file = request.files['avatar']
        
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        if not allowed_file(file.filename):
            return jsonify({'error': 'Invalid file type. Allowed: PNG, JPG, JPEG, GIF, WEBP'}), 400
        
        # Read file content
        file_content = file.read()
        
        if len(file_content) > MAX_FILE_SIZE:
            return jsonify({'error': 'File too large. Maximum size is 5MB'}), 400
        
        # Generate unique filename
        ext = file.filename.rsplit('.', 1)[1].lower()
        filename = f"{request.user_id}/{uuid.uuid4()}.{ext}"
        
        # Upload to Supabase Storage
        # Note: You need to create an 'avatars' bucket in Supabase Storage first
        try:
            storage_response = supabase.storage.from_('avatars').upload(
                filename,
                file_content,
                {
                    'content-type': file.content_type,
                    'upsert': 'true'
                }
            )
            
            # Get public URL
            public_url = supabase.storage.from_('avatars').get_public_url(filename)
            
            # Update user profile with avatar URL
            supabase.table('users').update({
                'avatar_url': public_url,
                'updated_at': datetime.utcnow().isoformat()
            }).eq('id', request.user_id).execute()
            
            return jsonify({
                'message': 'Avatar uploaded successfully',
                'avatar_url': public_url
            }), 200
            
        except Exception as storage_error:
            return jsonify({'error': f'Storage upload failed: {str(storage_error)}'}), 500
        
    except Exception as e:
        return jsonify({'error': f'Failed to upload avatar: {str(e)}'}), 500

@profile_bp.route('/profile/avatar', methods=['DELETE'])
@token_required
def delete_avatar():
    """Delete user avatar"""
    try:
        # Get current avatar URL
        user = supabase.table('users').select('avatar_url').eq('id', request.user_id).execute()
        
        if not user.data or not user.data[0].get('avatar_url'):
            return jsonify({'error': 'No avatar to delete'}), 404
        
        avatar_url = user.data[0]['avatar_url']
        
        # Extract filename from URL
        # URL format: https://{project}.supabase.co/storage/v1/object/public/avatars/{filename}
        if '/avatars/' in avatar_url:
            filename = avatar_url.split('/avatars/')[1]
            
            # Delete from storage
            try:
                supabase.storage.from_('avatars').remove([filename])
            except:
                pass  # Continue even if storage deletion fails
        
        # Update user profile
        supabase.table('users').update({
            'avatar_url': None,
            'updated_at': datetime.utcnow().isoformat()
        }).eq('id', request.user_id).execute()
        
        return jsonify({'message': 'Avatar deleted successfully'}), 200
        
    except Exception as e:
        return jsonify({'error': f'Failed to delete avatar: {str(e)}'}), 500
