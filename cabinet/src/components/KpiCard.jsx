import { Card } from './ui/Card.jsx'

// A large-figure KPI tile: small label on top, big value, optional delta below.
export default function KpiCard({
  label,
  value,
  delta,
  deltaTone = 'muted',
  icon,
  subtle,
}) {
  const toneClass =
    deltaTone === 'positive'
      ? 'text-positive'
      : deltaTone === 'negative'
        ? 'text-negative'
        : 'text-text-muted'

  return (
    <Card className="p-5">
      <div className="flex items-start justify-between">
        <span className="text-xs font-medium uppercase tracking-wide text-text-muted">
          {label}
        </span>
        {icon ? <span className="text-accent">{icon}</span> : null}
      </div>
      <div className="mt-3 text-[2rem] font-bold leading-none tracking-tight text-text-main tabular-nums">
        {value}
      </div>
      {delta != null && delta !== '' ? (
        <div className={`mt-2 text-sm font-medium tabular-nums ${toneClass}`}>
          {delta}
        </div>
      ) : subtle ? (
        <div className="mt-2 text-sm text-text-muted">{subtle}</div>
      ) : (
        <div className="mt-2 h-5" />
      )}
    </Card>
  )
}
