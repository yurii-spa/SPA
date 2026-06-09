import type { Protocol } from '../types'

interface Props {
  protocols: Protocol[]
}

function fmt(v: number | null, decimals = 2, suffix = '') {
  if (v === null || v === undefined) return '—'
  return `${v.toFixed(decimals)}${suffix}`
}

function fmtTVL(v: number | null) {
  if (v === null) return '—'
  if (v >= 1e9) return `$${(v / 1e9).toFixed(2)}B`
  if (v >= 1e6) return `$${(v / 1e6).toFixed(1)}M`
  return `$${v.toFixed(0)}`
}

export function Protocols({ protocols }: Props) {
  return (
    <div className="card">
      <div className="card-title">Protocol Whitelist — Latest APY</div>
      <table className="data-table">
        <thead>
          <tr>
            <th>Protocol</th>
            <th>Asset</th>
            <th>Tier</th>
            <th style={{ textAlign: 'right' }}>APY Total</th>
            <th style={{ textAlign: 'right' }}>Base</th>
            <th style={{ textAlign: 'right' }}>Reward</th>
            <th style={{ textAlign: 'right' }}>TVL</th>
            <th style={{ textAlign: 'right' }}>Last Snapshot</th>
          </tr>
        </thead>
        <tbody>
          {protocols.map((p) => (
            <tr key={p.key} style={{ opacity: p.is_active ? 1 : 0.45 }}>
              <td style={{ fontWeight: 500 }}>{p.protocol}</td>
              <td style={{ color: '#555' }}>{p.asset}</td>
              <td>
                <span className={`tier-badge tier-${p.tier.toLowerCase()}`}>
                  {p.tier}
                </span>
              </td>
              <td
                style={{
                  textAlign: 'right',
                  fontWeight: 600,
                  color: p.apy_total ? (p.apy_total >= 3 ? '#3B6D11' : '#555') : '#aaa',
                }}
              >
                {fmt(p.apy_total, 2, '%')}
              </td>
              <td style={{ textAlign: 'right', color: '#777' }}>
                {fmt(p.apy_base, 2, '%')}
              </td>
              <td style={{ textAlign: 'right', color: '#777' }}>
                {fmt(p.apy_reward, 2, '%')}
              </td>
              <td style={{ textAlign: 'right', color: '#555' }}>
                {fmtTVL(p.tvl_usd)}
              </td>
              <td style={{ textAlign: 'right', color: '#aaa', fontSize: 11 }}>
                {p.last_snapshot ? p.last_snapshot.slice(0, 16).replace('T', ' ') : '—'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
