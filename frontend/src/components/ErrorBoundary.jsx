import { Component } from 'react'
import { AlertTriangle } from 'lucide-react'
import { Button } from './ui/primitives'

/**
 * Catches render-time crashes so one broken page does not blank the whole app.
 * Errors during data fetching are handled by the API client instead.
 */
export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { error: null }
  }

  static getDerivedStateFromError(error) {
    return { error }
  }

  componentDidCatch(error, info) {
    console.error('Render error:', error, info)
  }

  handleReset = () => {
    this.setState({ error: null })
  }

  render() {
    const { error } = this.state
    if (!error) return this.props.children

    return (
      <div className="mx-auto max-w-lg rounded-lg border border-line bg-surface p-8 text-center">
        <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-lg bg-danger-soft">
          <AlertTriangle className="h-6 w-6 text-danger" aria-hidden="true" />
        </div>
        <h2 className="text-lg font-semibold text-ink">This page stopped working</h2>
        <p className="mt-2 text-sm text-ink-muted">
          The error has been logged. Reloading usually clears it.
        </p>

        {/* The stack is for the developer running locally, not the end user. */}
        {import.meta.env.DEV && (
          <pre className="mt-4 max-h-48 overflow-auto rounded border border-line bg-surface-sunk p-3 text-left font-mono text-xs text-ink-muted">
            {error.stack || String(error)}
          </pre>
        )}

        <div className="mt-6 flex justify-center gap-2">
          <Button onClick={() => window.location.reload()}>Reload page</Button>
          <Button variant="secondary" onClick={this.handleReset}>
            Dismiss
          </Button>
        </div>
      </div>
    )
  }
}
