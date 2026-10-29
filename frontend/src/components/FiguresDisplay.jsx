import { useState } from 'react'
import { FileImage } from 'lucide-react'
import { Badge, Card, CardBody, EmptyState, ErrorState, Eyebrow } from './ui/primitives'

/**
 * One figure card. Shows the extracted image when the pipeline managed to store
 * it, and degrades to a caption-only card when it didn't — rather than showing a
 * broken image icon.
 */
function FigureCard({ figure, index }) {
  const [imageFailed, setImageFailed] = useState(false)
  const showImage = Boolean(figure.image_url) && !imageFailed

  return (
    <Card interactive>
      <CardBody className="space-y-3">
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-baseline gap-2">
            <span className="font-mono tabular text-sm text-ink">
              {figure.figure_number || `Figure ${index + 1}`}
            </span>
            {figure.page > 0 && (
              <span className="font-mono tabular text-code text-ink-faint">
                p.{figure.page}
              </span>
            )}
          </div>

          {/* Relevance is a ranking, so it reads as a small bar plus the
              number — the bar for scanning, the number for comparing. */}
          {figure.relevance != null && (
            <div className="flex shrink-0 items-center gap-2">
              <div className="h-1 w-12 overflow-hidden rounded-full bg-surface-sunk">
                <div
                  className="h-full rounded-full bg-accent"
                  style={{ width: `${Math.min(figure.relevance, 1) * 100}%` }}
                />
              </div>
              <span className="font-mono tabular text-code text-ink-faint">
                {Math.round(Math.min(figure.relevance, 1) * 100)}%
              </span>
            </div>
          )}
        </div>

        {showImage && (
          <a
            href={figure.image_url}
            target="_blank"
            rel="noreferrer"
            className="block overflow-hidden rounded border border-line bg-surface-sunk"
          >
            <img
              src={figure.image_url}
              alt={figure.caption || `Figure ${index + 1} from the paper`}
              loading="lazy"
              onError={() => setImageFailed(true)}
              className="mx-auto max-h-80 w-auto max-w-full object-contain"
            />
          </a>
        )}

        {/* Captions are the paper's own prose. */}
        <p className="font-serif text-sm leading-relaxed text-ink-muted">
          {figure.caption || 'No caption available'}
        </p>

        {/* What the classifier made of the figure, beyond its caption. */}
        {figure.insight && figure.insight !== figure.caption && (
          <p className="border-t border-line pt-3 text-sm text-ink-muted">
            {figure.insight}
          </p>
        )}

        {figure.figure_type && figure.figure_type !== 'unknown' && (
          <Badge>{figure.figure_type.replace(/_/g, ' ')}</Badge>
        )}
      </CardBody>
    </Card>
  )
}

export default function FiguresDisplay({ figures, pipelineStatus }) {
  if (!figures || figures.length === 0) {
    // Distinguishes "this paper has no figures" from "figure extraction
    // crashed" — the FigureAgent stage in pipeline_status — which previously
    // rendered as the exact same reassuring empty state.
    if (pipelineStatus?.status === 'failed') {
      return (
        <ErrorState
          title="Figure extraction failed"
          message={pipelineStatus.error || 'Something went wrong while pulling figures from this PDF.'}
        />
      )
    }
    return (
      <EmptyState
        icon={FileImage}
        title="No figures detected"
        description="PaperMind found nothing in this PDF that it could read as a figure."
      />
    )
  }

  const withImages = figures.filter((f) => f.image_url).length

  return (
    <div>
      <Eyebrow className="block">
        {figures.length} figure{figures.length === 1 ? '' : 's'}
        {withImages > 0 && ` · ${withImages} with images`}
      </Eyebrow>

      {/* Three across on a wide monitor — figure cards are image-led, so they
          stay legible much narrower than a column of prose does. */}
      <div className="mt-4 grid gap-4 md:grid-cols-2 2xl:grid-cols-3">
        {figures.map((figure, idx) => (
          <FigureCard key={figure.id || idx} figure={figure} index={idx} />
        ))}
      </div>
    </div>
  )
}
