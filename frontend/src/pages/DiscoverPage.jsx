import { useState } from 'react'
import { Search, ExternalLink, PlusCircle, BookOpen, Calendar } from 'lucide-react'
import { useToast } from '../contexts/ToastContext'
import { graph, papers as papersApi } from '../lib/api'
import { fetchQuery, invalidate } from '../lib/query'
import {
  Button,
  Card,
  CardBody,
  EmptyState,
  Eyebrow,
  Input,
  SkeletonCard,
} from '../components/ui/primitives'

export default function DiscoverPage() {
  const toast = useToast()
  const [query, setQuery] = useState('')
  const [results, setResults] = useState([])
  const [searched, setSearched] = useState(false)
  const [source, setSource] = useState(null)
  const [loading, setLoading] = useState(false)
  const [importing, setImporting] = useState({})

  const handleSearch = async (e) => {
    e.preventDefault()
    const q = query.trim()
    if (!q) return
    setLoading(true)
    setResults([])
    try {
      // Cached by query text. Semantic Scholar rate-limits hard enough that
      // re-running a search the user already ran is likely to come back a 429
      // and fall through to the citation-less arXiv results instead.
      const data = await fetchQuery(['discover', q], () => graph.discover(q, 12))
      const found = data?.papers || []
      setResults(found)
      setSource(data?.degraded ? data.source : null)
      setSearched(true)
      if (found.length === 0) {
        toast.info('No results found. Try a different query.')
      }
    } catch (e) {
      toast.error('Search failed: ' + (e.message || 'Unknown error'))
    } finally {
      setLoading(false)
    }
  }

  /** Results are keyed by S2 id, which arXiv-sourced results do not have. */
  const paperKey = (paper) => paper.s2_id || paper.arxiv_id || paper.title

  const handleAddToLibrary = async (paper) => {
    if (!paper.arxiv_id) {
      toast.error('This paper has no arXiv ID, so it cannot be imported.')
      return
    }
    const key = paperKey(paper)
    setImporting(prev => ({ ...prev, [key]: true }))
    try {
      // Through the endpoint map, which sets the pipeline timeout. Called
      // directly, this inherited the client default and gave up long before the
      // server had finished summarising — reporting a failed import for a paper
      // that was, in fact, about to appear in the library.
      await papersApi.processArxiv(paper.arxiv_id)
      invalidate('summaries')
      invalidate('corpus')
      invalidate('graph')
      toast.success(`"${paper.title?.slice(0, 50)}..." added to your library.`)
    } catch (e) {
      toast.error('Import failed: ' + (e.message || 'Unknown error'))
    } finally {
      setImporting(prev => ({ ...prev, [key]: false }))
    }
  }

  return (
    <div className="animate-rise mx-auto max-w-4xl space-y-8 3xl:max-w-6xl">
      <header className="border-b border-line pb-6">
        <Eyebrow className="block">Beyond your library</Eyebrow>
        <h1 className="display mt-2 text-display-sm text-ink">Discover</h1>
        <p className="mt-2 max-w-prose text-sm text-ink-muted">
          Search Semantic Scholar for related work. Anything with an arXiv ID
          imports straight into your library.
        </p>
      </header>

      <form onSubmit={handleSearch} className="flex gap-2">
        <div className="relative flex-1">
          <Search
            className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-faint"
            aria-hidden="true"
          />
          <Input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="attention mechanism transformers, diffusion image synthesis…"
            className="pl-10"
            aria-label="Search Semantic Scholar"
          />
        </div>
        <Button type="submit" loading={loading} disabled={!query.trim()}>
          Search
        </Button>
      </form>

      {loading && (
        <div className="space-y-3">
          <SkeletonCard />
          <SkeletonCard />
          <SkeletonCard />
        </div>
      )}

      {!loading && source === 'arxiv' && (
        <p className="text-caption text-ink-faint">
          Semantic Scholar is rate-limiting us, so these results come from arXiv
          and carry no citation counts.
        </p>
      )}

      {!loading && results.length > 0 && (
        <div className="stagger space-y-3">
          {results.map((paper, i) => {
            const key = paperKey(paper)
            return (
            <Card key={key} interactive style={{ '--i': i }}>
              <CardBody className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
                <div className="min-w-0 flex-1">
                  <h3 className="font-serif text-lg leading-snug text-ink">
                    {paper.title}
                  </h3>

                  {paper.authors?.length > 0 && (
                    <p className="mt-1.5 text-sm text-ink-muted">
                      {paper.authors.slice(0, 4).join(', ')}
                      {paper.authors.length > 4 && ` +${paper.authors.length - 4} more`}
                    </p>
                  )}

                  <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-caption text-ink-faint">
                    {paper.year && (
                      <span className="inline-flex items-center gap-1.5">
                        <Calendar className="h-3.5 w-3.5" aria-hidden="true" />
                        <span className="font-mono tabular">{paper.year}</span>
                      </span>
                    )}
                    {paper.citation_count != null && (
                      <span className="inline-flex items-center gap-1.5">
                        <BookOpen className="h-3.5 w-3.5" aria-hidden="true" />
                        <span className="font-mono tabular">
                          {paper.citation_count.toLocaleString()}
                        </span>
                        citations
                      </span>
                    )}
                  </div>

                  {paper.abstract && (
                    <p className="mt-3 line-clamp-3 text-sm leading-relaxed text-ink-muted">
                      {paper.abstract}
                    </p>
                  )}
                </div>

                <div className="flex shrink-0 gap-2 sm:flex-col">
                  <Button
                    size="sm"
                    onClick={() => handleAddToLibrary(paper)}
                    disabled={!paper.can_import || importing[key]}
                    loading={importing[key]}
                    title={
                      !paper.can_import ? 'No arXiv ID, so this cannot be imported' : 'Add to library'
                    }
                  >
                    <PlusCircle className="h-3.5 w-3.5" aria-hidden="true" />
                    Add
                  </Button>
                  {paper.url && (
                    <Button
                      variant="secondary"
                      size="sm"
                      href={paper.url}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
                      Source
                    </Button>
                  )}
                </div>
              </CardBody>
            </Card>
            )
          })}
        </div>
      )}

      {!loading && searched && results.length === 0 && (
        <EmptyState
          icon={Search}
          title="No matches"
          description="Try broader terms, or search for an author instead."
        />
      )}

      {!loading && !searched && (
        <EmptyState
          icon={Search}
          title="Find related work"
          description="Search Semantic Scholar by topic or by author. Anything with an arXiv ID imports in one click."
        />
      )}
    </div>
  )
}
