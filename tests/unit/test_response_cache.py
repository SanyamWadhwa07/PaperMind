"""The corpus-view response cache.

These exercise the in-process backend, which is what runs when Redis is absent
— the default in local development and the fallback in production.
"""

import asyncio
import time

import pytest

from api import response_cache


@pytest.fixture(autouse=True)
def _memory_backend(monkeypatch):
    """Pin the tests to the in-process store, whether or not Redis is running."""
    monkeypatch.setattr(response_cache, '_get_redis', lambda: None)
    response_cache.clear()
    yield
    response_cache.clear()


async def _build(calls, value):
    calls.append(1)
    return value


def test_second_read_does_not_rebuild():
    calls = []

    async def run():
        first = await response_cache.cached_view(
            'author-graph', 'u1', lambda: _build(calls, {'nodes': [1]})
        )
        second = await response_cache.cached_view(
            'author-graph', 'u1', lambda: _build(calls, {'nodes': [2]})
        )
        return first, second

    first, second = asyncio.run(run())
    assert first == second == {'nodes': [1]}
    assert len(calls) == 1, 'the builder should run once'


def test_users_do_not_share_an_entry():
    """The single most important property here: these views are per-user, and a
    shared key would serve one person's library to another."""
    async def run():
        await response_cache.cached_view('author-graph', 'u1', lambda: _build([], 'A'))
        return await response_cache.cached_view(
            'author-graph', 'u2', lambda: _build([], 'B')
        )

    assert asyncio.run(run()) == 'B'
    assert response_cache.get('author-graph', 'u1') == 'A'


def test_views_do_not_share_an_entry():
    async def run():
        await response_cache.cached_view('author-graph', 'u1', lambda: _build([], 'A'))
        return await response_cache.cached_view(
            'citation-network', 'u1', lambda: _build([], 'C')
        )

    assert asyncio.run(run()) == 'C'
    assert response_cache.get('author-graph', 'u1') == 'A'


def test_entry_expires():
    response_cache.set('author-graph', 'u1', {'nodes': []}, ttl=1)
    assert response_cache.get('author-graph', 'u1') is not None
    time.sleep(1.05)
    assert response_cache.get('author-graph', 'u1') is None


def test_invalidate_clears_every_view_for_one_user_only():
    for view in ('author-graph', 'citation-network', 'topic-clusters'):
        response_cache.set(view, 'u1', {'v': view})
    response_cache.set('author-graph', 'u2', {'v': 'other'})

    response_cache.invalidate_user('u1')

    for view in ('author-graph', 'citation-network', 'topic-clusters'):
        assert response_cache.get(view, 'u1') is None
    assert response_cache.get('author-graph', 'u2') == {'v': 'other'}


def test_error_envelopes_are_not_cached():
    """Caching a failure would serve it for the whole TTL; the next request
    should get a real attempt instead."""
    calls = []

    async def run():
        await response_cache.cached_view(
            'author-graph', 'u1', lambda: _build(calls, {'error': 'boom'})
        )
        return await response_cache.cached_view(
            'author-graph', 'u1', lambda: _build(calls, {'nodes': []})
        )

    assert asyncio.run(run()) == {'nodes': []}
    assert len(calls) == 2


def test_lru_evicts_the_least_recently_used(monkeypatch):
    monkeypatch.setattr(response_cache, 'MAX_ENTRIES', 3)

    for i in range(3):
        response_cache.set('view', f'u{i}', i)

    # Touch the oldest so it is no longer the eviction candidate.
    assert response_cache.get('view', 'u0') == 0

    response_cache.set('view', 'u3', 3)

    assert response_cache.get('view', 'u0') == 0, 'recently read entry survived'
    assert response_cache.get('view', 'u1') is None, 'least recently used evicted'
    assert response_cache.get('view', 'u3') == 3
