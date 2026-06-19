import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client.js'
import { useAuth } from '../auth/AuthContext.jsx'
import { Card, CardHeader, CardTitle, CardContent } from '../components/ui/Card.jsx'
import Badge from '../components/ui/Badge.jsx'
import Button from '../components/ui/Button.jsx'
import Spinner from '../components/ui/Spinner.jsx'
import { fmtDateTime } from '../lib/format.js'

export default function AccountPage() {
  const { logout, role } = useAuth()
  const queryClient = useQueryClient()
  const [loggingOut, setLoggingOut] = useState(false)
  const [editMode, setEditMode] = useState(false)
  const [displayName, setDisplayName] = useState('')
  const [telegramHandle, setTelegramHandle] = useState('')

  const profile = useQuery({
    queryKey: ['profile'],
    queryFn: () => api.get('/users/me'),
    onSuccess: (data) => {
      setDisplayName(data.display_name || '')
      setTelegramHandle(data.telegram_handle || '')
    },
  })

  const updateProfile = useMutation({
    mutationFn: (body) => api.put('/users/me', body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['profile'] })
      setEditMode(false)
    },
  })

  const user = profile.data

  function handleStartEdit() {
    setDisplayName(user?.display_name || '')
    setTelegramHandle(user?.telegram_handle || '')
    setEditMode(true)
  }

  function handleSave() {
    updateProfile.mutate({
      display_name: displayName,
      telegram_handle: telegramHandle,
    })
  }

  async function handleLogout() {
    setLoggingOut(true)
    try {
      await logout()
    } finally {
      setLoggingOut(false)
    }
  }

  if (profile.isLoading) {
    return (
      <div className="flex h-72 items-center justify-center">
        <Spinner size={32} />
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-xl space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Account</CardTitle>
          <Badge tone="muted">{user?.role || role}</Badge>
        </CardHeader>
        <CardContent className="space-y-4 pt-4">
          <div>
            <label className="text-xs font-medium uppercase tracking-wide text-text-muted">
              Username
            </label>
            <div className="mt-1 text-sm text-text-main">{user?.username || '—'}</div>
          </div>

          <div>
            <label className="text-xs font-medium uppercase tracking-wide text-text-muted">
              Email
            </label>
            <div className="mt-1 text-sm text-text-main">{user?.email || '—'}</div>
          </div>

          <div>
            <label className="text-xs font-medium uppercase tracking-wide text-text-muted">
              Display Name
            </label>
            {editMode ? (
              <input
                type="text"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                className="mt-1 w-full rounded-lg border border-card-border bg-bg px-3 py-2 text-sm text-text-main focus:border-accent focus:outline-none"
                placeholder="Your display name"
              />
            ) : (
              <div className="mt-1 text-sm text-text-main">
                {user?.display_name || <span className="text-text-muted">Not set</span>}
              </div>
            )}
          </div>

          <div>
            <label className="text-xs font-medium uppercase tracking-wide text-text-muted">
              Telegram
            </label>
            {editMode ? (
              <input
                type="text"
                value={telegramHandle}
                onChange={(e) => setTelegramHandle(e.target.value)}
                className="mt-1 w-full rounded-lg border border-card-border bg-bg px-3 py-2 text-sm text-text-main focus:border-accent focus:outline-none"
                placeholder="@handle"
              />
            ) : (
              <div className="mt-1 text-sm text-text-main">
                {user?.telegram_handle || <span className="text-text-muted">Not set</span>}
              </div>
            )}
          </div>

          <div>
            <label className="text-xs font-medium uppercase tracking-wide text-text-muted">
              Status
            </label>
            <div className="mt-1">
              <Badge tone={user?.is_active ? 'positive' : 'negative'}>
                {user?.is_active ? 'Active' : 'Inactive'}
              </Badge>
            </div>
          </div>

          <div>
            <label className="text-xs font-medium uppercase tracking-wide text-text-muted">
              Last Login
            </label>
            <div className="mt-1 text-sm text-text-muted">
              {user?.last_login ? fmtDateTime(user.last_login) : 'Never recorded'}
            </div>
          </div>

          <div className="flex gap-3 pt-2">
            {editMode ? (
              <>
                <Button onClick={handleSave} disabled={updateProfile.isPending}>
                  {updateProfile.isPending ? <Spinner size={14} /> : 'Save'}
                </Button>
                <Button variant="outline" onClick={() => setEditMode(false)}>
                  Cancel
                </Button>
              </>
            ) : (
              <Button variant="outline" onClick={handleStartEdit}>
                Edit Profile
              </Button>
            )}
          </div>

          {updateProfile.isError && (
            <div className="rounded-lg border border-negative/30 bg-negative/10 px-3 py-2 text-xs text-negative">
              {updateProfile.error?.message || 'Failed to update profile'}
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardContent className="py-4">
          <Button
            variant="outline"
            className="w-full border-negative/30 text-negative hover:bg-negative/10"
            onClick={handleLogout}
            disabled={loggingOut}
          >
            {loggingOut ? <Spinner size={14} /> : 'Logout'}
          </Button>
        </CardContent>
      </Card>
    </div>
  )
}
