"""Persistence for the async paper-processing queue.

See `backend/database/migrations/012_processing_jobs.sql` for the table and the
`claim_processing_job` / `heartbeat_processing_job` / `release_processing_job`
RPCs this repository wraps. Fencing (`claimed_by`) is enforced at the SQL level
in every write below — a worker whose lease was reaped by another worker's
claim cannot silently overwrite that worker's job.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from .base import BaseRepository, RepositoryError


class JobRepository(BaseRepository):
    table_name = 'processing_jobs'

    async def enqueue(self, job: dict[str, Any]) -> dict[str, Any] | None:
        """Insert a new job. Returns None on a duplicate-active-job conflict.

        The partial unique index on (user_id, dedupe_key) WHERE status IN
        ('queued', 'running') is what makes this possible to detect cheaply —
        the database rejects the insert rather than the caller needing to
        check-then-insert (which races anyway).
        """
        try:
            from postgrest.exceptions import APIError
        except ImportError:  # pragma: no cover - postgrest always present in prod
            APIError = ()  # type: ignore[assignment]

        try:
            result = await asyncio.to_thread(
                lambda: self.table.insert(job).execute()
            )
        except APIError as exc:
            if getattr(exc, 'code', None) == '23505':  # unique_violation
                return None
            raise RepositoryError('enqueue failed') from exc
        except Exception as exc:  # noqa: BLE001 — boundary
            raise RepositoryError('enqueue failed') from exc

        rows = result.data or []
        return rows[0] if rows else None

    async def find_active_by_dedupe(
        self, user_id: str, dedupe_key: str
    ) -> dict[str, Any] | None:
        query = (
            self.table.select('*')
            .eq('user_id', user_id)
            .eq('dedupe_key', dedupe_key)
            .in_('status', ['queued', 'running'])
        )
        return await self._fetch_one(query, action='find_active_by_dedupe')

    # ── Worker-side lifecycle (all fenced by claimed_by at the SQL level) ──────

    async def claim(
        self, worker_id: str, *, lease_seconds: int = 900, max_per_user: int = 2,
    ) -> dict[str, Any] | None:
        result = await self._run(
            lambda: self._client.rpc('claim_processing_job', {
                'p_worker_id': worker_id,
                'p_lease_seconds': lease_seconds,
                'p_max_per_user': max_per_user,
            }).execute(),
            action='claim',
        )
        rows = result.data or []
        return rows[0] if rows else None

    async def heartbeat(
        self, job_id: str, worker_id: str, *, lease_seconds: int = 900,
    ) -> bool:
        result = await self._run(
            lambda: self._client.rpc('heartbeat_processing_job', {
                'p_job_id': job_id,
                'p_worker_id': worker_id,
                'p_lease_seconds': lease_seconds,
            }).execute(),
            action='heartbeat',
        )
        return bool(result.data)

    async def release(self, job_id: str, worker_id: str) -> None:
        await self._run(
            lambda: self._client.rpc('release_processing_job', {
                'p_job_id': job_id, 'p_worker_id': worker_id,
            }).execute(),
            action='release',
        )

    async def set_stage(self, job_id: str, worker_id: str, stage: str) -> None:
        await self._run(
            lambda: self.table.update({'stage': stage})
            .eq('id', job_id).eq('claimed_by', worker_id).eq('status', 'running')
            .execute(),
            action='set_stage',
        )

    async def finish(
        self,
        job_id: str,
        worker_id: str,
        *,
        status: str,
        summary_id: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        """Mark a job terminal: 'succeeded' | 'failed' | 'duplicate' | 'cancelled'."""
        payload: dict[str, Any] = {
            'status': status,
            'stage': status,
            'finished_at': datetime.now(timezone.utc).isoformat(),
            'result_summary_id': summary_id,
            'error_code': error_code,
            'error_message': error_message,
        }
        await self._run(
            lambda: self.table.update(payload)
            .eq('id', job_id).eq('claimed_by', worker_id)
            .execute(),
            action='finish',
        )

    async def fail_for_retry(
        self, job_id: str, worker_id: str, *, error_code: str, error_message: str,
    ) -> None:
        """A run failed but may still have attempts left.

        Reads the row first because whether this is terminal depends on
        attempts vs. max_attempts, which the claim RPC already incremented —
        this repository doesn't re-decide retry policy, it just reflects it.
        """
        job = await self.get_any(job_id)
        if job is None:
            return
        if job.get('attempts', 0) >= job.get('max_attempts', 2):
            await self.finish(
                job_id, worker_id, status='failed',
                error_code=error_code, error_message=error_message,
            )
        else:
            await self._run(
                lambda: self.table.update({
                    'status': 'queued',
                    'stage': 'queued',
                    'claimed_by': None,
                    'lease_expires_at': None,
                    'error_code': error_code,
                    'error_message': error_message,
                }).eq('id', job_id).eq('claimed_by', worker_id).execute(),
                action='fail_for_retry',
            )

    async def get_any(self, job_id: str) -> dict[str, Any] | None:
        """Fetch by id with no ownership check — worker-internal use only."""
        query = self.table.select('*').eq('id', job_id)
        return await self._fetch_one(query, action='get_any')

    # ── User-facing reads/writes ────────────────────────────────────────────────

    async def list_for_user(
        self, user_id: str, *, active_only: bool = False,
        since_hours: int = 24, limit: int = 50,
    ) -> list[dict[str, Any]]:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=since_hours)).isoformat()
        query = (
            self.table.select('*')
            .eq('user_id', user_id)
            .is_('dismissed_at', 'null')
        )
        if active_only:
            query = query.in_('status', ['queued', 'running'])
        else:
            query = query.gte('created_at', cutoff)
        query = query.order('created_at', desc=True).limit(limit)
        return await self._fetch_all(query, action='list_for_user')

    async def get(self, job_id: str, user_id: str) -> dict[str, Any] | None:
        query = self.table.select('*').eq('id', job_id).eq('user_id', user_id)
        return await self._fetch_one(query, action='get')

    async def cancel(self, job_id: str, user_id: str) -> bool:
        """Cancel a job that hasn't started yet. False if it's already running/terminal."""
        result = await self._run(
            lambda: self.table.update({
                'status': 'cancelled', 'stage': 'cancelled',
                'finished_at': datetime.now(timezone.utc).isoformat(),
            })
            .eq('id', job_id).eq('user_id', user_id).eq('status', 'queued')
            .execute(),
            action='cancel',
        )
        return bool(result.data)

    async def dismiss(self, job_id: str, user_id: str) -> None:
        await self._run(
            lambda: self.table.update({
                'dismissed_at': datetime.now(timezone.utc).isoformat(),
            }).eq('id', job_id).eq('user_id', user_id).execute(),
            action='dismiss',
        )

    async def count_open_for_user(self, user_id: str) -> int:
        result = await self._run(
            lambda: self.table.select('id', count='exact')
            .eq('user_id', user_id).in_('status', ['queued', 'running']).execute(),
            action='count_open_for_user',
        )
        return result.count or 0
