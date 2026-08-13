"""Authentication endpoints.

Thin controllers: parse the request, call a service, shape the response.
All rules (validation, uniqueness, password policy) live in `AuthService`.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Request, Response

from api.deps import AuthServiceDep, SettingsDep
from api.rate_limit import limit
from auth.dependencies import CurrentUser
from schemas import (
    ChangePasswordRequest,
    LoginRequest,
    PasswordResetConfirmRequest,
    PasswordResetRequest,
    ProfileUpdateRequest,
    RegisterRequest,
)

logger = structlog.get_logger(__name__)
router = APIRouter()


def _set_auth_cookie(response: Response, token: str, settings) -> None:
    """Store the JWT in an httpOnly cookie.

    `secure` follows the environment: forcing it on in local HTTP development
    would make the browser silently drop the cookie.
    """
    response.set_cookie(
        key='token',
        value=token,
        httponly=True,
        secure=settings.is_production,
        samesite='lax',
        max_age=settings.jwt_access_token_expires,
        path='/',
    )


@router.post('/signup', status_code=201)
@limit('auth')
async def signup(
    request: Request,
    data: RegisterRequest,
    response: Response,
    auth: AuthServiceDep,
    settings: SettingsDep,
):
    result = await auth.signup(data.email, data.password, data.full_name)
    _set_auth_cookie(response, result.token, settings)
    return result.to_dict('Account created successfully')


@router.post('/login')
@limit('auth')
async def login(
    request: Request,
    data: LoginRequest,
    response: Response,
    auth: AuthServiceDep,
    settings: SettingsDep,
):
    result = await auth.login(data.email, data.password)
    _set_auth_cookie(response, result.token, settings)
    return result.to_dict('Login successful')


@router.post('/logout')
async def logout(response: Response):
    response.delete_cookie(key='token', path='/')
    return {'message': 'Logged out successfully'}


@router.get('/me')
async def get_me(current_user: CurrentUser, auth: AuthServiceDep):
    user = await auth.get_profile(current_user['user_id'])
    return {'user': user}


@router.put('/me')
async def update_me(
    data: ProfileUpdateRequest, current_user: CurrentUser, auth: AuthServiceDep
):
    user = await auth.update_profile(current_user['user_id'], data.model_dump())
    return {'message': 'Profile updated successfully', 'user': user}


@router.post('/change-password')
@limit('auth')
async def change_password(
    request: Request,
    data: ChangePasswordRequest,
    current_user: CurrentUser,
    auth: AuthServiceDep,
):
    await auth.change_password(
        current_user['user_id'], data.current_password, data.new_password
    )
    return {'message': 'Password changed successfully'}


@router.post('/forgot-password')
@limit('auth')
async def forgot_password(
    request: Request,
    data: PasswordResetRequest,
    auth: AuthServiceDep,
    settings: SettingsDep,
):
    """Begin a password reset.

    Always reports success — revealing whether an address is registered would
    turn this into an account-enumeration oracle.
    """
    token = await auth.request_password_reset(data.email)
    payload: dict[str, object] = {
        'message': 'If an account exists for that address, a reset link has been sent.'
    }
    # No mail provider is wired up yet, so outside production the token is
    # returned directly to keep the flow usable and testable end to end.
    if token and not settings.is_production:
        payload['reset_token'] = token
    return payload


@router.post('/reset-password')
@limit('auth')
async def reset_password(
    request: Request, data: PasswordResetConfirmRequest, auth: AuthServiceDep
):
    await auth.reset_password(data.token, data.new_password)
    return {'message': 'Password reset successfully'}
