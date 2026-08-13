"""Repository base class.

Repositories own *all* persistence concerns. They never raise HTTP errors and
never contain business rules — that keeps services independent of Supabase and
lets them be unit-tested against an in-memory fake implementing the same shape.

Supabase's Python SDK is synchronous, so every call is pushed to a worker thread
to avoid blocking the event loop.
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable, TypeVar

import structlog
from supabase import Client

logger = structlog.get_logger(__name__)

T = TypeVar('T')


class RepositoryError(RuntimeError):
    """Raised when the underlying store fails. Services translate this to HTTP."""


class BaseRepository:
    """Shared plumbing for Supabase-backed repositories."""

    #: Table this repository reads and writes. Subclasses must set it.
    table_name: str = ''

    def __init__(self, client: Client) -> None:
        self._client = client

    @property
    def table(self):
        if not self.table_name:
            raise NotImplementedError(f'{type(self).__name__} must define table_name')
        return self._client.table(self.table_name)

    async def _run(self, operation: Callable[[], T], *, action: str) -> T:
        """Execute a blocking Supabase call off the event loop."""
        try:
            return await asyncio.to_thread(operation)
        except Exception as exc:  # noqa: BLE001 — boundary: normalise every driver error
            logger.exception(
                'repository_error',
                repository=type(self).__name__,
                table=self.table_name,
                action=action,
                error=str(exc),
            )
            raise RepositoryError(f'{action} failed') from exc

    async def _fetch_all(self, query, *, action: str) -> list[dict[str, Any]]:
        result = await self._run(query.execute, action=action)
        return result.data or []

    async def _fetch_one(self, query, *, action: str) -> dict[str, Any] | None:
        rows = await self._fetch_all(query, action=action)
        return rows[0] if rows else None
