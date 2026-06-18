const TONES = {
  default: 'bg-card-border text-text-main',
  accent: 'bg-accent/15 text-accent',
  positive: 'bg-positive/15 text-positive',
  negative: 'bg-negative/15 text-negative',
  muted: 'bg-card-border text-text-muted',
  warning: 'bg-yellow-500/15 text-yellow-400',
}

export default function Badge({ tone = 'default', className = '', children }) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium
        ${TONES[tone] || TONES.default} ${className}`}
    >
      {children}
    </span>
  )
}
