import { FileText, ExternalLink } from 'lucide-react'
import { Badge, Button, Card, CardBody, Identifier } from './ui/primitives'

/** Relative age reads faster than a date when scanning a list of results. */
function formatAge(dateString) {
  const date = new Date(dateString)
  const days = Math.ceil(Math.abs(new Date() - date) / (1000 * 60 * 60 * 24))

  if (days < 7) return `${days} day${days > 1 ? 's' : ''} ago`
  if (days < 30) {
    const weeks = Math.floor(days / 7)
    return `${weeks} week${weeks > 1 ? 's' : ''} ago`
  }
  if (days < 365) {
    const months = Math.floor(days / 30)
    return `${months} month${months > 1 ? 's' : ''} ago`
  }
  const years = Math.floor(days / 365)
  return `${years} year${years > 1 ? 's' : ''} ago`
}

export default function PaperCard({ paper, onSummarize, index = 0 }) {
  return (
    <Card interactive style={{ '--i': index }}>
      <CardBody className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0 flex-1 space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            {paper.arxiv_id && <Identifier>{paper.arxiv_id}</Identifier>}
            {paper.primary_category && (
              <Badge tone="outline">{paper.primary_category}</Badge>
            )}
          </div>

          {/* The paper's own voice. */}
          <h4 className="font-serif text-lg leading-snug text-ink">{paper.title}</h4>

          <p className="text-sm text-ink-muted">
            {paper.authors.slice(0, 3).join(', ')}
            {paper.authors.length > 3 && ` +${paper.authors.length - 3} more`}
          </p>

          {paper.summary && (
            <p className="line-clamp-2 text-sm text-ink-muted">{paper.summary}</p>
          )}

          <p className="flex items-center gap-2 pt-0.5 text-caption text-ink-faint">
            <span>{formatAge(paper.published)}</span>
            <span aria-hidden="true">·</span>
            <span className="font-mono tabular">{paper.published.split('T')[0]}</span>
          </p>
        </div>

        <div className="flex shrink-0 items-center gap-2 sm:flex-col sm:items-stretch">
          <Button size="sm" onClick={() => onSummarize(paper)}>
            <FileText className="h-3.5 w-3.5" aria-hidden="true" />
            Summarise
          </Button>
          {paper.pdf_url && (
            <Button
              variant="secondary"
              size="sm"
              href={paper.pdf_url}
              target="_blank"
              rel="noopener noreferrer"
            >
              <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
              PDF
            </Button>
          )}
        </div>
      </CardBody>
    </Card>
  )
}
