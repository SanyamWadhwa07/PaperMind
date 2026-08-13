"""Application error hierarchy and the handlers that render it.

Services raise these; they carry no FastAPI/HTTP imports so the domain stays
transport-agnostic. `register_error_handlers` maps them onto a single response
envelope so every client sees the same error shape.
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from repositories.base import RepositoryError

logger = structlog.get_logger(__name__)


class AppError(Exception):
    """Base class for expected, client-facing failures."""

    status_code: int = 400
    code: str = 'app_error'

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class ValidationError(AppError):
    status_code = 400
    code = 'validation_error'


class AuthenticationError(AppError):
    status_code = 401
    code = 'authentication_error'


class PermissionError_(AppError):
    status_code = 403
    code = 'permission_denied'


class NotFoundError(AppError):
    status_code = 404
    code = 'not_found'


class ConflictError(AppError):
    status_code = 409
    code = 'conflict'


class UnprocessableError(AppError):
    status_code = 422
    code = 'unprocessable'


class RateLimitError(AppError):
    status_code = 429
    code = 'rate_limited'


class ExternalServiceError(AppError):
    """A dependency we do not control failed (LLM, arXiv, storage)."""

    status_code = 502
    code = 'upstream_error'


def _envelope(
    *, code: str, message: str, details: dict[str, Any] | None = None
) -> dict[str, Any]:
    body: dict[str, Any] = {'error': {'code': code, 'message': message}}
    if details:
        body['error']['details'] = details
    return body


def register_error_handlers(app: FastAPI) -> None:
    """Attach handlers that normalise every failure to one JSON shape."""

    @app.exception_handler(AppError)
    async def _handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        logger.info(
            'app_error',
            code=exc.code,
            status=exc.status_code,
            path=request.url.path,
            message=exc.message,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=_envelope(code=exc.code, message=exc.message, details=exc.details),
        )

    @app.exception_handler(RepositoryError)
    async def _handle_repository_error(
        request: Request, exc: RepositoryError
    ) -> JSONResponse:
        logger.error('repository_failure', path=request.url.path, error=str(exc))
        return JSONResponse(
            status_code=503,
            content=_envelope(
                code='storage_unavailable',
                message='The data store is temporarily unavailable. Please retry.',
            ),
        )

    @app.exception_handler(RequestValidationError)
    async def _handle_request_validation(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        fields = [
            {
                'field': '.'.join(str(p) for p in err.get('loc', []) if p != 'body'),
                'message': err.get('msg', 'invalid value'),
            }
            for err in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content=_envelope(
                code='validation_error',
                message='Request validation failed',
                details={'fields': fields},
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http_exception(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        detail = exc.detail if isinstance(exc.detail, str) else 'Request failed'
        return JSONResponse(
            status_code=exc.status_code,
            content=_envelope(code=f'http_{exc.status_code}', message=detail),
            headers=getattr(exc, 'headers', None),
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        # Never leak internals: the message is logged, not returned.
        logger.exception(
            'unhandled_exception',
            path=request.url.path,
            error_type=type(exc).__name__,
            error=str(exc),
        )
        return JSONResponse(
            status_code=500,
            content=_envelope(
                code='internal_error', message='An unexpected error occurred'
            ),
        )
