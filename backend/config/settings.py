"""Typed application settings.

Single source of truth for every environment variable the backend reads.
Modules must depend on `get_settings()` rather than calling `os.getenv` directly,
so configuration is validated once at startup and can be overridden in tests.
"""

from __future__ import annotations

import secrets
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, computed_field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_BACKEND_DIR = Path(__file__).resolve().parent.parent
_PLACEHOLDER_SECRET = 'your-secret-key-change-in-production'


class Settings(BaseSettings):
    """Validated runtime configuration, loaded from the environment and backend/.env."""

    model_config = SettingsConfigDict(
        env_file=_BACKEND_DIR / '.env',
        env_file_encoding='utf-8',
        extra='ignore',
        case_sensitive=False,
    )

    # ── Environment ───────────────────────────────────────────────────────────
    app_env: Literal['development', 'staging', 'production'] = 'development'
    log_level: str = 'INFO'
    log_json: bool = False

    # ── Supabase ──────────────────────────────────────────────────────────────
    supabase_url: str = ''
    supabase_anon_key: str = ''
    supabase_service_key: str = ''

    # ── Auth ──────────────────────────────────────────────────────────────────
    jwt_secret_key: str = _PLACEHOLDER_SECRET
    jwt_algorithm: str = 'HS256'
    jwt_access_token_expires: int = 24 * 60 * 60
    password_reset_token_expires: int = 60 * 60

    # ── CORS ──────────────────────────────────────────────────────────────────
    cors_origins: str = 'http://localhost:3000,http://localhost:5173'

    # ── Uploads ───────────────────────────────────────────────────────────────
    max_upload_bytes: int = 50 * 1024 * 1024
    max_pdf_pages: int = 200
    upload_dir: str = 'uploads'
    arxiv_dir: str = 'arxiv_papers'

    # ── Rate limits ("count/period"; token bucket, see api/rate_limit.py) ──────────────────────────────────────────
    rate_limit_enabled: bool = True
    rate_limit_default: str = '120/minute'
    rate_limit_auth: str = '10/minute'
    # The pipeline routes. Batch offers a ten-paper queue, so a limit of ten
    # per hour would have let a user run the feature exactly once and then fail
    # — the ceiling has to clear the largest run the product itself offers,
    # with room for a retry after a partial failure.
    rate_limit_upload: str = '30/hour'
    rate_limit_expensive: str = '60/hour'

    # ── External services ─────────────────────────────────────────────────────
    redis_url: str = ''
    sentry_dsn: str = ''
    github_token: str = ''

    # ── Job queue ─────────────────────────────────────────────────────────────
    # Paper processing runs as a background job claimed from `processing_jobs`
    # rather than inline in the HTTP request — see
    # backend/database/migrations/012_processing_jobs.sql and
    # backend/services/job_queue.py. Disabled under pytest (see tests/conftest.py)
    # so the test suite doesn't start a real poller against a mock client.
    job_worker_enabled: bool = True
    # Concurrent jobs *per uvicorn process*. Global concurrency is this times
    # WEB_CONCURRENCY (2 in backend/Dockerfile) — kept low because extraction is
    # CPU-bound work sharing the same process as the API, and because a shared
    # free-tier LLM quota is the actual bottleneck, not I/O concurrency.
    job_concurrency: int = 1
    # In-flight cap per user, enforced inside claim_processing_job — stops one
    # user's batch from starving everyone else's queue.
    job_max_per_user: int = 2
    # Queued-or-running cap per user at enqueue time. A per-hour rate limit alone
    # can't stop someone parking 200 papers in the queue at once.
    job_max_queued_per_user: int = 20
    job_poll_interval_seconds: float = 3.0
    # Comfortably past the slowest observed pipeline run; a lease this short
    # would reap and requeue a job that was still legitimately running.
    job_lease_seconds: int = 900

    # ── LLM ───────────────────────────────────────────────────────────────────
    papermind_use_graph: bool = True
    papermind_llm_provider: str = 'auto'
    papermind_llm_backend: str = 'ollama'
    papermind_llm_model: str = ''
    groq_api_key: str = ''
    google_api_key: str = ''
    openai_api_key: str = ''
    anthropic_api_key: str = ''
    ollama_base_url: str = 'http://localhost:11434'

    # ── Validators ────────────────────────────────────────────────────────────

    @field_validator('cors_origins')
    @classmethod
    def _strip_origins(cls, v: str) -> str:
        return v.strip()

    @field_validator('log_level')
    @classmethod
    def _upper_log_level(cls, v: str) -> str:
        return v.strip().upper()

    @field_validator('sentry_dsn', 'redis_url', 'github_token', mode='before')
    @classmethod
    def _blank_out_comments(cls, v: object) -> str:
        """Tolerate `KEY=   # trailing comment` lines in hand-edited .env files."""
        text = str(v or '').strip()
        if text.startswith('#'):
            return ''
        return text.split('#', 1)[0].strip()

    # ── Derived values ────────────────────────────────────────────────────────

    @computed_field
    @property
    def is_production(self) -> bool:
        return self.app_env == 'production'

    @computed_field
    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(',') if o.strip()]

    @computed_field
    @property
    def redis_enabled(self) -> bool:
        return bool(self.redis_url)

    def validate_for_runtime(self) -> list[str]:
        """Return fatal misconfigurations. Raises in production, warns elsewhere.

        Kept separate from field validation so that importing Settings never
        explodes — tests and tooling can construct it without a full .env.
        """
        problems: list[str] = []

        if not self.supabase_url or not self.supabase_service_key:
            problems.append('SUPABASE_URL and SUPABASE_SERVICE_KEY are required')

        if self.jwt_secret_key == _PLACEHOLDER_SECRET:
            problems.append('JWT_SECRET_KEY is still the placeholder value')
        elif len(self.jwt_secret_key) < 32:
            problems.append('JWT_SECRET_KEY must be at least 32 characters')

        if self.is_production and '*' in self.cors_origin_list:
            problems.append('CORS_ORIGINS must not be "*" in production')

        return problems

    def ensure_directories(self) -> None:
        for directory in (self.upload_dir, self.arxiv_dir):
            Path(directory).mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings singleton. Call `.cache_clear()` in tests to reset."""
    return Settings()


def generate_secret() -> str:
    """Helper for operators bootstrapping a deployment."""
    return secrets.token_urlsafe(48)
