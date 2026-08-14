"""Paper processing routes — PDF upload and arXiv fetch through the 7-agent pipeline."""

import asyncio
import sys
import time
import structlog
from datetime import datetime, timezone
from pathlib import Path
import tempfile
from uuid import uuid4

from fastapi import APIRouter, UploadFile, File, Request, Response
from fastapi.responses import JSONResponse
from werkzeug.utils import secure_filename
from db import supabase as _shared_supabase

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from api.errors import UnprocessableError
from api.rate_limit import limit
from auth.dependencies import CurrentUser
from core.agent_integration import AgentPaperProcessor
from backend.main import load_config

logger = structlog.get_logger(__name__)

router = APIRouter()
supabase = _shared_supabase

ALLOWED_EXTENSIONS = {'pdf'}
MAX_PDF_PAGES = 200
MAX_FILE_BYTES = 50 * 1024 * 1024  # 50 MB

# Attempts for the one write that matters. See _insert_summary_with_retry.
_SAVE_ATTEMPTS = 4


async def _insert_summary_with_retry(record: dict) -> list:
    """Insert the finished summary, retrying on transport failures.

    This insert sits at the end of two to four minutes of PDF extraction and LLM
    calls, and it was a single unguarded attempt. Any blip on the socket at that
    exact moment discarded the entire run: the user waited minutes, the free-tier
    quota was spent, and the response was a 500 with nothing saved.

    Observed in practice as `WinError 10013` from httpx, where a security product
    briefly refused an outbound socket during a burst of concurrent requests. It
    cleared on its own seconds later, which is precisely the case a retry covers.

    Only transport-level errors are retried. A rejection from PostgREST (a
    constraint violation, a bad column) will fail identically every time, so it
    is raised on the first attempt rather than after four.
    """
    last_error: Exception | None = None

    for attempt in range(_SAVE_ATTEMPTS):
        try:
            result = await asyncio.to_thread(
                lambda: supabase.table('summaries').insert(record).execute()
            )
            if attempt:
                logger.info('summary_insert_recovered', attempt=attempt)
            return result.data
        except Exception as e:
            # postgrest raises APIError for anything the server actually
            # answered; those are deterministic and not worth repeating.
            if type(e).__name__ == 'APIError':
                raise
            last_error = e
            logger.warning(
                'summary_insert_attempt_failed',
                attempt=attempt, error=str(e)[:200], error_type=type(e).__name__,
            )
            if attempt < _SAVE_ATTEMPTS - 1:
                await asyncio.sleep(2 ** attempt)

    logger.error('summary_insert_failed', attempts=_SAVE_ATTEMPTS, error=str(last_error)[:300])
    raise last_error  # type: ignore[misc]


def _allowed_file(filename: str) -> bool:
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def _validate_pdf_bytes(content: bytes) -> bool:
    return content[:5] == b'%PDF-'


async def _validate_pdf_page_count(path: str) -> bool:
    try:
        import fitz
        def _check():
            doc = fitz.open(path)
            count = doc.page_count
            doc.close()
            return count <= MAX_PDF_PAGES
        return await asyncio.to_thread(_check)
    except Exception:
        return True  # allow if we can't check


async def _run_agent_pipeline(pdf_path: str) -> dict:
    """Run the 7-agent orchestrator on a PDF, returning the structured result."""
    config = load_config(None)
    processor = AgentPaperProcessor(config=config)
    try:
        return await processor.process_paper(pdf_path)
    finally:
        await processor.cleanup()


async def _process_pdf_cached(pdf_bytes: bytes, pdf_path: str) -> dict:
    """Run the pipeline, reusing a cached result for a byte-identical PDF.

    Processing a paper costs minutes of wall time and a chunk of a free-tier
    daily request quota, so re-uploading the same file — a re-run, a second user
    with the same paper, a batch retry — should not pay for it twice. Keyed on
    the PDF's SHA-256, so a different file can never hit the same entry.

    Cache unavailability is not an error: without Redis this is exactly the
    previous behaviour.
    """
    from core.pipeline.processing_cache import cache_result, get_cached_result

    cached = await asyncio.to_thread(get_cached_result, pdf_bytes)
    if cached:
        logger.info('processing_cache_hit', pdf_path=pdf_path)
        return cached

    result = await _run_agent_pipeline(pdf_path)

    # Only cache results worth replaying. Caching a failed run would pin the
    # failure for the full TTL, and the save gate would reject it every time.
    try:
        _reject_degenerate_summary(result)
    except UnprocessableError:
        return result

    await asyncio.to_thread(cache_result, pdf_bytes, result)
    return result


async def _store_figures(summary_result: dict) -> None:
    """Upload extracted figure images and swap temp paths for public URLs.

    Done before the row is written so the persisted record never contains a
    path into a temp directory that is about to be deleted. Keyed by a fresh
    UUID rather than the summary id, which does not exist until after insert.
    """
    figures = summary_result.get('figures') or []
    if not figures:
        return
    try:
        from services.figure_storage import FigureStorage
        storage = FigureStorage(supabase)
        summary_result['figures'] = await storage.attach_urls(str(uuid4()), figures)
    except Exception as e:
        # Figures are an enhancement, not the paper. Losing the images should
        # not lose the summary — but strip the dead temp paths regardless.
        logger.warning('figure_storage_failed', error=str(e))
        summary_result['figures'] = [
            {k: v for k, v in f.items() if k != 'path'} for f in figures
        ]


async def _persist_entities(summary_id: str, user_id: str, summary_result: dict) -> None:
    """Write entity co-occurrence pairs to entity_relationships for knowledge graph."""
    entities = summary_result.get('entities', {})
    typed_entities = (
        [('model',    m) for m in (entities.get('models', []) or [])[:15]]
        + [('dataset', d) for d in (entities.get('datasets', []) or [])[:15]]
        + [('metric',  m) for m in (entities.get('metrics', []) or [])[:10]]
        + [('task',    t) for t in (entities.get('tasks', []) or [])[:10]]
    )

    rows = []
    seen: set[tuple[str, str]] = set()
    for i, (type_a, name_a) in enumerate(typed_entities):
        for type_b, name_b in typed_entities[i + 1:]:
            key = (min(name_a, name_b), max(name_a, name_b))
            if key in seen:
                continue
            seen.add(key)
            rows.append({
                'entity_a':          name_a,
                'entity_a_type':     type_a,
                'entity_b':          name_b,
                'entity_b_type':     type_b,
                'relationship_type': 'co-occurs',
                'frequency_count':   1,
                'confidence_score':  0.7,
                'source_paper_id':   summary_id,
                'user_id':           user_id,
            })

    if rows:
        try:
            await asyncio.to_thread(
                lambda: supabase.table('entity_relationships')
                .upsert(rows, on_conflict='entity_a,entity_b,source_paper_id')
                .execute()
            )
            logger.info('entity_relationships_saved', count=len(rows), summary_id=summary_id)
        except Exception as e:
            logger.warning('entity_persist_failed', error=str(e), summary_id=summary_id)


async def _post_save_tasks(new_id: str, user_id: str, summary_result: dict) -> None:
    """Best-effort post-save: similarity cache + citations + lineage + entity graph."""
    # Drop the user's cached corpus views first. A new paper changes every one of
    # them, and leaving them cached means the paper the user just watched process
    # is absent from Explore and Timeline — which reads as the upload failing.
    from api.response_cache import invalidate_user
    invalidate_user(user_id)

    # Similarity cache
    try:
        from core.knowledge.graph_service import compute_and_cache_similarity
        await asyncio.to_thread(compute_and_cache_similarity, new_id, user_id, supabase)
    except Exception as e:
        logger.warning('similarity_cache_failed', error=str(e), summary_id=new_id)

    # Citation extraction + lineage
    try:
        from core.knowledge.citation_extractor import (
            extract_citations, extract_citation_contexts, match_arxiv_ids_to_library
        )
        from core.knowledge.lineage_service import (
            infer_lineage_from_citations, infer_lineage_from_similarity
        )
        ref_text = summary_result.get('sections', {}).get('__references__', '')
        if ref_text:
            full_text = ' '.join(summary_result.get('sections', {}).values())
            citations = extract_citations(ref_text)
            citations = extract_citation_contexts(full_text, citations)
            citations = match_arxiv_ids_to_library(citations, supabase, user_id)
            citation_rows = [
                {
                    'source_summary_id': new_id,
                    'cited_arxiv_id':    c.get('cited_arxiv_id'),
                    'cited_title':       c.get('cited_title'),
                    'year':              c.get('year'),
                    'confidence':        c.get('confidence', 0.7),
                }
                for c in citations[:100]
            ]
            if citation_rows:
                await asyncio.to_thread(
                    lambda: supabase.table('paper_citations').insert(citation_rows).execute()
                )
            await asyncio.to_thread(infer_lineage_from_citations, new_id, citations, supabase)
            await asyncio.to_thread(infer_lineage_from_similarity, new_id, supabase)
    except Exception as e:
        logger.warning('citation_lineage_failed', error=str(e), summary_id=new_id)

    # Entity relationships for knowledge graph
    await _persist_entities(new_id, user_id, summary_result)

    # Persist intelligence analysis rows
    await _persist_intelligence(new_id, user_id, summary_result)

    # Enrich GitHub links detected by ReproducibilityAgent
    await _enrich_github_links(new_id, summary_result)


async def _persist_intelligence(summary_id: str, user_id: str, summary_result: dict) -> None:
    """Save research gaps, reproducibility, and ablation data to paper_intelligence table."""
    rows = []
    intelligence_map = {
        'gaps': summary_result.get('research_gaps', {}),
        'reproducibility': summary_result.get('reproducibility', {}),
        'ablation': {'ablation_studies': summary_result.get('ablation_studies', [])},
    }
    for analysis_type, data in intelligence_map.items():
        if data:
            rows.append({
                'summary_id': summary_id,
                'user_id': user_id,
                'analysis_type': analysis_type,
                'analysis_data': data,
                'confidence_score': data.get('confidence', None),
            })
    if rows:
        try:
            await asyncio.to_thread(
                lambda: supabase.table('paper_intelligence')
                .upsert(rows, on_conflict='summary_id,analysis_type')
                .execute()
            )
            logger.info('intelligence_saved', count=len(rows), summary_id=summary_id)
        except Exception as e:
            logger.warning('intelligence_persist_failed', error=str(e), summary_id=summary_id)


async def _enrich_github_links(summary_id: str, summary_result: dict) -> None:
    """Enrich GitHub links extracted by ReproducibilityAgent."""
    links = summary_result.get('reproducibility', {}).get('github_links', [])
    if not links:
        return
    try:
        from core.knowledge.github_service import enrich_github_links
        enriched = await asyncio.to_thread(enrich_github_links, links)
        rows = [
            {
                'summary_id': summary_id,
                'repo_url': item['repo_url'],
                'repo_owner': item.get('repo_owner'),
                'repo_name': item.get('repo_name'),
                'is_active': item.get('is_active'),
                'readme_summary': item.get('readme_summary'),
                'stars': item.get('stars'),
            }
            for item in enriched
        ]
        if rows:
            await asyncio.to_thread(
                lambda: supabase.table('paper_github_links')
                .upsert(rows, on_conflict='summary_id,repo_url')
                .execute()
            )
    except Exception as e:
        logger.warning('github_enrich_failed', error=str(e), summary_id=summary_id)


# Sentinel strings earlier versions of the pipeline persisted as real summaries.
_PLACEHOLDER_SUMMARIES = (
    'summary generation in progress',
    'summary unavailable',
    'analysis complete. see extracted data for details.',
    'this paper presents a novel approach to the problem.',
)

# Below this, a "summary" is a failure wearing a summary's clothes. The graph
# engine targets 300-450 words; the legacy path ~350.
_MIN_SUMMARY_WORDS = 60


def _reject_degenerate_summary(summary_result: dict) -> None:
    """Refuse to persist a summary that records a failure as a success.

    The pipeline degrades toward plausible-looking output on almost every error
    path, so without this check a rate-limited or crashed run is saved as a
    normal paper and returned as 201 Created. Raising here surfaces the failure
    to the user instead of storing it.
    """
    summaries = summary_result.get('summaries') or {}
    main = ''
    if isinstance(summaries, dict):
        main = next((v for v in summaries.values() if isinstance(v, str) and v.strip()), '')
    elif isinstance(summaries, str):
        main = summaries

    main = main.strip()
    if not main:
        raise UnprocessableError(
            'The summarisation pipeline produced no summary for this paper.',
            details={'reason': 'empty_summary',
                     'pipeline_status': summary_result.get('pipeline_status', {})},
        )

    normalised = main.lower().rstrip('.') + '.'
    if any(normalised.startswith(p) for p in _PLACEHOLDER_SUMMARIES):
        raise UnprocessableError(
            'The summarisation pipeline failed and produced placeholder text.',
            details={'reason': 'placeholder_summary',
                     'pipeline_status': summary_result.get('pipeline_status', {})},
        )

    word_count = len(main.split())
    if word_count < _MIN_SUMMARY_WORDS:
        raise UnprocessableError(
            f'The summarisation pipeline produced only {word_count} words, which '
            'indicates a failed or rate-limited run rather than a real summary.',
            details={'reason': 'summary_too_short', 'word_count': word_count,
                     'pipeline_status': summary_result.get('pipeline_status', {})},
        )


def _build_summary_record(user_id: str, summary_result: dict,
                           paper_title: str, paper_authors: list,
                           paper_url: str | None, arxiv_id: str | None,
                           processing_time: float,
                           extra: dict | None = None) -> dict:
    """Assemble the DB row for the summaries table."""
    _reject_degenerate_summary(summary_result)
    quality_score = summary_result.get('agent_metadata', {}).get('summary_quality')
    record = {
        'user_id':                  user_id,
        'paper_title':              paper_title,
        'paper_authors':            paper_authors,
        'paper_url':                paper_url,
        'arxiv_id':                 arxiv_id,
        'summary_data': {
            'summaries':       summary_result.get('summaries', {}),
            'key_findings':    summary_result.get('key_findings', []),
            'methodology':     summary_result.get('methodology', {}),
            'results':         summary_result.get('results', {}),
            'datasets':        summary_result.get('datasets', []),
            'models':          summary_result.get('models', []),
            'metrics':         summary_result.get('metrics', []),
            'tasks':           summary_result.get('tasks', []),
            'entities': {
                'datasets': summary_result.get('datasets', []),
                'models':   summary_result.get('models', []),
                'metrics':  summary_result.get('metrics', []),
                'tasks':    summary_result.get('tasks', []),
            },
            'figures':          summary_result.get('figures', []),
            'tables':           summary_result.get('tables', []),
            'sections_found':   summary_result.get('sections_found', []),
            'section_count':    summary_result.get('section_count', 0),
            'section_summaries': summary_result.get('section_summaries', {}),
            'contributions':    summary_result.get('contributions', []),
            'methods_detail':   summary_result.get('methods_detail', ''),
            'experimental_setup': summary_result.get('experimental_setup', ''),
            'typed_entities':   summary_result.get('typed_entities', {}),
            'limitations':      summary_result.get('limitations', []),
            'future_work':      summary_result.get('future_work', []),
            'agent_metadata':   summary_result.get('agent_metadata', {}),
            # New intelligence pipeline outputs
            'research_gaps':    summary_result.get('research_gaps', {}),
            'ablation_studies': summary_result.get('ablation_studies', []),
            'reproducibility':  summary_result.get('reproducibility', {}),
            # Per-stage outcome so the UI can distinguish "nothing found" from
            # "this stage failed".
            'pipeline_status':  summary_result.get('pipeline_status', {}),
        },
        'model_used':               summary_result.get('agent_metadata', {}).get('llm_backend', 'ollama'),
        'processing_time_seconds':  round(processing_time, 2),
        'word_count':               len(next(iter(summary_result.get('summaries', {}).values()), '').split()),
        'quality_score':            quality_score,
        'created_at':               datetime.now(timezone.utc).isoformat(),
    }
    if extra:
        record.update(extra)
    return record


@router.post('/process/upload', status_code=201)
@limit('upload')
async def upload_and_process(
    request: Request,
    response: Response,  # slowapi writes X-RateLimit-* headers here
    current_user: CurrentUser,
    file: UploadFile = File(...),
):
    """Upload a PDF and run the 7-agent summarisation pipeline.

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
    temp_path = Path(tempfile.gettempdir()) / filename
    temp_path.write_bytes(content)

    try:
        if not await _validate_pdf_page_count(str(temp_path)):
            return JSONResponse(
                status_code=400,
                content={'error': f'PDF exceeds {MAX_PDF_PAGES} page limit'}
            )

        start = time.time()
        summary_result = await _process_pdf_cached(content, str(temp_path))
        processing_time = time.time() - start

        # Duplicate detection via pgvector
        abstract_text = summary_result.get('sections', {}).get('abstract', '')
        embedding_list = None
        try:
            from core.knowledge.embedding_service import embed_paper
            embedding = await asyncio.to_thread(
                lambda: embed_paper(
                    title=summary_result.get('title', filename),
                    abstract=abstract_text,
                    keywords=summary_result.get('models', []) + summary_result.get('datasets', []),
                )
            )
            dup_result = await asyncio.to_thread(
                lambda: supabase.rpc('find_duplicate_papers', {
                    'p_embedding': embedding.tolist(),
                    'p_user_id': user_id,
                    'p_threshold': 0.95,
                }).execute()
            )
            if dup_result.data:
                return JSONResponse(status_code=409, content={
                    'duplicate': True,
                    'existing_id': dup_result.data[0]['id'],
                    'message': 'This paper already exists in your library',
                })
            embedding_list = embedding.tolist()
        except Exception as e:
            logger.warning('embedding_failed', error=str(e), filename=filename)

        # The extractor leaves title empty when page-1 layout was inconclusive;
        # the uploaded filename is then the most honest label available.
        # (`.get('title', filename)` would not do this — the key is always present.)
        extracted_title = (summary_result.get('title') or '').strip()
        await _store_figures(summary_result)

        record = _build_summary_record(
            user_id=user_id,
            summary_result=summary_result,
            paper_title=extracted_title or Path(filename).stem or filename,
            paper_authors=summary_result.get('authors', []) or [],
            paper_url=None,
            arxiv_id=summary_result.get('arxiv_id'),
            processing_time=processing_time,
            extra={'abstract_text': abstract_text[:2000]},
        )
        if embedding_list:
            record['embedding'] = embedding_list

        saved = await _insert_summary_with_retry(record)
        if not saved:
            return JSONResponse(status_code=500, content={'error': 'Failed to save summary'})

        new_id = saved[0]['id']

        # Activity log (non-critical)
        try:
            await asyncio.to_thread(
                lambda: supabase.table('user_activity').insert({
                    'user_id':       user_id,
                    'activity_type': 'summarize',
                    'activity_data': {
                        'summary_id':      new_id,
                        'paper_title':     record['paper_title'],
                        'processing_time': processing_time,
                    },
                    'created_at': datetime.now(timezone.utc).isoformat(),
                }).execute()
            )
        except Exception as e:
            logger.warning('activity_log_failed', error=str(e))

        # Post-save tasks (similarity, citations, entities — all best-effort)
        asyncio.create_task(_post_save_tasks(new_id, user_id, summary_result))

        return {
            'message': 'Paper processed successfully',
            'summary_id': new_id,
            'summary': saved[0],
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
    response: Response,  # slowapi writes X-RateLimit-* headers here
    current_user: CurrentUser,
):
    """Fetch a paper from arXiv by ID and run the full summarisation pipeline."""
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
    temp_path = Path(tempfile.gettempdir()) / f"{arxiv_id}.pdf"

    try:
        resp = await asyncio.to_thread(lambda: _req.get(paper.pdf_url, timeout=60))
        resp.raise_for_status()
        temp_path.write_bytes(resp.content)
    except Exception as e:
        logger.exception('arxiv_download_failed', arxiv_id=arxiv_id, error=str(e))
        return JSONResponse(status_code=502, content={'error': 'Failed to download PDF from arXiv'})

    try:
        start = time.time()
        summary_result = await _run_agent_pipeline(str(temp_path))
        processing_time = time.time() - start

        # Duplicate detection
        embedding_list = None
        try:
            from core.knowledge.embedding_service import embed_paper
            embedding = await asyncio.to_thread(
                lambda: embed_paper(
                    title=paper.title,
                    abstract=paper.summary or '',
                    keywords=summary_result.get('models', []) + summary_result.get('datasets', []),
                )
            )
            dup_result = await asyncio.to_thread(
                lambda: supabase.rpc('find_duplicate_papers', {
                    'p_embedding': embedding.tolist(),
                    'p_user_id': user_id,
                    'p_threshold': 0.95,
                }).execute()
            )
            if dup_result.data:
                return JSONResponse(status_code=409, content={
                    'duplicate': True,
                    'existing_id': dup_result.data[0]['id'],
                    'message': 'This paper already exists in your library',
                })
            embedding_list = embedding.tolist()
        except Exception as e:
            logger.warning('embedding_failed', error=str(e), arxiv_id=arxiv_id)

        await _store_figures(summary_result)

        record = _build_summary_record(
            user_id=user_id,
            summary_result=summary_result,
            paper_title=paper.title,
            paper_authors=[a.name for a in paper.authors],
            paper_url=paper.pdf_url,
            arxiv_id=arxiv_id,
            processing_time=processing_time,
            extra={
                'abstract_text':    (paper.summary or '')[:2000],
                'published_date':   paper.published.strftime('%Y-%m-%d') if getattr(paper, 'published', None) else None,
                'primary_category': data.get('primary_category', getattr(paper, 'primary_category', None)),
            },
        )
        record['summary_data']['abstract_original'] = paper.summary
        if embedding_list:
            record['embedding'] = embedding_list

        saved = await _insert_summary_with_retry(record)
        if not saved:
            return JSONResponse(status_code=500, content={'error': 'Failed to save summary'})

        new_id = saved[0]['id']

        try:
            await asyncio.to_thread(
                lambda: supabase.table('user_activity').insert({
                    'user_id':       user_id,
                    'activity_type': 'summarize',
                    'activity_data': {
                        'summary_id':      new_id,
                        'paper_title':     paper.title,
                        'arxiv_id':        arxiv_id,
                        'processing_time': processing_time,
                    },
                    'created_at': datetime.now(timezone.utc).isoformat(),
                }).execute()
            )
        except Exception as e:
            logger.warning('activity_log_failed', error=str(e))

        asyncio.create_task(_post_save_tasks(new_id, user_id, summary_result))

        return {
            'message': 'Paper processed successfully',
            'summary_id': new_id,
            'summary': saved[0],
            'processing_time': processing_time,
        }

    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except Exception:
            pass
