"""PaperMind API — application factory.

Run with:
    uvicorn backend.main_app:app --reload --port 8000
or from backend/:
    uvicorn main_app:app --reload --port 8000

Composition happens here and nowhere else: settings are validated, logging is
configured, middleware is stacked, and routers are mounted. Business logic lives
in services/, persistence in repositories/, and HTTP concerns in routes/.
"""

from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from pathlib import Path

# Make the repo root importable whether the app is started from / or /backend.
_REPO_ROOT = Path(__file__).resolve().parent.parent
for _path in (str(_REPO_ROOT), str(_REPO_ROOT / 'backend')):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import structlog  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.middleware.gzip import GZipMiddleware  # noqa: E402

from api.errors import register_error_handlers  # noqa: E402
from api.health import router as health_router  # noqa: E402
from api.logging_config import configure_logging  # noqa: E402
from api.middleware import (  # noqa: E402
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
)
from api.rate_limit import limiter  # noqa: E402
from config import get_settings  # noqa: E402

logger = structlog.get_logger(__name__)

API_VERSION = '2.0.0'


def _configure_sentry(dsn: str, environment: str) -> None:
    if not dsn:
        return
    try:
        import sentry_sdk

        sentry_sdk.init(
            dsn=dsn,
            environment=environment,
            traces_sample_rate=0.1,
            send_default_pii=False,
        )
        logger.info('sentry_initialised', environment=environment)
    except ImportError:
        logger.warning('sentry_dsn_set_but_sdk_missing')


def _include_routers(app: FastAPI) -> None:
    """Mount every router. Imported lazily so a broken optional feature
    surfaces as one missing router rather than a failed application boot."""
    from auth.routes import router as auth_router
    from routes.annotations import router as annotations_router
    from routes.arxiv_diff import router as arxiv_diff_router
    from routes.batch_compare import router as batch_compare_router
    from routes.collections import router as collections_router
    from routes.corpus import router as corpus_router
    from routes.export_extra import router as export_extra_router
    from routes.feedback import router as feedback_router
    from routes.intelligence import router as intelligence_router
    from routes.knowledge_graph import router as knowledge_graph_router
    from routes.process_jobs import router as process_jobs_router
    from routes.process_paper import router as process_router
    from routes.profile import router as profile_router
    from routes.reading_queue import router as reading_queue_router
    from routes.search import router as search_router
    from routes.summaries import router as summaries_router

    app.include_router(health_router, prefix='/api')
    app.include_router(auth_router, prefix='/api/auth', tags=['auth'])
    app.include_router(search_router, prefix='/api', tags=['search'])
    app.include_router(process_router, prefix='/api', tags=['process'])
    app.include_router(process_jobs_router, prefix='/api', tags=['process'])
    app.include_router(summaries_router, prefix='/api', tags=['summaries'])
    app.include_router(knowledge_graph_router, prefix='/api', tags=['graph'])
    app.include_router(feedback_router, prefix='/api', tags=['feedback'])
    app.include_router(collections_router, prefix='/api', tags=['collections'])
    app.include_router(batch_compare_router, prefix='/api', tags=['batch'])
    app.include_router(profile_router, prefix='/api', tags=['profile'])
    app.include_router(intelligence_router, prefix='/api', tags=['intelligence'])
    app.include_router(corpus_router, prefix='/api', tags=['corpus'])
    app.include_router(reading_queue_router, prefix='/api', tags=['queue'])
    app.include_router(annotations_router, prefix='/api', tags=['annotations'])
    app.include_router(export_extra_router, prefix='/api', tags=['export'])
    app.include_router(arxiv_diff_router, prefix='/api', tags=['arxiv'])


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings)

    problems = settings.validate_for_runtime()
    if problems:
        if settings.is_production:
            raise RuntimeError(
                'Refusing to start in production with invalid configuration: '
                + '; '.join(problems)
            )
        for problem in problems:
            logger.warning('configuration_problem', problem=problem)

    settings.ensure_directories()
    _configure_sentry(settings.sentry_dsn, settings.app_env)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info(
            'api_startup',
            version=API_VERSION,
            environment=settings.app_env,
            rate_limiting=limiter is not None,
            job_worker=settings.job_worker_enabled,
        )
        from services.job_queue import start_workers, stop_workers
        start_workers(app)
        yield
        await stop_workers(app)
        logger.info('api_shutdown')

    app = FastAPI(
        title='PaperMind API',
        description='AI-powered research paper summarisation and knowledge graph.',
        version=API_VERSION,
        lifespan=lifespan,
        docs_url=None if settings.is_production else '/api/docs',
        redoc_url=None if settings.is_production else '/api/redoc',
        openapi_url=None if settings.is_production else '/api/openapi.json',
    )

    # Middleware runs bottom-up: security headers wrap the outermost response.
    app.add_middleware(SecurityHeadersMiddleware, production=settings.is_production)
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'],
        allow_headers=['Authorization', 'Content-Type', 'X-Request-ID'],
        # RateLimit-*/Retry-After are exposed so a browser client can read its
        # own budget and back off, instead of discovering the limit by 429.
        expose_headers=['X-Request-ID', 'RateLimit-Limit', 'RateLimit-Remaining',
                        'RateLimit-Reset', 'Retry-After'],
        max_age=600,
    )

    # The token bucket enforces itself in the `@limit(...)` decorator and raises
    # RateLimitError, which register_error_handlers already renders into the
    # single JSON envelope — no limiter-specific middleware or handler needed.
    if limiter is not None:
        app.state.limiter = limiter

    register_error_handlers(app)
    _include_routers(app)

    return app


app = create_app()


if __name__ == '__main__':
    import uvicorn

    uvicorn.run('main_app:app', host='0.0.0.0', port=8000, reload=True)
