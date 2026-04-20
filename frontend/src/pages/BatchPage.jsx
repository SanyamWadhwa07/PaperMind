import { useState } from 'react'
import { useAuth } from '../contexts/AuthContext'
import { useToast } from '../contexts/ToastContext'
import ComparisonTable from '../components/ComparisonTable'
import {
  Upload, Search, X, Loader2, BarChart2, FileText, CheckCircle2, AlertCircle
} from 'lucide-react'
import axios from 'axios'

const STATUS_ICON = {
  processing: <Loader2 className="w-4 h-4 animate-spin text-[#00988F]" />,
  done: <CheckCircle2 className="w-4 h-4 text-emerald-500" />,
  error: <AlertCircle className="w-4 h-4 text-red-500" />,
}

export default function BatchPage() {
  const { token } = useAuth()
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
      const res = await axios.post('http://localhost:5000/api/search', {
        query: arxivQuery,
        max_results: 8,
      })
      setSearchResults(res.data.papers || [])
    } catch {
      toast.error('Search failed')
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
      let summaryId
      if (item.file) {
        const form = new FormData()
        form.append('pdf', item.file)
        const res = await axios.post('http://localhost:5000/api/process/upload', form, {
          headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'multipart/form-data' },
        })
        summaryId = res.data?.summary_id
      } else {
        const res = await axios.post(
          'http://localhost:5000/api/process/arxiv',
          { arxiv_id: item.arxivId },
          { headers: { Authorization: `Bearer ${token}` } }
        )
        summaryId = res.data?.summary_id
      }
      setQueue((prev) =>
        prev.map((q) => q.id === item.id ? { ...q, status: 'done', summaryId } : q)
      )
    } catch (err) {
      const msg = err.response?.data?.error || 'Processing failed'
      setQueue((prev) => prev.map((q) => q.id === item.id ? { ...q, status: 'error', error: msg } : q))
    }
  }

  // ── process all pending ───────────────────────────────────────────────────────
  const processBatch = async () => {
    if (!token) { toast.error('Please log in to process papers'); return }
    const pending = queue.filter((q) => q.status === 'pending')
    if (!pending.length) { toast.error('No pending papers to process'); return }
    setComparisonData(null)
    await Promise.all(pending.map(processItem))
    toast.success('Batch processing complete')
  }

  // ── compare all done papers ───────────────────────────────────────────────────
  const compareAll = async () => {
    const ids = queue.filter((q) => q.status === 'done' && q.summaryId).map((q) => q.summaryId)
    if (ids.length < 2) { toast.error('Need at least 2 processed papers to compare'); return }
    setComparing(true)
    setComparisonData(null)
    try {
      const res = await axios.post(
        'http://localhost:5000/api/batch/compare',
        { summary_ids: ids },
        { headers: { Authorization: `Bearer ${token}` } }
      )
      setComparisonData(res.data)
    } catch {
      toast.error('Comparison failed')
    } finally {
      setComparing(false)
    }
  }

  const doneCount = queue.filter((q) => q.status === 'done').length
  const pendingCount = queue.filter((q) => q.status === 'pending').length

  return (
    <div className="space-y-6 max-w-5xl mx-auto">
      {/* Header */}
      <div>
        <h1 className="text-2xl sm:text-3xl font-bold text-[#C4935F] dark:text-[#D9A86C]">
          Batch Processing
        </h1>
        <p className="mt-1 text-sm text-[#8F8F8F]">
          Add up to 10 papers, process them in parallel, then compare results.
        </p>
      </div>

      {/* Search + Upload row */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* arXiv search */}
        <div className="card space-y-3">
          <h2 className="font-semibold text-[#1B1B1B] dark:text-[#F5F5F5] flex items-center gap-2">
            <Search className="w-4 h-4 text-[#00988F]" /> Search arXiv
          </h2>
          <form onSubmit={handleSearch} className="flex gap-2">
            <input
              type="text"
              value={arxivQuery}
              onChange={(e) => setArxivQuery(e.target.value)}
              placeholder="attention mechanism, BERT, diffusion…"
              className="flex-1 px-3 py-2 text-sm bg-[#F9FBFA] dark:bg-[#111312] border border-[#C4935F]/30 dark:border-[#D9A86C]/30 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#00988F] text-[#1B1B1B] dark:text-[#F5F5F5]"
            />
            <button type="submit" className="btn-primary px-4 text-sm" disabled={searching}>
              {searching ? <Loader2 className="w-4 h-4 animate-spin" /> : 'Search'}
            </button>
          </form>
          {searchResults.length > 0 && (
            <ul className="space-y-2 max-h-56 overflow-y-auto pr-1">
              {searchResults.map((p) => (
                <li key={p.arxiv_id} className="flex items-start justify-between gap-2 text-sm">
                  <div className="min-w-0">
                    <p className="text-[#1B1B1B] dark:text-[#F5F5F5] font-medium truncate" title={p.title}>
                      {p.title}
                    </p>
                    <p className="text-[#8F8F8F] text-xs">{p.arxiv_id}</p>
                  </div>
                  <button
                    onClick={() => addToQueue(p)}
                    className="shrink-0 text-xs btn-primary py-1 px-2"
                    disabled={queue.some((q) => q.arxivId === p.arxiv_id)}
                  >
                    {queue.some((q) => q.arxivId === p.arxiv_id) ? 'Added' : '+ Add'}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* PDF upload */}
        <div className="card flex flex-col items-center justify-center gap-3 border-dashed border-2 border-[#C4935F]/30 dark:border-[#D9A86C]/30 min-h-[140px]">
          <Upload className="w-8 h-8 text-[#00988F]" />
          <p className="text-sm text-[#8F8F8F] text-center">Upload PDFs (up to 10 total)</p>
          <label className="btn-primary text-sm cursor-pointer">
            Choose Files
            <input
              type="file"
              accept=".pdf"
              multiple
              onChange={handleFileUpload}
              className="hidden"
            />
          </label>
        </div>
      </div>

      {/* Queue */}
      {queue.length > 0 && (
        <div className="card space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="font-semibold text-[#1B1B1B] dark:text-[#F5F5F5] flex items-center gap-2">
              <FileText className="w-4 h-4 text-[#00988F]" />
              Queue ({queue.length}/10)
            </h2>
            <div className="flex gap-2">
              {pendingCount > 0 && (
                <button onClick={processBatch} className="btn-primary text-sm px-4">
                  Process {pendingCount} Paper{pendingCount !== 1 ? 's' : ''}
                </button>
              )}
              {doneCount >= 2 && (
                <button
                  onClick={compareAll}
                  disabled={comparing}
                  className="flex items-center gap-2 px-4 py-2 text-sm font-medium rounded-lg bg-[#00988F] hover:bg-[#008F89] text-white transition-colors disabled:opacity-50"
                >
                  {comparing ? <Loader2 className="w-4 h-4 animate-spin" /> : <BarChart2 className="w-4 h-4" />}
                  Compare {doneCount} Papers
                </button>
              )}
            </div>
          </div>

          <ul className="divide-y divide-[#C4935F]/10 dark:divide-[#D9A86C]/10">
            {queue.map((item) => (
              <li key={item.id} className="flex items-center gap-3 py-2.5">
                <span className="shrink-0">{STATUS_ICON[item.status] || <div className="w-4 h-4 rounded-full border-2 border-[#C4935F]/30" />}</span>
                <span className="flex-1 text-sm text-[#1B1B1B] dark:text-[#F5F5F5] truncate" title={item.title}>
                  {item.title}
                </span>
                {item.status === 'error' && (
                  <span className="text-xs text-red-500 shrink-0">{item.error}</span>
                )}
                {item.status === 'done' && item.summaryId && (
                  <a
                    href={`/summary/${item.summaryId}`}
                    className="text-xs text-[#00988F] hover:underline shrink-0"
                    target="_blank"
                    rel="noreferrer"
                  >
                    View
                  </a>
                )}
                {item.status !== 'processing' && (
                  <button
                    onClick={() => removeFromQueue(item.id)}
                    className="shrink-0 text-[#8F8F8F] hover:text-red-500 transition-colors"
                    aria-label="Remove"
                  >
                    <X className="w-4 h-4" />
                  </button>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Comparison results */}
      {comparing && (
        <div className="card flex items-center gap-3 text-[#8F8F8F]">
          <Loader2 className="w-5 h-5 animate-spin text-[#00988F]" />
          <span className="text-sm">Building comparison…</span>
        </div>
      )}

      {comparisonData && (
        <div className="card space-y-4">
          <h2 className="font-semibold text-[#1B1B1B] dark:text-[#F5F5F5] flex items-center gap-2">
            <BarChart2 className="w-4 h-4 text-[#00988F]" />
            Cross-Paper Comparison
          </h2>
          <ComparisonTable data={comparisonData} />
        </div>
      )}
    </div>
  )
}
