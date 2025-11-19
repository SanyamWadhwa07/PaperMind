import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Search, Upload, FileText, Calendar, TrendingUp, Clock, Zap, Brain, Shield, Sparkles, Github, Linkedin, Mail } from 'lucide-react'
import { useAuth } from '../contexts/AuthContext'
import { useToast } from '../contexts/ToastContext'
import { searchPapers, processArxivPaper, processUploadedPaper } from '../api'
import PaperCard from '../components/PaperCard'
import ProcessingModal from '../components/ProcessingModal'

export default function HomePage() {
  const navigate = useNavigate()
  const { isAuthenticated, token } = useAuth()
  const toast = useToast()
  const [topic, setTopic] = useState('')
  const [searchType, setSearchType] = useState('topic')
  const [maxResults, setMaxResults] = useState(10)
  const [sortBy, setSortBy] = useState('relevance')
  const [papers, setPapers] = useState([])
  const [loading, setLoading] = useState(false)
  const [processing, setProcessing] = useState(false)
  const [processingPaper, setProcessingPaper] = useState(null)

  const buildQuery = () => {
    if (!topic.trim()) {
      return 'cat:cs.LG' // Default fallback
    }

    // Smart query builder based on search type
    switch (searchType) {
      case 'topic':
        // Search in title and abstract for better topic matching
        return `all:"${topic.trim()}"` 
      case 'title':
        return `ti:"${topic.trim()}"`
      case 'author':
        return `au:"${topic.trim()}"`
      case 'abstract':
        return `abs:"${topic.trim()}"`
      default:
        return topic.trim()
    }
  }

  const handleSearch = async () => {
    if (!topic.trim()) {
      toast.error('Please enter a topic or keyword')
      return
    }

    setLoading(true)
    try {
      const query = buildQuery()
      const result = await searchPapers(query, maxResults)
      
      // Sort papers based on selected option
      let sortedPapers = [...result.papers]
      
      if (sortBy === 'newest') {
        sortedPapers.sort((a, b) => new Date(b.published) - new Date(a.published))
      } else if (sortBy === 'oldest') {
        sortedPapers.sort((a, b) => new Date(a.published) - new Date(b.published))
      }
      // 'relevance' keeps the original arXiv order
      
      setPapers(sortedPapers)
      toast.success(`Found ${result.count} papers!`)
    } catch (error) {
      toast.error('Failed to search papers: ' + error.message)
    } finally {
      setLoading(false)
    }
  }

  const handleFileUpload = async (event) => {
    const file = event.target.files[0]
    if (!file) return

    if (file.type !== 'application/pdf') {
      toast.error('Please upload a PDF file')
      return
    }

    if (!isAuthenticated) {
      toast.error('Please login to upload and summarize papers')
      navigate('/login')
      return
    }

    setProcessing(true)
    setProcessingPaper('Uploaded PDF')
    
    try {
      const result = await processUploadedPaper(file, token)
      toast.success('Paper summarized successfully!')
      navigate(`/summary/${result.summary_id}`)
    } catch (error) {
      toast.error('Failed to process PDF: ' + error.message)
    } finally {
      setProcessing(false)
      setProcessingPaper(null)
    }
  }

  const handleSummarize = async (paper) => {
    if (!isAuthenticated) {
      toast.error('Please login to summarize papers')
      navigate('/login')
      return
    }

    setProcessing(true)
    setProcessingPaper(paper.title)
    
    try {
      const result = await processArxivPaper(paper.arxiv_id, token)
      toast.success('Paper summarized successfully!')
      navigate(`/summary/${result.summary_id}`)
    } catch (error) {
      toast.error('Failed to summarize paper: ' + error.message)
    } finally {
      setProcessing(false)
      setProcessingPaper(null)
    }
  }

  return (
    <div className="space-y-8">
      {/* Hero Section */}
      <div className="text-center space-y-3 sm:space-y-4">
        <h2 className="text-2xl sm:text-3xl md:text-4xl font-bold text-[#C4935F] dark:text-[#D9A86C] px-2">
          Transform Research Papers with AI Intelligence
        </h2>
        <p className="text-base sm:text-lg md:text-xl text-[#1B1B1B] dark:text-[#F5F5F5] max-w-2xl mx-auto px-4">
          PaperMind extracts insights from academic papers using advanced AI. 
          Extract entities, keywords, and generate methodology flowcharts.
        </p>
      </div>

      {/* Upload Section */}
      <div className="card">
        <h3 className="text-lg font-semibold mb-4 flex items-center gap-2 text-[#C4935F] dark:text-[#D9A86C]">
          <Upload className="w-5 h-5" />
          Upload PDF
        </h3>
        <div className="flex items-center gap-4">
          <label className="btn-primary cursor-pointer">
            <FileText className="w-4 h-4" />
            Choose PDF File
            <input
              type="file"
              accept=".pdf"
              onChange={handleFileUpload}
              className="hidden"
              disabled={loading}
            />
          </label>
          <p className="text-sm text-[#1B1B1B] dark:text-[#F5F5F5]">
            Upload your own research paper for instant summarization
          </p>
        </div>
      </div>

      {/* Search Section */}
      <div className="card bg-gradient-to-br from-[#E8F0EF] to-[#DFE9E7] dark:from-[#1E2020]/50 dark:to-[#252727]/30 border-[#00988F]/30 dark:border-[#00A7A0]/30">
        <h3 className="text-xl font-bold mb-6 flex items-center gap-2 text-[#C4935F] dark:text-[#D9A86C]">
          <Search className="w-6 h-6" />
          Find Research Papers
        </h3>
        
        <div className="space-y-6">
          {/* Search Type Selector */}
          <div className="grid grid-cols-2 sm:flex sm:flex-wrap gap-2">
            {[
              { value: 'topic', label: 'Topic', icon: TrendingUp },
              { value: 'title', label: 'Title', icon: FileText },
              { value: 'author', label: 'Author', icon: Search },
              { value: 'abstract', label: 'Abstract', icon: FileText },
            ].map(({ value, label, icon: Icon }) => (
              <button
                key={value}
                onClick={() => setSearchType(value)}
                className={`flex items-center justify-center gap-1 sm:gap-2 px-3 sm:px-4 py-2 rounded-lg font-medium transition-all text-sm sm:text-base ${
                  searchType === value
                    ? 'bg-[#00988F] dark:bg-[#00A7A0] text-white shadow-md'
                    : 'bg-[#EEF4F3] dark:bg-[#1E2020] text-[#1B1B1B] dark:text-[#F5F5F5] hover:bg-[#E0EBE9] dark:hover:bg-[#252727] border border-[#C4935F]/20 dark:border-[#D9A86C]/20'
                }`}
              >
                <Icon className="w-4 h-4" />
                {label}
              </button>
            ))}
          </div>

          {/* Main Search Input */}
          <div>
            <label className="block text-sm font-medium text-[#1B1B1B] dark:text-[#F5F5F5] mb-2">
              {searchType === 'topic' && 'Enter any topic (e.g., deep learning, computer vision, NLP)'}
              {searchType === 'title' && 'Search by paper title'}
              {searchType === 'author' && 'Search by author name'}
              {searchType === 'abstract' && 'Search in abstract'}
            </label>
            <div className="relative">
              <input
                type="text"
                value={topic}
                onChange={(e) => setTopic(e.target.value)}
                onKeyPress={(e) => e.key === 'Enter' && handleSearch()}
                placeholder={
                  searchType === 'topic' ? 'e.g., transformer models, image segmentation, reinforcement learning...' :
                  searchType === 'author' ? 'e.g., Geoffrey Hinton, Yann LeCun...' :
                  searchType === 'title' ? 'e.g., Attention Is All You Need...' :
                  'Search in abstracts...'
                }
                className="w-full px-4 py-3 pr-12 border-2 border-gray-300 dark:border-gray-700 dark:bg-black/40 dark:text-white rounded-lg focus:ring-2 focus:ring-primary-500 dark:focus:ring-blue-500 focus:border-primary-500 dark:focus:border-blue-500 text-lg backdrop-blur-sm transition-colors"
                disabled={loading}
              />
              <Search className="absolute right-4 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-400" />
            </div>
            <p className="text-xs text-[#8F8F8F] dark:text-[#8F8F8F] mt-2">
               Use specific keywords for better results. Example topics: "attention mechanism", "GANs", "BERT fine-tuning"
            </p>
          </div>

          {/* Filters Row */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 sm:gap-4">
            <div>
              <label className="block text-sm font-medium text-[#1B1B1B] dark:text-[#F5F5F5] mb-2">
                <Calendar className="w-4 h-4 inline mr-1" />
                Sort By
              </label>
              <select
                value={sortBy}
                onChange={(e) => setSortBy(e.target.value)}
                className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent bg-white text-black"
              >
                <option value="relevance">Most Relevant</option>
                <option value="newest">Newest First</option>
                <option value="oldest">Oldest First</option>
              </select>
            </div>
            
            <div>
              <label className="block text-sm font-medium text-[#1B1B1B] dark:text-[#F5F5F5] mb-2">
                <Clock className="w-4 h-4 inline mr-1" />
                Number of Papers
              </label>
              <select
                value={maxResults}
                onChange={(e) => setMaxResults(parseInt(e.target.value))}
                className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent bg-white text-black"
              >
                <option value="5">5 papers</option>
                <option value="10">10 papers</option>
                <option value="15">15 papers</option>
                <option value="20">20 papers</option>
              </select>
            </div>
          </div>

          {/* Search Button */}
          <button
            onClick={handleSearch}
            disabled={loading || !topic.trim()}
            className="btn-primary w-full sm:w-auto px-6 sm:px-8 py-2 sm:py-3 text-base sm:text-lg disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <Search className="w-5 h-5" />
            {loading ? 'Searching arXiv...' : 'Search Papers'}
          </button>
        </div>
      </div>

      {/* Results */}
      {papers.length > 0 && (
        <div className="space-y-6 animate-fade-in">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 sm:gap-0">
            <div>
              <h3 className="text-xl sm:text-2xl font-bold text-[#C4935F] dark:text-[#D9A86C]">
                Found {papers.length} Papers
              </h3>
              <p className="text-xs sm:text-sm text-[#1B1B1B] dark:text-[#F5F5F5] mt-1">
                {topic && `Results for "${topic}"`} • Sorted by {sortBy === 'relevance' ? 'relevance' : sortBy === 'newest' ? 'newest first' : 'oldest first'}
              </p>
            </div>
            <div className="text-sm text-[#8F8F8F] dark:text-[#8F8F8F]">
              {papers.length} results
            </div>
          </div>
          <div className="grid gap-4">
            {papers.map((paper, index) => (
              <PaperCard
                key={index}
                paper={paper}
                onSummarize={handleSummarize}
                index={index}
              />
            ))}
          </div>
        </div>
      )}

      {/* Processing Modal */}
      {processing && (
        <ProcessingModal
          status={{ status: 'processing', message: `Processing ${processingPaper}...` }}
          onClose={() => {}}
        />
      )}

      {/* Features Section */}
      <div className="max-w-6xl mx-auto mt-20 space-y-16">
        <div className="text-center space-y-4">
          <h2 className="text-3xl sm:text-4xl font-bold text-[#C4935F] dark:text-[#D9A86C]">
            Why PaperMind?
          </h2>
          <p className="text-lg text-[#1B1B1B] dark:text-[#F5F5F5] max-w-2xl mx-auto">
            Advanced AI-powered research paper summarization with cutting-edge features
          </p>
        </div>

        <div className="grid md:grid-cols-2 lg:grid-cols-4 gap-6">
          {/* Feature 1 */}
          <div className="card group hover:shadow-xl transition-all duration-300 hover:-translate-y-1">
            <div className="w-12 h-12 bg-gradient-to-br from-teal-500 to-teal-600 rounded-lg flex items-center justify-center mb-4 group-hover:scale-110 transition-transform">
              <Brain className="w-6 h-6 text-white" />
            </div>
            <h3 className="text-xl font-bold text-[#C4935F] dark:text-[#D9A86C] mb-2">
              AI-Powered
            </h3>
            <p className="text-[#1B1B1B] dark:text-[#F5F5F5] text-sm">
              Using state-of-the-art LED transformer for hierarchical summarization and deep understanding
            </p>
          </div>

          {/* Feature 2 */}
          <div className="card group hover:shadow-xl transition-all duration-300 hover:-translate-y-1">
            <div className="w-12 h-12 bg-gradient-to-br from-amber-500 to-amber-600 rounded-lg flex items-center justify-center mb-4 group-hover:scale-110 transition-transform">
              <Zap className="w-6 h-6 text-white" />
            </div>
            <h3 className="text-xl font-bold text-[#C4935F] dark:text-[#D9A86C] mb-2">
              Lightning Fast
            </h3>
            <p className="text-[#1B1B1B] dark:text-[#F5F5F5] text-sm">
              Process papers in seconds with optimized GPU acceleration and smart caching
            </p>
          </div>

          {/* Feature 3 */}
          <div className="card group hover:shadow-xl transition-all duration-300 hover:-translate-y-1">
            <div className="w-12 h-12 bg-gradient-to-br from-purple-500 to-purple-600 rounded-lg flex items-center justify-center mb-4 group-hover:scale-110 transition-transform">
              <Shield className="w-6 h-6 text-white" />
            </div>
            <h3 className="text-xl font-bold text-[#C4935F] dark:text-[#D9A86C] mb-2">
              Secure & Private
            </h3>
            <p className="text-[#1B1B1B] dark:text-[#F5F5F5] text-sm">
              Your data is encrypted and protected. Full authentication system with email verification
            </p>
          </div>

          {/* Feature 4 */}
          <div className="card group hover:shadow-xl transition-all duration-300 hover:-translate-y-1">
            <div className="w-12 h-12 bg-gradient-to-br from-blue-500 to-blue-600 rounded-lg flex items-center justify-center mb-4 group-hover:scale-110 transition-transform">
              <Sparkles className="w-6 h-6 text-white" />
            </div>
            <h3 className="text-xl font-bold text-[#C4935F] dark:text-[#D9A86C] mb-2">
              Smart Analytics
            </h3>
            <p className="text-[#1B1B1B] dark:text-[#F5F5F5] text-sm">
              Entity extraction, keyword analysis, flowcharts, and interactive visualizations
            </p>
          </div>
        </div>
      </div>

      {/* About Section */}
      <div className="max-w-4xl mx-auto mt-20 card">
        <div className="text-center space-y-6">
          <h2 className="text-3xl sm:text-4xl font-bold text-[#C4935F] dark:text-[#D9A86C]">
            About PaperMind
          </h2>
          <div className="space-y-4 text-left text-[#1B1B1B] dark:text-[#F5F5F5]">
            <p className="leading-relaxed">
              <span className="font-semibold text-teal-600 dark:text-teal-400">PaperMind</span> is an advanced AI-powered research paper summarization platform designed to help researchers, students, and professionals quickly understand complex academic papers.
            </p>
            <p className="leading-relaxed">
              Using cutting-edge natural language processing with the <span className="font-semibold">LED (Longformer Encoder-Decoder)</span> transformer model, PaperMind performs hierarchical summarization that captures both high-level insights and detailed section-by-section breakdowns.
            </p>
            <p className="leading-relaxed">
              Our platform goes beyond simple summarization - we extract entities (datasets, models, metrics), generate keyword clouds, create methodology flowcharts, and provide comprehensive analytics to give you a complete understanding of any research paper.
            </p>
            <div className="grid sm:grid-cols-3 gap-4 mt-8 pt-6 border-t border-gray-200 dark:border-gray-700">
              <div className="text-center">
                <div className="text-3xl font-bold text-teal-600 dark:text-teal-400">1000+</div>
                <div className="text-sm text-gray-600 dark:text-gray-400 mt-1">Papers Summarized</div>
              </div>
              <div className="text-center">
                <div className="text-3xl font-bold text-teal-600 dark:text-teal-400">95%</div>
                <div className="text-sm text-gray-600 dark:text-gray-400 mt-1">Accuracy Rate</div>
              </div>
              <div className="text-center">
                <div className="text-3xl font-bold text-teal-600 dark:text-teal-400">10s</div>
                <div className="text-sm text-gray-600 dark:text-gray-400 mt-1">Avg Processing Time</div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Footer */}
      <footer className="mt-20 pt-8 border-t border-[#C4935F]/20 dark:border-[#D9A86C]/20">
        <div className="max-w-6xl mx-auto px-4">
          <div className="grid md:grid-cols-3 gap-8 mb-8">
            {/* Brand */}
            <div>
              <h3 className="text-xl font-bold text-[#C4935F] dark:text-[#D9A86C] mb-3">
                PaperMind
              </h3>
              <p className="text-sm text-[#1B1B1B] dark:text-[#F5F5F5]">
                AI-powered research paper summarization platform for the modern researcher.
              </p>
            </div>

            {/* Quick Links */}
            <div>
              <h4 className="font-semibold text-[#C4935F] dark:text-[#D9A86C] mb-3">
                Quick Links
              </h4>
              <ul className="space-y-2 text-sm">
                <li>
                  <a href="#" className="text-[#1B1B1B] dark:text-[#F5F5F5] hover:text-teal-600 dark:hover:text-teal-400 transition-colors">
                    Features
                  </a>
                </li>
                <li>
                  <a href="#" className="text-[#1B1B1B] dark:text-[#F5F5F5] hover:text-teal-600 dark:hover:text-teal-400 transition-colors">
                    About
                  </a>
                </li>
                <li>
                  <a href="/dashboard" className="text-[#1B1B1B] dark:text-[#F5F5F5] hover:text-teal-600 dark:hover:text-teal-400 transition-colors">
                    Dashboard
                  </a>
                </li>
              </ul>
            </div>

            {/* Contact */}
            <div>
              <h4 className="font-semibold text-[#C4935F] dark:text-[#D9A86C] mb-3">
                Connect
              </h4>
              <div className="flex gap-3">
                <a 
                  href="https://github.com" 
                  target="_blank" 
                  rel="noopener noreferrer"
                  className="w-10 h-10 bg-[#F9FBFA] dark:bg-[#1E2020] rounded-lg flex items-center justify-center hover:bg-teal-500 dark:hover:bg-teal-500 text-[#1B1B1B] dark:text-[#F5F5F5] hover:text-white transition-all"
                >
                  <Github className="w-5 h-5" />
                </a>
                <a 
                  href="https://linkedin.com" 
                  target="_blank" 
                  rel="noopener noreferrer"
                  className="w-10 h-10 bg-[#F9FBFA] dark:bg-[#1E2020] rounded-lg flex items-center justify-center hover:bg-teal-500 dark:hover:bg-teal-500 text-[#1B1B1B] dark:text-[#F5F5F5] hover:text-white transition-all"
                >
                  <Linkedin className="w-5 h-5" />
                </a>
                <a 
                  href="mailto:contact@papermind.ai" 
                  className="w-10 h-10 bg-[#F9FBFA] dark:bg-[#1E2020] rounded-lg flex items-center justify-center hover:bg-teal-500 dark:hover:bg-teal-500 text-[#1B1B1B] dark:text-[#F5F5F5] hover:text-white transition-all"
                >
                  <Mail className="w-5 h-5" />
                </a>
              </div>
            </div>
          </div>

          {/* Copyright */}
          <div className="pt-6 border-t border-[#C4935F]/20 dark:border-[#D9A86C]/20 text-center">
            <p className="text-sm text-[#8F8F8F]">
              © {new Date().getFullYear()} PaperMind. Created by{' '}
              <span className="font-semibold text-[#C4935F] dark:text-[#D9A86C]">
                Sanyam Wadhwa
              </span>
              . All rights reserved.
            </p>
          </div>
        </div>
      </footer>
    </div>
  )
}
