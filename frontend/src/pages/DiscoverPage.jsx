import { useState } from 'react'
import { Search, ExternalLink, PlusCircle, BookOpen, Users, Calendar } from 'lucide-react'
import { useAuth } from '../contexts/AuthContext'
import { useToast } from '../contexts/ToastContext'
import axios from 'axios'

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
      const res = await axios.get('/api/graph/discover', {
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
      toast.error('No arXiv ID — cannot import this paper.')
      return
    }
    setImporting(prev => ({ ...prev, [paper.paperId]: true }))
    try {
      await axios.post('/api/process/arxiv', { arxiv_id: paper.arxiv_id }, {
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
    <div className="max-w-4xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl sm:text-3xl font-bold text-[#C4935F] dark:text-[#D9A86C]">
          Discover Papers
        </h1>
        <p className="mt-1 text-sm text-[#8F8F8F]">
          Search Semantic Scholar and add papers to your library
        </p>
      </div>

      {/* Search bar */}
      <form onSubmit={handleSearch} className="flex gap-3">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-[#8F8F8F]" />
          <input
            type="text"
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder="e.g. attention mechanism transformers, diffusion models image synthesis..."
            className="w-full pl-10 pr-4 py-2.5 bg-[#F9FBFA] dark:bg-[#111312] border border-[#C4935F]/30 dark:border-[#D9A86C]/30 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[#00988F]"
          />
        </div>
        <button
          type="submit"
          disabled={loading || !query.trim()}
          className="px-5 py-2.5 bg-[#00988F] hover:bg-[#007a73] text-white rounded-lg text-sm font-medium disabled:opacity-50"
        >
          {loading ? 'Searching...' : 'Search'}
        </button>
      </form>

      {/* Loading */}
      {loading && (
        <div className="flex justify-center py-12">
          <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-[#00988F]" />
        </div>
      )}

      {/* Results */}
      {!loading && results.length > 0 && (
        <div className="grid gap-4">
          {results.map(paper => (
            <div key={paper.paperId} className="card hover:border-[#00988F]/40 transition-colors">
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1 min-w-0">
                  <h3 className="font-semibold text-[#1B1B1B] dark:text-[#F5F5F5] leading-snug mb-1">
                    {paper.title}
                  </h3>
                  {paper.authors?.length > 0 && (
                    <p className="text-xs text-[#8F8F8F] flex items-center gap-1 mb-1">
                      <Users className="w-3 h-3" />
                      {paper.authors.slice(0, 4).map(a => a.name).join(', ')}
                      {paper.authors.length > 4 && ` +${paper.authors.length - 4} more`}
                    </p>
                  )}
                  <div className="flex items-center gap-3 text-xs text-[#8F8F8F] mb-2">
                    {paper.year && (
                      <span className="flex items-center gap-1">
                        <Calendar className="w-3 h-3" /> {paper.year}
                      </span>
                    )}
                    {paper.citationCount != null && (
                      <span className="flex items-center gap-1">
                        <BookOpen className="w-3 h-3" /> {paper.citationCount} citations
                      </span>
                    )}
                  </div>
                  {paper.abstract && (
                    <p className="text-sm text-[#1B1B1B] dark:text-[#F5F5F5] opacity-70 line-clamp-3">
                      {paper.abstract}
                    </p>
                  )}
                </div>

                <div className="flex flex-col gap-2 shrink-0">
                  <button
                    onClick={() => handleAddToLibrary(paper)}
                    disabled={!paper.can_import || importing[paper.paperId]}
                    title={!paper.can_import ? 'No arXiv ID — cannot import' : 'Add to library'}
                    className="flex items-center gap-1.5 px-3 py-1.5 bg-[#00988F] hover:bg-[#007a73] text-white rounded-lg text-xs font-medium disabled:opacity-40 disabled:cursor-not-allowed whitespace-nowrap"
                  >
                    <PlusCircle className="w-3.5 h-3.5" />
                    {importing[paper.paperId] ? 'Adding...' : 'Add to Library'}
                  </button>
                  {paper.url && (
                    <a
                      href={paper.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="flex items-center gap-1.5 px-3 py-1.5 border border-slate-300 dark:border-slate-600 rounded-lg text-xs text-slate-600 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-800 whitespace-nowrap"
                    >
                      <ExternalLink className="w-3.5 h-3.5" />
                      View Paper
                    </a>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {!loading && query && results.length === 0 && (
        <div className="text-center py-16 text-slate-400">
          <Search className="w-12 h-12 mx-auto mb-3 opacity-40" />
          <p className="text-sm">No results — try broader search terms.</p>
        </div>
      )}

      {!loading && !query && (
        <div className="text-center py-16 text-slate-400">
          <Search className="w-12 h-12 mx-auto mb-3 opacity-40" />
          <p className="text-sm">Search Semantic Scholar to find related work.</p>
          <p className="text-xs mt-1 opacity-60">Papers with arXiv IDs can be imported directly.</p>
        </div>
      )}
    </div>
  )
}
