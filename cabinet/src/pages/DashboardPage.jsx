import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client.js'
import Spinner from '../components/ui/Spinner.jsx'
import KpiCard from '../components/KpiCard.jsx'
import EquityCurve from '../components/EquityCurve.jsx'
import PositionsTable from '../components/PositionsTable.jsx'
import YieldTable from '../components/YieldTable.jsx'
import SystemStatus from '../components/SystemStatus.jsx'
import {
  num,
  fmtUsd,
  fmtPct,
  fmtSignedUsd,
  toneForValue,
} from '../lib/format.js'

function useDashboardData() {
  const portfolio = useQuery({
    queryKey: ['portfolio'],
    queryFn: () => api.get('/portfolio'),
  })
  const performance = useQuery({
    queryKey: ['performance'],
    queryFn: () => api.get('/portfolio/performance'),
  })
  const history = useQuery({
    queryKey: ['yield-history', 30],
    queryFn: () => api.get('/yield/history?days=30'),
  })
  const recent = useQuery({
    queryKey: ['yield-history', 7],
    queryFn: () => api.get('/yield/history?days=7'),
  })
  const health = useQuery({
    queryKey: ['health'],
    queryFn: () => api.get('/health'),
    staleTime: 60_000,
  })
  return { portfolio, performance, history, recent, health }
}

function annualizedReturn(totalReturnPct, daysRunning) {
  const tr = num(totalReturnPct)
  const days = num(daysRunning)
  if (days >= 1) return (tr / days) * 365
  return tr
}

export default function DashboardPage() {
  const { portfolio, performance, history, recent, health } = useDashboardData()

  const isInitialLoading =
    portfolio.isLoading || performance.isLoading || history.isLoading

  const p = portfolio.data || {}
  const perf = performance.data || {}
  const days = history.data?.days || []
  const recentDays = recent.data?.days || []
  const positions = p.positions || []

  const apy = annualizedReturn(perf.total_return_pct, perf.days_running)

  return (
    <>
      {portfolio.isError ? (
        <div className="mb-6 rounded-xl border border-negative/30 bg-negative/10 px-4 py-3 text-sm text-negative">
          Failed to load portfolio: {portfolio.error?.message}
        </div>
      ) : null}

      {isInitialLoading ? (
        <div className="flex h-72 items-center justify-center">
          <Spinner size={32} />
        </div>
      ) : (
        <div className="space-y-6">
          {/* KPI ROW */}
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-5">
            <KpiCard
              label="Your Balance"
              value={fmtUsd(p.current_equity)}
              subtle={`${fmtUsd(p.deployed_usd)} deployed`}
            />
            <KpiCard
              label="Today's Yield"
              value={fmtSignedUsd(perf.daily_yield_usd)}
              delta={fmtPct(perf.daily_return_pct, { sign: true })}
              deltaTone={toneForValue(perf.daily_return_pct)}
            />
            <KpiCard
              label="Net APY"
              value={fmtPct(apy)}
              delta={`${fmtPct(perf.total_return_pct, { sign: true })} total`}
              deltaTone={toneForValue(perf.total_return_pct)}
            />
            <KpiCard
              label="Active Protocols"
              value={positions.length}
              subtle={
                positions.length
                  ? positions
                      .slice(0, 3)
                      .map((x) => x.tier || '—')
                      .join(' · ')
                  : 'No positions'
              }
            />
            <KpiCard
              label="System Status"
              value={health.data?.status === 'ok' ? 'Online' : 'Offline'}
              delta={
                perf.days_running != null
                  ? `${perf.days_running} days running`
                  : ''
              }
              deltaTone={health.data?.status === 'ok' ? 'positive' : 'negative'}
            />
          </div>

          {/* EQUITY + STATUS */}
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
            <div className="lg:col-span-2">
              <EquityCurve data={days} />
            </div>
            <div>
              <SystemStatus
                health={health.data}
                performance={perf}
                isDemo={p.is_demo}
              />
            </div>
          </div>

          {/* POSITIONS + YIELD */}
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            <PositionsTable positions={positions} />
            <YieldTable days={recentDays} />
          </div>
        </div>
      )}
    </>
  )
}
