"""
Supabase Auth integration - uses Supabase's built-in authentication
instead of custom JWT tokens
"""
from flask import Blueprint, request, jsonify
from supabase import create_client
from database.config import SUPABASE_URL, SUPABASE_SERVICE_KEY
from datetime import datetime

supabase_auth_bp = Blueprint('supabase_auth', __name__)
supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

@supabase_auth_bp.route('/signup', methods=['POST'])
def signup_with_email():
    """Sign up with email verification"""
    try:
        data = request.get_json()
        email = data.get('email', '').strip().lower()
        password = data.get('password', '')
        full_name = data.get('full_name', '').strip()
        
        if not email or not password:
            return jsonify({'error': 'Email and password are required'}), 400
        
        # Sign up user with Supabase Auth
        auth_response = supabase.auth.sign_up({
            'email': email,
            'password': password,
            'options': {
                'data': {
                    'full_name': full_name
                },
                'email_redirect_to': 'http://localhost:5173/auth/callback'
            }
        })
        
        if auth_response.user:
            # Create profile in users table
            supabase.table('users').insert({
                'id': auth_response.user.id,
                'email': email,
                'full_name': full_name,
                'created_at': datetime.utcnow().isoformat(),
                'is_active': True
            }).execute()
            
            return jsonify({
                'message': 'Signup successful! Please check your email to verify your account.',
                'user': {
                    'id': auth_response.user.id,
                    'email': auth_response.user.email,
                    'email_confirmed': auth_response.user.email_confirmed_at is not None
                },
                'session': {
                    'access_token': auth_response.session.access_token if auth_response.session else None,
                    'refresh_token': auth_response.session.refresh_token if auth_response.session else None
                }
            }), 201
        else:
            return jsonify({'error': 'Signup failed'}), 400
            
    except Exception as e:
        return jsonify({'error': f'Signup failed: {str(e)}'}), 500

@supabase_auth_bp.route('/login', methods=['POST'])
def login_with_email():
    """Login with email and password"""
    try:
        data = request.get_json()
        email = data.get('email', '').strip().lower()
        password = data.get('password', '')
        
        if not email or not password:
            return jsonify({'error': 'Email and password are required'}), 400
        
        # Sign in with Supabase Auth
        auth_response = supabase.auth.sign_in_with_password({
            'email': email,
            'password': password
        })
        
        if auth_response.user and auth_response.session:
            # Update last login
            supabase.table('users').update({
                'last_login': datetime.utcnow().isoformat()
            }).eq('id', auth_response.user.id).execute()
            
            return jsonify({
                'message': 'Login successful',
                'user': {
                    'id': auth_response.user.id,
                    'email': auth_response.user.email,
                    'email_confirmed': auth_response.user.email_confirmed_at is not None,
                    'user_metadata': auth_response.user.user_metadata
                },
                'session': {
                    'access_token': auth_response.session.access_token,
                    'refresh_token': auth_response.session.refresh_token,
                    'expires_at': auth_response.session.expires_at
                }
            }), 200
        else:
            return jsonify({'error': 'Invalid credentials'}), 401
            
    except Exception as e:
        return jsonify({'error': f'Login failed: {str(e)}'}), 500

@supabase_auth_bp.route('/verify-email', methods=['POST'])
def verify_email():
    """Verify email with token"""
    try:
        data = request.get_json()
        token_hash = data.get('token_hash')
        type = data.get('type', 'email')
        
        if not token_hash:
            return jsonify({'error': 'Token required'}), 400
        
        # Verify email with Supabase
        auth_response = supabase.auth.verify_otp({
            'token_hash': token_hash,
            'type': type
        })
        
        if auth_response.user:
            return jsonify({
                'message': 'Email verified successfully',
                'user': {
                    'id': auth_response.user.id,
                    'email': auth_response.user.email,
                    'email_confirmed': True
                }
            }), 200
        else:
            return jsonify({'error': 'Verification failed'}), 400
            
    except Exception as e:
        return jsonify({'error': f'Verification failed: {str(e)}'}), 500

@supabase_auth_bp.route('/resend-verification', methods=['POST'])
def resend_verification():
    """Resend verification email"""
    try:
        data = request.get_json()
        email = data.get('email', '').strip().lower()
        
        if not email:
            return jsonify({'error': 'Email is required'}), 400
        
        supabase.auth.resend({
            'type': 'signup',
            'email': email,
            'options': {
                'email_redirect_to': 'http://localhost:5173/auth/callback'
            }
        })
        
        return jsonify({
            'message': 'Verification email sent'
        }), 200
            
    except Exception as e:
        return jsonify({'error': f'Failed to resend verification: {str(e)}'}), 500

@supabase_auth_bp.route('/forgot-password', methods=['POST'])
def forgot_password():
    """Send password reset email"""
    try:
        data = request.get_json()
        email = data.get('email', '').strip().lower()
        
        if not email:
            return jsonify({'error': 'Email is required'}), 400
        
        supabase.auth.reset_password_email(email, {
            'redirect_to': 'http://localhost:5173/reset-password'
        })
        
        return jsonify({
            'message': 'Password reset email sent if account exists'
        }), 200
            
    except Exception as e:
        return jsonify({'error': f'Failed to send reset email: {str(e)}'}), 500

@supabase_auth_bp.route('/reset-password', methods=['POST'])
def reset_password():
    """Reset password with token"""
    try:
        data = request.get_json()
        access_token = data.get('access_token')
        new_password = data.get('new_password')
        
        if not access_token or not new_password:
            return jsonify({'error': 'Access token and new password required'}), 400
        
        # Set session
        supabase.auth.set_session(access_token, None)
        
        # Update password
        auth_response = supabase.auth.update_user({
            'password': new_password
        })
        
        if auth_response.user:
            return jsonify({
                'message': 'Password reset successfully'
            }), 200
        else:
            return jsonify({'error': 'Password reset failed'}), 400
            
    except Exception as e:
        return jsonify({'error': f'Password reset failed: {str(e)}'}), 500

@supabase_auth_bp.route('/logout', methods=['POST'])
def logout():
    """Logout user"""
    try:
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({'error': 'No token provided'}), 401
        
        token = auth_header.split(' ')[1]
        
        # Set session and sign out
        supabase.auth.set_session(token, None)
        supabase.auth.sign_out()
        
        return jsonify({'message': 'Logged out successfully'}), 200
            
    except Exception as e:
        return jsonify({'error': f'Logout failed: {str(e)}'}), 500

@supabase_auth_bp.route('/me', methods=['GET'])
def get_current_user():
    """Get current user info"""
    try:
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({'error': 'No token provided'}), 401
        
        token = auth_header.split(' ')[1]
        
        # Get user from token
        user_response = supabase.auth.get_user(token)
        
        if user_response.user:
            # Get profile data
            profile = supabase.table('users').select('*').eq('id', user_response.user.id).execute()
            
            return jsonify({
                'user': {
                    'id': user_response.user.id,
                    'email': user_response.user.email,
                    'email_confirmed': user_response.user.email_confirmed_at is not None,
                    'user_metadata': user_response.user.user_metadata,
                    'profile': profile.data[0] if profile.data else None
                }
            }), 200
        else:
            return jsonify({'error': 'User not found'}), 404
            
    except Exception as e:
        return jsonify({'error': f'Failed to get user: {str(e)}'}), 500
