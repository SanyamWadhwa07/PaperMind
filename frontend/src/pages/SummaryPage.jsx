import { useState, useEffect } from 'react'
import { useParams, Link } from 'react-router-dom'
import {
  ArrowLeft, Download, FileText, Database,
  BarChart3, BookOpen, Image, Share2, Star,
  Brain, Zap, FlaskConical, Presentation
} from 'lucide-react'
import { useAuth } from '../contexts/AuthContext'
import { useToast } from '../contexts/ToastContext'
import EntityDisplay from '../components/EntityDisplay'
import FiguresDisplay from '../components/FiguresDisplay'
import KnowledgeGraph from '../components/KnowledgeGraph'
import SectionSummaries from '../components/SectionSummaries'
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
  const [intelligence, setIntelligence] = useState(null)
  const [intelligenceLoading, setIntelligenceLoading] = useState(false)
  const [peerReviewLoading, setPeerReviewLoading] = useState(false)
  const [slideLoading, setSlideLoading] = useState(false)

  useEffect(() => {
    loadSummary()
  }, [id])

  const loadIntelligence = async () => {
    if (intelligence || intelligenceLoading) return
    setIntelligenceLoading(true)
    try {
      const res = await axios.get(`/api/intelligence/paper/${id}`, {
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
      await axios.post(`/api/intelligence/peer-review/${id}`, {}, {
        headers: { Authorization: `Bearer ${token}` },
      })
      await loadIntelligence()
      setIntelligence(null) // force reload
      toast.success('Peer review generated!')
    } catch (e) {
      toast.error('Peer review failed: ' + (e.response?.data?.detail || e.message))
    } finally {
      setPeerReviewLoading(false)
    }
  }

  const handleDownloadSlides = async () => {
    setSlideLoading(true)
    try {
      const res = await axios.post(`/api/export/slides/${id}`, {}, {
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
      const response = await fetch(`/api/summaries/${id}`, {
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
              { id: 'intelligence', label: 'Intelligence', icon: Brain },
            ].map(tab => (
              <button
                key={tab.id}
                onClick={() => {
                  setActiveTab(tab.id)
                  if (tab.id === 'graph') loadGraphData()
                  if (tab.id === 'intelligence') loadIntelligence()
                }}
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
              {(() => {
                const s = summaryData.summaries || {}
                const main = s.main
                const findings = summaryData.key_findings || []
                const contributions = summaryData.contributions || []
                const limitations = summaryData.limitations || []
                const futureWork = summaryData.future_work || []
                const resultRows = summaryData.results?.metrics || []
                const sectionSummaries = summaryData.section_summaries || {}

                return (
                  <>
                    {/* Comprehensive summary (LangGraph engine) — falls back to legacy 4-type below */}
                    {main ? (
                      <div className="bg-gradient-to-r from-[#EEF4F3] to-[#E0EBE9] dark:from-[#1E2020] dark:to-[#171919] p-5 rounded-lg border border-[#00988F]/20 dark:border-[#00A7A0]/20">
                        <h3 className="text-lg font-semibold mb-3 text-[#00988F] dark:text-[#00A7A0] flex items-center gap-2">
                          <FileText className="w-5 h-5" />
                          Comprehensive Summary
                        </h3>
                        <div className="text-[#1B1B1B] dark:text-[#F5F5F5] leading-relaxed whitespace-pre-wrap">
                          {main}
                        </div>
                      </div>
                    ) : (
                      <>
                        <div className="bg-gradient-to-r from-blue-50 to-blue-100 dark:from-blue-900/20 dark:to-blue-800/20 p-4 rounded-lg border border-blue-200 dark:border-blue-700">
                          <h3 className="text-lg font-semibold mb-3 text-blue-700 dark:text-blue-400 flex items-center gap-2">
                            <BookOpen className="w-5 h-5" /> Quick Overview
                          </h3>
                          <p className="text-[#1B1B1B] dark:text-[#F5F5F5] leading-relaxed">{s.simple || 'No summary available'}</p>
                        </div>
                        {s.detailed && (
                          <div className="bg-gradient-to-r from-purple-50 to-purple-100 dark:from-purple-900/20 dark:to-purple-800/20 p-4 rounded-lg border border-purple-200 dark:border-purple-700">
                            <h3 className="text-lg font-semibold mb-3 text-purple-700 dark:text-purple-400 flex items-center gap-2">
                              <FileText className="w-5 h-5" /> Detailed Academic Summary
                            </h3>
                            <div className="text-[#1B1B1B] dark:text-[#F5F5F5] leading-relaxed whitespace-pre-wrap">{s.detailed}</div>
                          </div>
                        )}
                        {s.eli5 && (
                          <div className="bg-gradient-to-r from-green-50 to-green-100 dark:from-green-900/20 dark:to-green-800/20 p-4 rounded-lg border border-green-200 dark:border-green-700">
                            <h3 className="text-lg font-semibold mb-3 text-green-700 dark:text-green-400 flex items-center gap-2">
                              <span className="text-xl">🎓</span> Explain Like I'm 5
                            </h3>
                            <p className="text-[#1B1B1B] dark:text-[#F5F5F5] leading-relaxed">{s.eli5}</p>
                          </div>
                        )}
                        {s.technical && (
                          <div className="bg-gradient-to-r from-orange-50 to-orange-100 dark:from-orange-900/20 dark:to-orange-800/20 p-4 rounded-lg border border-orange-200 dark:border-orange-700">
                            <h3 className="text-lg font-semibold mb-3 text-orange-700 dark:text-orange-400 flex items-center gap-2">
                              <BarChart3 className="w-5 h-5" /> Technical Analysis
                            </h3>
                            <div className="text-[#1B1B1B] dark:text-[#F5F5F5] leading-relaxed whitespace-pre-wrap">{s.technical}</div>
                          </div>
                        )}
                      </>
                    )}

                    {/* Key findings */}
                    {findings.length > 0 && (
                      <div className="bg-emerald-50 dark:bg-emerald-900/20 p-4 rounded-lg border border-emerald-200 dark:border-emerald-700">
                        <h3 className="text-lg font-semibold mb-3 text-emerald-700 dark:text-emerald-400 flex items-center gap-2">
                          <Zap className="w-5 h-5" /> Key Findings
                        </h3>
                        <ul className="list-disc list-inside space-y-1.5">
                          {findings.map((f, i) => <li key={i} className="text-[#1B1B1B] dark:text-[#F5F5F5] leading-relaxed">{f}</li>)}
                        </ul>
                      </div>
                    )}

                    {/* Contributions */}
                    {contributions.length > 0 && (
                      <div className="bg-indigo-50 dark:bg-indigo-900/20 p-4 rounded-lg border border-indigo-200 dark:border-indigo-700">
                        <h3 className="text-lg font-semibold mb-3 text-indigo-700 dark:text-indigo-400 flex items-center gap-2">
                          <Star className="w-5 h-5" /> Main Contributions
                        </h3>
                        <ul className="list-disc list-inside space-y-1.5">
                          {contributions.map((c, i) => <li key={i} className="text-[#1B1B1B] dark:text-[#F5F5F5] leading-relaxed">{c}</li>)}
                        </ul>
                      </div>
                    )}

                    {/* Results table */}
                    {resultRows.length > 0 && (
                      <div className="bg-slate-50 dark:bg-slate-800/50 p-4 rounded-lg border border-slate-200 dark:border-slate-700">
                        <h3 className="text-lg font-semibold mb-3 text-slate-700 dark:text-slate-300 flex items-center gap-2">
                          <BarChart3 className="w-5 h-5" /> Quantitative Results
                        </h3>
                        <div className="overflow-x-auto">
                          <table className="w-full text-sm">
                            <thead>
                              <tr className="text-xs text-slate-500 border-b border-slate-200 dark:border-slate-700">
                                <th className="text-left py-2 pr-3">Measurement</th>
                                <th className="text-left py-2 pr-3">Value</th>
                                <th className="text-left py-2 pr-3">Method</th>
                                <th className="text-left py-2">On</th>
                              </tr>
                            </thead>
                            <tbody>
                              {resultRows.map((r, i) => (
                                <tr key={i} className={`border-b border-slate-100 dark:border-slate-700/60 ${r.is_best ? 'bg-emerald-50 dark:bg-emerald-900/20' : ''}`}>
                                  <td className="py-1.5 pr-3 font-medium text-[#1B1B1B] dark:text-[#F5F5F5]">
                                    {r.metric || r.measurement || '-'}
                                    {r.is_best && <span className="ml-2 text-[10px] font-bold text-emerald-600 dark:text-emerald-400">BEST</span>}
                                  </td>
                                  <td className="py-1.5 pr-3 font-mono text-[#00988F] dark:text-[#00A7A0]">{r.value || '-'}</td>
                                  <td className="py-1.5 pr-3 text-slate-600 dark:text-slate-400">{r.model || r.method || '-'}</td>
                                  <td className="py-1.5 text-slate-500">{r.dataset || r.subject || '-'}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </div>
                    )}

                    {/* Limitations + Future work */}
                    {(limitations.length > 0 || futureWork.length > 0) && (
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        {limitations.length > 0 && (
                          <div className="bg-rose-50 dark:bg-rose-900/20 p-4 rounded-lg border border-rose-200 dark:border-rose-700">
                            <h3 className="text-base font-semibold mb-2 text-rose-700 dark:text-rose-400">Limitations</h3>
                            <ul className="list-disc list-inside space-y-1">
                              {limitations.map((l, i) => <li key={i} className="text-sm text-[#1B1B1B] dark:text-[#F5F5F5]">{l}</li>)}
                            </ul>
                          </div>
                        )}
                        {futureWork.length > 0 && (
                          <div className="bg-cyan-50 dark:bg-cyan-900/20 p-4 rounded-lg border border-cyan-200 dark:border-cyan-700">
                            <h3 className="text-base font-semibold mb-2 text-cyan-700 dark:text-cyan-400">Future Work</h3>
                            <ul className="list-disc list-inside space-y-1">
                              {futureWork.map((f, i) => <li key={i} className="text-sm text-[#1B1B1B] dark:text-[#F5F5F5]">{f}</li>)}
                            </ul>
                          </div>
                        )}
                      </div>
                    )}

                    {/* Per-section summaries */}
                    {Object.keys(sectionSummaries).length > 0 && (
                      <div>
                        <h3 className="text-lg font-semibold mb-3 text-[#C4935F] dark:text-[#D9A86C]">Section Summaries</h3>
                        <SectionSummaries summaries={sectionSummaries} />
                      </div>
                    )}
                  </>
                )
              })()}

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
            <EntityDisplay
              entities={summaryData.entities || {}}
              typed={summaryData.typed_entities || {}}
            />
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

          {activeTab === 'intelligence' && (
            <div className="space-y-6">
              {intelligenceLoading && (
                <div className="flex items-center justify-center h-32">
                  <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-indigo-500" />
                </div>
              )}
              {!intelligenceLoading && (
                <>
                  {/* Action buttons */}
                  <div className="flex flex-wrap gap-3">
                    <button
                      onClick={handleSimulatePeerReview}
                      disabled={peerReviewLoading}
                      className="flex items-center gap-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg text-sm font-medium disabled:opacity-50"
                    >
                      <FlaskConical className="w-4 h-4" />
                      {peerReviewLoading ? 'Simulating...' : 'Simulate Peer Review'}
                    </button>
                    <button
                      onClick={handleDownloadSlides}
                      disabled={slideLoading}
                      className="flex items-center gap-2 px-4 py-2 bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg text-sm font-medium disabled:opacity-50"
                    >
                      <Presentation className="w-4 h-4" />
                      {slideLoading ? 'Generating...' : 'Download Slides'}
                    </button>
                  </div>

                  {/* Research Gaps */}
                  {(() => {
                    const gapsData = intelligence?.gaps?.data || summaryData?.research_gaps || {}
                    const explicit = gapsData.explicit_gaps || []
                    const implicit = gapsData.implicit_gaps || []
                    const future = gapsData.future_directions || []
                    if (!explicit.length && !implicit.length && !future.length) return null
                    return (
                      <div className="bg-amber-50 dark:bg-amber-900/20 p-4 rounded-lg border border-amber-200 dark:border-amber-700">
                        <h3 className="text-lg font-semibold text-amber-700 dark:text-amber-400 mb-3 flex items-center gap-2">
                          <Zap className="w-5 h-5" /> Research Gaps
                        </h3>
                        {explicit.length > 0 && (
                          <div className="mb-3">
                            <p className="text-xs font-semibold text-amber-600 uppercase mb-1">Explicitly Stated</p>
                            <ul className="list-disc list-inside space-y-1">
                              {explicit.map((g, i) => <li key={i} className="text-sm text-amber-900 dark:text-amber-100">{g}</li>)}
                            </ul>
                          </div>
                        )}
                        {implicit.length > 0 && (
                          <div className="mb-3">
                            <p className="text-xs font-semibold text-amber-600 uppercase mb-1">Implicit Gaps</p>
                            <ul className="list-disc list-inside space-y-1">
                              {implicit.map((g, i) => <li key={i} className="text-sm text-amber-900 dark:text-amber-100">{g}</li>)}
                            </ul>
                          </div>
                        )}
                        {future.length > 0 && (
                          <div>
                            <p className="text-xs font-semibold text-amber-600 uppercase mb-1">Future Directions</p>
                            <ul className="list-disc list-inside space-y-1">
                              {future.map((g, i) => <li key={i} className="text-sm text-amber-900 dark:text-amber-100">{g}</li>)}
                            </ul>
                          </div>
                        )}
                      </div>
                    )
                  })()}

                  {/* Reproducibility Score */}
                  {(() => {
                    const repro = intelligence?.reproducibility?.data || summaryData?.reproducibility || {}
                    if (!repro.score && repro.score !== 0) return null
                    const score = repro.score || 0
                    const pct = Math.round((score / 10) * 100)
                    const color = score >= 7 ? '#22c55e' : score >= 4 ? '#f59e0b' : '#ef4444'
                    return (
                      <div className="bg-slate-50 dark:bg-slate-800/50 p-4 rounded-lg border border-slate-200 dark:border-slate-700">
                        <h3 className="text-lg font-semibold text-slate-700 dark:text-slate-300 mb-3">Reproducibility Score</h3>
                        <div className="flex items-center gap-4">
                          <div className="relative w-20 h-20 shrink-0">
                            <svg viewBox="0 0 36 36" className="w-full h-full -rotate-90">
                              <circle cx="18" cy="18" r="15.9" fill="none" stroke="#e2e8f0" strokeWidth="3" />
                              <circle cx="18" cy="18" r="15.9" fill="none" stroke={color} strokeWidth="3"
                                strokeDasharray={`${pct} ${100 - pct}`} strokeLinecap="round" />
                            </svg>
                            <div className="absolute inset-0 flex items-center justify-center">
                              <span className="text-xl font-bold" style={{ color }}>{score}/10</span>
                            </div>
                          </div>
                          <div className="flex-1 grid grid-cols-2 gap-1 text-xs">
                            {Object.entries(repro.evidence || {}).map(([k, v]) => (
                              <div key={k} className="flex items-center gap-1">
                                <span className={v ? 'text-green-500' : 'text-red-400'}>
                                  {v ? '✓' : '✗'}
                                </span>
                                <span className="text-slate-600 dark:text-slate-400 capitalize">
                                  {k.replace(/_/g, ' ')}
                                </span>
                              </div>
                            ))}
                          </div>
                        </div>
                        {(repro.github_links || []).length > 0 && (
                          <div className="mt-3">
                            <p className="text-xs font-semibold text-slate-500 mb-1">GitHub Links</p>
                            {repro.github_links.map((url, i) => (
                              <a key={i} href={url} target="_blank" rel="noopener noreferrer"
                                className="text-xs text-blue-500 hover:underline block truncate">{url}</a>
                            ))}
                          </div>
                        )}
                      </div>
                    )
                  })()}

                  {/* Peer Review */}
                  {(() => {
                    const pr = intelligence?.peer_review?.data
                    if (!pr) return null
                    const dims = ['novelty', 'soundness', 'clarity', 'significance']
                    const recColor = { accept: '#22c55e', minor_revision: '#f59e0b', major_revision: '#f97316', reject: '#ef4444' }
                    return (
                      <div className="bg-indigo-50 dark:bg-indigo-900/20 p-4 rounded-lg border border-indigo-200 dark:border-indigo-700">
                        <h3 className="text-lg font-semibold text-indigo-700 dark:text-indigo-400 mb-3 flex items-center gap-2">
                          <FlaskConical className="w-5 h-5" /> Simulated Peer Review
                        </h3>
                        <div className="flex items-center gap-2 mb-4">
                          <span className="text-sm font-medium text-slate-600 dark:text-slate-400">Recommendation:</span>
                          <span className="px-2 py-0.5 rounded-full text-xs font-bold text-white"
                            style={{ background: recColor[pr.recommendation] || '#6366f1' }}>
                            {(pr.recommendation || '').replace(/_/g, ' ').toUpperCase()}
                          </span>
                        </div>
                        <div className="grid grid-cols-2 gap-3 mb-4">
                          {dims.map(d => (
                            <div key={d}>
                              <div className="flex justify-between text-xs mb-1">
                                <span className="capitalize text-slate-600 dark:text-slate-400">{d}</span>
                                <span className="font-medium">{pr[d]}/10</span>
                              </div>
                              <div className="h-2 bg-slate-200 rounded-full">
                                <div className="h-2 bg-indigo-500 rounded-full" style={{ width: `${(pr[d] / 10) * 100}%` }} />
                              </div>
                            </div>
                          ))}
                        </div>
                        {pr.summary && <p className="text-sm text-slate-700 dark:text-slate-300 mb-3">{pr.summary}</p>}
                        {(pr.major_concerns || []).length > 0 && (
                          <div className="mb-2">
                            <p className="text-xs font-semibold text-red-600 mb-1">Major Concerns</p>
                            <ul className="list-disc list-inside space-y-1">
                              {pr.major_concerns.map((c, i) => <li key={i} className="text-xs text-red-800 dark:text-red-300">{c}</li>)}
                            </ul>
                          </div>
                        )}
                        {(pr.minor_concerns || []).length > 0 && (
                          <div>
                            <p className="text-xs font-semibold text-amber-600 mb-1">Minor Concerns</p>
                            <ul className="list-disc list-inside space-y-1">
                              {pr.minor_concerns.map((c, i) => <li key={i} className="text-xs text-amber-700 dark:text-amber-300">{c}</li>)}
                            </ul>
                          </div>
                        )}
                      </div>
                    )
                  })()}

                  {/* Ablation Studies */}
                  {(() => {
                    const ablation = intelligence?.ablation?.data?.ablation_studies || summaryData?.ablation_studies || []
                    if (!ablation.length) return null
                    return (
                      <div className="bg-slate-50 dark:bg-slate-800/50 p-4 rounded-lg border border-slate-200 dark:border-slate-700">
                        <h3 className="text-lg font-semibold text-slate-700 dark:text-slate-300 mb-3">Ablation Studies</h3>
                        <div className="overflow-x-auto">
                          <table className="w-full text-sm">
                            <thead><tr className="text-xs text-slate-500 border-b border-slate-200">
                              <th className="text-left py-1 pr-3">Component</th>
                              <th className="text-left py-1 pr-3">Metric</th>
                              <th className="text-left py-1 pr-3">Delta</th>
                              <th className="text-left py-1">Baseline</th>
                            </tr></thead>
                            <tbody>
                              {ablation.map((row, i) => (
                                <tr key={i} className="border-b border-slate-100 dark:border-slate-700">
                                  <td className="py-1 pr-3 font-medium text-slate-700 dark:text-slate-300">{row.component || '-'}</td>
                                  <td className="py-1 pr-3 text-slate-600 dark:text-slate-400">{row.metric || '-'}</td>
                                  <td className={`py-1 pr-3 font-mono ${row.delta > 0 ? 'text-green-600' : 'text-red-500'}`}>
                                    {row.delta != null ? `${row.delta > 0 ? '+' : ''}${row.delta}` : '-'}
                                  </td>
                                  <td className="py-1 font-mono text-slate-500">{row.baseline != null ? row.baseline : '-'}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </div>
                    )
                  })()}

                  {!intelligence?.gaps && !intelligence?.reproducibility && !intelligence?.peer_review && !summaryData?.research_gaps && (
                    <div className="text-center py-12 text-slate-400">
                      <Brain className="w-12 h-12 mx-auto mb-3 opacity-40" />
                      <p className="text-sm">Intelligence analysis will appear here after processing.</p>
                      <p className="text-xs mt-1 opacity-60">Use the buttons above to trigger on-demand analysis.</p>
                    </div>
                  )}
                </>
              )}
            </div>
          )}

        {/* Star rating */}
        <div className="mt-6 pt-4 border-t border-slate-700">
          <StarRating summaryId={id} />
        </div>
      </div>
    </div>
  )
}
