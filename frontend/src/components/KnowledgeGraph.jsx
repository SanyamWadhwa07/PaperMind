import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { forceCenter, forceCollide, forceLink, forceManyBody, forceSimulation, forceX, forceY } from 'd3-force';
import { select } from 'd3-selection';
import { drag as d3drag } from 'd3-drag';
import { zoom as d3zoom, zoomIdentity } from 'd3-zoom';
import { Crosshair, Minus, Plus } from 'lucide-react';
import { useTheme } from '../contexts/ThemeContext';
import { Badge, Button, Card, CardBody, Eyebrow, cx } from './ui/primitives';

/**
 * A force-directed graph drawn as SVG.
 *
 * Replaces vis-network, which shipped a 500KB canvas engine, drew its own
 * colours, and rendered node labels the app could not style. d3-force does the
 * layout only — every mark below is an SVG element carrying design-system
 * tokens, so the graph inherits the theme (including dark mode) the same way
 * the rest of the page does, and a node can be given real content: a paper
 * shows its title and authors, not a truncated string in a tooltip.
 */
function readToken(name) {
  if (typeof window === 'undefined') return '#000';
  const raw = getComputedStyle(document.documentElement)
    .getPropertyValue(`--${name}`)
    .trim();
  return raw ? `rgb(${raw})` : '#000';
}

const CATEGORY_STAGE = { cv: 1, nlp: 3, ml: 4, general: 5 };
const ENTITY_STAGE = { model: 4, dataset: 3, metric: 2, framework: 1, task: 5 };
// Authors have no sub-kind to encode (unlike a paper's category or an
// entity's type), so every author node gets one deliberate, consistent
// colour rather than falling through to ENTITY_STAGE's "unknown type"
// default — which is what made every author render as the same accidental
// grey regardless of this constant even existing.
const AUTHOR_STAGE = 4;

const STAGE_BG = {
  1: 'bg-stage-1',
  2: 'bg-stage-2',
  3: 'bg-stage-3',
  4: 'bg-stage-4',
  5: 'bg-stage-5',
};

/** Only legend entries the graph actually contains — an empty key teaches nothing. */
function usedKeys(nodes, group, field, fallback) {
  const present = new Set();
  nodes.forEach((n) => {
    if (n.group === group) present.add(n[field] || fallback);
  });
  return [...present].sort();
}

/** Labels are drawn, not laid out by the browser, so they are clipped by hand. */
function truncate(text, max) {
  const s = String(text ?? '');
  return s.length > max ? `${s.slice(0, max - 1)}…` : s;
}

function ControlButton({ label, onClick, children }) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={label}
      aria-label={label}
      className={cx(
        'flex h-8 w-8 items-center justify-center rounded border border-line',
        'bg-surface text-ink-muted transition-colors duration-fast',
        'hover:border-line-strong hover:text-ink',
        'focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/25',
      )}
    >
      {children}
    </button>
  );
}

export default function KnowledgeGraph({ nodes = [], edges = [], height = 480 }) {
  const svgRef = useRef(null);
  const zoomRef = useRef(null);
  const simulationRef = useRef(null);
  const [selected, setSelected] = useState(null);
  const [showEntities, setShowEntities] = useState(true);
  const { theme } = useTheme();

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
      inkMuted: readToken('ink-muted'),
      line: readToken('border-strong'),
      accent: readToken('accent'),
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [theme]
  );

  // Entities can be switched off to read the paper-to-paper structure on its
  // own, which is unreadable once every paper trails ten term nodes.
  const visibleNodes = useMemo(
    () => (showEntities ? nodes : nodes.filter((n) => n.group !== 'entity')),
    [nodes, showEntities]
  );

  const visibleEdges = useMemo(() => {
    const ids = new Set(visibleNodes.map((n) => n.id));
    return edges.filter((e) => ids.has(e.from) && ids.has(e.to));
  }, [edges, visibleNodes]);

  useEffect(() => {
    const svgEl = svgRef.current;
    if (!svgEl || visibleNodes.length === 0) return;

    const { width } = svgEl.getBoundingClientRect();
    const h = svgEl.clientHeight || height;

    const fillFor = (n) =>
      n.group === 'paper'
        ? palette.stages[CATEGORY_STAGE[n.category] || 5]
        : n.group === 'author'
          ? palette.stages[AUTHOR_STAGE]
          : palette.stages[ENTITY_STAGE[n.entity_type] || 5];

    const radiusFor = (n) => {
      if (n.group === 'paper') return n.is_anchor ? 16 : 11;
      return 5 + Math.min(n.paper_count || 1, 5);
    };

    // d3 mutates what it is given, so the simulation runs on copies — otherwise
    // React's props would acquire x/y/vx/vy and re-render on every tick.
    const simNodes = visibleNodes.map((n) => ({ ...n, r: radiusFor(n) }));
    const simLinks = visibleEdges.map((e) => ({ ...e, source: e.from, target: e.to }));

    const svg = select(svgEl);
    svg.selectAll('*').remove();

    const root = svg.append('g');

    const linkSel = root
      .append('g')
      .attr('fill', 'none')
      .selectAll('line')
      .data(simLinks)
      .join('line')
      .attr('stroke', palette.line)
      // A mention is context, a similarity is the structure — so mentions
      // recede into dashed hairlines and similarity carries the weight.
      .attr('stroke-opacity', (d) => (d.group === 'mentions' ? 0.3 : 0.65))
      .attr('stroke-width', (d) =>
        d.group === 'mentions' ? 1 : Math.max(1, Math.min((d.value || 1) * 3, 5))
      )
      .attr('stroke-dasharray', (d) => (d.group === 'mentions' ? '3,3' : null));

    const nodeSel = root
      .append('g')
      .selectAll('g')
      .data(simNodes)
      .join('g')
      .attr('cursor', 'pointer')
      .on('click', (_event, d) => setSelected(d));

    nodeSel
      .append(function (d) {
        // Papers are round, terms are square — the same shape language the
        // legend uses, readable without colour.
        return document.createElementNS(
          'http://www.w3.org/2000/svg',
          d.group === 'paper' ? 'circle' : 'rect'
        );
      })
      .attr('r', (d) => d.r)
      .attr('width', (d) => d.r * 2)
      .attr('height', (d) => d.r * 2)
      .attr('x', (d) => -d.r)
      .attr('y', (d) => -d.r)
      .attr('rx', 2)
      .attr('fill', fillFor)
      .attr('stroke', (d) => (d.is_anchor ? palette.accent : palette.line))
      .attr('stroke-width', (d) => (d.is_anchor ? 3 : 1.25));

    const label = nodeSel
      .append('text')
      .attr('text-anchor', 'middle')
      .attr('font-family', 'Inter Variable, Inter, system-ui, sans-serif')
      .attr('paint-order', 'stroke')
      // A halo in the canvas colour keeps labels readable where they cross an
      // edge, in either theme.
      .attr('stroke', readToken('canvas'))
      .attr('stroke-width', 3);

    label
      .append('tspan')
      .attr('x', 0)
      .attr('dy', (d) => d.r + 13)
      .attr('fill', palette.ink)
      .attr('font-size', (d) => (d.is_anchor ? 13 : 11))
      .attr('font-weight', (d) => (d.is_anchor ? 600 : 500))
      .text((d) => truncate(d.label, d.group === 'paper' ? 34 : 22));

    // The answer to "which paper is this, and whose?" — previously the graph
    // showed a truncated title and nothing else.
    label
      .filter((d) => d.group === 'paper' && d.authors)
      .append('tspan')
      .attr('x', 0)
      .attr('dy', 12)
      .attr('fill', palette.inkMuted)
      .attr('font-size', 10)
      .text((d) => truncate(d.authors, 30));

    const simulation = forceSimulation(simNodes)
      .force('link', forceLink(simLinks).id((d) => d.id).distance((d) => (d.group === 'mentions' ? 90 : 190)).strength(0.35))
      .force('charge', forceManyBody().strength(-900).distanceMax(700))
      // Labels sit under their node and are far wider than it, so collision has
      // to reserve room for the text — sizing this to the circle alone is what
      // let "VGG19" land on top of a paper title.
      .force('collide', forceCollide().radius((d) => d.r + (d.group === 'paper' ? 62 : 34)).strength(0.9))
      .force('center', forceCenter(width / 2, h / 2))
      // Gentle pull to the middle so disconnected components — a paper with no
      // similar neighbours — do not drift off-canvas forever.
      .force('x', forceX(width / 2).strength(0.03))
      .force('y', forceY(h / 2).strength(0.03));

    simulationRef.current = simulation;

    // Declared here rather than after the handlers below, both of which use it.
    // Referencing it from inside a deferred callback happens to work, but it
    // reads as a temporal-dead-zone bug and the linter treats it as one.
    const zoomBehaviour = d3zoom()
      .scaleExtent([0.2, 4])
      .on('zoom', (event) => root.attr('transform', event.transform));
    svg.call(zoomBehaviour);
    zoomRef.current = zoomBehaviour;

    // Once settled, frame the whole graph. Without this the layout keeps
    // whatever scale it happened to reach and sat as a small clump in the
    // middle of a large empty canvas.
    simulation.on('end', () => {
      const xs = simNodes.map((n) => n.x);
      const ys = simNodes.map((n) => n.y);
      const pad = 90;
      const minX = Math.min(...xs) - pad;
      const maxX = Math.max(...xs) + pad;
      const minY = Math.min(...ys) - pad;
      const maxY = Math.max(...ys) + pad;
      const boxW = Math.max(maxX - minX, 1);
      const boxH = Math.max(maxY - minY, 1);
      const scale = Math.min(width / boxW, h / boxH, 1.6);
      svg
        .transition()
        .duration(400)
        .call(
          zoomBehaviour.transform,
          zoomIdentity
            .translate(width / 2, h / 2)
            .scale(scale)
            .translate(-(minX + maxX) / 2, -(minY + maxY) / 2)
        );
    });

    simulation.on('tick', () => {
      linkSel
        .attr('x1', (d) => d.source.x)
        .attr('y1', (d) => d.source.y)
        .attr('x2', (d) => d.target.x)
        .attr('y2', (d) => d.target.y);
      nodeSel.attr('transform', (d) => `translate(${d.x},${d.y})`);
    });

    nodeSel.call(
      d3drag()
        .on('start', (event, d) => {
          if (!event.active) simulation.alphaTarget(0.2).restart();
          d.fx = d.x;
          d.fy = d.y;
        })
        .on('drag', (event, d) => {
          d.fx = event.x;
          d.fy = event.y;
        })
        .on('end', (event, d) => {
          if (!event.active) simulation.alphaTarget(0);
          // Released nodes stay put: a graph the reader has arranged should
          // keep that arrangement.
          d.fx = event.x;
          d.fy = event.y;
        })
    );

    return () => {
      simulation.stop();
      simulationRef.current = null;
    };
  }, [visibleNodes, visibleEdges, palette, height]);

  const zoomBy = useCallback((factor) => {
    if (!zoomRef.current || !svgRef.current) return;
    select(svgRef.current).transition().duration(200).call(zoomRef.current.scaleBy, factor);
  }, []);

  const reset = useCallback(() => {
    if (!zoomRef.current || !svgRef.current) return;
    select(svgRef.current).transition().duration(250).call(zoomRef.current.transform, zoomIdentity);
    // Unpin everything the reader dragged and let the layout settle again.
    const sim = simulationRef.current;
    if (sim) {
      sim.nodes().forEach((n) => {
        n.fx = null;
        n.fy = null;
      });
      sim.alpha(0.6).restart();
    }
  }, []);

  if (nodes.length === 0) {
    return (
      <div className="flex h-48 items-center justify-center rounded-lg border border-dashed border-line px-6 text-center text-sm text-ink-faint">
        No connections yet. Process more papers and the graph fills in.
      </div>
    );
  }

  const paperKeys = usedKeys(visibleNodes, 'paper', 'category', 'general');
  const entityKeys = usedKeys(visibleNodes, 'entity', 'entity_type', 'other');
  const hasAuthors = visibleNodes.some((n) => n.group === 'author');
  // The toggle only ever hides/shows 'entity' nodes — on a pure author graph
  // (no 'entity' nodes at all, in either state) it did nothing but sat there
  // looking like a real control. Base this on the unfiltered node list, not
  // visibleNodes, so hiding entities doesn't hide the toggle that hides them.
  const canToggleEntities = nodes.some((n) => n.group === 'entity');

  return (
    <div className="space-y-3">
      <div className="relative">
        <svg
          ref={svgRef}
          role="img"
          aria-label="Knowledge graph of papers and the terms they share"
          className="w-full touch-none overflow-hidden rounded-lg border border-line bg-surface-sunk"
          style={{ height: `min(${height}px, 70vh)` }}
        />

        <div className="absolute right-2 top-2 flex flex-col gap-1.5">
          <ControlButton label="Zoom in" onClick={() => zoomBy(1.3)}>
            <Plus className="h-4 w-4" aria-hidden="true" />
          </ControlButton>
          <ControlButton label="Zoom out" onClick={() => zoomBy(1 / 1.3)}>
            <Minus className="h-4 w-4" aria-hidden="true" />
          </ControlButton>
          <ControlButton label="Reset layout" onClick={reset}>
            <Crosshair className="h-4 w-4" aria-hidden="true" />
          </ControlButton>
        </div>

        <p className="pointer-events-none absolute bottom-2 left-3 text-caption text-ink-faint">
          Drag nodes · scroll to zoom
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        {paperKeys.length > 0 && (
          <>
            <Eyebrow>Papers</Eyebrow>
            {paperKeys.map((k) => (
              <span key={k} className="flex items-center gap-1.5 text-caption text-ink-muted">
                <span
                  className={`inline-block h-2.5 w-2.5 rounded-full ${STAGE_BG[CATEGORY_STAGE[k] || 5]}`}
                  aria-hidden="true"
                />
                {k.toUpperCase()}
              </span>
            ))}
          </>
        )}

        {entityKeys.length > 0 && (
          <>
            <Eyebrow className="ml-2">Mentions</Eyebrow>
            {entityKeys.map((k) => (
              <span key={k} className="flex items-center gap-1.5 text-caption text-ink-muted">
                <span
                  className={`inline-block h-2.5 w-2.5 rounded-sm ${STAGE_BG[ENTITY_STAGE[k] || 5]}`}
                  aria-hidden="true"
                />
                {k}
              </span>
            ))}
          </>
        )}

        {hasAuthors && (
          <p className="text-caption text-ink-muted">
            Nodes are authors; a line means they co-authored a paper. With a
            small library, most clusters are just one paper&apos;s author list.
          </p>
        )}

        {canToggleEntities && (
          <button
            type="button"
            onClick={() => setShowEntities((v) => !v)}
            className="ml-auto text-caption text-ink-muted underline-offset-2 hover:text-ink hover:underline"
          >
            {showEntities ? 'Papers only' : 'Show mentions'}
          </button>
        )}
      </div>

      {selected && (
        <Card className="animate-fade">
          <CardBody className="py-4">
            <p className="font-serif text-sm text-ink">
              {selected.title || selected.label}
            </p>
            {selected.authors && (
              <p className="mt-1 text-caption text-ink-muted">{selected.authors}</p>
            )}
            <div className="mt-2 flex flex-wrap items-center gap-2">
              {selected.group === 'paper' ? (
                <>
                  <Badge tone="outline">{selected.category || 'general'}</Badge>
                  {selected.arxiv_id && (
                    <span className="font-mono tabular text-code text-ink-faint">
                      arXiv:{selected.arxiv_id}
                    </span>
                  )}
                  {selected.published_date && (
                    <span className="font-mono tabular text-code text-ink-faint">
                      {selected.published_date}
                    </span>
                  )}
                  {selected.summary_id && !selected.is_anchor && (
                    <Button
                      variant="secondary"
                      size="sm"
                      to={`/summary/${selected.summary_id}`}
                      className="ml-auto"
                    >
                      Open paper
                    </Button>
                  )}
                </>
              ) : selected.group === 'author' ? (
                <span className="font-mono tabular text-code text-ink-faint">
                  {selected.paper_count} paper{selected.paper_count === 1 ? '' : 's'} in your library
                </span>
              ) : (
                <>
                  <Badge tone="outline">{selected.entity_type}</Badge>
                  {selected.paper_count > 1 && (
                    <span className="font-mono tabular text-code text-ink-faint">
                      in {selected.paper_count} papers
                    </span>
                  )}
                </>
              )}
            </div>

            {/* An author node used to open onto an empty entity-type badge —
                the actual point of clicking one is jumping to their papers. */}
            {selected.group === 'author' && selected.papers?.length > 0 && (
              <ul className="mt-2 space-y-1 border-t border-line pt-2">
                {selected.papers.map((p) => (
                  <li key={p.id}>
                    <a
                      href={`/summary/${p.id}`}
                      target="_blank"
                      rel="noreferrer"
                      className="block truncate text-sm text-accent hover:underline"
                      title={p.title}
                    >
                      {p.title}
                    </a>
                  </li>
                ))}
                {selected.paper_count > selected.papers.length && (
                  <li className="text-caption text-ink-faint">
                    +{selected.paper_count - selected.papers.length} more
                  </li>
                )}
              </ul>
            )}
          </CardBody>
        </Card>
      )}
    </div>
  );
}
