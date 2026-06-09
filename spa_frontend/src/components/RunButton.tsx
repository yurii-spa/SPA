import { useState } from 'react'
import { api } from '../api'
import type { RunResponse } from '../types'

interface Props {
  onComplete?: (result: RunResponse) => void
}

export function RunButton({ onComplete }: Props) {
  const [status, setStatus] = useState<'idle' | 'running' | 'ok' | 'error'>('idle')
  const [lastResult, setLastResult] = useState<RunResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  // В статическом режиме (GitHub Pages) — данные обновляются GitHub Actions каждые 4ч
  if (api.isStatic) {
    return (
      <span style={{ fontSize: 12, color: '#888' }}>
        ⏰ Auto-updated every 4h via GitHub Actions
      </span>
    )
  }

  async function handleRun() {
    setStatus('running')
    setError(null)
    try {
      const result = await api.run()
      setLastResult(result)
      setStatus('ok')
      onComplete?.(result)
      setTimeout(() => setStatus('idle'), 4000)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setStatus('error')
      setTimeout(() => setStatus('idle'), 6000)
    }
  }

  const label = {
    idle: '▶ Run Iteration',
    running: '⏳ Running…',
    ok: '✓ Done',
    error: '✗ Error',
  }[status]

  const bg = {
    idle: '#185FA5',
    running: '#888',
    ok: '#3B6D11',
    error: '#b91c1c',
  }[status]

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
      <button
        onClick={handleRun}
        disabled={status === 'running'}
        style={{
          background: bg,
          color: '#fff',
          border: 'none',
          borderRadius: 8,
          padding: '9px 20px',
          fontSize: 13,
          fontWeight: 500,
          cursor: status === 'running' ? 'not-allowed' : 'pointer',
          transition: 'background 0.2s',
          letterSpacing: '0.02em',
        }}
      >
        {label}
      </button>

      {status === 'ok' && lastResult && (
        <span style={{ fontSize: 12, color: '#3B6D11' }}>
          iter #{lastResult.iteration} · {lastResult.signals} signals ·{' '}
          {lastResult.executions} executions ·{' '}
          {lastResult.fetch_ok ? 'live data' : 'cached data'}
          {lastResult.blocked ? ' · ⚠ BLOCKED' : ''}
        </span>
      )}

      {status === 'error' && error && (
        <span style={{ fontSize: 12, color: '#b91c1c' }}>{error}</span>
      )}
    </div>
  )
}
