import { useState } from 'react'
import { Network, GitBranch, Users, AlertTriangle, RefreshCw } from 'lucide-react'
import { useToast } from '../contexts/ToastContext'
import KnowledgeGraph from '../components/KnowledgeGraph'
import { corpus } from '../lib/api'
import { invalidate } from '../lib/query'
import { useQuery } from '../lib/useQuery'
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

const LOADER = {
  'topic-clusters': corpus.topicClusters,
  'citation-network': corpus.citationNetwork,
  'author-graph': corpus.authorGraph,
  'contradiction-map': corpus.contradictions,
}

const EMPTY_GRAPH = { nodes: [], edges: [] }

export default function ExplorePage() {
  const toast = useToast()
  const [activeTab, setActiveTab] = useState('topic-clusters')
  const [recomputing, setRecomputing] = useState(false)

  // Each tab is its own cache key, and the cache is module-level — so switching
  // tabs, leaving for Timeline, and coming back all read the graph that is
  // already in memory. This used to be component state, which meant every
  // navigation away threw four corpus-wide graph queries on the floor and
  // re-ran them on return.
  const { data, error, loading, refreshing, refetch } = useQuery(
    ['corpus', activeTab],
    () => LOADER[activeTab](),
  )

  const handleRecompute = async () => {
    setRecomputing(true)
    try {
      const { num_topics: topics, num_papers: papers } =
        (await corpus.recomputeClusters()) || {}
      toast.success(
        topics
          ? `Grouped ${papers} papers into ${topics} topic${topics === 1 ? '' : 's'}.`
          : 'Clusters recomputed.'
      )
      // The clusters just changed server-side, so the cached graph is wrong
      // rather than merely old. `refetch` forces past the TTL.
      await refetch()
    } catch (e) {
      toast.error('Recompute failed: ' + (e.message || 'Unknown error'))
    } finally {
      setRecomputing(false)
    }
  }

  const handleMapRelations = async () => {
    setRecomputing(true)
    try {
      await corpus.relatePapers()
      toast.success('Relation mapping started. Refresh the citation network in a minute.')
      // Runs in the background server-side, so there is nothing to refetch yet
      // — just make sure the next visit does not serve the pre-mapping graph.
      invalidate(['corpus', 'citation-network'])
    } catch (e) {
      toast.error('Relation mapping failed: ' + (e.message || 'Unknown error'))
    } finally {
      setRecomputing(false)
    }
  }

  const current = data || EMPTY_GRAPH

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

      <div className="flex items-center gap-3">
        <Tabs
          tabs={TABS.map(({ id, label }) => ({ id, label }))}
          value={activeTab}
          onChange={setActiveTab}
          className="min-w-0 flex-1"
        />
        {/* A background refresh of a graph already on screen. Deliberately not
            the full skeleton — the reader is looking at valid data. */}
        {refreshing && !loading && (
          <Spinner size="sm" className="shrink-0 text-ink-faint" />
        )}
      </div>

      {loading ? (
        <Card className="flex h-96 items-center justify-center">
          <Spinner className="text-accent" />
        </Card>
      ) : error ? (
        <EmptyState
          icon={AlertTriangle}
          title="Could not load this graph"
          description={error.message || 'The request failed.'}
          action={
            <Button variant="secondary" onClick={refetch}>
              Try again
            </Button>
          }
        />
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
