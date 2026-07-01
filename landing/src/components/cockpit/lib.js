/*
 * cockpit/lib.js — shared helpers for the Desk Cockpit primitives (SPA-004/005, Lane B).
 *
 * Formatting, freshness derivation, i18n plumbing. Pure functions, no React. Every
 * primitive composes these so the doctrine («history, not a number» · fail-closed ·
 * tabular figures · idle = positive) is enforced ONCE, not re-implemented per file.
 *
 * FAIL-CLOSED CONTRACT: a null / NaN / missing value formats to NA ("—"), NEVER to 0 or
 * a fabricated number. Freshness is derived EXPLICITLY — a datapoint with no timestamp is
 * treated as stale-unknown, never silently fresh (safety is never implied by silence).
 */

export const NA = '—';

/* ── formatters (fail-closed: null/NaN → NA, never 0) ────────────────────────────── */
const isNum = (v) => v != null && isFinite(Number(v));

export const fmtUsd0 = (v) => (isNum(v) ? '$' + Number(v).toLocaleString('en-US', { maximumFractionDigits: 0 }) : NA);
export const fmtUsd2 = (v) => (isNum(v) ? '$' + Number(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : NA);
export const fmtPct = (v, d = 2) => (isNum(v) ? Number(v).toFixed(d) + '%' : NA);
export const fmtSigned = (v, d = 2) => (isNum(v) ? (Number(v) >= 0 ? '+' : '') + Number(v).toFixed(d) + '%' : NA);
export const fmtNum = (v, d = 2) => (isNum(v) ? Number(v).toFixed(d) : NA);

export function usdCompact(v) {
  const n = Number(v);
  if (!isNum(v)) return NA;
  const s = n < 0 ? '-' : '';
  const a = Math.abs(n);
  if (a >= 1e9) return s + '$' + (a / 1e9).toFixed(2) + 'B';
  if (a >= 1e6) return s + '$' + (a / 1e6).toFixed(2) + 'M';
  if (a >= 1e3) return s + '$' + (a / 1e3).toFixed(1) + 'k';
  return s + '$' + a.toFixed(0);
}

/* ── freshness — the fail-closed heart of StaleGuard ─────────────────────────────── */
/*
 * Reads BOTH backend idioms (the plan §1.1 envelope note):
 *   - /api/live/*  → `_fetched_at` (epoch seconds) + `stale` (bool)
 *   - proof/advisory → `generated_at` / `as_of` (ISO string or epoch)
 * Returns { ageMs, stale, ts, known }. `known:false` ⇒ NO timestamp at all ⇒ treated as
 * STALE (never silently fresh). An explicit `stale:true` from the backend always wins.
 */
export function deriveFreshness(payload, staleAfterMs = 90_000, now = Date.now()) {
  if (payload == null) return { ageMs: null, stale: true, ts: null, known: false };

  // explicit backend flag wins (but a false flag still needs a ts to be trusted)
  const explicit = typeof payload.stale === 'boolean' ? payload.stale : null;

  let tsMs = null;
  const raw = payload._fetched_at ?? payload.generated_at ?? payload.as_of ?? payload.ts ?? null;
  if (raw != null) {
    if (typeof raw === 'number' && isFinite(raw)) {
      tsMs = raw > 1e12 ? raw : raw * 1000; // ms vs epoch-seconds
    } else if (typeof raw === 'string') {
      const p = Date.parse(raw);
      if (!isNaN(p)) tsMs = p;
    }
  }

  if (tsMs == null) {
    // No parseable timestamp → fail-closed: unknown freshness ⇒ stale (unless backend says fresh explicitly).
    return { ageMs: null, stale: explicit === false ? false : true, ts: null, known: explicit === false };
  }

  const ageMs = Math.max(0, now - tsMs);
  const stale = explicit != null ? explicit : ageMs > staleAfterMs;
  return { ageMs, stale, ts: tsMs, known: true };
}

/* Human "updated Nm ago" (bilingual). null age → "unknown". */
export function agoLabel(ageMs, lang = 'en') {
  if (ageMs == null) return lang === 'ru' ? 'время неизвестно' : 'time unknown';
  const s = Math.round(ageMs / 1000);
  const u = (en, ru) => (lang === 'ru' ? ru : en);
  if (s < 60) return u(`updated ${s}s ago`, `обновлено ${s}с назад`);
  const m = Math.round(s / 60);
  if (m < 60) return u(`updated ${m}m ago`, `обновлено ${m}м назад`);
  const h = Math.round(m / 60);
  if (h < 48) return u(`updated ${h}h ago`, `обновлено ${h}ч назад`);
  const d = Math.round(h / 24);
  return u(`updated ${d}d ago`, `обновлено ${d}д назад`);
}

/* ── i18n — read the site's spa_lang, re-render on toggle (mirrors DashboardLive) ── */
export function readLang() {
  try {
    if (typeof window === 'undefined') return 'en';
    return window.localStorage.getItem('spa_lang') === 'ru' ? 'ru' : 'en';
  } catch {
    return 'en';
  }
}

/* pick({en, ru}, lang) → the string for the language, tolerant of a bare string. */
export function pick(obj, lang = 'en') {
  if (obj == null) return '';
  if (typeof obj === 'string') return obj;
  return obj[lang] ?? obj.en ?? '';
}
