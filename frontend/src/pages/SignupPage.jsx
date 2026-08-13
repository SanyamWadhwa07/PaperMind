import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { useToast } from '../contexts/ToastContext'
import { Mail, Lock, User } from 'lucide-react'
import {
  Button,
  Card,
  CardBody,
  ErrorState,
  Eyebrow,
  Field,
  Input,
} from '../components/ui/primitives'

export default function SignupPage() {
  const navigate = useNavigate()
  const { signup } = useAuth()
  const toast = useToast()

  const [formData, setFormData] = useState({
    fullName: '',
    email: '',
    password: '',
    confirmPassword: ''
  })
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

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

    // Validation
    if (!formData.email || !formData.password || !formData.fullName) {
      setError('All fields are required')
      toast.error('All fields are required')
      return
    }

    if (formData.password !== formData.confirmPassword) {
      setError('Passwords do not match')
      toast.error('Passwords do not match')
      return
    }

    if (formData.password.length < 8) {
      setError('Password must be at least 8 characters')
      toast.error('Password must be at least 8 characters')
      return
    }

    setLoading(true)

    const result = await signup(formData.email, formData.password, formData.fullName)

    if (result.success) {
      toast.success('Account created successfully!')
      navigate('/dashboard')
    } else {
      setError(result.error)
      toast.error(result.error || 'Signup failed')
    }

    setLoading(false)
  }

  return (
    <div className="mx-auto flex min-h-[70vh] max-w-md flex-col justify-center py-12">
      <div className="animate-rise">
        <header className="text-center">
          <Eyebrow>Create account</Eyebrow>
          <h1 className="mt-2 font-serif text-display-sm text-ink">
            Start reading faster
          </h1>
          <p className="mt-2 text-sm text-ink-muted">
            Four levels of summary for every paper you add.
          </p>
        </header>

        <Card className="mt-8">
          <CardBody>
            <form className="space-y-4" onSubmit={handleSubmit} noValidate>
              {error && <ErrorState title="Could not create account" message={error} />}

              <Field label="Full name" htmlFor="fullName">
                <div className="relative">
                  <User
                    className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-faint"
                    aria-hidden="true"
                  />
                  <Input
                    id="fullName"
                    type="text"
                    name="fullName"
                    autoComplete="name"
                    value={formData.fullName}
                    onChange={handleChange}
                    className="pl-9"
                    placeholder="Ada Lovelace"
                    required
                    autoFocus
                  />
                </div>
              </Field>

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
                    required
                  />
                </div>
              </Field>

              <Field
                label="Password"
                htmlFor="password"
                hint="At least 8 characters, with an uppercase letter, a lowercase letter, and a number."
              >
                <div className="relative">
                  <Lock
                    className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-faint"
                    aria-hidden="true"
                  />
                  <Input
                    id="password"
                    type="password"
                    name="password"
                    autoComplete="new-password"
                    value={formData.password}
                    onChange={handleChange}
                    className="pl-9"
                    placeholder="••••••••"
                    required
                  />
                </div>
              </Field>

              <Field label="Confirm password" htmlFor="confirmPassword">
                <div className="relative">
                  <Lock
                    className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-faint"
                    aria-hidden="true"
                  />
                  <Input
                    id="confirmPassword"
                    type="password"
                    name="confirmPassword"
                    autoComplete="new-password"
                    value={formData.confirmPassword}
                    onChange={handleChange}
                    className="pl-9"
                    placeholder="••••••••"
                    required
                  />
                </div>
              </Field>

              <Button type="submit" size="lg" className="w-full" loading={loading}>
                {loading ? 'Creating account…' : 'Create account'}
              </Button>
            </form>
          </CardBody>
        </Card>

        <p className="mt-6 text-center text-sm text-ink-muted">
          Already have an account?{' '}
          <Link to="/login" className="font-medium text-accent hover:underline">
            Sign in
          </Link>
        </p>
      </div>
    </div>
  )
}
