// realized_rate.js — the ONE honest source for the desk's paper return and its estimated equivalent (2026-09-09).
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
import { fmtPct2 } from './site_numbers.js';

// ── Owner/ARB 2026-10-08 (P1 Wave 2): the PRIMARY public metric is the paper return over the ACTUAL
// period — NAV ratio (no external flows), ACT/365 on valuation dates — read from the shelf
// (headline.period, one definition: spa_core/paper_trading/track_period_return.py). The annualised
// EQUIVALENT is secondary, always labelled «оценочный годовой эквивалент (ACT/365 Fixed по датам оценки; время начальной оценки не записано), не прогноз», and printed only
// while the shelf says headline.apy.display === "labelled" (one-line switch ANNUALISED_DISPLAY in
// scripts/build_site_numbers.py; "hidden" ⇒ no annualised figure from this helper).

/** Is the annualised equivalent shown at all (owner approval switch)? */
export function annualisedShown() {
  const a = NUMBERS && NUMBERS.headline && NUMBERS.headline.apy;
  return !!a && a.display !== 'hidden';
}

/** The period block, or null when the shelf has no MEASURED period (inv #17: never zeros). */
export function periodReturn() {
  const P = NUMBERS && NUMBERS.headline && NUMBERS.headline.period;
  if (!P || P.state !== 'MEASURED' || !P.period) return null;
  const val = (f) => (f && typeof f.value === 'number' && Number.isFinite(f.value) ? f.value : null);
  const r = {
    ret: val(P.return), navStart: val(P.nav_start), navEnd: val(P.nav_end), costs: val(P.costs_paid_usd),
    start: P.period.start_date || null, end: P.period.end_date || null,
    days: typeof P.period.days_act === 'number' ? P.period.days_act : null,
    bars: typeof P.period.evidenced_bars === 'number' ? P.period.evidenced_bars : null,
    convention: P.period.convention || null, method: P.method || null,
    flows: P.flows && typeof P.flows.count === 'number' && P.flows.state === 'MEASURED' ? P.flows.count : null,
  };
  return (r.ret == null || r.days == null || !r.start || !r.end) ? null : r;
}

/** «+1,41 %» / «+1.41%» (two decimals, ROUND_HALF_UP), or null. */
/** «108 дн. (ACT/365; 107 дн. с записью цикла)» — the elapsed period and the evidenced count, never confused. */
export function periodDaysText(ru = false) {
  const p = periodReturn();
  if (!p) return null;
  const b = p.bars != null ? (ru ? `; ${p.bars} дн. с записью цикла` : `; ${p.bars} days with a cycle record`) : '';
  return ru ? `${p.days} дн. (ACT/365${b})` : `${p.days} days (ACT/365${b})`;
}

export function periodReturnLabel(ru = false) {
  const p = periodReturn();
  return p ? fmtPct2(p.ret, ru, true) : null;
}

/** «4,85 % — оценочный годовой эквивалент (ACT/365 Fixed по датам оценки; время начальной оценки не записано), не прогноз» or '' when hidden/unavailable. */
export function annualisedNote(ru = false) {
  const v = realizedApyPct();
  if (v == null) return '';
  return ru ? `${fmtPct2(v, true)} — оценочный годовой эквивалент (ACT/365 Fixed по датам оценки; время начальной оценки не записано), не прогноз`
            : `${fmtPct2(v, false)} — estimated annualised equivalent (ACT/365 Fixed on valuation dates; start valuation time not recorded), not a forecast`;
}

/**
 * The full primary sentence: «+1,41 % за период 22.06.2026–08.10.2026 (108 дн., бумага): NAV $100 150,66 →
 * $101 564,21, внешних потоков нет, издержки $50,15 внутри NAV». Not measured ⇒ explicit «не измерено».
 */
export function periodReturnPhrase(ru = false) {
  const p = periodReturn();
  if (!p) return ru ? 'доходность за период не измерена' : 'period return not measured';
  const r = fmtPct2(p.ret, ru, true);
  const a = shortDate(p.start, ru), e = shortDate(p.end, ru);
  const ns = usdCents(p.navStart, ru), ne = usdCents(p.navEnd, ru);
  const flows = p.flows == null ? (ru ? 'внешние потоки не измерены' : 'external flows not measured')
    : p.flows === 0 ? (ru ? 'внешних потоков нет' : 'no external flows')
    : (ru ? `внешних потоков: ${p.flows} (TWR)` : `${p.flows} external flows (TWR)`);
  const costs = p.costs == null ? '' : (ru ? `, издержки ${usdCents(p.costs, true)} внутри NAV` : `, costs ${usdCents(p.costs, false)} inside NAV`);
  const navs = (ns && ne) ? (ru ? `: NAV ${ns} → ${ne}` : `: NAV ${ns} → ${ne}`) : '';
  return ru
    ? `${r} за период ${a}–${e}, ${periodDaysText(true)}, бумага${navs}, ${flows}${costs}`
    : `${r} over ${a} to ${e}, ${periodDaysText(false)}, paper${navs}, ${flows}${costs}`;
}

/** Realized track-to-date APY in percent, or null when the shelf does not carry it. */
export function realizedApyPct(_ignoredSnap) {
  if (!annualisedShown()) return null;
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

/**
 * "4.89%" / "4,89 %" — два знака, ROUND_HALF_UP, локаль-зависимо; null-safe (ADR-660).
 *
 * История: с 2026-10-04 ставка округлялась ВНИЗ до одного знака (ADR-563 — 4,9637 % печаталось
 * как 5,0 %). 2026-10-08 владелец заменил это правилом «два знака, к ближайшему, половина вверх»:
 * при двух знаках завышение не больше 0,005 п.п. Арифметика одна — `site_numbers.fmtPct2`.
 */
export function realizedApyLabel(_ignoredSnap, ru = false) {
  // ADR-660 (решение владельца 2026-10-08) заменило округление вниз ADR-563: два знака, ROUND_HALF_UP.
  // Голый форматтер числа. В прозе использовать realizedApyQualified(): годовой эквивалент никогда
  // не печатается без своей метки (owner/ARB 2026-10-08, P1 Wave 2).
  const s = fmtPct2(realizedApyPct(), ru);
  return s == null ? (ru ? 'нет данных' : 'data unavailable') : s;
}

/** Prose form: «4,85 % (годовой эквивалент за 108 дн., ACT/365, не прогноз)»; hidden ⇒ the period return. */
export function realizedApyQualified(_ignoredSnap, ru = false) {
  const v = realizedApyPct();
  if (v == null) {
    const p = periodReturn();
    if (p) return ru ? `${fmtPct2(p.ret, true, true)} за ${p.days} дн. (не годовых)` : `${fmtPct2(p.ret, false, true)} over ${p.days} days (not annualised)`;
    return ru ? 'нет данных' : 'data unavailable';
  }
  const p = periodReturn();
  const tag = p ? (ru ? ` (оценочный годовой эквивалент за ${p.days} дн., ACT/365 Fixed по датам оценки; время начальной оценки не записано, не прогноз)` : ` (estimated annualised equivalent over ${p.days} days, ACT/365 Fixed on valuation dates; start valuation time not recorded, not a forecast)`)
                : (ru ? ' (оценочный годовой эквивалент, не прогноз)' : ' (estimated annualised equivalent, not a forecast)');
  return fmtPct2(v, ru) + tag;
}

/** "~5.4% realized" / "~5,4% фактических" — the phrase most pages used to hardcode. */
export function realizedPhrase(_ignoredSnap, ru = false) {
  // Owner/ARB 2026-10-08: the period return leads; the annualised equivalent follows, labelled.
  const p = periodReturn();
  if (!p) return ru ? 'фактическая доходность недоступна' : 'realized return unavailable';
  const lead = ru
    ? `${fmtPct2(p.ret, true, true)} фактически на бумаге за ${periodDaysText(true)}, ${shortDate(p.start, true)}–${shortDate(p.end, true)}`
    : `${fmtPct2(p.ret, false, true)} realized on paper over ${periodDaysText(false)}, ${shortDate(p.start, false)} to ${shortDate(p.end, false)}`;
  const ann = annualisedNote(ru);
  return ann ? `${lead}; ${ann}` : lead;
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
/** |drawdown| as text, rounded AWAY from zero (2 decimals under 1 %, else 1) — never «0.0» for a loss. */
export function drawdownMagnitudeText(dd) {
  // ADR-660: two decimals, ROUND_HALF_UP; a nonzero loss below 0.005 % reads «<0.01», never «0.00».
  if (dd === null || dd === undefined || dd === '') return null;
  const m = Math.abs(Number(dd));
  if (!Number.isFinite(m)) return null;
  return fmtPct2(m, false).replace('%', '');
}

export function drawdownPhrase(_ignoredSnap, ru = false) {
  const dd = Number(NUMBERS && NUMBERS.headline && NUMBERS.headline.drawdown
                    && NUMBERS.headline.drawdown.value);
  if (!Number.isFinite(dd)) return ru ? 'наблюдавшаяся просадка не измерена' : 'observed drawdown not measured';
  // PRODUCT-TRUTH-02: a drawdown is never rounded toward zero — «0.0%» hid a measured −0.04 %.
  // Magnitude rounded UP (the safe side for a loss), two decimals below 1 %.
  const shown = drawdownMagnitudeText(dd);
  const shownRu = fmtPct2(Math.abs(dd), true);
  return ru
    ? `наблюдавшаяся просадка ${shownRu} — прошлое наблюдение, не предел убытка: кредитное начисление редко уходит в минус, а депег или сбой протокола в этой истории не встречались`
    : `observed drawdown ${shown}% — a past observation, not a loss limit: lending accrual rarely falls, and a depeg or protocol failure has not occurred in this history`;
}

/** Published track drawdown as «0.04%» / «0,04%» (magnitude, rounded away from zero), or null. */
export function drawdownPctText(ru = false) {
  const dd = NUMBERS && NUMBERS.headline && NUMBERS.headline.drawdown && NUMBERS.headline.drawdown.value;
  const m = drawdownMagnitudeText(dd);
  if (m == null) return null;
  return fmtPct2(Math.abs(Number(dd)), ru);   // ADR-660: «0,04 %» / «0.04%»
}

/** The ONE published realized rate for client code: {value (as measured), text_en, text_ru, as_of} or null.
 *  ADR-660: the TEXT is the only rounded form (two decimals, ROUND_HALF_UP); the value is not rounded. */
export function publishedRateFigure() {
  const v = realizedApyPct();
  if (v == null) return null;
  return { value: v, text_en: fmtPct2(v, false), text_ru: fmtPct2(v, true), as_of: measuredAt(), metric_type: 'REALIZED_PAPER',
           label_en: 'estimated annualised equivalent (ACT/365 Fixed on valuation dates; start valuation time not recorded), not a forecast', label_ru: 'оценочный годовой эквивалент (ACT/365 Fixed по датам оценки; время начальной оценки не записано), не прогноз',
           window_days: periodReturn() ? periodReturn().days : null };
}

/** The PRIMARY figure for client code: period return {value, text_en, text_ru, start, end, days} or null. */
export function periodReturnFigure() {
  const p = periodReturn();
  if (!p) return null;
  return { value: p.ret, text_en: fmtPct2(p.ret, false, true), text_ru: fmtPct2(p.ret, true, true),
           start: p.start, end: p.end, days: p.days, as_of: measuredAt(), metric_type: 'REALIZED_PAPER_PERIOD' };
}

// ── P1 2026-10-08 (C4): ставка, накопленный итог и NAV — СВЕДЕНЫ в одной строке ─────────────
// Ставка 4,89 % годовых и «Совокупная доходность +1,56 %» стояли рядом без базы и без окна,
// и читатель видел два противоречащих числа. Они не противоречат — у них разные базы. Эти
// помощники печатают каждую величину ВМЕСТЕ с её базой и окном, из витрины, ничего не
// пересчитывая: страница не может показать одну без другой.

function _fig(path) {
  let node = NUMBERS;
  for (const k of path) node = node && node[k];
  const v = node && node.value;
  return typeof v === 'number' && Number.isFinite(v) ? v : null;
}

/** «$100 150,66» / «$100,150.66» — центы видны: сверка по ним, а не по округлённым тысячам. */
export function usdCents(n, ru = false) {
  if (typeof n !== 'number' || !Number.isFinite(n)) return null;
  const s = n.toLocaleString(ru ? 'ru-RU' : 'en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return '$' + s;
}

/** «22.06.2026» / «2026-06-22» из ISO-даты; нет даты — null. */
export function shortDate(iso, ru = false) {
  if (typeof iso !== 'string' || !/^\d{4}-\d{2}-\d{2}/.test(iso)) return null;
  const [y, m, d] = iso.slice(0, 10).split('-');
  return ru ? `${d}.${m}.${y}` : `${y}-${m}-${d}`;
}

/** Части сверки: обе NAV, даты, длительность ACT/365, доходность за период — из headline.period. null-поля честно null. */
export function rateWindow() {
  const p = periodReturn();
  return {
    rate: realizedApyPct(),
    days: p ? p.days : null,
    anchor: p ? p.start : null,
    end: p ? p.end : null,
    anchorNav: p ? p.navStart : null,
    endNav: p ? p.navEnd : null,
    trackReturn: p ? p.ret : null,
    convention: p ? p.convention : null,
  };
}

/**
 * Сверка одной строкой: доходность за период первой, годовой эквивалент — вторым и с меткой:
 * «+1,41 % за период 22.06.2026–08.10.2026 (108 дн.) = NAV $101 564,21 / NAV $100 150,66 − 1; годовой
 * эквивалент (ACT/365), не прогноз: 4,85 % = (1 + 1,41 %)^(365/108) − 1». Не хватает части — null.
 */
export function rateReconciliation(ru = false) {
  const w = rateWindow();
  if ([w.days, w.anchorNav, w.endNav, w.trackReturn].some((x) => x == null) || !w.anchor || !w.end) return null;
  const tr = fmtPct2(w.trackReturn, ru, true);
  const a = usdCents(w.anchorNav, ru), e = usdCents(w.endNav, ru);
  const da = shortDate(w.anchor, ru), de = shortDate(w.end, ru);
  const lead = ru
    ? `${tr} за период ${da}–${de} (${w.days} дн.) = NAV ${e} / NAV ${a} − 1`
    : `${tr} over ${da} to ${de} (${w.days} days) = NAV ${e} / NAV ${a} − 1`;
  if (w.rate == null) return lead;
  const rate = fmtPct2(w.rate, ru);
  return ru
    ? `${lead}; оценочный годовой эквивалент (ACT/365 Fixed по датам оценки; время начальной оценки не записано), не прогноз: ${rate} = (NAV ${e} / NAV ${a})^(365/${w.days}) − 1`
    : `${lead}; estimated annualised equivalent (ACT/365 Fixed on valuation dates; start valuation time not recorded), not a forecast: ${rate} = (NAV ${e} / NAV ${a})^(365/${w.days}) − 1`;
}

/**
 * «Совокупная доходность» — ДРУГАЯ база: $100 000 с начала бумажного теста, дни до якоря трека
 * включены (в ставку они не входят). Возвращает {value, text}; нет значения — {value: null, text: null}.
 */
export function totalReturnSinceStart(ru = false) {
  const T = (NUMBERS && NUMBERS.track) || {};
  const v = _fig(['track', 'total_return_since_start']);
  const start = T.paper_start_date || null;
  const anchor = (NUMBERS && NUMBERS.headline && NUMBERS.headline.evidenced_anchor) || null;
  if (v == null || !start) return { value: null, text: null };
  const pre = (start && anchor) ? Math.round((Date.parse(anchor) - Date.parse(start)) / 86400000) : null;
  const s = fmtPct2(v, ru, true);
  const ds = shortDate(start, ru), da = shortDate(anchor, ru);
  return {
    value: v,
    text: ru
      ? `${s} с ${ds} на базу $100 000 (замер ${shortDate(measuredAt(), true)})${pre != null && pre > 0 ? ` — включает ${pre} дн. до якоря ${da}, которые в годовую ставку не входят` : ''}`
      : `${s} since ${ds} on the $100,000 base (measured ${measuredAt()})${pre != null && pre > 0 ? ` — includes ${pre} days before the ${da} anchor that the annualised rate excludes` : ''}`,
  };
}

/**
 * P1-12 (2026-10-08): the paper book's MEASURED drawdown with its own window — «since 2026-06-22,
 * 107 evidenced days (not a full year): max drawdown −0.04%». Pages that set our book against a
 * backtested year used «~0.00% over the same year»: a wrong number AND a measurement compared with
 * a backtest as if they shared a window (ADR-580 C2). Not measured ⇒ an explicit «not measured».
 */
export function measuredDrawdownWindow(ru = false) {
  const w = rateWindow();
  const dd = drawdownPctText(ru);
  if (dd == null || w.days == null || !w.anchor) {
    return ru ? 'просадка бумажной книги не измерена' : "the paper book's drawdown is not measured";
  }
  const a = shortDate(w.anchor, ru);
  return ru
    ? `бумажная книга деска с ${a}, ${w.days} подтверждённых дн. (не полный год): макс. просадка −${dd} — замер, а не бэктест`
    : `the desk's paper book since ${a}, ${w.days} evidenced days (not a full year): max drawdown −${dd} — a measurement, not a backtest`;
}
