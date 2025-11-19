import { useState, useEffect } from 'react'
import { useParams, Link } from 'react-router-dom'
import { 
  ArrowLeft, Download, FileText, Hash, Database, 
  BarChart3, GitBranch, BookOpen 
} from 'lucide-react'
import { useAuth } from '../contexts/AuthContext'
import { useToast } from '../contexts/ToastContext'
import EntityDisplay from '../components/EntityDisplay'
import KeywordCloud from '../components/KeywordCloud'
import SectionSummaries from '../components/SectionSummaries'
import FlowchartViewer from '../components/FlowchartViewer'
import ErrorBoundary from '../components/ErrorBoundary'

export default function SummaryPage() {
  const { id } = useParams()
  const { token } = useAuth()
  const toast = useToast()
  const [summary, setSummary] = useState(null)
  const [loading, setLoading] = useState(true)
  const [activeTab, setActiveTab] = useState('overview')

  useEffect(() => {
    loadSummary()
  }, [id])

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
        if (summary.summary_data?.overall_summary) {
          md += `## Summary\n\n${summary.summary_data.overall_summary}\n\n`
        }
        if (summary.summary_data?.overall_keywords?.length) {
          md += `## Keywords\n\n${summary.summary_data.overall_keywords.join(', ')}\n\n`
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
      </div>

      {/* Tabs */}
      <div className="card">
        <div className="border-b border-gray-200 mb-6 -mx-6 px-6 sm:mx-0 sm:px-0">
          <div className="flex gap-1 overflow-x-auto scrollbar-hide">
            {[
              { id: 'overview', label: 'Overview', icon: BookOpen },
              { id: 'sections', label: 'Sections', icon: FileText },
              { id: 'entities', label: 'Entities', icon: Database },
              { id: 'keywords', label: 'Keywords', icon: Hash },
              { id: 'flowchart', label: 'Flowchart', icon: GitBranch },
            ].map(tab => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
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
          {activeTab === 'overview' && (
            <div className="space-y-4">
              <div>
                <h3 className="text-lg font-semibold mb-3 text-[#C4935F] dark:text-[#D9A86C]">Overall Summary</h3>
                <p className="text-[#1B1B1B] dark:text-[#F5F5F5] leading-relaxed">
                  {summaryData.overall_summary || 'No summary available'}
                </p>
              </div>

              {summaryData.sections_found?.length > 0 && (
                <div>
                  <h3 className="text-lg font-semibold mb-3 text-[#C4935F] dark:text-[#D9A86C]">Detected Sections</h3>
                  <div className="flex flex-wrap gap-2">
                    {summaryData.sections_found.map((section, idx) => (
                      <span key={idx} className="badge badge-blue">
                        {section.replace('_', ' ').toUpperCase()}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {activeTab === 'sections' && (
            <SectionSummaries summaries={summaryData.section_summaries || {}} />
          )}

          {activeTab === 'entities' && (
            <EntityDisplay entities={summaryData.entities || {}} />
          )}

          {activeTab === 'keywords' && (
            <KeywordCloud
              overallKeywords={summaryData.overall_keywords || []}
              sectionKeywords={summaryData.section_keywords || {}}
            />
          )}

          {activeTab === 'flowchart' && (
            <ErrorBoundary>
              <FlowchartViewer flowchart={summaryData.methodology_flowchart} />
            </ErrorBoundary>
          )}
        </div>
      </div>
    </div>
  )
}
