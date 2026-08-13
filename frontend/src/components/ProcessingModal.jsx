import { X } from 'lucide-react'
import { Button, ErrorState, Eyebrow, Spinner } from './ui/primitives'

export default function ProcessingModal({ status, onClose }) {
  if (!status) return null

  const done = status.status === 'completed'

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 p-4 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-labelledby="processing-title"
    >
      {/* Scale-fade entrance, per the motion system: arrival without excitement. */}
      <div className="animate-scale-fade w-full max-w-md rounded-lg border border-line bg-surface shadow-lg">
        <div className="flex items-start justify-between gap-4 border-b border-line px-6 py-4">
          <div>
            <Eyebrow className="block">Pipeline</Eyebrow>
            <h3 id="processing-title" className="mt-1 text-base font-semibold text-ink">
              Processing paper
            </h3>
          </div>
          {done && (
            <Button variant="ghost" size="icon" onClick={onClose} aria-label="Close">
              <X className="h-4 w-4" />
            </Button>
          )}
        </div>

        <div className="space-y-4 p-6">
          <div
            className="h-1 overflow-hidden rounded-full bg-surface-sunk"
            role="progressbar"
            aria-valuenow={status.progress}
            aria-valuemin={0}
            aria-valuemax={100}
          >
            <div
              className="h-full rounded-full bg-accent transition-[width] duration-slow ease-out"
              style={{ width: `${status.progress}%` }}
            />
          </div>

          <div className="flex items-center justify-between gap-3">
            <div className="flex min-w-0 items-center gap-2.5">
              {status.status === 'processing' && (
                <Spinner size="sm" className="shrink-0 text-accent" />
              )}
              <span className="truncate text-sm text-ink">{status.message}</span>
            </div>
            <span className="shrink-0 font-mono tabular text-caption text-ink-faint">
              {status.progress}%
            </span>
          </div>

          {status.status === 'error' && (
            <ErrorState title="Processing failed" message={status.error} />
          )}
        </div>
      </div>
    </div>
  )
}
