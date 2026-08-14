import { useState } from 'react';
import { Download, BarChart2, Layers, Lightbulb } from 'lucide-react';
import {
  Badge,
  Button,
  Card,
  CardBody,
  Eyebrow,
  Inline,
  ScrollArea,
  cx,
} from './ui/primitives';

const VIEWS = [
  { key: 'metrics', label: 'Metrics', icon: BarChart2 },
  { key: 'entities', label: 'Overlap', icon: Layers },
  { key: 'findings', label: 'Findings', icon: Lightbulb },
];

/**
 * Best and worst in a row get a quiet tint rather than a saturated fill — the
 * reader is comparing numbers, and a loud cell pulls the eye off the column.
 */
function cellTone(value, allValues) {
  const nums = allValues.map((v) => parseFloat(v)).filter((n) => !isNaN(n));
  if (nums.length < 2 || value === null || value === undefined) return '';
  const num = parseFloat(value);
  if (isNaN(num)) return '';
  const max = Math.max(...nums);
  const min = Math.min(...nums);
  if (num === max) return 'bg-success-soft text-success font-medium';
  if (num === min) return 'text-ink-faint';
  return 'text-ink';
}

/** Quote a CSV field: wrap in quotes and double any quote inside. */
function csvCell(value) {
  const s = value == null ? '' : String(value);
  return `"${s.replace(/"/g, '""')}"`;
}

function exportCSV(papers, metricsMatrix) {
  const metricNames = Object.keys(metricsMatrix);
  const header = ['Paper', ...metricNames].map(csvCell).join(',');
  const rows = papers.map((p) =>
    [
      p.title,
      // Values were written raw. A measurement like `1,024` or one carrying a
      // quote shifted every column after it by one, silently — which is the
      // worst way for an export to be wrong.
      ...metricNames.map((m) => metricsMatrix[m]?.[p.id] ?? ''),
    ]
      .map(csvCell)
      .join(','),
  );
  // CRLF and a BOM: Excel is the overwhelmingly common destination for this
  // file, and without the BOM it reads the UTF-8 as the local codepage and
  // mangles every non-ASCII paper title.
  const csv = '﻿' + [header, ...rows].join('\r\n');
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'paper_comparison.csv';
  // Firefox ignores a click on an anchor that is not in the document, so the
  // button did nothing there.
  document.body.appendChild(a);
  a.click();
  a.remove();
  // Deferred: revoking in the same tick can cancel the download before the
  // browser has read the blob.
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export default function ComparisonTable({ data }) {
  const [view, setView] = useState('metrics');

  if (!data || !data.papers?.length) {
    return <p className="text-sm text-ink-faint">No comparison data available.</p>;
  }

  const { papers, metrics_matrix = {}, entity_overlap = {}, findings_clusters = [] } = data;
  const metricNames = Object.keys(metrics_matrix);

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-2">
        <div className="inline-flex rounded border border-line bg-surface-sunk p-0.5">
          {VIEWS.map(({ key, label, icon: Icon }) => (
            <button
              key={key}
              type="button"
              onClick={() => setView(key)}
              aria-pressed={view === key}
              className={cx(
                'inline-flex items-center gap-1.5 rounded-sm px-3 py-1.5 text-caption font-medium',
                'transition-colors duration-fast ease-out',
                view === key
                  ? 'bg-surface text-ink'
                  : 'text-ink-faint hover:text-ink'
              )}
            >
              <Icon size={13} aria-hidden="true" />
              {label}
            </button>
          ))}
        </div>

        {view === 'metrics' && metricNames.length > 0 && (
          <Button
            variant="secondary"
            size="sm"
            className="ml-auto"
            onClick={() => exportCSV(papers, metrics_matrix)}
          >
            <Download size={13} aria-hidden="true" />
            CSV
          </Button>
        )}
      </div>

      {view === 'metrics' &&
        (metricNames.length === 0 ? (
          <p className="text-sm text-ink-faint">
            No quantitative metrics were extracted for these papers.
          </p>
        ) : (
          /* Ten papers wide and however many measurements deep. Both axes are
             set by the corpus, so both scroll inside the card — the header row
             stays put so a value halfway down is still attributable to a
             paper. */
          <ScrollArea
            maxHeight="30rem"
            aria-label="Metric comparison"
            className="rounded-lg border border-line"
          >
            <table className="w-full border-collapse text-sm">
              <thead className="sticky top-0 z-10">
                <tr className="border-b border-line bg-surface-sunk">
                  <th className="px-4 py-2.5 text-left text-eyebrow font-semibold uppercase text-ink-faint">
                    Metric
                  </th>
                  {papers.map((p) => (
                    <th
                      key={p.id}
                      className="max-w-[140px] px-4 py-2.5 text-center font-medium text-ink"
                    >
                      <span className="block truncate font-serif" title={p.title}>
                        {p.title.slice(0, 25)}…
                      </span>
                      {p.date && (
                        <span className="mt-0.5 block font-mono tabular text-code font-normal text-ink-faint">
                          {p.date.slice(0, 7)}
                        </span>
                      )}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {metricNames.map((metric) => {
                  const allVals = papers.map((p) => metrics_matrix[metric]?.[p.id]);
                  return (
                    <tr key={metric} className="border-b border-line last:border-b-0">
                      <td className="px-4 py-2.5 font-medium text-ink">{metric}</td>
                      {papers.map((p) => {
                        const val = metrics_matrix[metric]?.[p.id];
                        return (
                          <td
                            key={p.id}
                            className={cx(
                              'px-4 py-2.5 text-center font-mono tabular',
                              cellTone(val, allVals)
                            )}
                          >
                            {val ?? <span className="text-ink-faint">—</span>}
                          </td>
                        );
                      })}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </ScrollArea>
        ))}

      {view === 'entities' && (
        /* Entities shared by more than one paper come first — that is the
           question this view answers, and burying the overlaps among dozens of
           singletons in extraction order made it unanswerable. */
        <ScrollArea maxHeight="30rem" aria-label="Entity overlap" className="space-y-5">
          {Object.entries(entity_overlap).map(([etype, entities]) => {
            const items = Object.entries(entities).sort(
              (a, b) => b[1].length - a[1].length,
            );
            if (!items.length) return null;
            const shared = items.filter(([, pids]) => pids.length > 1).length;
            return (
              <div key={etype}>
                <div className="flex items-baseline gap-2">
                  <Eyebrow>{etype}</Eyebrow>
                  <span className="text-caption text-ink-faint">
                    {shared > 0 ? `${shared} shared` : 'none shared'}
                  </span>
                </div>
                <div className="mt-2.5 flex flex-wrap gap-1.5">
                  {items.map(([ent, pids]) => (
                    <Badge
                      key={ent}
                      tone={pids.length > 1 ? 'accent' : 'outline'}
                      mono
                      title={`In ${pids.length} paper${pids.length === 1 ? '' : 's'}`}
                    >
                      {ent}
                      {pids.length > 1 && (
                        <span className="ml-1 opacity-70">×{pids.length}</span>
                      )}
                    </Badge>
                  ))}
                </div>
              </div>
            );
          })}
        </ScrollArea>
      )}

      {view === 'findings' && (
        <ScrollArea maxHeight="30rem" aria-label="Clustered findings" className="space-y-2">
          {findings_clusters.length === 0 ? (
            <p className="text-sm text-ink-faint">No clustered findings available.</p>
          ) : (
            findings_clusters.map((cluster, i) => (
              <Card key={i}>
                <CardBody className="py-4">
                  <p className="text-sm leading-relaxed text-ink">
                    <Inline>{cluster.representative}</Inline>
                  </p>
                  <p className="mt-2 text-caption text-ink-faint">
                    {cluster.unique_to
                      ? 'Unique to one paper'
                      : `Shared across ${cluster.papers.length} papers`}
                  </p>
                </CardBody>
              </Card>
            ))
          )}
        </ScrollArea>
      )}
    </div>
  );
}
