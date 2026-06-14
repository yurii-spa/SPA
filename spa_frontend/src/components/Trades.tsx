import type { Trade } from '../types'

interface Props {
  trades: Trade[]
}

function fmtDate(iso: string | null) {
  if (!iso) return '—'
  return iso.slice(0, 16).replace('T', ' ')
}

const ACTION_COLOR: Record<string, string> = {
  OPEN:      '#185FA5',
  CLOSE:     '#555555',
  REBALANCE: '#BA7517',
}

export function Trades({ trades }: Props) {
  if (trades.length === 0) {
    return (
      <div className="card">
        <div className="card-title">Trade History</div>
        <div style={{ color: '#aaa', fontSize: 13, textAlign: 'center', padding: '24px 0' }}>
          No trades yet
        </div>
      </div>
    )
  }

  const open   = trades.filter((t) => t.timestamp_close === null)
  const closed = trades.filter((t) => t.timestamp_close !== null)

  return (
    <div className="card">
      <div className="card-title">
        Trade History · {open.length} open · {closed.length} closed
      </div>
      <table className="data-table">
        <thead>
          <tr>
            <th>Opened</th>
            <th>Protocol</th>
            <th>Action</th>
            <th style={{ textAlign: 'right' }}>Amount</th>
            <th style={{ textAlign: 'right' }}>APY@Open</th>
            <th style={{ textAlign: 'right' }}>Net APY</th>
            <th style={{ textAlign: 'right' }}>PnL</th>
            <th style={{ textAlign: 'right' }}>Closed</th>
          </tr>
        </thead>
        <tbody>
          {trades.map((t) => {
            const isOpen   = t.timestamp_close === null
            const pnlPos   = (t.pnl_usd ?? 0) >= 0
            const pnlColor = pnlPos ? '#3B6D11' : '#b91c1c'
            const color    = ACTION_COLOR[t.action] ?? '#888'

            return (
              <tr key={t.trade_id} style={{ opacity: isOpen ? 1 : 0.7 }}>
                <td style={{ color: '#888', fontSize: 11, whiteSpace: 'nowrap' }}>
                  {fmtDate(t.timestamp_open)}
                </td>
                <td style={{ fontFamily: 'monospace', fontSize: 11 }}>
                  {t.protocol_key}
                </td>
                <td>
                  <span style={{
                    display: 'inline-block',
                    fontSize: 10,
                    padding: '2px 7px',
                    borderRadius: 4,
                    background: `${color}18`,
                    color,
                    fontWeight: 600,
                    letterSpacing: '0.04em',
                  }}>
                    {t.action}
                  </span>
                </td>
                <td style={{ textAlign: 'right' }}>
                  ${t.amount_usd.toLocaleString('en', { maximumFractionDigits: 0 })}
                </td>
                <td style={{ textAlign: 'right', color: '#777' }}>
                  {t.apy_at_open != null ? `${t.apy_at_open.toFixed(2)}%` : '—'}
                </td>
                <td style={{ textAlign: 'right', color: '#777' }}>
                  {t.net_apy_annualized != null ? `${t.net_apy_annualized.toFixed(2)}%` : '—'}
                </td>
                <td style={{ textAlign: 'right', fontWeight: 500, color: isOpen ? '#aaa' : pnlColor }}>
                  {isOpen
                    ? 'open'
                    : t.pnl_usd != null
                    ? `${pnlPos ? '+' : ''}$${Math.abs(t.pnl_usd).toFixed(4)}`
                    : '—'}
                </td>
                <td style={{ textAlign: 'right', color: '#aaa', fontSize: 11, whiteSpace: 'nowrap' }}>
                  {isOpen ? <span style={{ color: '#185FA5' }}>●</span> : fmtDate(t.timestamp_close)}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
