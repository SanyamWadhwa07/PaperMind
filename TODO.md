# PaperMind QA Remediation — Status

Tracking progress against the approved plan (`/so-there-are-some-generic-elephant`
in Claude's plan history). Session is mid-flight; this file is the checkpoint.

---

## ✅ DONE — Phase 1: Silent correctness bugs

All verified with passing tests (`tests/unit/test_failure_honesty.py`,
`tests/unit/test_table_extractor.py`, `tests/api/*`, full `tests/unit` suite).

- **1.1–1.3 Peer review (the SALM bug)** — `core/intelligence/peer_review_agent.py`
  rewritten: reads the summary_data keys that actually exist (was reading
  `summaries.simple`/`sections.methodology`/`results.table_results`, none of
  which are ever persisted); added required `strengths` field, calibration
  anchors, an abstain-on-thin-context instruction, `temperature=0.15`; raises
  instead of reviewing a blank paper on DB fetch failure; fixed `authors=None`
  crash; fixed `llm_backend` to reflect the real provider via `get_provider_info()`;
  added a score/recommendation consistency check.
  Also fixed the **same wrong-key bug** in `core/intelligence/slide_generator.py`
  (found while fixing peer review — not in the original plan, same root cause).
- **1.4 force=true + purge** — `backend/routes/intelligence.py` takes `?force=true`;
  `backend/database/migrations/011_purge_peer_reviews.sql` deletes all existing
  peer-review rows; frontend `SummaryPage.jsx` has a Regenerate button + renders
  `strengths`; `PeerReviewUnavailableError` now maps to 503, not a leaky 500.
- **1.5 structlog violations** — `core/agents/structure_agent.py` (the live
  `TypeError` that killed the pipeline on <3-section papers), `reproducibility_agent.py`,
  `core/knowledge/{embedding_service,citation_extractor}.py`,
  `backend/routes/{annotations,reading_queue,arxiv_diff}.py` all converted to
  structlog; dead `import logging` removed from `orchestrator.py` and
  `diagram_processor.py`. **Lint guard added**: `tests/unit/test_no_stdlib_logging.py`
  walks `core/`+`backend/` and fails on any stdlib `logging.getLogger()` binding
  (allowlists only `api/logging_config.py` and legacy `backend/main.py`, both
  with inline justification).
- **1.6 Table subprocess stdout/JSON collision** — `_main()` in
  `core/pipeline/table_extractor.py` now redirects structlog to stderr before
  extraction runs, so a per-page log line can never corrupt the JSON payload the
  parent parses. New tests including a real subprocess end-to-end check.
- **1.7–1.8 Honesty/dead-code fixes** — `core/intelligence/tools.py`'s
  `search_corpus` no longer imports a nonexistent `EmbeddingService` (was always
  silently returning `[]`); `hypothesis_agent.py` no longer fabricates
  `novelty_score: 0.5` on parse failure; `confidence_service.py` returns `None`
  instead of a fake `0.5`; `research_gap_agent.py`'s no-op `model_name` override
  deleted; `reproducibility_agent.py` gained a speech/audio corpora list (was
  vision/NLP-only, so SALM lost reproducibility points it earned).

## ✅ DONE — Phase 2: Tables

- `TablesDisplay.jsx`: ragged rows now padded to header width instead of
  short-shifting under the wrong column; banner heuristic no longer collapses a
  genuine single-labeled-column header; malformed rows (more cells than header)
  fall back to `<pre>` instead of rendering garbage.
- Two disagreeing table counts (`pdf_extractor.py` vs `structure_agent.py`) now
  emitted under distinct names (`structured_table_count`/`table_markdown_count`,
  `table_count`/`table_markdown_count`) instead of silently overwriting.
- `_split_wrapped_rows` and the subprocess-isolation machinery
  (`_process_is_polluted`, `_extract_in_subprocess`, `extract_tables`, `_main`)
  now have unit test coverage — previously none.

## ✅ DONE — Phase 3: Figures

- `_extract_figures` in `pdf_extractor.py` is now genuinely per-page (was
  all-or-nothing: one successfully rendered figure anywhere skipped the raster
  fallback for every other page).
- `figure_agent.py`'s relevance ranking now keys on the figure's actual printed
  number (`"Figure 3"`) instead of `fig["id"]`, which `DiagramProcessor` always
  sets to `"fig_000"`-style — the cross-reference bonus was dead code.
- MinerU's 0-based `page_idx` normalized to 1-based (was silently losing page-1
  figures and off-by-one on the rest).
- Caption attachment now matches by parsed figure number instead of list
  position (was misattributing captions on any gap).
- **Found and fixed while investigating test flakiness**: `extract_pdf()`'s
  workdir was keyed only by content hash with no per-call uniqueness, so two
  calls on byte-identical PDF content (or repeated calls in the same process)
  shared a mutable directory — a real race, not just a leak. Now uuid-suffixed
  per call. (This was surfaced by two `test_structure_agent.py` tests flaking
  under the full suite — see "Known pre-existing issue" below.)
- Figure-storage cache-ordering fixed: `_process_pdf_cached` now uploads figures
  *before* caching, so a cache hit no longer serves stale temp paths forever.
  Added a warning log when a figure's source path is missing (was silent).
  Added temp-file cleanup in `_store_figures`'s `finally`.

## ✅ DONE — Phase 4: pipeline_status → frontend

- `TablesDisplay.jsx`, `FiguresDisplay.jsx`, `EntityDisplay.jsx` all accept a
  `pipelineStatus` prop and render `ErrorState` (not the reassuring `EmptyState`)
  when that stage actually failed. `SummaryPage.jsx` wires
  `summaryData.pipeline_status.{tables,figure,entity}` through.
- Backend: `table_extraction_error` threaded from `table_extractor.py` →
  `pdf_extractor.py` → `structure_agent.py` metadata → `orchestrator.py`'s
  `stage_status['tables']`, alongside the existing per-agent stage_status.
- **Not done**: `SectionSummaries.jsx` was named in the plan but has no real
  backend failure signal to wire (summary generation failure aborts the whole
  pipeline before a paper is ever saved, so a rendered page's section_summaries
  is definitionally successful) — skipped as not applicable rather than faked.

## 🚧 IN PROGRESS — Phase 5: Async job queue + notification tray

### Backend — done, tested (50/50 API tests + 194/196 unit tests pass)
- `backend/database/migrations/012_processing_jobs.sql` — table +
  `claim_processing_job`/`heartbeat_processing_job`/`release_processing_job` RPCs.
  **Not yet run against a real Supabase instance** — only reasoned about, not
  verified live. Run it and sanity-check the claim RPC before relying on it.
- `backend/repositories/job_repository.py` — `JobRepository`, wired into
  `repositories/__init__.py` and `api/deps.py` (`JobRepoDep`).
- `backend/services/paper_processing_service.py` — pipeline body extracted from
  `process_paper.py`; `ProcessingSource`/`ProcessingOutcome`/`run_processing()`.
- `backend/services/job_queue.py` — `JobWorker` (claim/heartbeat-race/run loop,
  split-brain guard via lease-loss detection), `start_workers`/`stop_workers`
  wired into `main_app.py`'s lifespan, `CURRENT_WORKER` registry for health.
- `backend/routes/process_jobs.py` — `POST /process/jobs`,
  `/process/jobs/arxiv`, `/process/jobs/batch`, `GET /process/jobs`,
  `GET /process/jobs/{id}`, `DELETE /process/jobs/{id}`. Mounted in `main_app.py`.
- `backend/routes/process_paper.py` — gutted to the two deprecated sync routes,
  now thin wrappers over `run_processing()`.
- `backend/config/settings.py` — `job_worker_enabled` (forced `false` under
  pytest via `tests/conftest.py`, set *before* `main_app` is ever imported,
  since the app — and its lifespan closure — is built at module-import time),
  `job_concurrency`, `job_max_per_user`, `job_max_queued_per_user`,
  `job_poll_interval_seconds`, `job_lease_seconds`.
- `backend/api/health.py` — `/api/health` now reports a `worker` block.
- `backend/schemas.py` — `ArxivJobRequest`, `ArxivBatchJobRequest`.
- `backend/repositories/summary_repository.py` — added `find_by_sha256` (dup
  check at enqueue time).
- **Deliberate deviation from the original plan**: the deprecated sync routes
  (`/process/upload`, `/process/arxiv`) call `run_processing()` **directly**,
  not enqueue-then-await through the job queue. Simpler, lower-risk, and these
  routes are explicitly for backward compat only (evals/scripts/tests) — the
  SPA never calls them. Means they don't count against `job_max_per_user` or
  show up in the tray, which is fine since nothing in the app hits them anymore.

### Frontend — done, not yet manually verified in a browser
- `frontend/src/lib/processingStore.js` — module-level store (sibling of
  `query.js`, not an extension of it), `useProcessingJobs()`/`useJobFor()` via
  `useSyncExternalStore`, adaptive polling (2s running / 6s queued / stopped
  when idle, paused on `document.hidden`), `enqueueUpload`/`enqueueArxiv`/
  `enqueueArxivBatch`/`cancelJob`/`dismissJob`. Polls the *unfiltered* recent-jobs
  list (not `active=true`) — active-only would exclude terminal jobs entirely,
  making a transition-to-done undetectable client-side.
- `frontend/src/components/ProcessingTray.jsx` — new, mounted once in
  `Layout.jsx` outside `<main>`'s `isolate` stacking context, top-right,
  collapsed pill / expanded job list with Cancel/Open/Retry/dismiss.
- Toast collision fixed: `main.jsx`'s duplicate `<Toaster>` deleted (every toast
  was rendering twice); `ToastContext.jsx`'s `<Toaster>` moved to bottom-right
  since the tray now owns top-right.
- `AuthContext.jsx` — starts the poller on session resolve/login/signup, stops
  it on logout (`clearAuth`).
- `frontend/src/lib/api.js` — added `jobs` endpoint group (default 30s timeout,
  not `PIPELINE_TIMEOUT` — the whole point); fixed timeout-vs-network-down
  message conflation (`ECONNABORTED`/`ETIMEDOUT` → distinct message + `code: 'timeout'`).
- `HomePage.jsx` — rewritten. `ProcessingPanel`/`STAGES`/`runWithStages` deleted;
  input UI never unmounts; enqueues and lets the tray take over; upload
  percentage (before the job exists) shown inline via the salvaged
  `UploadProgressRow` from the deleted modal.
- `DiscoverPage.jsx` — rewritten. `handleAddToLibrary` enqueues instead of
  blocking; per-card busy state now `useJobFor(arxiv_id)` instead of a local
  `importing` map; extracted `ResultCard` subcomponent so the hook can be called
  per-item without violating rules-of-hooks inside `.map()`.

---

## ❌ NOT STARTED

1. **`BatchPage.jsx` rewrite** — was mid-edit when interrupted. Needs:
   delete `processItem`/`processBatch` (the sequential-loop pattern), replace
   "Process N" with one `enqueueArxivBatch(...)` call, keep the pre-submission
   staging list as-is (genuine client state), render submitted-job status from
   `useProcessingJobs()` filtered by `batch_id` instead of local `queue` state
   (this is what makes a batch survive a reload — currently it doesn't).
2. **Delete `frontend/src/components/ProcessingModal.jsx`** — confirmed zero
   importers; its progressbar markup was already salvaged into
   `ProcessingTray.jsx`'s `UploadProgressRow`.
3. **`docker-compose.yml`** — replace the Celery tombstone comment (lines ~93–101)
   with a truthful note + commented-out `worker` profile stanza.
4. **`CLAUDE.md`** — update the routes table (add `/api/process/jobs*`), the
   schema table (add `processing_jobs`), and the "(+ optional workers profile)"
   line in the setup section, which is currently stale either way.
5. **`backend/requirements.txt`** — the arq note at ~L52-53 should be revisited
   now that a queue actually exists (not via arq, but the comment explaining
   *why not* is now outdated).
6. **Tests not yet written**:
   - `tests/unit/test_job_queue.py` — claim→run→finish; **the split-brain guard**
     (heartbeat returning False aborts mid-run and writes nothing) is the most
     important one and doesn't exist yet; retry-vs-terminal on `max_attempts`;
     shutdown releases in-flight jobs.
   - `tests/unit/test_processing_service.py` — `run_processing`'s three
     behavioral changes (UnprocessableError → outcome, duplicate → outcome,
     on_stage ordering) have no dedicated tests yet (only indirectly exercised
     via the API test suite).
   - `tests/api/test_process_jobs.py` — enqueue returns 202 without invoking the
     pipeline (the actual regression test for "doesn't block"), 409 on duplicate
     summary and on in-flight job, 429 on queue_full, anonymous-rejection on the
     new routes added to `test_new_routes.py`'s parametrization.
7. **Full verification pass** (per the plan's Verification section):
   - `./venv/Scripts/python.exe -m pytest tests/ -q` full run (last full run:
     194 passed / 2 pre-existing failures, see below — needs a re-run after
     BatchPage + the remaining backend pieces land)
   - `cd frontend && npm run lint && npm run build` — **not run yet at all**
   - `npm run smoke` — not run
   - Manual verification checklist from the plan (SALM peer review end-to-end,
     table/figure rendering on a real paper, the blocking fix across route
     navigation, reload mid-job, priority queue with 5+1 papers, two-tab poll
     pickup) — none of this has been done against a running app yet.

## ⚠️ Known pre-existing issue (not caused by this session's changes)

Two tests — `test_structure_agent.py::test_extracts_sections_from_pdf` and
`::test_abstract_or_introduction_present` — fail intermittently when run as
part of the **full** `tests/unit` suite, but pass reliably in isolation
(verified repeatedly). Root-caused to test-order-dependent behavior in the
legacy `AdvancedSectionExtractor` (from `backend/main.py`) on this specific
dev machine, which is missing MinerU's OCR model weights so every extraction
falls through to that legacy path. Directly disproved the leading hypothesis
(pymupdf4llm's process-wide PyMuPDF geometry corruption) with a standalone
repro script — it does not affect `_extract_fitz`'s output for the fixture PDF.
The actual mechanism is still unidentified. Out of scope for this QA pass
(pre-existing, environment-dependent, not touched by any of this session's
diffs) — flagged here rather than silently ignored.

## Notes on scope decisions made without re-confirming

- `backend/main.py` allowlisted from the stdlib-logging lint guard rather than
  converting ~40 call sites in legacy fallback code untouched by this pass —
  all verified to use `%s`/f-string args only, so the actual bug class (kwargs
  on a stdlib logger) can't occur there.
- Toast "action buttons" (e.g., an inline Open link on the success toast) from
  the original plan sketch were dropped — `react-hot-toast`'s built-in toasts
  don't support rich actions without custom JSX toasts, and the tray already
  provides Open/Retry/Cancel, so a toast action would be redundant.

---

## ✅ DONE — Phase 3: Tables & figures not rendering on the Summary page

Reported symptom: Figures tab showed caption-only cards; Tables tab showed
"No tables detected" on papers that clearly have tables.

### 3.1 Figures — `image_url` was discarded on the success path

`backend/services/paper_processing_service.py::_store_figures`. `attach_urls`
builds **new** records carrying `image_url` and never mutates its input, but the
`finally` block re-projected `summary_result['figures']` from the **original**
list — and `finally` runs after a successful `try` too. Every uploaded URL was
thrown away 100% of the time, and `FiguresDisplay.jsx` keys off exactly that
field, so figures could only ever render caption-only.

- `finally` now only unlinks temp files; the path-stripping re-projection moved
  into the `except` branch (`attach_urls` already strips `path` on success).
- `_store_figures` takes an explicit `storage_key` — the PDF's sha256 rather
  than a throwaway `uuid4()`, so bucket objects stay reconcilable with the paper
  and a re-run upserts over its own objects instead of orphaning a new set.
- `processing_cache.py` gained `_CACHE_VERSION = 'v2'` in the key. The broken
  payload was cached *before* being written and a cache hit skips
  `_store_figures` entirely, so without the bump every previously-processed
  paper would have stayed caption-only for the full TTL.
- Regression tests in `tests/unit/test_processing_service.py` — confirmed to
  fail against the old code. The prior tests only ever passed `'figures': []`,
  which is why this was invisible.

### 3.2 Tables — the subprocess swallowed every extraction error

`core/pipeline/table_extractor.py`. In production the subprocess path is
*always* live (`pymupdf4llm` is imported by `Pymupdf4llmBackend.is_available()`
before `_enrich_result` runs, so `_process_is_polluted()` is always true).
`_extract_tables_impl` returns its exceptions as the status half of a tuple
rather than raising — and `_main` dropped that half and exited 0. A hard failure
therefore reached the parent as "successfully found zero tables": no
`table_extraction_error`, `stage_status.tables = ok`, and the UI rendered the
reassuring "No tables detected" empty state. Verified live:
`python -m core.pipeline.table_extractor nonexistent.pdf` → `[]`, exit 0.

- Subprocess payload is now `{"tables": [...], "error": <str|null>}`; a bare
  list is still accepted for one release so a rolling deploy can't hard-fail.
- `_extract_in_subprocess` returns `(tables, error)`, threaded through
  `extract_tables_with_status` → `table_extraction_error` → `pipeline_status`,
  so a real failure renders `ErrorState` instead of the empty state.
- Tests updated for the new shape, plus coverage for the error-propagation wire.

### 3.3 Verified the pipeline itself is sound

Ran the real production path against arXiv 2311.07919 (Qwen-Audio, 18pp):
`extract_pdf` → backend `pymupdf4llm`, **6 tables**, 13 figures, no error;
`StructureAgent` → 6 tables with exactly the keys `TablesDisplay.jsx` consumes;
`FigureAgent` → 13 figures, all with real files on disk;
`_transform_to_legacy_format` → both survive with the right keys.
So extraction/plumbing is correct — 3.2 was masking whatever failed at the time
those summaries were built. Existing broken summaries need a Reprocess; they
will now either succeed or say why.

### 3.4 Other fixes in the same pass

- **Frontend build gate was red.** `npm run lint` failed with 4
  `react/no-unescaped-entities` errors (`TablesDisplay.jsx` ×2,
  `KnowledgeGraph.jsx`, `BatchPage.jsx`). Now clean, and `npm run build` passes.
- `diagram_processor.process_figures` used `asyncio.gather(return_exceptions=False)`,
  so one corrupt PNG aborted the batch and lost every figure. Now
  `return_exceptions=True`, dropping only the failed figure.
- `figure_agent.py` logged nothing when the legacy extractor was unavailable
  (the `backend.main` import error is swallowed), producing an empty list
  indistinguishable from a paper with no figures. Now warns — and the module had
  **no logger at all**, so a module-level structlog logger was added.
- `StructureAgent.process` called the fully-synchronous `extract_pdf` directly
  on the event loop; its table step shells out with a 120s timeout retried once,
  so a slow paper could stall every other coroutine for ~4 minutes. Both it and
  the legacy `extract_sections_from_pdf` fallback now go through
  `asyncio.to_thread`.
- Removed `backend/scratch_job1.json` (a one-off job dump) and gitignored
  `scratch_*.json`.

### Known, not fixed (out of scope, flagged)

- **The entire Groq fallback tier is dead — every model id 404s.** Probed with
  `check_providers()` and a live orchestrator run:
  `llama-3.1-8b-instant` (fast), `llama-3.3-70b-versatile` (smart) and
  `meta-llama/llama-4-scout-17b-16e-instruct` (vision, `diagram_processor.py:261`)
  all return `404 model_not_found`. Combined with Ollama not running locally,
  Gemini is currently a **single point of failure** — the documented
  "Gemini → Groq → Ollama auto-failover" does not actually fail over. This
  surfaced when Gemini started returning `503 UNAVAILABLE` ("high demand"): the
  genai SDK burns ~33s of exponential backoff per call (1.8 → 2.3 → 4 → 8 → 17s),
  fails over to a 404 Groq, then to an unreachable Ollama, so every LangGraph
  node costs ~35s before failing. That is what makes
  `tests/integration/test_pipeline.py` (6 tests, real network calls despite the
  `LocalLLM.generate` mock — the graph engine uses `core/llm/providers.py`,
  which the mock does not cover) hang for 10+ minutes.
  Needs current Groq model ids. Worth also making those 6 tests mock the graph
  engine's provider so the suite stops depending on a live LLM.
- Table *quality* on multi-level headers: Qwen-Audio's Table 1 picks a data row
  as its header. `TablesDisplay`'s banner/malformed fallbacks cover the
  rendering, but the extraction heuristic could be better.

---

## ✅ DONE — Phase 4: Token bucket rate limiting (multi-user correctness)

Replaced slowapi's fixed window in `backend/api/rate_limit.py` with a token
bucket. The fixed window had two properties that get worse as users are added:

- **Boundary bursts.** A caller on `30/hour` could spend 30 at 10:59:59 and 30
  more at 11:00:00 — 60 pipeline runs in a second against a limit that reads as
  30 an hour. Pinned by `test_no_boundary_burst`.
- **Synchronised waves.** Every caller's window reset on the same boundary, so
  load arrived in spikes rather than spread out.

A token bucket refills continuously (`capacity` tokens at `capacity/period` per
second): same sustained throughput, burst bounded by capacity rather than by
where the wall clock falls, and callers self-space.

Implementation notes:
- **Atomic across processes.** Refill-check-decrement runs as one Redis Lua
  script, so two workers can't both see the last token. The script reads Redis's
  own `TIME` rather than each app server's clock, so limits stay correct when a
  fleet's clocks drift apart.
- **Degrades, never outages.** Redis unreachable at startup *or* mid-flight falls
  back to per-process buckets and logs it, rather than raising per request (a
  limiter that raises turns rate limiting into a total outage). Per-process
  buckets mean N workers grant N x the limit — logged loudly, and the reason
  `REDIS_URL` is not optional in a real multi-user deployment.
- **`RateLimit-Limit/Remaining/Reset` on every response path**, attached in
  `RequestContextMiddleware` rather than the endpoint: a raising endpoint's
  injected `Response` is discarded by the error handler, and a 401 or 429 is
  exactly when a client most needs its remaining budget. Exposed via CORS so a
  browser SPA can actually read them.
- **`Retry-After` on 429**, carried by a new optional `headers` on `AppError`,
  rendered through the existing single JSON envelope (`code: rate_limited`).
- Rule strings (`"120/minute"`) are unchanged, so existing settings/env keep
  working. `slowapi` dropped from `backend/requirements.txt`.
- 24 tests: `tests/unit/test_rate_limit.py` (bucket arithmetic, refill, burst
  ceiling, concurrent oversubscription, Redis-down degradation) and
  `tests/api/test_rate_limit_contract.py` (a real route actually 429s, envelope
  shape, headers on allowed *and* refused requests).

### Security review — clean

Full review of the pending diff found **no vulnerabilities**. Verified: job
ownership is `user_id`-scoped on every user-facing repository method and
re-checked in every route; the 012 RPCs are only reachable from the service-key
client and are parameterized (no dynamic SQL); `source_path` is always a
server-generated UUID so no attacker-controlled path reaches `Path()`/`unlink()`;
both `subprocess.run` calls are list-form with no shell; figure storage keys are
a SHA-256 hex digest (no traversal); arXiv/GitHub calls control path only, never
host or protocol.

One fairness bug found and fixed: `ArxivJobRequest.priority` was an unbounded
client-supplied int feeding `ORDER BY priority ASC`, so a caller could send a
large negative value and jump ahead of every other user's queued job. Now
`Field(ge=0, le=10)`.
