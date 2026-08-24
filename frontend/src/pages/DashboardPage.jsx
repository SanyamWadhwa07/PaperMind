import { useCallback, useEffect, useRef, useState } from 'react'
import { useToast } from '../contexts/ToastContext'
import { Link } from 'react-router-dom'
import ActivityChart from '../components/ActivityChart'
import { graph, papers } from '../lib/api'
import { fetchQuery, invalidate } from '../lib/query'
import {
  Badge,
  Button,
  Card,
  CardBody,
  EmptyState,
  Eyebrow,
  Identifier,
  Input,
  Metric,
  Select,
  SkeletonCard,
  cx,
} from '../components/ui/primitives'
import {
  FileText,
  TrendingUp,
  Clock,
  Calendar,
  Search,
  Zap,
  Trash2,
} from 'lucide-react'

/** Keyword and semantic are different questions, so they get a real switch. */
function ModeSwitch({ mode, onChange }) {
  const modes = [
    { id: 'keyword', label: 'Keyword', icon: Search },
    { id: 'semantic', label: 'Semantic', icon: Zap },
  ]
  return (
    <div className="inline-flex rounded border border-line bg-surface-sunk p-0.5">
      {modes.map(({ id, label, icon: Icon }) => (
        <button
          key={id}
          type="button"
          onClick={() => onChange(id)}
          aria-pressed={mode === id}
          className={cx(
            'inline-flex items-center gap-1.5 rounded-sm px-3 py-1.5 text-caption font-medium',
            'transition-colors duration-fast ease-out',
            mode === id
              ? 'bg-surface text-ink shadow-sm'
              : 'text-ink-faint hover:text-ink',
          )}
        >
          <Icon className="h-3.5 w-3.5" aria-hidden="true" />
          {label}
        </button>
      ))}
    </div>
  )
}

function SummaryRow({ summary, onDelete }) {
  return (
    <Card interactive className="group">
      <CardBody className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            {summary.arxiv_id && <Identifier>{summary.arxiv_id}</Identifier>}
            {summary.similarity_score != null && (
              <Badge tone="accent">
                {Math.round(summary.similarity_score * 100)}% match
              </Badge>
            )}
          </div>

          {/* The paper's own voice: serif, at reading size. */}
          <h3 className="mt-2 font-serif text-lg leading-snug text-ink">
            <Link to={`/summary/${summary.id}`} className="hover:text-accent">
              {summary.paper_title}
            </Link>
          </h3>

          {summary.paper_authors?.length > 0 && (
            <p className="mt-1.5 truncate text-sm text-ink-muted">
              {summary.paper_authors.slice(0, 3).join(', ')}
              {summary.paper_authors.length > 3 &&
                ` +${summary.paper_authors.length - 3} more`}
            </p>
          )}

          <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-caption text-ink-faint">
            {summary.created_at && (
              <span className="inline-flex items-center gap-1.5">
                <Calendar className="h-3.5 w-3.5" aria-hidden="true" />
                <span className="font-mono tabular">
                  {new Date(summary.created_at).toLocaleDateString()}
                </span>
              </span>
            )}
            {summary.processing_time_seconds != null && (
              <span className="inline-flex items-center gap-1.5">
                <Clock className="h-3.5 w-3.5" aria-hidden="true" />
                <span className="font-mono tabular">
                  {summary.processing_time_seconds.toFixed(1)}s
                </span>
              </span>
            )}
          </div>
        </div>

        <div className="flex shrink-0 items-center gap-2">
          <Button variant="secondary" size="sm" to={`/summary/${summary.id}`}>
            Open
          </Button>
          <Button
            variant="ghost"
            size="icon"
            onClick={() => onDelete(summary.id)}
            aria-label={`Delete summary of ${summary.paper_title}`}
            className="hover:text-danger"
          >
            <Trash2 className="h-4 w-4" />
          </Button>
        </div>
      </CardBody>
    </Card>
  )
}

export default function DashboardPage() {
  const toast = useToast()
  const [stats, setStats] = useState(null)
  const [summaries, setSummaries] = useState([])
  const [loading, setLoading] = useState(true)
  const [page, setPage] = useState(1)
  const [totalPages, setTotalPages] = useState(1)
  const [searchTerm, setSearchTerm] = useState('')
  const [sortBy, setSortBy] = useState('created_at')
  const [searchMode, setSearchMode] = useState('keyword') // 'keyword' | 'semantic'
  const [semanticSearching, setSemanticSearching] = useState(false)
  const [dailySummaries, setDailySummaries] = useState({})
  const [recentActivity, setRecentActivity] = useState([])

  // `searchTerm` is deliberately read from a ref rather than listed as a
  // dependency: it changes on every keystroke, and this must run when the page
  // or sort changes or when the form is submitted — not while the user types.
  const searchTermRef = useRef(searchTerm)
  searchTermRef.current = searchTerm

  const fetchDashboardData = useCallback(
    async ({ force = false } = {}) => {
      setLoading(true)
      try {
        // Both panels are independent, so fetch them concurrently. `allSettled`
        // means a stats failure still renders the paper list, and vice versa.
        const search = searchTermRef.current
        const listKey = ['summaries', 'list', page, sortBy, search]
        const [statsResult, listResult] = await Promise.allSettled([
          fetchQuery(['summaries', 'stats'], papers.dashboardStats, { force }),
          fetchQuery(
            listKey,
            () =>
              papers.list({
                page,
                per_page: 10,
                sort_by: sortBy,
                order: 'desc',
                search,
              }),
            { force },
          ),
        ])

        if (statsResult.status === 'fulfilled') {
          const data = statsResult.value
          setStats(data.stats)
          setDailySummaries(data.daily_summaries || {})
          setRecentActivity(data.recent_activity || [])
        }

        if (listResult.status === 'fulfilled') {
          setSummaries(listResult.value.summaries || [])
          setTotalPages(listResult.value.total_pages || 0)
        } else {
          throw listResult.reason
        }
      } catch (error) {
        toast.error(error.message || 'Could not load your library')
      } finally {
        setLoading(false)
      }
    },
    // `toast` is stable — it comes from a context whose value is memoised.
    [page, sortBy, toast],
  )

  useEffect(() => {
    fetchDashboardData()
  }, [fetchDashboardData])

  const runSemanticSearch = async (query) => {
    setSemanticSearching(true)
    try {
      const data = await graph.semanticSearch(query, 20)
      setSummaries(data.results || [])
      setTotalPages(1)
    } catch (error) {
      toast.error(error.message || 'Semantic search failed')
    } finally {
      setSemanticSearching(false)
    }
  }

  const handleSearch = async (e) => {
    e.preventDefault()
    setPage(1)
    if (searchMode === 'semantic' && searchTerm.trim()) {
      await runSemanticSearch(searchTerm)
    } else {
      // A submit is an explicit request for this search term's results, and the
      // term is not in the effect's dependencies, so nothing else triggers it.
      fetchDashboardData()
    }
  }

  const deleteSummary = async (id) => {
    if (!confirm('Delete this summary? This cannot be undone.')) return

    try {
      await papers.remove(id)
      toast.success('Summary deleted')
      // The row is gone, so every cached list page, the stats, and the corpus
      // graphs that counted it are all wrong now — not merely stale.
      invalidate('summaries')
      invalidate('corpus')
      invalidate('graph')
      fetchDashboardData({ force: true })
    } catch (error) {
      toast.error(error.message || 'Could not delete the summary')
    }
  }

  const metrics = [
    { label: 'Papers', value: stats?.total_summaries ?? 0, icon: FileText },
    {
      label: 'Avg. run',
      value: `${(stats?.avg_processing_time ?? 0).toFixed(1)}s`,
      icon: Clock,
    },
    {
      label: 'Words read',
      value: (stats?.total_words_processed ?? 0).toLocaleString(),
      icon: TrendingUp,
    },
    { label: 'Active days', value: stats?.active_days ?? 0, icon: Calendar },
  ]

  return (
    <div className="animate-rise space-y-8">
      <header className="border-b border-line pb-6">
        <Eyebrow className="block">Your corpus</Eyebrow>
        <h1 className="display mt-2 text-display-sm text-ink">Library</h1>
        <p className="mt-2 max-w-prose text-sm text-ink-muted">
          Every paper you have processed, with the numbers behind the pipeline.
        </p>
      </header>

      {/* Metrics sit in one hairline-divided band rather than four floating
          cards — the figures are meant to be read across, not compared as tiles. */}
      <Card>
        <div className="grid grid-cols-2 divide-line sm:grid-cols-4 sm:divide-x">
          {metrics.map(({ label, value, icon: Icon }, index) => (
            <div
              key={label}
              className={cx(
                'flex items-start justify-between gap-3 p-5',
                index < 2 && 'border-b border-line sm:border-b-0',
                index % 2 === 1 && 'border-l border-line sm:border-l-0',
              )}
            >
              <Metric label={label} value={value} />
              <Icon className="h-4 w-4 shrink-0 text-ink-faint" aria-hidden="true" />
            </div>
          ))}
        </div>
      </Card>

      <ActivityChart
        dailySummaries={dailySummaries}
        recentActivity={recentActivity}
      />

      <section className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-base font-semibold text-ink">Papers</h2>
          <ModeSwitch mode={searchMode} onChange={setSearchMode} />
        </div>

        <form onSubmit={handleSearch} className="flex flex-col gap-2 sm:flex-row">
          <div className="relative flex-1">
            {searchMode === 'keyword' ? (
              <Search
                className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-faint"
                aria-hidden="true"
              />
            ) : (
              <Zap
                className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-accent"
                aria-hidden="true"
              />
            )}
            <Input
              type="text"
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              placeholder={
                searchMode === 'semantic'
                  ? 'Describe what you are looking for…'
                  : 'Search titles and authors'
              }
              className="pl-10"
              aria-label={searchMode === 'semantic' ? 'Semantic search' : 'Keyword search'}
            />
          </div>

          {searchMode === 'keyword' && (
            <Select
              value={sortBy}
              onChange={(e) => setSortBy(e.target.value)}
              aria-label="Sort papers"
              className="sm:w-48"
            >
              <option value="created_at">Newest first</option>
              <option value="paper_title">Title A–Z</option>
              <option value="processing_time_seconds">Processing time</option>
            </Select>
          )}

          <Button type="submit" loading={semanticSearching}>
            Search
          </Button>
        </form>

        {searchMode === 'semantic' && summaries.length > 0 && (
          <p className="flex items-center gap-1.5 text-caption text-ink-faint">
            <Zap className="h-3.5 w-3.5 text-accent" aria-hidden="true" />
            {summaries.length} semantic matches. Switch to Keyword to see everything.
          </p>
        )}

        {loading ? (
          <div className="space-y-3">
            <SkeletonCard />
            <SkeletonCard />
            <SkeletonCard />
          </div>
        ) : summaries.length === 0 ? (
          <EmptyState
            icon={FileText}
            title="No papers yet"
            description="Add a PDF or an arXiv ID. PaperMind reads the structure, then pulls out what the paper measured."
            action={<Button to="/">Add your first paper</Button>}
          />
        ) : (
          <>
            <div className="stagger space-y-3">
              {summaries.map((summary, i) => (
                <div key={summary.id} style={{ '--i': i }}>
                  <SummaryRow summary={summary} onDelete={deleteSummary} />
                </div>
              ))}
            </div>

            {totalPages > 1 && (
              <div className="flex items-center justify-center gap-3 pt-2">
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={page === 1}
                >
                  Previous
                </Button>
                <span className="font-mono tabular text-caption text-ink-faint">
                  {page} / {totalPages}
                </span>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                  disabled={page === totalPages}
                >
                  Next
                </Button>
              </div>
            )}
          </>
        )}
      </section>
    </div>
  )
}
