"""ArXiv version diff service — compare two versions of the same paper."""

import difflib
import json
import structlog
from typing import Any, Dict, List, Optional

logger = structlog.get_logger(__name__)

DIFFABLE_KEYS = [
    "summaries.simple",
    "summaries.technical",
    "key_findings",
    "research_gaps.explicit_gaps",
    "reproducibility.score",
    "limitations",
]


def compute_summary_diff(summary_a: Dict, summary_b: Dict) -> Dict[str, Any]:
    """
    Compare two summary_data dicts and return a structured diff.
    summary_a = older version, summary_b = newer version.
    """
    diff_result: Dict[str, Any] = {}

    # Text diff on summaries
    for path in ["summaries.simple", "summaries.technical"]:
        parts = path.split(".")
        a_text = _get_nested(summary_a, parts) or ""
        b_text = _get_nested(summary_b, parts) or ""
        if a_text != b_text:
            diff_result[path] = {
                "changed": True,
                "diff_lines": list(difflib.unified_diff(
                    a_text.splitlines(), b_text.splitlines(),
                    fromfile="v1", tofile="v2", lineterm="",
                ))[:40],
            }
        else:
            diff_result[path] = {"changed": False}

    # List diff on key_findings
    a_findings = set(_get_nested(summary_a, ["key_findings"]) or [])
    b_findings = set(_get_nested(summary_b, ["key_findings"]) or [])
    diff_result["key_findings"] = {
        "added": list(b_findings - a_findings)[:5],
        "removed": list(a_findings - b_findings)[:5],
        "changed": bool(a_findings.symmetric_difference(b_findings)),
    }

    # Reproducibility score change
    a_repro = (_get_nested(summary_a, ["reproducibility", "score"]) or 0)
    b_repro = (_get_nested(summary_b, ["reproducibility", "score"]) or 0)
    diff_result["reproducibility_score"] = {
        "v1": a_repro,
        "v2": b_repro,
        "delta": round(float(b_repro) - float(a_repro), 2),
        "changed": a_repro != b_repro,
    }

    # Entities added/removed
    a_models = set(_get_nested(summary_a, ["models"]) or [])
    b_models = set(_get_nested(summary_b, ["models"]) or [])
    diff_result["models"] = {
        "added": list(b_models - a_models),
        "removed": list(a_models - b_models),
    }

    a_datasets = set(_get_nested(summary_a, ["datasets"]) or [])
    b_datasets = set(_get_nested(summary_b, ["datasets"]) or [])
    diff_result["datasets"] = {
        "added": list(b_datasets - a_datasets),
        "removed": list(a_datasets - b_datasets),
    }

    return diff_result


def _get_nested(d: Dict, keys: List[str]) -> Any:
    for key in keys:
        if not isinstance(d, dict):
            return None
        d = d.get(key)
    return d


def get_arxiv_versions(arxiv_id: str, user_id: str, supabase_client: Any) -> List[Dict]:
    """List all versions of an arXiv paper in the user's library."""
    try:
        resp = (
            supabase_client.table("summaries")
            .select("id, paper_title, arxiv_version, created_at, quality_score")
            .eq("arxiv_id", arxiv_id)
            .eq("user_id", user_id)
            .order("arxiv_version")
            .execute()
        )
        return resp.data or []
    except Exception as e:
        logger.error("get_arxiv_versions_error", error=str(e))
        return []


def diff_summaries(id1: str, id2: str, user_id: str, supabase_client: Any) -> Dict:
    """Compute diff between two summary IDs."""
    try:
        resp = (
            supabase_client.table("summaries")
            .select("id, paper_title, arxiv_version, summary_data")
            .in_("id", [id1, id2])
            .eq("user_id", user_id)
            .execute()
        )
        rows = {r["id"]: r for r in (resp.data or [])}
        if id1 not in rows or id2 not in rows:
            return {"error": "One or both summaries not found"}

        a = rows[id1]
        b = rows[id2]
        return {
            "summary_a": {"id": id1, "title": a.get("paper_title"), "version": a.get("arxiv_version")},
            "summary_b": {"id": id2, "title": b.get("paper_title"), "version": b.get("arxiv_version")},
            "diff": compute_summary_diff(a.get("summary_data", {}), b.get("summary_data", {})),
        }
    except Exception as e:
        logger.error("diff_summaries_error", error=str(e))
        return {"error": str(e)}
