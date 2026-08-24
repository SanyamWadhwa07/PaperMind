"""Business logic for reading, exporting, and deleting summaries.

Depends on repositories only — no FastAPI, no Supabase. That keeps the rules
here testable with plain fakes and lets routes stay as thin adapters.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from api.errors import NotFoundError, ValidationError
from repositories import ActivityRepository, StatsRepository, SummaryRepository

EXPORT_FORMATS = frozenset({'json', 'markdown', 'bibtex'})


@dataclass(frozen=True)
class Page:
    """A page of results plus the metadata a client needs to paginate."""

    items: list[dict[str, Any]]
    total: int
    page: int
    per_page: int

    @property
    def total_pages(self) -> int:
        if not self.total:
            return 0
        return (self.total + self.per_page - 1) // self.per_page

    def to_dict(self, key: str = 'items') -> dict[str, Any]:
        return {
            key: self.items,
            'total': self.total,
            'page': self.page,
            'per_page': self.per_page,
            'total_pages': self.total_pages,
        }


class SummaryService:
    def __init__(
        self,
        summaries: SummaryRepository,
        stats: StatsRepository | None = None,
        activity: ActivityRepository | None = None,
    ) -> None:
        self._summaries = summaries
        self._stats = stats
        self._activity = activity

    async def list_summaries(
        self,
        user_id: str,
        *,
        page: int = 1,
        per_page: int = 10,
        sort_by: str = 'created_at',
        order: str = 'desc',
        search: str = '',
    ) -> Page:
        offset = (page - 1) * per_page
        rows, total = await self._summaries.list_for_user(
            user_id,
            offset=offset,
            limit=per_page,
            sort_by=sort_by,
            descending=(order.lower() != 'asc'),
            search=search[:200].strip(),
        )
        return Page(items=rows, total=total, page=page, per_page=per_page)

    async def get_summary(self, summary_id: str, user_id: str) -> dict[str, Any]:
        row = await self._summaries.get_owned(summary_id, user_id)
        if row is None:
            # Same response for "missing" and "someone else's" — no existence leak.
            raise NotFoundError('Summary not found')
        return row

    async def delete_summary(self, summary_id: str, user_id: str) -> None:
        deleted = await self._summaries.delete_owned(summary_id, user_id)
        if not deleted:
            raise NotFoundError('Summary not found')
        if self._activity:
            await self._activity.record(user_id, 'delete', {'summary_id': summary_id})

    async def dashboard_stats(self, user_id: str) -> dict[str, Any]:
        if self._stats is None or self._activity is None:
            raise RuntimeError('SummaryService needs stats and activity repositories')

        stats = await self._stats.for_user(user_id)
        recent = await self._activity.recent(user_id, limit=10)
        # Day-level, not month-level: a personal library processes a handful
        # of papers a week at most, so a month-bucketed chart flattened every
        # real day of activity into one indistinguishable monthly bar. 30 days
        # of daily buckets is the same "recent activity" window at a
        # granularity that actually shows which days something happened.
        window_days = 30
        recent_summaries = await self._summaries.created_since(user_id, days=window_days)

        # Zero-filled up front so every day in the window has a bar/point —
        # a chart built only from days that had activity draws a line
        # straight across the gaps in between, which reads as continuous
        # activity on days nothing happened.
        today = datetime.now(timezone.utc).date()
        daily: dict[str, int] = {
            (today - timedelta(days=i)).isoformat(): 0
            for i in range(window_days - 1, -1, -1)
        }
        for row in recent_summaries:
            created = row.get('created_at') or ''
            if len(created) >= 10:
                key = created[:10]
                daily[key] = daily.get(key, 0) + 1

        return {
            'stats': {
                'total_summaries': stats.get('total_summaries', 0),
                'avg_processing_time': float(stats.get('avg_processing_time') or 0),
                'total_words_processed': stats.get('total_words_processed', 0),
                'last_summary_date': stats.get('last_summary_date'),
                'active_days': stats.get('active_days', 0),
            },
            'recent_activity': recent,
            'daily_summaries': daily,
        }

    async def export(
        self, summary_id: str, user_id: str, fmt: str = 'json'
    ) -> tuple[str, str, str]:
        """Render a summary for download.

        Returns (content, media_type, filename). Rendering to a string rather
        than a temp file keeps this pure and avoids leaking files on disk.
        """
        fmt = (fmt or 'json').lower()
        if fmt not in EXPORT_FORMATS:
            raise ValidationError(
                f'Unsupported export format: {fmt}',
                details={'supported': sorted(EXPORT_FORMATS)},
            )

        row = await self.get_summary(summary_id, user_id)
        slug = row.get('arxiv_id') or summary_id

        if fmt == 'markdown':
            return self._render_markdown(row), 'text/markdown', f'{slug}.md'
        if fmt == 'bibtex':
            return self._render_bibtex(row), 'application/x-bibtex', f'{slug}.bib'

        import json

        return json.dumps(row, indent=2, default=str), 'application/json', f'{slug}.json'

    @staticmethod
    def _render_markdown(row: dict[str, Any]) -> str:
        title = row.get('paper_title') or 'Untitled'
        authors = ', '.join(row.get('paper_authors') or [])
        data = row.get('summary_data') or {}
        lines = [f'# {title}', '']
        if authors:
            lines += [f'**Authors:** {authors}', '']
        if row.get('arxiv_id'):
            lines += [f'**arXiv:** {row["arxiv_id"]}', '']

        for name, text in (data.get('summaries') or {}).items():
            if text:
                lines += [f'## {str(name).replace("_", " ").title()}', '', str(text), '']

        findings = data.get('key_findings') or []
        if findings:
            lines += ['## Key Findings', '']
            lines += [f'- {f}' for f in findings]
            lines += ['']

        return '\n'.join(lines)

    @staticmethod
    def _render_bibtex(row: dict[str, Any]) -> str:
        arxiv_id = row.get('arxiv_id') or 'unknown'
        title = row.get('paper_title') or 'Unknown'
        authors = ' and '.join(row.get('paper_authors') or [])
        year = (row.get('published_date') or '')[:4] or '2024'
        return (
            f'@article{{{arxiv_id},\n'
            f'  title         = {{{title}}},\n'
            f'  author        = {{{authors}}},\n'
            f'  year          = {{{year}}},\n'
            f'  archivePrefix = {{arXiv}},\n'
            f'  eprint        = {{{arxiv_id}}},\n'
            f'}}\n'
        )
