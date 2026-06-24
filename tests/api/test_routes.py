"""API route tests using FastAPI TestClient (httpx).

Covers business logic rather than trivial authentication checks.
"""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock


@pytest.fixture
def client():
    """Create a TestClient for the FastAPI app with Supabase and agent calls mocked."""
    pytest.importorskip('fastapi', reason='fastapi required')
    from fastapi.testclient import TestClient

    mock_sb = MagicMock()
    mock_sb.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [{
        'id':            'user-123',
        'email':         'test@example.com',
        'password_hash': '$2b$12$KixK3HVWkGk9T3tMhlRNWeVJkGJ0o.0q5NjCqHGlbsO.sOCHRa72a',
        'full_name':     'Test User',
        'is_active':     True,
        'created_at':    '2024-01-01T00:00:00',
    }]
    mock_sb.table.return_value.insert.return_value.execute.return_value.data = [{'id': 'summary-456'}]
    mock_sb.table.return_value.update.return_value.eq.return_value.execute.return_value.data = [{}]

    with patch('auth.routes.supabase', mock_sb), \
         patch('routes.summaries.supabase', mock_sb), \
         patch('routes.feedback.supabase', mock_sb), \
         patch('routes.collections.supabase', mock_sb):
        import backend.main_app as app_module
        with TestClient(app_module.app) as c:
            yield c


def _auth_header(token: str) -> dict:
    return {'Authorization': f'Bearer {token}'}


def _make_token(user_id: str = 'user-123', email: str = 'test@example.com') -> str:
    from auth.utils import create_access_token
    return create_access_token(user_id, email)


# ----- Health ----------------------------------------------------------------

def test_health_returns_status(client):
    resp = client.get('/api/health')
    assert resp.status_code in (200, 503)
    body = resp.json()
    assert 'status' in body
    assert 'checks' in body


# ----- Feedback validation ---------------------------------------------------

def test_feedback_rejects_invalid_rating(client):
    token = _make_token()
    resp = client.post(
        '/api/feedback/summary/some-id',
        json={'rating': 6, 'comment': 'too high'},
        headers=_auth_header(token),
    )
    assert resp.status_code == 422  # Pydantic validation error


def test_feedback_rejects_zero_rating(client):
    token = _make_token()
    resp = client.post(
        '/api/feedback/summary/some-id',
        json={'rating': 0},
        headers=_auth_header(token),
    )
    assert resp.status_code == 422


def test_feedback_accepts_valid_rating(client):
    token = _make_token()
    with patch('routes.feedback.supabase') as mock_sb:
        mock_sb.table.return_value.upsert.return_value.execute.return_value.data = [{}]
        resp = client.post(
            '/api/feedback/summary/some-id',
            json={'rating': 4, 'comment': 'Good summary'},
            headers=_auth_header(token),
        )
    assert resp.status_code == 201


# ----- Batch compare validation ----------------------------------------------

def test_batch_compare_rejects_single_id(client):
    token = _make_token()
    resp = client.post(
        '/api/batch/compare',
        json={'summary_ids': ['only-one']},
        headers=_auth_header(token),
    )
    assert resp.status_code == 422


def test_batch_compare_rejects_too_many_ids(client):
    token = _make_token()
    resp = client.post(
        '/api/batch/compare',
        json={'summary_ids': [str(i) for i in range(11)]},
        headers=_auth_header(token),
    )
    assert resp.status_code == 422


# ----- Collections validation ------------------------------------------------

def test_create_collection_rejects_empty_name(client):
    token = _make_token()
    resp = client.post(
        '/api/collections',
        json={'name': '  ', 'color': '#ff0000'},
        headers=_auth_header(token),
    )
    assert resp.status_code == 422


def test_create_collection_sanitises_invalid_color(client):
    """An invalid hex color should be silently replaced with the default."""
    token = _make_token()
    with patch('routes.collections.supabase') as mock_sb:
        mock_sb.table.return_value.insert.return_value.execute.return_value.data = [{
            'id': 'col-1', 'name': 'ML Papers', 'color': '#6366f1',
        }]
        resp = client.post(
            '/api/collections',
            json={'name': 'ML Papers', 'color': 'not-a-color'},
            headers=_auth_header(token),
        )
    assert resp.status_code == 201


# ----- Summaries pagination --------------------------------------------------

def test_summaries_page_defaults(client):
    token = _make_token()
    with patch('routes.summaries.supabase') as mock_sb:
        q = MagicMock()
        q.execute.return_value.data = []
        q.execute.return_value.count = 0
        q.order.return_value = q
        q.range.return_value = q
        q.or_.return_value = q
        mock_sb.table.return_value.select.return_value.eq.return_value = q
        resp = client.get('/api/summaries', headers=_auth_header(token))
    assert resp.status_code == 200
    body = resp.json()
    assert 'summaries' in body
    assert body['page'] == 1


# ----- arXiv ID validation ---------------------------------------------------

def test_arxiv_rejects_malformed_id(client):
    token = _make_token()
    resp = client.post(
        '/api/process/arxiv',
        json={'arxiv_id': 'not-an-id'},
        headers=_auth_header(token),
    )
    assert resp.status_code == 400
