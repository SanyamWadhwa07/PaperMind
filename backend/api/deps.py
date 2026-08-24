"""FastAPI dependency providers.

Every repository and service is constructed here and injected via `Depends`.
Routes therefore never import Supabase, and tests can swap any layer with
`app.dependency_overrides[...]` instead of patching module globals.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from supabase import Client

from config import Settings, get_settings
from db import get_supabase
from repositories import (
    ActivityRepository,
    JobRepository,
    StatsRepository,
    SummaryRepository,
    UserRepository,
)
from services.auth_service import AuthService
from services.summary_service import SummaryService

SettingsDep = Annotated[Settings, Depends(get_settings)]
SupabaseDep = Annotated[Client, Depends(get_supabase)]


# ── Repositories ──────────────────────────────────────────────────────────────

def get_summary_repository(client: SupabaseDep) -> SummaryRepository:
    return SummaryRepository(client)


def get_user_repository(client: SupabaseDep) -> UserRepository:
    return UserRepository(client)


def get_activity_repository(client: SupabaseDep) -> ActivityRepository:
    return ActivityRepository(client)


def get_stats_repository(client: SupabaseDep) -> StatsRepository:
    return StatsRepository(client)


def get_job_repository(client: SupabaseDep) -> JobRepository:
    return JobRepository(client)


SummaryRepoDep = Annotated[SummaryRepository, Depends(get_summary_repository)]
UserRepoDep = Annotated[UserRepository, Depends(get_user_repository)]
ActivityRepoDep = Annotated[ActivityRepository, Depends(get_activity_repository)]
StatsRepoDep = Annotated[StatsRepository, Depends(get_stats_repository)]
JobRepoDep = Annotated[JobRepository, Depends(get_job_repository)]


# ── Services ──────────────────────────────────────────────────────────────────

def get_summary_service(
    summaries: SummaryRepoDep,
    stats: StatsRepoDep,
    activity: ActivityRepoDep,
) -> SummaryService:
    return SummaryService(summaries=summaries, stats=stats, activity=activity)


def get_auth_service(users: UserRepoDep, activity: ActivityRepoDep) -> AuthService:
    return AuthService(users=users, activity=activity)


SummaryServiceDep = Annotated[SummaryService, Depends(get_summary_service)]
AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]
