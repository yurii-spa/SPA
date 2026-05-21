import { useState, useEffect, useCallback } from 'react'
import { api } from './api'
import { Portfolio } from './components/Portfolio'
import { Positions } from './components/Positions'
import { Protocols } from './components/Protocols'
import { BusStats } from './components/BusStats'
import { APYChart } from './components/APYChart'
import { RunButton } from './components/RunButton'
import { Trades } from './components/Trades'
import type {
  StatusResponse,
  Protocol,
  Trade,
  BusStats as BusStatsType,
  StrategyPoint,
} from './types'
import './App.css'

type Tab = 'dashboard' | 'protocols' | 'trades' | 'bus'

interface AppState {
  status: StatusResponse | null
  protocols: Protocol[]
  trades: Trade[]
  busStats: BusStatsType
  strategyHistory: StrategyPoint[]
  serverOnline: boolean
  loading: boolean
  lastRefresh: string | null
  error: string | null
}

const INITIAL: AppState = {
  status: null,
  protocols: [],
  trades: [],
  busStats: {},
  strategyHistory: [],
  serverOnline: false,
  loading: true,
  lastRefresh: null,
  error: null,
}

const TAB_LABELS: Record<Tab, string> = {
  dashboard: '📊 Dashboard',
  protocols: '🔗 Protocols',
  trades:    '📋 Trades',
  bus:       '📨 Message Bus',
}

export default function App() {
  const [tab, setTab] = useState<Tab>('dashboard')
  const [state, setState] = useState<AppState>(INITIAL)
  const [refreshing, setRefreshing] = useState(false)

  const refresh = useCallback(async (silent = false) => {
    if (!silent) setRefreshing(true)
    try {
      const [status, protocols, trades, busStats, strategyHistory] = await Promise.all([
        api.status(),
        api.protocols(),
        api.trades(),
        api.busStats(),
        api.strategyState(48),
      ])
      setState({
        status,
        protocols,
        trades,
        busStats,
        strategyHistory,
        serverOnline: true,
        loading: false,
        lastRefresh: new Date().toISOString(),
        error: null,
      })
    } catch (e) {
      setState((prev) => ({
        ...prev,
        serverOnline: false,
        loading: false,
        error:
          e instanceof Error
            ? e.message
            : 'Cannot connect to API server (localhost:8000)',
      }))
    } finally {
      if (!silent) setRefreshing(false)
    }
  }, [])

  // Initial load
  useEffect(() => {
    refresh()
  }, [refresh])

  // Auto-refresh every 30s
  useEffect(() => {
    const id = setInterval(() => refresh(true), 30_000)
    return () => clearInterval(id)
  }, [refresh])

  const { status, protocols, trades, busStats, strategyHistory, serverOnline, loading, error, lastRefresh } =
    state

  return (
    <div className="app">
      {/* ── Header ── */}
      <header className="header">
        <div>
          <h1>Smart Passive Aggregator</h1>
          <p className="subtitle">
            {serverOnline ? (
              <>
                <span className="dot-green" />
                {api.isStatic ? 'Static mode' : 'API Online'} ·{' '}
                {lastRefresh ? `Updated ${lastRefresh.slice(11, 19)} UTC` : 'Loading…'}
              </>
            ) : (
              <>
                <span className="dot-red" /> Offline — start{' '}
                <code>uvicorn api.server:app --port 8000</code>
              </>
            )}
          </p>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <RunButton onComplete={() => setTimeout(() => refresh(true), 500)} />
          <button
            className="btn-ghost"
            onClick={() => refresh()}
            disabled={refreshing}
          >
            {refreshing ? '⟳' : '↻'} Refresh
          </button>
        </div>
      </header>

      {/* ── Tabs ── */}
      <div className="tabs">
        {(Object.keys(TAB_LABELS) as Tab[]).map((t) => (
          <button
            key={t}
            className={`tab-btn ${tab === t ? 'active' : ''}`}
            onClick={() => setTab(t)}
          >
            {TAB_LABELS[t]}
          </button>
        ))}
      </div>

      {/* ── Content ── */}
      <main className="main">
        {/* Error banner */}
        {error && !loading && (
          <div className="error-banner">⚠ {error}</div>
        )}

        {/* Loading */}
        {loading && (
          <div style={{ textAlign: 'center', padding: '60px 0', color: '#aaa' }}>
            Loading…
          </div>
        )}

        {/* Dashboard Tab */}
        {!loading && tab === 'dashboard' && status && (
          <div>
            <Portfolio
              portfolio={status.portfolio}
              clock={status.paper_trading}
              risk={status.risk}
            />
            <div style={{ marginTop: 14 }}>
              <Positions positions={status.positions} />
            </div>
            <div style={{ marginTop: 14 }}>
              <APYChart data={strategyHistory} />
            </div>
          </div>
        )}

        {/* Protocols Tab */}
        {!loading && tab === 'protocols' && (
          <Protocols protocols={protocols} />
        )}

        {/* Trades Tab */}
        {!loading && tab === 'trades' && (
          <Trades trades={trades} />
        )}

        {/* Bus Tab */}
        {!loading && tab === 'bus' && (
          <BusStats stats={busStats} />
        )}
      </main>

      {/* ── Footer ── */}
      <footer className="footer">
        SPA v0.4 · Paper Trading · strategy paper-v1 ·{' '}
        <a
          href="https://yurii-spa.github.io/SPA/"
          style={{ color: '#185FA5' }}
          target="_blank"
          rel="noreferrer"
        >
          Dashboard
        </a>
      </footer>
    </div>
  )
}
