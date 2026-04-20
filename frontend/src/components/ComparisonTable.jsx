import { useState } from 'react';
import { Download, BarChart2, Layers, Lightbulb } from 'lucide-react';

const VIEWS = [
  { key: 'metrics', label: 'Metrics', icon: BarChart2 },
  { key: 'entities', label: 'Entity Overlap', icon: Layers },
  { key: 'findings', label: 'Findings', icon: Lightbulb },
];

function cellColor(value, allValues) {
  const nums = allValues.map((v) => parseFloat(v)).filter((n) => !isNaN(n));
  if (nums.length < 2 || value === null || value === undefined) return '';
  const num = parseFloat(value);
  if (isNaN(num)) return '';
  const max = Math.max(...nums);
  const min = Math.min(...nums);
  if (num === max) return 'bg-emerald-900/40 text-emerald-300';
  if (num === min) return 'bg-red-900/30 text-red-300';
  return '';
}

function exportCSV(papers, metricsMatrix) {
  const metricNames = Object.keys(metricsMatrix);
  const header = ['Paper', ...metricNames].join(',');
  const rows = papers.map((p) =>
    [
      `"${p.title.replace(/"/g, '""')}"`,
      ...metricNames.map((m) => metricsMatrix[m]?.[p.id] ?? ''),
    ].join(',')
  );
  const csv = [header, ...rows].join('\n');
  const blob = new Blob([csv], { type: 'text/csv' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'paper_comparison.csv';
  a.click();
  URL.revokeObjectURL(url);
}

export default function ComparisonTable({ data }) {
  const [view, setView] = useState('metrics');

  if (!data || !data.papers?.length) {
    return <p className="text-slate-500 text-sm">No comparison data available.</p>;
  }

  const { papers, metrics_matrix = {}, entity_overlap = {}, findings_clusters = [] } = data;
  const metricNames = Object.keys(metrics_matrix);

  return (
    <div className="space-y-4">
      {/* View toggle */}
      <div className="flex gap-2">
        {VIEWS.map(({ key, label, icon: Icon }) => (
          <button
            key={key}
            onClick={() => setView(key)}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded text-sm font-medium transition-colors ${
              view === key
                ? 'bg-indigo-600 text-white'
                : 'bg-slate-800 text-slate-400 hover:text-slate-200'
            }`}
          >
            <Icon size={14} />
            {label}
          </button>
        ))}
        {view === 'metrics' && metricNames.length > 0 && (
          <button
            onClick={() => exportCSV(papers, metrics_matrix)}
            className="ml-auto flex items-center gap-1.5 px-3 py-1.5 rounded text-sm bg-slate-800 text-slate-400 hover:text-slate-200"
          >
            <Download size={14} />
            CSV
          </button>
        )}
      </div>

      {/* Metrics table */}
      {view === 'metrics' && (
        <div className="overflow-x-auto">
          {metricNames.length === 0 ? (
            <p className="text-slate-500 text-sm">No quantitative metrics extracted for these papers.</p>
          ) : (
            <table className="w-full text-sm border-collapse">
              <thead>
                <tr className="border-b border-slate-700">
                  <th className="text-left py-2 px-3 text-slate-400 font-medium">Metric</th>
                  {papers.map((p) => (
                    <th key={p.id} className="text-center py-2 px-3 text-slate-300 font-medium max-w-[120px]">
                      <span className="block truncate" title={p.title}>{p.title.slice(0, 25)}…</span>
                      {p.date && <span className="text-xs text-slate-500 font-normal">{p.date.slice(0, 7)}</span>}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {metricNames.map((metric) => {
                  const allVals = papers.map((p) => metrics_matrix[metric]?.[p.id]);
                  return (
                    <tr key={metric} className="border-b border-slate-800 hover:bg-slate-800/30">
                      <td className="py-2 px-3 text-slate-300 font-medium">{metric}</td>
                      {papers.map((p) => {
                        const val = metrics_matrix[metric]?.[p.id];
                        return (
                          <td
                            key={p.id}
                            className={`text-center py-2 px-3 rounded ${cellColor(val, allVals)}`}
                          >
                            {val ?? <span className="text-slate-600">—</span>}
                          </td>
                        );
                      })}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      )}

      {/* Entity overlap */}
      {view === 'entities' && (
        <div className="space-y-4">
          {Object.entries(entity_overlap).map(([etype, entities]) => {
            const items = Object.entries(entities);
            if (!items.length) return null;
            return (
              <div key={etype}>
                <h4 className="text-sm font-semibold text-slate-300 capitalize mb-2">{etype}</h4>
                <div className="flex flex-wrap gap-2">
                  {items.slice(0, 30).map(([ent, pids]) => (
                    <span
                      key={ent}
                      className={`px-2 py-0.5 rounded-full text-xs ${
                        pids.length > 1
                          ? 'bg-indigo-900/50 text-indigo-300 border border-indigo-700'
                          : 'bg-slate-800 text-slate-400'
                      }`}
                      title={`In ${pids.length} paper(s)`}
                    >
                      {ent}
                      {pids.length > 1 && (
                        <span className="ml-1 text-indigo-400">×{pids.length}</span>
                      )}
                    </span>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Findings clusters */}
      {view === 'findings' && (
        <div className="space-y-3">
          {findings_clusters.length === 0 ? (
            <p className="text-slate-500 text-sm">No clustered findings available.</p>
          ) : (
            findings_clusters.slice(0, 20).map((cluster, i) => (
              <div key={i} className="bg-slate-800 rounded-lg p-3">
                <p className="text-sm text-slate-200">{cluster.representative}</p>
                <p className="text-xs text-slate-500 mt-1">
                  {cluster.unique_to
                    ? `Unique to 1 paper`
                    : `Shared across ${cluster.papers.length} papers`}
                </p>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}
