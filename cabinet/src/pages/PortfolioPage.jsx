import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client.js'
import { useAuth } from '../auth/AuthContext.jsx'
import { Card, CardHeader, CardTitle, CardContent } from '../components/ui/Card.jsx'
import Badge from '../components/ui/Badge.jsx'
import Spinner from '../components/ui/Spinner.jsx'
import { num, fmtUsd, fmtPct } from '../lib/format.js'
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from 'recharts'

const TIER_TONE = {
  T1: 'positive',
  T2: 'accent',
  'T3-SPEC': 'warning',
}

const PERIODS = [
  { label: '7D', days: 7 },
  { label: '14D', days: 14 },
  { label: '30D', days: 30 },
]

function prettyProtocol(p) {
  if (!p) return '—'
  return p
    .split('_')
    .map((w) => (w.length <= 2 ? w.toUpperCase() : w[0].toUpperCase() + w.slice(1)))
    .join(' ')
}

function AttrTooltip({ active, payload }) {
  if (!active || !payload || !payload.length) return null
  const d = payload[0].payload
  return (
    <div className="rounded-lg border border-card-border bg-bg px-3 py-2 text-xs shadow-lg">
      <div className="font-medium text-text-main">{d.label}</div>
      <div className="mt-1 text-accent tabular-nums">{fmtUsd(d.yield_usd)}</div>
      <div className="text-text-muted tabular-nums">APY {fmtPct(d.apy)}</div>
    </div>
  )
}

function exportCSV(positions) {
  const header = 'Protocol,Tier,Allocation USD,Weight %,APY %'
  const rows = positions.map(
    (p) =>
      `${p.protocol},${p.tier || ''},${num(p.allocation_usd)},${num(p.weight_pct)},${p.apy_pct != null ? num(p.apy_pct) : ''}`
  )
  const csv = [header, ...rows].join('\n')
  const blob = new Blob([csv], { type: 'text/csv' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = 'portfolio_positions.csv'
  a.click()
  URL.revokeObjectURL(url)
}

export default function PortfolioPage() {
  const [period, setPeriod] = useState(7)
  const { role } = useAuth()

  const portfolio = useQuery({
    queryKey: ['portfolio'],
    queryFn: () => api.get('/portfolio'),
  })

  const attribution = useQuery({
    queryKey: ['attribution', period],
    queryFn: () => api.get(`/portfolio/attribution?days=${period}`),
  })

  const positions = portfolio.data?.positions || []
  const attrItems = (attribution.data?.items || []).map((it) => ({
    ...it,
    label: prettyProtocol(it.protocol),
    yield_usd: num(it.yield_usd),
    apy: num(it.apy),
  }))

  const sorted = [...positions].sort((a, b) => num(b.allocation_usd) - num(a.allocation_usd))

  if (portfolio.isLoading) {
    return (
      <div className="flex h-72 items-center justify-center">
        <Spinner size={32} />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Positions Table */}
      <Card>
        <CardHeader>
          <CardTitle>All Positions</CardTitle>
          <button
            onClick={() => exportCSV(sorted)}
            className="text-xs font-medium text-accent hover:underline"
          >
            Export CSV
          </button>
        </CardHeader>
        <CardContent className="pt-3">
          {sorted.length === 0 ? (
            <div className="py-8 text-center text-sm text-text-muted">
              No open positions
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-card-border text-left text-xs uppercase tracking-wide text-text-muted">
                    <th className="pb-2 pr-3 font-medium">#</th>
                    <th className="pb-2 pr-3 font-medium">Protocol</th>
                    <th className="pb-2 pr-3 font-medium">Tier</th>
                    <th className="pb-2 pr-3 text-right font-medium">Allocation</th>
                    <th className="pb-2 pr-3 text-right font-medium">Weight</th>
                    <th className="pb-2 text-right font-medium">APY</th>
                  </tr>
                </thead>
                <tbody>
                  {sorted.map((p, i) => (
                    <tr
                      key={p.protocol}
                      className="border-b border-card-border/50 last:border-0"
                    >
                      <td className="py-3 pr-3 text-text-muted">{i + 1}</td>
                      <td className="py-3 pr-3 font-medium text-text-main">
                        {prettyProtocol(p.protocol)}
                      </td>
                      <td className="py-3 pr-3">
                        {p.tier ? (
                          <Badge tone={TIER_TONE[p.tier] || 'muted'}>{p.tier}</Badge>
                        ) : (
                          <span className="text-text-muted">—</span>
                        )}
                      </td>
                      <td className="py-3 pr-3 text-right tabular-nums text-text-main">
                        {fmtUsd(p.allocation_usd)}
                      </td>
                      <td className="py-3 pr-3 text-right tabular-nums text-text-muted">
                        {fmtPct(p.weight_pct, { decimals: 1 })}
                      </td>
                      <td className="py-3 text-right tabular-nums text-accent">
                        {p.apy_pct != null ? fmtPct(p.apy_pct) : '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Yield Attribution Chart */}
      <Card>
        <CardHeader>
          <CardTitle>Yield Attribution</CardTitle>
          <div className="flex gap-1">
            {PERIODS.map((pr) => (
              <button
                key={pr.days}
                onClick={() => setPeriod(pr.days)}
                className={`rounded-lg px-3 py-1 text-xs font-medium transition-colors ${
                  period === pr.days
                    ? 'bg-accent/15 text-accent'
                    : 'text-text-muted hover:text-text-main'
                }`}
              >
                {pr.label}
              </button>
            ))}
          </div>
        </CardHeader>
        <CardContent className="pt-2">
          {attribution.isLoading ? (
            <div className="flex h-64 items-center justify-center">
              <Spinner size={24} />
            </div>
          ) : attrItems.length === 0 ? (
            <div className="flex h-64 items-center justify-center text-sm text-text-muted">
              No attribution data
            </div>
          ) : (
            <div className="h-64 w-full">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart
                  data={attrItems}
                  margin={{ top: 8, right: 8, left: 0, bottom: 0 }}
                >
                  <CartesianGrid stroke="#2a2a2a" vertical={false} />
                  <XAxis
                    dataKey="label"
                    stroke="#888888"
                    fontSize={11}
                    tickLine={false}
                    axisLine={{ stroke: '#2a2a2a' }}
                  />
                  <YAxis
                    stroke="#888888"
                    fontSize={11}
                    tickLine={false}
                    axisLine={false}
                    width={64}
                    tickFormatter={(v) => `$${v}`}
                  />
                  <Tooltip content={<AttrTooltip />} />
                  <Bar
                    dataKey="yield_usd"
                    fill="#00d4aa"
                    radius={[4, 4, 0, 0]}
                    maxBarSize={48}
                  />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
          {attribution.data?.total_yield_usd != null && (
            <div className="mt-3 text-right text-xs text-text-muted">
              Total yield ({period}D): <span className="font-medium text-accent">{fmtUsd(attribution.data.total_yield_usd)}</span>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
