"""Route coverage for endpoints beyond test_routes.py:
auth guards, the corpus graph endpoints, and the new RelationAgent trigger.

Supabase is mocked; no network or LLM calls happen.
"""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock


@pytest.fixture
def client():
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    mock_sb = MagicMock()
    mock_sb.table.return_value.select.return_value.eq.return_value.execute.return_value.data = []
    mock_sb.rpc.return_value.execute.return_value.data = []

    with patch("routes.corpus.supabase", mock_sb), \
         patch("routes.knowledge_graph.supabase", mock_sb, create=True):
        import backend.main_app as app_module
        with TestClient(app_module.app) as c:
            yield c


def _token(user_id="user-123", email="t@example.com"):
    from auth.utils import create_access_token
    return create_access_token(user_id, email)


def _auth(t):
    return {"Authorization": f"Bearer {t}"}


# ── Auth guards ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("path", [
    "/api/summaries",
    "/api/corpus/citation-network",
    "/api/corpus/author-graph",
])
def test_protected_routes_reject_anonymous(client, path):
    resp = client.get(path)
    assert resp.status_code in (401, 403), f"{path} should require auth, got {resp.status_code}"


# ── Corpus graph endpoints (authenticated) ────────────────────────────────────────

def test_citation_network_returns_graph_shape(client):
    resp = client.get("/api/corpus/citation-network", headers=_auth(_token()))
    assert resp.status_code == 200
    body = resp.json()
    assert "nodes" in body and "edges" in body


def test_author_graph_returns_graph_shape(client):
    resp = client.get("/api/corpus/author-graph", headers=_auth(_token()))
    assert resp.status_code == 200
    body = resp.json()
    assert "nodes" in body and "edges" in body


# ── RelationAgent trigger ───────────────────────────────────────────────────────

def test_relate_papers_returns_202(client):
    """The relate-papers endpoint schedules a background job and returns 202."""
    with patch("core.graph.relation_agent.relate_library",
               new_callable=AsyncMock) as mock_relate:
        mock_relate.return_value = {"related": 0, "persisted": 0}
        resp = client.post("/api/corpus/relate-papers", headers=_auth(_token()))
    assert resp.status_code == 202
    assert "message" in resp.json()


def test_relate_papers_requires_auth(client):
    resp = client.post("/api/corpus/relate-papers")
    assert resp.status_code in (401, 403)


# ── Health exposes provider info path ─────────────────────────────────────────────

def test_health_ok_shape(client):
    resp = client.get("/api/health")
    assert resp.status_code in (200, 503)
    assert "checks" in resp.json()
