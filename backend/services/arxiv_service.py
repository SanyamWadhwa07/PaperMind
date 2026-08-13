"""arXiv search and metadata lookup.

Wraps the `arxiv` client so routes never touch it directly, and so the blocking
network call is kept off the event loop.
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog

from api.errors import ExternalServiceError

logger = structlog.get_logger(__name__)

_SEARCH_TIMEOUT_SECONDS = 20.0


def _serialise(result: Any) -> dict[str, Any]:
    """Normalise an arxiv.Result into the shape the frontend expects."""
    entry_id = getattr(result, 'entry_id', '') or ''
    arxiv_id = entry_id.rsplit('/', 1)[-1] if entry_id else ''
    published = getattr(result, 'published', None)

    return {
        'arxiv_id': arxiv_id,
        'title': (getattr(result, 'title', '') or '').strip().replace('\n', ' '),
        'authors': [a.name for a in getattr(result, 'authors', [])][:12],
        'summary': (getattr(result, 'summary', '') or '').strip().replace('\n', ' '),
        'published': published.isoformat() if published else None,
        'categories': list(getattr(result, 'categories', []) or []),
        'primary_category': getattr(result, 'primary_category', None),
        'pdf_url': getattr(result, 'pdf_url', None),
    }


class ArxivService:
    """Read-only access to the arXiv public API."""

    async def search(self, query: str, max_results: int = 10) -> list[dict[str, Any]]:
        def _blocking_search() -> list[dict[str, Any]]:
            import arxiv

            search = arxiv.Search(
                query=query,
                max_results=max_results,
                sort_by=arxiv.SortCriterion.Relevance,
            )
            client = arxiv.Client(page_size=max_results, delay_seconds=0, num_retries=2)
            return [_serialise(r) for r in client.results(search)]

        try:
            return await asyncio.wait_for(
                asyncio.to_thread(_blocking_search),
                timeout=_SEARCH_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError as exc:
            logger.warning('arxiv_search_timeout', query=query)
            raise ExternalServiceError('arXiv search timed out') from exc
        except Exception as exc:  # noqa: BLE001 — boundary with a third-party service
            logger.warning('arxiv_search_failed', query=query, error=str(exc))
            raise ExternalServiceError('arXiv search is unavailable') from exc

    async def get_metadata(self, arxiv_id: str) -> dict[str, Any]:
        def _blocking_lookup() -> dict[str, Any]:
            import arxiv

            client = arxiv.Client(num_retries=2)
            results = list(client.results(arxiv.Search(id_list=[arxiv_id])))
            if not results:
                raise LookupError(f'arXiv paper {arxiv_id} not found')
            return _serialise(results[0])

        try:
            return await asyncio.wait_for(
                asyncio.to_thread(_blocking_lookup),
                timeout=_SEARCH_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError as exc:
            raise ExternalServiceError('arXiv lookup timed out') from exc
        except Exception as exc:  # noqa: BLE001
            logger.warning('arxiv_lookup_failed', arxiv_id=arxiv_id, error=str(exc))
            raise ExternalServiceError(f'Could not fetch arXiv paper {arxiv_id}') from exc
