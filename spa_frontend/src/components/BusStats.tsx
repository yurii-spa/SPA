import type { BusStats } from '../types'

interface Props {
  stats: BusStats
}

const TOPIC_ORDER = [
  'MARKET_DATA',
  'HEALTH_ALERT',
  'STRATEGY_SIGNAL',
  'TRADE_DECISION',
  'EXECUTION_RESULT',
]

const TOPIC_COLORS: Record<string, string> = {
  MARKET_DATA:       '#185FA5',
  HEALTH_ALERT:      '#BA7517',
  STRATEGY_SIGNAL:   '#2e2775',
  TRADE_DECISION:    '#065030',
  EXECUTION_RESULT:  '#5c2209',
}

export function BusStats({ stats }: Props) {
  const topics = TOPIC_ORDER.filter((t) => stats[t] !== undefined)

  return (
    <div className="card">
      <div className="card-title">Message Bus</div>
      <table className="data-table">
        <thead>
          <tr>
            <th>Topic</th>
            <th style={{ textAlign: 'right' }}>Pending</th>
            <th style={{ textAlign: 'right' }}>Consumed</th>
            <th style={{ textAlign: 'right' }}>Acked</th>
            <th style={{ textAlign: 'right' }}>Dead</th>
          </tr>
        </thead>
        <tbody>
          {topics.map((t) => {
            const s = stats[t] ?? { pending: 0, consumed: 0, acked: 0, dead: 0 }
            return (
              <tr key={t}>
                <td>
                  <span
                    style={{
                      display: 'inline-block',
                      fontFamily: 'monospace',
                      fontSize: 11,
                      padding: '2px 7px',
                      borderRadius: 4,
                      background: `${TOPIC_COLORS[t]}18`,
                      color: TOPIC_COLORS[t],
                      fontWeight: 600,
                    }}
                  >
                    {t}
                  </span>
                </td>
                <td style={{ textAlign: 'right', color: s.pending > 0 ? '#BA7517' : '#555' }}>
                  {s.pending}
                </td>
                <td style={{ textAlign: 'right', color: '#555' }}>{s.consumed}</td>
                <td style={{ textAlign: 'right', color: '#3B6D11' }}>{s.acked}</td>
                <td style={{ textAlign: 'right', color: s.dead > 0 ? '#b91c1c' : '#aaa' }}>
                  {s.dead}
                </td>
              </tr>
            )
          })}
          {topics.length === 0 && (
            <tr>
              <td colSpan={5} style={{ textAlign: 'center', color: '#aaa', padding: 16 }}>
                No messages yet
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  )
}
