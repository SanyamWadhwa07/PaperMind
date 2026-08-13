import { useState } from 'react'
import { Link, useNavigate, useLocation } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { useToast } from '../contexts/ToastContext'
import { Mail, Lock } from 'lucide-react'
import {
  Button,
  Card,
  CardBody,
  ErrorState,
  Eyebrow,
  Field,
  Input,
} from '../components/ui/primitives'

export default function LoginPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const { login } = useAuth()
  const toast = useToast()

  const [formData, setFormData] = useState({
    email: '',
    password: ''
  })
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const from = location.state?.from?.pathname || '/dashboard'

  const handleChange = (e) => {
    setFormData({
      ...formData,
      [e.target.name]: e.target.value
    })
    setError('')
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')

    if (!formData.email || !formData.password) {
      setError('Email and password are required')
      return
    }

    setLoading(true)

    const result = await login(formData.email, formData.password)

    if (result.success) {
      toast.success('Logged in successfully!')
      navigate(from, { replace: true })
    } else {
      setError(result.error)
      toast.error(result.error || 'Login failed')
    }

    setLoading(false)
  }

  return (
    <div className="mx-auto flex min-h-[70vh] max-w-md flex-col justify-center py-12">
      <div className="animate-rise">
        <header className="text-center">
          <Eyebrow>Sign in</Eyebrow>
          {/* Serif, like the papers this account holds. */}
          <h1 className="mt-2 font-serif text-display-sm text-ink">
            Welcome back
          </h1>
          <p className="mt-2 text-sm text-ink-muted">
            Your library and summaries are where you left them.
          </p>
        </header>

        <Card className="mt-8">
          <CardBody>
            <form className="space-y-4" onSubmit={handleSubmit} noValidate>
              {error && <ErrorState title="Could not sign in" message={error} />}

              <Field label="Email address" htmlFor="email">
                <div className="relative">
                  <Mail
                    className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-faint"
                    aria-hidden="true"
                  />
                  <Input
                    id="email"
                    type="email"
                    name="email"
                    autoComplete="email"
                    value={formData.email}
                    onChange={handleChange}
                    className="pl-9"
                    placeholder="you@university.edu"
                    invalid={Boolean(error)}
                    required
                    autoFocus
                  />
                </div>
              </Field>

              <Field label="Password" htmlFor="password">
                <div className="relative">
                  <Lock
                    className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-faint"
                    aria-hidden="true"
                  />
                  <Input
                    id="password"
                    type="password"
                    name="password"
                    autoComplete="current-password"
                    value={formData.password}
                    onChange={handleChange}
                    className="pl-9"
                    placeholder="••••••••"
                    invalid={Boolean(error)}
                    required
                  />
                </div>
              </Field>

              <div className="flex justify-end">
                <Link
                  to="/forgot-password"
                  className="text-sm text-accent hover:underline"
                >
                  Forgot password?
                </Link>
              </div>

              <Button type="submit" size="lg" className="w-full" loading={loading}>
                {loading ? 'Signing in…' : 'Sign in'}
              </Button>
            </form>
          </CardBody>
        </Card>

        <p className="mt-6 text-center text-sm text-ink-muted">
          Don&apos;t have an account?{' '}
          <Link to="/signup" className="font-medium text-accent hover:underline">
            Create one
          </Link>
        </p>
      </div>
    </div>
  )
}
