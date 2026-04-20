import { useState, useEffect } from 'react'
import { useParams, Link } from 'react-router-dom'
import {
  ArrowLeft, Download, FileText, Database,
  BarChart3, BookOpen, Image, Share2, Star
} from 'lucide-react'
import { useAuth } from '../contexts/AuthContext'
import { useToast } from '../contexts/ToastContext'
import EntityDisplay from '../components/EntityDisplay'
import FiguresDisplay from '../components/FiguresDisplay'
import KnowledgeGraph from '../components/KnowledgeGraph'
import StarRating from '../components/StarRating'
import axios from 'axios'

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

  useEffect(() => {
    loadSummary()
  }, [id])

  // Lazy-load graph data when graph tab is first opened
  const loadGraphData = async () => {
    if (graphData || graphLoading) return
    setGraphLoading(true)
    try {
      const [graphRes, recsRes] = await Promise.all([
        axios.get(`/api/graph/paper/${id}`, { headers: { Authorization: `Bearer ${token}` } }),
        axios.get(`/api/graph/recommendations/${id}`, { headers: { Authorization: `Bearer ${token}` } }),
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
      const response = await fetch(`http://localhost:5000/api/summaries/${id}`, {
        headers: { 'Authorization': `Bearer ${token}` }
      })
      const result = await response.json()
      
      if (response.ok) {
        setSummary(result.summary)
      } else {
        toast.error('Failed to load summary')
      }
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
      <div className="flex items-center justify-center h-96">
        <div className="text-center space-y-3">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-[#00988F] dark:border-[#00A7A0] mx-auto" />
          <p className="text-[#1B1B1B] dark:text-[#F5F5F5] font-medium">Loading summary...</p>
        </div>
      </div>
    )
  }

  if (!summary) {
    return (
      <div className="text-center space-y-4">
        <p className="text-xl text-[#1B1B1B] dark:text-[#F5F5F5] font-medium">Summary not found</p>
        <Link to="/" className="btn-primary inline-flex">
          <ArrowLeft className="w-4 h-4" />
          Back to Home
        </Link>
      </div>
    )
  }

  const summaryData = summary.summary_data || {}
  const compressionRatio = summary.word_count && summaryData.num_words_original 
    ? ((1 - summary.word_count / summaryData.num_words_original) * 100).toFixed(1)
    : 'N/A'

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row items-stretch sm:items-start justify-between gap-3 sm:gap-4">
        <Link to="/" className="btn-secondary justify-center">
          <ArrowLeft className="w-4 h-4" />
          Back
        </Link>
        
        <div className="flex gap-2">
          <button
            onClick={() => handleExport('json')}
            className="btn-secondary"
          >
            <Download className="w-4 h-4" />
            JSON
          </button>
          <button
            onClick={() => handleExport('markdown')}
            className="btn-secondary"
          >
            <Download className="w-4 h-4" />
            Markdown
          </button>
          <button
            onClick={() => handleExport('bibtex')}
            className="btn-secondary"
          >
            <Download className="w-4 h-4" />
            BibTeX
          </button>
        </div>
      </div>

      {/* Title & Meta */}
      <div className="card">
        <h1 className="text-xl sm:text-2xl md:text-3xl font-bold text-[#C4935F] dark:text-[#D9A86C] mb-4 break-words">
          {summary.paper_title}
        </h1>
        
        <div className="flex flex-col sm:flex-row sm:flex-wrap gap-2 sm:gap-4 text-xs sm:text-sm text-[#1B1B1B] dark:text-[#F5F5F5]">
          <div>
            <span className="font-medium">Authors:</span>{' '}
            {summary.paper_authors?.join(', ') || 'Unknown'}
          </div>
          <div>
            <span className="font-medium">Published:</span>{' '}
            {summary.created_at ? new Date(summary.created_at).toLocaleDateString() : 'N/A'}
          </div>
          {summary.arxiv_id && summary.arxiv_id !== 'uploaded' && (
            <div>
              <span className="font-medium">arXiv ID:</span>{' '}
              {summary.arxiv_id}
            </div>
          )}
        </div>
      </div>

      {/* Metrics */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 sm:gap-4">
        <div className="card">
          <p className="text-sm text-[#8F8F8F] dark:text-[#8F8F8F] mb-1">Model</p>
          <p className="text-xl font-bold text-[#1B1B1B] dark:text-[#F5F5F5]">
            {summary.model_used || 'LED'}
          </p>
        </div>
        <div className="card">
          <p className="text-sm text-[#8F8F8F] dark:text-[#8F8F8F] mb-1">Summary Words</p>
          <p className="text-2xl font-bold text-[#1B1B1B] dark:text-[#F5F5F5]">
            {summary.word_count?.toLocaleString() || 'N/A'}
          </p>
        </div>
        <div className="card">
          <p className="text-sm text-[#8F8F8F] dark:text-[#8F8F8F] mb-1">Processing Time</p>
          <p className="text-2xl font-bold text-[#00988F] dark:text-[#00A7A0]">
            {summary.processing_time_seconds ? `${summary.processing_time_seconds}s` : 'N/A'}
          </p>
        </div>
        <div className="card">
          <p className="text-sm text-[#8F8F8F] dark:text-[#8F8F8F] mb-1">Sections</p>
          <p className="text-2xl font-bold text-[#1B1B1B] dark:text-[#F5F5F5]">
            {summaryData.sections_found?.length || 0}
          </p>
        </div>
        {summary.quality_score != null && (
          <div className="card">
            <p className="text-sm text-[#8F8F8F] dark:text-[#8F8F8F] mb-1">Quality</p>
            <p className="text-2xl font-bold text-emerald-500">
              {Math.round(summary.quality_score * 100)}%
            </p>
          </div>
        )}
      </div>

      {/* Tabs */}
      <div className="card">
        <div className="border-b border-gray-200 mb-6 -mx-6 px-6 sm:mx-0 sm:px-0">
          <div className="flex gap-1 overflow-x-auto scrollbar-hide">
            {[
              { id: 'summaries', label: 'Summaries', icon: BookOpen },
              { id: 'entities', label: 'Entities', icon: Database },
              { id: 'figures', label: 'Figures', icon: Image },
              { id: 'graph', label: 'Knowledge Graph', icon: Share2 },
            ].map(tab => (
              <button
                key={tab.id}
                onClick={() => { setActiveTab(tab.id); if (tab.id === 'graph') loadGraphData() }}
                className={`flex items-center gap-1 sm:gap-2 px-3 sm:px-4 py-2 sm:py-3 border-b-2 font-medium transition-colors whitespace-nowrap text-sm sm:text-base ${
                  activeTab === tab.id
                    ? 'border-[#00988F] dark:border-[#00A7A0] text-[#00988F] dark:text-[#00A7A0]'
                    : 'border-transparent text-[#8F8F8F] hover:text-[#1B1B1B] dark:hover:text-[#F5F5F5]'
                }`}
              >
                <tab.icon className="w-4 h-4" />
                {tab.label}
              </button>
            ))}
          </div>
        </div>

        {/* Tab Content */}
        <div className="space-y-6">
          {activeTab === 'summaries' && (
            <div className="space-y-6">
              {/* Simple Summary */}
              <div className="bg-gradient-to-r from-blue-50 to-blue-100 dark:from-blue-900/20 dark:to-blue-800/20 p-4 rounded-lg border border-blue-200 dark:border-blue-700">
                <h3 className="text-lg font-semibold mb-3 text-blue-700 dark:text-blue-400 flex items-center gap-2">
                  <BookOpen className="w-5 h-5" />
                  Quick Overview
                </h3>
                <p className="text-[#1B1B1B] dark:text-[#F5F5F5] leading-relaxed">
                  {summaryData.summaries?.simple || 'No simple summary available'}
                </p>
              </div>

              {/* Detailed Summary */}
              <div className="bg-gradient-to-r from-purple-50 to-purple-100 dark:from-purple-900/20 dark:to-purple-800/20 p-4 rounded-lg border border-purple-200 dark:border-purple-700">
                <h3 className="text-lg font-semibold mb-3 text-purple-700 dark:text-purple-400 flex items-center gap-2">
                  <FileText className="w-5 h-5" />
                  Detailed Academic Summary
                </h3>
                <div className="text-[#1B1B1B] dark:text-[#F5F5F5] leading-relaxed whitespace-pre-wrap">
                  {summaryData.summaries?.detailed || 'No detailed summary available'}
                </div>
              </div>

              {/* ELI5 Summary */}
              <div className="bg-gradient-to-r from-green-50 to-green-100 dark:from-green-900/20 dark:to-green-800/20 p-4 rounded-lg border border-green-200 dark:border-green-700">
                <h3 className="text-lg font-semibold mb-3 text-green-700 dark:text-green-400 flex items-center gap-2">
                  <span className="text-xl">🎓</span>
                  Explain Like I'm 5
                </h3>
                <p className="text-[#1B1B1B] dark:text-[#F5F5F5] leading-relaxed">
                  {summaryData.summaries?.eli5 || 'No ELI5 summary available'}
                </p>
              </div>

              {/* Technical Summary */}
              <div className="bg-gradient-to-r from-orange-50 to-orange-100 dark:from-orange-900/20 dark:to-orange-800/20 p-4 rounded-lg border border-orange-200 dark:border-orange-700">
                <h3 className="text-lg font-semibold mb-3 text-orange-700 dark:text-orange-400 flex items-center gap-2">
                  <BarChart3 className="w-5 h-5" />
                  Technical Analysis
                </h3>
                <div className="text-[#1B1B1B] dark:text-[#F5F5F5] leading-relaxed whitespace-pre-wrap">
                  {summaryData.summaries?.technical || 'No technical summary available'}
                </div>
              </div>

              {/* Agent Metadata */}
              {summaryData.agent_metadata && (
                <div className="bg-gray-50 dark:bg-gray-900/50 p-4 rounded-lg border border-gray-200 dark:border-gray-700">
                  <h3 className="text-lg font-semibold mb-3 text-gray-700 dark:text-gray-300">Processing Info</h3>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
                    <div>
                      <span className="text-[#8F8F8F] dark:text-[#8F8F8F]">Mode:</span>
                      <p className="font-medium text-[#1B1B1B] dark:text-[#F5F5F5]">{summaryData.agent_metadata.processing_mode || 'N/A'}</p>
                    </div>
                    <div>
                      <span className="text-[#8F8F8F] dark:text-[#8F8F8F]">Agents:</span>
                      <p className="font-medium text-[#1B1B1B] dark:text-[#F5F5F5]">{summaryData.agent_metadata.agent_count || 'N/A'}</p>
                    </div>
                    <div>
                      <span className="text-[#8F8F8F] dark:text-[#8F8F8F]">Time:</span>
                      <p className="font-medium text-[#1B1B1B] dark:text-[#F5F5F5]">{summaryData.agent_metadata.total_time_ms ? `${(summaryData.agent_metadata.total_time_ms / 1000).toFixed(1)}s` : 'N/A'}</p>
                    </div>
                    <div>
                      <span className="text-[#8F8F8F] dark:text-[#8F8F8F]">LLM:</span>
                      <p className="font-medium text-[#1B1B1B] dark:text-[#F5F5F5]">{summaryData.agent_metadata.llm_backend || 'N/A'}</p>
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}

          {activeTab === 'entities' && (
            <EntityDisplay entities={summaryData.entities || {}} />
          )}

          {activeTab === 'figures' && (
            <FiguresDisplay figures={summaryData.figures || []} />
          )}

          {activeTab === 'graph' && (
            <div className="space-y-6">
              {graphLoading ? (
                <div className="flex items-center justify-center h-48">
                  <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-indigo-500" />
                </div>
              ) : (
                <KnowledgeGraph
                  nodes={graphData?.nodes || []}
                  edges={graphData?.edges || []}
                  height={440}
                />
              )}

              {recommendations.length > 0 && (
                <div>
                  <h3 className="text-base font-semibold text-slate-300 mb-3">Similar Papers</h3>
                  <div className="space-y-2">
                    {recommendations.map((rec) => {
                      const paper = rec.summaries || rec
                      return (
                        <Link
                          key={rec.paper_b_id || rec.id}
                          to={`/summary/${rec.paper_b_id || rec.id}`}
                          className="flex items-center justify-between p-3 bg-slate-800 rounded-lg hover:bg-slate-700 transition-colors"
                        >
                          <span className="text-sm text-slate-200 truncate">{paper.paper_title || 'Untitled'}</span>
                          <span className="text-xs text-slate-500 ml-2 shrink-0">
                            {(rec.similarity_score * 100).toFixed(0)}% similar
                          </span>
                        </Link>
                      )
                    })}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Star rating */}
        <div className="mt-6 pt-4 border-t border-slate-700">
          <StarRating summaryId={id} />
        </div>
      </div>
    </div>
  )
}
