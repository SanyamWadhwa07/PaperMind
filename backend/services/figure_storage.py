"""Upload extracted figure images to object storage and attach public URLs.

The extraction pipeline writes figure PNGs to a temporary directory that is
deleted once the request ends. Without this step the images exist for a few
seconds and are then lost, which is why the UI could only ever show captions.

Kept in the service layer because it is the only part of figure handling that
knows about Supabase: `core/` produces files on disk, this turns them into URLs,
and the route persists them.
"""

from __future__ import annotations

import asyncio
import mimetypes
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol

import structlog

logger = structlog.get_logger(__name__)

DEFAULT_BUCKET = "figures"

# Figures are page images; anything larger is a scan or a mis-detection, and not
# worth the storage or the page weight.
MAX_FIGURE_BYTES = 8 * 1024 * 1024


class ObjectStore(Protocol):
    """The slice of the Supabase storage client this service needs.

    Narrow on purpose: it keeps the service unit-testable with a fake, and
    documents the dependency as "somewhere to put bytes and get a URL back"
    rather than "Supabase".
    """

    def upload(self, path: str, file: bytes, file_options: Dict[str, str]) -> Any: ...

    def get_public_url(self, path: str) -> str: ...


class FigureStorage:
    """Stores figure images and returns the records with `image_url` filled in."""

    def __init__(self, supabase, bucket: str = DEFAULT_BUCKET) -> None:
        self._supabase = supabase
        self._bucket = bucket
        self._bucket_ready = False
        self._bucket_lock = threading.Lock()

    def _store(self) -> ObjectStore:
        return self._supabase.storage.from_(self._bucket)

    def _ensure_bucket(self) -> None:
        """Create the storage bucket on first use if the project lacks it.

        A Supabase project has no buckets until someone makes one, and nothing
        in the setup scripts did — so every upload answered `404 Bucket not
        found` and every figure silently arrived at the UI without an image.
        Creating it here means storage provisions itself the first time a paper
        is processed, the same way tables are provisioned by migrations.

        Public because the browser loads these directly from an <img> tag with
        no Supabase session to sign a URL with.
        """
        if self._bucket_ready:
            return
        with self._bucket_lock:
            if self._bucket_ready:
                return
            try:
                self._supabase.storage.get_bucket(self._bucket)
                self._bucket_ready = True
                return
            except Exception:
                pass  # Missing (or unlistable) — fall through and try to create.

            try:
                self._supabase.storage.create_bucket(
                    self._bucket,
                    options={
                        "public": True,
                        "file_size_limit": MAX_FIGURE_BYTES,
                        "allowed_mime_types": [
                            "image/png", "image/jpeg", "image/webp",
                        ],
                    },
                )
                logger.info("figure_bucket_created", bucket=self._bucket)
            except Exception as exc:
                # A concurrent request may have won the race, which is fine —
                # the upload that follows decides whether storage really works.
                logger.warning(
                    "figure_bucket_create_failed", bucket=self._bucket, error=str(exc)
                )
            self._bucket_ready = True

    def _upload_one(self, summary_id: str, index: int, source: Path) -> Optional[str]:
        """Upload a single figure; return its public URL, or None on failure."""
        try:
            data = source.read_bytes()
        except OSError as exc:
            logger.warning("figure_read_failed", path=str(source), error=str(exc))
            return None

        if not data or len(data) > MAX_FIGURE_BYTES:
            logger.warning("figure_skipped", path=str(source), bytes=len(data))
            return None

        suffix = source.suffix.lower() or ".png"
        key = f"{summary_id}/{index:03d}{suffix}"
        content_type = mimetypes.types_map.get(suffix, "image/png")

        try:
            self._store().upload(key, data, {"content-type": content_type, "upsert": "true"})
            return self._store().get_public_url(key)
        except Exception as exc:
            logger.warning("figure_upload_failed", key=key, error=str(exc))
            return None

    async def attach_urls(
        self, summary_id: str, figures: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Upload each figure's image and return records carrying `image_url`.

        Failures are per-figure and non-fatal: a figure whose upload fails keeps
        its caption and simply has no image, which the UI renders as a
        caption-only card. `path` is stripped from the result either way — it
        points into a temp directory that will not exist by the time anyone
        reads the record.
        """
        if not figures:
            return []

        def _run() -> List[Dict[str, Any]]:
            self._ensure_bucket()
            out: List[Dict[str, Any]] = []
            for index, figure in enumerate(figures):
                record = {k: v for k, v in figure.items() if k != "path"}
                raw_path = figure.get("path")
                if raw_path:
                    source = Path(raw_path)
                    if source.is_file():
                        url = self._upload_one(summary_id, index, source)
                        if url:
                            record["image_url"] = url
                out.append(record)
            return out

        records = await asyncio.to_thread(_run)
        stored = sum(1 for r in records if r.get("image_url"))
        logger.info("figures_stored", summary_id=summary_id,
                    stored=stored, total=len(records))
        return records
