import { useState } from 'react'
import { NavLink, useLocation } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext.jsx'
import Button from './ui/Button.jsx'
import Badge from './ui/Badge.jsx'
import Spinner from './ui/Spinner.jsx'

const NAV_ITEMS = [
  { to: '/dashboard', label: 'Dashboard' },
  { to: '/portfolio', label: 'Portfolio' },
  { to: '/yield', label: 'Yield' },
  { to: '/account', label: 'Account' },
]

function NavTab({ to, label }) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        `px-3 py-1.5 text-sm font-medium rounded-lg transition-colors ${
          isActive
            ? 'bg-accent/15 text-accent'
            : 'text-text-muted hover:text-text-main hover:bg-card-border/50'
        }`
      }
    >
      {label}
    </NavLink>
  )
}

export default function AppShell({ children }) {
  const { role, logout } = useAuth()
  const [loggingOut, setLoggingOut] = useState(false)

  const isAdmin = role === 'owner' || role === 'admin'

  async function handleLogout() {
    setLoggingOut(true)
    try {
      await logout()
    } finally {
      setLoggingOut(false)
    }
  }

  return (
    <div className="min-h-screen bg-bg">
      <header className="sticky top-0 z-10 border-b border-card-border bg-bg/90 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3.5 sm:px-6">
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2.5">
              <svg width="28" height="28" viewBox="0 0 32 32" aria-hidden>
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
                <div className="text-sm font-bold text-text-main">SPA Cabinet</div>
                <div className="text-[11px] text-text-muted">Family Fund</div>
              </div>
            </div>
            <nav className="hidden items-center gap-1 sm:flex">
              {NAV_ITEMS.map((item) => (
                <NavTab key={item.to} {...item} />
              ))}
              {isAdmin && <NavTab to="/admin" label="Admin" />}
            </nav>
          </div>
          <div className="flex items-center gap-3">
            {role ? <Badge tone="muted">{role}</Badge> : null}
            <Button variant="outline" size="sm" onClick={handleLogout} disabled={loggingOut}>
              {loggingOut ? <Spinner size={14} /> : 'Sign out'}
            </Button>
          </div>
        </div>
        {/* Mobile nav */}
        <div className="flex gap-1 overflow-x-auto px-4 pb-2 sm:hidden">
          {NAV_ITEMS.map((item) => (
            <NavTab key={item.to} {...item} />
          ))}
          {isAdmin && <NavTab to="/admin" label="Admin" />}
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-4 py-6 sm:px-6">{children}</main>
    </div>
  )
}
