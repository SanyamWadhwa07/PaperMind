"""Redis-backed processing cache for PDF summarization results.

Key: sha256(pdf_bytes) — TTL: 24 hours.
Prevents re-processing identical PDFs (important for batch jobs).
"""

from __future__ import annotations
import hashlib
import json
import logging
import os
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

_TTL_SECONDS = 86_400  # 24 hours
_redis_client = None


def _get_redis():
    global _redis_client
    if _redis_client is None:
        try:
            import redis
            url = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
            _redis_client = redis.from_url(url, decode_responses=True)
            _redis_client.ping()
        except Exception as e:
            logger.warning("redis_unavailable", error=str(e))
            _redis_client = None
    return _redis_client


def pdf_cache_key(pdf_bytes: bytes) -> str:
    return 'papermind:pdf:' + hashlib.sha256(pdf_bytes).hexdigest()


def get_cached_result(pdf_bytes: bytes) -> Optional[Dict[str, Any]]:
    """Return cached summary result for this PDF, or None."""
    r = _get_redis()
    if r is None:
        return None
    try:
        raw = r.get(pdf_cache_key(pdf_bytes))
        return json.loads(raw) if raw else None
    except Exception as e:
        logger.warning("cache_get_failed", error=str(e))
        return None


def cache_result(pdf_bytes: bytes, result: Dict[str, Any]) -> bool:
    """Store a summary result in Redis for 24 hours."""
    r = _get_redis()
    if r is None:
        return False
    try:
        r.setex(pdf_cache_key(pdf_bytes), _TTL_SECONDS, json.dumps(result))
        return True
    except Exception as e:
        logger.warning("cache_set_failed", error=str(e))
        return False
