import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import axios from 'axios';
import { Network } from 'vis-network';
import { DataSet } from 'vis-data';
import { Timeline } from 'vis-timeline';
import { GitBranch, Calendar } from 'lucide-react';

const LINK_COLORS = {
  cites: '#6b7280',
  extends: '#3b82f6',
  replicates: '#10b981',
  contradicts: '#ef4444',
  inspired_by: '#f59e0b',
};

const CAT_COLORS = {
  cv: '#f59e0b', nlp: '#3b82f6', ml: '#8b5cf6', general: '#64748b',
};

export default function TimelinePage() {
  const { token } = useAuth();
  const navigate = useNavigate();
  const timelineRef = useRef(null);
  const treeRef = useRef(null);
  const treeNetRef = useRef(null);
  const [loading, setLoading] = useState(true);
  const [timelineData, setTimelineData] = useState(null);
  const [selectedPaper, setSelectedPaper] = useState(null);
  const [ancestryData, setAncestryData] = useState(null);
  const [ancestryLoading, setAncestryLoading] = useState(false);

  useEffect(() => {
    const fetchTimeline = async () => {
      try {
        const res = await axios.get('/api/graph/timeline', {
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

    const items = new DataSet(
      papers.map((p) => ({
        id: p.id,
        content: `<span title="${p.paper_title}">${(p.paper_title || 'Untitled').slice(0, 30)}…</span>`,
        start: p.published_date,
        className: `cat-${p.primary_category || 'general'}`,
        style: `background:${CAT_COLORS[p.primary_category] || CAT_COLORS.general};border-color:#1e293b;color:#f8fafc;border-radius:4px;padding:2px 6px;font-size:11px;`,
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
  }, [timelineData]);

  const loadAncestry = async (paper) => {
    setSelectedPaper(paper);
    setAncestryLoading(true);
    try {
      const res = await axios.get(`/api/graph/ancestry/${paper.id}`, {
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
          background: n.is_anchor ? '#f59e0b' : (CAT_COLORS[n.category] || CAT_COLORS.general),
          border: '#1e293b',
          highlight: { background: '#fbbf24', border: '#f59e0b' },
        },
        font: { color: '#f8fafc', size: 11 },
        shape: n.is_anchor ? 'star' : 'ellipse',
        size: n.is_anchor ? 24 : 16,
      }))
    );

    const visEdges = new DataSet(
      ancestryData.edges.map((e, i) => ({
        id: `te_${i}`,
        from: e.from,
        to: e.to,
        title: e.link_type,
        color: { color: LINK_COLORS[e.link_type] || '#94a3b8' },
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
  }, [ancestryData, navigate]);

  return (
    <div className="max-w-6xl mx-auto px-4 py-8 space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-white flex items-center gap-2">
          <Calendar size={22} className="text-indigo-400" />
          Research Timeline
        </h1>
        <p className="text-slate-400 text-sm mt-1">
          Papers ordered by publication date. Click a paper to explore its lineage tree.
        </p>
      </div>

      {/* Legend */}
      <div className="flex flex-wrap gap-4 text-xs text-slate-400">
        {Object.entries(LINK_COLORS).map(([t, c]) => (
          <span key={t} className="flex items-center gap-1">
            <span className="w-4 h-0.5 inline-block" style={{ background: c }} />
            {t}
          </span>
        ))}
      </div>

      {loading ? (
        <div className="text-slate-400">Loading timeline…</div>
      ) : !timelineData?.papers?.filter((p) => p.published_date).length ? (
        <div className="text-slate-500 text-sm p-8 text-center bg-slate-800 rounded-lg">
          No papers with publication dates yet. Process arXiv papers to populate the timeline.
        </div>
      ) : (
        <>
          {/* Timeline strip */}
          <div
            ref={timelineRef}
            className="bg-slate-900 border border-slate-700 rounded-xl overflow-hidden"
          />

          {/* Ancestry tree */}
          {selectedPaper && (
            <div className="bg-slate-900 border border-slate-700 rounded-xl p-4">
              <h2 className="text-sm font-semibold text-white flex items-center gap-2 mb-3">
                <GitBranch size={16} className="text-indigo-400" />
                Lineage: {selectedPaper.paper_title?.slice(0, 60)}
              </h2>

              {ancestryLoading ? (
                <div className="text-slate-400 text-sm">Loading ancestry…</div>
              ) : !ancestryData?.nodes?.length ? (
                <div className="text-slate-500 text-sm">
                  No lineage connections found. More papers are needed to infer relationships.
                </div>
              ) : (
                <>
                  <div
                    ref={treeRef}
                    style={{ height: 320, background: '#0f172a', borderRadius: 8 }}
                  />
                  <p className="text-xs text-slate-500 mt-2">
                    ★ = selected paper · Double-click a node to open its summary
                  </p>
                </>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}
