"""Persistence for paper summaries."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from .base import BaseRepository

SORTABLE_COLUMNS = frozenset(
    {'created_at', 'paper_title', 'processing_time_seconds', 'word_count'}
)


class SummaryRepository(BaseRepository):
    table_name = 'summaries'

    async def list_for_user(
        self,
        user_id: str,
        *,
        offset: int,
        limit: int,
        sort_by: str = 'created_at',
        descending: bool = True,
        search: str = '',
    ) -> tuple[list[dict[str, Any]], int]:
        """Return one page of a user's summaries plus the total row count."""
        if sort_by not in SORTABLE_COLUMNS:
            sort_by = 'created_at'

        query = self.table.select('*', count='exact').eq('user_id', user_id)
        if search:
            escaped = search.replace('%', r'\%').replace(',', ' ')
            query = query.or_(
                f'paper_title.ilike.%{escaped}%,arxiv_id.ilike.%{escaped}%'
            )
        query = query.order(sort_by, desc=descending).range(offset, offset + limit - 1)

        result = await self._run(query.execute, action='list_for_user')
        return result.data or [], (result.count or 0)

    async def get_owned(self, summary_id: str, user_id: str) -> dict[str, Any] | None:
        """Fetch a summary only if it belongs to `user_id` (authorisation at the query)."""
        query = self.table.select('*').eq('id', summary_id).eq('user_id', user_id)
        return await self._fetch_one(query, action='get_owned')

    async def exists_owned(self, summary_id: str, user_id: str) -> bool:
        query = self.table.select('id').eq('id', summary_id).eq('user_id', user_id)
        return await self._fetch_one(query, action='exists_owned') is not None

    async def get_many_owned(
        self, summary_ids: list[str], user_id: str
    ) -> list[dict[str, Any]]:
        query = self.table.select('*').in_('id', summary_ids).eq('user_id', user_id)
        return await self._fetch_all(query, action='get_many_owned')

    async def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = await self._run(
            lambda: self.table.insert(payload).execute(), action='create'
        )
        rows = result.data or []
        return rows[0] if rows else {}

    async def delete_owned(self, summary_id: str, user_id: str) -> bool:
        """Delete scoped by user_id so a stale id cannot remove another user's row."""
        result = await self._run(
            lambda: self.table.delete()
            .eq('id', summary_id)
            .eq('user_id', user_id)
            .execute(),
            action='delete_owned',
        )
        return bool(result.data)

    async def created_since(
        self, user_id: str, *, days: int
    ) -> list[dict[str, Any]]:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        query = (
            self.table.select('created_at')
            .eq('user_id', user_id)
            .gte('created_at', cutoff)
        )
        return await self._fetch_all(query, action='created_since')

    async def find_by_arxiv_id(
        self, arxiv_id: str, user_id: str
    ) -> dict[str, Any] | None:
        query = (
            self.table.select('*').eq('arxiv_id', arxiv_id).eq('user_id', user_id)
        )
        return await self._fetch_one(query, action='find_by_arxiv_id')
