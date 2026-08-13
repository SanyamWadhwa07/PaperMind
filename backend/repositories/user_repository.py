"""Persistence for user accounts and activity."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .base import BaseRepository


class UserRepository(BaseRepository):
    table_name = 'users'

    async def get_by_email(self, email: str) -> dict[str, Any] | None:
        query = self.table.select('*').eq('email', email.strip().lower())
        return await self._fetch_one(query, action='get_by_email')

    async def get_by_id(self, user_id: str) -> dict[str, Any] | None:
        query = self.table.select(
            'id, email, full_name, bio, avatar_url, created_at, last_login'
        ).eq('id', user_id)
        return await self._fetch_one(query, action='get_by_id')

    async def get_credentials(self, email: str) -> dict[str, Any] | None:
        """Password hash included — only for the login path."""
        query = self.table.select('id, email, password_hash, full_name').eq(
            'email', email.strip().lower()
        )
        return await self._fetch_one(query, action='get_credentials')

    async def get_by_reset_token(self, token: str) -> dict[str, Any] | None:
        if not token:
            return None
        query = self.table.select('id, email, reset_token_expires').eq(
            'reset_token', token
        )
        return await self._fetch_one(query, action='get_by_reset_token')

    async def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = await self._run(
            lambda: self.table.insert(payload).execute(), action='create'
        )
        rows = result.data or []
        return rows[0] if rows else {}

    async def update(self, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        result = await self._run(
            lambda: self.table.update(payload).eq('id', user_id).execute(),
            action='update',
        )
        rows = result.data or []
        return rows[0] if rows else {}

    async def touch_last_login(self, user_id: str) -> None:
        await self._run(
            lambda: self.table.update(
                {'last_login': datetime.now(timezone.utc).isoformat()}
            )
            .eq('id', user_id)
            .execute(),
            action='touch_last_login',
        )


class ActivityRepository(BaseRepository):
    table_name = 'user_activity'

    async def record(
        self, user_id: str, activity_type: str, metadata: dict[str, Any] | None = None
    ) -> None:
        await self._run(
            lambda: self.table.insert(
                {
                    'user_id': user_id,
                    'activity_type': activity_type,
                    'activity_data': metadata or {},
                    'created_at': datetime.now(timezone.utc).isoformat(),
                }
            ).execute(),
            action='record',
        )

    async def recent(self, user_id: str, limit: int = 10) -> list[dict[str, Any]]:
        query = (
            self.table.select('*')
            .eq('user_id', user_id)
            .order('created_at', desc=True)
            .limit(limit)
        )
        return await self._fetch_all(query, action='recent')


class StatsRepository(BaseRepository):
    """Per-user summary counters.

    Aggregates over `summaries` in Python rather than reading the
    `user_summary_stats` view from schema.sql. The view is optional — a database
    provisioned from migrations alone does not have it, and PostgREST answers a
    missing relation with an error, which turned the whole dashboard into a 503.
    The row counts here are one user's papers, so aggregating client-side costs
    nothing and removes a deployment-order dependency.
    """

    table_name = 'summaries'

    async def for_user(self, user_id: str) -> dict[str, Any]:
        query = self.table.select(
            'processing_time_seconds, word_count, created_at, '
            'summary_data->num_words_original'
        ).eq('user_id', user_id)
        rows = await self._fetch_all(query, action='for_user')

        if not rows:
            return {
                'total_summaries': 0,
                'avg_processing_time': 0.0,
                'total_words_processed': 0,
                'last_summary_date': None,
                'active_days': 0,
            }

        times = [
            float(r['processing_time_seconds'])
            for r in rows
            if r.get('processing_time_seconds') is not None
        ]
        # The length of the *paper*, which is what "words read" means. The
        # `word_count` column holds the length of the generated summary, so
        # summing it reported three papers as 771 words read — the size of the
        # output, not the input. It stays as the fallback for rows written
        # before the pipeline recorded the original length.
        words = sum(
            int(r.get('num_words_original') or r.get('word_count') or 0)
            for r in rows
        )
        dates = [str(r.get('created_at') or '') for r in rows if r.get('created_at')]

        return {
            'total_summaries': len(rows),
            'avg_processing_time': (sum(times) / len(times)) if times else 0.0,
            'total_words_processed': words,
            'last_summary_date': max(dates) if dates else None,
            # A "day" is the date part of the timestamp — same definition the
            # view used via DATE(created_at).
            'active_days': len({d[:10] for d in dates}),
        }
