import { Table2 } from 'lucide-react'
import { Card, CardBody, EmptyState, ErrorState, Eyebrow } from './ui/primitives'

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
  const rawBody = lines.slice(2).map(toCells)
  if (!rawBody.length) return null

  // A body row with more cells than the header isn't a padding problem — the
  // pipe-split itself went wrong somewhere (most likely an unescaped `|` inside
  // a cell), and no amount of padding puts those extra cells under the right
  // header. Bail to the raw <pre> fallback rather than render orphan columns.
  if (rawBody.some((row) => row.length > header.length)) return null

  const columns = header.length
  const pad = (row) =>
    row.length < columns ? [...row, ...Array(columns - row.length).fill('')] : row
  // Short rows used to render as-is, so every cell after the gap silently
  // shifted left under the wrong header. The backend already pads before
  // persisting (table_extractor.py's _normalise), but older persisted rows and
  // any future non-rectangular source still reach this component un-padded.
  const body = rawBody.map(pad)

  /*
   * Papers stack multi-level headers with \cmidrule, which no line-based
   * extractor can map onto flat columns — it arrives as one merged band with
   * every other cell empty. Rendered as a normal <th> that band sets a column
   * width the data rows cannot live with, pushing the numbers out of view.
   * Spanning the row is both what it means and what fits.
   *
   * But a header that labels only its *first* column (e.g. `['Method', '',
   * '']`, the row-label column) is not that — it's an ordinary header that
   * simply didn't recover labels for the other columns, and collapsing it to a
   * full-width banner throws away the one column structure it had. Only treat
   * a single truthy label as a banner when it sits over other columns (a group
   * label, not a row label), or when the row beneath it is itself a second,
   * all-non-numeric header band \cmidrule left behind as data.
   */
  const truthy = header.reduce((acc, c, i) => (c ? [...acc, i] : acc), [])
  let banner = null
  if (truthy.length === 1) {
    const idx = truthy[0]
    const nextRow = rawBody[0] || []
    const nextRowLooksLikeHeader =
      nextRow.some(Boolean) && nextRow.every((c) => !c || !/\d/.test(c))
    if (idx !== 0 || nextRowLooksLikeHeader) {
      banner = header[idx]
    }
  }

  // A PyMuPDF column boundary occasionally goes undetected on a table with
  // grouped sub-headers (e.g. three metrics stacked under one "Text-to-Audio"
  // band) — the whole band's cells then arrive concatenated by whitespace
  // into what looks, structurally, like a single column. Rendered as an
  // ordinary <th>/<td> that reads as a wall of stacked words rather than a
  // misparsed table, which is worse than the row-per-line fallback below. A
  // real cell in a results table is short (the backend's own extraction
  // rejects anything wordier as prose, see table_extractor.py's
  // _MAX_CELL_WORDS/_MAX_VALUE_WORDS) — a cell many times that size is the
  // tell. `malformed: true` keeps the tokenised rows rather than discarding
  // them — losing the recovered column *boundaries* is unavoidable here, but
  // there's no reason to also lose the individual cell values and fall back
  // to the raw, unwrapped Markdown string.
  const wordCount = (cell) => cell.split(/\s+/).filter(Boolean).length
  const malformed =
    header.some((cell) => wordCount(cell) > 14) ||
    body.some((row) => row.some((cell) => wordCount(cell) > 12))

  return { header, body, columns, banner, malformed }
}

export default function TablesDisplay({ tables, pipelineStatus }) {
  if (!tables || tables.length === 0) {
    // "No tables in this paper" and "table extraction crashed" used to render
    // identically — the empty state below reads as a calm, expected outcome,
    // which is the wrong message when extraction actually failed.
    if (pipelineStatus?.status === 'failed') {
      return (
        <ErrorState
          title="Table extraction failed"
          message={pipelineStatus.error || 'Something went wrong while pulling tables from this PDF.'}
        />
      )
    }
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
                {parsed?.malformed ? (
                  <div className="space-y-3">
                    <p className="text-caption text-ink-faint">
                      This table&apos;s column structure didn&apos;t survive extraction —
                      showing the values PaperMind found, in reading order.
                    </p>
                    <div className="space-y-1.5 rounded bg-surface-sunk p-3 text-code leading-relaxed text-ink-muted">
                      {[parsed.header, ...parsed.body].map((row, r) => (
                        <p
                          key={r}
                          className={
                            r === 0
                              ? 'whitespace-pre-wrap break-words font-medium text-ink'
                              : 'whitespace-pre-wrap break-words border-t border-line/50 pt-1.5 first:border-0 first:pt-0'
                          }
                        >
                          {row.filter(Boolean).join('   ·   ')}
                        </p>
                      ))}
                    </div>
                  </div>
                ) : parsed ? (
                  <div className="-mx-1 overflow-x-auto px-1">
                    {/* No w-full: with header cells free to wrap and data
                        cells pinned to whitespace-nowrap, a `100%`-wide table
                        had nowhere to put its leftover space except the one
                        elastic column — usually the row-label column — which
                        stretched into a wide band of visually empty padding
                        between a short label and where the numbers began. A
                        table sized to its own content just sits at its
                        natural width, however small, and the wrapper above
                        still scrolls it if it's genuinely wide. */}
                    <table className="border-collapse text-sm">
                      <thead>
                        <tr className="border-b border-line">
                          {parsed.banner ? (
                            <th
                              colSpan={parsed.columns}
                              scope="colgroup"
                              className="px-3 py-2 text-left font-medium leading-snug text-ink"
                            >
                              {parsed.banner}
                            </th>
                          ) : (
                            parsed.header.map((cell, i) => (
                              <th
                                key={i}
                                scope="col"
                                /* Headers may wrap, but only within a capped
                                   width — unbounded wrap is what let one long
                                   label decide the table's entire width. */
                                className="max-w-[12rem] px-3 py-2 text-left align-bottom font-medium leading-snug text-ink"
                              >
                                {cell}
                              </th>
                            ))
                          )}
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
