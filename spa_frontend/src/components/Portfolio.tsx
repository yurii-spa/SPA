import type { Portfolio as PortfolioData, PaperTradingClock, RiskInfo } from '../types'

interface Props {
  portfolio: PortfolioData
  clock: PaperTradingClock
  risk: RiskInfo
}

function MetricCard({
  label,
  value,
  sub,
  accent,
}: {
  label: string
  value: string
  sub?: string
  accent?: 'green' | 'red' | 'blue'
}) {
  const color =
    accent === 'green' ? '#3B6D11' : accent === 'red' ? '#b91c1c' : '#1a1a1a'
  return (
    <div className="metric-card">
      <div className="metric-label">{label}</div>
      <div className="metric-value" style={{ color }}>
        {value}
      </div>
      {sub && <div className="metric-sub">{sub}</div>}
    </div>
  )
}

export function Portfolio({ portfolio: p, clock: pt, risk }: Props) {
  const pnlSign = p.total_pnl_usd >= 0 ? '+' : ''
  const pnlAccent: 'green' | 'red' =
    p.total_pnl_usd >= 0 ? 'green' : 'red'
  const clockPct = Math.min(
    (pt.weeks_elapsed / pt.min_weeks_required) * 100,
    100,
  )
  const weeksLeft = Math.max(pt.min_weeks_required - pt.weeks_elapsed, 0)

  return (
    <div>
      {/* ── Metrics row ── */}
      <div className="metrics-grid">
        <MetricCard
          label="Total Capital"
          value={`$${p.total_capital_usd.toLocaleString('en', { maximumFractionDigits: 0 })}`}
          sub="virtual USD"
        />
        <MetricCard
          label="Deployed"
          value={`$${p.deployed_usd.toLocaleString('en', { maximumFractionDigits: 0 })}`}
          sub={`${((1 - p.cash_pct) * 100).toFixed(0)}% · ${p.deployed_usd > 0 ? 'active' : 'idle'}`}
        />
        <MetricCard
          label="Cash Buffer"
          value={`$${p.cash_usd.toLocaleString('en', { maximumFractionDigits: 0 })}`}
          sub={`${(p.cash_pct * 100).toFixed(0)}% · min 5%`}
        />
        <MetricCard
          label="Unrealized PnL"
          value={`${pnlSign}$${Math.abs(p.total_pnl_usd).toFixed(2)}`}
          sub={`drawdown ${(p.total_drawdown_pct * 100).toFixed(2)}%`}
          accent={pnlAccent}
        />
      </div>

      {/* ── Risk + Clock row ── */}
      <div className="two-col" style={{ marginTop: 14 }}>
        {/* Risk Health */}
        <div className="card">
          <div className="card-title">Risk Health</div>
          <div
            className="badge"
            style={{
              background: risk.health_approved ? '#eaf3de' : '#fde8e8',
              color: risk.health_approved ? '#3B6D11' : '#b91c1c',
            }}
          >
            {risk.health_approved ? '✓ All Clear' : '⚠ Alert'}
          </div>
          {risk.violations.map((v, i) => (
            <div key={i} className="alert-row alert-error">
              ✗ {v}
            </div>
          ))}
          {risk.warnings.map((w, i) => (
            <div key={i} className="alert-row alert-warn">
              ⚠ {w}
            </div>
          ))}
          <div className="stat-row">
            <span>VaR 95% (7d)</span>
            <span
              style={{ color: risk.var_breach ? '#b91c1c' : '#3B6D11', fontWeight: 500 }}
            >
              ${risk.var_usd.toFixed(2)} ({risk.var_pct.toFixed(3)}%)
            </span>
          </div>
        </div>

        {/* Paper Trading Clock */}
        <div className="card">
          <div className="card-title">Paper Trading Clock</div>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
            <span style={{ fontSize: 13, color: '#555' }}>
              Week {pt.weeks_elapsed.toFixed(1)} / {pt.min_weeks_required}
            </span>
            <span
              style={{
                fontSize: 12,
                fontWeight: 500,
                color: pt.go_live_ready ? '#3B6D11' : '#BA7517',
              }}
            >
              {pt.go_live_ready ? '✅ Go-Live eligible' : `${weeksLeft.toFixed(1)}w remaining`}
            </span>
          </div>
          <div className="progress-bg">
            <div
              className="progress-fill"
              style={{
                width: `${clockPct}%`,
                background: pt.go_live_ready ? '#3B6D11' : '#1D9E75',
              }}
            />
          </div>
          <div className="stat-row" style={{ marginTop: 10 }}>
            <span>Days elapsed</span>
            <span>{pt.days_elapsed}d</span>
          </div>
          <div className="stat-row">
            <span>First trade</span>
            <span>{pt.first_trade ? pt.first_trade.slice(0, 10) : '—'}</span>
          </div>
          <div className="stat-row">
            <span>Min required</span>
            <span>{pt.min_weeks_required} weeks</span>
          </div>
        </div>
      </div>
    </div>
  )
}
