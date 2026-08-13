"""Repository layer — the only place that talks to Supabase.

Services depend on these classes rather than on the Supabase SDK, so business
logic can be tested with in-memory fakes and the storage backend can change
without touching the routes.
"""

from .base import BaseRepository, RepositoryError
from .summary_repository import SummaryRepository
from .user_repository import ActivityRepository, StatsRepository, UserRepository

__all__ = [
    'BaseRepository',
    'RepositoryError',
    'SummaryRepository',
    'UserRepository',
    'ActivityRepository',
    'StatsRepository',
]
