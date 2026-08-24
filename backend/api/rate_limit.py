"""Rate limiting — a token bucket, shared across processes via Redis.

The previous build created a limiter but never attached it to a route, so the
API was effectively unlimited. Limits are now declared here as named decorators
and applied at the routes that cost money (LLM pipelines) or invite abuse (auth).

Keys are per authenticated user when a token is present, falling back to client
IP — otherwise every user behind one NAT would share a bucket.

Why a token bucket rather than the fixed window this used to use
----------------------------------------------------------------
A fixed window counts requests per calendar interval and resets them all at
once. Two things follow, and both get worse the more users there are:

* **Boundary bursts.** A caller limited to 30/hour can spend 30 at 10:59:59 and
  30 more at 11:00:00 — 60 requests in a second against a limit that reads as
  "30 an hour". For the pipeline routes each of those is a paper extraction, so
  the burst lands squarely on the workers.
* **A cliff, then dead air.** Every caller's window resets on the same boundary,
  so traffic arrives in synchronised waves instead of spread out.

A token bucket refills continuously — `capacity` tokens, replenished at
`capacity / period` per second. Sustained throughput is the same, a burst is
bounded by the bucket's capacity rather than by where the clock happens to fall,
and the refill is smooth, so callers self-space instead of stampeding a boundary.

Correctness across processes
----------------------------
The refill-check-decrement sequence must be atomic, or two workers reading the
same bucket concurrently both see enough tokens and both allow. It runs as a
Lua script so Redis executes it as one indivisible step, and the script reads
Redis's own clock (``TIME``) rather than each app server's, so limits stay
correct when the fleet's clocks disagree.

Without Redis the buckets are per-process, which means N workers grant N times
the configured limit. That is the same degradation the previous implementation
had, is logged loudly at startup, and is why REDIS_URL is not optional in a
real multi-user deployment.
"""

from __future__ import annotations

import functools
import time
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional

import structlog
from fastapi import Request

from api.errors import RateLimitError
from config import get_settings

logger = structlog.get_logger(__name__)

#: Seconds per period name, as used in the "120/minute" rule strings.
_PERIODS = {
    'second': 1, 'sec': 1, 's': 1,
    'minute': 60, 'min': 60, 'm': 60,
    'hour': 3600, 'hr': 3600, 'h': 3600,
    'day': 86400, 'd': 86400,
}

# Refill, check and decrement in one indivisible step. Returns
# {allowed, tokens_remaining, retry_after_seconds} — the two float values as
# strings, because Lua truncates numbers to integers on the way out.
_LUA_TOKEN_BUCKET = """
local key      = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill   = tonumber(ARGV[2])
local cost     = tonumber(ARGV[3])

-- Redis's clock, not the caller's: app servers in a fleet drift apart, and a
-- bucket read by two of them must agree on how much time has passed.
local t   = redis.call('TIME')
local now = tonumber(t[1]) + (tonumber(t[2]) / 1000000)

local data   = redis.call('HMGET', key, 'tokens', 'ts')
local tokens = tonumber(data[1])
local ts     = tonumber(data[2])

if tokens == nil or ts == nil then
  tokens = capacity
  ts = now
end

local elapsed = now - ts
if elapsed < 0 then elapsed = 0 end
tokens = math.min(capacity, tokens + (elapsed * refill))

local allowed = 0
local retry_after = 0
if tokens >= cost then
  tokens = tokens - cost
  allowed = 1
else
  retry_after = (cost - tokens) / refill
end

redis.call('HSET', key, 'tokens', tokens, 'ts', now)
-- An idle bucket refills to full in capacity/refill seconds; after that its
-- stored state is indistinguishable from a fresh one, so let it expire.
redis.call('PEXPIRE', key, math.ceil((capacity / refill) * 1000) + 1000)

return {allowed, tostring(tokens), tostring(retry_after)}
"""


@dataclass(frozen=True)
class Rule:
    """A parsed limit: `capacity` tokens, refilled at `refill` per second."""

    capacity: int
    refill: float
    raw: str


@dataclass(frozen=True)
class Decision:
    allowed: bool
    remaining: float
    retry_after: float
    limit: int


def parse_rule(rule: str) -> Rule:
    """Parse a ``"120/minute"`` limit string into bucket parameters.

    The string form is kept from the previous implementation so existing
    settings and env vars keep working unchanged.
    """
    try:
        count_s, _, period_s = rule.partition('/')
        count = int(count_s.strip())
        period_key = period_s.strip().lower().rstrip('s') or 'minute'
        seconds = _PERIODS.get(period_key)
        if seconds is None:
            raise KeyError(period_key)
        if count <= 0:
            raise ValueError(count)
    except Exception as exc:  # noqa: BLE001 — a bad rule must not boot a broken limiter
        logger.warning('rate_limit_rule_invalid', rule=rule, error=str(exc))
        return Rule(capacity=120, refill=120 / 60, raw='120/minute')
    return Rule(capacity=count, refill=count / seconds, raw=rule)


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

    client = request.client
    return f'ip:{client.host}' if client and client.host else 'ip:unknown'


class TokenBucketLimiter:
    """Token bucket over Redis, degrading to per-process buckets."""

    def __init__(self, redis_url: str = '') -> None:
        self._redis_url = redis_url
        self._redis = None
        self._script = None
        self._local: dict[str, tuple[float, float]] = {}
        self._degraded = False

    @property
    def shared(self) -> bool:
        """True when buckets are shared across processes (i.e. Redis is live)."""
        return self._redis is not None and not self._degraded

    async def _client(self):
        if self._redis is None and self._redis_url and not self._degraded:
            try:
                import redis.asyncio as aioredis

                client = aioredis.from_url(
                    self._redis_url, socket_connect_timeout=1, socket_timeout=1,
                    decode_responses=True,
                )
                await client.ping()
                self._redis = client
                self._script = client.register_script(_LUA_TOKEN_BUCKET)
                logger.info('rate_limit_backend', backend='redis')
            except Exception as exc:  # noqa: BLE001
                # Any failure means "do not use it". A limiter that raises on
                # every request would turn rate limiting into a total outage.
                logger.warning('rate_limit_redis_unreachable', error=type(exc).__name__)
                self._degraded = True
        return self._redis

    def _consume_local(self, key: str, rule: Rule, cost: float) -> Decision:
        now = time.monotonic()
        tokens, ts = self._local.get(key, (float(rule.capacity), now))
        tokens = min(rule.capacity, tokens + max(0.0, now - ts) * rule.refill)

        if tokens >= cost:
            self._local[key] = (tokens - cost, now)
            return Decision(True, tokens - cost, 0.0, rule.capacity)

        self._local[key] = (tokens, now)
        return Decision(False, tokens, (cost - tokens) / rule.refill, rule.capacity)

    async def consume(self, key: str, rule: Rule, cost: float = 1.0) -> Decision:
        client = await self._client()
        if client is not None and self._script is not None:
            try:
                allowed, tokens, retry = await self._script(
                    keys=[f'papermind:rl:{key}'],
                    args=[rule.capacity, rule.refill, cost],
                )
                return Decision(
                    allowed=bool(int(allowed)),
                    remaining=float(tokens),
                    retry_after=float(retry),
                    limit=rule.capacity,
                )
            except Exception as exc:  # noqa: BLE001
                # Redis went away mid-flight. Fall through to local buckets for
                # this request rather than 500-ing a request that was fine.
                logger.warning('rate_limit_redis_failed', error=type(exc).__name__)
                self._redis = None
                self._script = None
                self._degraded = True
        return self._consume_local(key, rule, cost)


def _build_limiter() -> Optional[TokenBucketLimiter]:
    settings = get_settings()
    if not settings.rate_limit_enabled:
        logger.warning('rate_limiting_disabled', reason='RATE_LIMIT_ENABLED=false')
        return None

    if not settings.redis_url and settings.is_production:
        # Per-process buckets mean N workers grant N times the configured limit.
        # Surfaced loudly rather than silently mis-limiting in production.
        logger.warning('rate_limit_storage_not_shared', hint='set a reachable REDIS_URL')

    logger.info(
        'rate_limiting_enabled',
        algorithm='token_bucket',
        default=settings.rate_limit_default,
    )
    return TokenBucketLimiter(settings.redis_url)


limiter: Optional[TokenBucketLimiter] = _build_limiter()


def _rule_for(rule_name: str) -> Rule:
    settings = get_settings()
    raw = {
        'auth': settings.rate_limit_auth,
        'upload': settings.rate_limit_upload,
        'expensive': settings.rate_limit_expensive,
    }.get(rule_name, settings.rate_limit_default)
    return parse_rule(raw)


def rate_limit_headers(request: Request) -> dict[str, str]:
    """RateLimit-* headers for the decision recorded on this request, if any.

    Read by RequestContextMiddleware rather than written onto the injected
    `Response`: when an endpoint raises, FastAPI discards that object and the
    error handler builds a fresh response, so headers set there survive only on
    the success path. Clients that self-throttle need them on 401s and 429s too
    — those are exactly the responses that mean "slow down".
    """
    d: Optional[Decision] = getattr(request.state, 'ratelimit', None)
    if d is None:
        return {}
    return {
        'RateLimit-Limit': str(d.limit),
        'RateLimit-Remaining': str(max(0, int(d.remaining))),
        'RateLimit-Reset': str(max(0, int(round(d.retry_after)))),
    }


def limit(rule_name: str) -> Callable:
    """Decorator applying the named bucket to an endpoint.

    The endpoint must take ``request: Request`` (to key the bucket); it may also
    take ``response: Response``, which receives the RateLimit-* headers. Both are
    already present on every route this is applied to.

    A no-op when rate limiting is disabled, so the app still boots.
    """
    def decorator(func: Callable[..., Awaitable]) -> Callable[..., Awaitable]:
        if limiter is None:
            return func

        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            request: Optional[Request] = kwargs.get('request')
            if request is None:
                request = next((a for a in args if isinstance(a, Request)), None)
            if request is None:
                # No Request to key on: allow rather than reject, and say so —
                # a silently unlimited route is exactly the bug this module
                # was written to fix.
                logger.warning('rate_limit_skipped', reason='no_request_arg',
                               endpoint=func.__name__)
                return await func(*args, **kwargs)

            rule = _rule_for(rule_name)
            decision = await limiter.consume(_client_key(request), rule)
            request.state.ratelimit = decision

            if not decision.allowed:
                retry = max(1, int(round(decision.retry_after)))
                logger.info('rate_limit_exceeded', bucket=rule_name,
                            rule=rule.raw, endpoint=func.__name__, retry_after=retry)
                raise RateLimitError(
                    f'Rate limit exceeded for this endpoint ({rule.raw}). '
                    f'Retry in {retry}s.',
                    headers={'Retry-After': str(retry)},
                )
            return await func(*args, **kwargs)

        return wrapper

    return decorator
