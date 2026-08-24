"""Enqueue and track background paper-processing jobs.

Paper processing used to run inside the HTTP request: `POST /api/process/upload`
held a connection open for the whole 7-agent pipeline (minutes), during which
the frontend replaced its entire input UI with a progress panel faked on
`setTimeout`s, and queueing a second paper meant firing a second full pipeline
run with no coordination — burning through a shared free-tier LLM quota with no
limit.

These routes just write a row and return — see
`backend/database/migrations/012_processing_jobs.sql` for the table and
`backend/services/job_queue.py` for the worker that claims and runs it. The
frontend polls `GET /process/jobs` (see `frontend/src/lib/processingStore.js`)
to drive a persistent notification tray instead.

`/api/queue/*` is already taken by `routes/reading_queue.py` (a human reading
list), hence `/api/process/jobs`.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

import structlog
from fastapi import APIRouter, File, Query, Request, Response, UploadFile
from fastapi.responses import JSONResponse
from werkzeug.utils import secure_filename

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from api.deps import JobRepoDep, SettingsDep, SummaryRepoDep
from api.rate_limit import limit
from auth.dependencies import CurrentUser
from schemas import ArxivBatchJobRequest, ArxivJobRequest
from services.paper_processing_service import (
    MAX_PDF_PAGES,
    _validate_pdf_page_count,
)

logger = structlog.get_logger(__name__)
router = APIRouter()

ALLOWED_EXTENSIONS = {'pdf'}
MAX_FILE_BYTES = 50 * 1024 * 1024  # 50 MB

#: Client-side sanity cap on a batch; the real limit that actually protects the
#: shared LLM quota is job_max_queued_per_user, enforced below.
MAX_BATCH = 10


def _allowed_file(filename: str) -> bool:
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def _validate_pdf_bytes(content: bytes) -> bool:
    return content[:5] == b'%PDF-'


def _job_public(job: dict[str, Any]) -> dict[str, Any]:
    """Trim a job row to what the client needs — never leak source_path, which
    is a server-local filesystem path."""
    return {
        'id': job['id'],
        'source_type': job['source_type'],
        'arxiv_id': job.get('arxiv_id'),
        'display_title': job['display_title'],
        'status': job['status'],
        'stage': job['stage'],
        'priority': job['priority'],
        'batch_id': job.get('batch_id'),
        'attempts': job['attempts'],
        'result_summary_id': job.get('result_summary_id'),
        'error_code': job.get('error_code'),
        'error_message': job.get('error_message'),
        'created_at': job['created_at'],
        'started_at': job.get('started_at'),
        'finished_at': job.get('finished_at'),
    }


async def _stage_dir(settings: SettingsDep) -> Path:
    d = Path(settings.upload_dir) / 'jobs'
    d.mkdir(parents=True, exist_ok=True)
    return d


async def _check_queue_depth(jobs: JobRepoDep, settings: SettingsDep, user_id: str) -> Optional[JSONResponse]:
    open_count = await jobs.count_open_for_user(user_id)
    if open_count >= settings.job_max_queued_per_user:
        return JSONResponse(status_code=429, content={
            'error': {
                'code': 'queue_full',
                'message': (
                    f'You have {open_count} papers already queued or processing '
                    f'(limit {settings.job_max_queued_per_user}). Wait for some to '
                    'finish, or cancel ones you no longer need.'
                ),
            },
        })
    return None


# ── Enqueue ──────────────────────────────────────────────────────────────────

@router.post('/process/jobs', status_code=202)
@limit('upload')
async def enqueue_upload(
    request: Request,
    response: Response,  # receives the RateLimit-* headers
    current_user: CurrentUser,
    jobs: JobRepoDep,
    summaries: SummaryRepoDep,
    settings: SettingsDep,
    file: UploadFile = File(...),
):
    user_id = current_user['user_id']

    if not _allowed_file(file.filename or ''):
        return JSONResponse(status_code=400, content={'error': 'Only PDF files are allowed'})

    content = await file.read()
    if len(content) > MAX_FILE_BYTES:
        return JSONResponse(status_code=413, content={'error': 'File exceeds 50 MB limit'})
    if not _validate_pdf_bytes(content):
        return JSONResponse(status_code=400, content={'error': 'File does not appear to be a valid PDF'})

    depth_error = await _check_queue_depth(jobs, settings, user_id)
    if depth_error:
        return depth_error

    sha256 = hashlib.sha256(content).hexdigest()

    existing = await summaries.find_by_sha256(sha256, user_id)
    if existing:
        return JSONResponse(status_code=409, content={
            'duplicate': True, 'existing_id': existing['id'],
            'message': 'This paper already exists in your library',
        })

    filename = secure_filename(file.filename or 'upload.pdf')
    job_id = uuid4()

    # Named by job id, not by the uploaded filename — two callers uploading
    # "paper.pdf" at once used to collide on the same temp path under the old
    # synchronous route (backend/routes/process_paper.py's now-deprecated
    # handlers), and it also has to outlive this request and be reachable from
    # a future worker container mounting the same volume.
    staged = (await _stage_dir(settings)) / f'{job_id}.pdf'
    staged.write_bytes(content)

    if not await _validate_pdf_page_count(str(staged)):
        staged.unlink(missing_ok=True)
        return JSONResponse(
            status_code=400,
            content={'error': f'PDF exceeds {MAX_PDF_PAGES} page limit'},
        )

    job = await jobs.enqueue({
        'id': str(job_id),
        'user_id': user_id,
        'source_type': 'upload',
        'source_path': str(staged),
        'source_sha256': sha256,
        'original_filename': filename,
        'display_title': Path(filename).stem or filename,
        'priority': 0,
        'dedupe_key': f'sha256:{sha256}',
    })

    if job is None:
        # The partial unique index rejected the insert: this exact paper is
        # already queued or running for this user.
        staged.unlink(missing_ok=True)
        active = await jobs.find_active_by_dedupe(user_id, f'sha256:{sha256}')
        return JSONResponse(status_code=409, content={
            'duplicate': True,
            'job_id': active['id'] if active else None,
            'message': 'This paper is already queued or processing',
        })

    return {'job': _job_public(job)}


@router.post('/process/jobs/arxiv', status_code=202)
@limit('upload')
async def enqueue_arxiv(
    request: Request,
    response: Response,  # receives the RateLimit-* headers
    body: ArxivJobRequest,
    current_user: CurrentUser,
    jobs: JobRepoDep,
    summaries: SummaryRepoDep,
    settings: SettingsDep,
):
    user_id = current_user['user_id']
    arxiv_id = body.arxiv_id

    depth_error = await _check_queue_depth(jobs, settings, user_id)
    if depth_error:
        return depth_error

    existing = await summaries.find_by_arxiv_id(arxiv_id, user_id)
    if existing:
        return JSONResponse(status_code=409, content={
            'duplicate': True, 'existing_id': existing['id'],
            'message': 'This paper already exists in your library',
        })

    # Resolved synchronously, not in the worker: the tray needs the real title
    # on the same click, and "not found on arXiv" should be a 404 the user sees
    # now rather than a job that turns red three minutes later. Costs about a
    # second. Only a definite "doesn't exist" is answered here, though — arXiv
    # rate-limits aggressively, and a transient HTTPError still enqueues (with a
    # placeholder title) so a slow arXiv doesn't block queueing at all; the
    # worker resolves metadata for real when it runs (see job_queue.py).
    display_title = f'arXiv:{arxiv_id}'
    try:
        import arxiv as arxiv_lib
        import asyncio

        search = arxiv_lib.Search(id_list=[arxiv_id])
        client = arxiv_lib.Client()
        paper = await asyncio.to_thread(lambda: next(client.results(search), None))
        if paper is None:
            return JSONResponse(status_code=404, content={'error': 'Paper not found on arXiv'})
        display_title = paper.title
    except Exception as e:
        logger.warning('arxiv_enqueue_lookup_failed', arxiv_id=arxiv_id, error=str(e))

    job_id = uuid4()
    staged_path = (await _stage_dir(settings)) / f'{job_id}.pdf'  # worker downloads here

    job = await jobs.enqueue({
        'id': str(job_id),
        'user_id': user_id,
        'source_type': 'arxiv',
        'arxiv_id': arxiv_id,
        'source_path': str(staged_path),
        'display_title': display_title,
        'priority': body.priority,
        'dedupe_key': f'arxiv:{arxiv_id}',
    })

    if job is None:
        active = await jobs.find_active_by_dedupe(user_id, f'arxiv:{arxiv_id}')
        return JSONResponse(status_code=409, content={
            'duplicate': True,
            'job_id': active['id'] if active else None,
            'message': 'This paper is already queued or processing',
        })

    return {'job': _job_public(job)}


@router.post('/process/jobs/reprocess/{summary_id}', status_code=202)
@limit('upload')
async def reprocess_paper(
    request: Request,
    response: Response,  # receives the RateLimit-* headers
    summary_id: str,
    current_user: CurrentUser,
    jobs: JobRepoDep,
    summaries: SummaryRepoDep,
    settings: SettingsDep,
):
    """Re-run the pipeline on a paper already in the library.

    Only works for arXiv-sourced papers — an upload's original PDF is deleted
    once the worker finishes with it (`JobWorker._cleanup_source`), so there's
    no source left to re-run for those; an arXiv id can always be re-fetched.

    The existing summary is deleted up front, not replaced atomically once the
    new run succeeds — the same trade every other regenerate action in this
    app already makes (see peer review's `?force=true`). A failed reprocess
    loses the old copy; that's judged an acceptable risk for "this came out
    wrong, try again" rather than building the machinery to hold both copies
    until one succeeds.
    """
    user_id = current_user['user_id']
    existing = await summaries.get_owned(summary_id, user_id)
    if existing is None:
        return JSONResponse(status_code=404, content={'error': 'Summary not found'})

    arxiv_id = existing.get('arxiv_id')
    if not arxiv_id:
        return JSONResponse(status_code=400, content={
            'error': "This paper wasn't imported from arXiv, so there's no source "
                     "file left to reprocess it from. Delete it and re-upload the "
                     "PDF instead.",
        })

    depth_error = await _check_queue_depth(jobs, settings, user_id)
    if depth_error:
        return depth_error

    await summaries.delete_owned(summary_id, user_id)

    job_id = uuid4()
    staged_path = (await _stage_dir(settings)) / f'{job_id}.pdf'

    job = await jobs.enqueue({
        'id': str(job_id),
        'user_id': user_id,
        'source_type': 'arxiv',
        'arxiv_id': arxiv_id,
        'source_path': str(staged_path),
        'display_title': existing.get('paper_title') or f'arXiv:{arxiv_id}',
        'priority': 0,
        'dedupe_key': f'arxiv:{arxiv_id}',
    })

    if job is None:
        # Vanishingly unlikely immediately after the delete above, but the
        # dedupe index is still real — surface it rather than dropping silently.
        active = await jobs.find_active_by_dedupe(user_id, f'arxiv:{arxiv_id}')
        return JSONResponse(status_code=409, content={
            'duplicate': True,
            'job_id': active['id'] if active else None,
            'message': 'This paper is already queued or processing',
        })

    return {'job': _job_public(job)}


@router.post('/process/jobs/batch', status_code=202)
@limit('upload')
async def enqueue_batch(
    request: Request,
    response: Response,  # receives the RateLimit-* headers
    body: ArxivBatchJobRequest,
    current_user: CurrentUser,
    jobs: JobRepoDep,
    summaries: SummaryRepoDep,
    settings: SettingsDep,
):
    """Enqueue up to MAX_BATCH arXiv papers under one batch_id.

    Partial success is the normal case here — some ids will already be in the
    library, some may already be queued — so this never fails the whole call
    for one bad id; it reports per-id outcomes instead.
    """
    user_id = current_user['user_id']
    arxiv_ids = body.arxiv_ids[:MAX_BATCH]
    batch_id = uuid4()

    enqueued: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    for arxiv_id in arxiv_ids:
        depth_error = await _check_queue_depth(jobs, settings, user_id)
        if depth_error:
            rejected.append({'arxiv_id': arxiv_id, 'reason': 'queue_full'})
            continue

        existing = await summaries.find_by_arxiv_id(arxiv_id, user_id)
        if existing:
            rejected.append({'arxiv_id': arxiv_id, 'reason': 'already_in_library',
                              'existing_id': existing['id']})
            continue

        job_id = uuid4()
        staged_path = (await _stage_dir(settings)) / f'{job_id}.pdf'
        job = await jobs.enqueue({
            'id': str(job_id),
            'user_id': user_id,
            'source_type': 'arxiv',
            'arxiv_id': arxiv_id,
            'source_path': str(staged_path),
            'display_title': f'arXiv:{arxiv_id}',
            'priority': 10,  # behind interactive single-paper jobs
            'batch_id': str(batch_id),
            'dedupe_key': f'arxiv:{arxiv_id}',
        })
        if job is None:
            rejected.append({'arxiv_id': arxiv_id, 'reason': 'already_queued'})
            continue
        enqueued.append(_job_public(job))

    return {
        'batch_id': str(batch_id),
        'jobs': enqueued,
        'rejected': rejected,
    }


# ── Status ───────────────────────────────────────────────────────────────────

@router.get('/process/jobs')
async def list_jobs(
    current_user: CurrentUser,
    jobs: JobRepoDep,
    active: bool = Query(False),
    since_hours: int = Query(24, ge=1, le=168),
):
    user_id = current_user['user_id']
    rows = await jobs.list_for_user(user_id, active_only=active, since_hours=since_hours)
    return {'jobs': [_job_public(j) for j in rows]}


@router.get('/process/jobs/{job_id}')
async def get_job(job_id: str, current_user: CurrentUser, jobs: JobRepoDep):
    user_id = current_user['user_id']
    job = await jobs.get(job_id, user_id)
    if job is None:
        return JSONResponse(status_code=404, content={'error': 'Job not found'})
    return {'job': _job_public(job)}


@router.delete('/process/jobs/{job_id}', status_code=204)
async def remove_job(job_id: str, current_user: CurrentUser, jobs: JobRepoDep):
    """Cancel a queued job, or dismiss a terminal one from the tray.

    A *running* job can't be cancelled here — cooperative cancellation would
    need to thread through every agent in the pipeline, and a running job
    finishes in a couple of minutes regardless. That case answers 409.
    """
    user_id = current_user['user_id']
    job = await jobs.get(job_id, user_id)
    if job is None:
        return JSONResponse(status_code=404, content={'error': 'Job not found'})

    if job['status'] == 'queued':
        await jobs.cancel(job_id, user_id)
        return Response(status_code=204)

    if job['status'] == 'running':
        return JSONResponse(status_code=409, content={
            'error': 'This job is already running and cannot be cancelled. '
                     'It will finish shortly.',
        })

    await jobs.dismiss(job_id, user_id)
    return Response(status_code=204)
