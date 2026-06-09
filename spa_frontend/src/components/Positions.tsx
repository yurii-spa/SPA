import type { Position } from '../types'

interface Props {
  positions: Position[]
}

export function Positions({ positions }: Props) {
  if (positions.length === 0) {
    return (
      <div className="card">
        <div className="card-title">Open Positions</div>
        <div style={{ color: '#aaa', fontSize: 13, textAlign: 'center', padding: '20px 0' }}>
          No open positions
        </div>
      </div>
    )
  }

  return (
    <div className="card">
      <div className="card-title">Open Positions ({positions.length})</div>
      <table className="data-table">
        <thead>
          <tr>
            <th>Protocol</th>
            <th>Tier</th>
            <th style={{ textAlign: 'right' }}>Amount</th>
            <th style={{ textAlign: 'right' }}>APY</th>
            <th style={{ textAlign: 'right' }}>PnL</th>
            <th style={{ textAlign: 'right' }}>Days</th>
          </tr>
        </thead>
        <tbody>
          {positions.map((pos) => {
            const pnlColor =
              pos.unrealized_pnl_usd >= 0 ? '#3B6D11' : '#b91c1c'
            const pnlSign = pos.unrealized_pnl_usd >= 0 ? '+' : ''
            return (
              <tr key={pos.protocol_key}>
                <td>
                  <span style={{ fontFamily: 'monospace', fontSize: 12 }}>
                    {pos.protocol_key}
                  </span>
                </td>
                <td>
                  <span
                    className={`tier-badge tier-${pos.tier.toLowerCase()}`}
                  >
                    {pos.tier}
                  </span>
                </td>
                <td style={{ textAlign: 'right' }}>
                  ${pos.amount_usd.toLocaleString('en', { maximumFractionDigits: 0 })}
                </td>
                <td style={{ textAlign: 'right' }}>
                  {pos.current_apy.toFixed(2)}%
                </td>
                <td style={{ textAlign: 'right', color: pnlColor, fontWeight: 500 }}>
                  {pnlSign}${Math.abs(pos.unrealized_pnl_usd).toFixed(4)}
                </td>
                <td style={{ textAlign: 'right', color: '#777' }}>
                  {pos.days_held.toFixed(1)}d
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
