"""Celery task definitions for async paper processing.

Replaces the fragile in-memory processing_status dict in app.py.

Start worker:
    celery -A tasks.paper_tasks worker --loglevel=info

Uses Redis as both broker and result backend (set REDIS_URL env var).
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from celery import Celery

_redis_url = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')

celery_app = Celery(
    'papermind',
    broker=_redis_url,
    backend=_redis_url.replace('/0', '/1'),  # separate DB for results
)

celery_app.conf.update(
    task_serializer='json',
    result_serializer='json',
    accept_content=['json'],
    result_expires=3600,  # 1 hour TTL on results
    task_track_started=True,
)


@celery_app.task(bind=True, max_retries=3, default_retry_delay=10)
def process_paper_task(self, pdf_path: str, user_id: str, metadata: dict):
    """Process a paper PDF through the full agent pipeline.

    Args:
        pdf_path: Absolute path to the PDF file.
        user_id:  UUID of the owning user.
        metadata: Dict with keys: title, authors, arxiv_id, published, primary_category.

    Returns:
        Dict with summary_id on success.
    """
    try:
        self.update_state(state='PROGRESS', meta={'progress': 10, 'message': 'Loading config...'})

        from backend.main import load_config, load_patterns
        from core.agent_integration import run_agent_mode
        from core.pipeline.processing_cache import get_cached_result, cache_result

        config = load_config(None)
        patterns = load_patterns('patterns.json')

        # Check cache first
        pdf_bytes = Path(pdf_path).read_bytes()
        cached = get_cached_result(pdf_bytes)
        if cached:
            self.update_state(state='PROGRESS', meta={'progress': 90, 'message': 'Cache hit'})
            summary_result = cached
        else:
            self.update_state(state='PROGRESS', meta={'progress': 20, 'message': 'Running agents...'})
            summary_result = run_agent_mode(pdf_path, config, patterns)
            cache_result(pdf_bytes, summary_result)

        self.update_state(state='PROGRESS', meta={'progress': 80, 'message': 'Saving to database...'})

        # Save to DB (reuse logic from process_paper.py routes)
        from datetime import datetime
        from supabase import create_client
        import sys as _sys, os as _os
        _sys.path.insert(0, str(Path(__file__).parent.parent))
        from database.config import SUPABASE_URL, SUPABASE_SERVICE_KEY
        supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

        abstract_text = summary_result.get('sections', {}).get('abstract', '')
        quality_score = summary_result.get('agent_metadata', {}).get('summary_quality')

        summary_data = {
            'user_id': user_id,
            'paper_title': metadata.get('title', Path(pdf_path).stem),
            'paper_authors': metadata.get('authors', []),
            'paper_url': metadata.get('paper_url'),
            'arxiv_id': metadata.get('arxiv_id'),
            'published_date': metadata.get('published'),
            'primary_category': metadata.get('primary_category'),
            'abstract_text': abstract_text[:2000],
            'quality_score': quality_score,
            'summary_data': {
                'summaries': summary_result.get('summaries', {}),
                'key_findings': summary_result.get('key_findings', []),
                'methodology': summary_result.get('methodology', {}),
                'results': summary_result.get('results', {}),
                'entities': {
                    'datasets': summary_result.get('datasets', []),
                    'models': summary_result.get('models', []),
                    'metrics': summary_result.get('metrics', []),
                    'tasks': summary_result.get('tasks', []),
                },
                'figures': summary_result.get('figures', []),
                'sections_found': summary_result.get('sections_found', []),
                'limitations': summary_result.get('limitations', []),
                'future_work': summary_result.get('future_work', []),
                'section_summaries': summary_result.get('section_summaries', {}),
                'agent_metadata': summary_result.get('agent_metadata', {}),
            },
            'model_used': summary_result.get('agent_metadata', {}).get('llm_backend', 'ollama'),
            'processing_time_seconds': summary_result.get('agent_metadata', {}).get('total_time_ms', 0) / 1000,
            'word_count': sum(len(s.split()) for s in summary_result.get('summaries', {}).values()),
            'created_at': datetime.utcnow().isoformat(),
        }

        result = supabase.table('summaries').insert(summary_data).execute()
        if not result.data:
            raise RuntimeError('Database insert returned no data')

        new_id = result.data[0]['id']

        # Post-save background work
        try:
            from core.knowledge.graph_service import compute_and_cache_similarity
            compute_and_cache_similarity(new_id, user_id, supabase)
        except Exception:
            pass

        self.update_state(state='PROGRESS', meta={'progress': 100, 'message': 'Done'})
        return {'summary_id': new_id, 'status': 'completed'}

    except Exception as exc:
        raise self.retry(exc=exc)
