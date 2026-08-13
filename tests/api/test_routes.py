"""API route tests using FastAPI TestClient.

Dependencies are swapped with `app.dependency_overrides` (see `api_client` in
conftest) rather than patched module globals, so these tests survive refactors
of where the Supabase client is constructed.
"""

import pytest


@pytest.fixture
def client(api_client):
    return api_client


def _auth_header(token: str) -> dict:
    return {'Authorization': f'Bearer {token}'}


def _make_token(user_id: str = 'user-123', email: str = 'test@example.com') -> str:
    from auth.utils import create_access_token
    return create_access_token(user_id, email)


# ----- Health ----------------------------------------------------------------

def test_health_returns_status(client):
    resp = client.get('/api/health')
    assert resp.status_code == 200
    body = resp.json()
    assert 'status' in body
    assert 'checks' in body


def test_liveness_never_touches_dependencies(client):
    """Liveness must stay 200 even when the database is unreachable."""
    resp = client.get('/api/health/live')
    assert resp.status_code == 200
    assert resp.json()['status'] == 'alive'


# ----- Feedback validation ---------------------------------------------------

def test_feedback_rejects_invalid_rating(client, auth_headers):
    resp = client.post(
        '/api/feedback/summary/some-id',
        json={'rating': 6, 'comment': 'too high'},
        headers=auth_headers,
    )
    assert resp.status_code == 422


def test_feedback_rejects_zero_rating(client, auth_headers):
    resp = client.post(
        '/api/feedback/summary/some-id',
        json={'rating': 0},
        headers=auth_headers,
    )
    assert resp.status_code == 422


def test_feedback_accepts_valid_rating(client, auth_headers, mock_supabase):
    mock_supabase.table.return_value.execute.return_value.data = [{}]
    resp = client.post(
        '/api/feedback/summary/some-id',
        json={'rating': 4, 'comment': 'Good summary'},
        headers=auth_headers,
    )
    assert resp.status_code == 201


# ----- Batch compare validation ----------------------------------------------

def test_batch_compare_rejects_single_id(client, auth_headers):
    resp = client.post(
        '/api/batch/compare',
        json={'summary_ids': ['only-one']},
        headers=auth_headers,
    )
    assert resp.status_code == 422


def test_batch_compare_rejects_too_many_ids(client, auth_headers):
    resp = client.post(
        '/api/batch/compare',
        json={'summary_ids': [str(i) for i in range(11)]},
        headers=auth_headers,
    )
    assert resp.status_code == 422


# ----- Collections validation ------------------------------------------------

def test_create_collection_rejects_empty_name(client, auth_headers):
    resp = client.post(
        '/api/collections',
        json={'name': '  ', 'color': '#ff0000'},
        headers=auth_headers,
    )
    assert resp.status_code == 422


def test_create_collection_sanitises_invalid_color(client, auth_headers, mock_supabase):
    """An invalid hex colour is replaced with the default rather than rejected."""
    mock_supabase.table.return_value.execute.return_value.data = [
        {'id': 'col-1', 'name': 'ML Papers', 'color': '#6366f1'}
    ]
    resp = client.post(
        '/api/collections',
        json={'name': 'ML Papers', 'color': 'not-a-color'},
        headers=auth_headers,
    )
    assert resp.status_code == 201


# ----- Summaries pagination --------------------------------------------------

def test_summaries_page_defaults(client, auth_headers):
    resp = client.get('/api/summaries', headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert 'summaries' in body
    assert body['page'] == 1
    assert body['per_page'] == 10


def test_summaries_rejects_bad_sort_order(client, auth_headers):
    resp = client.get('/api/summaries?order=sideways', headers=auth_headers)
    assert resp.status_code == 422


def test_summaries_caps_per_page(client, auth_headers):
    resp = client.get('/api/summaries?per_page=5000', headers=auth_headers)
    assert resp.status_code == 422


# ----- arXiv ID validation ---------------------------------------------------

def test_arxiv_rejects_malformed_id(client, auth_headers):
    resp = client.post(
        '/api/process/arxiv',
        json={'arxiv_id': 'not-an-id'},
        headers=auth_headers,
    )
    assert resp.status_code in (400, 422)


# ----- Error envelope --------------------------------------------------------

def test_errors_use_a_consistent_envelope(client):
    """Every failure renders as {"error": {"code", "message"}}."""
    resp = client.get('/api/summaries')
    assert resp.status_code == 401
    body = resp.json()
    assert 'error' in body
    assert 'code' in body['error']
    assert 'message' in body['error']


# ----- Security headers ------------------------------------------------------

def test_security_headers_present(client):
    resp = client.get('/api/health/live')
    assert resp.headers['X-Content-Type-Options'] == 'nosniff'
    assert resp.headers['X-Frame-Options'] == 'DENY'
    assert 'X-Request-ID' in resp.headers


def test_inbound_request_id_is_preserved(client):
    resp = client.get('/api/health/live', headers={'X-Request-ID': 'trace-abc'})
    assert resp.headers['X-Request-ID'] == 'trace-abc'
