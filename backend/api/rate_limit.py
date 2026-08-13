"""Rate limiting.

The previous build created a limiter but never attached it to a route, so the
API was effectively unlimited. Limits are now declared here as named decorators
and applied at the routes that cost money (LLM pipelines) or invite abuse (auth).

Keys are per authenticated user when a token is present, falling back to client
IP — otherwise every user behind one NAT would share a bucket.
"""

from __future__ import annotations

import structlog
from fastapi import Request

from config import get_settings

logger = structlog.get_logger(__name__)

try:
    from slowapi import Limiter
    from slowapi.errors import RateLimitExceeded
    from slowapi.util import get_remote_address

    SLOWAPI_AVAILABLE = True
except ImportError:  # pragma: no cover - optional dependency
    Limiter = None  # type: ignore[assignment]
    RateLimitExceeded = None  # type: ignore[assignment]
    get_remote_address = None  # type: ignore[assignment]
    SLOWAPI_AVAILABLE = False


def _client_key(request: Request) -> str:
    """Prefer the authenticated subject; fall back to remote address."""
    auth = request.headers.get('authorization', '')
    token = auth[7:] if auth.startswith('Bearer ') else request.cookies.get('token')

    if token:
        try:
            from auth.utils import decode_access_token

            payload = decode_access_token(token)
            user_id = payload.get('user_id')
            if user_id:
                return f'user:{user_id}'
        except Exception:  # noqa: BLE001 — an invalid token just falls back to IP
            pass

    return f'ip:{get_remote_address(request)}' if get_remote_address else 'ip:unknown'


def _redis_reachable(url: str) -> bool:
    """Probe Redis before handing it to the limiter.

    slowapi raises from its storage backend on every request, so an unreachable
    Redis would turn a *rate limiter* into a total API outage. Better to check
    once and fall back to in-process buckets.
    """
    try:
        import redis

        client = redis.from_url(url, socket_connect_timeout=1, socket_timeout=1)
        try:
            client.ping()
            return True
        finally:
            client.close()
    except Exception as exc:  # noqa: BLE001 — any failure means "do not use it"
        logger.warning('rate_limit_redis_unreachable', error=type(exc).__name__)
        return False


def _build_limiter():
    if not SLOWAPI_AVAILABLE:
        logger.warning('rate_limiting_unavailable', reason='slowapi not installed')
        return None

    settings = get_settings()
    if not settings.rate_limit_enabled:
        logger.warning('rate_limiting_disabled', reason='RATE_LIMIT_ENABLED=false')
        return None

    storage_uri = 'memory://'
    if settings.redis_url and _redis_reachable(settings.redis_url):
        storage_uri = settings.redis_url

    if storage_uri == 'memory://' and settings.is_production:
        # In-memory buckets are per-process; with N workers the effective limit
        # is N times the configured one. Surfaced loudly rather than silently
        # mis-limiting in production.
        logger.warning('rate_limit_storage_not_shared', hint='set a reachable REDIS_URL')

    logger.info(
        'rate_limiting_enabled',
        storage='redis' if storage_uri != 'memory://' else 'memory',
        default=settings.rate_limit_default,
    )
    return Limiter(
        key_func=_client_key,
        default_limits=[settings.rate_limit_default],
        storage_uri=storage_uri,
        headers_enabled=True,
    )


limiter = _build_limiter()


def limit(rule_name: str):
    """Decorator factory returning the configured limit for a named bucket.

    Falls back to a no-op when slowapi is missing so the app still boots.
    """
    if limiter is None:
        def _noop(func):
            return func

        return _noop

    settings = get_settings()
    rule = {
        'auth': settings.rate_limit_auth,
        'upload': settings.rate_limit_upload,
        'expensive': settings.rate_limit_expensive,
    }.get(rule_name, settings.rate_limit_default)

    return limiter.limit(rule)
