"""The background worker that drains `processing_jobs`.

One `JobWorker` runs per uvicorn process (started from `main_app.py`'s
`lifespan`). Coordination across the `WEB_CONCURRENCY` processes that
docker-compose/uvicorn may run is entirely Postgres's job: `claim_processing_job`
(migration 012) uses `FOR UPDATE SKIP LOCKED`, so two workers polling at once
simply never claim the same row — no lock, no leader election, no in-app state
shared between processes.

Concurrency *within* one process is a plain `asyncio.Semaphore`, acquired before
a claim and released when that job's run finishes — so a job a worker cannot yet
start stays visibly `queued` in the database rather than being claimed early and
piling up as pending asyncio tasks.

Split-brain safety: each run races the pipeline against its own heartbeat. If a
heartbeat call reports the lease was lost — the reaper already gave this job to
someone else, most likely because a health check or a slow LLM call outran the
lease — the run is cancelled and nothing is written. Two pipelines racing to
insert a summary row for the same paper is the failure mode this exists to rule
out entirely, not just make unlikely.
"""

from __future__ import annotations

import asyncio
import os
import socket
import time
import uuid
from pathlib import Path
from typing import Any, Optional

import structlog

from config import Settings, get_settings
from repositories.job_repository import JobRepository
from services.paper_processing_service import ProcessingSource, run_processing

logger = structlog.get_logger(__name__)

#: Identifies this process's worker in `claimed_by`. Unique per process start,
#: not per job — every job this process runs carries the same id.
WORKER_ID = f'{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}'

#: The running worker, if any — set by start_workers/cleared by stop_workers.
#: `api/health.py` reads this rather than reaching into `app.state`, since a
#: health check route only has `Request`/`app.state` for the app it's mounted
#: on and this keeps the two modules from needing to pass the instance around.
CURRENT_WORKER: Optional['JobWorker'] = None


class JobWorker:
    def __init__(self, repo: JobRepository, settings: Settings) -> None:
        self._repo = repo
        self._settings = settings
        self._sem = asyncio.Semaphore(max(settings.job_concurrency, 1))
        self._tasks: set[asyncio.Task] = set()
        self._loop_task: Optional[asyncio.Task] = None
        self._claims = 0
        self._last_claim_at: Optional[float] = None

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def start(self) -> None:
        self._loop_task = asyncio.create_task(self.run_forever(), name='job-worker-loop')

    async def stop(self) -> None:
        """Graceful shutdown: stop claiming, cancel in-flight runs, hand them back."""
        if self._loop_task is not None:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass

        in_flight = list(self._tasks)
        for task in in_flight:
            task.cancel()
        if in_flight:
            await asyncio.gather(*in_flight, return_exceptions=True)

    def snapshot(self) -> dict[str, Any]:
        """For /api/health — never used to gate readiness (see api/health.py)."""
        return {
            'worker_id': WORKER_ID,
            'in_flight': len(self._tasks),
            'concurrency': self._settings.job_concurrency,
            'total_claims': self._claims,
            'last_claim_at': self._last_claim_at,
        }

    # ── The poll/claim loop ──────────────────────────────────────────────────

    async def run_forever(self) -> None:
        interval = self._settings.job_poll_interval_seconds
        while True:
            # Block here, not after claiming — claiming first and gating on the
            # semaphore after would mark jobs 'running' in the database faster
            # than this process can actually start them, which is exactly the
            # "queued jobs disappear into memory instead of staying visible"
            # failure this whole design exists to avoid.
            await self._sem.acquire()

            try:
                job = await self._repo.claim(
                    WORKER_ID,
                    lease_seconds=self._settings.job_lease_seconds,
                    max_per_user=self._settings.job_max_per_user,
                )
            except Exception as exc:
                logger.warning('job_claim_failed', error=str(exc))
                job = None

            if job is None:
                self._sem.release()
                # Small jitter so two processes polling on the same interval
                # don't lock-step into claiming at the same instant every time.
                jitter = (hash((WORKER_ID, time.monotonic())) % 1000) / 1000.0
                await asyncio.sleep(interval + jitter * 0.5)
                continue

            self._claims += 1
            self._last_claim_at = time.time()

            task = asyncio.create_task(self._run_one(job), name=f'job-{job["id"]}')
            self._tasks.add(task)
            task.add_done_callback(self._on_task_done)

    def _on_task_done(self, task: asyncio.Task) -> None:
        self._tasks.discard(task)
        self._sem.release()
        exc = task.exception() if not task.cancelled() else None
        if exc is not None:
            logger.error('job_task_unhandled_exception', error=str(exc))

    # ── Running one job ──────────────────────────────────────────────────────

    async def _run_one(self, job: dict[str, Any]) -> None:
        job_id = job['id']
        user_id = job['user_id']

        try:
            source = await self._build_source(job)
        except Exception as exc:
            logger.warning('job_source_build_failed', job_id=job_id, error=str(exc))
            await self._repo.fail_for_retry(
                job_id, WORKER_ID, error_code='source_unavailable', error_message=str(exc),
            )
            self._cleanup_source(job)
            return

        lease_lost = asyncio.Event()

        async def _heartbeat_loop() -> None:
            interval = max(self._settings.job_lease_seconds // 3, 5)
            while True:
                await asyncio.sleep(interval)
                ok = await self._repo.heartbeat(
                    job_id, WORKER_ID, lease_seconds=self._settings.job_lease_seconds,
                )
                if not ok:
                    lease_lost.set()
                    return

        async def on_stage(stage: str) -> None:
            try:
                await self._repo.set_stage(job_id, WORKER_ID, stage)
            except Exception:
                pass  # a missed stage label isn't worth failing the job over

        hb_task = asyncio.create_task(_heartbeat_loop())
        run_task = asyncio.create_task(run_processing(source, user_id, on_stage=on_stage))

        try:
            await asyncio.wait({run_task, hb_task}, return_when=asyncio.FIRST_COMPLETED)

            if lease_lost.is_set():
                # The reaper already reassigned this job — writing a result now
                # could race a second worker's insert for the same paper. Abort
                # without persisting anything; the job's new owner will finish
                # or fail it.
                run_task.cancel()
                await asyncio.gather(run_task, return_exceptions=True)
                logger.warning('job_lease_lost_mid_run', job_id=job_id, worker_id=WORKER_ID)
                return

            outcome = await run_task
        except asyncio.CancelledError:
            # Worker shutdown: hand the job back rather than making the caller
            # (or the next poller) wait out the full lease for work that isn't
            # actually happening anymore.
            run_task.cancel()
            await asyncio.gather(run_task, return_exceptions=True)
            try:
                await self._repo.release(job_id, WORKER_ID)
            except Exception:
                pass
            raise
        finally:
            hb_task.cancel()
            try:
                await hb_task
            except (asyncio.CancelledError, Exception):
                pass
            self._cleanup_source(job)

        if outcome.status == 'succeeded':
            await self._repo.finish(
                job_id, WORKER_ID, status='succeeded', summary_id=outcome.summary_id,
            )
        elif outcome.status == 'duplicate':
            await self._repo.finish(
                job_id, WORKER_ID, status='duplicate', summary_id=outcome.existing_summary_id,
                error_code='duplicate',
                error_message='This paper already exists in your library.',
            )
        else:
            await self._repo.fail_for_retry(
                job_id, WORKER_ID,
                error_code=outcome.error_code or 'unknown',
                error_message=outcome.error_message or 'Processing failed.',
            )

    async def _build_source(self, job: dict[str, Any]) -> ProcessingSource:
        if job['source_type'] == 'upload':
            return ProcessingSource(
                kind='upload',
                pdf_path=Path(job['source_path']),
                display_title=job['display_title'],
                sha256=job.get('source_sha256'),
            )

        # arXiv: the enqueue route only resolved metadata far enough to get a
        # display title and rule out "paper doesn't exist" synchronously — the
        # download itself happens here, in the worker, where a slow or failing
        # fetch is a job retry rather than a held-open HTTP connection.
        import arxiv as arxiv_lib

        arxiv_id = job['arxiv_id']
        search = arxiv_lib.Search(id_list=[arxiv_id])
        client = arxiv_lib.Client()
        paper = await asyncio.to_thread(lambda: next(client.results(search), None))
        if paper is None:
            raise RuntimeError(f'arXiv:{arxiv_id} no longer resolves')

        import requests as _req

        dest = Path(job['source_path'])
        dest.parent.mkdir(parents=True, exist_ok=True)
        resp = await asyncio.to_thread(lambda: _req.get(paper.pdf_url, timeout=60))
        resp.raise_for_status()
        await asyncio.to_thread(dest.write_bytes, resp.content)

        return ProcessingSource(
            kind='arxiv',
            pdf_path=dest,
            display_title=paper.title,
            arxiv_id=arxiv_id,
            paper_url=paper.pdf_url,
            authors=[a.name for a in paper.authors],
            abstract=paper.summary or '',
            published_date=(
                paper.published.strftime('%Y-%m-%d')
                if getattr(paper, 'published', None) else None
            ),
            primary_category=getattr(paper, 'primary_category', None),
        )

    def _cleanup_source(self, job: dict[str, Any]) -> None:
        source_path = job.get('source_path')
        if not source_path:
            return
        try:
            Path(source_path).unlink(missing_ok=True)
        except OSError as exc:
            logger.debug('job_source_cleanup_failed', job_id=job.get('id'), error=str(exc))


# ── Lifespan wiring (backend/main_app.py) ───────────────────────────────────

def start_workers(app) -> None:
    global CURRENT_WORKER

    settings = get_settings()
    if not settings.job_worker_enabled:
        logger.info('job_worker_disabled')
        return

    try:
        from db import get_supabase
        client = get_supabase()
    except Exception as exc:
        logger.warning('job_worker_start_skipped', reason='supabase_unavailable', error=str(exc))
        return

    repo = JobRepository(client)
    worker = JobWorker(repo, settings)
    worker.start()
    app.state.job_worker = worker
    CURRENT_WORKER = worker
    logger.info(
        'job_worker_started', worker_id=WORKER_ID, concurrency=settings.job_concurrency,
    )


async def stop_workers(app) -> None:
    global CURRENT_WORKER

    worker = getattr(app.state, 'job_worker', None)
    if worker is None:
        return
    await worker.stop()
    CURRENT_WORKER = None
    logger.info('job_worker_stopped', worker_id=WORKER_ID)
