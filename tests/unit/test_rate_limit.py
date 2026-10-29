"""Token bucket rate limiter.

These cover the properties the previous fixed-window implementation did not
have: a burst bounded by capacity rather than by where the wall clock falls,
continuous refill, and a Retry-After the client can actually act on.
"""
from __future__ import annotations

import asyncio

import pytest

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))

from api.rate_limit import Rule, TokenBucketLimiter, parse_rule  # noqa: E402


# ── Rule parsing ────────────────────────────────────────────────────────────

@pytest.mark.parametrize('raw,capacity,refill', [
    ('120/minute', 120, 2.0),
    ('30/hour', 30, 30 / 3600),
    ('10/second', 10, 10.0),
    ('5/day', 5, 5 / 86400),
    ('60/min', 60, 1.0),
    ('120/minutes', 120, 2.0),      # plural accepted
])
def test_parse_rule(raw, capacity, refill):
    r = parse_rule(raw)
    assert r.capacity == capacity
    assert r.refill == pytest.approx(refill)
    assert r.raw == raw


@pytest.mark.parametrize('bad', ['nonsense', '0/minute', '-5/hour', '10/fortnight', ''])
def test_parse_rule_falls_back_rather_than_raising(bad):
    """A malformed rule must not boot a broken limiter or an unlimited route."""
    r = parse_rule(bad)
    assert r.capacity == 120
    assert r.refill == pytest.approx(2.0)


# ── Bucket behaviour (in-process backend) ───────────────────────────────────

@pytest.mark.asyncio
async def test_burst_is_bounded_by_capacity():
    limiter = TokenBucketLimiter()          # no redis url -> local buckets
    rule = Rule(capacity=5, refill=1.0, raw='5/5seconds')

    allowed = [(await limiter.consume('user:a', rule)).allowed for _ in range(8)]
    assert allowed[:5] == [True] * 5, 'a full bucket should spend its capacity'
    assert allowed[5:] == [False] * 3, 'and then refuse until it refills'


@pytest.mark.asyncio
async def test_buckets_are_isolated_per_key():
    """One user exhausting their bucket must not affect another's."""
    limiter = TokenBucketLimiter()
    rule = Rule(capacity=2, refill=1.0, raw='2/2seconds')

    for _ in range(2):
        assert (await limiter.consume('user:a', rule)).allowed
    assert not (await limiter.consume('user:a', rule)).allowed
    assert (await limiter.consume('user:b', rule)).allowed


@pytest.mark.asyncio
async def test_tokens_refill_continuously(monkeypatch):
    """The point of a token bucket: capacity returns smoothly, not on a boundary."""
    limiter = TokenBucketLimiter()
    rule = Rule(capacity=10, refill=10.0, raw='10/second')

    clock = {'t': 1_000.0}
    monkeypatch.setattr('api.rate_limit.time.monotonic', lambda: clock['t'])

    for _ in range(10):
        assert (await limiter.consume('user:a', rule)).allowed
    assert not (await limiter.consume('user:a', rule)).allowed

    clock['t'] += 0.5                       # half a second -> 5 tokens back
    allowed = [(await limiter.consume('user:a', rule)).allowed for _ in range(7)]
    assert allowed[:5] == [True] * 5
    assert allowed[5:] == [False] * 2


@pytest.mark.asyncio
async def test_refill_never_exceeds_capacity(monkeypatch):
    """An idle bucket must not bank unbounded credit while nobody is calling."""
    limiter = TokenBucketLimiter()
    rule = Rule(capacity=3, refill=1.0, raw='3/3seconds')

    clock = {'t': 500.0}
    monkeypatch.setattr('api.rate_limit.time.monotonic', lambda: clock['t'])

    assert (await limiter.consume('user:a', rule)).allowed
    clock['t'] += 3600                      # idle for an hour
    allowed = [(await limiter.consume('user:a', rule)).allowed for _ in range(4)]
    assert allowed == [True, True, True, False], 'capacity is the ceiling'


@pytest.mark.asyncio
async def test_no_boundary_burst(monkeypatch):
    """The fixed-window bug: 2x the limit across an interval boundary.

    A fixed window let a caller spend the whole allowance at the end of one
    window and the whole allowance again at the start of the next. Over any
    span of one period, a token bucket must never grant more than capacity
    beyond what genuinely refilled.
    """
    limiter = TokenBucketLimiter()
    rule = Rule(capacity=30, refill=30 / 3600, raw='30/hour')

    clock = {'t': 0.0}
    monkeypatch.setattr('api.rate_limit.time.monotonic', lambda: clock['t'])

    granted = sum([(await limiter.consume('user:a', rule)).allowed for _ in range(30)])
    assert granted == 30

    clock['t'] += 1                         # cross a would-be window boundary
    extra = sum([(await limiter.consume('user:a', rule)).allowed for _ in range(30)])
    assert extra == 0, 'a window reset must not hand back a second full allowance'


@pytest.mark.asyncio
async def test_retry_after_is_actionable(monkeypatch):
    """A denied caller must be told a wait that actually earns them a token."""
    limiter = TokenBucketLimiter()
    rule = Rule(capacity=2, refill=0.5, raw='2/4seconds')

    clock = {'t': 10.0}
    monkeypatch.setattr('api.rate_limit.time.monotonic', lambda: clock['t'])

    for _ in range(2):
        await limiter.consume('user:a', rule)
    denied = await limiter.consume('user:a', rule)

    assert not denied.allowed
    assert denied.retry_after == pytest.approx(2.0, abs=0.01)   # 1 token / 0.5 per s

    clock['t'] += denied.retry_after
    assert (await limiter.consume('user:a', rule)).allowed, 'the advertised wait must work'


@pytest.mark.asyncio
async def test_decision_reports_remaining_and_limit():
    limiter = TokenBucketLimiter()
    rule = Rule(capacity=4, refill=1.0, raw='4/4seconds')

    d = await limiter.consume('user:a', rule)
    assert d.limit == 4
    assert d.remaining == pytest.approx(3.0)


@pytest.mark.asyncio
async def test_unreachable_redis_degrades_to_local_buckets():
    """A limiter that raises would turn rate limiting into a total outage."""
    limiter = TokenBucketLimiter('redis://127.0.0.1:1/0')   # nothing listening
    rule = Rule(capacity=2, refill=1.0, raw='2/2seconds')

    results = [(await limiter.consume('user:a', rule)).allowed for _ in range(3)]
    assert results == [True, True, False], 'still limits, just per-process'
    assert not limiter.shared, 'and reports that buckets are not shared'


@pytest.mark.asyncio
async def test_concurrent_consumers_cannot_oversubscribe():
    """Concurrent requests on one key must not both spend the last token."""
    limiter = TokenBucketLimiter()
    rule = Rule(capacity=5, refill=0.0001, raw='5/hour')

    decisions = await asyncio.gather(
        *(limiter.consume('user:a', rule) for _ in range(20))
    )
    assert sum(d.allowed for d in decisions) == 5
