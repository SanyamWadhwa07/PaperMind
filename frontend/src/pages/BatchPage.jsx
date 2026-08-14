import { useState } from 'react'
import { useToast } from '../contexts/ToastContext'
import ComparisonTable from '../components/ComparisonTable'
import {
  Upload, Search, X, BarChart2, FileText, CheckCircle2, AlertCircle, Circle
} from 'lucide-react'
import { batch, papers } from '../lib/api'
import { invalidate } from '../lib/query'
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
  processing: <Spinner size="sm" className="text-accent" />,
  done: <CheckCircle2 className="h-4 w-4 text-success" />,
  error: <AlertCircle className="h-4 w-4 text-danger" />,
}

/** Matches the server's cap in `BatchCompareRequest` — over ten, the comparison
 *  request is rejected by validation before it reaches the service. */
const MAX_QUEUE = 10

export default function BatchPage() {
  const toast = useToast()

  // arXiv search
  const [arxivQuery, setArxivQuery] = useState('')
  const [searchResults, setSearchResults] = useState([])
  const [searching, setSearching] = useState(false)

  // queue: [{id?, arxivId?, title, status, summaryId?}]
  const [queue, setQueue] = useState([])
  const [processing, setProcessing] = useState(false)

  // comparison
  const [comparing, setComparing] = useState(false)
  const [comparisonData, setComparisonData] = useState(null)

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
      { id: crypto.randomUUID(), arxivId: paper.arxiv_id, title: paper.title, status: 'pending', summaryId: null },
    ])
    setComparisonData(null)
  }

  const removeFromQueue = (id) => {
    setQueue((prev) => prev.filter((q) => q.id !== id))
    setComparisonData(null)
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

    // One functional update for the whole selection. The previous version
    // called setQueue per file while testing `queue.length` from the render
    // closure, so that length never moved: selecting 15 PDFs at once passed the
    // cap check 15 times and queued all of them.
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
          status: 'pending',
          summaryId: null,
        })),
      ]
    })
    if (overflow) {
      toast.error(`Queue holds ${MAX_QUEUE} papers — ${overflow} left out`)
    }
    setComparisonData(null)
  }

  // ── process one item ─────────────────────────────────────────────────────────
  /** Resolves to true when the paper was summarised and saved. */
  const processItem = async (item) => {
    setQueue((prev) => prev.map((q) => q.id === item.id ? { ...q, status: 'processing' } : q))
    try {
      // The upload field is named `file` to match the API; sending `pdf` was
      // rejected with a validation error before it ever reached the pipeline.
      const data = item.file
        ? await papers.processUpload(item.file)
        : await papers.processArxiv(item.arxivId)

      const summaryId = data?.summary_id || data?.id
      if (!summaryId) {
        // A 2xx with no id means the row was never written. Recording it as
        // done produced a queue item that looked finished but could not be
        // opened, and silently shrank the comparison below the two-paper floor.
        throw new Error('Processed, but no summary was saved')
      }
      setQueue((prev) =>
        prev.map((q) => q.id === item.id ? { ...q, status: 'done', summaryId } : q)
      )
      return true
    } catch (error) {
      setQueue((prev) =>
        prev.map((q) =>
          q.id === item.id
            ? { ...q, status: 'error', error: error.message || 'Processing failed' }
            : q,
        ),
      )
      return false
    }
  }

  // ── process all pending ───────────────────────────────────────────────────────
  const processBatch = async () => {
    const pending = queue.filter((q) => q.status === 'pending')
    if (!pending.length) {
      toast.error('No pending papers to process')
      return
    }
    setComparisonData(null)
    setProcessing(true)

    // Sequential on purpose. Each paper runs a full LLM pipeline, so firing the
    // whole queue at once burns through provider rate limits and every request
    // fails together.
    let ok = 0
    try {
      for (const item of pending) {
        if (await processItem(item)) ok += 1
      }
    } finally {
      setProcessing(false)
    }

    // Every paper in the queue is a new row, so the library, the corpus graphs,
    // and the dashboard counts are all stale now.
    invalidate('summaries')
    invalidate('corpus')
    invalidate('graph')

    // This reported success unconditionally, so a batch where all ten papers
    // failed still ended on "Batch processing complete".
    const failed = pending.length - ok
    if (!ok) {
      toast.error(`All ${failed} papers failed to process`)
    } else if (failed) {
      toast.info(`${ok} of ${pending.length} processed — ${failed} failed`)
    } else {
      toast.success(`Processed ${ok} paper${ok === 1 ? '' : 's'}`)
    }
  }

  // ── compare all done papers ───────────────────────────────────────────────────
  const compareAll = async () => {
    const ids = queue.filter((q) => q.status === 'done' && q.summaryId).map((q) => q.summaryId)
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

  const doneCount = queue.filter((q) => q.status === 'done').length
  const pendingCount = queue.filter((q) => q.status === 'pending').length
  const errorCount = queue.filter((q) => q.status === 'error').length

  return (
    <div className="animate-rise mx-auto max-w-6xl space-y-8 3xl:max-w-7xl">
      <header className="border-b border-line pb-6">
        <Eyebrow className="block">Many at once</Eyebrow>
        <h1 className="display mt-2 text-display-sm text-ink">Batch</h1>
        <p className="mt-2 max-w-prose text-sm text-ink-muted">
          Queue up to ten papers. They run one at a time, and once they are done
          you can compare what each of them measured.
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
            description={
              [
                `${queue.length} of ${MAX_QUEUE} slots used`,
                doneCount ? `${doneCount} done` : null,
                errorCount ? `${errorCount} failed` : null,
              ]
                .filter(Boolean)
                .join(' · ')
            }
            action={
              <div className="flex shrink-0 gap-2">
                {pendingCount > 0 && (
                  <Button size="sm" onClick={processBatch} loading={processing}>
                    Process {pendingCount}
                  </Button>
                )}
                {doneCount >= 2 && (
                  <Button
                    size="sm"
                    variant="contrast"
                    onClick={compareAll}
                    loading={comparing}
                    // Comparing halfway through a run compares half a batch and
                    // caches the result as if it were the whole thing.
                    disabled={processing}
                  >
                    <BarChart2 className="h-3.5 w-3.5" aria-hidden="true" />
                    Compare {doneCount}
                  </Button>
                )}
              </div>
            }
          />
          {/* Ten rows is taller than it looks once errors wrap, and the queue
              sits above the comparison it produces — letting it grow pushes the
              actual result off-screen. */}
          <ScrollArea maxHeight="22rem" aria-label="Processing queue">
            <CardBody className="py-0">
              <ul className="divide-y divide-line">
                {queue.map((item) => (
                  <li key={item.id} className="flex items-center gap-3 py-3">
                    <span className="flex h-4 w-4 shrink-0 items-center justify-center">
                      {STATUS_ICON[item.status] || (
                        <Circle className="h-3.5 w-3.5 text-ink-faint" aria-hidden="true" />
                      )}
                    </span>
                    <span
                      className="min-w-0 flex-1 truncate font-serif text-sm text-ink"
                      title={item.title}
                    >
                      {item.title}
                    </span>
                    {item.status === 'error' && (
                      <span
                        className="max-w-[16rem] shrink-0 truncate text-caption text-danger"
                        title={item.error}
                      >
                        {item.error}
                      </span>
                    )}
                    {item.status === 'done' && item.summaryId && (
                      <a
                        href={`/summary/${item.summaryId}`}
                        className="shrink-0 text-caption text-accent hover:underline"
                        target="_blank"
                        rel="noreferrer"
                      >
                        Open
                      </a>
                    )}
                    {item.status !== 'processing' && (
                      <button
                        type="button"
                        onClick={() => removeFromQueue(item.id)}
                        className="shrink-0 rounded-sm p-1 text-ink-faint transition-colors duration-fast ease-out hover:text-danger disabled:opacity-40"
                        // Removing a queued paper mid-run drops it from the loop
                        // already iterating over it.
                        disabled={processing}
                        aria-label={`Remove ${item.title}`}
                      >
                        <X className="h-4 w-4" />
                      </button>
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
