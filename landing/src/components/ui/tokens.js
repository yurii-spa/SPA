/*
 * ui/tokens.js — the ONE canonical risk-color map, shared by .astro and .jsx surfaces.
 *
 * docs/SITE_DESIGN_SYSTEM_V2.md §3.3. Every value resolves to a CSS custom property
 * (defined in Layout.astro :root) so React islands and Astro pages render IDENTICALLY.
 * NEVER hardcode a hex in a surface — import from here (islands) or use the Tailwind
 * alias / StatusPill component (.astro). This file is the single source of truth for the
 * A/B/C/D tiers and the SAFE/WATCH/REFUSE verdicts.
 */

/* Base token references (all resolve to Layout.astro :root vars). */
export const C = {
  ok: 'var(--ok)',
  warn: 'var(--warn)',
  danger: 'var(--danger)',
  accent: 'var(--accent)',
  accentHover: 'var(--accent-hover)',
  teal: 'var(--data-teal)',
  muted: 'var(--text-muted)',
  faint: 'var(--text-faint)',
  primary: 'var(--text-primary)',
  secondary: 'var(--text-secondary)',
};

/* Tone → {fg, bg, border} — the physical recipe every Badge/pill/tint uses. */
export const TONES = {
  ok:     { fg: 'var(--ok)',        bg: 'var(--ok-bg)',     border: 'var(--ok-border)' },
  warn:   { fg: 'var(--warn)',      bg: 'var(--warn-bg)',   border: 'var(--warn-border)' },
  danger: { fg: 'var(--danger)',    bg: 'var(--danger-bg)', border: 'var(--danger-border)' },
  accent: { fg: 'var(--accent-hover)', bg: 'var(--accent-bg)', border: 'var(--accent-border)' },
  teal:   { fg: 'var(--data-teal)', bg: 'var(--teal-bg)',   border: 'var(--teal-border)' },
  muted:  { fg: 'var(--text-muted)', bg: 'var(--bg-surface-2)', border: 'var(--border-strong)' },
};

/* A/B/C/D risk tiers — severity ramp low→high (V2 §3.3). C=amber, D=red (DFB ordering). */
export const TIER_TONE = { A: 'teal', B: 'accent', C: 'warn', D: 'danger' };

/* SAFE / WATCH / REFUSE verdict → tone (V2 §3.3). SAFE is GREEN everywhere (never teal). */
export const VERDICT_TONE = {
  SAFE: 'ok', ENTRY: 'ok', PASS: 'ok', LIVE: 'ok', GO: 'ok', CLEAR: 'ok', NONE: 'ok',
  WATCH: 'warn', PENDING: 'warn', CAUTION: 'warn', SOFT: 'warn', ARMED: 'warn',
  REFUSE: 'danger', FAIL: 'danger', KILL: 'danger', HARD: 'danger', OFFLINE: 'danger', 'NO-GO': 'danger',
  UNKNOWN: 'muted', 'N/A': 'muted',
};

/* Resolve a verdict/tier string → tone key (falls back to muted for anything unknown). */
export function toneForVerdict(v) {
  if (!v) return 'muted';
  const k = String(v).trim().toUpperCase();
  return VERDICT_TONE[k] || 'muted';
}
export function toneForTier(t) {
  return TIER_TONE[String(t || '').trim().toUpperCase()] || 'muted';
}

/* ─────────────────────────────────── Desk Cockpit shared constants ───────────────
 * The Cockpit primitives (components/cockpit/*) EXTEND this canonical map — they never
 * fork it. These are the tiny cross-primitive constants (mono font, tabular-figures,
 * a motion-safe transition) so every primitive renders numbers that do NOT jump and
 * respects prefers-reduced-motion without re-declaring the recipe in each file.
 */
export const MONO = 'var(--font-mono)';

/* TABULAR — spread onto any element carrying a NUMBER so digits never re-flow width.
 * The Cockpit doctrine: numbers are tabular-figures, never jumping. */
export const TABULAR = { fontVariantNumeric: 'tabular-nums', fontFeatureSettings: '"tnum" 1' };

/* Physical resolved tone recipe (fg/bg/border) for a tone key — thin wrapper over TONES
 * so JS islands (KillGauge SVG, waterfall bars) can pull the same three values. */
export function toneStyle(tone) {
  return TONES[tone] || TONES.muted;
}

/* The raw stroke/fill color for a tone (the fg) — for hand-rolled SVG (gauge arc, chart
 * line) where a var() reference is exactly what <svg stroke> wants. */
export function toneColor(tone) {
  return (TONES[tone] || TONES.muted).fg;
}
