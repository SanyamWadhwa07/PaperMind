import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { useTheme } from '../contexts/ThemeContext';
import api from '../lib/api';
import { Network } from 'vis-network';
import { DataSet } from 'vis-data';
import { Timeline } from 'vis-timeline';
// vis-timeline builds its axis, rows and items out of DOM nodes that are
// positioned entirely by this stylesheet. Without it the widget mounts, the
// items exist, and the container renders as an empty box — which is exactly how
// the timeline looked. (vis-network survived the same omission only because it
// draws to a canvas.)
import 'vis-timeline/styles/vis-timeline-graph2d.css';
import { GitBranch, Calendar } from 'lucide-react';
import {
  Card,
  CardBody,
  EmptyState,
  Eyebrow,
  Skeleton,
  Spinner,
  cx,
} from '../components/ui/primitives';

/** vis takes concrete colours, so tokens are resolved from the document. */
function readToken(name) {
  if (typeof window === 'undefined') return '#000';
  const raw = getComputedStyle(document.documentElement)
    .getPropertyValue(`--${name}`)
    .trim();
  return raw ? `rgb(${raw})` : '#000';
}

const CATEGORY_STAGE = { cv: 1, nlp: 3, ml: 4, general: 5 };

// Link types read as a set of relations, so they take the stage palette too.
const LINK_STAGE = {
  cites: 5,
  extends: 3,
  replicates: 2,
  contradicts: 1,
  inspired_by: 4,
};

const STAGE_BG = {
  1: 'bg-stage-1',
  2: 'bg-stage-2',
  3: 'bg-stage-3',
  4: 'bg-stage-4',
  5: 'bg-stage-5',
};

export default function TimelinePage() {
  const { token } = useAuth();
  const { theme } = useTheme();
  const navigate = useNavigate();
  const timelineRef = useRef(null);
  const treeRef = useRef(null);
  const treeNetRef = useRef(null);
  const [loading, setLoading] = useState(true);
  const [timelineData, setTimelineData] = useState(null);
  const [selectedPaper, setSelectedPaper] = useState(null);
  const [ancestryData, setAncestryData] = useState(null);
  const [ancestryLoading, setAncestryLoading] = useState(false);

  const palette = useMemo(
    () => ({
      stages: {
        1: readToken('stage-1'),
        2: readToken('stage-2'),
        3: readToken('stage-3'),
        4: readToken('stage-4'),
        5: readToken('stage-5'),
      },
      ink: readToken('ink'),
      line: readToken('border-strong'),
      accent: readToken('accent'),
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [theme]
  );

  useEffect(() => {
    const fetchTimeline = async () => {
      try {
        const res = await api.get('/api/graph/timeline', {
          headers: { Authorization: `Bearer ${token}` },
        });
        setTimelineData(res.data);
      } catch {
        // ignore
      } finally {
        setLoading(false);
      }
    };
    fetchTimeline();
  }, [token]);

  // Build vis-timeline
  useEffect(() => {
    if (!timelineRef.current || !timelineData?.papers?.length) return;

    const papers = timelineData.papers.filter((p) => p.published_date);
    if (!papers.length) return;

    // vis-timeline renders `content` as raw HTML rather than through React, so
    // a title is built as a DOM node instead of a template string — paper
    // titles come from arXiv metadata and uploaded PDFs, neither trustworthy
    // enough to interpolate directly into markup.
    const buildLabel = (title) => {
      const span = document.createElement('span');
      span.title = title || 'Untitled';
      span.textContent = `${(title || 'Untitled').slice(0, 30)}…`;
      return span;
    };

    const items = new DataSet(
      papers.map((p) => ({
        id: p.id,
        content: buildLabel(p.paper_title),
        start: p.published_date,
        className: `cat-${p.primary_category || 'general'}`,
        style: `background:${
          palette.stages[CATEGORY_STAGE[p.primary_category] || 5]
        };border-color:${palette.line};color:${
          palette.ink
        };border-radius:4px;padding:2px 6px;font-size:11px;`,
      }))
    );

    const tl = new Timeline(timelineRef.current, items, {
      orientation: 'top',
      showCurrentTime: false,
      zoomable: true,
      moveable: true,
      stack: true,
      height: 220,
    });

    tl.on('select', ({ items: sel }) => {
      if (!sel.length) return;
      const paper = papers.find((p) => p.id === sel[0]);
      if (paper) loadAncestry(paper);
    });

    return () => tl.destroy();
  }, [timelineData, palette]);

  const loadAncestry = async (paper) => {
    setSelectedPaper(paper);
    setAncestryLoading(true);
    try {
      const res = await api.get(`/api/graph/ancestry/${paper.id}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      setAncestryData(res.data);
    } catch {
      setAncestryData(null);
    } finally {
      setAncestryLoading(false);
    }
  };

  // Build ancestry vis-network when data changes
  useEffect(() => {
    if (!treeRef.current || !ancestryData?.nodes?.length) return;

    if (treeNetRef.current) {
      treeNetRef.current.destroy();
      treeNetRef.current = null;
    }

    const visNodes = new DataSet(
      ancestryData.nodes.map((n) => ({
        id: n.id,
        label: n.label,
        title: n.title || '',
        level: n.depth,
        color: {
          // The anchor is the one thing on this screen that earns the accent.
          background: n.is_anchor
            ? palette.accent
            : palette.stages[CATEGORY_STAGE[n.category] || 5],
          border: palette.line,
          highlight: { background: palette.accent, border: palette.accent },
        },
        font: {
          color: palette.ink,
          size: 11,
          face: 'Inter Variable, Inter, system-ui, sans-serif',
        },
        shape: n.is_anchor ? 'star' : 'dot',
        size: n.is_anchor ? 24 : 14,
      }))
    );

    const visEdges = new DataSet(
      ancestryData.edges.map((e, i) => ({
        id: `te_${i}`,
        from: e.from,
        to: e.to,
        title: e.link_type,
        color: { color: palette.stages[LINK_STAGE[e.link_type] || 5] },
        arrows: { to: { enabled: true, scaleFactor: 0.7 } },
        dashes: e.link_type === 'inspired_by',
      }))
    );

    const net = new Network(
      treeRef.current,
      { nodes: visNodes, edges: visEdges },
      {
        layout: { hierarchical: { direction: 'UD', sortMethod: 'directed', levelSeparation: 80 } },
        physics: false,
        interaction: { hover: true },
        nodes: { borderWidth: 1.5 },
      }
    );

    net.on('doubleClick', ({ nodes: sel }) => {
      if (sel.length) navigate(`/summary/${sel[0]}`);
    });

    treeNetRef.current = net;
    return () => { net.destroy(); treeNetRef.current = null; };
  }, [ancestryData, navigate, palette]);

  const hasDated = timelineData?.papers?.filter((p) => p.published_date).length

  return (
    <div className="animate-rise mx-auto max-w-6xl space-y-8">
      <header className="border-b border-line pb-6">
        <Eyebrow className="block">Ordered by publication</Eyebrow>
        <h1 className="display mt-2 text-display-sm text-ink">Timeline</h1>
        <p className="mt-2 max-w-prose text-sm text-ink-muted">
          Your library along its own history. Select a paper to trace what it
          builds on and what came after.
        </p>
      </header>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <Eyebrow>Relations</Eyebrow>
        {Object.entries(LINK_STAGE).map(([type, stage]) => (
          <span
            key={type}
            className="flex items-center gap-1.5 text-caption text-ink-muted"
          >
            <span
              className={cx('inline-block h-0.5 w-4', STAGE_BG[stage])}
              aria-hidden="true"
            />
            {type.replace(/_/g, ' ')}
          </span>
        ))}
      </div>

      {loading ? (
        <Skeleton className="h-56 w-full" />
      ) : !hasDated ? (
        <EmptyState
          icon={Calendar}
          title="No dated papers yet"
          description="Process papers from arXiv and their publication dates will place them on this timeline."
        />
      ) : (
        <>
          <div
            ref={timelineRef}
            className="overflow-hidden rounded-lg border border-line bg-surface"
          />

          {selectedPaper && (
            <Card className="animate-fade">
              <div className="border-b border-line px-6 py-4">
                <h2 className="flex items-center gap-2 text-sm font-semibold text-ink">
                  <GitBranch className="h-4 w-4 text-ink-faint" aria-hidden="true" />
                  Lineage
                </h2>
                <p className="mt-1 truncate font-serif text-sm text-ink-muted">
                  {selectedPaper.paper_title}
                </p>
              </div>

              <CardBody>
                {ancestryLoading ? (
                  <div className="flex h-40 items-center justify-center">
                    <Spinner className="text-accent" />
                  </div>
                ) : !ancestryData?.nodes?.length ? (
                  <p className="text-sm text-ink-faint">
                    No lineage found yet. More papers are needed before
                    relationships can be inferred.
                  </p>
                ) : (
                  <>
                    <div
                      ref={treeRef}
                      className="overflow-hidden rounded border border-line bg-surface-sunk"
                      style={{ height: 320 }}
                    />
                    <p className="mt-3 text-caption text-ink-faint">
                      ★ marks the selected paper · double-click any node to open its summary
                    </p>
                  </>
                )}
              </CardBody>
            </Card>
          )}
        </>
      )}
    </div>
  );
}
