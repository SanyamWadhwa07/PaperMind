"""Authentication utilities — JWT creation/validation and password hashing."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from database.config import JWT_ACCESS_TOKEN_EXPIRES, JWT_ALGORITHM, JWT_SECRET_KEY

# bcrypt silently truncates at 72 bytes; rejecting longer input avoids two
# different passwords hashing to the same digest.
_MAX_PASSWORD_BYTES = 72

_EMAIL_PATTERN = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')


class TokenError(Exception):
    """Raised when a JWT is missing, malformed, or expired."""


def hash_password(password: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode('utf-8')[:_MAX_PASSWORD_BYTES], salt).decode('utf-8')


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(
            password.encode('utf-8')[:_MAX_PASSWORD_BYTES], hashed.encode('utf-8')
        )
    except (ValueError, TypeError):
        # A malformed stored hash must read as "no match", never as an error.
        return False


def create_access_token(user_id: str, email: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        'user_id': user_id,
        'email': email,
        'exp': now + timedelta(seconds=JWT_ACCESS_TOKEN_EXPIRES),
        'iat': now,
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    try:
        return jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise TokenError('Token has expired') from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError('Invalid token') from exc


def validate_email(email: str) -> bool:
    return bool(_EMAIL_PATTERN.match(email or ''))


def validate_password_strength(password: str) -> tuple[bool, str]:
    if len(password or '') < 8:
        return False, 'Password must be at least 8 characters long'
    if len(password.encode('utf-8')) > _MAX_PASSWORD_BYTES:
        return False, 'Password must be at most 72 bytes long'
    if not any(c.isupper() for c in password):
        return False, 'Password must contain at least one uppercase letter'
    if not any(c.islower() for c in password):
        return False, 'Password must contain at least one lowercase letter'
    if not any(c.isdigit() for c in password):
        return False, 'Password must contain at least one number'
    return True, ''
