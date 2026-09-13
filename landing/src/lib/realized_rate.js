// realized_rate.js — the ONE honest source for the desk's realized paper rate (2026-09-09).
//
// ИЗМЕНЕНО 13.09 (ADR-372, установка владельца ADR-357 п. 5): числа берутся из ВИТРИНЫ
// (`site_numbers.json`), а не из дневного снимка напрямую.
//
// Зачем. Владелец просил обновлять сайт РАЗ В НЕДЕЛЮ. Витрину с недельным тактом я
// построил (ADR-365), но страницы продолжали читать дневной снимок — то есть сайт как
// обновлялся ежедневно, так и обновлялся, и недельный такт существовал только в файле,
// которого никто не читает. Разрыв между «сделано» и «действует» ровно того рода, что
// этот проект ловит у себя каждую неделю.
//
// Аргумент `snap` СОХРАНЁН в сигнатурах и НЕ ЧИТАЕТСЯ — переименован в `_ignoredSnap`,
// чтобы это было видно глазами, а не выяснялось отладкой. Так пятнадцать страниц и
// пятьдесят два вызова переходят на витрину одной правкой, без слепого прохода по ним.
// Проверено: все вызовы передают один и тот же импорт снимка, другого объекта не
// передаёт никто.
//
// И ДАТА ЗАМЕРА идёт вместе со ставкой. Публикация недельная, наблюдение ежедневное:
// без даты недельное число читалось бы как сегодняшнее — та же подмена, из-за которой
// «~3,3 %» простояло два месяца.
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

import NUMBERS from '../data/site_numbers.json';

/** Realized track-to-date APY in percent, or null when the shelf does not carry it. */
export function realizedApyPct(_ignoredSnap) {
  const v = NUMBERS && NUMBERS.headline && NUMBERS.headline.apy && NUMBERS.headline.apy.value;
  const n = typeof v === 'number' ? v : Number(v);
  return Number.isFinite(n) && n > 0 ? n : null;
}

/** День, когда снят замер (публикация недельная — наблюдение ежедневное). */
export function measuredAt() {
  return (NUMBERS && NUMBERS.measured_at) || null;
}

/** «(замер 13 сентября)» / «(measured 13 Sep)» — пусто, если даты нет. */
export function measuredNote(ru = false) {
  const d = measuredAt();
  if (!d) return '';
  return ru ? ` (замер ${d})` : ` (measured ${d})`;
}

/** "5.4%" / "5,4%" — one decimal, locale-aware; null-safe. */
export function realizedApyLabel(_ignoredSnap, ru = false) {
  const n = realizedApyPct();
  if (n == null) return ru ? 'нет данных' : 'data unavailable';
  const s = n.toFixed(1);
  return (ru ? s.replace('.', ',') : s) + '%';
}

/** "~5.4% realized" / "~5,4% фактических" — the phrase most pages used to hardcode. */
export function realizedPhrase(_ignoredSnap, ru = false) {
  const n = realizedApyPct();
  if (n == null) return ru ? 'фактическая ставка недоступна' : 'realized rate unavailable';
  return ru
    ? `~${realizedApyLabel(null, true)} фактических${measuredNote(true)}`
    : `~${realizedApyLabel(null)} realized${measuredNote(false)}`;
}

/** Evidenced days behind the number, or null. */
export function evidencedDays(_ignoredSnap) {
  const n = Number(NUMBERS && NUMBERS.headline && NUMBERS.headline.evidenced_days
                   && NUMBERS.headline.evidenced_days.value);
  return Number.isFinite(n) && n > 0 ? n : null;
}

/**
 * The drawdown sentence. NOT just "0.0%": an accrual-only paper book cannot go negative by
 * construction (yield is always positive and trading costs are not charged to the curve yet),
 * so the zero is a property of the model, not measured resilience. Saying "0.0% drawdown"
 * alone reads as "we have never lost money" — which the number does not support.
 */
export function drawdownPhrase(_ignoredSnap, ru = false) {
  const dd = Number(NUMBERS && NUMBERS.headline && NUMBERS.headline.drawdown
                    && NUMBERS.headline.drawdown.value);
  const shown = Number.isFinite(dd) ? Math.abs(dd).toFixed(1) : '0.0';
  return ru
    ? `просадка ${shown.replace('.', ',')}% — начисление по построению не уходит в минус, издержки перекладок в кривую пока не списываются`
    : `${shown}% drawdown — an accrual book cannot fall by construction; trading costs are not charged to the curve yet`;
}
