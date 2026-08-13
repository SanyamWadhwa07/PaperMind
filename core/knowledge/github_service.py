"""GitHub link enrichment service."""

import structlog
import re
import time
from typing import List, Dict

import httpx

logger = structlog.get_logger(__name__)

GITHUB_API = "https://api.github.com"
_last_request_time = 0.0
_MIN_INTERVAL = 1.0  # seconds between requests (unauthenticated: 60 req/hr)

GITHUB_RE = re.compile(r"https?://github\.com/([\w\-]+)/([\w\-]+)", re.IGNORECASE)


def _get_headers() -> Dict[str, str]:
    import os
    token = os.environ.get("GITHUB_TOKEN", "")
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _throttle() -> None:
    global _last_request_time
    elapsed = time.monotonic() - _last_request_time
    if elapsed < _MIN_INTERVAL:
        time.sleep(_MIN_INTERVAL - elapsed)
    _last_request_time = time.monotonic()


def enrich_github_links(urls: List[str]) -> List[Dict]:
    """
    For each GitHub URL: check if active (last commit < 2yr), fetch stars and README summary.
    Caps at 5 links to stay within unauthenticated rate limits.
    """
    results = []
    seen = set()
    for url in urls[:5]:
        m = GITHUB_RE.match(url.strip())
        if not m:
            continue
        owner, repo = m.group(1), m.group(2)
        key = (owner.lower(), repo.lower())
        if key in seen:
            continue
        seen.add(key)

        enriched = _fetch_repo_info(owner, repo)
        results.append(enriched)

    return results


def _fetch_repo_info(owner: str, repo: str) -> Dict:
    result: Dict = {
        "repo_url": f"https://github.com/{owner}/{repo}",
        "repo_owner": owner,
        "repo_name": repo,
        "is_active": None,
        "readme_summary": None,
        "stars": None,
    }

    try:
        _throttle()
        resp = httpx.get(f"{GITHUB_API}/repos/{owner}/{repo}", headers=_get_headers(), timeout=8)
        if resp.status_code == 200:
            data = resp.json()
            result["stars"] = data.get("stargazers_count")
            pushed_at = data.get("pushed_at", "")
            if pushed_at:
                from datetime import datetime, timezone
                pushed = datetime.fromisoformat(pushed_at.replace("Z", "+00:00"))
                age_days = (datetime.now(timezone.utc) - pushed).days
                result["is_active"] = age_days < 730  # 2 years
    except Exception as e:
        logger.debug("github_repo_fetch_failed", owner=owner, repo=repo, error=str(e))

    # Fetch README
    try:
        _throttle()
        resp = httpx.get(
            f"{GITHUB_API}/repos/{owner}/{repo}/readme",
            headers={**_get_headers(), "Accept": "application/vnd.github.raw"},
            timeout=8,
        )
        if resp.status_code == 200:
            readme = resp.text[:2000]
            # Strip markdown headers and excessive whitespace
            readme = re.sub(r"#+ ?", "", readme)
            readme = re.sub(r"\s+", " ", readme).strip()
            result["readme_summary"] = readme[:500]
    except Exception as e:
        logger.debug("github_readme_fetch_failed", owner=owner, repo=repo, error=str(e))

    return result
