-- Migration 012: Asynchronous paper processing queue
--
-- Paper processing ran inside the HTTP request: POST /api/process/upload held a
-- connection open for the entire 7-agent pipeline (nginx allows 600s on /api
-- for exactly this, and the client sets a ten-minute timeout for exactly this).
-- The whole site's input UI unmounted while a paper processed, navigating away
-- abandoned nothing server-side (the paper still saved) but the user never
-- learned it had worked, and queueing a second or third paper meant firing a
-- second full pipeline run concurrently with no coordination — burning through
-- the shared free-tier LLM quota with no queue, no priority, and no limit.
--
-- Work is now a row. The request writes it and returns in well under a second;
-- a worker claims it with FOR UPDATE SKIP LOCKED, which is also what makes
-- running two uvicorn workers (WEB_CONCURRENCY=2) safe — Postgres, not a lock
-- in the application, decides who runs what, and a lease with a reaper means a
-- worker that crashes mid-job doesn't strand it forever.
--
-- Run this in the Supabase SQL editor. Every statement is IF NOT EXISTS,
-- CREATE OR REPLACE, or ADD COLUMN IF NOT EXISTS, so running it twice is safe.

CREATE TABLE IF NOT EXISTS processing_jobs (
    id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id           UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,

    -- 'upload' | 'arxiv'
    source_type       VARCHAR(20) NOT NULL,
    arxiv_id          VARCHAR(50),
    -- Staged PDF under uploads/jobs/<id>.pdf. Nulled once the worker deletes it.
    source_path       TEXT,
    -- Cheap pre-flight duplicate check, and the same key
    -- core/pipeline/processing_cache.py already hashes results by.
    source_sha256     CHAR(64),
    original_filename TEXT,

    -- What the notification tray says before anything has been extracted: the
    -- arXiv title (looked up synchronously at enqueue time) or the filename.
    -- Replaced with the real title once the pipeline recovers one.
    display_title     TEXT NOT NULL,

    -- 'queued' | 'running' | 'succeeded' | 'failed' | 'duplicate' | 'cancelled'
    status            VARCHAR(20) NOT NULL DEFAULT 'queued',
    -- Coarse phase for the tray: queued | fetching | extracting | analysing | saving.
    -- Deliberately not a percentage — the orchestrator has no notion of one,
    -- and a fabricated bar is exactly what this migration replaces
    -- (HomePage.jsx used to advance a stage indicator on a plain setTimeout,
    -- unrelated to what the server was actually doing).
    stage             VARCHAR(30) NOT NULL DEFAULT 'queued',

    -- Lower runs first. 0 = interactive (Home, Discover), 10 = batch,
    -- -10 = reserved for the deprecated synchronous wrapper routes — a request
    -- with a caller blocked on the HTTP response must not wait behind a
    -- ten-paper batch someone else queued first.
    priority          SMALLINT NOT NULL DEFAULT 0,
    batch_id          UUID,

    attempts          SMALLINT NOT NULL DEFAULT 0,
    max_attempts      SMALLINT NOT NULL DEFAULT 2,

    -- Fencing. Every write a worker makes carries `claimed_by`, so a worker
    -- whose lease was reaped and reassigned can't overwrite the job its
    -- replacement is now running (see heartbeat_processing_job below).
    claimed_by        TEXT,
    lease_expires_at  TIMESTAMPTZ,

    result_summary_id UUID REFERENCES summaries(id) ON DELETE SET NULL,
    error_code        VARCHAR(50),
    error_message     TEXT,

    -- 'arxiv:2106.09685' or 'sha256:<hex>' — backs the partial unique index
    -- below, which is what stops a double-click on Discover's Add button (or
    -- queueing a paper that's already mid-pipeline) from paying for the
    -- pipeline twice.
    dedupe_key        TEXT,

    created_at        TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at        TIMESTAMPTZ,
    finished_at       TIMESTAMPTZ,
    -- Acknowledged by the user: the tray stops showing it. The row stays —
    -- this is a dismissal, not a delete.
    dismissed_at      TIMESTAMPTZ
);

-- The claim query's exact shape. Partial, so it stays small regardless of how
-- many finished jobs accumulate.
CREATE INDEX IF NOT EXISTS idx_processing_jobs_claim
    ON processing_jobs (priority ASC, created_at ASC)
    WHERE status = 'queued';

-- The reaper's scan, folded into every claim call rather than run as a
-- separate scheduled task.
CREATE INDEX IF NOT EXISTS idx_processing_jobs_lease
    ON processing_jobs (lease_expires_at)
    WHERE status = 'running';

-- The tray's poll: this user's active and recently-finished jobs.
CREATE INDEX IF NOT EXISTS idx_processing_jobs_user_recent
    ON processing_jobs (user_id, created_at DESC);

-- Jobs within one submitted batch, for BatchPage to reconstruct progress after
-- a reload.
CREATE INDEX IF NOT EXISTS idx_processing_jobs_batch
    ON processing_jobs (batch_id)
    WHERE batch_id IS NOT NULL;

-- One live job per (user, paper). Partial, so re-processing a paper next month
-- is still allowed — only a paper already queued or running is blocked.
CREATE UNIQUE INDEX IF NOT EXISTS uq_processing_jobs_active_dedupe
    ON processing_jobs (user_id, dedupe_key)
    WHERE status IN ('queued', 'running') AND dedupe_key IS NOT NULL;

-- Cheap pre-flight duplicate detection at enqueue time — before the pipeline
-- runs, not after. The pgvector near-duplicate check in the pipeline is
-- necessarily post-hoc (it needs an extracted abstract to embed, which costs
-- the whole run); this one catches the case users actually hit — the same
-- arXiv id, or the byte-identical PDF — for the price of an index lookup.
ALTER TABLE summaries
    ADD COLUMN IF NOT EXISTS source_sha256 CHAR(64);

CREATE INDEX IF NOT EXISTS idx_summaries_user_sha
    ON summaries (user_id, source_sha256)
    WHERE source_sha256 IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_summaries_user_arxiv
    ON summaries (user_id, arxiv_id)
    WHERE arxiv_id IS NOT NULL;


-- ── Claim ────────────────────────────────────────────────────────────────────
-- Reap expired leases, then claim one job. Both in a single round trip because
-- the reaper has no other natural home: a separate scheduled task is one more
-- process to run and one more thing to forget, and every poll from a worker is
-- already an opportunity to do it.
CREATE OR REPLACE FUNCTION claim_processing_job(
    p_worker_id     TEXT,
    p_lease_seconds INTEGER DEFAULT 900,
    p_max_per_user  INTEGER DEFAULT 2
) RETURNS SETOF processing_jobs
LANGUAGE plpgsql AS $$
BEGIN
    -- A worker that was killed mid-pipeline left its row 'running' forever.
    -- Past the lease, the job is requeued for another attempt, or — once
    -- max_attempts is exhausted — declared abandoned rather than retried
    -- indefinitely against whatever keeps crashing the extractor on it.
    UPDATE processing_jobs j
       SET status = CASE WHEN j.attempts >= j.max_attempts THEN 'failed' ELSE 'queued' END,
           error_code = CASE WHEN j.attempts >= j.max_attempts
                             THEN 'abandoned' ELSE j.error_code END,
           error_message = CASE WHEN j.attempts >= j.max_attempts
                                THEN 'Processing was interrupted and did not recover.'
                                ELSE j.error_message END,
           finished_at = CASE WHEN j.attempts >= j.max_attempts THEN now() ELSE NULL END,
           stage = 'queued',
           claimed_by = NULL,
           lease_expires_at = NULL
     WHERE j.status = 'running'
       AND j.lease_expires_at < now();

    RETURN QUERY
    UPDATE processing_jobs j
       SET status           = 'running',
           stage            = 'fetching',
           attempts         = j.attempts + 1,
           claimed_by       = p_worker_id,
           started_at       = COALESCE(j.started_at, now()),
           lease_expires_at = now() + make_interval(secs => p_lease_seconds)
     WHERE j.id = (
        SELECT c.id
          FROM processing_jobs c
         WHERE c.status = 'queued'
           -- Fairness and quota protection in one clause: one user's ten-paper
           -- batch can't occupy every slot, so a second user's single paper is
           -- never stuck behind it.
           AND (SELECT count(*) FROM processing_jobs r
                 WHERE r.user_id = c.user_id AND r.status = 'running') < p_max_per_user
         ORDER BY c.priority ASC, c.created_at ASC
           FOR UPDATE OF c SKIP LOCKED
         LIMIT 1
     )
    RETURNING j.*;
END;
$$;

-- ── Heartbeat ────────────────────────────────────────────────────────────────
-- Returns FALSE when the lease was lost — the reaper above already requeued
-- the job and someone else may own it now. The worker must then abandon its
-- run without writing anything further, or two pipelines could both insert a
-- summary row for the same paper.
CREATE OR REPLACE FUNCTION heartbeat_processing_job(
    p_job_id UUID, p_worker_id TEXT, p_lease_seconds INTEGER DEFAULT 900
) RETURNS BOOLEAN
LANGUAGE plpgsql AS $$
DECLARE v_ok BOOLEAN;
BEGIN
    UPDATE processing_jobs
       SET lease_expires_at = now() + make_interval(secs => p_lease_seconds)
     WHERE id = p_job_id AND claimed_by = p_worker_id AND status = 'running';
    GET DIAGNOSTICS v_ok = ROW_COUNT;
    RETURN v_ok;
END;
$$;

-- ── Release ──────────────────────────────────────────────────────────────────
-- Graceful shutdown path: hands the job back immediately rather than making
-- the next worker wait out a fifteen-minute lease for work nobody is doing.
CREATE OR REPLACE FUNCTION release_processing_job(p_job_id UUID, p_worker_id TEXT)
RETURNS VOID
LANGUAGE sql AS $$
    UPDATE processing_jobs
       SET status = 'queued', stage = 'queued',
           claimed_by = NULL, lease_expires_at = NULL
     WHERE id = p_job_id AND claimed_by = p_worker_id AND status = 'running';
$$;

-- Job completion needs no RPC — a plain PostgREST
-- `.update(...).eq('id', job_id).eq('claimed_by', worker_id)` carries the same
-- fencing predicate as the functions above.
