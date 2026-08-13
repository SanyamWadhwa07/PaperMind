import { Navigate, useLocation } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { Spinner } from './ui/primitives'

export default function ProtectedRoute({ children }) {
  const { isAuthenticated, loading } = useAuth()
  const location = useLocation()

  // Redirecting before the session check finishes would bounce a signed-in
  // user to the login page on every hard refresh.
  if (loading) {
    return (
      <div className="flex min-h-[50vh] items-center justify-center text-ink-faint">
        <Spinner size="lg" />
        <span className="sr-only">Checking your session</span>
      </div>
    )
  }

  if (!isAuthenticated) {
    // Carry the intended destination so login can return the user to it.
    const next = encodeURIComponent(location.pathname + location.search)
    return <Navigate to={`/login?next=${next}`} replace />
  }

  return children
}
