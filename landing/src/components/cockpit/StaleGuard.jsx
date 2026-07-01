/*
 * StaleGuard ⚙ — the fail-closed freshness wrapper. THE primitive every other primitive
 * composes. (Cockpit doctrine: «safety is NEVER implied by silence» — a stale datapoint is
 * shown EXPLICITLY grey + "updated Nm ago", never silently passed off as live.)
 *
 * 5-question map: it is the honesty substrate under ALL five — it stamps every answer with
 * "as of when", and refuses to let a stale answer masquerade as fresh.
 *
 * Props:
 *   payload      — the API response object (read `_fetched_at`/`generated_at`/`as_of`/`ts`+`stale`)
 *   freshness    — OR pass a pre-derived {stale, ageMs, known} (skips deriveFreshness)
 *   staleAfterMs — age past which data is stale (default 90s; poll is 15s)
 *   loading      — render the skeleton state
 *   error        — render the explicit error/offline state (string or bool)
 *   lang, inline — 'en'|'ru'; inline=true → a compact chip instead of a wrapping panel
 *   label        — optional short source label shown next to the freshness stamp
 *   children     — the wrapped content; greyed (opacity + desaturate) when stale
 *
 * States: healthy · stale (grey+stamp) · loading (skeleton) · error/offline (explicit).
 */
import { TABULAR, MONO } from '../ui/tokens.js';
import { deriveFreshness, agoLabel } from './lib.js';

const STAMP = { ...TABULAR, fontFamily: MONO, fontSize: '.6875rem', whiteSpace: 'nowrap' };

function Dot({ color, pulse }) {
  return (
    <span
      aria-hidden="true"
      style={{
        width: 6, height: 6, borderRadius: '50%', background: color, flexShrink: 0,
        animation: pulse ? 'pulse 3s cubic-bezier(.4,0,.6,1) infinite' : 'none',
      }}
    />
  );
}

/* The freshness stamp — the little "● live · updated 12s ago" / "● stale · …" line. */
export function FreshnessStamp({ freshness, lang = 'en', label }) {
  const ru = lang === 'ru';
  const { stale, ageMs, known } = freshness;
  const color = stale ? 'var(--text-muted)' : 'var(--ok)';
  const word = !known
    ? (ru ? 'без метки времени' : 'no timestamp')
    : stale
      ? (ru ? 'устарело' : 'stale')
      : (ru ? 'вживую' : 'live');
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, color }}>
      <Dot color={color} pulse={!stale && known} />
      <span style={STAMP}>{word}</span>
      <span style={{ ...STAMP, color: 'var(--text-faint)' }}>· {agoLabel(ageMs, lang)}</span>
      {label && <span style={{ ...STAMP, color: 'var(--text-faint)' }}>· {label}</span>}
    </span>
  );
}

export default function StaleGuard({
  payload, freshness, staleAfterMs = 90_000, loading = false, error = false,
  lang = 'en', inline = false, label, showStamp = true, children,
}) {
  const ru = lang === 'ru';

  /* ── loading skeleton ── */
  if (loading) {
    return (
      <div aria-busy="true" style={{ display: 'grid', gap: 8 }}>
        {[0, 1, 2].map((i) => (
          <div key={i} className="ck-skel" style={{
            height: i === 0 ? 20 : 12, width: i === 0 ? '55%' : i === 1 ? '85%' : '40%',
            borderRadius: 'var(--r-sm)', background: 'var(--bg-surface-2)',
          }} />
        ))}
        <span className="sr-only">{ru ? 'Загрузка…' : 'Loading…'}</span>
      </div>
    );
  }

  /* ── explicit error / offline ── */
  if (error) {
    const msg = typeof error === 'string'
      ? error
      : (ru ? 'Данные недоступны — источник офлайн. Ничего не выдумано.' : 'Data unavailable — source offline. Nothing fabricated.');
    return (
      <div style={{
        display: 'flex', alignItems: 'center', gap: 8, padding: inline ? '4px 10px' : '12px 14px',
        borderRadius: 'var(--r-sm)', background: 'var(--bg-surface-2)', border: '1px solid var(--border-strong)',
      }}>
        <Dot color="var(--text-muted)" />
        <span style={{ ...STAMP, color: 'var(--text-muted)', whiteSpace: 'normal' }}>{msg}</span>
      </div>
    );
  }

  const fr = freshness || deriveFreshness(payload, staleAfterMs);
  const stale = fr.stale;

  /* Greying recipe applied to children when stale (desaturate + dim, never HIDE the number). */
  const veil = stale
    ? { opacity: 0.55, filter: 'grayscale(0.85)', transition: 'opacity 200ms ease' }
    : undefined;

  if (inline) {
    return (
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <span style={veil}>{children}</span>
        {showStamp && <FreshnessStamp freshness={fr} lang={lang} label={label} />}
      </span>
    );
  }

  return (
    <div style={{ display: 'grid', gap: 8 }}>
      <div style={veil}>{children}</div>
      {showStamp && (
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8,
          flexWrap: 'wrap', paddingTop: 2,
        }}>
          <FreshnessStamp freshness={fr} lang={lang} label={label} />
          {stale && (
            <span style={{ ...STAMP, color: 'var(--warn)' }}>
              {ru ? 'не обновляется — показано как есть' : 'not refreshing — shown as-is'}
            </span>
          )}
        </div>
      )}
    </div>
  );
}
