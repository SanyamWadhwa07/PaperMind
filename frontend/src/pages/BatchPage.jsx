import { useState } from 'react'
import { useToast } from '../contexts/ToastContext'
import ComparisonTable from '../components/ComparisonTable'
import {
  Upload, Search, X, BarChart2, FileText, CheckCircle2, AlertCircle, Circle
} from 'lucide-react'
import { batch, papers } from '../lib/api'
import {
  Button,
  Card,
  CardBody,
  CardHeader,
  Eyebrow,
  Identifier,
  Input,
  Spinner,
} from '../components/ui/primitives'

const STATUS_ICON = {
  processing: <Spinner size="sm" className="text-accent" />,
  done: <CheckCircle2 className="h-4 w-4 text-success" />,
  error: <AlertCircle className="h-4 w-4 text-danger" />,
}

export default function BatchPage() {
  const toast = useToast()

  // arXiv search
  const [arxivQuery, setArxivQuery] = useState('')
  const [searchResults, setSearchResults] = useState([])
  const [searching, setSearching] = useState(false)

  // queue: [{id?, arxivId?, title, status, summaryId?}]
  const [queue, setQueue] = useState([])

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
    if (queue.length >= 10) { toast.error('Maximum 10 papers per batch'); return }
    if (queue.some((q) => q.arxivId === paper.arxiv_id)) {
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
    for (const file of files) {
      if (!file.name.endsWith('.pdf')) { toast.error(`${file.name}: not a PDF`); continue }
      if (queue.length >= 10) { toast.error('Maximum 10 papers per batch'); break }
      setQueue((prev) => [
        ...prev,
        { id: crypto.randomUUID(), file, title: file.name.replace('.pdf', ''), status: 'pending', summaryId: null },
      ])
    }
    setComparisonData(null)
    e.target.value = ''
  }

  // ── process one item ─────────────────────────────────────────────────────────
  const processItem = async (item) => {
    setQueue((prev) => prev.map((q) => q.id === item.id ? { ...q, status: 'processing' } : q))
    try {
      // The upload field is named `file` to match the API; sending `pdf` was
      // rejected with a validation error before it ever reached the pipeline.
      const data = item.file
        ? await papers.processUpload(item.file)
        : await papers.processArxiv(item.arxivId)

      const summaryId = data?.summary_id || data?.id
      setQueue((prev) =>
        prev.map((q) => q.id === item.id ? { ...q, status: 'done', summaryId } : q)
      )
    } catch (error) {
      setQueue((prev) =>
        prev.map((q) =>
          q.id === item.id
            ? { ...q, status: 'error', error: error.message || 'Processing failed' }
            : q,
        ),
      )
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

    // Sequential on purpose. Each paper runs a full LLM pipeline, so firing the
    // whole queue at once burns through provider rate limits and every request
    // fails together.
    for (const item of pending) {
      await processItem(item)
    }
    toast.success('Batch processing complete')
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

  return (
    <div className="animate-rise mx-auto max-w-5xl space-y-8">
      <header className="border-b border-line pb-6">
        <Eyebrow className="block">Many at once</Eyebrow>
        <h1 className="display mt-2 text-display-sm text-ink">Batch</h1>
        <p className="mt-2 max-w-prose text-sm text-ink-muted">
          Queue up to ten papers. They run one at a time, and once they are done
          you can compare what each of them measured.
        </p>
      </header>

      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader title="Search arXiv" />
          <CardBody className="space-y-4">
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
              <ul className="max-h-56 space-y-2 overflow-y-auto pr-1">
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
            )}
          </CardBody>
        </Card>

        <label className="flex min-h-[180px] cursor-pointer flex-col items-center justify-center gap-3 rounded-lg border-2 border-dashed border-line p-6 text-center transition-colors duration-fast ease-out hover:border-line-strong">
          <div className="flex h-12 w-12 items-center justify-center rounded-lg bg-surface-sunk">
            <Upload className="h-5 w-5 text-ink-faint" aria-hidden="true" />
          </div>
          <div>
            <p className="text-sm font-medium text-ink">Or upload PDFs</p>
            <p className="mt-1 text-caption text-ink-faint">Up to ten in the queue</p>
          </div>
          <span className="mt-1 inline-flex h-8 items-center rounded border border-line bg-surface px-3 text-caption font-medium text-ink">
            Choose files
          </span>
          <input
            type="file"
            accept=".pdf"
            multiple
            onChange={handleFileUpload}
            className="sr-only"
          />
        </label>
      </div>

      {queue.length > 0 && (
        <Card>
          <CardHeader
            title={`Queue`}
            description={`${queue.length} of 10 slots used`}
            action={
              <div className="flex shrink-0 gap-2">
                {pendingCount > 0 && (
                  <Button size="sm" onClick={processBatch}>
                    Process {pendingCount}
                  </Button>
                )}
                {doneCount >= 2 && (
                  <Button
                    size="sm"
                    variant="contrast"
                    onClick={compareAll}
                    loading={comparing}
                  >
                    <BarChart2 className="h-3.5 w-3.5" aria-hidden="true" />
                    Compare {doneCount}
                  </Button>
                )}
              </div>
            }
          />
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
                    <span className="shrink-0 text-caption text-danger">{item.error}</span>
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
                      className="shrink-0 rounded-sm p-1 text-ink-faint transition-colors duration-fast ease-out hover:text-danger"
                      aria-label={`Remove ${item.title}`}
                    >
                      <X className="h-4 w-4" />
                    </button>
                  )}
                </li>
              ))}
            </ul>
          </CardBody>
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
