"""Database and secrets configuration loaded from .env."""

import os
import structlog
from pathlib import Path
from dotenv import load_dotenv

env_path = Path(__file__).parent.parent / '.env'
load_dotenv(dotenv_path=env_path)

logger = structlog.get_logger(__name__)

# Supabase
SUPABASE_URL = os.getenv('SUPABASE_URL', '')
SUPABASE_KEY = os.getenv('SUPABASE_ANON_KEY', '')
SUPABASE_SERVICE_KEY = os.getenv('SUPABASE_SERVICE_KEY', '')

# PostgreSQL direct (optional, for SQLAlchemy)
DATABASE_URL = os.getenv('DATABASE_URL', '')

# JWT
_DEFAULT_SECRET = 'your-secret-key-change-in-production'
JWT_SECRET_KEY = os.getenv('JWT_SECRET_KEY', _DEFAULT_SECRET)
JWT_ALGORITHM = 'HS256'
JWT_ACCESS_TOKEN_EXPIRES = 24 * 60 * 60  # 24 hours

if JWT_SECRET_KEY == _DEFAULT_SECRET:
    _app_env = os.getenv('APP_ENV', 'development')
    if _app_env == 'production':
        raise RuntimeError(
            'JWT_SECRET_KEY is the default placeholder — '
            'set a strong secret in .env before running in production.'
        )
    logger.warning('jwt_secret_is_default_placeholder', env=_app_env)

# Connection pool (used if SQLAlchemy is added later)
DB_POOL_SIZE = 10
DB_MAX_OVERFLOW = 20
DB_POOL_TIMEOUT = 30
DB_POOL_RECYCLE = 3600
