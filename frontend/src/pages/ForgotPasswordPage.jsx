import { useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowLeft, MailCheck } from 'lucide-react'
import { auth } from '../lib/api'
import { Button, Card, CardBody, Field, Input } from '../components/ui/primitives'

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [sent, setSent] = useState(false)
  const [devToken, setDevToken] = useState(null)
  const [error, setError] = useState('')

  const onSubmit = async (event) => {
    event.preventDefault()
    setError('')
    setSubmitting(true)
    try {
      const data = await auth.forgotPassword(email)
      setSent(true)
      // Outside production the API returns the token directly, since no mail
      // provider is wired up yet.
      if (data.reset_token) setDevToken(data.reset_token)
    } catch (err) {
      setError(err.message)
    } finally {
      setSubmitting(false)
    }
  }

  if (sent) {
    return (
      <div className="mx-auto max-w-md py-12">
        <Card>
          <CardBody className="text-center">
            <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-lg bg-accent-soft">
              <MailCheck className="h-6 w-6 text-accent" aria-hidden="true" />
            </div>
            <h1 className="text-lg font-semibold text-ink">Check your email</h1>
            <p className="mt-2 text-sm text-ink-muted">
              If an account exists for {email}, a reset link is on its way.
            </p>

            {devToken && (
              <div className="mt-5 rounded border border-warning/30 bg-warning-soft p-3 text-left">
                <p className="text-xs font-medium text-warning">
                  Development mode: no mail provider is configured
                </p>
                <p className="mt-1 break-all font-mono text-xs text-ink-muted">
                  {devToken}
                </p>
                <Button
                  size="sm"
                  variant="secondary"
                  className="mt-2"
                  to={`/reset-password?token=${devToken}`}
                >
                  Continue to reset
                </Button>
              </div>
            )}

            <Link
              to="/login"
              className="mt-6 inline-flex items-center gap-1.5 text-sm text-accent hover:underline"
            >
              <ArrowLeft className="h-4 w-4" />
              Back to sign in
            </Link>
          </CardBody>
        </Card>
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-md py-12">
      <Card>
        <CardBody>
          <h1 className="text-lg font-semibold text-ink">Reset your password</h1>
          <p className="mt-1.5 text-sm text-ink-muted">
            Enter the address you signed up with and we&apos;ll send a reset link.
          </p>

          <form onSubmit={onSubmit} className="mt-6 space-y-4">
            <Field label="Email" htmlFor="email" error={error}>
              <Input
                id="email"
                type="email"
                autoComplete="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@university.edu"
                invalid={Boolean(error)}
              />
            </Field>

            <Button type="submit" className="w-full" loading={submitting}>
              Send reset link
            </Button>
          </form>

          <Link
            to="/login"
            className="mt-5 inline-flex items-center gap-1.5 text-sm text-accent hover:underline"
          >
            <ArrowLeft className="h-4 w-4" />
            Back to sign in
          </Link>
        </CardBody>
      </Card>
    </div>
  )
}
