"""Repair data that the pipeline failed to write while bugs were live.

Three of the fixes in this codebase are forward-looking: they stop the pipeline
losing data, but they cannot recover what was already lost. Papers processed
before them sit in the database with an empty similarity cache and figures that
have captions and no images, which is why the graph, the timeline, the
recommendations and the Figures tab all render empty for an existing library.

    similarity  — recompute paper_similarity from the embeddings already stored.
                  These were being dropped because pgvector returns its column
                  as text and numpy could not read it. Cheap, no network.

    figures     — re-extract figure images from the PDF and upload them. The
                  originals lived in a temp directory that is long deleted, so
                  this re-downloads the paper from arXiv and runs extraction
                  again. Slow, and only works for arXiv papers.

Usage (from the repo root, with the venv active):

    python scripts/backfill.py similarity
    python scripts/backfill.py figures
    python scripts/backfill.py all
    python scripts/backfill.py figures --dry-run
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'backend'))


def _client():
    from db.client import get_supabase
    return get_supabase()


# ── similarity ───────────────────────────────────────────────────────────────

def backfill_similarity(dry_run: bool = False) -> None:
    from core.knowledge.graph_service import compute_and_cache_similarity

    client = _client()
    rows = client.table('summaries').select('id, user_id, paper_title').execute().data or []
    print(f'{len(rows)} papers to process\n')

    total = 0
    for row in rows:
        title = (row.get('paper_title') or 'Untitled')[:52]
        if dry_run:
            print(f'  would recompute  {title}')
            continue

        written = compute_and_cache_similarity(row['id'], row['user_id'], client)
        total += written
        print(f'  {written:>3} pairs  {title}')

    if not dry_run:
        print(f'\n{total} similarity pairs written.')
        print('The graph, timeline and recommendations read from this table.')


# ── figures ──────────────────────────────────────────────────────────────────

def _download_arxiv_pdf(arxiv_id: str, dest: Path) -> bool:
    import arxiv as arxiv_lib
    import requests

    try:
        client = arxiv_lib.Client()
        paper = next(client.results(arxiv_lib.Search(id_list=[arxiv_id])), None)
        if paper is None:
            return False
        resp = requests.get(paper.pdf_url, timeout=90)
        resp.raise_for_status()
        dest.write_bytes(resp.content)
        return True
    except Exception as exc:
        print(f'      download failed: {exc}')
        return False


def _merge(stored: List[Dict[str, Any]], fresh: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Attach fresh `image_url`s to the stored records, by position.

    The stored records carry the captions and the LLM's insight, which are worth
    more than anything a re-extraction produces; the fresh ones carry the only
    thing missing. Extraction is deterministic for a given PDF and backend, so
    position is a sound join here — but only as far as the shorter list, and
    nothing is overwritten if a record somehow already has an image.
    """
    for i, record in enumerate(stored):
        if record.get('image_url') or i >= len(fresh):
            continue
        url = fresh[i].get('image_url')
        if url:
            record['image_url'] = url
    return stored


def backfill_figures(dry_run: bool = False, limit: int | None = None) -> None:
    import asyncio

    from core.pipeline.pdf_extractor import extract_pdf
    from services.figure_storage import FigureStorage

    client = _client()
    rows = client.table('summaries') \
        .select('id, arxiv_id, paper_title, summary_data') \
        .execute().data or []

    needing = []
    for row in rows:
        figures = (row.get('summary_data') or {}).get('figures') or []
        if figures and not any(f.get('image_url') for f in figures):
            needing.append((row, figures))

    print(f'{len(needing)} of {len(rows)} papers have figures without images\n')
    if limit:
        needing = needing[:limit]

    storage = FigureStorage(client)
    repaired = 0

    for row, stored in needing:
        title = (row.get('paper_title') or 'Untitled')[:52]
        arxiv_id = row.get('arxiv_id')
        print(f'  {title}  ({len(stored)} figures)')

        if not arxiv_id or arxiv_id == 'uploaded':
            print('      skipped: no arXiv id, and the uploaded PDF was not kept')
            continue
        if dry_run:
            print('      would re-extract and upload')
            continue

        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / f'{arxiv_id}.pdf'
            if not _download_arxiv_pdf(arxiv_id, pdf):
                continue

            try:
                result = extract_pdf(str(pdf))
            except Exception as exc:
                print(f'      extraction failed: {exc}')
                continue

            fresh = [
                {'path': f.path, 'caption': f.caption}
                for f in (result.figures or [])
                if getattr(f, 'path', None)
            ]
            if not fresh:
                print('      no figure images found in the PDF')
                continue

            uploaded = asyncio.run(storage.attach_urls(row['id'], fresh))

        merged = _merge(stored, uploaded)
        attached = sum(1 for f in merged if f.get('image_url'))
        if not attached:
            print('      nothing uploaded')
            continue

        summary_data = dict(row.get('summary_data') or {})
        summary_data['figures'] = merged
        client.table('summaries').update({'summary_data': summary_data}) \
            .eq('id', row['id']).execute()

        repaired += 1
        print(f'      {attached}/{len(merged)} figures now have images')

    if not dry_run:
        print(f'\n{repaired} papers repaired.')


# ── entry point ──────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('task', choices=['similarity', 'figures', 'all'])
    parser.add_argument('--dry-run', action='store_true',
                        help='report what would change without writing')
    parser.add_argument('--limit', type=int,
                        help='figures only: stop after N papers')
    args = parser.parse_args()

    if args.task in ('similarity', 'all'):
        print('== similarity ' + '=' * 50)
        backfill_similarity(args.dry_run)
        print()

    if args.task in ('figures', 'all'):
        print('== figures ' + '=' * 53)
        backfill_figures(args.dry_run, args.limit)


if __name__ == '__main__':
    main()
