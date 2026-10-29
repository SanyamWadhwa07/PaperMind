"""Unit tests for `JobWorker` (backend/services/job_queue.py).

Exercises the worker in isolation from Supabase and the real pipeline: a
`FakeJobRepository` stands in for `JobRepository`, mirroring just enough of its
retry-vs-terminal semantics to make those assertions meaningful, and
`run_processing` is monkeypatched per test. `asyncio_mode = auto` (pytest.ini)
means async defs run as tests with no `@pytest.mark.asyncio` needed.
"""
from __future__ import annotations

import asyncio
import types

import pytest

import services.job_queue as job_queue
from services.paper_processing_service import ProcessingOutcome

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


class FakeJobRepository:
    """In-memory stand-in for `JobRepository`.

    `fail_for_retry` reimplements the real repository's terminal-vs-retry
    decision (attempts vs. max_attempts) rather than delegating anywhere, since
    the point of these tests is to pin down what `JobWorker` does with that
    decision, not to re-test the repository's SQL.
    """

    def __init__(self, job: dict) -> None:
        self.job = dict(job)
        self.calls: list[tuple] = []
        self.heartbeat_result = True

    async def heartbeat(self, job_id, worker_id, *, lease_seconds=900):
        self.calls.append(('heartbeat', job_id, worker_id))
        return self.heartbeat_result

    async def release(self, job_id, worker_id):
        self.calls.append(('release', job_id, worker_id))

    async def set_stage(self, job_id, worker_id, stage):
        self.calls.append(('set_stage', job_id, worker_id, stage))

    async def finish(self, job_id, worker_id, *, status, summary_id=None,
                      error_code=None, error_message=None):
        self.calls.append(('finish', status, summary_id, error_code))
        self.job.update(
            status=status, result_summary_id=summary_id,
            error_code=error_code, error_message=error_message,
        )

    async def fail_for_retry(self, job_id, worker_id, *, error_code, error_message):
        self.calls.append(('fail_for_retry', error_code))
        attempts = self.job.get('attempts', 0)
        max_attempts = self.job.get('max_attempts', 2)
        if attempts >= max_attempts:
            await self.finish(
                job_id, worker_id, status='failed',
                error_code=error_code, error_message=error_message,
            )
        else:
            self.job.update(
                status='queued', claimed_by=None,
                error_code=error_code, error_message=error_message,
            )


def make_job(**overrides) -> dict:
    job = {
        'id': 'job-1',
        'user_id': 'user-1',
        'source_type': 'upload',
        'source_path': '/tmp/does-not-exist.pdf',
        'display_title': 'Attention Is All You Need',
        'source_sha256': None,
        'attempts': 1,
        'max_attempts': 3,
    }
    job.update(overrides)
    return job


def make_worker(job: dict, *, lease_seconds: int = 900) -> tuple[job_queue.JobWorker, FakeJobRepository]:
    repo = FakeJobRepository(job)
    settings = types.SimpleNamespace(job_lease_seconds=lease_seconds, job_concurrency=1)
    worker = job_queue.JobWorker(repo, settings)  # type: ignore[arg-type]
    return worker, repo


# ── claim → run → finish ─────────────────────────────────────────────────────

async def test_run_one_succeeded_marks_finished(monkeypatch):
    job = make_job()
    worker, repo = make_worker(job)

    async def fake_run_processing(source, user_id, *, on_stage=None):
        if on_stage:
            await on_stage('extracting')
        return ProcessingOutcome(status='succeeded', summary_id='summary-1')

    monkeypatch.setattr(job_queue, 'run_processing', fake_run_processing)

    await worker._run_one(job)

    assert repo.job['status'] == 'succeeded'
    assert repo.job['result_summary_id'] == 'summary-1'
    assert ('finish', 'succeeded', 'summary-1', None) in repo.calls
    assert not any(call[0] == 'fail_for_retry' for call in repo.calls)


async def test_run_one_duplicate_marks_finished_as_duplicate(monkeypatch):
    job = make_job()
    worker, repo = make_worker(job)

    async def fake_run_processing(source, user_id, *, on_stage=None):
        return ProcessingOutcome(status='duplicate', existing_summary_id='existing-1')

    monkeypatch.setattr(job_queue, 'run_processing', fake_run_processing)

    await worker._run_one(job)

    assert repo.job['status'] == 'duplicate'
    assert repo.job['result_summary_id'] == 'existing-1'


# ── retry vs. terminal on max_attempts ───────────────────────────────────────

async def test_run_one_requeues_when_attempts_remain(monkeypatch):
    job = make_job(attempts=1, max_attempts=3)
    worker, repo = make_worker(job)

    async def fake_run_processing(source, user_id, *, on_stage=None):
        return ProcessingOutcome(
            status='failed', error_code='pipeline_error', error_message='boom',
        )

    monkeypatch.setattr(job_queue, 'run_processing', fake_run_processing)

    await worker._run_one(job)

    assert repo.job['status'] == 'queued'
    assert repo.job['claimed_by'] is None
    assert repo.job['error_code'] == 'pipeline_error'
    assert not any(call[0] == 'finish' for call in repo.calls)


async def test_run_one_marks_terminal_when_attempts_exhausted(monkeypatch):
    job = make_job(attempts=3, max_attempts=3)
    worker, repo = make_worker(job)

    async def fake_run_processing(source, user_id, *, on_stage=None):
        return ProcessingOutcome(
            status='failed', error_code='pipeline_error', error_message='boom',
        )

    monkeypatch.setattr(job_queue, 'run_processing', fake_run_processing)

    await worker._run_one(job)

    assert repo.job['status'] == 'failed'
    assert ('finish', 'failed', None, 'pipeline_error') in repo.calls


# ── split-brain guard ─────────────────────────────────────────────────────────

async def test_run_one_aborts_and_writes_nothing_when_lease_lost(monkeypatch):
    """The most important test in this file: if the heartbeat reports the
    lease was lost mid-run (another worker already reclaimed this job), the
    run must be cancelled and nothing may be written — writing a result here
    could race the new owner's insert for the same paper."""
    job = make_job()
    # Short lease so `_heartbeat_loop`'s `max(lease_seconds // 3, 5)` interval
    # doesn't dominate the test; `asyncio.sleep` is patched below to make even
    # that floor instant.
    worker, repo = make_worker(job, lease_seconds=15)
    repo.heartbeat_result = False  # simulates the reaper having reclaimed this job

    hang_forever = asyncio.Event()

    async def hanging_run_processing(source, user_id, *, on_stage=None):
        await hang_forever.wait()  # never resolves on its own — must be cancelled
        raise AssertionError('should have been cancelled before returning')

    monkeypatch.setattr(job_queue, 'run_processing', hanging_run_processing)

    real_sleep = asyncio.sleep

    async def instant_sleep(_seconds):
        await real_sleep(0)

    monkeypatch.setattr(job_queue.asyncio, 'sleep', instant_sleep)

    await worker._run_one(job)

    assert ('heartbeat', job['id'], job_queue.WORKER_ID) in repo.calls
    assert not any(call[0] in ('finish', 'fail_for_retry', 'release') for call in repo.calls)
    # The job row was never touched — no status/result written.
    assert repo.job == job


# ── shutdown releases in-flight jobs ─────────────────────────────────────────

async def test_run_one_cancellation_releases_the_job(monkeypatch):
    """Worker shutdown cancels `_run_one`'s own task. That must hand the job
    back via `release()` rather than leaving it claimed until its lease expires."""
    job = make_job()
    worker, repo = make_worker(job)

    hang_forever = asyncio.Event()

    async def hanging_run_processing(source, user_id, *, on_stage=None):
        await hang_forever.wait()

    monkeypatch.setattr(job_queue, 'run_processing', hanging_run_processing)

    task = asyncio.create_task(worker._run_one(job))
    # Let the task actually start and reach the `asyncio.wait(...)` inside
    # `_run_one` before cancelling it — cancelling before that would just
    # cancel the coroutine before it ever claimed to be "in flight".
    for _ in range(5):
        await asyncio.sleep(0)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert ('release', job['id'], job_queue.WORKER_ID) in repo.calls
    assert not any(call[0] in ('finish', 'fail_for_retry') for call in repo.calls)
