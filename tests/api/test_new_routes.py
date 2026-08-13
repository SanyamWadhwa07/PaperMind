"""Route coverage beyond test_routes.py: auth guards, corpus graph endpoints,
and the RelationAgent trigger.

Supabase is swapped via dependency override; no network or LLM calls happen.
"""

import pytest
from unittest.mock import AsyncMock, patch


@pytest.fixture
def client(api_client):
    return api_client


# ── Auth guards ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("path", [
    "/api/summaries",
    "/api/corpus/citation-network",
    "/api/corpus/author-graph",
    "/api/dashboard/stats",
    "/api/queue",
])
def test_protected_routes_reject_anonymous(client, path):
    resp = client.get(path)
    assert resp.status_code in (401, 403), f"{path} should require auth"


# ── Corpus graph endpoints (authenticated) ────────────────────────────────────

def test_citation_network_returns_graph_shape(client, auth_headers):
    resp = client.get("/api/corpus/citation-network", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert "nodes" in body and "edges" in body


def test_author_graph_returns_graph_shape(client, auth_headers):
    resp = client.get("/api/corpus/author-graph", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert "nodes" in body and "edges" in body


# ── RelationAgent trigger ─────────────────────────────────────────────────────

def test_relate_papers_returns_202(client, auth_headers):
    """The relate-papers endpoint schedules a background job and returns 202."""
    with patch("core.graph.relation_agent.relate_library",
               new_callable=AsyncMock) as mock_relate:
        mock_relate.return_value = {"related": 0, "persisted": 0}
        resp = client.post("/api/corpus/relate-papers", headers=auth_headers)
    assert resp.status_code == 202
    assert "message" in resp.json()


def test_relate_papers_requires_auth(client):
    resp = client.post("/api/corpus/relate-papers")
    assert resp.status_code in (401, 403)


# ── Health ────────────────────────────────────────────────────────────────────

def test_health_ok_shape(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert "checks" in resp.json()


def test_readiness_reports_database(client):
    resp = client.get("/api/health/ready")
    assert resp.status_code in (200, 503)
    assert "database" in resp.json()


# ── Search (restored endpoint) ────────────────────────────────────────────────

def test_search_requires_auth(client):
    resp = client.post("/api/search", json={"query": "transformers"})
    assert resp.status_code in (401, 403)


def test_search_rejects_empty_query(client, auth_headers):
    resp = client.post("/api/search", json={"query": "   "}, headers=auth_headers)
    assert resp.status_code == 422


def test_search_returns_papers(client, auth_headers):
    """The route delegates to ArxivService, which is stubbed out here."""
    from routes.search import get_arxiv_service
    import backend.main_app as app_module

    class FakeArxiv:
        async def search(self, query, max_results=10):
            return [{"arxiv_id": "2301.00001", "title": "A Paper"}]

    app_module.app.dependency_overrides[get_arxiv_service] = lambda: FakeArxiv()
    try:
        resp = client.post(
            "/api/search", json={"query": "transformers"}, headers=auth_headers
        )
    finally:
        app_module.app.dependency_overrides.pop(get_arxiv_service, None)

    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["papers"][0]["arxiv_id"] == "2301.00001"
