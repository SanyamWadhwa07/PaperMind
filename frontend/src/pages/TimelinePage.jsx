import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTheme } from '../contexts/ThemeContext';
import { graph } from '../lib/api';
import { fetchQuery } from '../lib/query';
import { useQuery } from '../lib/useQuery';
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

/** The whole palette vis needs, read at the moment the widget is (re)built. */
function readPalette() {
  return {
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
    accentInk: readToken('accent-ink'),
  };
}

// The stage pastels keep the same RGB in both themes precisely so they can carry
// dark ink either way — see the note beside `--stage-1` in index.css. Reading
// `--ink` for text *on* a pastel therefore inverts to near-white in dark mode
// and disappears; this is the ink those fills are designed around.
const PASTEL_INK = '#26251e';

/**
 * Papers are stored with their arXiv primary category (`cs.CV`, `eess.IV`, …),
 * while the extraction pipeline labels its own domains (`cv`, `nlp`, `ml`).
 * Both land in `primary_category`, so both have to resolve here — keying the
 * palette on the pipeline names alone meant every real arXiv paper fell through
 * to the default and the whole timeline rendered in one colour.
 */
const DOMAINS = [
  { id: 'cv', label: 'Vision', stage: 1, prefixes: ['cv', 'cs.cv', 'eess.iv'] },
  { id: 'nlp', label: 'Language', stage: 3, prefixes: ['nlp', 'cs.cl'] },
  {
    id: 'ml',
    label: 'Learning',
    stage: 4,
    prefixes: ['ml', 'cs.lg', 'cs.ai', 'cs.ne', 'stat.ml'],
  },
];
const OTHER_DOMAIN = { id: 'general', label: 'Other', stage: 5, prefixes: [] };

function domainOf(rawCategory) {
  const value = (rawCategory || '').trim().toLowerCase();
  if (!value) return OTHER_DOMAIN;
  return (
    DOMAINS.find((d) => d.prefixes.some((p) => value === p || value.startsWith(`${p}.`))) ||
    OTHER_DOMAIN
  );
}

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
  const { theme } = useTheme();
  const navigate = useNavigate();
  const timelineRef = useRef(null);
  const treeRef = useRef(null);
  const treeNetRef = useRef(null);
  const [selectedPaper, setSelectedPaper] = useState(null);
  const [ancestryData, setAncestryData] = useState(null);
  const [ancestryLoading, setAncestryLoading] = useState(false);

  // Through the shared cache, so returning from a paper does not rebuild the
  // whole timeline from a fresh corpus query.
  const { data: timelineData, loading } = useQuery(['graph', 'timeline'], graph.timeline);

  // Only papers carrying a publication date can be placed. Uploaded PDFs never
  // get one — `published_date` is written on the arXiv import path alone — so
  // they drop off this page silently; the count is surfaced below rather than
  // leaving the library looking smaller than it is.
  //
  // Keyed on `timelineData` rather than on a `?? []` fallback, which would be a
  // fresh array identity every render and rebuild the whole widget each time.
  const datedPapers = useMemo(
    () => (timelineData?.papers || []).filter((p) => p.published_date),
    [timelineData]
  );
  const undatedCount = (timelineData?.papers?.length || 0) - datedPapers.length;

  // Legend entries for the domains actually on screen, in palette order.
  const domainsPresent = useMemo(() => {
    const present = new Map();
    for (const p of datedPapers) {
      const d = domainOf(p.primary_category);
      present.set(d.id, d);
    }
    return [...DOMAINS, OTHER_DOMAIN].filter((d) => present.has(d.id));
  }, [datedPapers]);

  const loadAncestry = async (paper) => {
    setSelectedPaper(paper);
    setAncestryLoading(true);
    try {
      // Cached per paper: clicking back and forth along the timeline is the
      // normal way to read it, and each hop re-requested the same ancestry.
      setAncestryData(
        await fetchQuery(['ancestry', paper.id], () => graph.ancestry(paper.id)),
      );
    } catch {
      setAncestryData(null);
    } finally {
      setAncestryLoading(false);
    }
  };

  // Build vis-timeline
  useEffect(() => {
    if (!timelineRef.current || !datedPapers.length) return;

    // Read tokens here rather than in a memo keyed on `theme`: the `.dark`
    // class is toggled by ThemeContext's own effect, which has not run yet
    // while a memo is being recomputed during render. Reading inside an effect
    // always sees the class the palette is supposed to describe.
    const palette = readPalette();
    const papers = datedPapers;

    // vis-timeline renders `content` as raw HTML rather than through React, so
    // a title is built as a DOM node instead of a template string — paper
    // titles come from arXiv metadata and uploaded PDFs, neither trustworthy
    // enough to interpolate directly into markup.
    const buildLabel = (title) => {
      const span = document.createElement('span');
      span.title = title || 'Untitled';
      const text = title || 'Untitled';
      span.textContent = text.length > 30 ? `${text.slice(0, 30)}…` : text;
      return span;
    };

    const items = new DataSet(
      papers.map((p) => {
        const domain = domainOf(p.primary_category);
        return {
          id: p.id,
          content: buildLabel(p.paper_title),
          start: p.published_date,
          title: `${p.paper_title || 'Untitled'} — ${p.published_date}`,
          className: `cat-${domain.id}`,
          style: `background:${palette.stages[domain.stage]};border-color:${
            palette.line
          };color:${PASTEL_INK};border-radius:4px;padding:2px 6px;font-size:11px;`,
        };
      })
    );

    const tl = new Timeline(timelineRef.current, items, {
      orientation: 'top',
      showCurrentTime: false,
      zoomable: true,
      moveable: true,
      stack: true,
      // No fixed height. A hardcoded 220px is only right for the one library
      // that happens to stack to that many rows; every other library either
      // scrolls inside the box or — far more often, since items only stack
      // when their labels overlap — leaves most of the panel blank. Letting
      // vis size itself to its rows keeps the panel exactly as tall as the
      // content, with `minHeight` covering the single-row case.
      minHeight: 130,
      margin: { item: { horizontal: 10, vertical: 8 }, axis: 8 },
      // Two decades is a sensible outer limit and a quarter a sensible inner
      // one; without these a stray scroll zooms out to the epoch or in to a
      // single afternoon, and the papers vanish either way.
      zoomMin: 1000 * 60 * 60 * 24 * 90,
      zoomMax: 1000 * 60 * 60 * 24 * 365 * 25,
    });

    tl.on('select', ({ items: sel }) => {
      if (!sel.length) return;
      const paper = papers.find((p) => p.id === sel[0]);
      if (paper) loadAncestry(paper);
    });

    return () => tl.destroy();
  }, [datedPapers, theme]);

  // Build ancestry vis-network when data changes
  useEffect(() => {
    if (!treeRef.current || !ancestryData?.nodes?.length) return;

    if (treeNetRef.current) {
      treeNetRef.current.destroy();
      treeNetRef.current = null;
    }

    const palette = readPalette();

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
            : palette.stages[domainOf(n.category).stage],
          border: palette.line,
          highlight: { background: palette.accent, border: palette.accent },
        },
        font: {
          // Both fills are light-on-dark-ink by design, so the label follows the
          // fill rather than the page: `--ink` inverts with the theme and would
          // put white text on a pastel node.
          color: n.is_anchor ? palette.accentInk : PASTEL_INK,
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
  }, [ancestryData, navigate, theme]);

  return (
    <div className="animate-rise mx-auto max-w-6xl space-y-8 3xl:max-w-7xl">
      <header className="border-b border-line pb-6">
        <Eyebrow className="block">Ordered by publication</Eyebrow>
        <h1 className="display mt-2 text-display-sm text-ink">Timeline</h1>
        <p className="mt-2 max-w-prose text-sm text-ink-muted">
          Your library along its own history. Select a paper to trace what it
          builds on and what came after.
        </p>
      </header>

      {loading ? (
        <Skeleton className="h-56 w-full" />
      ) : !datedPapers.length ? (
        <EmptyState
          icon={Calendar}
          title="No dated papers yet"
          description="Process papers from arXiv and their publication dates will place them on this timeline."
        />
      ) : (
        <>
          {/* The legend that belongs to *this* widget is the one for the item
              colours. Relation colours moved down to the lineage card, which is
              the only place an edge is ever drawn — sitting up here they
              described a graph the reader could not yet see. */}
          {domainsPresent.length > 1 && (
            <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
              <Eyebrow>Field</Eyebrow>
              {domainsPresent.map((d) => (
                <span
                  key={d.id}
                  className="flex items-center gap-1.5 text-caption text-ink-muted"
                >
                  <span
                    className={cx(
                      'inline-block h-2.5 w-2.5 rounded-sm',
                      STAGE_BG[d.stage]
                    )}
                    aria-hidden="true"
                  />
                  {d.label}
                </span>
              ))}
            </div>
          )}

          <div
            ref={timelineRef}
            className="overflow-hidden rounded-lg border border-line bg-surface"
          />

          <p className="text-caption text-ink-faint">
            Scroll to zoom, drag to pan · select a paper to trace its lineage
            {undatedCount > 0 && (
              <>
                {' · '}
                {undatedCount} paper{undatedCount === 1 ? '' : 's'} hidden for
                want of a publication date (uploads carry none)
              </>
            )}
          </p>

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
                    <div className="mb-4 flex flex-wrap items-center gap-x-4 gap-y-2">
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
