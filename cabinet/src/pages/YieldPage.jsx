import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client.js'
import { Card, CardHeader, CardTitle, CardContent } from '../components/ui/Card.jsx'
import Spinner from '../components/ui/Spinner.jsx'
import { num, fmtUsd, fmtPct, fmtSignedUsd, fmtDate, toneForValue } from '../lib/format.js'
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from 'recharts'

const PERIODS = [
  { label: '7D', days: 7 },
  { label: '14D', days: 14 },
  { label: '30D', days: 30 },
  { label: 'All', days: 365 },
]

function ChartTooltip({ active, payload, label }) {
  if (!active || !payload || !payload.length) return null
  return (
    <div className="rounded-lg border border-card-border bg-bg px-3 py-2 text-xs shadow-lg">
      <div className="text-text-muted">{fmtDate(label)}</div>
      <div className="mt-0.5 font-semibold text-accent tabular-nums">
        {fmtUsd(payload[0].value)}
      </div>
    </div>
  )
}

function exportCSV(days) {
  const header = 'Date,Equity USD,Daily Yield USD,Daily Return %,APY %'
  const rows = days.map(
    (d) =>
      `${d.date},${num(d.equity_usd)},${d.daily_yield_usd != null ? num(d.daily_yield_usd) : ''},${d.daily_return_pct != null ? num(d.daily_return_pct) : ''},${d.apy_today_pct != null ? num(d.apy_today_pct) : ''}`
  )
  const csv = [header, ...rows].join('\n')
  const blob = new Blob([csv], { type: 'text/csv' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = 'yield_history.csv'
  a.click()
  URL.revokeObjectURL(url)
}

export default function YieldPage() {
  const [period, setPeriod] = useState(30)

  const history = useQuery({
    queryKey: ['yield-history', period],
    queryFn: () => api.get(`/yield/history?days=${period}`),
  })

  const days = history.data?.days || []
  const points = days.map((d) => ({
    date: d.date,
    equity: num(d.equity_usd),
  }))

  const equities = points.map((p) => p.equity)
  const min = equities.length ? Math.min(...equities) : 0
  const max = equities.length ? Math.max(...equities) : 1
  const pad = (max - min) * 0.15 || max * 0.02 || 1

  const rows = [...days].reverse()

  if (history.isLoading) {
    return (
      <div className="flex h-72 items-center justify-center">
        <Spinner size={32} />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Equity Curve */}
      <Card>
        <CardHeader>
          <CardTitle>Equity Curve</CardTitle>
          <div className="flex items-center gap-3">
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
            <button
              onClick={() => exportCSV(days)}
              className="text-xs font-medium text-accent hover:underline"
            >
              Export CSV
            </button>
          </div>
        </CardHeader>
        <CardContent className="pt-2">
          {points.length === 0 ? (
            <div className="flex h-64 items-center justify-center text-sm text-text-muted">
              No equity history yet
            </div>
          ) : (
            <div className="h-72 w-full">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart
                  data={points}
                  margin={{ top: 8, right: 8, left: 0, bottom: 0 }}
                >
                  <defs>
                    <linearGradient id="yieldEquityFill" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#00d4aa" stopOpacity={0.35} />
                      <stop offset="100%" stopColor="#00d4aa" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid stroke="#2a2a2a" vertical={false} />
                  <XAxis
                    dataKey="date"
                    tickFormatter={fmtDate}
                    stroke="#888888"
                    fontSize={11}
                    tickLine={false}
                    axisLine={{ stroke: '#2a2a2a' }}
                    minTickGap={24}
                  />
                  <YAxis
                    domain={[min - pad, max + pad]}
                    stroke="#888888"
                    fontSize={11}
                    tickLine={false}
                    axisLine={false}
                    width={64}
                    tickFormatter={(v) => fmtUsd(v, { decimals: 0, compact: true })}
                  />
                  <Tooltip content={<ChartTooltip />} />
                  <Area
                    type="monotone"
                    dataKey="equity"
                    stroke="#00d4aa"
                    strokeWidth={2}
                    fill="url(#yieldEquityFill)"
                    dot={false}
                    activeDot={{ r: 4, fill: '#00d4aa', stroke: '#0f0f0f' }}
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Yield History Table */}
      <Card>
        <CardHeader>
          <CardTitle>Yield History</CardTitle>
          <span className="text-xs text-text-muted">{rows.length} days</span>
        </CardHeader>
        <CardContent className="pt-3">
          {rows.length === 0 ? (
            <div className="py-8 text-center text-sm text-text-muted">
              No yield records yet
            </div>
          ) : (
            <div className="overflow-x-auto max-h-96 overflow-y-auto">
              <table className="w-full text-sm">
                <thead className="sticky top-0 bg-card">
                  <tr className="border-b border-card-border text-left text-xs uppercase tracking-wide text-text-muted">
                    <th className="pb-2 pr-3 font-medium">Date</th>
                    <th className="pb-2 pr-3 text-right font-medium">Equity</th>
                    <th className="pb-2 pr-3 text-right font-medium">Yield</th>
                    <th className="pb-2 pr-3 text-right font-medium">Return</th>
                    <th className="pb-2 text-right font-medium">APY</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((d) => (
                    <tr
                      key={d.date}
                      className="border-b border-card-border/50 last:border-0"
                    >
                      <td className="py-2.5 pr-3 text-text-main">{fmtDate(d.date)}</td>
                      <td className="py-2.5 pr-3 text-right tabular-nums text-text-main">
                        {fmtUsd(d.equity_usd)}
                      </td>
                      <td
                        className={`py-2.5 pr-3 text-right tabular-nums ${
                          toneForValue(d.daily_yield_usd) === 'positive'
                            ? 'text-positive'
                            : toneForValue(d.daily_yield_usd) === 'negative'
                              ? 'text-negative'
                              : 'text-text-muted'
                        }`}
                      >
                        {d.daily_yield_usd != null
                          ? fmtSignedUsd(d.daily_yield_usd)
                          : '—'}
                      </td>
                      <td
                        className={`py-2.5 pr-3 text-right tabular-nums ${
                          toneForValue(d.daily_return_pct) === 'positive'
                            ? 'text-positive'
                            : toneForValue(d.daily_return_pct) === 'negative'
                              ? 'text-negative'
                              : 'text-text-muted'
                        }`}
                      >
                        {d.daily_return_pct != null
                          ? fmtPct(d.daily_return_pct, { sign: true })
                          : '—'}
                      </td>
                      <td className="py-2.5 text-right tabular-nums text-accent">
                        {d.apy_today_pct != null ? fmtPct(d.apy_today_pct) : '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
