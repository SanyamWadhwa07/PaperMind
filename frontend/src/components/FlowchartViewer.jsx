import { useEffect, useRef, useState } from 'react'
import mermaid from 'mermaid'
import { ExternalLink, GitBranch } from 'lucide-react'
import { useTheme } from '../contexts/ThemeContext'
import {
  Button,
  Card,
  EmptyState,
  ErrorState,
  Eyebrow,
  Skeleton,
} from './ui/primitives'

/** Resolve a token to a concrete colour for mermaid's theme variables. */
function readToken(name) {
  if (typeof window === 'undefined') return '#000'
  const raw = getComputedStyle(document.documentElement)
    .getPropertyValue(`--${name}`)
    .trim()
  return raw ? `rgb(${raw})` : '#000'
}

export default function FlowchartViewer({ flowchart }) {
  const chartRef = useRef(null)
  const [renderError, setRenderError] = useState(null)
  const [isRendering, setIsRendering] = useState(false)
  const { theme } = useTheme()

  useEffect(() => {
    if (!flowchart || !chartRef.current) return

    const renderChart = async () => {
      try {
        setIsRendering(true)
        setRenderError(null)

        // Clear previous content
        const container = chartRef.current
        container.innerHTML = ''

        // Mermaid draws with its own palette unless told otherwise, so the
        // theme variables are wired to the same tokens as the rest of the app.
        mermaid.initialize({
          startOnLoad: false,
          theme: 'base',
          securityLevel: 'loose',
          fontFamily: 'Inter Variable, Inter, system-ui, sans-serif',
          themeVariables: {
            background: readToken('surface'),
            primaryColor: readToken('surface-sunk'),
            primaryTextColor: readToken('ink'),
            primaryBorderColor: readToken('border-strong'),
            lineColor: readToken('border-strong'),
            secondaryColor: readToken('stage-3'),
            tertiaryColor: readToken('stage-2'),
            fontSize: '13px',
          },
          flowchart: {
            useMaxWidth: true,
            htmlLabels: true,
          },
        })

        // Generate unique ID
        const chartId = `mermaid-chart-${Date.now()}`

        // Render the chart - mermaid.render returns the SVG string
        const { svg } = await mermaid.render(chartId, flowchart)

        // Insert the SVG into the container
        if (container && svg) {
          container.innerHTML = svg
        }
      } catch (error) {
        console.error('Mermaid rendering error:', error)
        setRenderError(error?.message || 'Failed to render flowchart')
      } finally {
        setIsRendering(false)
      }
    }

    renderChart()
  }, [flowchart, theme])

  if (!flowchart) {
    return (
      <EmptyState
        icon={GitBranch}
        title="No methodology flowchart"
        description="PaperMind draws a flowchart when the methodology describes steps in sequence, such as an algorithm or a numbered procedure. This paper's methodology is either very short or written as continuous prose."
      />
    )
  }

  return (
    <div className="space-y-4">
      {isRendering ? (
        <Skeleton className="h-72 w-full" />
      ) : renderError ? (
        <ErrorState
          title="Could not render the flowchart"
          message={`${renderError}. The Mermaid source is below, and the live editor will point at the exact parse error.`}
        />
      ) : (
        <Card>
          <div className="flex items-center gap-2 border-b border-line px-6 py-3.5">
            <GitBranch className="h-4 w-4 text-ink-faint" aria-hidden="true" />
            <Eyebrow>Methodology</Eyebrow>
          </div>
          <div ref={chartRef} className="min-h-[300px] overflow-x-auto p-8" />
        </Card>
      )}

      <details className="group rounded-lg border border-line bg-surface">
        <summary className="cursor-pointer list-none px-5 py-3 text-sm font-medium text-ink-muted transition-colors duration-fast ease-out hover:text-ink">
          Mermaid source
        </summary>
        <div className="border-t border-line p-4">
          <pre className="overflow-x-auto rounded bg-surface-sunk p-4 font-mono text-code text-ink-muted">
            <code>{flowchart}</code>
          </pre>
        </div>
      </details>

      <Button
        variant="secondary"
        size="sm"
        href={`https://mermaid.live/edit#pako:${encodeURIComponent(flowchart || '')}`}
        target="_blank"
        rel="noopener noreferrer"
      >
        <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
        Open in Mermaid Live
      </Button>
    </div>
  )
}
