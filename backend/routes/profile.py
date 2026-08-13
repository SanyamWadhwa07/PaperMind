"""Profile and avatar management routes."""

import asyncio
import structlog
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, UploadFile, File
from fastapi.responses import JSONResponse
from werkzeug.utils import secure_filename
from db import supabase as _shared_supabase

from auth.dependencies import CurrentUser
from schemas import ProfileUpdateRequest

logger = structlog.get_logger(__name__)
router = APIRouter()
supabase = _shared_supabase

ALLOWED_IMAGE_EXTS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
MAX_AVATAR_BYTES = 5 * 1024 * 1024  # 5 MB


def _allowed_image(filename: str) -> bool:
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_IMAGE_EXTS


@router.get('/profile')
async def get_profile(current_user: CurrentUser):
    user_id = current_user['user_id']
    try:
        result = await asyncio.to_thread(
            lambda: supabase.table('users').select('*').eq('id', user_id).execute()
        )
        if not result.data:
            return JSONResponse(status_code=404, content={'error': 'Profile not found'})
        return {'profile': result.data[0]}
    except Exception as e:
        logger.exception('get_profile_error', error=str(e))
        return JSONResponse(status_code=500, content={'error': 'Failed to fetch profile'})


@router.put('/profile')
async def update_profile(data: ProfileUpdateRequest, current_user: CurrentUser):
    user_id = current_user['user_id']
    update_data = {k: v for k, v in data.model_dump().items() if v is not None}
    if 'full_name' in update_data:
        update_data['full_name'] = update_data['full_name'].strip()
    if 'bio' in update_data:
        update_data['bio'] = update_data['bio'].strip()

    if not update_data:
        return JSONResponse(status_code=400, content={'error': 'No data to update'})

    update_data['updated_at'] = datetime.now(timezone.utc).isoformat()

    try:
        result = await asyncio.to_thread(
            lambda: supabase.table('users').update(update_data).eq('id', user_id).execute()
        )
        if not result.data:
            return JSONResponse(status_code=500, content={'error': 'Failed to update profile'})
        return {'message': 'Profile updated successfully', 'profile': result.data[0]}
    except Exception as e:
        logger.exception('update_profile_error', error=str(e))
        return JSONResponse(status_code=500, content={'error': 'Failed to update profile'})


@router.post('/profile/avatar')
async def upload_avatar(current_user: CurrentUser, avatar: UploadFile = File(...)):
    user_id = current_user['user_id']

    if not _allowed_image(avatar.filename or ''):
        return JSONResponse(
            status_code=400,
            content={'error': 'Invalid file type. Allowed: PNG, JPG, JPEG, GIF, WEBP'},
        )

    content = await avatar.read()
    if len(content) > MAX_AVATAR_BYTES:
        return JSONResponse(status_code=400, content={'error': 'File too large. Maximum 5 MB'})

    ext = (avatar.filename or 'avatar.png').rsplit('.', 1)[1].lower()
    filename = f"{user_id}/{uuid.uuid4()}.{ext}"

    try:
        await asyncio.to_thread(
            lambda: supabase.storage.from_('avatars').upload(
                filename, content,
                {'content-type': avatar.content_type or 'image/jpeg', 'upsert': 'true'}
            )
        )
        public_url = supabase.storage.from_('avatars').get_public_url(filename)

        await asyncio.to_thread(
            lambda: supabase.table('users').update({
                'avatar_url': public_url,
                'updated_at': datetime.now(timezone.utc).isoformat(),
            }).eq('id', user_id).execute()
        )

        return {'message': 'Avatar uploaded successfully', 'avatar_url': public_url}
    except Exception as e:
        logger.exception('avatar_upload_error', error=str(e))
        return JSONResponse(status_code=500, content={'error': f'Storage upload failed: {str(e)}'})


@router.delete('/profile/avatar')
async def delete_avatar(current_user: CurrentUser):
    user_id = current_user['user_id']
    try:
        user_result = await asyncio.to_thread(
            lambda: supabase.table('users').select('avatar_url').eq('id', user_id).execute()
        )
        if not user_result.data or not user_result.data[0].get('avatar_url'):
            return JSONResponse(status_code=404, content={'error': 'No avatar to delete'})

        avatar_url = user_result.data[0]['avatar_url']
        if '/avatars/' in avatar_url:
            storage_filename = avatar_url.split('/avatars/')[1]
            try:
                await asyncio.to_thread(
                    lambda: supabase.storage.from_('avatars').remove([storage_filename])
                )
            except Exception as e:
                logger.warning('avatar_storage_delete_failed', error=str(e))

        await asyncio.to_thread(
            lambda: supabase.table('users').update({
                'avatar_url': None,
                'updated_at': datetime.now(timezone.utc).isoformat(),
            }).eq('id', user_id).execute()
        )
        return {'message': 'Avatar deleted successfully'}
    except Exception as e:
        logger.exception('delete_avatar_error', error=str(e))
        return JSONResponse(status_code=500, content={'error': 'Failed to delete avatar'})
