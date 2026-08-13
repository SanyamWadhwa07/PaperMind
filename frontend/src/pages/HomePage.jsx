import { useCallback, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { FileUp, Search, Sparkles, X } from 'lucide-react'
import toast from 'react-hot-toast'
import { papers } from '../lib/api'
import { useAuth } from '../contexts/AuthContext'
import {
  Badge,
  Button,
  Card,
  CardBody,
  Eyebrow,
  Identifier,
  Input,
  Spinner,
} from '../components/ui/primitives'

const MAX_UPLOAD_BYTES = 50 * 1024 * 1024

/** The four stages the pipeline moves through, shown while a paper processes. */
const STAGES = [
  { id: 'extract', label: 'Reading the PDF' },
  { id: 'analyse', label: 'Extracting entities and results' },
  { id: 'summarise', label: 'Writing summaries' },
  { id: 'link', label: 'Linking to your library' },
]

function ProcessingPanel({ stage, progress }) {
  return (
    <Card>
      <CardBody>
        <div className="flex items-center gap-3">
          <Spinner className="text-accent" />
          <div>
            <p className="text-sm font-medium text-ink">Processing your paper</p>
            <p className="text-xs text-ink-muted">
              A full pass takes a few minutes. You can leave this page open.
            </p>
          </div>
        </div>

        {/* The section spine, reused as a progress indicator: each stage is a
            node on the same rail that structures a paper. */}
        <ol className="spine mt-5 space-y-3">
          {STAGES.map((item, index) => (
            <li
              key={item.id}
              className="spine-node"
              data-active={index <= stage}
            >
              <span
                className={
                  index <= stage
                    ? 'text-sm text-ink'
                    : 'text-sm text-ink-faint'
                }
              >
                {item.label}
              </span>
            </li>
          ))}
        </ol>

        {progress > 0 && progress < 100 && (
          <div className="mt-4">
            <div className="h-1 overflow-hidden rounded-full bg-surface-sunk">
              <div
                className="h-full rounded-full bg-accent transition-[width] duration-300"
                style={{ width: `${progress}%` }}
              />
            </div>
            <p className="mt-1.5 font-mono tabular text-xs text-ink-faint">
              {progress}% uploaded
            </p>
          </div>
        )}
      </CardBody>
    </Card>
  )
}

function SearchResult({ paper, onProcess, busy }) {
  return (
    <Card interactive>
      <CardBody className="space-y-2">
        <div className="flex items-center gap-2">
          <Identifier>{paper.arxiv_id}</Identifier>
          {paper.primary_category && (
            <Badge tone="neutral">{paper.primary_category}</Badge>
          )}
        </div>

        {/* Paper titles are set in serif — the document's own voice. */}
        <h3 className="font-serif text-lg leading-snug text-ink">{paper.title}</h3>

        <p className="text-sm text-ink-muted">
          {(paper.authors || []).slice(0, 3).join(', ')}
          {paper.authors?.length > 3 && ` +${paper.authors.length - 3}`}
        </p>

        <p className="line-clamp-3 text-sm text-ink-muted">{paper.summary}</p>

        <div className="pt-1">
          <Button size="sm" onClick={() => onProcess(paper.arxiv_id)} disabled={busy}>
            Summarise this paper
          </Button>
        </div>
      </CardBody>
    </Card>
  )
}

export default function HomePage() {
  const navigate = useNavigate()
  const { isAuthenticated } = useAuth()
  const fileInputRef = useRef(null)

  const [query, setQuery] = useState('')
  const [results, setResults] = useState([])
  const [searching, setSearching] = useState(false)
  const [processing, setProcessing] = useState(false)
  const [stage, setStage] = useState(0)
  const [uploadProgress, setUploadProgress] = useState(0)
  const [dragging, setDragging] = useState(false)

  const requireAuth = useCallback(() => {
    if (isAuthenticated) return true
    toast.error('Sign in to summarise papers')
    navigate('/login?next=%2F')
    return false
  }, [isAuthenticated, navigate])

  const onSearch = async (event) => {
    event.preventDefault()
    if (!query.trim() || !requireAuth()) return

    setSearching(true)
    try {
      const data = await papers.search(query.trim(), 10)
      setResults(data.papers || [])
      if (!data.papers?.length) {
        toast('No papers matched that search', { icon: '🔍' })
      }
    } catch (error) {
      toast.error(error.message)
    } finally {
      setSearching(false)
    }
  }

  /** Advance the stage indicator while the request is in flight. */
  const runWithStages = async (work) => {
    setProcessing(true)
    setStage(0)
    const timers = [
      setTimeout(() => setStage(1), 4000),
      setTimeout(() => setStage(2), 20000),
      setTimeout(() => setStage(3), 60000),
    ]
    try {
      return await work()
    } finally {
      timers.forEach(clearTimeout)
      setProcessing(false)
      setUploadProgress(0)
    }
  }

  const processArxiv = async (arxivId) => {
    if (!requireAuth()) return
    try {
      const data = await runWithStages(() => papers.processArxiv(arxivId))
      toast.success('Paper summarised')
      navigate(`/summary/${data.summary_id || data.id}`)
    } catch (error) {
      toast.error(error.message)
    }
  }

  const processFile = async (file) => {
    if (!file || !requireAuth()) return

    if (!file.name.toLowerCase().endsWith('.pdf')) {
      toast.error('Only PDF files can be processed')
      return
    }
    if (file.size > MAX_UPLOAD_BYTES) {
      toast.error('That file is larger than the 50 MB limit')
      return
    }

    try {
      const data = await runWithStages(() =>
        papers.processUpload(file, { onProgress: setUploadProgress }),
      )
      toast.success('Paper summarised')
      navigate(`/summary/${data.summary_id || data.id}`)
    } catch (error) {
      toast.error(error.message)
    }
  }

  const onDrop = (event) => {
    event.preventDefault()
    setDragging(false)
    processFile(event.dataTransfer.files?.[0])
  }

  return (
    <div className="mx-auto max-w-3xl space-y-10 py-6">
      <section className="animate-rise text-center">
        <Eyebrow>Structured reading</Eyebrow>
        {/* Weight 400 with negative tracking — the magazine voice. */}
        <h1 className="display mt-3 text-display text-ink sm:text-[3.5rem] sm:leading-[1.08]">
          Read the paper,
          <br />
          not the whole paper.
        </h1>
        <p className="mx-auto mt-4 max-w-prose text-ink-muted">
          Drop in a PDF or an arXiv ID. PaperMind pulls out the sections and the
          numbers behind them, then writes summaries at four levels of depth.
        </p>
      </section>

      {processing ? (
        <ProcessingPanel stage={stage} progress={uploadProgress} />
      ) : (
        <>
          <section
            onDragOver={(e) => {
              e.preventDefault()
              setDragging(true)
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={onDrop}
            className={`rounded-lg border-2 border-dashed p-10 text-center transition-colors ${
              dragging
                ? 'border-accent bg-accent-soft'
                : 'border-line hover:border-line-strong'
            }`}
          >
            <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-lg bg-surface-sunk">
              <FileUp className="h-5 w-5 text-ink-faint" aria-hidden="true" />
            </div>
            <p className="text-sm font-medium text-ink">
              Drop a PDF here, or choose a file
            </p>
            <p className="mt-1 text-xs text-ink-muted">PDF up to 50 MB</p>

            <input
              ref={fileInputRef}
              type="file"
              accept="application/pdf,.pdf"
              className="sr-only"
              onChange={(e) => processFile(e.target.files?.[0])}
            />
            <Button
              variant="secondary"
              className="mt-4"
              onClick={() => fileInputRef.current?.click()}
            >
              Choose file
            </Button>
          </section>

          <section>
            <form onSubmit={onSearch} className="flex gap-2">
              <div className="relative flex-1">
                <Search
                  className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-faint"
                  aria-hidden="true"
                />
                <Input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Search arXiv, or paste an ID like 1706.03762"
                  className="pl-9"
                  aria-label="Search arXiv"
                />
                {query && (
                  <button
                    type="button"
                    onClick={() => {
                      setQuery('')
                      setResults([])
                    }}
                    className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 text-ink-faint hover:text-ink"
                    aria-label="Clear search"
                  >
                    <X className="h-4 w-4" />
                  </button>
                )}
              </div>
              <Button type="submit" loading={searching} disabled={!query.trim()}>
                Search
              </Button>
            </form>

            {/* A bare arXiv ID is a direct instruction, not a search term. */}
            {/^\d{4}\.\d{4,5}(v\d+)?$/.test(query.trim()) && (
              <div className="mt-3 flex items-center gap-2 rounded border border-accent/30 bg-accent-soft px-3 py-2">
                <Sparkles className="h-4 w-4 shrink-0 text-accent" aria-hidden="true" />
                <span className="text-sm text-ink">
                  That looks like an arXiv ID.
                </span>
                <Button
                  size="sm"
                  className="ml-auto"
                  onClick={() => processArxiv(query.trim())}
                >
                  Summarise it
                </Button>
              </div>
            )}

            {results.length > 0 && (
              <div className="mt-5 space-y-3">
                <Eyebrow>{results.length} results</Eyebrow>
                {results.map((paper) => (
                  <SearchResult
                    key={paper.arxiv_id}
                    paper={paper}
                    onProcess={processArxiv}
                    busy={processing}
                  />
                ))}
              </div>
            )}
          </section>
        </>
      )}
    </div>
  )
}
