import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client.js'
import { useAuth } from '../auth/AuthContext.jsx'
import { Card, CardHeader, CardTitle, CardContent } from '../components/ui/Card.jsx'
import Badge from '../components/ui/Badge.jsx'
import Button from '../components/ui/Button.jsx'
import Spinner from '../components/ui/Spinner.jsx'
import { fmtUsd, fmtDateTime } from '../lib/format.js'

const ROLE_TONE = {
  owner: 'warning',
  admin: 'accent',
  investor: 'positive',
  readonly: 'muted',
}

function UserRow({ user, onEdit, onDeactivate, currentUserId }) {
  const isSelf = user.username === currentUserId || user.id === currentUserId
  return (
    <tr className="border-b border-card-border/50 last:border-0">
      <td className="py-3 pr-3 font-medium text-text-main">
        {user.display_name || user.username}
        {isSelf && <span className="ml-1 text-xs text-text-muted">(you)</span>}
      </td>
      <td className="py-3 pr-3 text-sm text-text-muted">{user.email}</td>
      <td className="py-3 pr-3">
        <Badge tone={ROLE_TONE[user.role] || 'muted'}>{user.role}</Badge>
      </td>
      <td className="py-3 pr-3">
        <Badge tone={user.is_active ? 'positive' : 'negative'}>
          {user.is_active ? 'Active' : 'Inactive'}
        </Badge>
      </td>
      <td className="py-3 text-right">
        <div className="flex justify-end gap-2">
          <button
            onClick={() => onEdit(user)}
            className="text-xs font-medium text-accent hover:underline"
          >
            Edit
          </button>
          {!isSelf && user.is_active && (
            <button
              onClick={() => onDeactivate(user)}
              className="text-xs font-medium text-negative hover:underline"
            >
              Deactivate
            </button>
          )}
        </div>
      </td>
    </tr>
  )
}

function CreateUserForm({ onCreated }) {
  const [username, setUsername] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [role, setRole] = useState('investor')
  const [displayName, setDisplayName] = useState('')

  const create = useMutation({
    mutationFn: (body) => api.post('/admin/users', body),
    onSuccess: () => {
      setUsername('')
      setEmail('')
      setPassword('')
      setRole('investor')
      setDisplayName('')
      onCreated()
    },
  })

  function handleSubmit(e) {
    e.preventDefault()
    create.mutate({ username, email, password, role, display_name: displayName })
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-3">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <input
          type="text"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          placeholder="Username"
          required
          className="rounded-lg border border-card-border bg-bg px-3 py-2 text-sm text-text-main focus:border-accent focus:outline-none"
        />
        <input
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="Email"
          required
          className="rounded-lg border border-card-border bg-bg px-3 py-2 text-sm text-text-main focus:border-accent focus:outline-none"
        />
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="Password"
          required
          minLength={6}
          className="rounded-lg border border-card-border bg-bg px-3 py-2 text-sm text-text-main focus:border-accent focus:outline-none"
        />
        <select
          value={role}
          onChange={(e) => setRole(e.target.value)}
          className="rounded-lg border border-card-border bg-bg px-3 py-2 text-sm text-text-main focus:border-accent focus:outline-none"
        >
          <option value="investor">Investor</option>
          <option value="readonly">Read-only</option>
          <option value="admin">Admin</option>
        </select>
      </div>
      <input
        type="text"
        value={displayName}
        onChange={(e) => setDisplayName(e.target.value)}
        placeholder="Display Name (optional)"
        className="w-full rounded-lg border border-card-border bg-bg px-3 py-2 text-sm text-text-main focus:border-accent focus:outline-none"
      />
      <div className="flex items-center gap-3">
        <Button type="submit" disabled={create.isPending}>
          {create.isPending ? <Spinner size={14} /> : 'Create User'}
        </Button>
        {create.isError && (
          <span className="text-xs text-negative">{create.error?.message}</span>
        )}
      </div>
    </form>
  )
}

function EditUserModal({ user, onClose, onSaved }) {
  const [role, setRole] = useState(user.role)
  const [email, setEmail] = useState(user.email)
  const [displayName, setDisplayName] = useState(user.display_name || '')
  const [telegram, setTelegram] = useState(user.telegram_handle || '')

  const update = useMutation({
    mutationFn: (body) => api.put(`/admin/users/${user.id || user.username}`, body),
    onSuccess: () => {
      onSaved()
      onClose()
    },
  })

  function handleSubmit(e) {
    e.preventDefault()
    update.mutate({ role, email, display_name: displayName, telegram_handle: telegram })
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="mx-4 w-full max-w-md rounded-2xl border border-card-border bg-card p-6">
        <h3 className="text-sm font-semibold text-text-main">
          Edit: {user.display_name || user.username}
        </h3>
        <form onSubmit={handleSubmit} className="mt-4 space-y-3">
          <div>
            <label className="text-xs text-text-muted">Role</label>
            <select
              value={role}
              onChange={(e) => setRole(e.target.value)}
              className="mt-1 w-full rounded-lg border border-card-border bg-bg px-3 py-2 text-sm text-text-main focus:border-accent focus:outline-none"
            >
              <option value="owner">Owner</option>
              <option value="admin">Admin</option>
              <option value="investor">Investor</option>
              <option value="readonly">Read-only</option>
            </select>
          </div>
          <div>
            <label className="text-xs text-text-muted">Email</label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="mt-1 w-full rounded-lg border border-card-border bg-bg px-3 py-2 text-sm text-text-main focus:border-accent focus:outline-none"
            />
          </div>
          <div>
            <label className="text-xs text-text-muted">Display Name</label>
            <input
              type="text"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              className="mt-1 w-full rounded-lg border border-card-border bg-bg px-3 py-2 text-sm text-text-main focus:border-accent focus:outline-none"
            />
          </div>
          <div>
            <label className="text-xs text-text-muted">Telegram</label>
            <input
              type="text"
              value={telegram}
              onChange={(e) => setTelegram(e.target.value)}
              placeholder="@handle"
              className="mt-1 w-full rounded-lg border border-card-border bg-bg px-3 py-2 text-sm text-text-main focus:border-accent focus:outline-none"
            />
          </div>
          <div className="flex gap-3 pt-2">
            <Button type="submit" disabled={update.isPending}>
              {update.isPending ? <Spinner size={14} /> : 'Save'}
            </Button>
            <Button variant="outline" onClick={onClose} type="button">
              Cancel
            </Button>
          </div>
          {update.isError && (
            <div className="text-xs text-negative">{update.error?.message}</div>
          )}
        </form>
      </div>
    </div>
  )
}

export default function AdminPage() {
  const { role: currentRole } = useAuth()
  const queryClient = useQueryClient()
  const [editingUser, setEditingUser] = useState(null)

  const users = useQuery({
    queryKey: ['admin-users'],
    queryFn: () => api.get('/admin/users'),
  })

  const system = useQuery({
    queryKey: ['admin-system'],
    queryFn: () => api.get('/admin/system'),
    staleTime: 30_000,
  })

  const deactivate = useMutation({
    mutationFn: (userId) => api.del(`/admin/users/${userId}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['admin-users'] }),
  })

  function handleDeactivate(user) {
    if (window.confirm(`Deactivate user "${user.display_name || user.username}"?`)) {
      deactivate.mutate(user.id || user.username)
    }
  }

  if (currentRole !== 'owner' && currentRole !== 'admin') {
    return (
      <div className="flex h-72 items-center justify-center text-text-muted">
        Access denied. Admin role required.
      </div>
    )
  }

  const sys = system.data || {}
  const health = sys.cycle_health || {}
  const golive = sys.golive_status || {}

  return (
    <div className="space-y-6">
      {/* System Status */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Card className="p-5">
          <div className="text-xs font-medium uppercase tracking-wide text-text-muted">
            Sprint
          </div>
          <div className="mt-2 text-lg font-bold text-text-main">
            {sys.sprint_current || '—'}
          </div>
        </Card>
        <Card className="p-5">
          <div className="text-xs font-medium uppercase tracking-wide text-text-muted">
            Done Count
          </div>
          <div className="mt-2 text-lg font-bold text-accent">
            {sys.kanban_done_count || 0}
          </div>
        </Card>
        <Card className="p-5">
          <div className="text-xs font-medium uppercase tracking-wide text-text-muted">
            Go-Live
          </div>
          <div className="mt-2 flex items-center gap-2">
            <Badge tone={golive.ready ? 'positive' : 'warning'}>
              {golive.ready ? 'READY' : 'NOT READY'}
            </Badge>
            <span className="text-sm text-text-muted">
              {golive.passed}/{golive.total}
            </span>
          </div>
        </Card>
        <Card className="p-5">
          <div className="text-xs font-medium uppercase tracking-wide text-text-muted">
            Current Equity
          </div>
          <div className="mt-2 text-lg font-bold text-text-main">
            {fmtUsd(health.current_equity)}
          </div>
          <div className="mt-1 text-xs text-text-muted">
            {health.days_running || 0} days &middot; APY {health.apy_today_pct || '0'}%
          </div>
        </Card>
      </div>

      {/* Users Table */}
      <Card>
        <CardHeader>
          <CardTitle>Users</CardTitle>
          <span className="text-xs text-text-muted">
            {(users.data || []).length} total
          </span>
        </CardHeader>
        <CardContent className="pt-3">
          {users.isLoading ? (
            <div className="flex h-32 items-center justify-center">
              <Spinner size={24} />
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-card-border text-left text-xs uppercase tracking-wide text-text-muted">
                    <th className="pb-2 pr-3 font-medium">Name</th>
                    <th className="pb-2 pr-3 font-medium">Email</th>
                    <th className="pb-2 pr-3 font-medium">Role</th>
                    <th className="pb-2 pr-3 font-medium">Status</th>
                    <th className="pb-2 text-right font-medium">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {(users.data || []).map((u) => (
                    <UserRow
                      key={u.id || u.username}
                      user={u}
                      currentUserId={null}
                      onEdit={setEditingUser}
                      onDeactivate={handleDeactivate}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Create User Form */}
      <Card>
        <CardHeader>
          <CardTitle>Add User</CardTitle>
        </CardHeader>
        <CardContent className="pt-3">
          <CreateUserForm
            onCreated={() =>
              queryClient.invalidateQueries({ queryKey: ['admin-users'] })
            }
          />
        </CardContent>
      </Card>

      {editingUser && (
        <EditUserModal
          user={editingUser}
          onClose={() => setEditingUser(null)}
          onSaved={() =>
            queryClient.invalidateQueries({ queryKey: ['admin-users'] })
          }
        />
      )}
    </div>
  )
}
