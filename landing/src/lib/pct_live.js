// pct_live.js — the ADR-660 formatter for React islands, in the page's CURRENT language.
//
// Module-level helpers in islands (`function pct(x)`) have no `lang` in scope. A component calls
// `pctLang(ru)` at the top of its render with the language IT is rendering in (the same state that
// drives its labels), and every `pctL()` during that render prints «4,89 %» or «4.89%» accordingly.
// SSR and the first client render both use the component's initial language, so hydration agrees.
// Absent / non-numeric ⇒ «—», never «0.00%» (inv. #17). The arithmetic is pct_format.js — one copy.
import { fmtPct2 } from './pct_format.js';

let _ru = false;

/** Set the language for the percentages of the render in progress. */
export function pctLang(ru) { _ru = !!ru; }

/** «4,89 %» / «4.89%» (two decimals, ROUND_HALF_UP); null/NaN/boolean ⇒ «—». */
export function pctL(v, signed = false) {
  if (v == null || v === '' || typeof v === 'boolean') return '—';
  const n = Number(v);
  if (!Number.isFinite(n)) return '—';
  return fmtPct2(n, _ru, signed) ?? '—';
}
