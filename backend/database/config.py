"""Legacy configuration shim.

Configuration now lives in `backend/config/settings.py` as a validated
`Settings` object. This module re-exports the handful of values that older
modules import by name so existing imports keep working.

New code should depend on `config.get_settings()` instead.
"""

from __future__ import annotations

from config import get_settings

_settings = get_settings()

SUPABASE_URL = _settings.supabase_url
SUPABASE_KEY = _settings.supabase_anon_key
SUPABASE_SERVICE_KEY = _settings.supabase_service_key
DATABASE_URL = ''

JWT_SECRET_KEY = _settings.jwt_secret_key
JWT_ALGORITHM = _settings.jwt_algorithm
JWT_ACCESS_TOKEN_EXPIRES = _settings.jwt_access_token_expires

__all__ = [
    'SUPABASE_URL',
    'SUPABASE_KEY',
    'SUPABASE_SERVICE_KEY',
    'DATABASE_URL',
    'JWT_SECRET_KEY',
    'JWT_ALGORITHM',
    'JWT_ACCESS_TOKEN_EXPIRES',
]
