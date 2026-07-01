/*
 * RegimeBadge ⚙ — funding/market regime + streak + vol + cycle position.
 * (From market_regime.json via /api/regime — SPA-002 passthrough.)
 *
 * 5-question map: "what REGIME" — the fifth question, answered as a labeled state not a
 * number. Fail-closed: no regime data ⇒ UNKNOWN (muted), never a fabricated "STABLE".
 *
 * Props:
 *   regime  — 'STABLE'|'HIGH_YIELD'|'COMPRESSED_YIELD'|'VOLATILE' | null
 *   streak  — days in current regime (number|null)
 *   vol     — volatility readout string (e.g. '12.4%') | null
 *   cycle   — optional cycle-position label (string|{en,ru})
 *   note    — optional one-line recommendation (string|{en,ru})
 *   lang, compact
 */
import { Badge } from '../ui/kit.jsx';
import { TABULAR, MONO } from '../ui/tokens.js';
import { pick, NA } from './lib.js';

/* Regime → canonical tone + bilingual label. VOLATILE=danger, COMPRESSED=warn (yield squeezed),
 * HIGH_YIELD=accent (opportunity, not "safe"), STABLE=ok. Unknown → muted. */
const REGIME = {
  STABLE:           { tone: 'ok',     en: 'Stable',           ru: 'Стабильно' },
  HIGH_YIELD:       { tone: 'accent', en: 'High yield',       ru: 'Высокий yield' },
  COMPRESSED_YIELD: { tone: 'warn',   en: 'Compressed yield', ru: 'Сжатый yield' },
  VOLATILE:         { tone: 'danger', en: 'Volatile',         ru: 'Волатильно' },
};

export default function RegimeBadge({ regime, streak, vol, cycle, note, lang = 'en', compact = false }) {
  const ru = lang === 'ru';
  const key = String(regime || '').trim().toUpperCase();
  const meta = REGIME[key] || { tone: 'muted', en: 'Unknown', ru: 'Неизвестно' };
  const label = ru ? meta.ru : meta.en;

  const chip = (k, v) => (
    <span style={{ display: 'inline-flex', alignItems: 'baseline', gap: 5 }}>
      <span style={{ fontFamily: MONO, fontSize: '.625rem', textTransform: 'uppercase', letterSpacing: '.06em', color: 'var(--text-faint)' }}>{k}</span>
      <span style={{ ...TABULAR, fontFamily: MONO, fontSize: '.75rem', color: 'var(--text-secondary)' }}>{v ?? NA}</span>
    </span>
  );

  if (compact) {
    return <Badge tone={meta.tone} dot>{label}</Badge>;
  }

  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 14, flexWrap: 'wrap',
      padding: '10px 14px', borderRadius: 'var(--r-md)',
      background: 'var(--bg-surface)', border: '1px solid var(--border)',
    }}>
      <Badge tone={meta.tone} dot>{label}</Badge>
      {chip(ru ? 'серия' : 'streak', streak != null ? `${streak}${ru ? 'д' : 'd'}` : null)}
      {chip(ru ? 'вол' : 'vol', vol)}
      {cycle != null && chip(ru ? 'цикл' : 'cycle', pick(cycle, lang))}
      {note != null && (
        <span style={{ fontSize: '.75rem', color: 'var(--text-muted)', lineHeight: 1.4 }}>{pick(note, lang)}</span>
      )}
    </div>
  );
}
