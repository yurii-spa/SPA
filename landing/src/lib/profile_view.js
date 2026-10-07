// profile_view.js — the PRODUCT-UX-01 surfaces' view of a public profile, built ON TOP of the canonical
// card model (lib/package_card.js, ADR-537 «one card»). It computes no number and owns no rule:
//   • result (measured or «accumulating») · maturity · research target · research tail · stop rule ·
//     mechanism · live status  → cardModels() from package_card.js
//   • the measured drawdown as a figure → the same shelf the card reads (site_numbers.js)
// What it adds is ORDER and plain WORDS for a first-time visitor. Canonical rules it keeps (tested in
// spa_core/tests/test_package_card_rule.py):
//   1. a research target is never shown without its tail, and never for a profile that is not yet
//      reportable as if it were its result — immature ⇒ target and tail are collapsed «research» detail;
//   2. Conservative has no backtest tail (the card returns tail = null): its realized drawdown is its tail;
//   3. every tail is labelled «earlier version, not this strategy» at the number.

import { cardModels, PACKAGES } from './package_card.js';
import NUMBERS, { value, book } from './site_numbers.js';
import { drawdownMagnitudeText, measuredAt } from './realized_rate.js';
import SNAP from '../data/track_snapshot.json';
import TIER_BANDS from './tier_bands.json';   // NAMES only — targets and tails come from package_card.js

export const PROFILES = PACKAGES;

const pkg = (key) => (SNAP && SNAP.package_status && SNAP.package_status.packages && SNAP.package_status.packages[key]) || null;
const ci = SNAP && SNAP.package_status && SNAP.package_status.code_identity;

// Plain-language copy only (no figures). «For» reflects maturity: an immature profile is research.
const COPY = {
  conservative: {
    for_en: 'People who want stablecoins to earn something while capital stays the priority.',
    for_ru: 'Тем, кто хочет, чтобы стейблкоины что-то зарабатывали, но главное — сохранность капитала.',
    objective_en: 'Steady lending income on large stablecoin lending markets, no leverage.',
    objective_ru: 'Ровный доход от кредитования на крупных рынках стейблкоинов, без плеча.',
    risk_en: 'Lower', risk_ru: 'Ниже', risk_tone: 'low',
    liquidity_en: 'Lending markets — normally withdrawable daily; can be delayed if a market is fully borrowed.',
    liquidity_ru: 'Кредитные рынки — обычно вывод в течение дня; может задержаться, если рынок полностью занят.',
  },
  balanced: {
    for_en: 'Research — testing whether a locked fixed rate is worth a fixed term and some extra protocol risk.',
    for_ru: 'Исследование — проверяем, стоит ли фиксированная ставка фиксированного срока и чуть большего риска протокола.',
    objective_en: 'Add a fixed rate on top of lending: a Pendle PT is bought below its face value and redeems at face value on its maturity date — that difference is the fixed rate.',
    objective_ru: 'Добавить к кредитованию фиксированную ставку: Pendle PT покупается дешевле номинала и в дату погашения погашается по номиналу — эта разница и есть фиксированная ставка.',
    risk_en: 'Medium', risk_ru: 'Средний', risk_tone: 'mid',
    liquidity_en: 'The fixed-rate part is held to maturity; exiting early means selling at the market price.',
    liquidity_ru: 'Фиксированная часть держится до погашения; ранний выход — продажа по рыночной цене.',
  },
  aggressive: {
    for_en: 'Research only — studying what leverage adds and what it costs. Not offered for real capital.',
    for_ru: 'Только исследование — изучаем, что даёт плечо и чего оно стоит. Для реального капитала не предлагается.',
    objective_en: 'Measure a leveraged stablecoin loop (simulated: deposit sUSDe, borrow PYUSD against it, repeat) against its liquidation risk.',
    objective_ru: 'Измерить петлю с плечом на стейблкоинах (симулированную: внести sUSDe, занять под него PYUSD, повторить) против риска ликвидации.',
    risk_en: 'Higher', risk_ru: 'Выше', risk_tone: 'high',
    liquidity_en: 'Unwinding a loop depends on market depth; in stress it can be slow and costly.',
    liquidity_ru: 'Выход из петли зависит от глубины рынка; в стрессе может быть медленным и дорогим.',
  },
};

// One-line plain glossary for terms that still appear (inline explanations, not a separate page).
export const GLOSSARY = {
  evidenced_days: { en: 'Evidenced days: days for which a complete, checkable daily record of the portfolio exists.', ru: 'Подтверждённые дни: дни, за которые есть полная проверяемая дневная запись портфеля.' },
  health_factor: { en: 'Health factor: how far a leveraged position is from liquidation — below 1 the lender sells the collateral.', ru: 'Фактор здоровья: насколько позиция с плечом далека от ликвидации — ниже 1 кредитор продаёт залог.' },
  susde: { en: 'sUSDe: Ethena’s staked synthetic dollar; its yield comes from futures funding and basis trades, and it can lose its peg to the dollar.', ru: 'sUSDe: застейканный синтетический доллар Ethena; доходность идёт от фандинга и базиса фьючерсов, и он может потерять привязку к доллару.' },
  pyusd: { en: 'PYUSD: PayPal’s dollar stablecoin.', ru: 'PYUSD: долларовый стейблкоин PayPal.' },
  steakhouse: { en: 'Steakhouse vault: a curated lending vault on Morpho Blue — a curator chooses which markets the deposits are lent into.', ru: 'Хранилище Steakhouse: курируемое кредитное хранилище на Morpho Blue — куратор выбирает, в какие рынки отдаются депозиты.' },
  thirty_days: { en: 'Why the wait: an annual rate from a few days can swing wildly, so a rate is published only after the minimum history.', ru: 'Почему ждём: годовая ставка по нескольким дням может скакать как угодно, поэтому её публикуем только после минимальной истории.' },
  target_vs_realized: { en: 'Why the target differs from the result: the target is what the research tries to reach under good conditions; the result is what actually happened, after modelled costs.', ru: 'Почему цель отличается от результата: цель — то, чего исследование пытается достичь в хороших условиях; результат — что получилось на деле, после расчётных издержек.' },
};

/** Asset/venue terms explained wherever they are named — derived from the text, never per-page lists. */
const TERM_TOKENS = { susde: 'sUSDe', pyusd: 'PYUSD', steakhouse: 'Steakhouse' };
export function termsIn(...texts) {
  const t = texts.filter(Boolean).join(' ');
  return Object.keys(TERM_TOKENS).filter((k) => t.includes(TERM_TOKENS[k])).map((k) => GLOSSARY[k]);
}

const PROTOCOL = {
  aave_v3: 'Aave v3', compound_v3: 'Compound v3', fluid_fusdc: 'Fluid (fUSDC)', maple: 'Maple',
  morpho_blue_base: 'Morpho Blue (Base)', morpho_steakhouse: 'Morpho (Steakhouse vault)', susde: 'Ethena sUSDe',
};

// owner-layer words: «book» → «portfolio» (the card's operator vocabulary stays in the card)
const owner = (s, ru) => s && (ru
  ? s.replace(/книга прекращает/g, 'портфель прекращает').replace(/книги/g, 'портфеля').replace(/книгу/g, 'портфель').replace(/книга/g, 'портфель')
  : s.replace(/\bthe book\b/g, 'the portfolio').replace(/\bbook\b/g, 'portfolio'));

const plainLive = (s, ru) => s && (ru
  ? s.replace(/трека go-live/g, 'пути к реальному капиталу').replace(/гейтов go-live/g, 'проверок перед реальным капиталом')
  : s.replace(/the go-live track/g, 'the path to live capital').replace(/the go-live gates/g, 'the checks before live capital'));

/** Maturity from the canonical card (history state + valid days / reportable after). */
export function maturity(key) {
  const m = cardModels(key, pkg(key), null, ci).en;
  const h = m.history || {};
  if (m.missing || typeof h.n !== 'number' || typeof h.need !== 'number') return { state: 'NOT_MEASURED', n: null, need: null };
  return {
    state: h.state === 'REPORTABLE' ? 'MATURE' : 'ACCUMULATING', n: h.n, need: h.need, since: h.since || null,
    research_only: m.live && m.live.state === 'REFUSED',
  };
}

/** Profiles that currently have a reportable (mature) result — derived, never hand-typed. */
export function matureProfiles() { return PROFILES.filter((k) => maturity(k).state === 'MATURE'); }

/** Everything a profile card / page needs, in both languages — from the canonical card model. */
export function profileView(key) {
  const cards = cardModels(key, pkg(key), null, ci);
  const en = cards.en, ru = cards.ru;
  const mat = maturity(key);
  const res = en.result || {};
  let measured = null;
  if (res.measured) {
    const b = key === 'conservative' ? (NUMBERS.headline || {}) : (book(key) || {});
    const dd = value(b.drawdown);
    const m = drawdownMagnitudeText(dd);
    measured = {
      rate_en: en.result.main, rate_ru: ru.result.main,
      dd_en: m == null ? null : `−${m}%`, dd_ru: m == null ? null : `−${m.replace('.', ',')}%`,
      date: measuredAt(), days: mat.n,
    };
  }
  const tail_en = en.tail, tail_ru = ru.tail;   // null for Conservative (canonical)
  return {
    key, name_en: TIER_BANDS[key].en, name_ru: TIER_BANDS[key].ru,
    ...COPY[key],
    mechanism_en: en.mechanic || null, mechanism_ru: ru.mechanic || null,
    maturity: mat, measured,
    // rule 1: the target is part of the result block only when the profile is mature; otherwise collapsed research
    target_en: en.target, target_ru: ru.target, target_shown: mat.state === 'MATURE',
    tail_en, tail_ru,
    stop: { en: owner(en.risk && en.risk.stop, false), ru: owner(ru.risk && ru.risk.stop, true) },
    drawdown_phrase: { en: en.risk && en.risk.drawdown, ru: ru.risk && ru.risk.drawdown },
    live_en: plainLive(en.live && en.live.reason, false), live_ru: plainLive(ru.live && ru.live.reason, true),
    position_en: owner(en.decision && en.decision.position, false), position_ru: owner(ru.decision && ru.decision.position, true),
    position_date: en.decision && en.decision.date,
    holdings: holdings(key),
  };
}

/** Protocol names held (weights are not published) — from the snapshot composition the card also reads. */
export function holdings(key) {
  const c = pkg(key) && pkg(key).composition;
  if (!c || c.state !== 'MEASURED') return null;
  const ids = [];
  const unresolved = Array.isArray((c.tiers_held || {}).unresolved) ? c.tiers_held.unresolved : [];
  for (const [k, arr] of Object.entries(c.tiers_held || {})) if (k !== 'unresolved' && Array.isArray(arr)) ids.push(...arr);
  return { protocols: ids.map((x) => PROTOCOL[x] || x), unresolved: unresolved.map((x) => PROTOCOL[x] || x), tech_en: c.summary_en || null };
}

/** The headline figure: the mature profile's measured result (from the shelf through the card). */
export function headline() {
  return {
    published: NUMBERS.published_at || null, next: NUMBERS.next_publication || null,
  };
}

export const GO_LIVE = {
  en: 'Paper stage. Live capital is not open; opening it requires a decision by the project owner and a legal review — not just a day count.',
  ru: 'Бумажная стадия. Реальный капитал не принимается; для этого нужны решение владельца проекта и юридическая проверка, а не только счёт дней.',
};

export const STATUS_BAR = {
  en: 'Paper stage · simulated portfolios, no deposits · not an offer',
  ru: 'Бумажная стадия · симулированные портфели, депозитов нет · не оферта',
};

export const TIER_NAMES = Object.fromEntries(PACKAGES.map((k) => [k, { en: TIER_BANDS[k].en, ru: TIER_BANDS[k].ru }]));

/** «Only Conservative has enough history…» — derived from maturity(), never hand-typed. */
export function maturitySentence() {
  const mat = matureProfiles(), rest = PROFILES.filter((k) => !mat.includes(k));
  const names = (ks, ru) => ks.map((k) => TIER_BANDS[k][ru ? 'ru' : 'en']).join(ru ? ' и ' : ' and ');
  if (!mat.length) return { en: 'No strategy has enough history to publish a result yet.', ru: 'Пока ни у одной стратегии нет достаточной истории для публикации результата.' };
  if (!rest.length) return { en: 'All strategies have enough history to publish a result.', ru: 'У всех стратегий достаточно истории для публикации результата.' };
  return {
    en: `Only ${names(mat)} ${mat.length > 1 ? 'have' : 'has'} enough history to publish a result. For ${names(rest)} we show how many days have been collected so far.`,
    ru: `Достаточная для публикации результата история есть только у: ${names(mat, true)}. Для ${rest.length > 1 ? 'остальных' : 'остальной'} — ${names(rest, true)} — показываем, сколько дней уже набрано.`,
  };
}

/** Short nav/teaser label per profile — derived from maturity, not typed. */
export function maturityShort(key) {
  const m = maturity(key);
  if (m.state === 'MATURE') return { en: 'result published', ru: 'результат опубликован' };
  if (m.state === 'ACCUMULATING') return { en: `history accumulating (${m.n}/${m.need} days)`, ru: `история копится (${m.n}/${m.need} дн.)` };
  return { en: 'not measured', ru: 'не измерено' };
}
