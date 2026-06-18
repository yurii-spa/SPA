// Formatting helpers. API returns numeric values as JSON numbers/strings
// (Decimal serialized) — coerce defensively.

export function num(v, fallback = 0) {
  if (v === null || v === undefined || v === '') return fallback
  const n = typeof v === 'number' ? v : parseFloat(v)
  return Number.isFinite(n) ? n : fallback
}

export function fmtUsd(v, { decimals = 2, compact = false } = {}) {
  const n = num(v)
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
    notation: compact ? 'compact' : 'standard',
  }).format(n)
}

export function fmtPct(v, { decimals = 2, sign = false } = {}) {
  const n = num(v)
  const s = `${n.toFixed(decimals)}%`
  return sign && n > 0 ? `+${s}` : s
}

export function fmtSignedUsd(v, decimals = 2) {
  const n = num(v)
  const formatted = fmtUsd(Math.abs(n), { decimals })
  if (n > 0) return `+${formatted}`
  if (n < 0) return `-${formatted}`
  return formatted
}

export function toneForValue(v) {
  const n = num(v)
  if (n > 0) return 'positive'
  if (n < 0) return 'negative'
  return 'muted'
}

export function fmtDate(dateStr) {
  if (!dateStr) return '—'
  try {
    const d = new Date(dateStr.length === 10 ? `${dateStr}T00:00:00Z` : dateStr)
    return new Intl.DateTimeFormat('en-US', {
      month: 'short',
      day: 'numeric',
    }).format(d)
  } catch {
    return dateStr
  }
}

export function fmtDateTime(dateStr) {
  if (!dateStr) return '—'
  try {
    const d = new Date(dateStr)
    return new Intl.DateTimeFormat('en-US', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    }).format(d)
  } catch {
    return dateStr
  }
}
