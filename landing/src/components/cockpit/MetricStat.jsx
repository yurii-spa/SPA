/*
 * MetricStat ⚙ — number + label + Δ + trend, tabular-figures, fail-closed.
 * (Promotes DashboardLive::Metric into a shared, stale-aware, tabular-safe primitive.)
 *
 * 5-question map: "where's the money" / "how much risk" — the atomic readout. Every KPI
 * on every screen is a MetricStat so a null renders as "—" (never 0), digits never jump.
 *
 * Props:
 *   label    — the metric name (string | {en,ru})
 *   value    — the FORMATTED display string (caller formats via lib.js: fmtUsd0/fmtPct…)
 *   delta    — optional {value:'+1.2%', tone?} OR a formatted string; tone auto: +→ok / −→danger
 *   deltaTone— override the delta tone ('ok'|'danger'|'warn'|'muted')
 *   trend    — optional array of numbers → a tiny inline sparkline (hand-rolled SVG)
 *   sub      — small caption under the value (string | {en,ru})
 *   tone     — value color tone ('ok'|'warn'|'danger'|'accent'|'teal'); default primary ink
 *   idle     — true ⇒ render as a POSITIVE "parked" state (teal, not error) — doctrine
 *   stale    — true ⇒ grey the value (composed by StaleGuard, or set directly)
 *   size     — 'md' (default) | 'lg' | 'sm'
 *   lang
 */
import { TABULAR, MONO, toneColor } from '../ui/tokens.js';
import { pick, NA } from './lib.js';

const SIZE = {
  sm: { v: '1.15rem', l: '.625rem' },
  md: { v: '1.6rem', l: '.6875rem' },
  lg: { v: '2.1rem', l: '.75rem' },
};

function Sparkline({ data, color }) {
  if (!Array.isArray(data) || data.length < 2) return null;
  const w = 56, h = 18, pad = 1;
  const min = Math.min(...data), max = Math.max(...data);
  const span = max - min || 1;
  const pts = data.map((v, i) => {
    const x = pad + (i / (data.length - 1)) * (w - 2 * pad);
    const y = h - pad - ((v - min) / span) * (h - 2 * pad);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(' ');
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} aria-hidden="true" style={{ flexShrink: 0 }}>
      <polyline points={pts} fill="none" stroke={color} strokeWidth="1.25" strokeLinejoin="round" strokeLinecap="round" opacity="0.85" />
    </svg>
  );
}

export default function MetricStat({
  label, value, delta, deltaTone, trend, sub, tone, idle = false, stale = false,
  size = 'md', lang = 'en', style,
}) {
  const s = SIZE[size] || SIZE.md;
  const valColor = idle ? 'var(--data-teal)' : tone ? toneColor(tone) : 'var(--text-primary)';

  // delta tone: explicit → else infer from leading sign of the string
  let dText = null, dTone = deltaTone || 'muted';
  if (delta != null) {
    dText = typeof delta === 'object' ? delta.value : String(delta);
    if (!deltaTone && typeof delta === 'object' && delta.tone) dTone = delta.tone;
    else if (!deltaTone && dText) {
      const first = dText.trim()[0];
      dTone = first === '-' || first === '−' ? 'danger' : first === '+' ? 'ok' : 'muted';
    }
  }
  const dColor = toneColor(dTone);
  const trendColor = idle ? 'var(--data-teal)' : (tone ? toneColor(tone) : 'var(--text-muted)');

  return (
    <div style={{
      background: 'var(--bg-surface)', border: '1px solid var(--border)', borderRadius: 'var(--r-lg)',
      padding: '18px 18px 16px', display: 'grid', gap: 8, minWidth: 0,
      ...(idle ? { borderColor: 'var(--teal-border)' } : null), ...style,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
        <p style={{
          fontFamily: MONO, fontSize: s.l, textTransform: 'uppercase', letterSpacing: '.08em',
          color: 'var(--text-muted)', margin: 0,
        }}>{pick(label, lang)}</p>
        {trend && <Sparkline data={trend} color={trendColor} />}
      </div>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, flexWrap: 'wrap' }}>
        <p style={{
          ...TABULAR, fontFamily: MONO, fontSize: s.v, fontWeight: 700, lineHeight: 1.05,
          color: value == null || value === NA ? 'var(--text-muted)' : valColor, margin: 0,
          opacity: stale ? 0.55 : 1, filter: stale ? 'grayscale(0.85)' : undefined,
        }}>{value == null ? NA : value}</p>
        {dText && (
          <span style={{ ...TABULAR, fontFamily: MONO, fontSize: '.8125rem', fontWeight: 600, color: dColor }}>
            {dText}
          </span>
        )}
      </div>
      {(sub || idle) && (
        <p style={{ fontSize: '.75rem', color: idle ? 'var(--data-teal)' : 'var(--text-muted)', margin: 0, lineHeight: 1.4 }}>
          {idle && !sub ? (lang === 'ru' ? 'капитал припаркован — рабочее состояние' : 'capital parked — a working state') : pick(sub, lang)}
        </p>
      )}
    </div>
  );
}
