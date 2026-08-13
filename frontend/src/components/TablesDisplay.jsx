import { Table2 } from 'lucide-react'
import { Card, CardBody, EmptyState, Eyebrow } from './ui/primitives'

/**
 * Parse one Markdown table into a header row and body rows.
 *
 * The backend renders tables as Markdown so the same string can feed the
 * summariser's prompt and this view. Rendering it as a real <table> rather than
 * a code block is the difference between reading the numbers and squinting at
 * them.
 */
function parseMarkdownTable(markdown) {
  const lines = (markdown || '').trim().split('\n').filter(Boolean)
  if (lines.length < 2) return null

  const toCells = (line) =>
    line
      .replace(/^\||\|$/g, '')
      .split(/(?<!\\)\|/)
      .map((c) => c.replace(/\\\|/g, '|').trim())

  // Line 2 is the `| --- | --- |` separator; everything after it is data.
  const header = toCells(lines[0])
  const body = lines.slice(2).map(toCells)
  if (!body.length) return null

  return { header, body }
}

export default function TablesDisplay({ tables }) {
  if (!tables || tables.length === 0) {
    return (
      <EmptyState
        icon={Table2}
        title="No tables detected"
        description="PaperMind found no captioned tables in this PDF. Papers that present results only in prose or as images won't have any."
      />
    )
  }

  return (
    <div>
      <Eyebrow className="block">
        {tables.length} table{tables.length === 1 ? '' : 's'} lifted from the paper
      </Eyebrow>

      <div className="mt-4 space-y-4">
        {tables.map((table, idx) => {
          const parsed = parseMarkdownTable(table.markdown)

          return (
            <Card key={idx}>
              <CardBody className="space-y-3">
                <div className="flex items-baseline justify-between gap-3">
                  <span className="font-mono tabular text-sm text-ink">
                    {table.label || `Table ${idx + 1}`}
                  </span>
                  {table.page > 0 && (
                    <span className="font-mono tabular text-code text-ink-faint">
                      p.{table.page}
                    </span>
                  )}
                </div>

                {/* The caption is the paper's own prose, so it reads as prose. */}
                {table.caption && (
                  <p className="font-serif text-sm leading-relaxed text-ink-muted">
                    {table.caption}
                  </p>
                )}

                {/* Wide tables scroll inside their own box; the page never does. */}
                {parsed ? (
                  <div className="-mx-1 overflow-x-auto px-1">
                    <table className="w-full border-collapse text-sm">
                      <thead>
                        <tr className="border-b border-line">
                          {parsed.header.map((cell, i) => (
                            <th
                              key={i}
                              scope="col"
                              className="whitespace-nowrap px-3 py-2 text-left font-medium text-ink"
                            >
                              {cell}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {parsed.body.map((row, r) => (
                          <tr key={r} className="border-b border-line/50 last:border-0">
                            {row.map((cell, c) => (
                              <td
                                key={c}
                                /* Values are numeric and want to line up; the
                                   first column is a label and wants to read. */
                                className={
                                  c === 0
                                    ? 'px-3 py-2 text-ink-muted'
                                    : 'whitespace-nowrap px-3 py-2 font-mono tabular text-ink-muted'
                                }
                              >
                                {cell}
                              </td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <pre className="overflow-x-auto rounded bg-surface-sunk p-3 text-code text-ink-muted">
                    {table.markdown}
                  </pre>
                )}
              </CardBody>
            </Card>
          )
        })}
      </div>
    </div>
  )
}
