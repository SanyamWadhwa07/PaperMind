"""Short-lived cache for corpus-wide read models.

The four `/api/corpus/*` graphs and the timeline each rebuild a whole-library
view from scratch: every summary row for the user, plus its citations or lineage
edges, reduced into nodes and edges. That is the same work every time, and the
inputs only change when the user processes or deletes a paper — but the UI hits
these endpoints on every visit to Explore or Timeline, and tab switching hits
them again.

Two backends, chosen the way the rest of the project chooses: Redis when it is
reachable (shared across workers, survives a restart), an in-process LRU
otherwise. The fallback is per-worker, so with N workers a cold entry can be
computed up to N times — acceptable for a read cache with a short TTL, and the
alternative is making Redis a hard dependency of a feature that works without it.

Entries are keyed by user, and `invalidate_user` is called whenever a paper is
written or removed, so a stale graph is bounded by the mutation rather than by
the TTL.
"""

from __future__ import annotations

import json
import threading
import time
from collections import OrderedDict
from typing import Any, Callable, Dict, Optional

import structlog

logger = structlog.get_logger(__name__)

# Long enough to cover a session of tab-switching, short enough that a change
# made in another tab or by a background task shows up on its own.
DEFAULT_TTL_SECONDS = 300

# Per worker. A corpus graph is a few hundred KB at most, and entries are
# per-user-per-view, so this comfortably holds an active set.
MAX_ENTRIES = 256

_lock = threading.Lock()
_store: "OrderedDict[str, tuple[float, Any]]" = OrderedDict()

_redis_client = None
_redis_checked = False


def _get_redis():
    """Redis if reachable, else None. Probed once per process."""
    global _redis_client, _redis_checked
    if _redis_checked:
        return _redis_client

    _redis_checked = True
    try:
        from config import get_settings

        url = get_settings().redis_url
        if not url:
            return None

        import redis

        client = redis.from_url(
            url, decode_responses=True, socket_connect_timeout=1, socket_timeout=1
        )
        client.ping()
        _redis_client = client
        logger.info("response_cache_backend", backend="redis")
    except Exception as exc:  # noqa: BLE001 — any failure means "use memory"
        logger.info("response_cache_backend", backend="memory", reason=type(exc).__name__)
        _redis_client = None

    return _redis_client


def _key(view: str, user_id: str) -> str:
    return f"papermind:view:{view}:{user_id}"


def _memory_get(key: str) -> Optional[Any]:
    with _lock:
        entry = _store.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if time.time() >= expires_at:
            del _store[key]
            return None
        _store.move_to_end(key)
        return value


def _memory_set(key: str, value: Any, ttl: int) -> None:
    with _lock:
        _store[key] = (time.time() + ttl, value)
        _store.move_to_end(key)
        while len(_store) > MAX_ENTRIES:
            _store.popitem(last=False)


def get(view: str, user_id: str) -> Optional[Any]:
    """The cached view, or None."""
    key = _key(view, user_id)

    client = _get_redis()
    if client is not None:
        try:
            raw = client.get(key)
            return json.loads(raw) if raw else None
        except Exception as exc:  # noqa: BLE001
            # A cache is never worth failing a request over.
            logger.warning("response_cache_read_failed", error=type(exc).__name__)
            return None

    return _memory_get(key)


def set(view: str, user_id: str, value: Any, ttl: int = DEFAULT_TTL_SECONDS) -> None:
    """Store a view. Failures are logged and ignored."""
    key = _key(view, user_id)

    client = _get_redis()
    if client is not None:
        try:
            client.setex(key, ttl, json.dumps(value, default=str))
            return
        except Exception as exc:  # noqa: BLE001
            logger.warning("response_cache_write_failed", error=type(exc).__name__)
            return

    _memory_set(key, value, ttl)


def invalidate_user(user_id: str) -> None:
    """Drop every cached view for one user.

    Called after any write that changes what the graphs are built from. Without
    it, a freshly processed paper would be missing from Explore and Timeline for
    up to the TTL, which reads as the upload having silently failed.
    """
    client = _get_redis()
    if client is not None:
        try:
            pattern = _key("*", user_id)
            # `scan_iter`, not `keys`: `keys` blocks the server for the whole
            # scan, which on a shared free-tier instance affects every caller.
            for key in client.scan_iter(match=pattern, count=100):
                client.delete(key)
            return
        except Exception as exc:  # noqa: BLE001
            logger.warning("response_cache_invalidate_failed", error=type(exc).__name__)
            return

    suffix = f":{user_id}"
    with _lock:
        for key in [k for k in _store if k.endswith(suffix)]:
            del _store[key]


async def cached_view(
    view: str,
    user_id: str,
    builder: Callable[[], Any],
    ttl: int = DEFAULT_TTL_SECONDS,
) -> Any:
    """Return `view` for `user_id`, building and caching it on a miss.

    `builder` is an awaitable-returning callable — the routes wrap their
    blocking Supabase work in `asyncio.to_thread` already.
    """
    hit = get(view, user_id)
    if hit is not None:
        logger.debug("response_cache_hit", view=view)
        return hit

    value = await builder()

    # Do not cache an error envelope; the next request should retry rather than
    # be served the failure for the whole TTL.
    if isinstance(value, dict) and value.get("error"):
        return value

    set(view, user_id, value, ttl)
    return value


def clear() -> None:
    """Drop everything. For tests."""
    with _lock:
        _store.clear()
