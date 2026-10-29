"""Route contracts for `/api/process/jobs*` (backend/routes/process_jobs.py).

These enqueue-and-return routes replaced the synchronous `/api/process/upload`
and `/api/process/arxiv` handlers that used to block for the full pipeline —
see TODO.md phase 5. The behaviors worth pinning down here are specific to
that change: a 202 with nothing actually processed inline, the two different
409 shapes (already in the library vs. already queued), and the 429 queue-depth
guard. `JobRepository`/`SummaryRepository` are swapped for hand-written fakes
via `app.dependency_overrides` rather than the generic chainable Supabase mock,
since these routes make several distinct repository calls per request whose
results need to differ from each other within a single test.
"""
from __future__ import annotations

import arxiv
import pytest

from api.deps import get_job_repository, get_summary_repository
from config import get_settings, Settings


class FakeSummaryRepo:
    def __init__(self, *, sha256_hit=None, arxiv_hit=None):
        self.sha256_hit = sha256_hit
        self.arxiv_hit = arxiv_hit

    async def find_by_sha256(self, sha256, user_id):
        return self.sha256_hit

    async def find_by_arxiv_id(self, arxiv_id, user_id):
        return self.arxiv_hit


class FakeJobRepo:
    """`enqueue_should_succeed=False` models the partial-unique-index conflict
    the real repository detects via a 23505 from Postgres — an active job for
    the same paper already exists."""

    def __init__(self, *, open_count=0, enqueue_should_succeed=True, active_job=None):
        self.open_count = open_count
        self.enqueue_should_succeed = enqueue_should_succeed
        self.active_job = active_job
        self.enqueued: list[dict] = []

    async def count_open_for_user(self, user_id):
        return self.open_count

    async def enqueue(self, job):
        if not self.enqueue_should_succeed:
            return None
        self.enqueued.append(job)
        return {
            'id': job['id'],
            'source_type': job['source_type'],
            'arxiv_id': job.get('arxiv_id'),
            'display_title': job['display_title'],
            'status': 'queued',
            'stage': 'queued',
            'priority': job.get('priority', 0),
            'batch_id': job.get('batch_id'),
            'attempts': 0,
            'result_summary_id': None,
            'error_code': None,
            'error_message': None,
            'created_at': '2026-08-15T00:00:00+00:00',
            'started_at': None,
            'finished_at': None,
        }

    async def find_active_by_dedupe(self, user_id, dedupe_key):
        return self.active_job


class FakeArxivPaper:
    def __init__(self, title):
        self.title = title


@pytest.fixture(autouse=True)
def fake_arxiv_client(monkeypatch):
    """The single-paper enqueue route resolves the real title synchronously
    (see the comment in process_jobs.py) via `arxiv.Client.results` — replaced
    here so these tests never touch the network."""
    def fake_results(self, search):
        return iter([FakeArxivPaper('A Paper About Attention')])

    monkeypatch.setattr(arxiv.Client, 'results', fake_results)


@pytest.fixture
def client(api_client):
    return api_client


def wire(client, *, summary_repo=None, job_repo=None, upload_dir):
    import backend.main_app as app_module
    app = app_module.app
    app.dependency_overrides[get_summary_repository] = lambda: (summary_repo or FakeSummaryRepo())
    app.dependency_overrides[get_job_repository] = lambda: (job_repo or FakeJobRepo())
    app.dependency_overrides[get_settings] = lambda: Settings(upload_dir=str(upload_dir))


# ── Enqueue returns 202 without running the pipeline ────────────────────────

def test_enqueue_upload_returns_202_without_processing(client, auth_headers, test_pdf_path, tmp_path):
    job_repo = FakeJobRepo()
    wire(client, job_repo=job_repo, upload_dir=tmp_path)

    with open(test_pdf_path, 'rb') as f:
        resp = client.post(
            '/api/process/jobs',
            headers=auth_headers,
            files={'file': ('paper.pdf', f, 'application/pdf')},
        )

    assert resp.status_code == 202
    body = resp.json()
    # Nothing ran inline — the job comes back exactly as queued, not succeeded.
    assert body['job']['status'] == 'queued'
    assert body['job']['stage'] == 'queued'
    assert body['job']['id']
    assert len(job_repo.enqueued) == 1


def test_enqueue_arxiv_returns_202_without_processing(client, auth_headers, tmp_path):
    job_repo = FakeJobRepo()
    wire(client, job_repo=job_repo, upload_dir=tmp_path)

    resp = client.post(
        '/api/process/jobs/arxiv',
        headers=auth_headers,
        json={'arxiv_id': '2311.12345'},
    )

    assert resp.status_code == 202
    body = resp.json()
    assert body['job']['status'] == 'queued'
    assert body['job']['display_title'] == 'A Paper About Attention'
    assert len(job_repo.enqueued) == 1


# ── 409s: already in the library vs. already queued ─────────────────────────

def test_enqueue_upload_409s_on_duplicate_in_library(client, auth_headers, test_pdf_path, tmp_path):
    summary_repo = FakeSummaryRepo(sha256_hit={'id': 'existing-42'})
    job_repo = FakeJobRepo()
    wire(client, summary_repo=summary_repo, job_repo=job_repo, upload_dir=tmp_path)

    with open(test_pdf_path, 'rb') as f:
        resp = client.post(
            '/api/process/jobs',
            headers=auth_headers,
            files={'file': ('paper.pdf', f, 'application/pdf')},
        )

    assert resp.status_code == 409
    body = resp.json()
    assert body['duplicate'] is True
    assert body['existing_id'] == 'existing-42'
    # Never got as far as staging a file or touching the job repo.
    assert job_repo.enqueued == []


def test_enqueue_arxiv_409s_on_already_queued(client, auth_headers, tmp_path):
    job_repo = FakeJobRepo(enqueue_should_succeed=False, active_job={'id': 'job-active-1'})
    wire(client, job_repo=job_repo, upload_dir=tmp_path)

    resp = client.post(
        '/api/process/jobs/arxiv',
        headers=auth_headers,
        json={'arxiv_id': '2311.12345'},
    )

    assert resp.status_code == 409
    body = resp.json()
    assert body['duplicate'] is True
    assert body['job_id'] == 'job-active-1'


# ── 429: queue depth ─────────────────────────────────────────────────────────

def test_enqueue_upload_429s_when_queue_full(client, auth_headers, test_pdf_path, tmp_path):
    # Default job_max_queued_per_user is 20 (config/settings.py) — 20 open jobs
    # already trips the guard.
    job_repo = FakeJobRepo(open_count=20)
    wire(client, job_repo=job_repo, upload_dir=tmp_path)

    with open(test_pdf_path, 'rb') as f:
        resp = client.post(
            '/api/process/jobs',
            headers=auth_headers,
            files={'file': ('paper.pdf', f, 'application/pdf')},
        )

    assert resp.status_code == 429
    assert resp.json()['error']['code'] == 'queue_full'
    assert job_repo.enqueued == []


def test_enqueue_arxiv_429s_when_queue_full(client, auth_headers, tmp_path):
    job_repo = FakeJobRepo(open_count=20)
    wire(client, job_repo=job_repo, upload_dir=tmp_path)

    resp = client.post(
        '/api/process/jobs/arxiv',
        headers=auth_headers,
        json={'arxiv_id': '2311.12345'},
    )

    assert resp.status_code == 429
    assert resp.json()['error']['code'] == 'queue_full'
