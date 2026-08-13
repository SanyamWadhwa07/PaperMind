import { useState } from 'react'
import { Search, ExternalLink, PlusCircle, BookOpen, Calendar } from 'lucide-react'
import { useAuth } from '../contexts/AuthContext'
import { useToast } from '../contexts/ToastContext'
import api from '../lib/api'
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
  const { token } = useAuth()
  const toast = useToast()
  const [query, setQuery] = useState('')
  const [results, setResults] = useState([])
  const [loading, setLoading] = useState(false)
  const [importing, setImporting] = useState({})

  const handleSearch = async (e) => {
    e.preventDefault()
    if (!query.trim()) return
    setLoading(true)
    setResults([])
    try {
      const res = await api.get('/api/graph/discover', {
        params: { q: query, limit: 12 },
        headers: { Authorization: `Bearer ${token}` },
      })
      setResults(res.data?.papers || [])
      if ((res.data?.papers || []).length === 0) {
        toast.info('No results found. Try a different query.')
      }
    } catch (e) {
      toast.error('Search failed: ' + (e.response?.data?.detail || e.message))
    } finally {
      setLoading(false)
    }
  }

  const handleAddToLibrary = async (paper) => {
    if (!paper.arxiv_id) {
      toast.error('This paper has no arXiv ID, so it cannot be imported.')
      return
    }
    setImporting(prev => ({ ...prev, [paper.paperId]: true }))
    try {
      await api.post('/api/process/arxiv', { arxiv_id: paper.arxiv_id }, {
        headers: { Authorization: `Bearer ${token}` },
      })
      toast.success(`"${paper.title?.slice(0, 50)}..." added to your library.`)
    } catch (e) {
      toast.error('Import failed: ' + (e.response?.data?.detail || e.message))
    } finally {
      setImporting(prev => ({ ...prev, [paper.paperId]: false }))
    }
  }

  return (
    <div className="animate-rise mx-auto max-w-4xl space-y-8">
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

      {!loading && results.length > 0 && (
        <div className="stagger space-y-3">
          {results.map((paper, i) => (
            <Card key={paper.paperId} interactive style={{ '--i': i }}>
              <CardBody className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
                <div className="min-w-0 flex-1">
                  <h3 className="font-serif text-lg leading-snug text-ink">
                    {paper.title}
                  </h3>

                  {paper.authors?.length > 0 && (
                    <p className="mt-1.5 text-sm text-ink-muted">
                      {paper.authors.slice(0, 4).map((a) => a.name).join(', ')}
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
                    {paper.citationCount != null && (
                      <span className="inline-flex items-center gap-1.5">
                        <BookOpen className="h-3.5 w-3.5" aria-hidden="true" />
                        <span className="font-mono tabular">
                          {paper.citationCount.toLocaleString()}
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
                    disabled={!paper.can_import || importing[paper.paperId]}
                    loading={importing[paper.paperId]}
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
          ))}
        </div>
      )}

      {!loading && query && results.length === 0 && (
        <EmptyState
          icon={Search}
          title="No matches"
          description="Try broader terms, or search for an author instead."
        />
      )}

      {!loading && !query && (
        <EmptyState
          icon={Search}
          title="Find related work"
          description="Search Semantic Scholar by topic or by author. Anything with an arXiv ID imports in one click."
        />
      )}
    </div>
  )
}
