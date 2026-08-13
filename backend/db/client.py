"""Supabase client lifecycle.

Previously every route module built its own client at import time, which meant
importing a route opened a network client and tests had to patch module globals.
The client is now created lazily behind a provider so it can be swapped in tests
and constructed after settings are validated.
"""

from __future__ import annotations

import threading
from typing import Optional

import structlog
from supabase import Client, create_client

from config import get_settings

logger = structlog.get_logger(__name__)


class SupabaseProvider:
    """Lazy, per-thread Supabase clients behind one accessor.

    Repositories run every Supabase call in a worker thread (`asyncio.to_thread`)
    because the SDK is synchronous, so a single shared client is driven by many
    threads at once. Underneath it is one `httpx.Client` speaking HTTP/2, and
    concurrent use of that sync HTTP/2 transport corrupts the connection's
    stream state: reads fail with `WinError 10035 — a non-blocking socket
    operation could not be completed immediately`, which surfaced as random 503s
    on endpoints that were otherwise perfectly healthy.

    Each thread therefore gets its own client and its own connection pool. The
    executor's thread count is bounded, so the number of clients is too, and
    threads are reused across requests so this is not per-request cost.
    """

    def __init__(self) -> None:
        self._local = threading.local()
        self._injected: Optional[Client] = None
        self._lock = threading.Lock()

    def _create(self) -> Client:
        settings = get_settings()
        if not settings.supabase_url or not settings.supabase_service_key:
            raise RuntimeError(
                'Supabase is not configured — set SUPABASE_URL and '
                'SUPABASE_SERVICE_KEY in the environment.'
            )
        client = create_client(settings.supabase_url, settings.supabase_service_key)
        logger.info('supabase_client_created', thread=threading.current_thread().name)
        return client

    def get(self) -> Client:
        # An injected double is shared on purpose: tests assert against the calls
        # it recorded, which only works if every thread sees the same object.
        if self._injected is not None:
            return self._injected

        client = getattr(self._local, 'client', None)
        if client is None:
            client = self._create()
            self._local.client = client
        return client

    def set(self, client: Optional[Client]) -> None:
        """Inject a client (or a test double). Passing None clears the cache."""
        with self._lock:
            self._injected = client
            self._local = threading.local()


_provider = SupabaseProvider()


def get_supabase() -> Client:
    """FastAPI dependency / direct accessor for the shared Supabase client."""
    return _provider.get()


def reset_supabase(client: Optional[Client] = None) -> None:
    """Test hook: replace or clear the cached client."""
    _provider.set(client)


class LazySupabase:
    """Attribute proxy that resolves the shared client on first use.

    Route modules that have not yet been moved onto the repository layer import
    this instead of building their own client at import time. Importing a route
    therefore no longer opens a network client, and nothing breaks if Supabase
    credentials are absent until a request actually needs them.
    """

    __slots__ = ()

    def __getattr__(self, name: str):
        return getattr(_provider.get(), name)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return '<LazySupabase>'


#: Drop-in replacement for a module-level `create_client(...)` result.
supabase = LazySupabase()
