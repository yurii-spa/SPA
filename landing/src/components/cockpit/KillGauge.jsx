/*
 * KillGauge ⭐ SIGNATURE — one kill-condition as a MANOMETER (hand-rolled SVG, no dep).
 *
 * Value vs threshold on a 180° arc, headroom %, last-triggered. The arc fills toward the
 * threshold; the needle sits at the live value. Tone escalates as it nears the threshold:
 *   green (safe headroom) → amber (nearing, WATCH band) → kill-red (breached).
 * (SPA-002 conditions[]: {condition, value, threshold, headroom, unit, tier}.)
 *
 * 5-question map: "how much RISK" + "what the system WILL do" — a pressure reading of a
 * kill condition, so a breach is UNMISTAKABLE, not a number to interpret.
 *
 * FAIL-CLOSED: value==null OR threshold==null OR tier==='UNKNOWN' ⇒ renders an explicit
 * UNKNOWN gauge (grey, no needle, no fabricated headroom). It NEVER invents headroom.
 *
 * Props:
 *   label       — condition name (string|{en,ru}) e.g. "Drawdown"
 *   value       — live value (number|null)
 *   threshold   — kill threshold (number|null)  (breach when value >= threshold)
 *   headroom    — optional pre-computed headroom (threshold − value); else derived
 *   unit        — '%' | '$' | '' (suffix on value/threshold)
 *   tier        — 'SAFE'|'WATCH'|'SOFT'|'HARD'|'BREACHED'|'UNKNOWN' | null (drives tone)
 *   warnAt      — fraction of threshold to begin the amber band (default 0.6)
 *   lastTriggered — optional string shown as "last triggered …"
 *   reducedMotion — disable arc transition
 *   lang, size  — 'md' (default) | 'sm'
 */
import { TABULAR, MONO, toneColor } from '../ui/tokens.js';
import { pick, fmtNum, NA } from './lib.js';

const isNum = (v) => v != null && isFinite(Number(v));

/* Point on the 180° arc (semicircle, left→right) at fraction f∈[0,1]. */
function arcPoint(cx, cy, r, f) {
  const a = Math.PI - Math.PI * Math.max(0, Math.min(1, f)); // π (left) → 0 (right)
  return { x: cx + r * Math.cos(a), y: cy - r * Math.sin(a) };
}
function arcPath(cx, cy, r, f0, f1) {
  const p0 = arcPoint(cx, cy, r, f0);
  const p1 = arcPoint(cx, cy, r, f1);
  const large = Math.abs(f1 - f0) > 0.5 ? 1 : 0;
  return `M ${p0.x.toFixed(2)} ${p0.y.toFixed(2)} A ${r} ${r} 0 ${large} 1 ${p1.x.toFixed(2)} ${p1.y.toFixed(2)}`;
}

/* Resolve tier → tone. If tier absent, derive from value/threshold ratio. */
function resolveTone(tier, ratio, warnAt, breached) {
  const t = String(tier || '').trim().toUpperCase();
  if (t === 'UNKNOWN') return 'muted';
  if (t === 'HARD' || t === 'BREACHED' || breached) return 'danger';
  if (t === 'SOFT' || t === 'WATCH') return 'warn';
  if (t === 'SAFE') return 'ok';
  // derive
  if (ratio == null) return 'muted';
  if (ratio >= 1) return 'danger';
  if (ratio >= warnAt) return 'warn';
  return 'ok';
}

export default function KillGauge({
  label, value, threshold, headroom, unit = '', tier, warnAt = 0.6,
  lastTriggered, reducedMotion = false, lang = 'en', size = 'md',
}) {
  const ru = lang === 'ru';
  const known = isNum(value) && isNum(threshold) && String(tier || '').toUpperCase() !== 'UNKNOWN';
  const dim = size === 'sm' ? { w: 132, h: 80, r: 52, cx: 66, cy: 70, sw: 8 } : { w: 168, h: 100, r: 66, cx: 84, cy: 88, sw: 10 };

  const ratio = known ? Number(value) / Number(threshold) : null;
  const fill = ratio == null ? 0 : Math.max(0, Math.min(1, ratio));
  const breached = known && Number(value) >= Number(threshold);
  const tone = resolveTone(tier, ratio, warnAt, breached);
  const col = toneColor(tone);

  const hr = headroom != null ? Number(headroom) : (known ? Number(threshold) - Number(value) : null);
  const suffix = unit === '$' ? '' : unit;
  const fmtV = (v) => (isNum(v) ? (unit === '$' ? '$' + fmtNum(v, 2) : fmtNum(v, 2) + suffix) : NA);

  // needle
  const np = arcPoint(dim.cx, dim.cy, dim.r - 2, fill);
  const warnP = arcPoint(dim.cx, dim.cy, dim.r, warnAt); // amber band start tick

  return (
    <div style={{
      display: 'grid', gap: 8, padding: '14px 16px 12px', borderRadius: 'var(--r-lg)',
      background: 'var(--bg-surface)',
      border: `1px solid ${breached ? 'var(--danger-border)' : 'var(--border)'}`,
    }}>
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 8 }}>
        <p style={{ fontFamily: MONO, fontSize: '.6875rem', textTransform: 'uppercase', letterSpacing: '.07em', color: 'var(--text-muted)', margin: 0 }}>
          {pick(label, lang)}
        </p>
        <span style={{ fontFamily: MONO, fontSize: '.625rem', fontWeight: 600, color: col, textTransform: 'uppercase', letterSpacing: '.05em' }}>
          {known ? (breached ? (ru ? 'ПРОБИТО' : 'BREACHED') : (String(tier || '').toUpperCase() || (tone === 'ok' ? 'SAFE' : tone === 'warn' ? 'WATCH' : ''))) : (ru ? 'НЕИЗВ.' : 'UNKNOWN')}
        </span>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <svg width={dim.w} height={dim.h} viewBox={`0 0 ${dim.w} ${dim.h}`} aria-hidden="true" style={{ flexShrink: 0 }}>
          {/* track */}
          <path d={arcPath(dim.cx, dim.cy, dim.r, 0, 1)} fill="none" stroke="var(--border)" strokeWidth={dim.sw} strokeLinecap="round" />
          {/* filled arc value→threshold */}
          {known && fill > 0 && (
            <path
              d={arcPath(dim.cx, dim.cy, dim.r, 0, fill)}
              fill="none" stroke={col} strokeWidth={dim.sw} strokeLinecap="round"
              style={reducedMotion ? undefined : { transition: 'stroke 300ms ease' }}
            />
          )}
          {/* threshold tick at the top (f=1, right end = kill) + warn tick */}
          <circle cx={arcPoint(dim.cx, dim.cy, dim.r, 1).x} cy={arcPoint(dim.cx, dim.cy, dim.r, 1).y} r={dim.sw / 2 + 1} fill="var(--danger)" opacity={known ? 1 : 0.4} />
          {known && <circle cx={warnP.x} cy={warnP.y} r={2} fill="var(--warn)" opacity={0.7} />}
          {/* needle */}
          {known && (
            <line
              x1={dim.cx} y1={dim.cy} x2={np.x} y2={np.y}
              stroke={col} strokeWidth={size === 'sm' ? 2 : 2.5} strokeLinecap="round"
              style={reducedMotion ? undefined : { transition: 'all 400ms cubic-bezier(.4,0,.2,1)' }}
            />
          )}
          <circle cx={dim.cx} cy={dim.cy} r={size === 'sm' ? 3 : 4} fill={known ? col : 'var(--text-muted)'} />
        </svg>

        <div style={{ display: 'grid', gap: 4, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
            <span style={{ ...TABULAR, fontFamily: MONO, fontSize: '1.35rem', fontWeight: 700, color: known ? col : 'var(--text-muted)', lineHeight: 1 }}>
              {fmtV(value)}
            </span>
            <span style={{ ...TABULAR, fontFamily: MONO, fontSize: '.6875rem', color: 'var(--text-faint)' }}>
              / {fmtV(threshold)}
            </span>
          </div>
          <span style={{ ...TABULAR, fontFamily: MONO, fontSize: '.6875rem', color: known ? 'var(--text-secondary)' : 'var(--text-muted)' }}>
            {known
              ? `${ru ? 'запас' : 'headroom'} ${hr >= 0 ? '' : ''}${fmtV(hr)}`
              : (ru ? 'нет данных — запас не выдумываем' : 'no data — headroom not fabricated')}
          </span>
          {lastTriggered && (
            <span style={{ ...TABULAR, fontFamily: MONO, fontSize: '.625rem', color: 'var(--text-faint)' }}>
              {ru ? 'посл. срабатывание ' : 'last triggered '}{lastTriggered}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

/* KillPanel — a responsive grid of KillGauge. props: {conditions[], lang, reducedMotion, size}.
 * Each condition is a KillGauge prop object. Empty/absent conditions → explicit fail-closed note. */
export function KillPanel({ conditions, lang = 'en', reducedMotion = false, size = 'md', title }) {
  const ru = lang === 'ru';
  const rows = Array.isArray(conditions) ? conditions : [];
  return (
    <div style={{ display: 'grid', gap: 12 }}>
      {title && (
        <p style={{ fontFamily: MONO, fontSize: '.6875rem', textTransform: 'uppercase', letterSpacing: '.08em', color: 'var(--text-muted)', margin: 0 }}>
          {pick(title, lang)}
        </p>
      )}
      {rows.length === 0 ? (
        <div style={{ padding: '14px 16px', borderRadius: 'var(--r-md)', background: 'var(--bg-surface-2)', border: '1px solid var(--border-strong)' }}>
          <span style={{ fontFamily: MONO, fontSize: '.75rem', color: 'var(--text-muted)' }}>
            {ru ? 'Условия kill-switch недоступны — fail-closed (без выдуманного запаса).' : 'Kill-switch conditions unavailable — fail-closed (no fabricated headroom).'}
          </span>
        </div>
      ) : (
        <div style={{ display: 'grid', gap: 12, gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))' }}>
          {rows.map((c, i) => (
            <KillGauge key={c.key || c.condition || i} lang={lang} reducedMotion={reducedMotion} size={size} {...c} />
          ))}
        </div>
      )}
    </div>
  );
}
