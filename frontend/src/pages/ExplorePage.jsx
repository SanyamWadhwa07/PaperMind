import { useState, useEffect } from 'react'
import { Network, GitBranch, Users, AlertTriangle, RefreshCw } from 'lucide-react'
import { useAuth } from '../contexts/AuthContext'
import { useToast } from '../contexts/ToastContext'
import KnowledgeGraph from '../components/KnowledgeGraph'
import axios from 'axios'

const TABS = [
  { id: 'topic-clusters', label: 'Topic Clusters', icon: Network },
  { id: 'citation-network', label: 'Citation Network', icon: GitBranch },
  { id: 'author-graph', label: 'Author Network', icon: Users },
  { id: 'contradiction-map', label: 'Contradictions', icon: AlertTriangle },
]

const ENDPOINT = {
  'topic-clusters': '/api/corpus/topic-clusters',
  'citation-network': '/api/corpus/citation-network',
  'author-graph': '/api/corpus/author-graph',
  'contradiction-map': '/api/corpus/contradiction-map',
}

export default function ExplorePage() {
  const { token } = useAuth()
  const toast = useToast()
  const [activeTab, setActiveTab] = useState('topic-clusters')
  const [graphData, setGraphData] = useState({})
  const [loading, setLoading] = useState(false)
  const [recomputing, setRecomputing] = useState(false)

  useEffect(() => {
    loadTab(activeTab)
  }, [activeTab])

  const loadTab = async (tab) => {
    if (graphData[tab]) return
    setLoading(true)
    try {
      const res = await axios.get(ENDPOINT[tab], {
        headers: { Authorization: `Bearer ${token}` },
      })
      setGraphData(prev => ({ ...prev, [tab]: res.data }))
    } catch (e) {
      toast.error('Failed to load graph: ' + (e.response?.data?.detail || e.message))
      setGraphData(prev => ({ ...prev, [tab]: { nodes: [], edges: [] } }))
    } finally {
      setLoading(false)
    }
  }

  const handleRecompute = async () => {
    setRecomputing(true)
    try {
      await axios.post('/api/corpus/recompute-clusters', {}, {
        headers: { Authorization: `Bearer ${token}` },
      })
      toast.success('Cluster recomputation started (background task).')
      setGraphData(prev => ({ ...prev, 'topic-clusters': undefined }))
    } catch (e) {
      toast.error('Recompute failed: ' + (e.response?.data?.detail || e.message))
    } finally {
      setRecomputing(false)
    }
  }

  const handleMapRelations = async () => {
    setRecomputing(true)
    try {
      await axios.post('/api/corpus/relate-papers', {}, {
        headers: { Authorization: `Bearer ${token}` },
      })
      toast.success('Relation mapping started. Refresh the citation network in a minute.')
      setGraphData(prev => ({ ...prev, 'citation-network': undefined }))
    } catch (e) {
      toast.error('Relation mapping failed: ' + (e.response?.data?.detail || e.message))
    } finally {
      setRecomputing(false)
    }
  }

  const current = graphData[activeTab] || { nodes: [], edges: [] }

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl sm:text-3xl font-bold text-[#C4935F] dark:text-[#D9A86C]">
            Explore Corpus
          </h1>
          <p className="mt-1 text-sm text-[#8F8F8F]">
            Visualise your paper library as interactive graphs
          </p>
        </div>
        {activeTab === 'topic-clusters' && (
          <button
            onClick={handleRecompute}
            disabled={recomputing}
            className="flex items-center gap-2 px-3 py-1.5 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg text-sm disabled:opacity-50"
          >
            <RefreshCw className={`w-4 h-4 ${recomputing ? 'animate-spin' : ''}`} />
            {recomputing ? 'Running...' : 'Recompute Clusters'}
          </button>
        )}
        {activeTab === 'citation-network' && (
          <button
            onClick={handleMapRelations}
            disabled={recomputing}
            className="flex items-center gap-2 px-3 py-1.5 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg text-sm disabled:opacity-50"
            title="Use the RelationAgent to label how your papers relate (extends, replicates, shares method...)"
          >
            <RefreshCw className={`w-4 h-4 ${recomputing ? 'animate-spin' : ''}`} />
            {recomputing ? 'Mapping...' : 'Map Relations (AI)'}
          </button>
        )}
      </div>

      {/* Tab bar */}
      <div className="flex gap-1 border-b border-slate-200 dark:border-slate-700">
        {TABS.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            onClick={() => setActiveTab(id)}
            className={`flex items-center gap-2 px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              activeTab === id
                ? 'border-[#00988F] text-[#00988F]'
                : 'border-transparent text-[#8F8F8F] hover:text-[#1B1B1B] dark:hover:text-[#F5F5F5]'
            }`}
          >
            <Icon className="w-4 h-4" />
            {label}
          </button>
        ))}
      </div>

      {/* Graph area */}
      <div className="card p-0 overflow-hidden rounded-xl">
        {loading ? (
          <div className="flex items-center justify-center h-96">
            <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-[#00988F]" />
          </div>
        ) : current.nodes?.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-96 text-slate-400">
            <Network className="w-12 h-12 mb-3 opacity-40" />
            <p className="text-sm">No data yet. Process some papers first.</p>
            {activeTab === 'topic-clusters' && (
              <p className="text-xs mt-1 opacity-60">Then click "Recompute Clusters".</p>
            )}
          </div>
        ) : (
          <KnowledgeGraph
            nodes={current.nodes}
            edges={current.edges}
            height={520}
          />
        )}
      </div>

      {/* Legend */}
      {activeTab === 'topic-clusters' && current.nodes?.length > 0 && (
        <div className="flex flex-wrap gap-3">
          {(current.cluster_labels || []).slice(0, 8).map((lbl, i) => (
            <span key={i} className="px-2 py-1 rounded-full text-xs font-medium bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300">
              {lbl}
            </span>
          ))}
        </div>
      )}
      {activeTab === 'citation-network' && (
        <div className="flex gap-4 text-xs text-slate-500">
          <span className="flex items-center gap-1"><span className="w-3 h-3 rounded-full bg-red-500 inline-block" /> Foundational</span>
          <span className="flex items-center gap-1"><span className="w-3 h-3 rounded-full bg-green-500 inline-block" /> Frontier</span>
          <span className="flex items-center gap-1"><span className="w-3 h-3 rounded-full bg-yellow-400 inline-block" /> Bridge</span>
        </div>
      )}
    </div>
  )
}
