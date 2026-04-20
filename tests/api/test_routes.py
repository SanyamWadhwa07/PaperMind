"""API route tests using Flask test client.

These tests mock the Supabase client and token_required decorator so they
can run without a real database or auth service.
"""
import json
import pytest
from unittest.mock import MagicMock, patch


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def flask_app():
    """Bootstrap the Flask app with all external deps mocked."""
    with patch.dict('sys.modules', {
        'supabase': MagicMock(),
        'sentry_sdk': MagicMock(),
        'sentry_sdk.integrations.flask': MagicMock(),
        'flask_limiter': MagicMock(),
        'flask_limiter.util': MagicMock(),
        'redis': MagicMock(),
        'structlog': MagicMock(),
        'structlog.contextvars': MagicMock(),
    }):
        with patch('backend.app.supabase', MagicMock()), \
             patch('backend.routes.summaries.supabase', MagicMock()), \
             patch('backend.routes.feedback.supabase', MagicMock()), \
             patch('backend.routes.batch_compare.supabase', MagicMock()), \
             patch('backend.routes.knowledge_graph.supabase', MagicMock()):
            from backend.app import app
            app.config['TESTING'] = True
            yield app


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


def auth_header(token='test-token'):
    return {'Authorization': f'Bearer {token}'}


# ── Health ────────────────────────────────────────────────────────────────────

def test_health_endpoint_exists(client):
    resp = client.get('/api/health')
    # Should not 404
    assert resp.status_code != 404


# ── Summaries ─────────────────────────────────────────────────────────────────

def test_summaries_requires_auth(client):
    resp = client.get('/api/summaries')
    assert resp.status_code == 401


def test_single_summary_requires_auth(client):
    resp = client.get('/api/summaries/some-id')
    assert resp.status_code == 401


def test_delete_summary_requires_auth(client):
    resp = client.delete('/api/summaries/some-id')
    assert resp.status_code == 401


# ── Batch compare ─────────────────────────────────────────────────────────────

def test_batch_compare_requires_auth(client):
    resp = client.post(
        '/api/batch/compare',
        json={'summary_ids': ['id1', 'id2']},
    )
    assert resp.status_code == 401


# ── Feedback ──────────────────────────────────────────────────────────────────

def test_feedback_submit_requires_auth(client):
    resp = client.post('/api/feedback/summary/test-id', json={'rating': 4})
    assert resp.status_code == 401


def test_feedback_get_requires_auth(client):
    resp = client.get('/api/feedback/summary/test-id')
    assert resp.status_code == 401


# ── Knowledge graph ───────────────────────────────────────────────────────────

def test_graph_paper_requires_auth(client):
    resp = client.get('/api/graph/paper/some-id')
    assert resp.status_code == 401


def test_graph_search_requires_auth(client):
    resp = client.post('/api/graph/search', json={'query': 'attention'})
    assert resp.status_code == 401


def test_graph_timeline_requires_auth(client):
    resp = client.get('/api/graph/timeline')
    assert resp.status_code == 401


# ── Collections ───────────────────────────────────────────────────────────────

def test_collections_list_requires_auth(client):
    resp = client.get('/api/collections')
    assert resp.status_code == 401


def test_collections_create_requires_auth(client):
    resp = client.post('/api/collections', json={'name': 'My Collection'})
    assert resp.status_code == 401


# ── Comparison logic (unit, no HTTP) ─────────────────────────────────────────

def test_compare_papers_validates_min_ids():
    """compare_papers_endpoint rejects fewer than 2 IDs (no real DB needed)."""
    mock_supabase = MagicMock()
    mock_supabase.table.return_value.select.return_value \
        .in_.return_value.eq.return_value.execute.return_value.data = []

    with patch('backend.routes.batch_compare.supabase', mock_supabase), \
         patch('backend.routes.batch_compare.request') as mock_req, \
         patch('backend.routes.batch_compare.token_required', lambda f: f):
        mock_req.get_json.return_value = {'summary_ids': ['only-one']}
        mock_req.user_id = 'user-1'
        from backend.routes.batch_compare import compare_papers_endpoint
        resp, status = compare_papers_endpoint()
        assert status == 400


def test_compare_papers_rejects_too_many_ids():
    """compare_papers_endpoint rejects more than 10 IDs."""
    mock_supabase = MagicMock()
    with patch('backend.routes.batch_compare.supabase', mock_supabase), \
         patch('backend.routes.batch_compare.request') as mock_req, \
         patch('backend.routes.batch_compare.token_required', lambda f: f):
        mock_req.get_json.return_value = {'summary_ids': [f'id-{i}' for i in range(11)]}
        mock_req.user_id = 'user-1'
        from backend.routes.batch_compare import compare_papers_endpoint
        resp, status = compare_papers_endpoint()
        assert status == 400


def test_feedback_validates_rating_range():
    """submit_feedback rejects rating outside 1-5."""
    mock_supabase = MagicMock()
    with patch('backend.routes.feedback.supabase', mock_supabase), \
         patch('backend.routes.feedback.request') as mock_req, \
         patch('backend.routes.feedback.token_required', lambda f: f):
        mock_req.get_json.return_value = {'rating': 10}
        mock_req.user_id = 'user-1'
        from backend.routes.feedback import submit_feedback
        resp, status = submit_feedback('some-summary-id')
        assert status == 400
