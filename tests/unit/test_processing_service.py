"""Unit tests for `run_processing`'s behavior changes from the route-handler
extraction (backend/services/paper_processing_service.py):

1. A degenerate/placeholder summary (`UnprocessableError`) becomes a returned
   `ProcessingOutcome(status='failed', ...)` rather than a raised exception —
   a worker loop must never see an HTTP-shaped exception.
2. A pgvector near-duplicate hit becomes `status='duplicate'` rather than a
   `JSONResponse(409, ...)`.
3. `on_stage` is awaited in the right order, since the job queue's `set_stage`
   (and therefore what the tray shows) depends on it.

The real pipeline, LLM calls, and Supabase are all replaced — this only
exercises `run_processing`'s own control flow.
"""
from __future__ import annotations

import types
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

import core.knowledge.embedding_service as embedding_service_module
import services.paper_processing_service as pps
from services.paper_processing_service import ProcessingSource


def healthy_summary_result() -> dict:
    return {
        'title': 'Attention Is All You Need',
        'authors': ['A. Vaswani'],
        'sections': {
            'abstract': (
                'We propose the Transformer, a model architecture eschewing '
                'recurrence entirely and relying on attention to draw global '
                'dependencies between input and output.'
            ),
        },
        'summaries': {'detailed': ' '.join(['word'] * 80)},  # >= _MIN_SUMMARY_WORDS
        'key_findings': [], 'methodology': {}, 'results': {}, 'datasets': [],
        'models': [], 'metrics': [], 'tasks': [], 'figures': [], 'tables': [],
        'sections_found': ['abstract'], 'section_count': 1, 'section_summaries': {},
        'contributions': [], 'methods_detail': '', 'experimental_setup': '',
        'typed_entities': {}, 'limitations': [], 'future_work': [],
        'agent_metadata': {}, 'research_gaps': {}, 'ablation_studies': [],
        'reproducibility': {}, 'pipeline_status': {},
    }


class FakeTable:
    def __init__(self, parent, name):
        self._parent = parent
        self._name = name
        self._payload = None

    def insert(self, payload):
        self._payload = payload
        return self

    def execute(self):
        if self._name == 'summaries':
            if self._parent.insert_fail:
                raise RuntimeError('summaries insert failed')
            row = {**self._payload, 'id': self._parent.insert_id}
            self._parent.inserted.append(row)
            return types.SimpleNamespace(data=[row])
        return types.SimpleNamespace(data=[{}])  # user_activity etc. — accepted silently


class FakeSupabase:
    """Just enough of the Supabase client for `run_processing`'s own calls —
    `_post_save_tasks` is monkeypatched out below rather than modeled here,
    since these tests are about `run_processing`'s control flow, not the
    enrichment pipeline behind it."""

    def __init__(self, *, dup_id: str | None = None, insert_id: str = 'summary-1',
                 insert_fail: bool = False):
        self.dup_id = dup_id
        self.insert_id = insert_id
        self.insert_fail = insert_fail
        self.inserted: list[dict] = []

    def rpc(self, name, params):
        assert name == 'find_duplicate_papers'
        data = [{'id': self.dup_id}] if self.dup_id else []
        return types.SimpleNamespace(execute=lambda: types.SimpleNamespace(data=data))

    def table(self, name):
        return FakeTable(self, name)


@pytest.fixture(autouse=True)
def fake_embed(monkeypatch):
    def _fake_embed_paper(title, abstract, keywords=None):
        return types.SimpleNamespace(tolist=lambda: [0.1, 0.2, 0.3])

    monkeypatch.setattr(embedding_service_module, 'embed_paper', _fake_embed_paper)


@pytest.fixture
def source(tmp_path) -> ProcessingSource:
    pdf_path = tmp_path / 'paper.pdf'
    pdf_path.write_bytes(b'%PDF-1.4 not a real pdf, but never actually parsed')
    return ProcessingSource(
        kind='upload', pdf_path=pdf_path, display_title='Uploaded Paper', sha256='abc123',
    )


# ── 1. UnprocessableError → failed outcome, never raised ────────────────────

async def test_degenerate_summary_returns_failed_outcome_instead_of_raising(monkeypatch, source):
    monkeypatch.setattr(
        pps, '_process_pdf_cached',
        AsyncMock(return_value={**healthy_summary_result(), 'summaries': {}}),
    )
    monkeypatch.setattr(pps, 'supabase', FakeSupabase())

    outcome = await pps.run_processing(source, user_id='user-1')

    assert outcome.status == 'failed'
    assert outcome.error_code == 'empty_summary'


# ── 2. Near-duplicate → duplicate outcome, not a 409 raised anywhere ────────

async def test_near_duplicate_returns_duplicate_outcome(monkeypatch, source):
    monkeypatch.setattr(
        pps, '_process_pdf_cached', AsyncMock(return_value=healthy_summary_result()),
    )
    fake_supabase = FakeSupabase(dup_id='existing-99')
    monkeypatch.setattr(pps, 'supabase', fake_supabase)

    outcome = await pps.run_processing(source, user_id='user-1')

    assert outcome.status == 'duplicate'
    assert outcome.existing_summary_id == 'existing-99'
    # Never reached the insert — the whole point of catching this early.
    assert fake_supabase.inserted == []


# ── 3. on_stage ordering ──────────────────────────────────────────────────────

async def test_on_stage_called_in_order_for_a_successful_run(monkeypatch, source):
    monkeypatch.setattr(
        pps, '_process_pdf_cached', AsyncMock(return_value=healthy_summary_result()),
    )
    monkeypatch.setattr(pps, 'supabase', FakeSupabase(insert_id='summary-42'))
    monkeypatch.setattr(pps, '_post_save_tasks', AsyncMock(return_value=None))

    stages: list[str] = []

    async def on_stage(name: str) -> None:
        stages.append(name)

    outcome = await pps.run_processing(source, user_id='user-1', on_stage=on_stage)

    assert outcome.status == 'succeeded'
    assert outcome.summary_id == 'summary-42'
    assert stages == ['extracting', 'saving', 'analysing']


# ── _store_figures ──────────────────────────────────────────────────────────
#
# The bug these cover: `attach_urls` builds *new* records carrying `image_url`
# and never mutates the list it is given. `_store_figures` used to re-project
# `summary_result['figures']` from the ORIGINAL list inside a `finally` block,
# which runs after the successful `try` too — so every uploaded URL was thrown
# away on the success path and FiguresDisplay.jsx (which keys off `image_url`)
# could only ever render caption-only cards. The old tests here only ever passed
# `'figures': []`, so nothing exercised this at all.


class _FakeStorage:
    """Stands in for FigureStorage, with attach_urls' real copy semantics."""

    def __init__(self, *_args, **_kwargs):
        self.seen_key = None

    async def attach_urls(self, summary_id, figures):
        self.seen_key = summary_id
        out = []
        for i, fig in enumerate(figures):
            record = {k: v for k, v in fig.items() if k != 'path'}
            record['image_url'] = f'https://example.test/{summary_id}/{i:03d}.png'
            out.append(record)
        return out


@pytest.fixture
def fake_figure_storage(monkeypatch):
    holder = {}

    def _factory(*args, **kwargs):
        holder['instance'] = _FakeStorage(*args, **kwargs)
        return holder['instance']

    monkeypatch.setitem(
        __import__('sys').modules, 'services.figure_storage',
        types.SimpleNamespace(FigureStorage=_factory),
    )
    return holder


@pytest.mark.asyncio
async def test_store_figures_keeps_image_url_on_success(tmp_path, fake_figure_storage):
    png = tmp_path / 'fig1.png'
    png.write_bytes(b'\x89PNG\r\n')
    result = {'figures': [{'caption': 'Figure 1: Architecture.', 'path': str(png)}]}

    await pps._store_figures(result, 'sha256-of-pdf')

    figure = result['figures'][0]
    assert figure['image_url'] == 'https://example.test/sha256-of-pdf/000.png', (
        'the upload result was discarded — figures will render caption-only'
    )
    assert figure['caption'] == 'Figure 1: Architecture.'
    assert 'path' not in figure, 'temp path must never reach the persisted record'
    # The temp file has served its purpose and nothing else cleans it up.
    assert not png.exists()
    # A stable, reconcilable key, not a throwaway uuid4.
    assert fake_figure_storage['instance'].seen_key == 'sha256-of-pdf'


@pytest.mark.asyncio
async def test_store_figures_strips_path_when_storage_fails(tmp_path, monkeypatch):
    """Losing the images must not lose the summary — or leak a dead temp path."""
    def _boom(*_args, **_kwargs):
        raise RuntimeError('bucket unreachable')

    monkeypatch.setitem(
        __import__('sys').modules, 'services.figure_storage',
        types.SimpleNamespace(FigureStorage=_boom),
    )
    png = tmp_path / 'fig1.png'
    png.write_bytes(b'\x89PNG\r\n')
    result = {'figures': [{'caption': 'Figure 1.', 'path': str(png)}]}

    await pps._store_figures(result, 'sha256-of-pdf')

    figure = result['figures'][0]
    assert figure['caption'] == 'Figure 1.'
    assert 'path' not in figure
    assert 'image_url' not in figure
    assert not png.exists()
