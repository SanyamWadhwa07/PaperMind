import { useState, useEffect } from 'react'
import { useParams, Link } from 'react-router-dom'
import {
  ArrowLeft, Download, FileText, Database,
  BarChart3, BookOpen, Image, Share2, Table2,
  Brain, Zap, FlaskConical, Presentation, Star,
} from 'lucide-react'
import { useAuth } from '../contexts/AuthContext'
import { useToast } from '../contexts/ToastContext'
import EntityDisplay from '../components/EntityDisplay'
import FiguresDisplay from '../components/FiguresDisplay'
import TablesDisplay from '../components/TablesDisplay'
import KnowledgeGraph from '../components/KnowledgeGraph'
import SectionSummaries from '../components/SectionSummaries'
import StarRating from '../components/StarRating'
import api from '../lib/api'
import {
  Badge,
  Button,
  Card,
  CardBody,
  Disclosure,
  EmptyState,
  ErrorState,
  Eyebrow,
  Identifier,
  Inline,
  Metric,
  Prose,
  Skeleton,
  Spinner,
  StagePill,
  Tabs,
  cx,
} from '../components/ui/primitives'

/**
 * The four reading levels, in ascending depth. Each carries one of the system's
 * stage pastels so a reader can tell which register they are in at a glance —
 * the palette exists to mark kinds of things, which is exactly this.
 */
const LEVELS = [
  { key: 'simple', stage: 1, label: 'Overview', blurb: 'The paper in a paragraph' },
  { key: 'detailed', stage: 2, label: 'Detailed', blurb: 'The academic summary' },
  { key: 'eli5', stage: 3, label: 'Plain words', blurb: 'No jargon at all' },
  { key: 'technical', stage: 4, label: 'Technical', blurb: 'Methods and numbers' },
]

/** A block of prose under a stage marker. */
function Passage({ stage, label, blurb, children, size, serif }) {
  return (
    <section className="border-t border-line pt-6 first:border-t-0 first:pt-0">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <StagePill stage={stage}>{label}</StagePill>
        <span className="text-caption text-ink-faint">{blurb}</span>
      </div>
      {/* `measure={false}`: the card around this is already the reading width. */}
      <Prose className="mt-4" size={size} serif={serif} measure={false}>
        {children}
      </Prose>
    </section>
  )
}

/** Rough reading time, so the length of a long synthesis is not a surprise. */
function readingTime(text) {
  const words = (text || '').trim().split(/\s+/).filter(Boolean).length
  if (!words) return null
  return `${words.toLocaleString()} words · ${Math.max(1, Math.round(words / 220))} min read`
}

/** A titled list of claims. Used for findings, contributions, limitations. */
function ClaimList({ title, items, icon: Icon, tone = 'neutral' }) {
  if (!items?.length) return null
  return (
    <Card>
      <CardBody>
        <h3 className="flex items-center gap-2 text-sm font-semibold text-ink">
          {Icon && <Icon className="h-4 w-4 text-ink-faint" aria-hidden="true" />}
          {title}
          <Badge tone={tone} className="ml-auto">
            {items.length}
          </Badge>
        </h3>
        {/* The section spine, reused: each claim is a node on the rail. */}
        <ul className="spine mt-4 space-y-2.5">
          {items.map((item, i) => (
            <li key={i} className="spine-node text-sm leading-relaxed text-ink-muted">
              <Inline>{item}</Inline>
            </li>
          ))}
        </ul>
      </CardBody>
    </Card>
  )
}

export default function SummaryPage() {
  const { id } = useParams()
  const { token } = useAuth()
  const toast = useToast()
  const [summary, setSummary] = useState(null)
  const [loading, setLoading] = useState(true)
  const [activeTab, setActiveTab] = useState('summaries')
  const [graphData, setGraphData] = useState(null)
  const [recommendations, setRecommendations] = useState([])
  const [graphLoading, setGraphLoading] = useState(false)
  const [intelligence, setIntelligence] = useState(null)
  const [intelligenceLoading, setIntelligenceLoading] = useState(false)
  const [peerReviewLoading, setPeerReviewLoading] = useState(false)
  const [slideLoading, setSlideLoading] = useState(false)

  useEffect(() => {
    loadSummary()
  }, [id])

  // `force` exists for the refetch after generating something: the cached
  // result is deliberately stale at that point, and state updates do not land
  // before the next statement, so clearing it first would not lift the guard.
  const loadIntelligence = async ({ force = false } = {}) => {
    if ((intelligence && !force) || intelligenceLoading) return
    setIntelligenceLoading(true)
    try {
      const res = await api.get(`/api/intelligence/paper/${id}`, {
        headers: { Authorization: `Bearer ${token}` },
      })
      setIntelligence(res.data)
    } catch {
      setIntelligence({})
    } finally {
      setIntelligenceLoading(false)
    }
  }

  const handleSimulatePeerReview = async () => {
    setPeerReviewLoading(true)
    try {
      await api.post(`/api/intelligence/peer-review/${id}`, {}, {
        headers: { Authorization: `Bearer ${token}` },
      })
      // Previously this refetched (a no-op — the guard saw the cached value)
      // and then set the cache to null, so the freshly generated review was
      // replaced by the "No analysis yet" empty state.
      await loadIntelligence({ force: true })
      toast.success('Peer review generated')
    } catch (e) {
      toast.error('Peer review failed: ' + (e.response?.data?.detail || e.message))
    } finally {
      setPeerReviewLoading(false)
    }
  }

  const handleDownloadSlides = async () => {
    setSlideLoading(true)
    try {
      const res = await api.post(`/api/export/slides/${id}`, {}, {
        headers: { Authorization: `Bearer ${token}` },
        responseType: 'blob',
      })
      const url = window.URL.createObjectURL(new Blob([res.data], { type: 'text/html' }))
      const link = document.createElement('a')
      link.href = url
      link.setAttribute('download', `slides_${id.slice(0, 8)}.html`)
      document.body.appendChild(link)
      link.click()
      link.remove()
      toast.success('Slides downloaded!')
    } catch (e) {
      toast.error('Slide generation failed: ' + (e.response?.data?.detail || e.message))
    } finally {
      setSlideLoading(false)
    }
  }

  // Lazy-load graph data when graph tab is first opened
  const loadGraphData = async () => {
    if (graphData || graphLoading) return
    setGraphLoading(true)
    try {
      const [graphRes, recsRes] = await Promise.all([
        api.get(`/api/graph/paper/${id}`, { headers: { Authorization: `Bearer ${token}` } }),
        api.get(`/api/graph/recommendations/${id}`, { headers: { Authorization: `Bearer ${token}` } }),
      ])
      setGraphData(graphRes.data)
      setRecommendations(recsRes.data?.recommendations || [])
    } catch {
      // ignore
    } finally {
      setGraphLoading(false)
    }
  }

  const loadSummary = async () => {
    try {
      // Through the shared client, like every other call on this page: it
      // resolves the API origin, attaches the token, and normalises errors.
      // The raw `fetch` here did none of that and hardcoded a same-origin path.
      const { data } = await api.get(`/api/summaries/${id}`)
      setSummary(data.summary)
    } catch (error) {
      toast.error('Failed to load summary: ' + error.message)
    } finally {
      setLoading(false)
    }
  }

  const handleExport = async (format) => {
    if (!summary) return

    try {
      if (format === 'bibtex') {
        const arxivId = summary.arxiv_id && summary.arxiv_id !== 'uploaded' ? summary.arxiv_id : id
        const year = summary.published_date
          ? summary.published_date.slice(0, 4)
          : new Date(summary.created_at).getFullYear()
        const firstAuthor = summary.paper_authors?.[0]?.split(' ').pop() || 'Author'
        const key = `${firstAuthor}${year}${arxivId.replace(/[^a-z0-9]/gi, '').slice(0, 6)}`
        const authors = (summary.paper_authors || []).join(' and ')
        const bibtex = `@article{${key},\n  title={${summary.paper_title}},\n  author={${authors}},\n  year={${year}},\n  journal={arXiv preprint arXiv:${arxivId}},\n  url={https://arxiv.org/abs/${arxivId}}\n}\n`
        const blob = new Blob([bibtex], { type: 'text/plain' })
        const url = window.URL.createObjectURL(blob)
        const link = document.createElement('a')
        link.href = url
        link.setAttribute('download', `${key}.bib`)
        document.body.appendChild(link)
        link.click()
        link.remove()
        toast.success('Exported as BibTeX')
        return
      }
      if (format === 'json') {
        const blob = new Blob([JSON.stringify(summary, null, 2)], { type: 'application/json' })
        const url = window.URL.createObjectURL(blob)
        const link = document.createElement('a')
        link.href = url
        link.setAttribute('download', `summary_${id}.json`)
        document.body.appendChild(link)
        link.click()
        link.remove()
      } else {
        // Generate markdown
        let md = `# ${summary.paper_title}\n\n`
        if (summary.paper_authors?.length) {
          md += `**Authors:** ${summary.paper_authors.join(', ')}\n\n`
        }

        // Add all 4 summaries
        const summaries = summary.summary_data?.summaries || {}
        if (summaries.simple) {
          md += `## Quick Overview\n\n${summaries.simple}\n\n`
        }
        if (summaries.detailed) {
          md += `## Detailed Academic Summary\n\n${summaries.detailed}\n\n`
        }
        if (summaries.eli5) {
          md += `## Explain Like I'm 5\n\n${summaries.eli5}\n\n`
        }
        if (summaries.technical) {
          md += `## Technical Analysis\n\n${summaries.technical}\n\n`
        }

        if (summary.summary_data?.key_findings?.length) {
          md += `## Key Findings\n\n${summary.summary_data.key_findings.map(f => `- ${f}`).join('\n')}\n\n`
        }

        const blob = new Blob([md], { type: 'text/markdown' })
        const url = window.URL.createObjectURL(blob)
        const link = document.createElement('a')
        link.href = url
        link.setAttribute('download', `summary_${id}.md`)
        document.body.appendChild(link)
        link.click()
        link.remove()
      }
      toast.success(`Exported as ${format.toUpperCase()}`)
    } catch (error) {
      toast.error('Failed to export: ' + error.message)
    }
  }

  if (loading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-4 w-24" />
        <Skeleton className="h-10 w-3/4" />
        <Skeleton className="h-4 w-1/2" />
        <Skeleton className="h-28 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    )
  }

  if (!summary) {
    return (
      <EmptyState
        icon={FileText}
        title="Summary not found"
        description="It may have been deleted, or it belongs to another account."
        action={
          <Button to="/dashboard">
            <ArrowLeft className="h-4 w-4" />
            Back to library
          </Button>
        }
      />
    )
  }

  const summaryData = summary.summary_data || {}
  const s = summaryData.summaries || {}
  const originalWords = summaryData.num_words_original
  // How much reading the summary saves. Only meaningful when the original
  // length was actually recorded.
  const compression =
    originalWords && summary.word_count
      ? `${((1 - summary.word_count / originalWords) * 100).toFixed(0)}%`
      : '—'

  const metrics = [
    { label: 'Model', value: summary.model_used || '—' },
    { label: 'Words', value: summary.word_count?.toLocaleString() ?? '—' },
    {
      label: 'Run time',
      value: summary.processing_time_seconds
        ? `${Math.round(summary.processing_time_seconds)}s`
        : '—',
    },
    { label: 'Sections', value: summaryData.sections_found?.length ?? 0 },
    { label: 'Condensed', value: compression },
  ]

  const agentMeta = summaryData.agent_metadata
  // Enough on the closed row to answer "did this run properly?" at a glance,
  // without unfolding it.
  const runHint = [
    summary.model_used,
    summary.processing_time_seconds
      ? `${Math.round(summary.processing_time_seconds)}s`
      : null,
  ]
    .filter(Boolean)
    .join(' · ')

  const tabs = [
    { id: 'summaries', label: 'Summaries', icon: BookOpen },
    {
      id: 'entities',
      label: 'Entities',
      icon: Database,
      count: Object.values(summaryData.entities || {}).flat().length || undefined,
    },
    {
      id: 'figures',
      label: 'Figures',
      icon: Image,
      count: summaryData.figures?.length || undefined,
    },
    {
      id: 'tables',
      label: 'Tables',
      icon: Table2,
      count: summaryData.tables?.length || undefined,
    },
    { id: 'graph', label: 'Graph', icon: Share2 },
    { id: 'intelligence', label: 'Intelligence', icon: Brain },
  ]

  const onTabChange = (tabId) => {
    setActiveTab(tabId)
    if (tabId === 'graph') loadGraphData()
    if (tabId === 'intelligence') loadIntelligence()
  }

  const resultRows = summaryData.results?.metrics || []
  const sectionSummaries = summaryData.section_summaries || {}

  return (
    <article className="animate-rise space-y-8">
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
        <Button variant="ghost" size="sm" to="/dashboard">
          <ArrowLeft className="h-4 w-4" />
          Library
        </Button>

        <div className="flex flex-wrap items-center gap-1.5">
          <Eyebrow className="mr-1 hidden sm:inline">Export</Eyebrow>
          {['json', 'markdown', 'bibtex'].map((format) => (
            <Button
              key={format}
              variant="secondary"
              size="sm"
              onClick={() => handleExport(format)}
            >
              <Download className="h-3.5 w-3.5" aria-hidden="true" />
              {format === 'bibtex' ? 'BibTeX' : format === 'json' ? 'JSON' : 'MD'}
            </Button>
          ))}
        </div>
      </div>

      {/* The paper announces itself in its own voice, above the apparatus. */}
      <header className="border-b border-line pb-8">
        <div className="flex flex-wrap items-center gap-2">
          {summary.arxiv_id && summary.arxiv_id !== 'uploaded' ? (
            <Identifier>arXiv:{summary.arxiv_id}</Identifier>
          ) : (
            <Badge tone="outline">Uploaded</Badge>
          )}
          {summary.created_at && (
            <span className="font-mono tabular text-code text-ink-faint">
              {new Date(summary.created_at).toLocaleDateString()}
            </span>
          )}
          {summary.quality_score != null && (
            <Badge tone="success">
              Quality {Math.round(summary.quality_score * 100)}%
            </Badge>
          )}
        </div>

        <h1 className="mt-4 max-w-prose font-serif text-display-sm font-normal leading-tight text-ink sm:text-display">
          {summary.paper_title}
        </h1>

        {summary.paper_authors?.length > 0 && (
          <p className="mt-4 max-w-prose text-sm leading-relaxed text-ink-muted">
            {summary.paper_authors.join(', ')}
          </p>
        )}
      </header>

      {/* How the summary was made — a question asked once, if ever, so it sits
          folded away rather than between the title and the writing. */}
      <Disclosure label="Run details" hint={runHint}>
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5">
          {metrics.map(({ label, value }, i) => (
            <div
              key={label}
              className={cx(
                'border-line p-4 sm:p-5',
                i % 2 === 1 && 'border-l sm:border-l-0',
                i % 3 !== 0 && 'sm:border-l',
                'lg:border-l lg:first:border-l-0',
                i < 4 && 'border-b sm:border-b-0',
              )}
            >
              <Metric label={label} value={value} />
            </div>
          ))}
        </div>

        {agentMeta && (
          <dl className="grid grid-cols-2 gap-4 border-t border-line p-4 sm:p-5 md:grid-cols-4">
            {[
              ['Mode', agentMeta.processing_mode],
              ['Agents', agentMeta.agent_count],
              [
                'Agent time',
                agentMeta.total_time_ms
                  ? `${(agentMeta.total_time_ms / 1000).toFixed(1)}s`
                  : null,
              ],
              ['Backend', agentMeta.llm_backend],
            ].map(([label, value]) => (
              <div key={label}>
                <dt className="text-caption text-ink-faint">{label}</dt>
                <dd className="mt-0.5 font-mono tabular text-sm text-ink">
                  {value || '—'}
                </dd>
              </div>
            ))}
          </dl>
        )}
      </Disclosure>

      <Tabs
        tabs={tabs.map((t) => ({ id: t.id, label: t.label, count: t.count }))}
        value={activeTab}
        onChange={onTabChange}
      />

      <div className="space-y-6">
        {activeTab === 'summaries' && (
          /* Reading column + a findings column beside it, from `xl` up. Prose
             has to stay near 68 characters to be readable, so on a wide display
             a single column left the right half of the page empty.
             Deliberately NOT sticky: these lists run taller than the viewport,
             and a sticky box taller than the screen pins its own top and makes
             the rest unreachable. */
          <div className="grid gap-6 xl:grid-cols-[minmax(0,68ch)_minmax(0,1fr)] xl:items-start">
            <div className="min-w-0 space-y-6">
            {/* Fills its column, which is itself capped at the reading measure.
                A full-width box holding a 65-character line put ~700px of blank
                inside its own border, which reads as broken, not as margin. */}
            <Card className="w-full">
              <CardBody className="space-y-6 sm:p-8">
                {s.main ? (
                  <Passage
                    stage={5}
                    label="Summary"
                    blurb={readingTime(s.main) || 'Generated across the whole paper'}
                    serif
                  >
                    {s.main}
                  </Passage>
                ) : (
                  LEVELS.filter(({ key }) => s[key]).map(({ key, stage, label, blurb }) => (
                    <Passage key={key} stage={stage} label={label} blurb={blurb} serif>
                      {s[key]}
                    </Passage>
                  ))
                )}

                {!s.main && !LEVELS.some(({ key }) => s[key]) && (
                  <p className="text-sm text-ink-faint">No summary was generated for this paper.</p>
                )}
              </CardBody>
            </Card>

            {/* The technical detail a reader would otherwise open the PDF for. */}
            {(summaryData.methods_detail || summaryData.experimental_setup) && (
              <Card className="w-full">
                <CardBody className="space-y-6 sm:p-8">
                  {summaryData.methods_detail && (
                    <Passage stage={2} label="How it works" blurb="The method in detail" serif>
                      {summaryData.methods_detail}
                    </Passage>
                  )}
                  {summaryData.experimental_setup && (
                    <Passage stage={4} label="Experimental setup" blurb="What was tested against what" serif>
                      {summaryData.experimental_setup}
                    </Passage>
                  )}
                </CardBody>
              </Card>
            )}

            {/* Section digests are prose too, so they belong to the reading
                column. Spanning them across the page only stretched the panel,
                not the text inside it, which left each one two-thirds empty. */}
            {Object.keys(sectionSummaries).length > 0 && (
              <div>
                <h3 className="mb-3 text-sm font-semibold text-ink">Section by section</h3>
                <SectionSummaries summaries={sectionSummaries} />
              </div>
            )}
            </div>

            {/* Everything structured — claims and the results table — sits in
                the column beside the prose. Two purposes: it fills the width a
                68-character measure cannot use, and it gives this column enough
                height to roughly match the article, so neither side ends in a
                long empty gutter.

                Deliberately not sticky. Sticky clipped its own overflow in one
                attempt, and in another the full-width row below slid underneath
                it; a plain grid item does neither. */}
            <div className="min-w-0 space-y-4">
              <ClaimList
                title="Key findings"
                items={summaryData.key_findings}
                icon={Zap}
                tone="accent"
              />
              <ClaimList
                title="Contributions"
                items={summaryData.contributions}
                icon={Star}
              />
              <ClaimList title="Limitations" items={summaryData.limitations} />
              <ClaimList title="Future work" items={summaryData.future_work} />

            {resultRows.length > 0 && (
              <Card>
                <div className="border-b border-line px-5 py-4 sm:px-6">
                  <h3 className="flex items-center gap-2 text-sm font-semibold text-ink">
                    <BarChart3 className="h-4 w-4 text-ink-faint" aria-hidden="true" />
                    Quantitative results
                  </h3>
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-line">
                        {['Measurement', 'Value', 'Method', 'On'].map((h) => (
                          <th
                            key={h}
                            className="px-4 py-2.5 sm:px-6 text-left text-eyebrow font-semibold uppercase text-ink-faint"
                          >
                            {h}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {resultRows.map((r, i) => (
                        <tr
                          key={i}
                          className={cx(
                            'border-b border-line last:border-b-0',
                            r.is_best && 'bg-accent-soft/40',
                          )}
                        >
                          <td className="px-4 py-2.5 sm:px-6 font-medium text-ink">
                            {r.metric || r.measurement || '—'}
                            {r.is_best && (
                              <Badge tone="accent" className="ml-2">
                                Best
                              </Badge>
                            )}
                          </td>
                          {/* Values are the column readers scan down. */}
                          <td className="px-4 py-2.5 sm:px-6 font-mono tabular text-ink">
                            {r.value || '—'}
                          </td>
                          <td className="px-4 py-2.5 sm:px-6 text-ink-muted">
                            {r.model || r.method || '—'}
                          </td>
                          <td className="px-4 py-2.5 sm:px-6 text-ink-faint">
                            {r.dataset || r.subject || '—'}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Card>
            )}

            </div>
          </div>
        )}

        {activeTab === 'entities' && (
          <EntityDisplay
            entities={summaryData.entities || {}}
            typed={summaryData.typed_entities || {}}
          />
        )}

        {activeTab === 'figures' && (
          <FiguresDisplay figures={summaryData.figures || []} />
        )}

        {activeTab === 'tables' && (
          <TablesDisplay tables={summaryData.tables || []} />
        )}

        {activeTab === 'graph' && (
          <div className="space-y-6">
            {graphLoading ? (
              <div className="flex h-48 items-center justify-center">
                <Spinner className="text-accent" />
              </div>
            ) : (
              <KnowledgeGraph
                nodes={graphData?.nodes || []}
                edges={graphData?.edges || []}
                height={440}
              />
            )}

            {recommendations.length > 0 && (
              <section>
                <h3 className="mb-3 text-sm font-semibold text-ink">Similar papers</h3>
                <div className="space-y-2">
                  {recommendations.map((rec) => {
                    const paper = rec.summaries || rec
                    return (
                      <Card
                        key={rec.paper_b_id || rec.id}
                        interactive
                        as={Link}
                        to={`/summary/${rec.paper_b_id || rec.id}`}
                        className="flex items-center justify-between gap-4 px-5 py-3.5"
                      >
                        <span className="truncate font-serif text-sm text-ink">
                          {paper.paper_title || 'Untitled'}
                        </span>
                        <span className="shrink-0 font-mono tabular text-code text-ink-faint">
                          {(rec.similarity_score * 100).toFixed(0)}%
                        </span>
                      </Card>
                    )
                  })}
                </div>
              </section>
            )}
          </div>
        )}

        {activeTab === 'intelligence' && (
          <IntelligenceTab
            intelligence={intelligence}
            loading={intelligenceLoading}
            summaryData={summaryData}
            onPeerReview={handleSimulatePeerReview}
            peerReviewLoading={peerReviewLoading}
            onDownloadSlides={handleDownloadSlides}
            slideLoading={slideLoading}
          />
        )}
      </div>

      <div className="border-t border-line pt-6">
        <StarRating summaryId={id} />
      </div>
    </article>
  )
}

/* ── Intelligence tab ─────────────────────────────────────────────────────── */

function ScoreRing({ score }) {
  const pct = Math.round((score / 10) * 100)
  // Ring colour is a judgement, so it uses the semantic scale, not the accent.
  const tone =
    score >= 7 ? 'text-success' : score >= 4 ? 'text-warning' : 'text-danger'
  return (
    <div className="relative h-24 w-24 shrink-0">
      <svg viewBox="0 0 36 36" className="h-full w-full -rotate-90">
        <circle
          cx="18" cy="18" r="15.9" fill="none"
          className="text-line" stroke="currentColor" strokeWidth="2.5"
        />
        <circle
          cx="18" cy="18" r="15.9" fill="none"
          className={tone} stroke="currentColor" strokeWidth="2.5"
          strokeDasharray={`${pct} ${100 - pct}`} strokeLinecap="round"
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className={cx('font-mono tabular text-lg', tone)}>{score}</span>
        <span className="font-mono tabular text-[0.625rem] text-ink-faint">/10</span>
      </div>
    </div>
  )
}

function IntelligenceTab({
  intelligence,
  loading,
  summaryData,
  onPeerReview,
  peerReviewLoading,
  onDownloadSlides,
  slideLoading,
}) {
  if (loading) {
    return (
      <div className="flex h-32 items-center justify-center">
        <Spinner className="text-accent" />
      </div>
    )
  }

  const gapsData = intelligence?.gaps?.data || summaryData?.research_gaps || {}
  const explicit = gapsData.explicit_gaps || []
  const implicit = gapsData.implicit_gaps || []
  const future = gapsData.future_directions || []
  const repro = intelligence?.reproducibility?.data || summaryData?.reproducibility || {}
  const pr = intelligence?.peer_review?.data
  const ablation =
    intelligence?.ablation?.data?.ablation_studies || summaryData?.ablation_studies || []

  const hasAnything =
    explicit.length || implicit.length || future.length ||
    repro.score != null || pr || ablation.length

  const RECOMMENDATION_TONE = {
    accept: 'success',
    minor_revision: 'warning',
    major_revision: 'annotate',
    reject: 'danger',
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap gap-2">
        <Button variant="secondary" onClick={onPeerReview} loading={peerReviewLoading}>
          <FlaskConical className="h-4 w-4" aria-hidden="true" />
          {peerReviewLoading ? 'Reviewing…' : 'Simulate peer review'}
        </Button>
        <Button variant="secondary" onClick={onDownloadSlides} loading={slideLoading}>
          <Presentation className="h-4 w-4" aria-hidden="true" />
          {slideLoading ? 'Building…' : 'Download slides'}
        </Button>
      </div>

      {(explicit.length > 0 || implicit.length > 0 || future.length > 0) && (
        <Card>
          <CardBody className="space-y-5">
            <h3 className="flex items-center gap-2 text-sm font-semibold text-ink">
              <Zap className="h-4 w-4 text-ink-faint" aria-hidden="true" />
              Research gaps
            </h3>
            {[
              ['Explicitly stated', explicit],
              ['Implicit', implicit],
              ['Future directions', future],
            ].map(([label, items]) =>
              items.length ? (
                <div key={label}>
                  <Eyebrow className="block">{label}</Eyebrow>
                  <ul className="spine mt-2.5 space-y-2">
                    {items.map((g, i) => (
                      <li key={i} className="spine-node text-sm leading-relaxed text-ink-muted">
                        {g}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null,
            )}
          </CardBody>
        </Card>
      )}

      {repro.score != null && (
        <Card>
          <CardBody>
            <h3 className="text-sm font-semibold text-ink">Reproducibility</h3>
            <div className="mt-4 flex flex-wrap items-center gap-6">
              <ScoreRing score={repro.score || 0} />
              <dl className="grid min-w-0 flex-1 grid-cols-1 gap-x-6 gap-y-1.5 sm:grid-cols-2">
                {Object.entries(repro.evidence || {}).map(([k, v]) => (
                  <div key={k} className="flex items-center gap-2 text-sm">
                    <span
                      className={cx(
                        'font-mono',
                        v ? 'text-success' : 'text-ink-faint',
                      )}
                      aria-hidden="true"
                    >
                      {v ? '✓' : '✗'}
                    </span>
                    <span className="capitalize text-ink-muted">
                      {k.replace(/_/g, ' ')}
                    </span>
                  </div>
                ))}
              </dl>
            </div>

            {(repro.github_links || []).length > 0 && (
              <div className="mt-5 border-t border-line pt-4">
                <Eyebrow className="block">Code</Eyebrow>
                <ul className="mt-2 space-y-1">
                  {repro.github_links.map((url, i) => (
                    <li key={i}>
                      <a
                        href={url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="block truncate font-mono text-code text-accent hover:underline"
                      >
                        {url}
                      </a>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </CardBody>
        </Card>
      )}

      {pr && (
        <Card>
          <CardBody className="space-y-5">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h3 className="flex items-center gap-2 text-sm font-semibold text-ink">
                <FlaskConical className="h-4 w-4 text-ink-faint" aria-hidden="true" />
                Simulated peer review
              </h3>
              <Badge tone={RECOMMENDATION_TONE[pr.recommendation] || 'neutral'}>
                {(pr.recommendation || '').replace(/_/g, ' ')}
              </Badge>
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              {['novelty', 'soundness', 'clarity', 'significance'].map((d) => (
                <div key={d}>
                  <div className="flex items-baseline justify-between text-caption">
                    <span className="capitalize text-ink-muted">{d}</span>
                    <span className="font-mono tabular text-ink">{pr[d]}/10</span>
                  </div>
                  <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-surface-sunk">
                    <div
                      className="h-full rounded-full bg-accent"
                      style={{ width: `${(pr[d] / 10) * 100}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>

            {pr.summary && <Prose>{pr.summary}</Prose>}

            {(pr.major_concerns || []).length > 0 && (
              <ErrorState
                title="Major concerns"
                message={pr.major_concerns.join(' · ')}
              />
            )}

            {(pr.minor_concerns || []).length > 0 && (
              <div>
                <Eyebrow className="block">Minor concerns</Eyebrow>
                <ul className="spine mt-2 space-y-1.5">
                  {pr.minor_concerns.map((c, i) => (
                    <li key={i} className="spine-node text-sm text-ink-muted">
                      {c}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </CardBody>
        </Card>
      )}

      {ablation.length > 0 && (
        <Card>
          <div className="border-b border-line px-5 py-4 sm:px-6">
            <h3 className="text-sm font-semibold text-ink">Ablation studies</h3>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-line">
                  {['Component', 'Metric', 'Delta', 'Baseline'].map((h) => (
                    <th
                      key={h}
                      className="px-4 py-2.5 sm:px-6 text-left text-eyebrow font-semibold uppercase text-ink-faint"
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {ablation.map((row, i) => (
                  <tr key={i} className="border-b border-line last:border-b-0">
                    <td className="px-4 py-2.5 sm:px-6 font-medium text-ink">
                      {row.component || '—'}
                    </td>
                    <td className="px-4 py-2.5 sm:px-6 text-ink-muted">{row.metric || '—'}</td>
                    <td
                      className={cx(
                        'px-4 py-2.5 sm:px-6 font-mono tabular',
                        row.delta > 0 ? 'text-success' : 'text-danger',
                      )}
                    >
                      {row.delta != null ? `${row.delta > 0 ? '+' : ''}${row.delta}` : '—'}
                    </td>
                    <td className="px-4 py-2.5 sm:px-6 font-mono tabular text-ink-faint">
                      {row.baseline != null ? row.baseline : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {!hasAnything && (
        <EmptyState
          icon={Brain}
          title="No analysis yet"
          description="Run a peer review simulation above, or reprocess the paper to populate gaps and reproducibility."
        />
      )}
    </div>
  )
}
