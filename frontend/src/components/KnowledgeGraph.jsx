import { useEffect, useRef, useState } from 'react';
import { Network } from 'vis-network';
import { DataSet } from 'vis-data';

const CATEGORY_COLORS = {
  cv: '#f59e0b',
  nlp: '#3b82f6',
  ml: '#8b5cf6',
  general: '#64748b',
};

const ENTITY_COLORS = {
  model: '#8b5cf6',
  dataset: '#3b82f6',
  metric: '#10b981',
  framework: '#f59e0b',
};

const EDGE_COLORS = {
  similarity: '#94a3b8',
  entity_rel: '#cbd5e1',
  cites: '#6b7280',
  extends: '#3b82f6',
  replicates: '#10b981',
  contradicts: '#ef4444',
  inspired_by: '#f59e0b',
};

export default function KnowledgeGraph({ nodes = [], edges = [], height = 480 }) {
  const containerRef = useRef(null);
  const networkRef = useRef(null);
  const [selected, setSelected] = useState(null);

  useEffect(() => {
    if (!containerRef.current || nodes.length === 0) return;

    const visNodes = new DataSet(
      nodes.map((n) => ({
        id: n.id,
        label: n.label,
        title: n.title || n.label,
        shape: n.shape || 'ellipse',
        color: {
          background: n.color || (n.group === 'paper'
            ? (CATEGORY_COLORS[n.category] || CATEGORY_COLORS.general)
            : ENTITY_COLORS[n.entity_type] || '#64748b'),
          border: '#1e293b',
          highlight: { background: '#fbbf24', border: '#f59e0b' },
        },
        font: { color: '#f8fafc', size: 12 },
        size: n.group === 'paper' ? 18 : 12,
      }))
    );

    const visEdges = new DataSet(
      edges.map((e, i) => ({
        id: `edge_${i}`,
        from: e.from,
        to: e.to,
        title: e.title || e.link_type || '',
        width: Math.max(1, Math.min((e.value || 1) * 3, 6)),
        color: {
          color: EDGE_COLORS[e.group] || EDGE_COLORS[e.link_type] || '#94a3b8',
          opacity: 0.7,
        },
        arrows: e.group === 'similarity' ? undefined : { to: { enabled: true, scaleFactor: 0.6 } },
        smooth: { type: 'continuous' },
      }))
    );

    const options = {
      nodes: { borderWidth: 1.5 },
      edges: { smooth: { type: 'continuous' } },
      physics: {
        enabled: true,
        stabilization: { iterations: 150 },
        barnesHut: { gravitationalConstant: -6000, springLength: 120 },
      },
      interaction: { hover: true, tooltipDelay: 100 },
      layout: { improvedLayout: true },
    };

    const network = new Network(containerRef.current, { nodes: visNodes, edges: visEdges }, options);
    networkRef.current = network;

    network.on('selectNode', ({ nodes: selected }) => {
      const node = nodes.find((n) => n.id === selected[0]);
      setSelected(node || null);
    });
    network.on('deselectNode', () => setSelected(null));

    return () => {
      network.destroy();
      networkRef.current = null;
    };
  }, [nodes, edges]);

  if (nodes.length === 0) {
    return (
      <div className="flex items-center justify-center h-48 text-slate-500 text-sm">
        No knowledge graph data yet. Process more papers to build connections.
      </div>
    );
  }

  return (
    <div className="relative">
      <div ref={containerRef} style={{ height, background: '#0f172a', borderRadius: 8 }} />

      {/* Legend */}
      <div className="flex flex-wrap gap-3 mt-3 text-xs text-slate-400">
        {Object.entries(CATEGORY_COLORS).map(([k, c]) => (
          <span key={k} className="flex items-center gap-1">
            <span className="w-3 h-3 rounded-full inline-block" style={{ background: c }} />
            {k.toUpperCase()} paper
          </span>
        ))}
        {Object.entries(ENTITY_COLORS).map(([k, c]) => (
          <span key={k} className="flex items-center gap-1">
            <span className="w-3 h-3 rounded inline-block" style={{ background: c }} />
            {k}
          </span>
        ))}
      </div>

      {/* Node detail panel */}
      {selected && (
        <div className="mt-3 p-3 bg-slate-800 rounded-lg text-sm text-slate-200">
          <p className="font-semibold">{selected.title || selected.label}</p>
          {selected.group === 'paper' && (
            <p className="text-slate-400 mt-1">
              Category: {selected.category || 'general'}
              {selected.published_date && ` · ${selected.published_date}`}
              {selected.quality_score != null && ` · Quality: ${(selected.quality_score * 100).toFixed(0)}%`}
            </p>
          )}
          {selected.group === 'entity' && (
            <p className="text-slate-400 mt-1">Type: {selected.entity_type}</p>
          )}
        </div>
      )}
    </div>
  );
}
