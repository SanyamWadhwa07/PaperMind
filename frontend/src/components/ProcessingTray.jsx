import { useEffect, useMemo, useState } from 'react'
import { CheckCircle2, ChevronDown, ChevronUp, XCircle } from 'lucide-react'
import { Badge, Button, Card, CardBody, ScrollArea, Spinner, cx } from './ui/primitives'
import { useProcessingJobs, cancelJob, dismissJob, enqueueArxiv } from '../lib/processingStore'

const STAGE_LABEL = {
  queued: 'Queued',
  fetching: 'Fetching',
  extracting: 'Extracting',
  analysing: 'Analysing',
  saving: 'Saving',
  succeeded: 'Done',
  failed: 'Failed',
  duplicate: 'Already in library',
  cancelled: 'Cancelled',
}

const TERMINAL = new Set(['succeeded', 'failed', 'duplicate', 'cancelled'])

/** How long a job's row stays in the tray after finishing, once *every* job
 *  in the batch is terminal — long enough to read, short enough to clear itself. */
const AUTO_HIDE_MS = 8000

function elapsed(job) {
  const start = job.started_at || job.created_at
  if (!start) return null
  const seconds = Math.max(0, Math.floor((Date.now() - new Date(start).getTime()) / 1000))
  if (seconds < 60) return `${seconds}s`
  return `${Math.floor(seconds / 60)}m ${seconds % 60}s`
}

function StatusIcon({ status }) {
  if (status === 'succeeded') return <CheckCircle2 className="h-4 w-4 shrink-0 text-success" aria-hidden="true" />
  if (status === 'failed') return <XCircle className="h-4 w-4 shrink-0 text-danger" aria-hidden="true" />
  if (status === 'duplicate') return <CheckCircle2 className="h-4 w-4 shrink-0 text-ink-faint" aria-hidden="true" />
  if (status === 'cancelled') return <XCircle className="h-4 w-4 shrink-0 text-ink-faint" aria-hidden="true" />
  return <Spinner size="sm" className="shrink-0 text-accent" />
}

function JobRow({ job }) {
  const [, forceTick] = useState(0)
  // Re-render once a second so the elapsed-time readout for a running job
  // actually moves — nothing else touches this row between polls.
  useEffect(() => {
    if (TERMINAL.has(job.status)) return
    const id = setInterval(() => forceTick((n) => n + 1), 1000)
    return () => clearInterval(id)
  }, [job.status])

  return (
    <div className="flex items-start gap-3 px-4 py-3">
      <StatusIcon status={job.status} />
      <div className="min-w-0 flex-1">
        <p className="truncate font-serif text-sm text-ink" title={job.display_title}>
          {job.display_title}
        </p>
        <div className="mt-0.5 flex items-center gap-2 text-code text-ink-faint">
          <span>{STAGE_LABEL[job.stage] || STAGE_LABEL[job.status] || job.stage}</span>
          {elapsed(job) && <span className="font-mono tabular">· {elapsed(job)}</span>}
        </div>
        {job.status === 'failed' && job.error_message && (
          <p className="mt-1 line-clamp-2 text-code text-danger">{job.error_message}</p>
        )}
      </div>

      <div className="flex shrink-0 items-center gap-1.5">
        {job.status === 'queued' && (
          <Button variant="ghost" size="sm" onClick={() => cancelJob(job.id)}>
            Cancel
          </Button>
        )}
        {(job.status === 'succeeded' || job.status === 'duplicate') && job.result_summary_id && (
          <Button to={`/summary/${job.result_summary_id}`} variant="ghost" size="sm">
            Open
          </Button>
        )}
        {job.status === 'failed' && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() =>
              job.source_type === 'arxiv' && job.arxiv_id
                ? enqueueArxiv(job.arxiv_id)
                : dismissJob(job.id)
            }
          >
            Retry
          </Button>
        )}
        {TERMINAL.has(job.status) && (
          <button
            type="button"
            onClick={() => dismissJob(job.id)}
            aria-label="Dismiss"
            className="rounded p-1 text-ink-faint transition-colors hover:bg-surface-hover hover:text-ink"
          >
            <XCircle className="h-3.5 w-3.5" aria-hidden="true" />
          </button>
        )}
      </div>
    </div>
  )
}

export default function ProcessingTray() {
  const jobs = useProcessingJobs()
  const [expanded, setExpanded] = useState(false)
  const [hiddenAt, setHiddenAt] = useState(null)

  const allTerminal = jobs.length > 0 && jobs.every((j) => TERMINAL.has(j.status))
  const runningCount = jobs.filter((j) => j.status === 'running').length
  const queuedCount = jobs.filter((j) => j.status === 'queued').length

  // Auto-hide the tray a few seconds after everything in it finished — not
  // sooner, or a fast job's success flashes and vanishes before it's readable.
  useEffect(() => {
    if (!allTerminal) {
      setHiddenAt(null)
      return
    }
    const timer = setTimeout(() => setHiddenAt(Date.now()), AUTO_HIDE_MS)
    return () => clearTimeout(timer)
  }, [allTerminal, jobs.length])

  const visible = jobs.length > 0 && !hiddenAt

  const headline = useMemo(() => {
    if (runningCount + queuedCount === 0) {
      const done = jobs.filter((j) => j.status === 'succeeded').length
      const failed = jobs.filter((j) => j.status === 'failed').length
      if (failed && !done) return `${failed} paper${failed === 1 ? '' : 's'} failed`
      if (failed) return `${done} ready · ${failed} failed`
      return `${done} paper${done === 1 ? '' : 's'} ready`
    }
    const active = jobs.find((j) => j.status === 'running') || jobs.find((j) => j.status === 'queued')
    const rest = jobs.length - 1
    const base = `Summarising "${active?.display_title || ''}"`
    return rest > 0 ? `${base} +${rest} more` : base
  }, [jobs, runningCount, queuedCount])

  if (!visible) return null

  return (
    <div
      className="fixed right-4 top-16 z-40 w-[22rem] max-w-[calc(100vw-2rem)]"
      role="status"
      aria-live="polite"
    >
      <Card className="shadow-lg">
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="flex w-full items-center gap-2.5 px-4 py-3 text-left"
          aria-expanded={expanded}
        >
          {runningCount + queuedCount > 0 ? (
            <Spinner size="sm" className="shrink-0 text-accent" />
          ) : (
            <CheckCircle2 className="h-4 w-4 shrink-0 text-success" aria-hidden="true" />
          )}
          <span className="min-w-0 flex-1 truncate text-sm font-medium text-ink">{headline}</span>
          {jobs.length > 1 && (
            <Badge tone="neutral" mono>
              {jobs.length}
            </Badge>
          )}
          {expanded ? (
            <ChevronDown className="h-4 w-4 shrink-0 text-ink-faint" aria-hidden="true" />
          ) : (
            <ChevronUp className="h-4 w-4 shrink-0 text-ink-faint" aria-hidden="true" />
          )}
        </button>

        {expanded && (
          <ScrollArea maxHeight="18rem" aria-label="Processing jobs" className="border-t border-line">
            <CardBody className={cx('divide-y divide-line p-0')}>
              {jobs.map((job) => (
                <JobRow key={job.id} job={job} />
              ))}
            </CardBody>
          </ScrollArea>
        )}
      </Card>
    </div>
  )
}

/**
 * A real upload-progress bar, salvaged from the deleted `ProcessingModal`
 * (which had this right, just behind a full-screen blocking overlay). The
 * job doesn't exist yet while the multipart body is still uploading — there's
 * nothing in `processingStore` to drive off of — so the caller (HomePage)
 * owns the percentage locally via `enqueueUpload(file, { onProgress })` and
 * renders this inline until the POST resolves into a real job.
 */
export function UploadProgressRow({ progress }) {
  return (
    <div
      role="progressbar"
      aria-valuenow={progress}
      aria-valuemin={0}
      aria-valuemax={100}
      className="h-1 overflow-hidden rounded-full bg-surface-sunk"
    >
      <div className="h-full rounded-full bg-accent transition-all" style={{ width: `${progress}%` }} />
    </div>
  )
}
