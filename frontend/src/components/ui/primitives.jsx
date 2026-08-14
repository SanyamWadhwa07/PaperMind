/**
 * Component primitives.
 *
 * Every surface in the app is built from these, so spacing, radius, focus, and
 * colour stay consistent without each page reinventing them. They read tokens
 * only — no raw hex anywhere below.
 *
 * Geometry follows the DesignMD `cursor` system: 40px control height, 8px
 * control radius, 12px card radius, hairline-only depth (no drop shadows), and
 * display type pinned to weight 400.
 */
import { forwardRef, useId, useState } from 'react'
import { ChevronDown } from 'lucide-react'
import { Link } from 'react-router-dom'

import { MATH_TOKEN, looksLikeMath, mathBody, renderMath } from '../../lib/mathText'

/** Join class names, dropping falsy entries. */
export function cx(...parts) {
  return parts.filter(Boolean).join(' ')
}

/* ── Button ─────────────────────────────────────────────────────────────── */

const BUTTON_VARIANTS = {
  // The single brand voltage. Used scarcely — one per view, at most.
  primary:
    'bg-accent text-accent-ink hover:bg-accent-hover disabled:hover:bg-accent',
  secondary:
    'bg-surface text-ink border border-line hover:bg-surface-hover hover:border-line-strong',
  ghost:
    'text-ink-muted hover:text-ink hover:bg-surface-hover',
  // Ink-filled, for the second-strongest action on a view.
  contrast:
    'bg-ink text-canvas hover:bg-ink/90',
  danger:
    'bg-danger-soft text-danger border border-danger/30 hover:border-danger/60',
}

const BUTTON_SIZES = {
  sm: 'h-8 px-3 text-caption gap-1.5',
  md: 'h-10 px-[18px] text-sm gap-2',
  lg: 'h-11 px-5 text-sm gap-2',
  icon: 'h-9 w-9 justify-center',
}

const BUTTON_BASE =
  'inline-flex items-center justify-center rounded font-medium ' +
  'transition-colors duration-fast ease-out ' +
  'disabled:opacity-50 disabled:cursor-not-allowed select-none'

export const Button = forwardRef(function Button(
  { variant = 'primary', size = 'md', className, as, to, href, loading, children, ...props },
  ref,
) {
  const classes = cx(BUTTON_BASE, BUTTON_VARIANTS[variant], BUTTON_SIZES[size], className)
  const content = (
    <>
      {loading && <Spinner size="sm" />}
      {children}
    </>
  )

  if (to) {
    return (
      <Link ref={ref} to={to} className={classes} {...props}>
        {content}
      </Link>
    )
  }
  if (href) {
    return (
      <a ref={ref} href={href} className={classes} {...props}>
        {content}
      </a>
    )
  }

  const Tag = as || 'button'
  return (
    <Tag ref={ref} className={classes} disabled={loading || props.disabled} {...props}>
      {content}
    </Tag>
  )
})

/* ── Card ───────────────────────────────────────────────────────────────── */

/** White on cream, separated by a hairline. This system has no shadows. */
export function Card({ className, interactive, as: Tag = 'div', ...props }) {
  return (
    <Tag
      className={cx(
        'rounded-lg border border-line bg-surface',
        interactive &&
          'transition-colors duration-fast ease-out hover:border-line-strong',
        className,
      )}
      {...props}
    />
  )
}

/** 20px of padding on a phone, 24px from `sm` up — 24px on all four sides of a
 *  390px screen spends an eighth of the width on margin. */
export function CardBody({ className, ...props }) {
  return <div className={cx('p-5 sm:p-6', className)} {...props} />
}

/* ── Scroll containment ─────────────────────────────────────────────────── */

/**
 * A block that scrolls inside itself rather than growing without bound.
 *
 * Extraction output has no length ceiling: one paper yields six result rows and
 * the next yields ninety. A card that grows to fit ninety sets the height of the
 * whole row, so the column beside it ends in hundreds of pixels of empty gutter
 * and the page stops looking designed. Capping the height means the *layout* is
 * decided by the design rather than by whatever the pipeline happened to
 * extract.
 *
 * `maxHeight` is a raw CSS length so a caller can match one block's cap to
 * another's. Scrolling regions are focusable on purpose — a keyboard user with
 * no pointer otherwise cannot reach content below the fold (WCAG 2.1.1).
 */
export function ScrollArea({
  maxHeight = '26rem',
  className,
  style,
  children,
  ...props
}) {
  return (
    <div
      // `overscroll-contain` stops a scroll that bottoms out here from
      // continuing into the page behind it, which otherwise reads as the
      // viewport lurching when the pointer happens to be over a table.
      className={cx('overflow-auto overscroll-contain', className)}
      style={{ maxHeight, ...style }}
      tabIndex={0}
      {...props}
    >
      {children}
    </div>
  )
}

/* ── Bento grid ─────────────────────────────────────────────────────────── */

/**
 * The app's one dense-layout grid.
 *
 * Pages had each grown their own column definition — `sm:grid-cols-3` here,
 * `xl:grid-cols-[minmax(0,68ch)_minmax(0,1fr)]` there — so no two views lined
 * up and a card meant a different width on each page. This is a single six-
 * column track that every tiled view shares; tiles claim width through
 * `BentoItem`'s `span`, and the column count is the only thing that changes
 * across breakpoints.
 *
 * Six divides by two and three, so halves, thirds, and two-thirds all land on
 * the same track — the arrangements a bento actually needs.
 */
export function Bento({ className, ...props }) {
  return (
    <div
      className={cx(
        'grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-6',
        // Tiles in a row match heights, so a short card does not float with a
        // gap beneath it while its neighbour runs long.
        'items-stretch',
        className,
      )}
      {...props}
    />
  )
}

/**
 * One tile. `span` is in sixths and applies from `xl` up, where the six-column
 * track exists; below that the grid is two columns and `wide` tiles take both.
 */
const BENTO_SPANS = {
  2: 'xl:col-span-2',
  3: 'xl:col-span-3',
  4: 'xl:col-span-4',
  6: 'xl:col-span-6',
}

export function BentoItem({ span = 3, className, as: Tag = 'div', ...props }) {
  return (
    <Tag
      className={cx(
        'min-w-0',
        // A tile spanning the full track should also span both columns at the
        // mid breakpoint — half a full-width tile is not a smaller version of
        // the same idea, it is a different layout.
        span === 6 && 'sm:col-span-2',
        BENTO_SPANS[span] || BENTO_SPANS[3],
        className,
      )}
      {...props}
    />
  )
}

export function CardHeader({ title, description, action, className }) {
  return (
    <div
      className={cx(
        'flex flex-wrap items-start justify-between gap-x-4 gap-y-2',
        'border-b border-line px-5 py-4 sm:px-6',
        className,
      )}
    >
      <div className="min-w-0">
        <h2 className="truncate text-base font-semibold text-ink">{title}</h2>
        {description && (
          <p className="mt-0.5 text-sm text-ink-muted">{description}</p>
        )}
      </div>
      {action}
    </div>
  )
}

/* ── Field label ────────────────────────────────────────────────────────── */

/** The small tracked-out label used above every value in the app. */
export function Eyebrow({ className, ...props }) {
  return (
    <span
      className={cx(
        'text-eyebrow font-semibold uppercase text-ink-faint',
        className,
      )}
      {...props}
    />
  )
}

/* ── Inputs ─────────────────────────────────────────────────────────────── */

const CONTROL_BASE =
  'w-full rounded border border-line bg-surface px-4 text-sm text-ink ' +
  'placeholder:text-ink-faint transition-colors duration-fast ease-out ' +
  'hover:border-line-strong ' +
  'focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/25 ' +
  'disabled:cursor-not-allowed disabled:opacity-60'

export const Input = forwardRef(function Input({ className, invalid, ...props }, ref) {
  return (
    <input
      ref={ref}
      aria-invalid={invalid || undefined}
      className={cx(CONTROL_BASE, 'h-11', invalid && 'border-danger', className)}
      {...props}
    />
  )
})

export const Textarea = forwardRef(function Textarea({ className, ...props }, ref) {
  return <textarea ref={ref} className={cx(CONTROL_BASE, 'py-3', className)} {...props} />
})

export const Select = forwardRef(function Select({ className, ...props }, ref) {
  return <select ref={ref} className={cx(CONTROL_BASE, 'h-11', className)} {...props} />
})

export function Field({ label, hint, error, htmlFor, children, className }) {
  return (
    <div className={cx('space-y-1.5', className)}>
      {label && (
        <label htmlFor={htmlFor} className="block text-sm font-medium text-ink">
          {label}
        </label>
      )}
      {children}
      {error ? (
        <p className="text-caption text-danger">{error}</p>
      ) : hint ? (
        <p className="text-caption text-ink-muted">{hint}</p>
      ) : null}
    </div>
  )
}

/* ── Badge ──────────────────────────────────────────────────────────────── */

const BADGE_TONES = {
  neutral: 'bg-surface-hover text-ink border-transparent',
  accent: 'bg-accent-soft text-accent border-transparent',
  annotate: 'bg-annotate-soft text-annotate border-transparent',
  success: 'bg-success-soft text-success border-transparent',
  warning: 'bg-warning-soft text-warning border-transparent',
  danger: 'bg-danger-soft text-danger border-transparent',
  outline: 'bg-transparent text-ink-muted border-line',
}

/** Pill, tracked caps. Cursor's badge dialect. */
export function Badge({ tone = 'neutral', mono, className, ...props }) {
  return (
    <span
      className={cx(
        'inline-flex items-center gap-1 rounded-full border px-2.5 py-1',
        'text-eyebrow font-semibold uppercase',
        BADGE_TONES[tone],
        mono && 'font-mono tabular normal-case tracking-normal',
        className,
      )}
      {...props}
    />
  )
}

/**
 * The AI-timeline pill — this system's strongest signature. Cursor reserves the
 * five pastels for marking stages inside product UI, never as action colours,
 * so they carry pipeline stages and the four summary levels here.
 */
const STAGE_FILLS = {
  1: 'bg-stage-1',
  2: 'bg-stage-2',
  3: 'bg-stage-3',
  4: 'bg-stage-4',
  5: 'bg-stage-5',
}

export function StagePill({ stage = 1, className, ...props }) {
  return <span className={cx('stage-pill', STAGE_FILLS[stage], className)} {...props} />
}

/** arXiv IDs, DOIs, and other identifiers. Always mono, always tabular. */
export function Identifier({ children, className }) {
  return (
    <span className={cx('font-mono tabular text-code text-ink-faint', className)}>
      {children}
    </span>
  )
}

/** A number the reader is meant to compare against others. Mono, aligned. */
export function Metric({ label, value, hint, className }) {
  return (
    <div className={cx('min-w-0', className)}>
      <Eyebrow className="block">{label}</Eyebrow>
      <p className="mt-1.5 font-mono tabular text-display-xs text-ink">{value}</p>
      {hint && <p className="mt-0.5 text-caption text-ink-faint">{hint}</p>}
    </div>
  )
}

/* ── Loading ────────────────────────────────────────────────────────────── */

const SPINNER_SIZES = { sm: 'h-3.5 w-3.5', md: 'h-5 w-5', lg: 'h-8 w-8' }

export function Spinner({ size = 'md', className }) {
  return (
    <svg
      className={cx('animate-spin', SPINNER_SIZES[size], className)}
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
    >
      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" opacity="0.2" />
      <path
        d="M22 12a10 10 0 0 1-10 10"
        stroke="currentColor"
        strokeWidth="3"
        strokeLinecap="round"
      />
    </svg>
  )
}

export function Skeleton({ className }) {
  return <div className={cx('shimmer rounded', className)} aria-hidden="true" />
}

/** Placeholder matching the shape of a paper card, so lists don't jump. */
export function SkeletonCard() {
  return (
    <Card>
      <CardBody className="space-y-3">
        <Skeleton className="h-3 w-24" />
        <Skeleton className="h-5 w-3/4" />
        <Skeleton className="h-4 w-1/2" />
        <div className="flex gap-2 pt-1">
          <Skeleton className="h-5 w-16" />
          <Skeleton className="h-5 w-20" />
        </div>
      </CardBody>
    </Card>
  )
}

/* ── Empty and error states ─────────────────────────────────────────────── */

/** An empty screen is an invitation to act, so it always carries the action. */
export function EmptyState({ icon: Icon, title, description, action, className }) {
  return (
    <div
      className={cx(
        'flex flex-col items-center justify-center rounded-lg border border-dashed ' +
          'border-line px-6 py-16 text-center',
        className,
      )}
    >
      {Icon && (
        <div className="mb-4 rounded-lg bg-surface-sunk p-3 text-ink-faint">
          <Icon className="h-6 w-6" aria-hidden="true" />
        </div>
      )}
      <h3 className="text-base font-semibold text-ink">{title}</h3>
      {description && (
        <p className="mt-1.5 max-w-sm text-sm text-ink-muted">{description}</p>
      )}
      {action && <div className="mt-6">{action}</div>}
    </div>
  )
}

/** States what went wrong and how to fix it. Never apologises, never vague. */
export function ErrorState({ title = 'Something went wrong', message, onRetry }) {
  return (
    <div className="rounded-lg border border-danger/30 bg-danger-soft px-5 py-4">
      <h3 className="text-sm font-semibold text-danger">{title}</h3>
      {message && <p className="mt-1 text-sm text-ink-muted">{message}</p>}
      {onRetry && (
        <Button variant="secondary" size="sm" className="mt-3" onClick={onRetry}>
          Try again
        </Button>
      )}
    </div>
  )
}

/* ── Page scaffolding ───────────────────────────────────────────────────── */

export function PageHeader({ eyebrow, title, description, actions, className }) {
  return (
    <header
      className={cx(
        'flex flex-col gap-4 border-b border-line pb-6 sm:flex-row sm:items-end sm:justify-between',
        className,
      )}
    >
      <div className="min-w-0">
        {eyebrow && <Eyebrow className="block">{eyebrow}</Eyebrow>}
        {/* Weight 400 — the magazine voice. Never bold at display sizes. */}
        <h1 className="display mt-2 text-display-sm text-ink">{title}</h1>
        {description && (
          <p className="mt-2 max-w-prose text-sm text-ink-muted">{description}</p>
        )}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </header>
  )
}

/* ── Disclosure ─────────────────────────────────────────────────────────── */

/**
 * A labelled expander for secondary material.
 *
 * Exists so that diagnostics — run times, model names, agent counts — can stay
 * reachable without competing with the paper for the top of the page. They are
 * answers to "how was this made", which is a question a reader asks once, if
 * ever, and never before reading the summary itself.
 */
export function Disclosure({
  label,
  hint,
  defaultOpen = false,
  children,
  className,
}) {
  const [open, setOpen] = useState(defaultOpen)
  const panelId = useId()

  return (
    <div className={cx('rounded-lg border border-line bg-surface', className)}>
      <button
        type="button"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((v) => !v)}
        className={cx(
          'flex w-full items-center gap-2 px-4 py-3 text-left sm:px-5',
          'text-sm font-medium text-ink-muted',
          'transition-colors duration-fast ease-out hover:text-ink',
          'focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/25',
        )}
      >
        <ChevronDown
          className={cx(
            'h-4 w-4 shrink-0 text-ink-faint transition-transform duration-fast',
            open && 'rotate-180',
          )}
          aria-hidden="true"
        />
        {label}
        {hint && (
          <span className="ml-auto truncate font-mono tabular text-code text-ink-faint">
            {hint}
          </span>
        )}
      </button>
      {open && (
        <div id={panelId} className="border-t border-line">
          {children}
        </div>
      )}
    </div>
  )
}

/* ── Prose ──────────────────────────────────────────────────────────────── */

// The synthesis prompt asks for flowing prose with no markdown, but models
// emit `**bold**` anyway often enough that rendering it literally is the more
// common failure. The same goes for the `$\alpha$` spans the source paper is
// written in, which the summariser reproduces verbatim and correctly — those
// are resolved by `mathText`. Handled inline rather than by pulling in a
// markdown library: the output below is React elements, never HTML, so there is
// no injection surface regardless of what the model writes.
const INLINE_TOKEN = new RegExp(
  `(\\*\\*[^*]+\\*\\*|__[^_]+__|\`[^\`]+\`|\\*[^*\\n]+\\*)|${MATH_TOKEN.source}`,
  'g',
)

function renderInline(text, keyPrefix) {
  return text.split(INLINE_TOKEN).filter(Boolean).map((part, i) => {
    const key = `${keyPrefix}-${i}`
    if (part.startsWith('**') && part.endsWith('**')) {
      return <strong key={key} className="font-semibold text-ink">{part.slice(2, -2)}</strong>
    }
    if (part.startsWith('__') && part.endsWith('__')) {
      return <strong key={key} className="font-semibold text-ink">{part.slice(2, -2)}</strong>
    }
    if (part.startsWith('`') && part.endsWith('`')) {
      return (
        <code key={key} className="rounded bg-surface-sunk px-1 py-0.5 font-mono text-code text-ink">
          {part.slice(1, -1)}
        </code>
      )
    }
    if (MATH_TOKEN.test(part)) {
      const body = mathBody(part)
      // A dollar amount is not notation. Left exactly as written when it is
      // not, rather than italicised and mangled into symbols.
      return looksLikeMath(body) ? renderMath(body, key) : part
    }
    if (part.startsWith('*') && part.endsWith('*')) {
      return <em key={key}>{part.slice(1, -1)}</em>
    }
    return part
  })
}

/**
 * One line of generated text with its inline markup resolved, and no block
 * wrapper — for list items and captions, where a `<p>` would fight the layout.
 */
export function Inline({ children }) {
  if (typeof children !== 'string') return children ?? null
  return <>{renderInline(children, 'i')}</>
}

const BULLET = /^\s*(?:[-–—*•]|\d+[.)])\s+/

/**
 * Long-form generated prose, set to be read rather than skimmed.
 *
 * A 900-word synthesis was previously one `whitespace-pre-wrap` block in muted
 * grey — technically all there, but a wall no one reads. Paragraphs are split
 * on blank lines (falling back to single newlines, which is what most models
 * actually emit), and any run of list-looking lines becomes a real list.
 */
export function Prose({ children, className, size = 'md', serif = false, measure = true }) {
  if (typeof children !== 'string' || !children.trim()) return null

  const text = children.replace(/\r\n/g, '\n').trim()
  const blocks = (text.includes('\n\n') ? text.split(/\n{2,}/) : text.split(/\n/))
    .map((b) => b.trim())
    .filter(Boolean)

  // The serif is the system's document voice — the face paper titles are set
  // in. A thousand words of Inter at 15px is a UI label stretched to article
  // length; the serif carries the distance, and the extra leading and slightly
  // darker ink are what make a long read comfortable rather than merely legible.
  const sizing = serif
    ? 'font-serif text-[1.0625rem] leading-[1.8] text-ink/90'
    : size === 'lg'
      ? 'text-base leading-[1.75]'
      : 'text-[0.9375rem] leading-[1.7]'

  return (
    <div
      className={cx(
        // `measure={false}` for callers that have already constrained the line
        // length themselves — doubling the cap leaves dead space inside a box.
        measure && 'max-w-prose',
        'space-y-4 text-ink-muted',
        sizing,
        className,
      )}
    >
      {blocks.map((block, i) => {
        const lines = block.split('\n')
        if (lines.length > 1 && lines.every((l) => BULLET.test(l))) {
          return (
            <ul key={i} className="spine space-y-2">
              {lines.map((line, j) => (
                <li key={j} className="spine-node">
                  {renderInline(line.replace(BULLET, ''), `${i}-${j}`)}
                </li>
              ))}
            </ul>
          )
        }
        // A markdown heading the model emitted despite being asked not to.
        const heading = block.match(/^#{1,4}\s+(.*)$/)
        if (heading) {
          return (
            <h4 key={i} className="pt-2 text-sm font-semibold text-ink">
              {renderInline(heading[1], String(i))}
            </h4>
          )
        }
        return <p key={i}>{renderInline(block, String(i))}</p>
      })}
    </div>
  )
}

/* ── Tabs ───────────────────────────────────────────────────────────────── */

export function Tabs({ tabs, value, onChange, className }) {
  return (
    <div
      role="tablist"
      className={cx(
        'flex gap-1 border-b border-line',
        // Bleeds to the viewport edge on narrow screens so the row scrolls as a
        // full-width strip — a tab clipped by the page gutter reads as the end
        // of the list, and the last tabs are never found.
        'no-scrollbar -mx-4 overflow-x-auto px-4 sm:mx-0 sm:px-0',
        className,
      )}
    >
      {tabs.map((tab) => {
        const active = tab.id === value
        return (
          <button
            key={tab.id}
            role="tab"
            type="button"
            aria-selected={active}
            onClick={() => onChange(tab.id)}
            className={cx(
              'relative whitespace-nowrap px-3 py-2.5 text-sm font-medium',
              'transition-colors duration-fast ease-out',
              active ? 'text-ink' : 'text-ink-muted hover:text-ink',
            )}
          >
            {tab.label}
            {tab.count != null && (
              <span className="ml-1.5 font-mono tabular text-code text-ink-faint">
                {tab.count}
              </span>
            )}
            {active && (
              <span className="absolute inset-x-0 -bottom-px h-0.5 rounded-full bg-accent" />
            )}
          </button>
        )
      })}
    </div>
  )
}
