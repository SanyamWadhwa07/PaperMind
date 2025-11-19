import { useState, useEffect } from 'react'
import { useAuth } from '../contexts/AuthContext'
import { useToast } from '../contexts/ToastContext'
import { Link } from 'react-router-dom'
import ActivityChart from '../components/ActivityChart'
import { 
  FileText, 
  TrendingUp, 
  Clock, 
  Calendar,
  Search,
  Filter,
  Download,
  Trash2,
  Eye
} from 'lucide-react'

export default function DashboardPage() {
  const { token } = useAuth()
  const toast = useToast()
  const [stats, setStats] = useState(null)
  const [summaries, setSummaries] = useState([])
  const [loading, setLoading] = useState(true)
  const [page, setPage] = useState(1)
  const [totalPages, setTotalPages] = useState(1)
  const [searchTerm, setSearchTerm] = useState('')
  const [sortBy, setSortBy] = useState('created_at')
  const [monthlySummaries, setMonthlySummaries] = useState({})
  const [recentActivity, setRecentActivity] = useState([])

  useEffect(() => {
    fetchDashboardData()
  }, [page, sortBy])

  const fetchDashboardData = async () => {
    setLoading(true)
    try {
      // Fetch stats
      const statsRes = await fetch('http://localhost:5000/api/dashboard/stats', {
        headers: { 'Authorization': `Bearer ${token}` }
      })
      const statsData = await statsRes.json()
      setStats(statsData.stats)
      setMonthlySummaries(statsData.monthly_summaries || {})
      setRecentActivity(statsData.recent_activity || [])

      // Fetch summaries
      const summariesRes = await fetch(
        `http://localhost:5000/api/summaries?page=${page}&per_page=10&sort_by=${sortBy}&order=desc&search=${searchTerm}`,
        { headers: { 'Authorization': `Bearer ${token}` } }
      )
      const summariesData = await summariesRes.json()
      setSummaries(summariesData.summaries)
      setTotalPages(summariesData.total_pages)
    } catch (error) {
      console.error('Failed to fetch dashboard data:', error)
      toast.error('Failed to load dashboard data')
    }
    setLoading(false)
  }

  const handleSearch = (e) => {
    e.preventDefault()
    setPage(1)
    fetchDashboardData()
  }

  const deleteSummary = async (id) => {
    if (!confirm('Are you sure you want to delete this summary?')) return

    try {
      await fetch(`http://localhost:5000/api/summaries/${id}`, {
        method: 'DELETE',
        headers: { 'Authorization': `Bearer ${token}` }
      })
      toast.success('Summary deleted successfully')
      fetchDashboardData()
    } catch (error) {
      console.error('Failed to delete summary:', error)
      toast.error('Failed to delete summary')
    }
  }

  if (loading && !stats) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="animate-spin rounded-full h-12 w-12 border-4 border-[#00988F] border-t-transparent"></div>
      </div>
    )
  }

  return (
    <div className="space-y-6 sm:space-y-8">
      {/* Header */}
      <div>
        <h1 className="text-2xl sm:text-3xl md:text-4xl font-bold text-[#C4935F] dark:text-[#D9A86C]">
          Dashboard
        </h1>
        <p className="mt-2 text-sm sm:text-base text-[#1B1B1B] dark:text-[#F5F5F5]">
          Track your research summaries and activity
        </p>
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="card">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-[#8F8F8F]">Total Summaries</p>
              <p className="text-2xl sm:text-3xl font-bold text-[#C4935F] dark:text-[#D9A86C] mt-1">
                {stats?.total_summaries || 0}
              </p>
            </div>
            <FileText className="w-8 h-8 text-[#00988F] dark:text-[#00A7A0]" />
          </div>
        </div>

        <div className="card">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-[#8F8F8F]">Avg Processing Time</p>
              <p className="text-2xl sm:text-3xl font-bold text-[#C4935F] dark:text-[#D9A86C] mt-1">
                {stats?.avg_processing_time?.toFixed(1) || 0}s
              </p>
            </div>
            <Clock className="w-8 h-8 text-[#00988F] dark:text-[#00A7A0]" />
          </div>
        </div>

        <div className="card">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-[#8F8F8F]">Words Processed</p>
              <p className="text-2xl sm:text-3xl font-bold text-[#C4935F] dark:text-[#D9A86C] mt-1">
                {(stats?.total_words_processed || 0).toLocaleString()}
              </p>
            </div>
            <TrendingUp className="w-8 h-8 text-[#00988F] dark:text-[#00A7A0]" />
          </div>
        </div>

        <div className="card">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-[#8F8F8F]">Active Days</p>
              <p className="text-2xl sm:text-3xl font-bold text-[#C4935F] dark:text-[#D9A86C] mt-1">
                {stats?.active_days || 0}
              </p>
            </div>
            <Calendar className="w-8 h-8 text-[#00988F] dark:text-[#00A7A0]" />
          </div>
        </div>
      </div>

      {/* Activity Chart */}
      <ActivityChart 
        monthlySummaries={monthlySummaries} 
        recentActivity={recentActivity}
      />

      {/* Search and Filters */}
      <div className="card">
        <form onSubmit={handleSearch} className="flex flex-col sm:flex-row gap-3">
          <div className="flex-1 relative">
            <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 w-5 h-5 text-[#8F8F8F]" />
            <input
              type="text"
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              placeholder="Search summaries..."
              className="w-full pl-10 pr-4 py-2 bg-[#F9FBFA] dark:bg-[#111312] border border-[#C4935F]/30 dark:border-[#D9A86C]/30 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#00988F] dark:focus:ring-[#00A7A0] text-[#1B1B1B] dark:text-[#F5F5F5]"
            />
          </div>
          <div className="flex gap-2">
            <select
              value={sortBy}
              onChange={(e) => setSortBy(e.target.value)}
              className="px-4 py-2 bg-[#F9FBFA] dark:bg-[#111312] border border-[#C4935F]/30 dark:border-[#D9A86C]/30 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#00988F] dark:focus:ring-[#00A7A0] text-[#1B1B1B] dark:text-[#F5F5F5] text-black"
            >
              <option value="created_at">Newest First</option>
              <option value="paper_title">Title A-Z</option>
              <option value="processing_time_seconds">Processing Time</option>
            </select>
            <button type="submit" className="btn-primary px-6">
              Search
            </button>
          </div>
        </form>
      </div>

      {/* Summaries List */}
      <div className="space-y-4">
        <h2 className="text-xl sm:text-2xl font-bold text-[#C4935F] dark:text-[#D9A86C]">
          Your Summaries
        </h2>

        {summaries.length === 0 ? (
          <div className="card text-center py-12">
            <FileText className="w-16 h-16 mx-auto text-[#8F8F8F] mb-4" />
            <p className="text-lg text-[#1B1B1B] dark:text-[#F5F5F5] mb-2">
              No summaries yet
            </p>
            <p className="text-sm text-[#8F8F8F] mb-4">
              Start by searching for papers or uploading PDFs
            </p>
            <Link to="/" className="btn-primary inline-flex">
              Create Summary
            </Link>
          </div>
        ) : (
          <>
            {summaries.map((summary) => (
              <div key={summary.id} className="card">
                <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-4">
                  <div className="flex-1 min-w-0">
                    <h3 className="text-lg sm:text-xl font-bold text-[#C4935F] dark:text-[#D9A86C] mb-2 break-words">
                      {summary.paper_title}
                    </h3>
                    <div className="flex flex-wrap gap-2 text-xs sm:text-sm text-[#8F8F8F] mb-3">
                      {summary.arxiv_id && (
                        <span className="badge badge-blue">{summary.arxiv_id}</span>
                      )}
                      <span className="flex items-center gap-1">
                        <Calendar className="w-4 h-4" />
                        {new Date(summary.created_at).toLocaleDateString()}
                      </span>
                      <span className="flex items-center gap-1">
                        <Clock className="w-4 h-4" />
                        {summary.processing_time_seconds?.toFixed(1)}s
                      </span>
                    </div>
                    {summary.paper_authors && summary.paper_authors.length > 0 && (
                      <p className="text-sm text-[#1B1B1B] dark:text-[#F5F5F5]">
                        {summary.paper_authors.slice(0, 3).join(', ')}
                        {summary.paper_authors.length > 3 && ` +${summary.paper_authors.length - 3} more`}
                      </p>
                    )}
                  </div>
                  <div className="flex sm:flex-col gap-2">
                    <Link
                      to={`/summary/${summary.id}`}
                      className="btn-primary text-sm px-3 py-2 flex-1 sm:flex-initial justify-center"
                    >
                      <Eye className="w-4 h-4" />
                      View
                    </Link>
                    <button
                      onClick={() => deleteSummary(summary.id)}
                      className="btn-secondary text-sm px-3 py-2 flex-1 sm:flex-initial justify-center hover:bg-red-50 dark:hover:bg-red-900/20 hover:text-red-600 dark:hover:text-red-400"
                    >
                      <Trash2 className="w-4 h-4" />
                      Delete
                    </button>
                  </div>
                </div>
              </div>
            ))}

            {/* Pagination */}
            {totalPages > 1 && (
              <div className="flex justify-center gap-2 mt-6">
                <button
                  onClick={() => setPage(p => Math.max(1, p - 1))}
                  disabled={page === 1}
                  className="btn-secondary px-4 py-2 disabled:opacity-50"
                >
                  Previous
                </button>
                <span className="px-4 py-2 text-[#1B1B1B] dark:text-[#F5F5F5]">
                  Page {page} of {totalPages}
                </span>
                <button
                  onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                  disabled={page === totalPages}
                  className="btn-secondary px-4 py-2 disabled:opacity-50"
                >
                  Next
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
