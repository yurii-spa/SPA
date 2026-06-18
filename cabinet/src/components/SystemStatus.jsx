import { Card, CardHeader, CardTitle, CardContent } from './ui/Card.jsx'
import Badge from './ui/Badge.jsx'
import { fmtDateTime } from '../lib/format.js'

function Row({ label, children }) {
  return (
    <div className="flex items-center justify-between py-2">
      <span className="text-sm text-text-muted">{label}</span>
      <span className="text-sm font-medium text-text-main">{children}</span>
    </div>
  )
}

export default function SystemStatus({ health, performance, isDemo }) {
  const apiUp = health?.status === 'ok'
  const lastCycle = performance?.last_cycle_ts
  const daysRunning = performance?.days_running

  return (
    <Card>
      <CardHeader>
        <CardTitle>System Status</CardTitle>
        <Badge tone={apiUp ? 'positive' : 'negative'}>
          {apiUp ? '● Online' : '● Offline'}
        </Badge>
      </CardHeader>
      <CardContent className="pt-2 divide-y divide-card-border/50">
        <Row label="API">
          <Badge tone={apiUp ? 'positive' : 'negative'}>
            {apiUp ? 'OK' : 'Down'}
          </Badge>
        </Row>
        <Row label="Track mode">
          <Badge tone={isDemo ? 'warning' : 'accent'}>
            {isDemo ? 'Demo' : 'Live paper'}
          </Badge>
        </Row>
        <Row label="Days running">{daysRunning != null ? daysRunning : '—'}</Row>
        <Row label="Last cycle">
          {lastCycle ? fmtDateTime(lastCycle) : '—'}
        </Row>
      </CardContent>
    </Card>
  )
}
