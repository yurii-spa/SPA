/*
 * AttributionWaterfall ⭐ SIGNATURE + AttributionBar — P&L by source, hand-rolled SVG.
 *
 * The waterfall SUMS to the total: each source (funding / basis / staking / rwa / price)
 * is a floating block stacked from the running cumulative, and the final "Total" bar closes
 * to the sum. price≈0 renders as a visually-nothing sliver → PROVES market-neutrality by eye.
 * (Data: /api/captured-book::attribution — floor_leg + carry_leg = realized_pnl, reconciles.)
 *
 * 5-question map: "WHERE'S THE MONEY" — decomposes the P&L into its honest sources so a
 * reader sees WHY the number is what it is, not just the number.
 *
 * FAIL-CLOSED: if the segments do NOT sum to the stated total within tolerance, the
 * `reconciles` badge goes red and we DO NOT silently rescale — we show the mismatch.
 * If segments are missing/empty ⇒ explicit "attribution unavailable", never a fake bar.
 *
 * Props:
 *   segments — [{ key, label:{en,ru}|str, value:number, tone? }]  (signed USD; +earn/−cost)
 *   total    — the stated realized total (number|null); used for the reconcile check
 *   reconciles — optional explicit bool from the API; else derived (|sum−total| ≤ tol)
 *   tol      — reconcile tolerance in USD (default 1.0)
 *   fmt      — value formatter (default usdCompact); pass fmtUsd2 for exact
 *   reducedMotion, lang, height
 */
import { TABULAR, MONO, toneColor } from '../ui/tokens.js';
import { pick, usdCompact, NA } from './lib.js';

const isNum = (v) => v != null && isFinite(Number(v));

/* Default source→tone: earn sources teal/ok, cost sources warn, price=muted (should be ~0). */
const DEFAULT_TONE = {
  funding: 'teal', basis: 'accent', staking: 'ok', rwa: 'ok', carry: 'teal', floor: 'accent',
  price: 'muted', fees: 'warn', cost: 'warn', slippage: 'warn',
};
function toneFor(seg) {
  if (seg.tone) return seg.tone;
  const k = String(seg.key || '').toLowerCase();
  if (DEFAULT_TONE[k]) return DEFAULT_TONE[k];
  return Number(seg.value) < 0 ? 'warn' : 'teal';
}

export default function AttributionWaterfall({
  segments, total, reconciles, tol = 1.0, fmt = usdCompact,
  reducedMotion = false, lang = 'en', height = 200,
}) {
  const ru = lang === 'ru';
  const segs = Array.isArray(segments) ? segments.filter((s) => isNum(s.value)) : [];

  if (!segs.length) {
    return (
      <div style={{ padding: '16px', borderRadius: 'var(--r-md)', background: 'var(--bg-surface-2)', border: '1px solid var(--border-strong)' }}>
        <span style={{ fontFamily: MONO, fontSize: '.75rem', color: 'var(--text-muted)' }}>
          {ru ? 'Атрибуция недоступна — источник не сошёлся или пуст (число не выдумано).' : 'Attribution unavailable — source empty or failed integrity (no number fabricated).'}
        </span>
      </div>
    );
  }

  const sum = segs.reduce((a, s) => a + Number(s.value), 0);
  const shownTotal = isNum(total) ? Number(total) : sum;
  const ok = typeof reconciles === 'boolean' ? reconciles : Math.abs(sum - shownTotal) <= tol;

  // scale: running cumulative range + total
  const cum = [];
  let run = 0;
  for (const s of segs) { const start = run; run += Number(s.value); cum.push({ ...s, start, end: run }); }
  const lo = Math.min(0, ...cum.map((c) => Math.min(c.start, c.end)), shownTotal);
  const hi = Math.max(0, ...cum.map((c) => Math.max(c.start, c.end)), shownTotal);
  const span = hi - lo || 1;
  const plot = height - 44; // room for labels
  const y = (v) => plot - ((v - lo) / span) * plot;

  const n = segs.length + 1; // +1 for the closing Total bar
  const colGap = 10;
  const bars = cum.map((c, i) => {
    const tone = toneFor(c);
    const yTop = y(Math.max(c.start, c.end));
    const h = Math.max(2, Math.abs(y(c.start) - y(c.end)));
    return { i, tone, yTop, h, val: c.value, label: c.label, key: c.key || i };
  });
  const totTone = shownTotal >= 0 ? 'teal' : 'danger';
  const totTop = y(Math.max(0, shownTotal));
  const totH = Math.max(2, Math.abs(y(0) - y(shownTotal)));

  return (
    <div style={{ display: 'grid', gap: 10 }}>
      {/* reconcile badge */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap' }}>
        <span style={{
          display: 'inline-flex', alignItems: 'center', gap: 6, fontFamily: MONO, fontSize: '.6875rem', fontWeight: 600,
          padding: '3px 10px', borderRadius: 'var(--r-full)',
          background: ok ? 'var(--ok-bg)' : 'var(--danger-bg)', border: `1px solid ${ok ? 'var(--ok-border)' : 'var(--danger-border)'}`,
          color: ok ? 'var(--ok)' : 'var(--danger)',
        }}>
          <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'currentColor' }} aria-hidden="true" />
          {ok ? (ru ? 'сходится к итогу ✓' : 'reconciles to total ✓') : (ru ? 'НЕ СХОДИТСЯ — не масштабируем' : 'DOES NOT RECONCILE — not rescaled')}
        </span>
        <span style={{ ...TABULAR, fontFamily: MONO, fontSize: '.75rem', color: 'var(--text-secondary)' }}>
          Σ {fmt(sum)}{ok ? '' : ` ≠ ${fmt(shownTotal)}`}
        </span>
      </div>

      {/* the waterfall */}
      <svg width="100%" height={height} viewBox={`0 0 ${Math.max(320, n * 72)} ${height}`} preserveAspectRatio="xMidYMid meet" role="img"
           aria-label={ru ? 'Водопад атрибуции P&L' : 'P&L attribution waterfall'}>
        {/* zero baseline */}
        <line x1="0" y1={y(0)} x2={n * 72} y2={y(0)} stroke="var(--border-strong)" strokeWidth="1" strokeDasharray="3 3" />
        {bars.map((b) => {
          const x = colGap + b.i * 72;
          const col = toneColor(b.tone);
          const nearZero = Math.abs(b.val) < (span * 0.01);
          return (
            <g key={b.key}>
              <rect x={x} y={b.yTop} width={52} height={b.h} rx="2" fill={col} opacity={nearZero ? 0.35 : 0.85}
                    style={reducedMotion ? undefined : { transition: 'y 400ms cubic-bezier(.4,0,.2,1), height 400ms cubic-bezier(.4,0,.2,1)' }} />
              {/* connector to next bar's start */}
              {b.i < bars.length - 1 && (
                <line x1={x + 52} y1={y(cum[b.i].end)} x2={x + 72 + colGap - colGap} y2={y(cum[b.i].end)} stroke="var(--border-strong)" strokeWidth="1" strokeDasharray="2 2" opacity="0.6" />
              )}
              <text x={x + 26} y={height - 26} textAnchor="middle" fontFamily="var(--font-mono)" fontSize="9" fill="var(--text-muted)" style={{ textTransform: 'uppercase' }}>
                {pick(b.label, lang).slice(0, 9)}
              </text>
              <text x={x + 26} y={height - 14} textAnchor="middle" fontFamily="var(--font-mono)" fontSize="9" fill={nearZero ? 'var(--text-faint)' : 'var(--text-secondary)'} style={{ fontVariantNumeric: 'tabular-nums' }}>
                {fmt(b.val)}
              </text>
            </g>
          );
        })}
        {/* closing Total bar */}
        {(() => {
          const x = colGap + segs.length * 72;
          const col = toneColor(totTone);
          return (
            <g>
              <rect x={x} y={totTop} width={52} height={totH} rx="2" fill={col}
                    style={reducedMotion ? undefined : { transition: 'y 400ms cubic-bezier(.4,0,.2,1), height 400ms cubic-bezier(.4,0,.2,1)' }} />
              <text x={x + 26} y={height - 26} textAnchor="middle" fontFamily="var(--font-mono)" fontSize="9" fill="var(--text-primary)" fontWeight="600" style={{ textTransform: 'uppercase' }}>
                {ru ? 'итог' : 'total'}
              </text>
              <text x={x + 26} y={height - 14} textAnchor="middle" fontFamily="var(--font-mono)" fontSize="9" fill="var(--text-primary)" fontWeight="600" style={{ fontVariantNumeric: 'tabular-nums' }}>
                {fmt(shownTotal)}
              </text>
            </g>
          );
        })()}
      </svg>
    </div>
  );
}

/* AttributionBar — the compact 100%-stacked variant (same data, no waterfall). One row of
 * proportional segments; price≈0 is a hairline → market-neutrality by eye. Fail-closed same. */
export function AttributionBar({ segments, fmt = usdCompact, lang = 'en', showLabels = true }) {
  const ru = lang === 'ru';
  const segs = Array.isArray(segments) ? segments.filter((s) => isNum(s.value)) : [];
  if (!segs.length) {
    return (
      <span style={{ fontFamily: MONO, fontSize: '.75rem', color: 'var(--text-muted)' }}>
        {ru ? 'Атрибуция недоступна.' : 'Attribution unavailable.'}
      </span>
    );
  }
  const totalAbs = segs.reduce((a, s) => a + Math.abs(Number(s.value)), 0) || 1;
  return (
    <div style={{ display: 'grid', gap: 8 }}>
      <div style={{ display: 'flex', height: 14, borderRadius: 'var(--r-full)', overflow: 'hidden', border: '1px solid var(--border)' }}>
        {segs.map((s, i) => {
          const w = (Math.abs(Number(s.value)) / totalAbs) * 100;
          return <div key={s.key || i} title={`${pick(s.label, lang)}: ${fmt(s.value)}`}
                      style={{ width: `${w}%`, background: toneColor(toneFor(s)), opacity: Math.abs(s.value) < totalAbs * 0.005 ? 0.3 : 0.85 }} />;
        })}
      </div>
      {showLabels && (
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
          {segs.map((s, i) => (
            <span key={s.key || i} style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontFamily: MONO, fontSize: '.6875rem' }}>
              <span style={{ width: 8, height: 8, borderRadius: 2, background: toneColor(toneFor(s)), flexShrink: 0 }} aria-hidden="true" />
              <span style={{ color: 'var(--text-muted)' }}>{pick(s.label, lang)}</span>
              <span style={{ ...TABULAR, color: 'var(--text-secondary)' }}>{fmt(s.value)}</span>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
