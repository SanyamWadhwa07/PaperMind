"""PaperMind FastAPI application.

Run with:
    uvicorn backend.main_app:app --reload --port 8000
or from the backend/ directory:
    uvicorn main_app:app --reload --port 8000
"""

import os
import sys
import asyncio

# Fix Windows console Unicode encoding
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
import uuid as _uuid
import structlog
import structlog.contextvars
from contextlib import asynccontextmanager
from pathlib import Path

# Ensure the repo root is importable when running from backend/
_repo_root = Path(__file__).parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# Optional Sentry integration
try:
    import sentry_sdk
    from sentry_sdk.integrations.asgi import SentryAsgiMiddleware
    _dsn = (os.environ.get('SENTRY_DSN') or '').strip()
    if _dsn and not _dsn.startswith('#'):
        sentry_sdk.init(dsn=_dsn, traces_sample_rate=0.1)
except Exception:
    pass

# Optional slowapi rate limiting
try:
    from slowapi import Limiter, _rate_limit_exceeded_handler
    from slowapi.util import get_remote_address
    from slowapi.errors import RateLimitExceeded
    limiter = Limiter(key_func=get_remote_address)
    _rate_limiting_enabled = True
except ImportError:
    limiter = None
    _rate_limiting_enabled = False

from auth.routes import router as auth_router
from routes.process_paper import router as process_router
from routes.summaries import router as summaries_router
from routes.knowledge_graph import router as knowledge_graph_router
from routes.feedback import router as feedback_router
from routes.collections import router as collections_router
from routes.batch_compare import router as batch_compare_router
from routes.profile import router as profile_router
from routes.intelligence import router as intelligence_router
from routes.corpus import router as corpus_router
from routes.reading_queue import router as reading_queue_router
from routes.annotations import router as annotations_router
from routes.export_extra import router as export_extra_router
from routes.arxiv_diff import router as arxiv_diff_router

logger = structlog.get_logger(__name__)

# Ensure upload directories exist
for _d in ('uploads', 'arxiv_papers'):
    Path(_d).mkdir(exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("papermind_api_startup", version="2.0.0", port=8000)
    yield
    logger.info("papermind_api_shutdown")


app = FastAPI(
    title="PaperMind API",
    description="AI-powered research paper summarization — 7-agent parallel pipeline",
    version="2.0.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

if _rate_limiting_enabled and limiter:
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Restrict CORS to the Vite dev server origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(auth_router,           prefix="/api/auth",  tags=["auth"])
app.include_router(process_router,        prefix="/api",       tags=["process"])
app.include_router(summaries_router,      prefix="/api",       tags=["summaries"])
app.include_router(knowledge_graph_router,prefix="/api",       tags=["graph"])
app.include_router(feedback_router,       prefix="/api",       tags=["feedback"])
app.include_router(collections_router,    prefix="/api",       tags=["collections"])
app.include_router(batch_compare_router,  prefix="/api",       tags=["batch"])
app.include_router(profile_router,        prefix="/api",       tags=["profile"])
app.include_router(intelligence_router,   prefix="/api",       tags=["intelligence"])
app.include_router(corpus_router,         prefix="/api",       tags=["corpus"])
app.include_router(reading_queue_router,  prefix="/api",       tags=["queue"])
app.include_router(annotations_router,    prefix="/api",       tags=["annotations"])
app.include_router(export_extra_router,   prefix="/api",       tags=["export"])
app.include_router(arxiv_diff_router,     prefix="/api",       tags=["arxiv"])


@app.middleware("http")
async def attach_request_id(request: Request, call_next):
    request_id = str(_uuid.uuid4())
    structlog.contextvars.bind_contextvars(request_id=request_id)
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    logger.exception("unhandled_exception", path=str(request.url), error=str(exc))
    return JSONResponse(status_code=500, content={"error": "Internal server error"})


@app.get("/api/health", tags=["health"])
async def health_check():
    """Dependency health check — database, Ollama, Redis."""
    checks: dict[str, str] = {}

    try:
        from database.config import SUPABASE_URL, SUPABASE_SERVICE_KEY
        from supabase import create_client
        _sb = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
        await asyncio.to_thread(lambda: _sb.table('users').select('id').limit(1).execute())
        checks['database'] = 'ok'
    except Exception as e:
        checks['database'] = f'error: {type(e).__name__}'

    try:
        import ollama
        await asyncio.to_thread(ollama.list)
        checks['ollama'] = 'ok'
    except Exception:
        checks['ollama'] = 'unavailable'

    try:
        import redis as _redis
        _r = _redis.from_url(os.environ.get('REDIS_URL', 'redis://localhost:6379'))
        await asyncio.to_thread(_r.ping)
        checks['redis'] = 'ok'
    except Exception:
        checks['redis'] = 'unavailable'

    all_ok = all(v == 'ok' for v in checks.values())
    return JSONResponse(
        status_code=200 if all_ok else 503,
        content={
            'status': 'healthy' if all_ok else 'degraded',
            'service': 'papermind-api',
            'version': '2.0.0',
            'checks': checks,
        },
    )


if __name__ == '__main__':
    import uvicorn
    uvicorn.run("main_app:app", host="0.0.0.0", port=8000, reload=True)
