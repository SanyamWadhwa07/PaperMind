"""
PaperMind Full Feature Test — Topic: Pituitary Tumor
Runs against live backend at http://localhost:5000
Saves results to test_final/test_results.txt
"""

import sys
import io
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

import requests
import json
import time
from datetime import datetime

BASE = "http://localhost:5000"
RESULTS = []

def log(section, status, detail="", data=None):
    entry = {
        "section": section,
        "status": status,
        "detail": detail,
        "data_preview": str(data)[:300] if data else "",
        "time": datetime.now().strftime("%H:%M:%S")
    }
    RESULTS.append(entry)
    symbol = "OK" if status == "PASS" else ("FAIL" if status == "FAIL" else "SKIP")
    print(f"  [{entry['time']}] [{symbol}] {section}: {status} - {detail}")

def save_results(token=None, summary_id=None):
    lines = []
    lines.append("=" * 70)
    lines.append("PAPERMIND FEATURE TEST — TOPIC: PITUITARY TUMOR")
    lines.append(f"Run at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("=" * 70)

    passed = sum(1 for r in RESULTS if r["status"] == "PASS")
    failed = sum(1 for r in RESULTS if r["status"] == "FAIL")
    lines.append(f"\nSUMMARY: {passed} passed, {failed} failed out of {len(RESULTS)} tests\n")

    for r in RESULTS:
        symbol = "[OK]  " if r["status"] == "PASS" else ("[FAIL]" if r["status"] == "FAIL" else "[SKIP]")
        lines.append(f"[{r['time']}] {symbol} {r['section']}")
        lines.append(f"     Status : {r['status']}")
        lines.append(f"     Detail : {r['detail']}")
        if r["data_preview"]:
            lines.append(f"     Preview: {r['data_preview']}")
        lines.append("")

    if token:
        lines.append(f"\nAuth token (first 40 chars): {token[:40]}...")
    if summary_id:
        lines.append(f"Summary ID created: {summary_id}")

    out_path = "test_results.txt"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"\n  Results saved -> test_final/{out_path}")

# ─── 1. Health Check ─────────────────────────────────────────────────────────
print("\n[1] HEALTH CHECK")
try:
    r = requests.get(f"{BASE}/api/health", timeout=10)
    data = r.json()
    log("Health Check", "PASS", f"status={data.get('status')} db={data['checks'].get('database')}", data["checks"])
except Exception as e:
    log("Health Check", "FAIL", str(e))

# ─── 2. Register ─────────────────────────────────────────────────────────────
print("\n[2] AUTH — REGISTER")
TEST_EMAIL = f"test_pituitary_{int(time.time())}@papermind.test"
TEST_PASS  = "TestPass123!"
token = None
user_id = None

try:
    r = requests.post(f"{BASE}/api/auth/signup", json={
        "email": TEST_EMAIL, "password": TEST_PASS, "full_name": "Pituitary Test User"
    }, timeout=15)
    data = r.json()
    if r.status_code == 201 and data.get("token"):
        token = data["token"]
        user_id = data.get("user", {}).get("id")
        log("Register", "PASS", f"user_id={user_id}", {"email": TEST_EMAIL})
    else:
        log("Register", "FAIL", str(data))
except Exception as e:
    log("Register", "FAIL", str(e))

# ─── 3. Login ─────────────────────────────────────────────────────────────────
print("\n[3] AUTH — LOGIN")
try:
    r = requests.post(f"{BASE}/api/auth/login", json={
        "email": TEST_EMAIL, "password": TEST_PASS
    }, timeout=10)
    data = r.json()
    if r.status_code == 200 and data.get("token"):
        token = data["token"]
        log("Login", "PASS", f"token obtained, user={data.get('user',{}).get('email')}")
    else:
        log("Login", "FAIL", str(data))
except Exception as e:
    log("Login", "FAIL", str(e))

HEADERS = {"Authorization": f"Bearer {token}"} if token else {}

# ─── 4. /me endpoint ─────────────────────────────────────────────────────────
print("\n[4] AUTH — /me")
try:
    r = requests.get(f"{BASE}/api/auth/me", headers=HEADERS, timeout=10)
    data = r.json()
    if r.status_code == 200:
        log("/me", "PASS", f"email={data.get('user',{}).get('email')}")
    else:
        log("/me", "FAIL", str(data))
except Exception as e:
    log("/me", "FAIL", str(e))

# ─── 5. Process arXiv paper (pituitary tumor) ─────────────────────────────────
print("\n[5] PROCESS — arXiv PITUITARY TUMOR PAPER")
summary_id = None
# arXiv paper: "Deep learning for pituitary adenoma segmentation" 2302.05587
ARXIV_ID = "2302.05587"

try:
    r = requests.post(f"{BASE}/api/process/arxiv", json={"arxiv_id": ARXIV_ID},
                      headers=HEADERS, timeout=300)
    data = r.json()
    if r.status_code in (200, 201) and (data.get("summary_id") or data.get("id")):
        summary_id = data.get("summary_id") or data.get("id")
        title = data.get("paper_title", data.get("title", ""))
        log("Process arXiv", "PASS", f"summary_id={summary_id} title={title[:60]}", {"arxiv_id": ARXIV_ID})
    elif r.status_code == 202:
        # Async — poll
        task_id = data.get("task_id")
        log("Process arXiv (async started)", "PASS", f"task_id={task_id}")
        for _ in range(20):
            time.sleep(6)
            sr = requests.get(f"{BASE}/api/status/{task_id}", timeout=10)
            sd = sr.json()
            status = sd.get("status")
            if status == "completed":
                summary_id = sd.get("result", {}).get("summary_id")
                log("Process arXiv (async done)", "PASS", f"summary_id={summary_id}")
                break
            elif status == "error":
                log("Process arXiv (async)", "FAIL", sd.get("message", ""))
                break
        else:
            log("Process arXiv (async)", "FAIL", "Timeout after 120s")
    else:
        log("Process arXiv", "FAIL", f"HTTP {r.status_code}: {str(data)[:200]}")
except Exception as e:
    log("Process arXiv", "FAIL", str(e))

# ─── 6. List Summaries ────────────────────────────────────────────────────────
print("\n[6] SUMMARIES — LIST")
try:
    r = requests.get(f"{BASE}/api/summaries", headers=HEADERS, timeout=10)
    data = r.json()
    count = len(data) if isinstance(data, list) else data.get("count", data.get("total", "?"))
    if r.status_code == 200:
        log("List Summaries", "PASS", f"returned {count} summaries")
        if isinstance(data, list) and data and not summary_id:
            summary_id = data[0].get("id") or data[0].get("summary_id")
    else:
        log("List Summaries", "FAIL", str(data)[:200])
except Exception as e:
    log("List Summaries", "FAIL", str(e))

# ─── 7. Get Single Summary ────────────────────────────────────────────────────
print("\n[7] SUMMARIES — GET BY ID")
if summary_id:
    try:
        r = requests.get(f"{BASE}/api/summaries/{summary_id}", headers=HEADERS, timeout=10)
        data = r.json()
        if r.status_code == 200:
            title = data.get("paper_title", data.get("title", ""))
            sdata = data.get("summary_data", {})
            types = list(sdata.keys()) if isinstance(sdata, dict) else []
            log("Get Summary", "PASS", f"title='{title[:50]}' keys={types[:4]}")
        else:
            log("Get Summary", "FAIL", str(data)[:200])
    except Exception as e:
        log("Get Summary", "FAIL", str(e))
else:
    log("Get Summary", "SKIP", "No summary_id available")

# ─── 8. Export — JSON ────────────────────────────────────────────────────────
print("\n[8] EXPORT — JSON")
if summary_id:
    try:
        r = requests.get(f"{BASE}/api/export/{summary_id}?format=json",
                         headers=HEADERS, timeout=10)
        if r.status_code == 200:
            log("Export JSON", "PASS", f"Content-Type={r.headers.get('Content-Type','')}")
        else:
            log("Export JSON", "FAIL", f"HTTP {r.status_code}")
    except Exception as e:
        log("Export JSON", "FAIL", str(e))
else:
    log("Export JSON", "SKIP", "No summary_id")

# ─── 9. Export — Markdown ────────────────────────────────────────────────────
print("\n[9] EXPORT — MARKDOWN")
if summary_id:
    try:
        r = requests.get(f"{BASE}/api/export/{summary_id}?format=markdown",
                         headers=HEADERS, timeout=10)
        if r.status_code == 200:
            log("Export Markdown", "PASS", f"size={len(r.content)} bytes")
        else:
            log("Export Markdown", "FAIL", f"HTTP {r.status_code}: {r.text[:100]}")
    except Exception as e:
        log("Export Markdown", "FAIL", str(e))
else:
    log("Export Markdown", "SKIP", "No summary_id")

# ─── 10. Knowledge Graph ──────────────────────────────────────────────────────
print("\n[10] KNOWLEDGE GRAPH — PAPER GRAPH")
if summary_id:
    try:
        r = requests.get(f"{BASE}/api/graph/paper/{summary_id}",
                         headers=HEADERS, timeout=15)
        data = r.json()
        if r.status_code == 200:
            nodes = len(data.get("nodes", []))
            edges = len(data.get("edges", []))
            log("Knowledge Graph", "PASS", f"nodes={nodes} edges={edges}")
        else:
            log("Knowledge Graph", "FAIL", str(data)[:200])
    except Exception as e:
        log("Knowledge Graph", "FAIL", str(e))
else:
    log("Knowledge Graph", "SKIP", "No summary_id")

# ─── 11. Semantic Search ─────────────────────────────────────────────────────
print("\n[11] KNOWLEDGE GRAPH — SEMANTIC SEARCH")
try:
    r = requests.post(f"{BASE}/api/graph/search",
                      json={"query": "pituitary tumor segmentation deep learning", "limit": 5},
                      headers=HEADERS, timeout=15)
    data = r.json()
    if r.status_code == 200:
        results = data.get("results", data.get("papers", []))
        log("Semantic Search", "PASS", f"returned {len(results)} results")
    else:
        log("Semantic Search", "FAIL", str(data)[:200])
except Exception as e:
    log("Semantic Search", "FAIL", str(e))

# ─── 12. Recommendations ─────────────────────────────────────────────────────
print("\n[12] KNOWLEDGE GRAPH — RECOMMENDATIONS")
if summary_id:
    try:
        r = requests.get(f"{BASE}/api/graph/recommendations/{summary_id}",
                         headers=HEADERS, timeout=15)
        data = r.json()
        if r.status_code == 200:
            recs = data.get("recommendations", data.get("papers", []))
            log("Recommendations", "PASS", f"returned {len(recs)} recommendations")
        else:
            log("Recommendations", "FAIL", str(data)[:200])
    except Exception as e:
        log("Recommendations", "FAIL", str(e))
else:
    log("Recommendations", "SKIP", "No summary_id")

# ─── 13. Timeline ────────────────────────────────────────────────────────────
print("\n[13] KNOWLEDGE GRAPH — TIMELINE")
try:
    r = requests.get(f"{BASE}/api/graph/timeline", headers=HEADERS, timeout=10)
    data = r.json()
    if r.status_code == 200:
        papers = data.get("papers", data.get("nodes", []))
        log("Timeline", "PASS", f"returned {len(papers)} papers")
    else:
        log("Timeline", "FAIL", str(data)[:200])
except Exception as e:
    log("Timeline", "FAIL", str(e))

# ─── 14. Collections — Create ────────────────────────────────────────────────
print("\n[14] COLLECTIONS — CREATE")
collection_id = None
try:
    r = requests.post(f"{BASE}/api/collections",
                      json={"name": "Pituitary Tumor Research", "description": "Papers on pituitary tumors", "color": "#6366f1"},
                      headers=HEADERS, timeout=10)
    data = r.json()
    if r.status_code in (200, 201):
        collection_id = data.get("id") or data.get("collection", {}).get("id")
        log("Create Collection", "PASS", f"collection_id={collection_id}")
    else:
        log("Create Collection", "FAIL", str(data)[:200])
except Exception as e:
    log("Create Collection", "FAIL", str(e))

# ─── 15. Collections — Add Paper ─────────────────────────────────────────────
print("\n[15] COLLECTIONS — ADD PAPER")
if collection_id and summary_id:
    try:
        r = requests.post(f"{BASE}/api/collections/{collection_id}/papers",
                          json={"summary_id": summary_id},
                          headers=HEADERS, timeout=10)
        data = r.json()
        if r.status_code in (200, 201):
            log("Add to Collection", "PASS", f"paper {summary_id} → collection {collection_id}")
        else:
            log("Add to Collection", "FAIL", str(data)[:200])
    except Exception as e:
        log("Add to Collection", "FAIL", str(e))
else:
    log("Add to Collection", "SKIP", "Missing collection_id or summary_id")

# ─── 16. Feedback — Star Rating ───────────────────────────────────────────────
print("\n[16] FEEDBACK — STAR RATING")
if summary_id:
    try:
        r = requests.post(f"{BASE}/api/feedback/summary/{summary_id}",
                          json={"rating": 5, "comment": "Excellent pituitary tumor analysis!"},
                          headers=HEADERS, timeout=10)
        data = r.json()
        if r.status_code in (200, 201):
            log("Star Rating", "PASS", "rating=5 submitted successfully")
        else:
            log("Star Rating", "FAIL", str(data)[:200])
    except Exception as e:
        log("Star Rating", "FAIL", str(e))
else:
    log("Star Rating", "SKIP", "No summary_id")

# ─── 17. Batch Compare ───────────────────────────────────────────────────────
print("\n[17] BATCH COMPARE")
if summary_id:
    try:
        r = requests.post(f"{BASE}/api/batch/compare",
                          json={"summary_ids": [summary_id, summary_id]},
                          headers=HEADERS, timeout=15)
        data = r.json()
        if r.status_code == 200:
            log("Batch Compare", "PASS", f"keys={list(data.keys())[:5]}")
        else:
            log("Batch Compare", "FAIL", str(data)[:200])
    except Exception as e:
        log("Batch Compare", "FAIL", str(e))
else:
    log("Batch Compare", "SKIP", "No summary_id")

# ─── 18. Profile ─────────────────────────────────────────────────────────────
print("\n[18] PROFILE — GET")
try:
    r = requests.get(f"{BASE}/api/profile", headers=HEADERS, timeout=10)
    data = r.json()
    if r.status_code == 200:
        log("Get Profile", "PASS", f"keys={list(data.keys())[:6]}")
    else:
        log("Get Profile", "FAIL", str(data)[:200])
except Exception as e:
    log("Get Profile", "FAIL", str(e))

# ─── Save Results ────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
save_results(token=token, summary_id=summary_id)

passed = sum(1 for r in RESULTS if r["status"] == "PASS")
failed = sum(1 for r in RESULTS if r["status"] == "FAIL")
skipped = sum(1 for r in RESULTS if r["status"] == "SKIP")
print(f"\n  TOTAL: {passed} PASS  |  {failed} FAIL  |  {skipped} SKIP")
