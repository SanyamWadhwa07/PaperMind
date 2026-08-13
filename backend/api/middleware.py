"""Cross-cutting HTTP middleware: request correlation and security headers."""

from __future__ import annotations

import time
import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

logger = structlog.get_logger(__name__)

#: Paths that are too noisy to log on every request.
_QUIET_PATHS = frozenset({'/api/health', '/api/health/live', '/api/health/ready'})


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Bind a request id to the logging context and time every request.

    An inbound `X-Request-ID` is honoured so a correlation id set by a proxy
    survives into our logs; otherwise one is generated.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get('X-Request-ID') or str(uuid.uuid4())
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
        )

        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            duration_ms = (time.perf_counter() - started) * 1000
            logger.exception('request_failed', duration_ms=round(duration_ms, 2))
            raise

        duration_ms = (time.perf_counter() - started) * 1000
        response.headers['X-Request-ID'] = request_id
        response.headers['X-Response-Time'] = f'{duration_ms:.0f}ms'

        if request.url.path not in _QUIET_PATHS:
            logger.info(
                'request_completed',
                status=response.status_code,
                duration_ms=round(duration_ms, 2),
            )
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Apply baseline security response headers.

    HSTS is only sent in production — sending it from a local HTTP dev server
    would pin the browser to HTTPS on localhost and break development.
    """

    def __init__(self, app: ASGIApp, *, production: bool = False) -> None:
        super().__init__(app)
        self._production = production

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)

        response.headers.setdefault('X-Content-Type-Options', 'nosniff')
        response.headers.setdefault('X-Frame-Options', 'DENY')
        response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
        response.headers.setdefault(
            'Permissions-Policy', 'geolocation=(), microphone=(), camera=()'
        )
        # The API only ever returns JSON, so a maximally strict CSP is safe here.
        response.headers.setdefault(
            'Content-Security-Policy',
            "default-src 'none'; frame-ancestors 'none'; base-uri 'none'",
        )

        if self._production:
            response.headers.setdefault(
                'Strict-Transport-Security',
                'max-age=31536000; includeSubDomains',
            )

        return response
