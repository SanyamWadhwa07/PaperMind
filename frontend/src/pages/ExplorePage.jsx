import { useState, useEffect } from 'react'
import { Network, GitBranch, Users, AlertTriangle, RefreshCw } from 'lucide-react'
import { useAuth } from '../contexts/AuthContext'
import { useToast } from '../contexts/ToastContext'
import KnowledgeGraph from '../components/KnowledgeGraph'
import api from '../lib/api'
import {
  Badge,
  Button,
  Card,
  EmptyState,
  Eyebrow,
  Spinner,
  Tabs,
  cx,
} from '../components/ui/primitives'

const TABS = [
  { id: 'topic-clusters', label: 'Topics', icon: Network },
  { id: 'citation-network', label: 'Citations', icon: GitBranch },
  { id: 'author-graph', label: 'Authors', icon: Users },
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

  const loadTab = async (tab, { force = false } = {}) => {
    if (graphData[tab] && !force) return
    setLoading(true)
    try {
      const res = await api.get(ENDPOINT[tab], {
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
      const res = await api.post('/api/corpus/recompute-clusters', {}, {
        headers: { Authorization: `Bearer ${token}` },
      })
      const { num_topics: topics, num_papers: papers } = res.data || {}
      toast.success(
        topics
          ? `Grouped ${papers} papers into ${topics} topic${topics === 1 ? '' : 's'}.`
          : 'Clusters recomputed.'
      )
      // Clearing the cache is not enough on its own — the tab is already
      // active, so nothing triggers a refetch. Load the new graph directly.
      setGraphData(prev => ({ ...prev, 'topic-clusters': undefined }))
      await loadTab('topic-clusters', { force: true })
    } catch (e) {
      toast.error('Recompute failed: ' + (e.response?.data?.detail || e.message))
    } finally {
      setRecomputing(false)
    }
  }

  const handleMapRelations = async () => {
    setRecomputing(true)
    try {
      await api.post('/api/corpus/relate-papers', {}, {
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

  const action =
    activeTab === 'topic-clusters'
      ? { onClick: handleRecompute, label: 'Recompute clusters', busy: 'Running…' }
      : activeTab === 'citation-network'
        ? { onClick: handleMapRelations, label: 'Map relations', busy: 'Mapping…' }
        : null

  return (
    <div className="animate-rise mx-auto max-w-6xl space-y-8 3xl:max-w-7xl">
      <header className="flex flex-col gap-4 border-b border-line pb-6 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <Eyebrow className="block">The whole library at once</Eyebrow>
          <h1 className="display mt-2 text-display-sm text-ink">Explore</h1>
          <p className="mt-2 max-w-prose text-sm text-ink-muted">
            Your corpus drawn as a graph: what clusters together, and where the
            papers disagree with each other.
          </p>
        </div>

        {action && (
          <Button
            variant="secondary"
            onClick={action.onClick}
            disabled={recomputing}
            className="shrink-0"
          >
            <RefreshCw
              className={cx('h-4 w-4', recomputing && 'animate-spin')}
              aria-hidden="true"
            />
            {recomputing ? action.busy : action.label}
          </Button>
        )}
      </header>

      <Tabs
        tabs={TABS.map(({ id, label }) => ({ id, label }))}
        value={activeTab}
        onChange={setActiveTab}
      />

      {loading ? (
        <Card className="flex h-96 items-center justify-center">
          <Spinner className="text-accent" />
        </Card>
      ) : current.nodes?.length === 0 ? (
        <EmptyState
          icon={Network}
          title="Nothing to draw yet"
          description={
            activeTab === 'topic-clusters'
              ? 'Process a few papers, then recompute clusters to see how they group.'
              : 'Process a few papers and this graph fills in.'
          }
        />
      ) : (
        <KnowledgeGraph nodes={current.nodes} edges={current.edges} height={520} />
      )}

      {activeTab === 'topic-clusters' && current.nodes?.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <Eyebrow>Clusters</Eyebrow>
          {(current.cluster_labels || []).slice(0, 8).map((lbl, i) => (
            <Badge key={i} tone="outline">
              {lbl}
            </Badge>
          ))}
        </div>
      )}

      {activeTab === 'citation-network' && current.nodes?.length > 0 && (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <Eyebrow>Role in the corpus</Eyebrow>
          {[
            ['Foundational', 'bg-stage-5'],
            ['Frontier', 'bg-stage-2'],
            ['Bridge', 'bg-stage-3'],
          ].map(([label, fill]) => (
            <span
              key={label}
              className="flex items-center gap-1.5 text-caption text-ink-muted"
            >
              <span
                className={cx('inline-block h-2.5 w-2.5 rounded-full', fill)}
                aria-hidden="true"
              />
              {label}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}
