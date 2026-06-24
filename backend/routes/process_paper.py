"""Paper processing routes — PDF upload and arXiv fetch through the 7-agent pipeline."""

import asyncio
import sys
import time
import structlog
from datetime import datetime
from pathlib import Path
import tempfile

from fastapi import APIRouter, UploadFile, File, Request
from fastapi.responses import JSONResponse
from werkzeug.utils import secure_filename
from supabase import create_client

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from database.config import SUPABASE_URL, SUPABASE_SERVICE_KEY
from auth.dependencies import CurrentUser
from core.agent_integration import AgentPaperProcessor
from backend.main import load_config, load_patterns

logger = structlog.get_logger(__name__)

router = APIRouter()
supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

ALLOWED_EXTENSIONS = {'pdf'}
MAX_PDF_PAGES = 200
MAX_FILE_BYTES = 50 * 1024 * 1024  # 50 MB


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
    patterns = load_patterns('patterns.json')
    processor = AgentPaperProcessor(patterns=patterns, config=config)
    try:
        return await processor.process_paper(pdf_path)
    finally:
        await processor.cleanup()


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


def _build_summary_record(user_id: str, summary_result: dict,
                           paper_title: str, paper_authors: list,
                           paper_url: str | None, arxiv_id: str | None,
                           processing_time: float,
                           extra: dict | None = None) -> dict:
    """Assemble the DB row for the summaries table."""
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
            'sections_found':   summary_result.get('sections_found', []),
            'section_count':    summary_result.get('section_count', 0),
            'section_summaries': summary_result.get('section_summaries', {}),
            'contributions':    summary_result.get('contributions', []),
            'typed_entities':   summary_result.get('typed_entities', {}),
            'limitations':      summary_result.get('limitations', []),
            'future_work':      summary_result.get('future_work', []),
            'agent_metadata':   summary_result.get('agent_metadata', {}),
            # New intelligence pipeline outputs
            'research_gaps':    summary_result.get('research_gaps', {}),
            'ablation_studies': summary_result.get('ablation_studies', []),
            'reproducibility':  summary_result.get('reproducibility', {}),
        },
        'model_used':               summary_result.get('agent_metadata', {}).get('llm_backend', 'ollama'),
        'processing_time_seconds':  round(processing_time, 2),
        'word_count':               len(next(iter(summary_result.get('summaries', {}).values()), '').split()),
        'quality_score':            quality_score,
        'created_at':               datetime.utcnow().isoformat(),
    }
    if extra:
        record.update(extra)
    return record


@router.post('/process/upload', status_code=201)
async def upload_and_process(current_user: CurrentUser, file: UploadFile = File(...)):
    """Upload a PDF and run the 7-agent summarisation pipeline."""
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
        summary_result = await _run_agent_pipeline(str(temp_path))
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

        record = _build_summary_record(
            user_id=user_id,
            summary_result=summary_result,
            paper_title=summary_result.get('title', filename),
            paper_authors=summary_result.get('authors', []),
            paper_url=None,
            arxiv_id=summary_result.get('arxiv_id'),
            processing_time=processing_time,
            extra={'abstract_text': abstract_text[:2000]},
        )
        if embedding_list:
            record['embedding'] = embedding_list

        result = await asyncio.to_thread(lambda: supabase.table('summaries').insert(record).execute())
        if not result.data:
            return JSONResponse(status_code=500, content={'error': 'Failed to save summary'})

        new_id = result.data[0]['id']

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
                    'created_at': datetime.utcnow().isoformat(),
                }).execute()
            )
        except Exception as e:
            logger.warning('activity_log_failed', error=str(e))

        # Post-save tasks (similarity, citations, entities — all best-effort)
        asyncio.create_task(_post_save_tasks(new_id, user_id, summary_result))

        return {
            'message': 'Paper processed successfully',
            'summary_id': new_id,
            'summary': result.data[0],
            'processing_time': processing_time,
        }

    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except Exception:
            pass


@router.post('/process/arxiv', status_code=201)
async def process_from_arxiv(current_user: CurrentUser, request: Request):
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
    paper = await asyncio.to_thread(lambda: next(client.results(search), None))

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

        result = await asyncio.to_thread(lambda: supabase.table('summaries').insert(record).execute())
        if not result.data:
            return JSONResponse(status_code=500, content={'error': 'Failed to save summary'})

        new_id = result.data[0]['id']

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
                    'created_at': datetime.utcnow().isoformat(),
                }).execute()
            )
        except Exception as e:
            logger.warning('activity_log_failed', error=str(e))

        asyncio.create_task(_post_save_tasks(new_id, user_id, summary_result))

        return {
            'message': 'Paper processed successfully',
            'summary_id': new_id,
            'summary': result.data[0],
            'processing_time': processing_time,
        }

    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except Exception:
            pass
