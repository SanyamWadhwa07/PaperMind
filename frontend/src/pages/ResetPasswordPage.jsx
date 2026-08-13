import { useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { CheckCircle2 } from 'lucide-react'
import toast from 'react-hot-toast'
import { auth } from '../lib/api'
import { Button, Card, CardBody, Field, Input } from '../components/ui/primitives'

/** Mirrors the server-side policy so the user sees problems before submitting. */
const RULES = [
  { test: (v) => v.length >= 8, label: 'At least 8 characters' },
  { test: (v) => /[A-Z]/.test(v), label: 'One uppercase letter' },
  { test: (v) => /[a-z]/.test(v), label: 'One lowercase letter' },
  { test: (v) => /\d/.test(v), label: 'One number' },
]

export default function ResetPasswordPage() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const token = params.get('token') || ''

  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  const unmet = RULES.filter((rule) => !rule.test(password))
  const mismatch = confirm.length > 0 && confirm !== password
  const canSubmit = token && !unmet.length && !mismatch && confirm.length > 0

  const onSubmit = async (event) => {
    event.preventDefault()
    setError('')
    setSubmitting(true)
    try {
      await auth.resetPassword(token, password)
      toast.success('Password updated. Sign in with your new password.')
      navigate('/login', { replace: true })
    } catch (err) {
      setError(err.message)
    } finally {
      setSubmitting(false)
    }
  }

  if (!token) {
    return (
      <div className="mx-auto max-w-md py-12">
        <Card>
          <CardBody className="text-center">
            <h1 className="text-lg font-semibold text-ink">This link is incomplete</h1>
            <p className="mt-2 text-sm text-ink-muted">
              The reset link is missing its token. Request a new one to continue.
            </p>
            <Button to="/forgot-password" className="mt-5">
              Request a new link
            </Button>
          </CardBody>
        </Card>
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-md py-12">
      <Card>
        <CardBody>
          <h1 className="text-lg font-semibold text-ink">Choose a new password</h1>

          <form onSubmit={onSubmit} className="mt-6 space-y-4">
            <Field label="New password" htmlFor="password">
              <Input
                id="password"
                type="password"
                autoComplete="new-password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </Field>

            {password.length > 0 && (
              <ul className="space-y-1">
                {RULES.map((rule) => {
                  const met = rule.test(password)
                  return (
                    <li
                      key={rule.label}
                      className={`flex items-center gap-1.5 text-xs ${
                        met ? 'text-success' : 'text-ink-faint'
                      }`}
                    >
                      <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" />
                      {rule.label}
                    </li>
                  )
                })}
              </ul>
            )}

            <Field
              label="Confirm password"
              htmlFor="confirm"
              error={mismatch ? 'Passwords do not match' : error}
            >
              <Input
                id="confirm"
                type="password"
                autoComplete="new-password"
                required
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                invalid={mismatch}
              />
            </Field>

            <Button
              type="submit"
              className="w-full"
              loading={submitting}
              disabled={!canSubmit}
            >
              Update password
            </Button>
          </form>

          <Link to="/login" className="mt-5 inline-block text-sm text-accent hover:underline">
            Back to sign in
          </Link>
        </CardBody>
      </Card>
    </div>
  )
}
