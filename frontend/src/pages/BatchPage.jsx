import { useState } from 'react'
import { useToast } from '../contexts/ToastContext'
import ComparisonTable from '../components/ComparisonTable'
import {
  Upload, Search, X, BarChart2, FileText, CheckCircle2, AlertCircle, Circle
} from 'lucide-react'
import { batch, papers } from '../lib/api'
import { enqueueArxivBatch, enqueueUpload, useProcessingJobs } from '../lib/processingStore'
import {
  Bento,
  BentoItem,
  Button,
  Card,
  CardBody,
  CardHeader,
  Eyebrow,
  Identifier,
  Input,
  ScrollArea,
  Spinner,
} from '../components/ui/primitives'

const STATUS_ICON = {
  queued: <Circle className="h-3.5 w-3.5 text-ink-faint" aria-hidden="true" />,
  running: <Spinner size="sm" className="text-accent" />,
  succeeded: <CheckCircle2 className="h-4 w-4 text-success" aria-hidden="true" />,
  failed: <AlertCircle className="h-4 w-4 text-danger" aria-hidden="true" />,
  duplicate: <CheckCircle2 className="h-4 w-4 text-ink-faint" aria-hidden="true" />,
  cancelled: <AlertCircle className="h-4 w-4 text-ink-faint" aria-hidden="true" />,
}

/** Matches the server's cap in `BatchCompareRequest` — over ten, the comparison
 *  request is rejected by validation before it reaches the service. */
const MAX_QUEUE = 10

/** Remembers which jobs belong to "this" batch across a reload — the jobs
 *  themselves live server-side (`processingStore` polls `GET /process/jobs`
 *  regardless of this page), but without this the submitted-status view had
 *  no way to know which of those rows were this page's, so a reload silently
 *  reset the batch to empty. */
const STORAGE_KEY = 'papermind:batch-submission'

function loadSubmission() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    const parsed = raw ? JSON.parse(raw) : null
    return parsed && Array.isArray(parsed.jobIds) ? parsed : null
  } catch {
    return null
  }
}

function saveSubmission(submission) {
  try {
    if (submission) localStorage.setItem(STORAGE_KEY, JSON.stringify(submission))
    else localStorage.removeItem(STORAGE_KEY)
  } catch {
    // Private browsing / storage full — the batch just won't survive a reload.
  }
}

export default function BatchPage() {
  const toast = useToast()

  // arXiv search
  const [arxivQuery, setArxivQuery] = useState('')
  const [searchResults, setSearchResults] = useState([])
  const [searching, setSearching] = useState(false)

  // Pre-submission staging list: [{id, arxivId?, file?, title}]. Nothing here
  // has a status of its own — items just sit until Queue is pressed, at which
  // point the pipeline runs server-side and this list is cleared in favor of
  // the submitted-jobs view below.
  const [queue, setQueue] = useState([])
  const [submitting, setSubmitting] = useState(false)

  // The batch actually sent to the server: which job ids (and, for the arXiv
  // half, which batch_id) to pick out of the global job list polled by
  // processingStore. Persisted so a reload doesn't lose track of it.
  const [submission, setSubmission] = useState(loadSubmission)

  // comparison
  const [comparing, setComparing] = useState(false)
  const [comparisonData, setComparisonData] = useState(null)

  const allJobs = useProcessingJobs()
  const submittedJobs = submission
    ? allJobs
        .filter((j) => j.batch_id === submission.batchId || submission.jobIds.includes(j.id))
        .sort((a, b) => new Date(a.created_at) - new Date(b.created_at))
    : []

  // ── arXiv search ────────────────────────────────────────────────────────────
  const handleSearch = async (e) => {
    e.preventDefault()
    if (!arxivQuery.trim()) return
    setSearching(true)
    setSearchResults([])
    try {
      const data = await papers.search(arxivQuery, 8)
      setSearchResults(data.papers || [])
    } catch (error) {
      toast.error(error.message || 'Search failed')
    } finally {
      setSearching(false)
    }
  }

  // ── add paper to queue ───────────────────────────────────────────────────────
  const addToQueue = (paper) => {
    if (queue.length >= MAX_QUEUE) { toast.error(`Maximum ${MAX_QUEUE} papers per batch`); return }
    // Comparing `arxivId` alone matched two uploaded PDFs against each other,
    // since both carry `undefined` and `undefined === undefined`. Adding an
    // arXiv paper to a queue of uploads was reported as a duplicate.
    if (paper.arxiv_id && queue.some((q) => q.arxivId === paper.arxiv_id)) {
      toast.error('Paper already in queue'); return
    }
    setQueue((prev) => [
      ...prev,
      { id: crypto.randomUUID(), arxivId: paper.arxiv_id, title: paper.title },
    ])
  }

  const removeFromQueue = (id) => {
    setQueue((prev) => prev.filter((q) => q.id !== id))
  }

  // ── PDF upload → queue ───────────────────────────────────────────────────────
  const handleFileUpload = (e) => {
    const files = Array.from(e.target.files || [])
    e.target.value = ''
    if (!files.length) return

    const rejected = files.filter((f) => !f.name.toLowerCase().endsWith('.pdf'))
    const pdfs = files.filter((f) => f.name.toLowerCase().endsWith('.pdf'))
    if (rejected.length) {
      toast.error(
        rejected.length === 1
          ? `${rejected[0].name} is not a PDF`
          : `${rejected.length} files skipped — not PDFs`,
      )
    }

    // One functional update for the whole selection. A version that called
    // setQueue per file while testing `queue.length` from the render closure
    // would never see that length move: selecting 15 PDFs at once would pass
    // the cap check 15 times and queue all of them.
    let overflow = 0
    setQueue((prev) => {
      const room = MAX_QUEUE - prev.length
      overflow = Math.max(0, pdfs.length - room)
      return [
        ...prev,
        ...pdfs.slice(0, room).map((file) => ({
          id: crypto.randomUUID(),
          file,
          title: file.name.replace(/\.pdf$/i, ''),
        })),
      ]
    })
    if (overflow) {
      toast.error(`Queue holds ${MAX_QUEUE} papers — ${overflow} left out`)
    }
  }

  // ── submit the whole staging list ────────────────────────────────────────────
  // Enqueues and returns almost immediately — the pipeline runs in the
  // background (see the processing tray) — so unlike the old sequential
  // per-item loop, this is one round trip for the arXiv half (one batch_id)
  // plus one parallel round trip per upload, not a loop that burns through
  // provider rate limits waiting on a full pipeline run per item.
  const handleSubmit = async () => {
    if (!queue.length) { toast.error('Add at least one paper to the queue'); return }
    setSubmitting(true)
    try {
      const arxivItems = queue.filter((q) => q.arxivId)
      const fileItems = queue.filter((q) => q.file)
      const jobIds = []
      let batchId = null

      if (arxivItems.length) {
        const result = await enqueueArxivBatch(arxivItems.map((q) => q.arxivId))
        batchId = result.batch_id
        jobIds.push(...result.jobs.map((j) => j.id))
        if (result.rejected?.length) {
          toast.error(
            `${result.rejected.length} paper${result.rejected.length === 1 ? '' : 's'} skipped — already queued or in your library`,
          )
        }
      }

      if (fileItems.length) {
        const settled = await Promise.allSettled(fileItems.map((q) => enqueueUpload(q.file)))
        let failed = 0
        for (const r of settled) {
          if (r.status === 'fulfilled') jobIds.push(r.value.id)
          else failed += 1
        }
        if (failed) {
          toast.error(`${failed} upload${failed === 1 ? '' : 's'} failed to queue`)
        }
      }

      if (!jobIds.length) {
        toast.error('Nothing was queued')
        return
      }

      const next = { batchId, jobIds }
      setSubmission(next)
      saveSubmission(next)
      setQueue([])
      setComparisonData(null)
      toast.success(`Queued ${jobIds.length} paper${jobIds.length === 1 ? '' : 's'} — track progress in the tray`)
    } finally {
      setSubmitting(false)
    }
  }

  const startNewBatch = () => {
    setSubmission(null)
    saveSubmission(null)
    setComparisonData(null)
  }

  // ── compare all done papers ───────────────────────────────────────────────────
  const doneJobs = submittedJobs.filter((j) => j.status === 'succeeded' && j.result_summary_id)
  const compareAll = async () => {
    const ids = doneJobs.map((j) => j.result_summary_id)
    if (ids.length < 2) { toast.error('Need at least 2 processed papers to compare'); return }
    setComparing(true)
    setComparisonData(null)
    try {
      setComparisonData(await batch.compare(ids))
    } catch (error) {
      toast.error(error.message || 'Comparison failed')
    } finally {
      setComparing(false)
    }
  }

  const activeCount = submittedJobs.filter((j) => j.status === 'queued' || j.status === 'running').length
  const failedCount = submittedJobs.filter((j) => j.status === 'failed').length

  return (
    <div className="animate-rise mx-auto max-w-6xl space-y-8 3xl:max-w-7xl">
      <header className="border-b border-line pb-6">
        <Eyebrow className="block">Many at once</Eyebrow>
        <h1 className="display mt-2 text-display-sm text-ink">Batch</h1>
        <p className="mt-2 max-w-prose text-sm text-ink-muted">
          Queue up to ten papers. They process in the background — track
          progress in the tray, top right — and once they&apos;re done you can
          compare what each of them measured.
        </p>
      </header>

      <Bento>
        <BentoItem span={3} as={Card} className="flex flex-col">
          <CardHeader title="Search arXiv" />
          <CardBody className="flex min-h-0 flex-1 flex-col gap-4">
            <form onSubmit={handleSearch} className="flex gap-2">
              <div className="relative flex-1">
                <Search
                  className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-faint"
                  aria-hidden="true"
                />
                <Input
                  type="text"
                  value={arxivQuery}
                  onChange={(e) => setArxivQuery(e.target.value)}
                  placeholder="attention, BERT, diffusion…"
                  className="pl-10"
                  aria-label="Search arXiv"
                />
              </div>
              <Button type="submit" loading={searching}>
                Search
              </Button>
            </form>

            {searchResults.length > 0 && (
              <ScrollArea maxHeight="14rem" aria-label="Search results" className="-mr-2 pr-2">
                <ul className="space-y-2">
                  {searchResults.map((p) => {
                    const added = queue.some((q) => q.arxivId === p.arxiv_id)
                    return (
                      <li
                        key={p.arxiv_id}
                        className="flex items-start justify-between gap-3 border-b border-line pb-2 last:border-b-0"
                      >
                        <div className="min-w-0">
                          <p
                            className="truncate font-serif text-sm text-ink"
                            title={p.title}
                          >
                            {p.title}
                          </p>
                          <Identifier>{p.arxiv_id}</Identifier>
                        </div>
                        <Button
                          size="sm"
                          variant={added ? 'secondary' : 'primary'}
                          onClick={() => addToQueue(p)}
                          disabled={added}
                          className="shrink-0"
                        >
                          {added ? 'Added' : 'Add'}
                        </Button>
                      </li>
                    )
                  })}
                </ul>
              </ScrollArea>
            )}
          </CardBody>
        </BentoItem>

        <BentoItem span={3}>
          <label className="flex h-full min-h-[200px] cursor-pointer flex-col items-center justify-center gap-3 rounded-lg border-2 border-dashed border-line p-6 text-center transition-colors duration-fast ease-out hover:border-line-strong">
            <div className="flex h-12 w-12 items-center justify-center rounded-lg bg-surface-sunk">
              <Upload className="h-5 w-5 text-ink-faint" aria-hidden="true" />
            </div>
            <div>
              <p className="text-sm font-medium text-ink">Or upload PDFs</p>
              <p className="mt-1 text-caption text-ink-faint">
                Up to {MAX_QUEUE} in the queue
              </p>
            </div>
            <span className="mt-1 inline-flex h-8 items-center rounded border border-line bg-surface px-3 text-caption font-medium text-ink">
              Choose files
            </span>
            <input
              type="file"
              accept="application/pdf,.pdf"
              multiple
              onChange={handleFileUpload}
              className="sr-only"
            />
          </label>
        </BentoItem>
      </Bento>

      {queue.length > 0 && (
        <Card>
          <CardHeader
            title="Queue"
            description={`${queue.length} of ${MAX_QUEUE} slots used`}
            action={
              <Button size="sm" onClick={handleSubmit} loading={submitting}>
                Queue {queue.length}
              </Button>
            }
          />
          <ScrollArea maxHeight="22rem" aria-label="Papers staged for this batch">
            <CardBody className="py-0">
              <ul className="divide-y divide-line">
                {queue.map((item) => (
                  <li key={item.id} className="flex items-center gap-3 py-3">
                    <span
                      className="min-w-0 flex-1 truncate font-serif text-sm text-ink"
                      title={item.title}
                    >
                      {item.title}
                    </span>
                    <button
                      type="button"
                      onClick={() => removeFromQueue(item.id)}
                      className="shrink-0 rounded-sm p-1 text-ink-faint transition-colors duration-fast ease-out hover:text-danger disabled:opacity-40"
                      disabled={submitting}
                      aria-label={`Remove ${item.title}`}
                    >
                      <X className="h-4 w-4" />
                    </button>
                  </li>
                ))}
              </ul>
            </CardBody>
          </ScrollArea>
        </Card>
      )}

      {submission && (
        <Card>
          <CardHeader
            title="Submitted"
            description={
              [
                submittedJobs.length ? `${submittedJobs.length} in this batch` : null,
                activeCount ? `${activeCount} in progress` : null,
                doneJobs.length ? `${doneJobs.length} done` : null,
                failedCount ? `${failedCount} failed` : null,
              ]
                .filter(Boolean)
                .join(' · ') || 'Waiting on the queue…'
            }
            action={
              <div className="flex shrink-0 gap-2">
                {doneJobs.length >= 2 && (
                  <Button
                    size="sm"
                    variant="contrast"
                    onClick={compareAll}
                    loading={comparing}
                  >
                    <BarChart2 className="h-3.5 w-3.5" aria-hidden="true" />
                    Compare {doneJobs.length}
                  </Button>
                )}
                <Button size="sm" variant="secondary" onClick={startNewBatch}>
                  New batch
                </Button>
              </div>
            }
          />
          <ScrollArea maxHeight="22rem" aria-label="Submitted batch status">
            <CardBody className="py-0">
              <ul className="divide-y divide-line">
                {submittedJobs.map((job) => (
                  <li key={job.id} className="flex items-center gap-3 py-3">
                    <span className="flex h-4 w-4 shrink-0 items-center justify-center">
                      {STATUS_ICON[job.status] || (
                        <Circle className="h-3.5 w-3.5 text-ink-faint" aria-hidden="true" />
                      )}
                    </span>
                    <span
                      className="min-w-0 flex-1 truncate font-serif text-sm text-ink"
                      title={job.display_title}
                    >
                      {job.display_title}
                    </span>
                    {job.status === 'failed' && job.error_message && (
                      <span
                        className="max-w-[16rem] shrink-0 truncate text-caption text-danger"
                        title={job.error_message}
                      >
                        {job.error_message}
                      </span>
                    )}
                    {(job.status === 'succeeded' || job.status === 'duplicate') && job.result_summary_id && (
                      <a
                        href={`/summary/${job.result_summary_id}`}
                        className="shrink-0 text-caption text-accent hover:underline"
                        target="_blank"
                        rel="noreferrer"
                      >
                        Open
                      </a>
                    )}
                  </li>
                ))}
              </ul>
            </CardBody>
          </ScrollArea>
        </Card>
      )}

      {comparing && (
        <Card>
          <CardBody className="flex items-center gap-3">
            <Spinner size="sm" className="text-accent" />
            <span className="text-sm text-ink-muted">Building the comparison…</span>
          </CardBody>
        </Card>
      )}

      {comparisonData && (
        <Card>
          <CardHeader
            title="Cross-paper comparison"
            action={<FileText className="h-4 w-4 text-ink-faint" aria-hidden="true" />}
          />
          <CardBody>
            <ComparisonTable data={comparisonData} />
          </CardBody>
        </Card>
      )}
    </div>
  )
}
