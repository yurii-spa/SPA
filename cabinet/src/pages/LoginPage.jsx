import { useState } from 'react'
import { useNavigate, useLocation, Navigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext.jsx'
import { Card } from '../components/ui/Card.jsx'
import Button from '../components/ui/Button.jsx'
import Spinner from '../components/ui/Spinner.jsx'

function Logo() {
  return (
    <div className="flex items-center gap-2.5">
      <svg width="34" height="34" viewBox="0 0 32 32" aria-hidden>
        <rect width="32" height="32" rx="7" fill="#1a1a1a" stroke="#2a2a2a" />
        <path
          d="M9 21c0-3 2.2-4 4.6-4.6C16 15.8 18 15 18 13c0-1.6-1.4-2.6-3.4-2.6-1.9 0-3.3.9-3.8 2.4"
          fill="none"
          stroke="#00d4aa"
          strokeWidth="2.4"
          strokeLinecap="round"
        />
        <circle cx="22" cy="11" r="2" fill="#00d4aa" />
      </svg>
      <div className="leading-tight">
        <div className="text-base font-bold text-text-main">SPA</div>
        <div className="text-[11px] text-text-muted">Investor Cabinet</div>
      </div>
    </div>
  )
}

export default function LoginPage() {
  const { login, isAuthenticated, isLoading } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const from = location.state?.from || '/dashboard'

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  if (isAuthenticated) {
    return <Navigate to={from} replace />
  }

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')
    setSubmitting(true)
    try {
      await login(email.trim(), password)
      navigate(from, { replace: true })
    } catch (err) {
      setError(err?.message || 'Login failed. Check your credentials.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-bg px-4">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex justify-center">
          <Logo />
        </div>
        <Card className="p-7">
          <h1 className="text-xl font-bold text-text-main">Welcome back</h1>
          <p className="mt-1 text-sm text-text-muted">
            Sign in to the Family Fund portal
          </p>

          <form onSubmit={handleSubmit} className="mt-6 space-y-4">
            <div>
              <label
                htmlFor="email"
                className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-text-muted"
              >
                Email
              </label>
              <input
                id="email"
                type="text"
                autoComplete="username"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                placeholder="you@example.com"
                className="w-full rounded-xl border border-card-border bg-bg px-3.5 py-2.5 text-sm
                  text-text-main placeholder:text-text-muted/60 focus:border-accent focus:outline-none
                  focus:ring-2 focus:ring-accent/30"
              />
            </div>

            <div>
              <label
                htmlFor="password"
                className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-text-muted"
              >
                Password
              </label>
              <input
                id="password"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                placeholder="••••••••"
                className="w-full rounded-xl border border-card-border bg-bg px-3.5 py-2.5 text-sm
                  text-text-main placeholder:text-text-muted/60 focus:border-accent focus:outline-none
                  focus:ring-2 focus:ring-accent/30"
              />
            </div>

            {error ? (
              <div className="rounded-xl border border-negative/30 bg-negative/10 px-3.5 py-2.5 text-sm text-negative">
                {error}
              </div>
            ) : null}

            <Button
              type="submit"
              size="lg"
              className="w-full"
              disabled={submitting || isLoading}
            >
              {submitting ? <Spinner size={18} className="text-bg" /> : 'Sign in'}
            </Button>
          </form>
        </Card>

        <p className="mt-6 text-center text-xs text-text-muted">
          SPA — Smart Passive Aggregator · Family Fund
        </p>
      </div>
    </div>
  )
}
