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

    # ── Rate limits (slowapi syntax) ──────────────────────────────────────────
    rate_limit_enabled: bool = True
    rate_limit_default: str = '120/minute'
    rate_limit_auth: str = '10/minute'
    rate_limit_upload: str = '10/hour'
    rate_limit_expensive: str = '30/hour'

    # ── External services ─────────────────────────────────────────────────────
    redis_url: str = ''
    sentry_dsn: str = ''
    github_token: str = ''

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
