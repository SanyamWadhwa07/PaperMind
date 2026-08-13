import { Suspense, lazy } from 'react'
import { Route, Routes } from 'react-router-dom'
import Layout from './components/Layout'
import ProtectedRoute from './components/ProtectedRoute'
import ErrorBoundary from './components/ErrorBoundary'
import { Spinner } from './components/ui/primitives'

// Routes are split so the initial load ships only the landing page and the
// shell. The heavy visualisation dependencies (vis-network, mermaid, charts)
// stay out of the entry bundle until a route that needs them is opened.
const HomePage = lazy(() => import('./pages/HomePage'))
const LoginPage = lazy(() => import('./pages/LoginPage'))
const SignupPage = lazy(() => import('./pages/SignupPage'))
const ForgotPasswordPage = lazy(() => import('./pages/ForgotPasswordPage'))
const ResetPasswordPage = lazy(() => import('./pages/ResetPasswordPage'))
const DashboardPage = lazy(() => import('./pages/DashboardPage'))
const SummaryPage = lazy(() => import('./pages/SummaryPage'))
const BatchPage = lazy(() => import('./pages/BatchPage'))
const ProfilePage = lazy(() => import('./pages/ProfilePage'))
const TimelinePage = lazy(() => import('./pages/TimelinePage'))
const ExplorePage = lazy(() => import('./pages/ExplorePage'))
const DiscoverPage = lazy(() => import('./pages/DiscoverPage'))
const NotFoundPage = lazy(() => import('./pages/NotFoundPage'))

function RouteFallback() {
  return (
    <div className="flex min-h-[50vh] items-center justify-center text-ink-faint">
      <Spinner size="lg" />
      <span className="sr-only">Loading</span>
    </div>
  )
}

/** Wrap a page in the auth guard. */
const guarded = (element) => <ProtectedRoute>{element}</ProtectedRoute>

export default function App() {
  return (
    <Layout>
      <ErrorBoundary>
        <Suspense fallback={<RouteFallback />}>
          <Routes>
            <Route path="/" element={<HomePage />} />
            <Route path="/login" element={<LoginPage />} />
            <Route path="/signup" element={<SignupPage />} />
            <Route path="/forgot-password" element={<ForgotPasswordPage />} />
            <Route path="/reset-password" element={<ResetPasswordPage />} />

            {/* Every route below reads user-scoped data and must be signed in.
                /summary and /batch were previously left open, so they rendered
                a broken shell for anonymous visitors instead of a login prompt. */}
            <Route path="/summary/:id" element={guarded(<SummaryPage />)} />
            <Route path="/batch" element={guarded(<BatchPage />)} />
            <Route path="/dashboard" element={guarded(<DashboardPage />)} />
            <Route path="/profile" element={guarded(<ProfilePage />)} />
            <Route path="/timeline" element={guarded(<TimelinePage />)} />
            <Route path="/explore" element={guarded(<ExplorePage />)} />
            <Route path="/discover" element={guarded(<DiscoverPage />)} />

            <Route path="*" element={<NotFoundPage />} />
          </Routes>
        </Suspense>
      </ErrorBoundary>
    </Layout>
  )
}
