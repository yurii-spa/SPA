import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts'
import type { StrategyPoint } from '../types'

interface Props {
  data: StrategyPoint[]
}

function formatTime(ts: string) {
  return ts.slice(5, 16).replace('T', ' ')
}

function formatPnL(v: number) {
  return `${v >= 0 ? '+' : ''}$${v.toFixed(2)}`
}

export function APYChart({ data }: Props) {
  if (data.length < 2) {
    return (
      <div className="card">
        <div className="card-title">Portfolio History</div>
        <div style={{ color: '#aaa', fontSize: 13, textAlign: 'center', padding: '32px 0' }}>
          Not enough data yet (need ≥ 2 snapshots)
        </div>
      </div>
    )
  }

  const chartData = data.map((d) => ({
    ts: formatTime(d.timestamp),
    pnl: parseFloat(d.total_pnl_usd.toFixed(4)),
    apy: d.current_apy ? parseFloat(d.current_apy.toFixed(2)) : null,
    deployed: parseFloat(((d.deployed_capital_usd / d.total_capital_usd) * 100).toFixed(1)),
  }))

  return (
    <div className="card">
      <div className="card-title">Portfolio History</div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        {/* PnL Chart */}
        <div>
          <div style={{ fontSize: 11, color: '#888', marginBottom: 8, fontWeight: 600, letterSpacing: '0.06em' }}>
            UNREALIZED PnL (USD)
          </div>
          <ResponsiveContainer width="100%" height={180}>
            <LineChart data={chartData} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
              <XAxis
                dataKey="ts"
                tick={{ fontSize: 10, fill: '#aaa' }}
                tickLine={false}
                axisLine={false}
              />
              <YAxis
                tick={{ fontSize: 10, fill: '#aaa' }}
                tickLine={false}
                axisLine={false}
                tickFormatter={(v) => `$${v}`}
              />
              <Tooltip
                formatter={(v: number) => [formatPnL(v), 'PnL']}
                contentStyle={{ fontSize: 12, border: '0.5px solid #ddd', borderRadius: 6 }}
              />
              <Line
                type="monotone"
                dataKey="pnl"
                stroke="#1D9E75"
                strokeWidth={2}
                dot={false}
                activeDot={{ r: 4 }}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>

        {/* Deployed % chart */}
        <div>
          <div style={{ fontSize: 11, color: '#888', marginBottom: 8, fontWeight: 600, letterSpacing: '0.06em' }}>
            DEPLOYED CAPITAL (%)
          </div>
          <ResponsiveContainer width="100%" height={180}>
            <LineChart data={chartData} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
              <XAxis
                dataKey="ts"
                tick={{ fontSize: 10, fill: '#aaa' }}
                tickLine={false}
                axisLine={false}
              />
              <YAxis
                tick={{ fontSize: 10, fill: '#aaa' }}
                tickLine={false}
                axisLine={false}
                domain={[0, 100]}
                tickFormatter={(v) => `${v}%`}
              />
              <Tooltip
                formatter={(v: number) => [`${v}%`, 'Deployed']}
                contentStyle={{ fontSize: 12, border: '0.5px solid #ddd', borderRadius: 6 }}
              />
              <Line
                type="monotone"
                dataKey="deployed"
                stroke="#185FA5"
                strokeWidth={2}
                dot={false}
                activeDot={{ r: 4 }}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  )
}
