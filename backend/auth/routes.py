"""Authentication routes — register, login, profile, password management."""

import asyncio
import structlog
from datetime import datetime
from fastapi import APIRouter, Response, Request
from fastapi.responses import JSONResponse
from supabase import create_client

from database.config import SUPABASE_URL, SUPABASE_SERVICE_KEY
from auth.utils import (
    hash_password,
    verify_password,
    create_access_token,
    validate_email,
    validate_password_strength,
)
from auth.dependencies import CurrentUser
from schemas import LoginRequest, RegisterRequest, ChangePasswordRequest, ProfileUpdateRequest

logger = structlog.get_logger(__name__)

router = APIRouter()
supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

_COOKIE_MAX_AGE = 24 * 60 * 60  # 24 hours, matches JWT expiry


def _set_auth_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key='token',
        value=token,
        httponly=True,
        secure=False,   # set True when serving over HTTPS in production
        samesite='lax',
        max_age=_COOKIE_MAX_AGE,
        path='/',
    )


@router.post('/signup', status_code=201)
async def signup(data: RegisterRequest, response: Response):
    email = data.email
    password = data.password
    full_name = data.full_name

    if not validate_email(email):
        return JSONResponse(status_code=400, content={'error': 'Invalid email format'})

    is_valid, err = validate_password_strength(password)
    if not is_valid:
        return JSONResponse(status_code=400, content={'error': err})

    try:
        existing = await asyncio.to_thread(
            lambda: supabase.table('users').select('id').eq('email', email).execute()
        )
    except Exception:
        existing = type('obj', (object,), {'data': []})()

    if existing.data:
        return JSONResponse(status_code=409, content={'error': 'Email already registered'})

    password_hash = await asyncio.to_thread(hash_password, password)

    try:
        result = await asyncio.to_thread(
            lambda: supabase.table('users').insert({
                'email': email,
                'password_hash': password_hash,
                'full_name': full_name,
                'created_at': datetime.utcnow().isoformat(),
                'is_active': True,
            }).execute()
        )
    except Exception as e:
        logger.exception('signup_db_error', email=email, error=str(e))
        return JSONResponse(status_code=500, content={'error': 'Failed to create user'})

    if not result.data:
        return JSONResponse(status_code=500, content={'error': 'Failed to create user'})

    user = result.data[0]
    token = create_access_token(user['id'], user['email'])
    _set_auth_cookie(response, token)

    return {
        'message': 'User created successfully',
        'token': token,
        'user': {
            'id': user['id'],
            'email': user['email'],
            'full_name': user.get('full_name'),
            'created_at': user['created_at'],
        },
    }


@router.post('/login')
async def login(data: LoginRequest, response: Response, request: Request):
    email = data.email
    password = data.password

    try:
        result = await asyncio.to_thread(
            lambda: supabase.table('users').select('*').eq('email', email).execute()
        )
    except Exception as e:
        logger.exception('login_db_error', error=str(e))
        return JSONResponse(status_code=500, content={'error': 'Login failed'})

    if not result.data:
        return JSONResponse(status_code=401, content={'error': 'Invalid email or password'})

    user = result.data[0]

    if not user.get('is_active', True):
        return JSONResponse(status_code=403, content={'error': 'Account is deactivated'})

    match = await asyncio.to_thread(verify_password, password, user['password_hash'])
    if not match:
        return JSONResponse(status_code=401, content={'error': 'Invalid email or password'})

    try:
        await asyncio.to_thread(
            lambda: supabase.table('users').update({
                'last_login': datetime.utcnow().isoformat()
            }).eq('id', user['id']).execute()
        )
    except Exception:
        pass  # non-critical

    token = create_access_token(user['id'], user['email'])
    _set_auth_cookie(response, token)

    return {
        'message': 'Login successful',
        'token': token,
        'user': {
            'id': user['id'],
            'email': user['email'],
            'full_name': user.get('full_name'),
            'bio': user.get('bio'),
            'avatar_url': user.get('avatar_url'),
            'created_at': user['created_at'],
        },
    }


@router.post('/logout')
async def logout(response: Response):
    response.delete_cookie(key='token', path='/')
    return {'message': 'Logged out successfully'}


@router.get('/me')
async def get_current_user_profile(current_user: CurrentUser):
    user_id = current_user['user_id']
    try:
        result = await asyncio.to_thread(
            lambda: supabase.table('users')
            .select('id, email, full_name, bio, avatar_url, created_at, last_login')
            .eq('id', user_id)
            .execute()
        )
    except Exception as e:
        logger.exception('get_profile_error', error=str(e))
        return JSONResponse(status_code=500, content={'error': 'Failed to fetch user'})

    if not result.data:
        return JSONResponse(status_code=404, content={'error': 'User not found'})

    user = result.data[0]

    try:
        stats_result = await asyncio.to_thread(
            lambda: supabase.table('summaries').select('id', count='exact').eq('user_id', user_id).execute()
        )
        total = stats_result.count or 0
    except Exception:
        total = 0

    return {
        'user': user,
        'stats': {
            'total_summaries': total,
            'avg_processing_time': 0,
            'total_words_processed': 0,
            'last_summary_date': None,
            'active_days': 0,
        },
    }


@router.put('/me')
async def update_profile_route(data: ProfileUpdateRequest, current_user: CurrentUser):
    user_id = current_user['user_id']
    update_data = {k: v for k, v in data.model_dump().items() if v is not None}
    if not update_data:
        return JSONResponse(status_code=400, content={'error': 'No valid fields to update'})

    update_data['updated_at'] = datetime.utcnow().isoformat()

    try:
        result = await asyncio.to_thread(
            lambda: supabase.table('users').update(update_data).eq('id', user_id).execute()
        )
    except Exception as e:
        logger.exception('update_profile_error', error=str(e))
        return JSONResponse(status_code=500, content={'error': 'Update failed'})

    if not result.data:
        return JSONResponse(status_code=500, content={'error': 'Failed to update profile'})

    return {'message': 'Profile updated successfully', 'user': result.data[0]}


@router.post('/change-password')
async def change_password(data: ChangePasswordRequest, current_user: CurrentUser):
    user_id = current_user['user_id']

    is_valid, err = validate_password_strength(data.new_password)
    if not is_valid:
        return JSONResponse(status_code=400, content={'error': err})

    try:
        result = await asyncio.to_thread(
            lambda: supabase.table('users').select('password_hash').eq('id', user_id).execute()
        )
    except Exception as e:
        logger.exception('change_password_db_error', error=str(e))
        return JSONResponse(status_code=500, content={'error': 'Password change failed'})

    if not result.data:
        return JSONResponse(status_code=404, content={'error': 'User not found'})

    if not await asyncio.to_thread(verify_password, data.current_password, result.data[0]['password_hash']):
        return JSONResponse(status_code=401, content={'error': 'Current password is incorrect'})

    new_hash = await asyncio.to_thread(hash_password, data.new_password)
    await asyncio.to_thread(
        lambda: supabase.table('users').update({
            'password_hash': new_hash,
            'updated_at': datetime.utcnow().isoformat(),
        }).eq('id', user_id).execute()
    )

    return {'message': 'Password changed successfully'}
