import { Card, CardHeader, CardTitle, CardContent } from './ui/Card.jsx'
import Badge from './ui/Badge.jsx'
import { num, fmtUsd, fmtPct } from '../lib/format.js'

const TIER_TONE = {
  T1: 'positive',
  T2: 'accent',
  'T3-SPEC': 'warning',
}

function prettyProtocol(p) {
  if (!p) return '—'
  return p
    .split('_')
    .map((w) => (w.length <= 2 ? w.toUpperCase() : w[0].toUpperCase() + w.slice(1)))
    .join(' ')
}

export default function PositionsTable({ positions = [] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Positions</CardTitle>
        <span className="text-xs text-text-muted">{positions.length} active</span>
      </CardHeader>
      <CardContent className="pt-3">
        {positions.length === 0 ? (
          <div className="py-8 text-center text-sm text-text-muted">
            No open positions
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-card-border text-left text-xs uppercase tracking-wide text-text-muted">
                  <th className="pb-2 pr-3 font-medium">Protocol</th>
                  <th className="pb-2 pr-3 font-medium">Tier</th>
                  <th className="pb-2 pr-3 text-right font-medium">Allocation</th>
                  <th className="pb-2 pr-3 text-right font-medium">Weight</th>
                  <th className="pb-2 text-right font-medium">APY</th>
                </tr>
              </thead>
              <tbody>
                {positions.map((p) => (
                  <tr
                    key={p.protocol}
                    className="border-b border-card-border/50 last:border-0"
                  >
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
  )
}
