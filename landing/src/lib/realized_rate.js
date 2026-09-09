// realized_rate.js — the ONE honest source for the desk's realized paper rate (2026-09-09).
//
// Why this exists. The number "~3.3% realized" was typed into SIXTEEN files (prose, meta
// descriptions, RU copy, page comments and the /snapshot calculator's arithmetic). It was the
// track-to-date rate at some point in July and then stayed frozen while the track moved on:
// measured 2026-09-09 the evidenced book gives 5.38% (anchor 2026-06-22, 78 evidenced days).
// A number retyped in sixteen places is a number nobody updates — so no page types it any more.
//
// Same pattern as golive_label.js: the value comes from the build-time snapshot
// (landing/src/data/track_snapshot.json), which the site custodian refreshes daily.
//
// Honesty rules kept here, not in the pages:
//   • no snapshot value ⇒ NO number is rendered ("data unavailable"), never a stale literal;
//   • the drawdown line says WHY it is 0.0% — an accrual book cannot fall by construction —
//     because "0.0% drawdown" read as resilience is the most misleading number on the site.

/** Realized track-to-date APY in percent, or null when the snapshot does not carry it. */
export function realizedApyPct(snap) {
  const v = snap && snap.paper_apy_pct;
  const n = typeof v === 'number' ? v : Number(v);
  return Number.isFinite(n) && n > 0 ? n : null;
}

/** "5.4%" / "5,4%" — one decimal, locale-aware; null-safe. */
export function realizedApyLabel(snap, ru = false) {
  const n = realizedApyPct(snap);
  if (n == null) return ru ? 'нет данных' : 'data unavailable';
  const s = n.toFixed(1);
  return (ru ? s.replace('.', ',') : s) + '%';
}

/** "~5.4% realized" / "~5,4% фактических" — the phrase most pages used to hardcode. */
export function realizedPhrase(snap, ru = false) {
  const n = realizedApyPct(snap);
  if (n == null) return ru ? 'фактическая ставка недоступна' : 'realized rate unavailable';
  return ru ? `~${realizedApyLabel(snap, true)} фактических` : `~${realizedApyLabel(snap)} realized`;
}

/** Evidenced days behind the number, or null. */
export function evidencedDays(snap) {
  const n = Number(snap && snap.real_track_days);
  return Number.isFinite(n) && n > 0 ? n : null;
}

/**
 * The drawdown sentence. NOT just "0.0%": an accrual-only paper book cannot go negative by
 * construction (yield is always positive and trading costs are not charged to the curve yet),
 * so the zero is a property of the model, not measured resilience. Saying "0.0% drawdown"
 * alone reads as "we have never lost money" — which the number does not support.
 */
export function drawdownPhrase(snap, ru = false) {
  const dd = Number(snap && snap.max_drawdown_pct);
  const shown = Number.isFinite(dd) ? Math.abs(dd).toFixed(1) : '0.0';
  return ru
    ? `просадка ${shown.replace('.', ',')}% — начисление по построению не уходит в минус, издержки перекладок в кривую пока не списываются`
    : `${shown}% drawdown — an accrual book cannot fall by construction; trading costs are not charged to the curve yet`;
}
