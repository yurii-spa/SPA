import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from 'recharts'
import { Card, CardHeader, CardTitle, CardContent } from './ui/Card.jsx'
import { num, fmtUsd, fmtDate } from '../lib/format.js'

function ChartTooltip({ active, payload, label }) {
  if (!active || !payload || !payload.length) return null
  const equity = payload[0].value
  return (
    <div className="rounded-lg border border-card-border bg-bg px-3 py-2 text-xs shadow-lg">
      <div className="text-text-muted">{fmtDate(label)}</div>
      <div className="mt-0.5 font-semibold text-accent tabular-nums">
        {fmtUsd(equity)}
      </div>
    </div>
  )
}

export default function EquityCurve({ data = [] }) {
  const points = data.map((d) => ({
    date: d.date,
    equity: num(d.equity_usd),
  }))

  const equities = points.map((p) => p.equity)
  const min = equities.length ? Math.min(...equities) : 0
  const max = equities.length ? Math.max(...equities) : 1
  const pad = (max - min) * 0.15 || max * 0.02 || 1

  return (
    <Card>
      <CardHeader>
        <CardTitle>Equity Curve</CardTitle>
        <span className="text-xs text-text-muted">{points.length} days</span>
      </CardHeader>
      <CardContent className="pt-2">
        {points.length === 0 ? (
          <div className="flex h-64 items-center justify-center text-sm text-text-muted">
            No equity history yet
          </div>
        ) : (
          <div className="h-64 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart
                data={points}
                margin={{ top: 8, right: 8, left: 0, bottom: 0 }}
              >
                <defs>
                  <linearGradient id="equityFill" x1="0" y1="0" x2="0" y2="1">
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
                  fill="url(#equityFill)"
                  dot={false}
                  activeDot={{ r: 4, fill: '#00d4aa', stroke: '#0f0f0f' }}
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
