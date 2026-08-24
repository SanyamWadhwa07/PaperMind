"""Paper processing routes — PDF upload and arXiv fetch through the 7-agent pipeline.

The pipeline itself lives in `services/paper_processing_service.py`. These two
routes are the *deprecated, synchronous* entry points, kept for `evals/`, one-off
scripts and existing API callers. The application's own frontend uses
`POST /api/process/jobs*` instead (see `routes/process_jobs.py`): processing now
runs as a background job — see that module's docstring for why. These routes
still run the pipeline inline, holding the HTTP connection open for the whole
run, exactly as before; the only change here is that the pipeline body itself
moved out from under them.
"""

import asyncio
import sys
import tempfile
import time
import structlog
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, Request, Response
from fastapi.responses import JSONResponse
from werkzeug.utils import secure_filename

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from api.rate_limit import limit
from auth.dependencies import CurrentUser
from services.paper_processing_service import (
    MAX_PDF_PAGES,
    ProcessingSource,
    run_processing,
)

logger = structlog.get_logger(__name__)

router = APIRouter()

ALLOWED_EXTENSIONS = {'pdf'}
MAX_FILE_BYTES = 50 * 1024 * 1024  # 50 MB


def _allowed_file(filename: str) -> bool:
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def _validate_pdf_bytes(content: bytes) -> bool:
    return content[:5] == b'%PDF-'


def _outcome_to_response(outcome, *, not_found_msg: str) -> JSONResponse | None:
    """Shared translation from ProcessingOutcome to the legacy response shapes.

    Returns None for a 'succeeded' outcome — the caller builds the 201 body
    itself, since upload and arXiv historically differed in what they returned
    alongside `summary`.
    """
    if outcome.status == 'duplicate':
        return JSONResponse(status_code=409, content={
            'duplicate': True,
            'existing_id': outcome.existing_summary_id,
            'message': 'This paper already exists in your library',
        })
    if outcome.status == 'failed':
        if outcome.error_code in ('empty_summary', 'placeholder_summary', 'summary_too_short'):
            return JSONResponse(status_code=422, content={
                'error': outcome.error_message, 'reason': outcome.error_code,
            })
        if outcome.error_code == 'too_many_pages':
            return JSONResponse(status_code=400, content={'error': outcome.error_message})
        return JSONResponse(status_code=500, content={
            'error': outcome.error_message or not_found_msg,
        })
    return None


@router.post('/process/upload', status_code=201)
@limit('upload')
async def upload_and_process(
    request: Request,
    response: Response,  # receives the RateLimit-* headers
    current_user: CurrentUser,
    file: UploadFile = File(...),
):
    """Upload a PDF and run the 7-agent summarisation pipeline.

    Deprecated: prefer `POST /api/process/jobs`, which returns in well under a
    second and lets the frontend show progress instead of holding a connection
    open for minutes. Kept for `evals/run_benchmark.py`, one-off scripts, and
    `tests/api/test_routes.py`'s contract tests.

    Rate limited: these two routes are the only ones that run the full LLM
    pipeline, and they had no limit at all — so the buckets configured in
    `config/settings.py` for exactly this purpose were never applied, and one
    client could spend the whole shared provider quota in a loop.
    """
    user_id = current_user['user_id']

    if not _allowed_file(file.filename or ''):
        return JSONResponse(status_code=400, content={'error': 'Only PDF files are allowed'})

    content = await file.read()

    if len(content) > MAX_FILE_BYTES:
        return JSONResponse(status_code=413, content={'error': 'File exceeds 50 MB limit'})

    if not _validate_pdf_bytes(content):
        return JSONResponse(status_code=400, content={'error': 'File does not appear to be a valid PDF'})

    filename = secure_filename(file.filename or 'upload.pdf')
    # uuid4-prefixed, not the bare filename: two callers uploading files with the
    # same name at once used to write the same temp path, and whichever request's
    # `finally: unlink` ran first deleted the file the other one was still reading.
    from uuid import uuid4
    temp_path = Path(tempfile.gettempdir()) / f'{uuid4().hex}-{filename}'
    temp_path.write_bytes(content)

    try:
        start = time.time()
        source = ProcessingSource(
            kind='upload',
            pdf_path=temp_path,
            display_title=Path(filename).stem or filename,
        )
        outcome = await run_processing(source, user_id)
        processing_time = time.time() - start

        early = _outcome_to_response(outcome, not_found_msg='Failed to save summary')
        if early is not None:
            return early

        return {
            'message': 'Paper processed successfully',
            'summary_id': outcome.summary_id,
            'summary': outcome.summary,
            'processing_time': processing_time,
        }

    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except Exception:
            pass


@router.post('/process/arxiv', status_code=201)
@limit('upload')
async def process_from_arxiv(
    request: Request,
    response: Response,  # receives the RateLimit-* headers
    current_user: CurrentUser,
):
    """Fetch a paper from arXiv by ID and run the full summarisation pipeline.

    Deprecated: prefer `POST /api/process/jobs/arxiv`. See `upload_and_process`.
    """
    user_id = current_user['user_id']
    data = await request.json()
    arxiv_input = str(data.get('arxiv_id', '')).strip()

    if not arxiv_input:
        return JSONResponse(status_code=400, content={'error': 'arXiv ID or URL required'})

    import re
    match = re.search(r'(\d{4}\.\d{4,5}(?:v\d+)?)', arxiv_input)
    if not match:
        return JSONResponse(status_code=400, content={'error': 'Invalid arXiv ID format'})
    arxiv_id = match.group(1)

    import arxiv as arxiv_lib
    search = arxiv_lib.Search(id_list=[arxiv_id])
    client = arxiv_lib.Client()
    try:
        paper = await asyncio.to_thread(lambda: next(client.results(search), None))
    except arxiv_lib.HTTPError as e:
        # arXiv's own API rate-limits aggressively; without this the client
        # library's exception propagated as a bare, unexplained 500.
        logger.warning('arxiv_lookup_failed', arxiv_id=arxiv_id, error=str(e))
        return JSONResponse(
            status_code=502,
            content={'error': 'arXiv is temporarily unavailable or rate-limiting requests. Try again shortly.'},
        )

    if not paper:
        return JSONResponse(status_code=404, content={'error': 'Paper not found on arXiv'})

    import requests as _req
    from uuid import uuid4
    temp_path = Path(tempfile.gettempdir()) / f'{uuid4().hex}-{arxiv_id}.pdf'

    try:
        resp = await asyncio.to_thread(lambda: _req.get(paper.pdf_url, timeout=60))
        resp.raise_for_status()
        temp_path.write_bytes(resp.content)
    except Exception as e:
        logger.exception('arxiv_download_failed', arxiv_id=arxiv_id, error=str(e))
        return JSONResponse(status_code=502, content={'error': 'Failed to download PDF from arXiv'})

    try:
        start = time.time()
        source = ProcessingSource(
            kind='arxiv',
            pdf_path=temp_path,
            display_title=paper.title,
            arxiv_id=arxiv_id,
            paper_url=paper.pdf_url,
            authors=[a.name for a in paper.authors],
            abstract=paper.summary or '',
            published_date=(
                paper.published.strftime('%Y-%m-%d')
                if getattr(paper, 'published', None) else None
            ),
            primary_category=data.get('primary_category', getattr(paper, 'primary_category', None)),
        )
        outcome = await run_processing(source, user_id)
        processing_time = time.time() - start

        early = _outcome_to_response(outcome, not_found_msg='Failed to save summary')
        if early is not None:
            return early

        return {
            'message': 'Paper processed successfully',
            'summary_id': outcome.summary_id,
            'summary': outcome.summary,
            'processing_time': processing_time,
        }

    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except Exception:
            pass
