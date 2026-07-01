/*
 * ui/riskStyles.js — JSX-side risk-style helper for the DFB islands.
 *
 * DERIVES from Agent A's canonical map (ui/tokens.js) — it does NOT define a second
 * risk-color language. It only reshapes the ONE canonical tone map into the inline
 * `{ bg, bd, fg }` style-object shape the DFB React islands consume, so the board
 * renders the risk language IDENTICALLY to the dashboard, academy, and marketing
 * StatusPill. Every value resolves to a var(--…) token from Layout.astro :root.
 *
 * Canonical (from tokens.js):
 *   A/B/C/D tier → TIER_TONE  (A=teal, B=accent, C=warn, D=danger)
 *   SAFE/WATCH/REFUSE → VERDICT_TONE (SAFE=ok/green, WATCH=warn, REFUSE=danger, ? → muted)
 *   alert severity   → critical=danger, high=warn, medium=warn, ? → muted (no invented orange)
 */
import { TONES, toneForTier, toneForVerdict } from './tokens.js';

// { fg, bg, border } (A's shape) → { bg, bd, fg } (island shape).
function shape(tone, ru) {
  const t = TONES[tone] || TONES.muted;
  return { bg: t.bg, bd: t.border, fg: t.fg, ru };
}

const CLASS_RU = { A: 'A', B: 'B', C: 'C', D: 'D' };
export function classStyle(c) {
  const key = String(c || '').trim().toUpperCase();
  return shape(toneForTier(key), CLASS_RU[key] || '?');
}

const VERDICT_RU = { SAFE: 'БЕЗОПАСНО', WATCH: 'НАБЛЮДЕНИЕ', REFUSE: 'ОТКАЗ' };
export function verdictStyle(v) {
  const key = String(v || '').trim().toUpperCase();
  return shape(toneForVerdict(key), VERDICT_RU[key] || 'НЕИЗВЕСТНО');
}

// Alert severity → canonical tone. high folds into warn (V2 §3.3 — no orange in the palette).
const SEV_TONE = { critical: 'danger', high: 'warn', medium: 'warn' };
const SEV_RU = { critical: 'критично', high: 'высокая', medium: 'средняя' };
export function sevStyle(s) {
  const key = String(s || '').trim().toLowerCase();
  return shape(SEV_TONE[key] || 'muted', SEV_RU[key] || 'неизв.');
}
