"""The paper-processing pipeline body, extracted from `routes/process_paper.py`.

This used to live entirely inside the two HTTP handlers (`upload_and_process`,
`process_from_arxiv`), which is why processing a paper held an HTTP connection
open for the full multi-minute pipeline. `run_processing()` is the same pipeline
with the HTTP concerns removed: it takes a `ProcessingSource` instead of a
`Request`, reports progress through an `on_stage` callback instead of nothing,
and returns a `ProcessingOutcome` instead of raising or building a `JSONResponse`
— so it can be called equally from the synchronous (deprecated) route handlers
and from `services/job_queue.py`'s background worker, which must never see an
HTTP-shaped exception.

Kept identical to the original route code wherever the behaviour doesn't need to
change for that reason. Three places it does:

1. `UnprocessableError` (a degenerate/placeholder summary) becomes a returned
   `ProcessingOutcome(status='failed', ...)` rather than a raised exception —
   the honesty guard in `_reject_degenerate_summary` keeps its full force, only
   the translation at the boundary changes.
2. A pgvector near-duplicate hit becomes `status='duplicate'` with
   `existing_summary_id` rather than a `JSONResponse(409, ...)`.
3. `_post_save_tasks` is awaited rather than fired with a bare
   `asyncio.create_task` and discarded. The bare task held no strong reference,
   so it could be garbage-collected mid-flight; awaiting it also means a job
   isn't reported `succeeded` until `invalidate_user()` has actually run, so the
   dashboard is never stale by the time the tray says "done".
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Literal, Optional

import structlog
from db import supabase as _shared_supabase

from api.errors import UnprocessableError
from backend.main import load_config
from core.agent_integration import AgentPaperProcessor

logger = structlog.get_logger(__name__)

supabase = _shared_supabase

# Attempts for the one write that matters. See _insert_summary_with_retry.
_SAVE_ATTEMPTS = 4

MAX_PDF_PAGES = 200


# ── Public contract ─────────────────────────────────────────────────────────

@dataclass(slots=True)
class ProcessingSource:
    """What run_processing needs, independent of whether it came from an
    upload or an arXiv fetch — the two differ only in how this gets built."""

    kind: Literal['upload', 'arxiv']
    pdf_path: Path
    display_title: str
    sha256: Optional[str] = None
    arxiv_id: Optional[str] = None
    paper_url: Optional[str] = None
    authors: list[str] = field(default_factory=list)
    # arXiv's own abstract/metadata — unavailable for an upload, where the
    # extractor's own abstract section stands in.
    abstract: Optional[str] = None
    published_date: Optional[str] = None
    primary_category: Optional[str] = None


@dataclass(slots=True)
class ProcessingOutcome:
    status: Literal['succeeded', 'duplicate', 'failed']
    summary_id: Optional[str] = None
    summary: Optional[dict[str, Any]] = None
    existing_summary_id: Optional[str] = None
    processing_time: float = 0.0
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    # The extractor's own recovered title, when better than what the caller
    # already knew (e.g. an upload's filename) — lets the job's display_title
    # be corrected once the real one is known.
    paper_title: Optional[str] = None


OnStage = Optional[Callable[[str], Awaitable[None]]]


async def run_processing(
    source: ProcessingSource,
    user_id: str,
    *,
    on_stage: OnStage = None,
) -> ProcessingOutcome:
    async def _stage(name: str) -> None:
        if on_stage is not None:
            await on_stage(name)

    if not await _validate_pdf_page_count(str(source.pdf_path)):
        return ProcessingOutcome(
            status='failed', error_code='too_many_pages',
            error_message=f'PDF exceeds {MAX_PDF_PAGES} page limit',
        )

    await _stage('extracting')
    start = time.time()

    try:
        pdf_bytes = await asyncio.to_thread(source.pdf_path.read_bytes)
        summary_result = await _process_pdf_cached(pdf_bytes, str(source.pdf_path))
    except Exception as e:
        logger.exception('pipeline_run_failed', error=str(e), source_kind=source.kind)
        return ProcessingOutcome(
            status='failed', error_code='pipeline_error', error_message=str(e),
        )

    processing_time = time.time() - start

    # Duplicate detection via pgvector. Needs the extracted abstract, so it can
    # only run post-extraction — the pre-flight sha256/arxiv_id check at enqueue
    # time (backend/routes/process_jobs.py) catches the common case for free;
    # this one catches a near-duplicate that isn't byte- or id-identical.
    abstract_text = source.abstract or summary_result.get('sections', {}).get('abstract', '')
    embedding_list: Optional[list[float]] = None
    try:
        from core.knowledge.embedding_service import embed_paper
        embedding = await asyncio.to_thread(
            lambda: embed_paper(
                title=source.display_title,
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
            return ProcessingOutcome(
                status='duplicate',
                existing_summary_id=dup_result.data[0]['id'],
                processing_time=processing_time,
            )
        embedding_list = embedding.tolist()
    except Exception as e:
        logger.warning('embedding_failed', error=str(e), source_kind=source.kind)

    await _stage('saving')

    # The extractor leaves title empty when page-1 layout was inconclusive; the
    # caller's own display title (filename, or arXiv's) is then the most honest
    # label available. (`.get('title', source.display_title)` would not do
    # this — the key is always present, just possibly empty.)
    extracted_title = (summary_result.get('title') or '').strip()
    paper_title = extracted_title or source.display_title
    paper_authors = source.authors or summary_result.get('authors', []) or []

    try:
        record = _build_summary_record(
            user_id=user_id,
            summary_result=summary_result,
            paper_title=paper_title,
            paper_authors=paper_authors,
            paper_url=source.paper_url,
            arxiv_id=source.arxiv_id,
            processing_time=processing_time,
            extra={
                'abstract_text': (abstract_text or '')[:2000],
                'source_sha256': source.sha256,
                **({'published_date': source.published_date} if source.published_date else {}),
                **({'primary_category': source.primary_category} if source.primary_category else {}),
            },
        )
    except UnprocessableError as e:
        # The honesty guard: a degenerate or placeholder "summary" must not be
        # saved and returned as a success. A worker loop must never see an
        # HTTP-shaped exception, so this is the one place that catches it and
        # translates it into an outcome instead.
        reason = (e.details or {}).get('reason', 'unprocessable')
        return ProcessingOutcome(
            status='failed', error_code=reason, error_message=e.message,
            processing_time=processing_time,
        )

    if source.abstract:
        record['summary_data']['abstract_original'] = source.abstract
    if embedding_list:
        record['embedding'] = embedding_list

    saved = await _insert_summary_with_retry(record)
    if not saved:
        return ProcessingOutcome(
            status='failed', error_code='save_failed',
            error_message='Failed to save summary', processing_time=processing_time,
        )

    new_id = saved[0]['id']

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

    await _stage('analysing')
    # Awaited, not fired-and-forgotten: a bare asyncio.create_task here held no
    # strong reference (the previous code's actual bug — nothing kept it alive,
    # so the event loop's garbage collector could reap it mid-flight) and meant
    # the response returned before invalidate_user() had necessarily run, so a
    # client polling right after could still see a stale corpus. Now the job
    # isn't 'succeeded' until this has actually finished.
    await _post_save_tasks(new_id, user_id, summary_result)

    return ProcessingOutcome(
        status='succeeded',
        summary_id=new_id,
        summary=saved[0],
        processing_time=processing_time,
        paper_title=paper_title,
    )


# ── Validation ───────────────────────────────────────────────────────────────

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


# ── Pipeline execution + caching ────────────────────────────────────────────

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
    with the same paper, a batch retry, or (now) an arXiv re-import that used to
    skip this cache entirely — should not pay for it twice. Keyed on the PDF's
    SHA-256, so a different file can never hit the same entry.

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

    # Figures must be uploaded — and their temp `path`s swapped for public
    # `image_url`s — before the result is cached, not after. This cache entry is
    # served verbatim to the next byte-identical upload, possibly from a
    # different process or a fresh container where the original temp files no
    # longer exist. Caching the raw pipeline output meant every cache hit
    # rendered every figure caption-only, permanently and silently: the check
    # in figure_storage.py just found nothing at the stale path and moved on.
    await _store_figures(result, hashlib.sha256(pdf_bytes).hexdigest())

    await asyncio.to_thread(cache_result, pdf_bytes, result)
    return result


async def _store_figures(summary_result: dict, storage_key: str) -> None:
    """Upload extracted figure images and swap temp paths for public URLs.

    Done before the row is written so the persisted record never contains a
    path into a temp directory that is about to be deleted. `storage_key` is the
    PDF's content hash rather than the summary id (which does not exist until
    after insert) — a stable key means bucket objects stay reconcilable with the
    paper that produced them, and a re-run of the same PDF upserts over its own
    objects instead of orphaning a fresh UUID's worth every time.
    """
    figures = summary_result.get('figures') or []
    if not figures:
        return
    source_paths = [f.get('path') for f in figures if f.get('path')]
    try:
        from services.figure_storage import FigureStorage
        storage = FigureStorage(supabase)
        # attach_urls builds *new* records carrying `image_url` and already
        # strips `path`; it does not mutate `figures`. Rebinding
        # summary_result['figures'] to anything derived from the original list
        # after this point silently throws every uploaded URL away — which is
        # exactly what the old `finally` block did on the success path, making
        # every figure render caption-only. Only the failure path re-projects.
        summary_result['figures'] = await storage.attach_urls(storage_key, figures)
    except Exception as e:
        # Figures are an enhancement, not the paper. Losing the images should
        # not lose the summary — but strip the dead temp paths regardless.
        logger.warning('figure_storage_failed', error=str(e))
        summary_result['figures'] = [
            {k: v for k, v in f.items() if k != 'path'} for f in figures
        ]
    finally:
        # The extractor writes each figure PNG to a scratch location (a
        # papermind_extract/<hash>-<uuid> workdir, or a NamedTemporaryFile on the
        # legacy path) that nothing else ever cleans up. Once the upload attempt
        # above has run — succeeded or not — the local file has served its only
        # purpose, so remove it here rather than let it accumulate on disk for
        # the life of the container.
        for path in source_paths:
            try:
                Path(path).unlink(missing_ok=True)
            except OSError as exc:
                logger.debug('figure_temp_cleanup_failed', path=path, error=str(exc))


# ── Post-save enrichment (similarity, citations, entities, intelligence) ────

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


# ── Save gate ────────────────────────────────────────────────────────────────

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
    normal paper and returned as a success. Raising here surfaces the failure
    to the caller instead of storing it — run_processing() converts this into a
    failed ProcessingOutcome rather than letting it propagate as an exception.
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
        record.update({k: v for k, v in extra.items() if v is not None})
    return record


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
