/**
 * Module-level store for background paper-processing jobs.
 *
 * A sibling of `query.js`, not an extension of it and not a React context:
 *
 * - `query.js` is a read-through *cache* — TTL, LRU eviction, `MAX_ENTRIES`. A
 *   processing job list is none of those things; it needs a polling timer,
 *   visibility handling and an auth-reset, none of which belong in the module
 *   whose entire value is doing one small thing correctly.
 * - A React context would re-render its whole subtree on every poll tick.
 *   `useSyncExternalStore` (the same primitive `useQuery.js` is built on) only
 *   re-renders actual subscribers, and a module store can also be read from
 *   non-component code (`enqueueUpload` etc., callable from anywhere).
 *
 * This is also the one place that reliably calls `invalidate()` after a paper
 * finishes processing. Before this store existed, that call was scattered
 * across three pages — BatchPage and DiscoverPage did it, HomePage never did,
 * so summarising a paper from the landing page left /dashboard, /timeline and
 * /explore serving pre-upload data for up to five minutes.
 */
import { useSyncExternalStore } from 'react'
import toast from 'react-hot-toast'

import { jobs as jobsApi } from './api'
import { invalidate } from './query'

/** id -> job row (the shape _job_public returns from the backend). */
const store = new Map()

/** Rebuilt only on write — a fresh array every getSnapshot() call would make
 *  useSyncExternalStore re-render in a loop (the same trap useQuery.js documents). */
let snapshot = []

const listeners = new Set()

let pollTimer = null
let pollInFlight = false
let visibilityBound = false

function rebuildSnapshot() {
  snapshot = Array.from(store.values()).sort(
    (a, b) => new Date(b.created_at) - new Date(a.created_at),
  )
}

function notify() {
  for (const fn of listeners) fn()
}

function isTerminal(status) {
  return status === 'succeeded' || status === 'failed' || status === 'duplicate' || status === 'cancelled'
}

/** Merge a fresh list of rows from the server into the store, firing toasts
 *  and cache invalidation for anything that newly went terminal. */
function reconcile(rows) {
  const seenIds = new Set()

  for (const row of rows) {
    seenIds.add(row.id)
    const prev = store.get(row.id)
    store.set(row.id, row)

    if (prev && !isTerminal(prev.status) && isTerminal(row.status)) {
      onTransitionToTerminal(row)
    }
  }

  // A job absent from the server's active/recent window (dismissed, or aged
  // out) shouldn't linger locally.
  for (const id of store.keys()) {
    if (!seenIds.has(id)) store.delete(id)
  }

  rebuildSnapshot()
  notify()
}

function onTransitionToTerminal(job) {
  if (job.status === 'succeeded') {
    // 'summaries' covers the per-paper key too (['summaries', id]) — invalidate
    // prefix-matches, so there's no separate cache entry to prime or clear here.
    invalidate('summaries')
    invalidate('corpus')
    invalidate('graph')
    toast.success(`"${job.display_title}" is ready`)
  } else if (job.status === 'duplicate') {
    toast(`"${job.display_title}" is already in your library`, { icon: 'ℹ️' })
  } else if (job.status === 'failed') {
    toast.error(`"${job.display_title}" failed: ${job.error_message || 'processing error'}`)
  }
}

// ── Polling ──────────────────────────────────────────────────────────────────

function nextInterval() {
  const rows = snapshot
  if (rows.some((j) => j.status === 'running')) return 2000
  if (rows.some((j) => j.status === 'queued')) return 6000
  return null // nothing active — stop polling until something is enqueued
}

async function pollOnce() {
  if (pollInFlight) return
  pollInFlight = true
  try {
    // Deliberately *not* `{ active: true }` — that filter excludes terminal
    // jobs entirely, so a job would vanish from the response the instant it
    // finished, with no chance for this store to ever see the transition and
    // fire its toast. The unfiltered "recent" list (last 24h, server-side)
    // includes queued/running/just-finished together, which is what makes
    // reconcile()'s prev-vs-next status comparison able to detect "went
    // terminal" at all.
    const { jobs: rows } = await jobsApi.list()
    reconcile(rows)
  } catch {
    // A transient failure here just means the tray is stale for one tick —
    // not worth surfacing as an error toast on top of whatever the user is doing.
  } finally {
    pollInFlight = false
    scheduleNext()
  }
}

function scheduleNext() {
  clearTimeout(pollTimer)
  pollTimer = null
  if (document.hidden) return // resumes on visibilitychange, see below
  const interval = nextInterval()
  if (interval == null) return // nothing to watch — idle until enqueue() kicks it
  pollTimer = setTimeout(pollOnce, interval)
}

function kick() {
  clearTimeout(pollTimer)
  pollTimer = null
  pollOnce()
}

function handleVisibilityChange() {
  if (!document.hidden) {
    kick()
  }
}

export function startProcessingPoller() {
  if (!visibilityBound) {
    document.addEventListener('visibilitychange', handleVisibilityChange)
    visibilityBound = true
  }
  kick()
}

export function stopProcessingPoller() {
  clearTimeout(pollTimer)
  pollTimer = null
  if (visibilityBound) {
    document.removeEventListener('visibilitychange', handleVisibilityChange)
    visibilityBound = false
  }
  store.clear()
  rebuildSnapshot()
  notify()
}

// ── React ────────────────────────────────────────────────────────────────────

export function subscribeProcessingJobs(callback) {
  listeners.add(callback)
  return () => listeners.delete(callback)
}

export function getProcessingJobsSnapshot() {
  return snapshot
}

/** All non-dismissed jobs from the last poll, newest first. */
export function useProcessingJobs() {
  return useSyncExternalStore(subscribeProcessingJobs, getProcessingJobsSnapshot)
}

/** The job for one arXiv id, or undefined — for a per-item "already queued"
 *  busy indicator (HomePage's search results, DiscoverPage's cards). */
export function useJobFor(arxivId) {
  const rows = useProcessingJobs()
  if (!arxivId) return undefined
  return rows.find(
    (j) => j.arxiv_id === arxivId && (j.status === 'queued' || j.status === 'running'),
  )
}

// ── Mutations ────────────────────────────────────────────────────────────────

function insertOptimistic(job) {
  store.set(job.id, job)
  rebuildSnapshot()
  notify()
  startProcessingPoller()
}

export async function enqueueUpload(file, { onProgress } = {}) {
  const { job } = await jobsApi.enqueueUpload(file, { onProgress })
  insertOptimistic(job)
  return job
}

export async function enqueueArxiv(arxivId, { priority } = {}) {
  const { job } = await jobsApi.enqueueArxiv(arxivId, priority)
  insertOptimistic(job)
  return job
}

/** Reprocessing deletes the existing summary server-side (see the route's
 *  docstring), so the caller should navigate away from it immediately —
 *  the id this returns is a brand-new job/paper, not the old one. */
export async function reprocessPaper(summaryId) {
  const { job } = await jobsApi.reprocess(summaryId)
  insertOptimistic(job)
  invalidate('summaries')
  return job
}

export async function enqueueArxivBatch(arxivIds) {
  const result = await jobsApi.enqueueBatch(arxivIds)
  for (const job of result.jobs) {
    store.set(job.id, job)
  }
  rebuildSnapshot()
  notify()
  startProcessingPoller()
  return result
}

// The backend's DELETE /process/jobs/{id} disambiguates by status: cancels a
// queued job, dismisses a terminal one, and 409s on a running one. Both names
// exist here because the tray shows two different buttons (Cancel vs. ✕
// dismiss) for two different states, but they're the same call.

export async function cancelJob(id) {
  await jobsApi.remove(id)
  store.delete(id)
  rebuildSnapshot()
  notify()
}

export const dismissJob = cancelJob
