"""Health, readiness, and liveness probes.

The previous single endpoint returned 503 whenever Ollama or Redis were down,
even though both are optional — that makes a platform health check kill healthy
containers. Probes are now split by what they actually mean:

  /api/health/live   — the process is running. Never touches a dependency.
  /api/health/ready  — required dependencies are usable; safe to route traffic.
  /api/health        — full diagnostic detail, always 200.
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from config import get_settings

logger = structlog.get_logger(__name__)
router = APIRouter(tags=['health'])

_TIMEOUT_SECONDS = 3.0


async def _with_timeout(coro, label: str) -> dict[str, Any]:
    try:
        await asyncio.wait_for(coro, timeout=_TIMEOUT_SECONDS)
        return {'status': 'ok'}
    except asyncio.TimeoutError:
        return {'status': 'error', 'detail': f'{label} timed out'}
    except Exception as exc:  # noqa: BLE001 — probes report, never raise
        return {'status': 'error', 'detail': type(exc).__name__}


async def _check_database() -> dict[str, Any]:
    async def probe() -> None:
        from db import get_supabase

        client = get_supabase()
        await asyncio.to_thread(
            lambda: client.table('users').select('id').limit(1).execute()
        )

    return await _with_timeout(probe(), 'database')


async def _check_redis() -> dict[str, Any]:
    settings = get_settings()
    if not settings.redis_enabled:
        return {'status': 'disabled', 'detail': 'REDIS_URL not set'}

    async def probe() -> None:
        import redis.asyncio as aioredis

        client = aioredis.from_url(settings.redis_url)
        try:
            await client.ping()
        finally:
            await client.aclose()

    return await _with_timeout(probe(), 'redis')


async def _check_llm(probe: bool = False) -> dict[str, Any]:
    """Report LLM provider configuration, and optionally whether they answer.

    A configured key does not mean a working model: Google retired
    `gemini-2.0-flash` and every call 404'd, but because the provider chain
    treats any error as "try the next one", the only symptom was worse
    summaries. Pass ``probe=True`` (``/api/health?probe_llm=true``) to actually
    call each provider and see which are alive.
    """
    settings = get_settings()
    providers = []
    if settings.google_api_key:
        providers.append('gemini')
    if settings.groq_api_key:
        providers.append('groq')
    if settings.openai_api_key:
        providers.append('openai')
    if settings.anthropic_api_key:
        providers.append('anthropic')

    if not providers:
        return {
            'status': 'degraded',
            'detail': 'no cloud provider key set; falling back to local Ollama',
        }

    if not probe:
        return {'status': 'ok', 'providers': providers, 'detail': 'keys present; not probed'}

    from core.llm.providers import check_providers
    reachable = await check_providers()
    healthy = [name for name, info in reachable.items() if info['ok']]
    return {
        'status': 'ok' if healthy else 'error',
        'providers': providers,
        'reachable': reachable,
        'detail': None if healthy else 'every configured LLM provider failed to respond',
    }


@router.get('/health/live')
async def liveness() -> dict[str, str]:
    """Liveness probe — restart the container only if this fails."""
    return {'status': 'alive'}


@router.get('/health/ready')
async def readiness() -> JSONResponse:
    """Readiness probe — 503 only when a *required* dependency is unusable."""
    database = await _check_database()
    ready = database['status'] == 'ok'
    return JSONResponse(
        status_code=200 if ready else 503,
        content={'status': 'ready' if ready else 'not_ready', 'database': database},
    )


def _check_worker() -> dict[str, Any]:
    """The processing-job worker (services/job_queue.py).

    Deliberately never touched by readiness — a stalled worker means queued
    papers wait longer, not that the API should stop taking traffic (and
    taking the container out of rotation wouldn't restart the worker anyway;
    it would just stop everything else that's healthy).
    """
    settings = get_settings()
    if not settings.job_worker_enabled:
        return {'status': 'disabled'}

    from services import job_queue

    worker = job_queue.CURRENT_WORKER
    if worker is None:
        return {'status': 'error', 'detail': 'enabled but not running'}
    return {'status': 'ok', **worker.snapshot()}


@router.get('/health')
async def health(probe_llm: bool = False) -> dict[str, Any]:
    """Full diagnostics. Always 200 so it can be scraped without alerting.

    ``?probe_llm=true`` additionally calls each LLM provider. It costs a few
    tokens and a couple of seconds, so it is opt-in rather than part of the
    scraped default.
    """
    settings = get_settings()
    database, redis_state, llm = await asyncio.gather(
        _check_database(), _check_redis(), _check_llm(probe=probe_llm)
    )
    worker = _check_worker()

    checks = {'database': database, 'redis': redis_state, 'llm': llm, 'worker': worker}
    required_ok = database['status'] == 'ok'
    degraded = any(c['status'] in ('error', 'degraded') for c in checks.values())

    if not required_ok:
        status = 'unhealthy'
    elif degraded:
        status = 'degraded'
    else:
        status = 'healthy'

    return {
        'status': status,
        'service': 'papermind-api',
        'version': '2.0.0',
        'environment': settings.app_env,
        'checks': checks,
    }
