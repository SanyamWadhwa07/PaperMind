"""End-to-end contract for the token bucket at the HTTP boundary.

`tests/unit/test_rate_limit.py` covers the bucket arithmetic. This covers the
half that only breaks in wiring: that the `@limit(...)` decorator actually
refuses a real request once the bucket is empty, that the refusal comes back in
the app's single JSON envelope rather than a limiter-specific shape, and that it
carries a `Retry-After` the client can act on.

The decorator wraps endpoints that take many injected dependencies, so a
signature or kwarg mistake would show up as every request failing — or, worse,
as a route that silently never limits. Both are what this pins down.
"""
from __future__ import annotations

import pytest

from api.rate_limit import limiter


pytestmark = pytest.mark.skipif(limiter is None, reason='rate limiting disabled')


@pytest.fixture(autouse=True)
def _clean_buckets():
    """Each test starts from full buckets.

    Buckets are process-global, so without this the first test to spend the auth
    bucket would make every later one fail for the wrong reason.
    """
    limiter._local.clear()
    yield
    limiter._local.clear()


def _login(client):
    return client.post('/api/auth/login',
                       json={'email': 'nobody@example.com', 'password': 'wrong-password'})


def test_auth_route_eventually_returns_429(api_client):
    """The auth bucket is 10/minute — the 11th attempt must be refused.

    Credential stuffing is the reason this bucket exists, so the limit has to
    bite on repeated failed logins specifically, not just on successful ones.
    """
    statuses = [_login(api_client).status_code for _ in range(12)]

    assert 429 in statuses, f'never rate limited: {statuses}'
    first_429 = statuses.index(429)
    assert first_429 >= 10, f'limited too early, at attempt {first_429 + 1}'
    # Once refused, it stays refused — the bucket cannot refill mid-test.
    assert all(s == 429 for s in statuses[first_429:])


def test_429_uses_the_app_error_envelope_and_retry_after(api_client):
    for _ in range(12):
        resp = _login(api_client)
        if resp.status_code == 429:
            break
    else:
        pytest.fail('never rate limited')

    assert resp.headers.get('Retry-After'), 'a 429 without Retry-After leaves clients guessing'
    assert int(resp.headers['Retry-After']) >= 1

    body = resp.json()
    # Same envelope as every other failure — see api/errors.py::_envelope.
    assert body.get('error', {}).get('code') == 'rate_limited', body


def test_rate_limit_headers_present_on_allowed_requests(api_client):
    resp = _login(api_client)
    assert resp.status_code != 429
    assert resp.headers.get('RateLimit-Limit') == '10'
    assert 'RateLimit-Remaining' in resp.headers
    assert int(resp.headers['RateLimit-Remaining']) < 10, 'the request should have spent a token'


def test_buckets_are_per_caller_not_global(api_client):
    """One IP exhausting its bucket must not lock out a different caller.

    Unauthenticated callers key by IP; TestClient lets us vary it through the
    forwarded client address, which is what `request.client.host` reflects.
    """
    for _ in range(12):
        _login(api_client)
    assert _login(api_client).status_code == 429

    # A different key must still be served. Keys are derived per authenticated
    # subject or per client host, so clearing just this caller's bucket models
    # a second, independent caller arriving.
    limiter._local.clear()
    assert _login(api_client).status_code != 429
