"""
Authentication routes for user signup, login, and profile management
"""
from flask import Blueprint, request, jsonify
from supabase import create_client
from database.config import SUPABASE_URL, SUPABASE_KEY, SUPABASE_SERVICE_KEY
from auth.utils import (
    hash_password, 
    verify_password, 
    create_access_token,
    token_required,
    validate_email,
    validate_password_strength
)
from datetime import datetime

auth_bp = Blueprint('auth', __name__)
supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

@auth_bp.route('/signup', methods=['POST'])
def signup():
    """Register a new user"""
    try:
        data = request.get_json()
        
        email = data.get('email', '').strip().lower()
        password = data.get('password', '')
        full_name = data.get('full_name', '').strip()
        
        # Validation
        if not email or not password:
            return jsonify({'error': 'Email and password are required'}), 400
        
        if not validate_email(email):
            return jsonify({'error': 'Invalid email format'}), 400
        
        is_valid, error_msg = validate_password_strength(password)
        if not is_valid:
            return jsonify({'error': error_msg}), 400
        
        # Check if user exists
        try:
            existing_user = supabase.table('users').select('id').eq('email', email).execute()
        except Exception as check_error:
            print(f"⚠️ Error checking existing user: {check_error}")
            # User might not exist, continue anyway
            existing_user = type('obj', (object,), {'data': []})()
        
        if existing_user.data:
            return jsonify({'error': 'Email already registered'}), 409
        
        # Hash password and create user
        password_hash = hash_password(password)
        
        user_data = {
            'email': email,
            'password_hash': password_hash,
            'full_name': full_name,
            'created_at': datetime.utcnow().isoformat(),
            'is_active': True
        }
        
        result = supabase.table('users').insert(user_data).execute()
        
        if not result.data:
            return jsonify({'error': 'Failed to create user'}), 500
        
        user = result.data[0]
        
        # Create access token
        token = create_access_token(user['id'], user['email'])
        
        return jsonify({
            'message': 'User created successfully',
            'token': token,
            'user': {
                'id': user['id'],
                'email': user['email'],
                'full_name': user.get('full_name'),
                'created_at': user['created_at']
            }
        }), 201
        
    except Exception as e:
        print(f"❌ Signup error: {type(e).__name__}: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': f'Signup failed: {str(e)}'}), 500

@auth_bp.route('/login', methods=['POST'])
def login():
    """Authenticate a user and return access token"""
    try:
        data = request.get_json()
        email = data.get('email', '').strip().lower()
        password = data.get('password', '')
        
        if not email or not password:
            return jsonify({'error': 'Email and password are required'}), 400
        
        # Get user from database
        result = supabase.table('users').select('*').eq('email', email).execute()
        
        if not result.data:
            return jsonify({'error': 'Invalid email or password'}), 401
        
        user = result.data[0]
        
        # Check if account is active
        if not user.get('is_active', True):
            return jsonify({'error': 'Account is deactivated'}), 403
        
        # Verify password
        if not verify_password(password, user['password_hash']):
            return jsonify({'error': 'Invalid email or password'}), 401
        
        # Update last login
        supabase.table('users').update({
            'last_login': datetime.utcnow().isoformat()
        }).eq('id', user['id']).execute()
        
        # Create access token
        token = create_access_token(user['id'], user['email'])
        
        return jsonify({
            'message': 'Login successful',
            'token': token,
            'user': {
                'id': user['id'],
                'email': user['email'],
                'full_name': user.get('full_name'),
                'bio': user.get('bio'),
                'avatar_url': user.get('avatar_url'),
                'created_at': user['created_at']
            }
        }), 200
        
    except Exception as e:
        return jsonify({'error': f'Login failed: {str(e)}'}), 500

@auth_bp.route('/me', methods=['GET'])
@token_required
def get_current_user():
    """Get current authenticated user's profile"""
    try:
        result = supabase.table('users').select('id, email, full_name, bio, avatar_url, created_at, last_login').eq('id', request.user_id).execute()
        
        if not result.data:
            return jsonify({'error': 'User not found'}), 404
        
        user = result.data[0]
        
        # Get user statistics
        stats_result = supabase.table('user_summary_stats').select('*').eq('user_id', request.user_id).execute()
        stats = stats_result.data[0] if stats_result.data else {}
        
        return jsonify({
            'user': user,
            'stats': {
                'total_summaries': stats.get('total_summaries', 0),
                'avg_processing_time': float(stats.get('avg_processing_time', 0)) if stats.get('avg_processing_time') else 0,
                'total_words_processed': stats.get('total_words_processed', 0),
                'last_summary_date': stats.get('last_summary_date'),
                'active_days': stats.get('active_days', 0)
            }
        }), 200
        
    except Exception as e:
        return jsonify({'error': f'Failed to fetch user: {str(e)}'}), 500

@auth_bp.route('/me', methods=['PUT'])
@token_required
def update_profile():
    """Update current user's profile"""
    try:
        data = request.get_json()
        
        # Only allow updating certain fields
        allowed_fields = ['full_name', 'bio', 'avatar_url']
        update_data = {k: v for k, v in data.items() if k in allowed_fields}
        
        if not update_data:
            return jsonify({'error': 'No valid fields to update'}), 400
        
        update_data['updated_at'] = datetime.utcnow().isoformat()
        
        result = supabase.table('users').update(update_data).eq('id', request.user_id).execute()
        
        if not result.data:
            return jsonify({'error': 'Failed to update profile'}), 500
        
        return jsonify({
            'message': 'Profile updated successfully',
            'user': result.data[0]
        }), 200
        
    except Exception as e:
        return jsonify({'error': f'Update failed: {str(e)}'}), 500

@auth_bp.route('/change-password', methods=['POST'])
@token_required
def change_password():
    """Change user's password"""
    try:
        data = request.get_json()
        current_password = data.get('current_password', '')
        new_password = data.get('new_password', '')
        
        if not current_password or not new_password:
            return jsonify({'error': 'Current and new passwords are required'}), 400
        
        # Validate new password strength
        is_valid, error_msg = validate_password_strength(new_password)
        if not is_valid:
            return jsonify({'error': error_msg}), 400
        
        # Get current user
        result = supabase.table('users').select('password_hash').eq('id', request.user_id).execute()
        
        if not result.data:
            return jsonify({'error': 'User not found'}), 404
        
        user = result.data[0]
        
        # Verify current password
        if not verify_password(current_password, user['password_hash']):
            return jsonify({'error': 'Current password is incorrect'}), 401
        
        # Hash new password and update
        new_password_hash = hash_password(new_password)
        
        supabase.table('users').update({
            'password_hash': new_password_hash,
            'updated_at': datetime.utcnow().isoformat()
        }).eq('id', request.user_id).execute()
        
        return jsonify({'message': 'Password changed successfully'}), 200
        
    except Exception as e:
        return jsonify({'error': f'Password change failed: {str(e)}'}), 500
