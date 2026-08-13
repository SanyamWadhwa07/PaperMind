"""Authentication and account business logic."""

from __future__ import annotations

import asyncio
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog

from api.errors import (
    AuthenticationError,
    ConflictError,
    NotFoundError,
    PermissionError_,
    ValidationError,
)
from auth.utils import (
    create_access_token,
    hash_password,
    validate_email,
    validate_password_strength,
    verify_password,
)
from repositories import ActivityRepository, UserRepository

logger = structlog.get_logger(__name__)

# A real bcrypt digest of a random string. Verifying against it when an account
# does not exist keeps login latency constant, so response time cannot be used
# to enumerate registered email addresses.
_DUMMY_HASH = '$2b$12$C6UzMDM.H6dfI/f/IKcEe.rXcCZTa7bC6ZnKZ3f8sCTn6mLp0Ru1S'

_PUBLIC_USER_FIELDS = ('id', 'email', 'full_name', 'bio', 'avatar_url', 'created_at')


@dataclass(frozen=True)
class AuthResult:
    token: str
    user: dict[str, Any]

    def to_dict(self, message: str) -> dict[str, Any]:
        return {'message': message, 'token': self.token, 'user': self.user}


def _public_user(row: dict[str, Any]) -> dict[str, Any]:
    """Strip password hashes and internal columns before returning a user."""
    return {field: row.get(field) for field in _PUBLIC_USER_FIELDS}


def _parse_timestamp(value: str) -> datetime:
    """Parse an ISO timestamp, treating a naive value as UTC."""
    parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


class AuthService:
    def __init__(
        self,
        users: UserRepository,
        activity: ActivityRepository | None = None,
        *,
        reset_token_ttl_seconds: int = 3600,
    ) -> None:
        self._users = users
        self._activity = activity
        self._reset_ttl = reset_token_ttl_seconds

    async def signup(
        self, email: str, password: str, full_name: str | None = None
    ) -> AuthResult:
        email = email.strip().lower()

        if not validate_email(email):
            raise ValidationError('Invalid email format')

        ok, problem = validate_password_strength(password)
        if not ok:
            raise ValidationError(problem)

        if await self._users.get_by_email(email) is not None:
            raise ConflictError('Email already registered')

        password_hash = await asyncio.to_thread(hash_password, password)
        created = await self._users.create(
            {
                'email': email,
                'password_hash': password_hash,
                'full_name': full_name,
                'created_at': datetime.now(timezone.utc).isoformat(),
                'is_active': True,
            }
        )
        if not created:
            raise ConflictError('Failed to create account')

        logger.info('user_signed_up', user_id=created.get('id'))
        token = create_access_token(created['id'], created['email'])
        return AuthResult(token=token, user=_public_user(created))

    async def login(self, email: str, password: str) -> AuthResult:
        email = email.strip().lower()
        user = await self._users.get_by_email(email)

        if user is None:
            # Burn the same time a real verification would take.
            await asyncio.to_thread(verify_password, password, _DUMMY_HASH)
            raise AuthenticationError('Invalid email or password')

        if not user.get('is_active', True):
            raise PermissionError_('Account is deactivated')

        matches = await asyncio.to_thread(
            verify_password, password, user.get('password_hash') or _DUMMY_HASH
        )
        if not matches:
            raise AuthenticationError('Invalid email or password')

        await self._users.touch_last_login(user['id'])
        logger.info('user_logged_in', user_id=user['id'])

        token = create_access_token(user['id'], user['email'])
        return AuthResult(token=token, user=_public_user(user))

    async def get_profile(self, user_id: str) -> dict[str, Any]:
        user = await self._users.get_by_id(user_id)
        if user is None:
            raise NotFoundError('User not found')
        return user

    async def update_profile(
        self, user_id: str, fields: dict[str, Any]
    ) -> dict[str, Any]:
        updates = {k: v for k, v in fields.items() if v is not None}
        if not updates:
            raise ValidationError('No valid fields to update')

        updates['updated_at'] = datetime.now(timezone.utc).isoformat()
        updated = await self._users.update(user_id, updates)
        if not updated:
            raise NotFoundError('User not found')
        return _public_user(updated)

    async def change_password(
        self, user_id: str, current_password: str, new_password: str
    ) -> None:
        ok, problem = validate_password_strength(new_password)
        if not ok:
            raise ValidationError(problem)

        user = await self._users.get_by_id(user_id)
        if user is None:
            raise NotFoundError('User not found')

        credentials = await self._users.get_credentials(user['email'])
        stored_hash = (credentials or {}).get('password_hash') or _DUMMY_HASH

        if not await asyncio.to_thread(verify_password, current_password, stored_hash):
            raise AuthenticationError('Current password is incorrect')

        if await asyncio.to_thread(verify_password, new_password, stored_hash):
            raise ValidationError('New password must differ from the current one')

        new_hash = await asyncio.to_thread(hash_password, new_password)
        await self._users.update(
            user_id,
            {
                'password_hash': new_hash,
                'updated_at': datetime.now(timezone.utc).isoformat(),
            },
        )
        logger.info('password_changed', user_id=user_id)

    async def request_password_reset(self, email: str) -> str | None:
        """Issue a reset token.

        Always returns without error so callers cannot use this endpoint to
        discover which addresses are registered. The token is returned to the
        caller (not the client) so a mailer can send it; None means no account.
        """
        email = email.strip().lower()
        user = await self._users.get_by_email(email)
        if user is None:
            logger.info('password_reset_requested_unknown_email')
            return None

        token = secrets.token_urlsafe(32)
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=self._reset_ttl)
        await self._users.update(
            user['id'],
            {
                'reset_token': token,
                'reset_token_expires': expires_at.isoformat(),
            },
        )
        logger.info('password_reset_requested', user_id=user['id'])
        return token

    async def reset_password(self, token: str, new_password: str) -> None:
        """Consume a reset token and set a new password."""
        ok, problem = validate_password_strength(new_password)
        if not ok:
            raise ValidationError(problem)

        user = await self._users.get_by_reset_token(token)
        if user is None:
            raise ValidationError('Invalid or expired reset token')

        expires_raw = user.get('reset_token_expires')
        if not expires_raw or _parse_timestamp(expires_raw) < datetime.now(timezone.utc):
            raise ValidationError('Invalid or expired reset token')

        new_hash = await asyncio.to_thread(hash_password, new_password)
        await self._users.update(
            user['id'],
            {
                'password_hash': new_hash,
                # Single-use: clear the token so it cannot be replayed.
                'reset_token': None,
                'reset_token_expires': None,
                'updated_at': datetime.now(timezone.utc).isoformat(),
            },
        )
        logger.info('password_reset_completed', user_id=user['id'])
