import { Card, CardHeader, CardTitle, CardContent } from './ui/Card.jsx'
import { fmtUsd, fmtPct, fmtSignedUsd, toneForValue, fmtDate } from '../lib/format.js'

export default function YieldTable({ days = [] }) {
  // newest first
  const rows = [...days].reverse()

  return (
    <Card>
      <CardHeader>
        <CardTitle>Recent Yield</CardTitle>
        <span className="text-xs text-text-muted">last {rows.length} days</span>
      </CardHeader>
      <CardContent className="pt-3">
        {rows.length === 0 ? (
          <div className="py-8 text-center text-sm text-text-muted">
            No yield records yet
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-card-border text-left text-xs uppercase tracking-wide text-text-muted">
                  <th className="pb-2 pr-3 font-medium">Date</th>
                  <th className="pb-2 pr-3 text-right font-medium">Equity</th>
                  <th className="pb-2 pr-3 text-right font-medium">Yield</th>
                  <th className="pb-2 text-right font-medium">Return</th>
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
                      className={`py-2.5 text-right tabular-nums ${
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
