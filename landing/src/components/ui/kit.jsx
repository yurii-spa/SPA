/*
 * ui/kit.jsx — React-island mirror of the shared UI kit (V2 §3.4).
 *
 * The .astro kit (Badge/StatusPill/Table/…) can't render inside a hydrated React
 * island, so DFB / academy islands import these instead. They resolve to the SAME
 * CSS custom properties (via ui/tokens.js) so an island badge is pixel-identical to an
 * .astro badge. NEVER hardcode a hex in an island — use these.
 */
import { TONES, toneForVerdict, toneForTier } from './tokens.js';

const MONO = 'var(--font-mono)';

/* Badge — one geometry, tone-mapped. props: {tone, dot, title, children} */
export function Badge({ tone = 'muted', dot = false, title, children, style }) {
  const t = TONES[tone] || TONES.muted;
  return (
    <span
      title={title}
      style={{
        display: 'inline-flex', alignItems: 'center', gap: 6, whiteSpace: 'nowrap',
        fontFamily: MONO, fontSize: '.6875rem', fontWeight: 500, lineHeight: 1,
        padding: '4px 10px', borderRadius: 'var(--r-full)',
        background: t.bg, border: `1px solid ${t.border}`, color: t.fg, ...style,
      }}
    >
      {dot && <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'currentColor', flexShrink: 0 }} aria-hidden="true" />}
      {children}
    </span>
  );
}

/* StatusPill — map a verdict OR tier → the canonical tone, then render a Badge.
 * props: {verdict, tier, tone, label, dot, title} */
export function StatusPill({ verdict, tier, tone, label, dot = true, title }) {
  const resolved = tone || (verdict ? toneForVerdict(verdict) : tier ? toneForTier(tier) : 'muted');
  return <Badge tone={resolved} dot={dot} title={title}>{label ?? verdict ?? tier ?? ''}</Badge>;
}

/* LiveChip — one live/offline source chip. props: {live, source, updated, label} */
export function LiveChip({ live = false, source, updated, label }) {
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
      <Badge tone={live ? 'ok' : 'muted'}>
        <span
          style={{
            width: 6, height: 6, borderRadius: '50%', background: 'currentColor', flexShrink: 0,
            animation: live ? 'pulse 3s cubic-bezier(.4,0,.6,1) infinite' : 'none',
          }}
          aria-hidden="true"
        />
        {label ?? (live ? 'Live' : 'Offline')}
      </Badge>
      {source && (
        <span style={{ fontFamily: MONO, fontSize: '.6875rem', color: 'var(--text-muted)' }}>
          {source}{updated ? ` · ${updated}` : ''}
        </span>
      )}
    </span>
  );
}

/* Card surface style (spread onto a div). One treatment: solid bg-surface. */
export const cardStyle = {
  background: 'var(--bg-surface)', border: '1px solid var(--border)', borderRadius: 'var(--r-lg)',
};
