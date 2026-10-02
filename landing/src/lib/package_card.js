// package_card.js — ONE rendering rule for the three paper-portfolio cards (ADR-533/534).
//
// The home page, /packages and the strategy pages all show Conservative / Balanced / Aggressive.
// They used to answer different questions with the same badge: a green «evidenced» next to a
// yellow «research / paper» next to a yellow «refused for live», and a measured rate in the same
// big font as two research targets. This module is the single place where a package-status record
// (``spa_core.defi_engine.package_status.public_view`` — served by the daily snapshot AND by
// ``/api/v1/packages/status``) becomes the words and tones of a card. Pages import it for the
// server render; the card script imports the same functions for the live refresh, so the two can
// never drift.
//
// Seven questions, seven fields — never one badge (owner, 2026-10-02):
//   work      RUNNING · PAUSED · FAILED · UNKNOWN · NOT_STARTED   is the scheduled process working?
//   data      HEALTHY · DEGRADED · WAITING_FOR_DATA · STALE        did it see fresh inputs?
//   decision  OPEN · HOLD · EXIT · NONE                            what it holds / decided, and why
//   history   WARMUP · ACCUMULATING · REPORTABLE                   how mature the CURRENT version is
//   mode      PAPER_ONLY + live NOT_APPROVED · REFUSED             real-capital admission
//   result    one definition for all three: the current version's realized paper result
//   risk      risk profile, observed drawdown, stop rule and its ACTION — three different things
//
// **The status colour is not a risk grade.** Green = the scheduled process is confirmed working
// and its data is fresh. It never means low risk, profit, enough statistics or live approval.
// Yellow = a named warning or missing data. Red = a CONFIRMED fault. Neutral = paper mode,
// accumulation, a correct HOLD.
//
// **Freshness is judged by the reader's clock.** A record says when its run happened and how
// long that stays fresh (``freshness.stale_at``). ``effective()`` turns an expired record into
// UNKNOWN / STALE whatever ``generated_at`` says — a newly built JSON never makes an old
// observation fresh, and an open tab goes yellow on its own when updates stop.
//
// **No number is typed or computed here** (site-numbers rule, ADR-357 п. 5): every rate, NAV and
// drawdown comes from the ONE shelf (`site_numbers.js` — the same figures realized_rate.js and every
// other page print); kill-switch thresholds from the shelf's `thresholds`, the two sleeve stops
// (not on the shelf) from constitution.json; research targets from tier_bands.json. The status
// record supplies only STATES, dates and position facts (positions count, loop debt and health
// factor) — never a yield figure. A sleeve's rate and drawdown appear only when the shelf carries
// them (REPORTABLE); before that the card says the statistics are accumulating.

import NUMBERS, { value, pct as figPct, usd as figUsd, headlineApy, book, threshold } from './site_numbers.js';
import C from './constitution.json';
import TIER_BANDS from './tier_bands.json';

export const PACKAGES = ['conservative', 'balanced', 'aggressive'];

const WORK = {
  RUNNING: { tone: 'ok', en: 'Paper · running', ru: 'Бумажный режим · работает' },
  PAUSED: { tone: 'warn', en: 'Paper · paused', ru: 'Бумажный режим · на паузе' },
  FAILED: { tone: 'bad', en: 'Paper · not running', ru: 'Бумажный режим · не работает' },
  UNKNOWN: { tone: 'warn', en: 'Paper · status not confirmed', ru: 'Бумажный режим · статус не подтверждён' },
  NOT_STARTED: { tone: 'neutral', en: 'Paper · not started', ru: 'Бумажный режим · не запущен' },
};
const DATA = {
  HEALTHY: { tone: 'neutral', en: 'data complete and fresh', ru: 'данные полные и свежие' },
  DEGRADED: { tone: 'warn', en: 'data incomplete', ru: 'данные неполные' },
  WAITING_FOR_DATA: { tone: 'warn', en: 'waiting for data', ru: 'ожидает данных' },
  STALE: { tone: 'warn', en: 'data out of date', ru: 'данные устарели' },
};
const DECISION = {
  OPEN: { en: 'position open', ru: 'позиция открыта' },
  HOLD: { en: 'holding — no entry', ru: 'удержание — входа нет' },
  EXIT: { en: 'exited', ru: 'выход выполнен' },
  NONE: { en: 'no decision yet', ru: 'решений ещё нет' },
};
const HISTORY = {
  WARMUP: { en: 'warm-up', ru: 'разогрев' },
  ACCUMULATING: { en: 'accumulating', ru: 'накапливается' },
  REPORTABLE: { en: 'reportable', ru: 'достаточно для отчёта' },
};
const LIVE = {
  NOT_APPROVED: { tone: 'neutral', en: 'Real capital: not approved', ru: 'Реальный капитал: не одобрен' },
  REFUSED: { tone: 'warn', en: 'Real capital: refused', ru: 'Реальный капитал: не допускается' },
};
const RISK_PROFILE = {
  conservative: { en: 'Low', ru: 'Низкий' },
  balanced: { en: 'Medium', ru: 'Средний' },
  aggressive: { en: 'Higher', ru: 'Повышенный' },
};
const COSTS = {
  conservative: {
    en: 'net of modelled gas and slippage of the book’s own moves (charged since 2026-09-10); real execution costs not included',
    ru: 'за вычетом расчётных газа и проскальзывания собственных ходов книги (списываются с 10.09.2026); реальные издержки исполнения не учтены',
  },
  balanced: {
    en: 'net of modelled costs (gas, slippage, Pendle fees on PT trades); real execution costs not included',
    ru: 'за вычетом расчётных издержек (газ, проскальзывание, комиссии Pendle при сделках с PT); реальные издержки исполнения не учтены',
  },
  aggressive: {
    en: 'net of modelled costs (gas, slippage, swap cost of the loop both ways, borrow interest); real execution costs not included',
    ru: 'за вычетом расчётных издержек (газ, проскальзывание, обмен в петле в обе стороны, проценты по займу); реальные издержки исполнения не учтены',
  },
};

const iso = (v) => (v ? String(v).replace('+00:00', 'Z') : null);
/** "2026-10-02 09:00 UTC" — or the honest «—» for an absent timestamp. */
export function when(v) {
  const s = iso(v);
  if (!s) return '—';
  const d = new Date(s);
  if (isNaN(d.getTime())) return '—';
  return d.toISOString().slice(0, 16).replace('T', ' ') + ' UTC';
}
const ms = (v) => { const d = new Date(iso(v) || ''); return isNaN(d.getTime()) ? null : d.getTime(); };

/**
 * The record as the reader's clock sees it. A record past ``freshness.stale_at`` is not
 * «running» any more, whatever the file says: work → UNKNOWN, data → STALE, with the age named.
 */
export function effective(p, nowMs) {
  if (!p || typeof p !== 'object') return null;
  const staleAt = ms(p.freshness && p.freshness.stale_at);
  const settled = p.work && (p.work.state === 'FAILED' || p.work.state === 'PAUSED' || p.work.state === 'NOT_STARTED');
  if (staleAt == null) {
    // no freshness window ⇒ nothing confirms the run is current: never green by default
    if (settled) return { ...p, expired: false };
    return { ...p, expired: true,
      work: { ...p.work, state: 'UNKNOWN', reason_en: 'no run timestamp — status not confirmed', reason_ru: 'нет отметки времени запуска — статус не подтверждён' },
      data: { ...p.data, state: 'STALE', reason_en: 'freshness not measured', reason_ru: 'свежесть не измерена' } };
  }
  if (nowMs == null || nowMs <= staleAt) return { ...p, expired: false };
  const ageH = ((nowMs - (ms(p.freshness.last_successful_run_at) || staleAt)) / 3600000).toFixed(1);
  const work = settled ? p.work : {
    ...p.work, state: 'UNKNOWN',
    reason_en: `no confirmed run for ${ageH} h — status not confirmed`,
    reason_ru: `подтверждённого запуска нет ${ageH.replace('.', ',')} ч — статус не подтверждён`,
  };
  const data = { ...p.data, state: 'STALE',
    reason_en: `the last observation is ${ageH} h old`,
    reason_ru: `последнему наблюдению ${ageH.replace('.', ',')} ч` };
  return { ...p, work, data, expired: true };
}

function shelfFigures(key) {
  if (key === 'conservative') {
    const H = NUMBERS.headline || {};
    return { apy: headlineApy(), drawdown: H.drawdown, nav: H.nav, days: value(H.evidenced_days),
      since: H.evidenced_anchor || null };
  }
  const b = book(key) || {};
  return { apy: b.apy, drawdown: b.drawdown, nav: b.nav, days: typeof b.days === 'number' ? b.days : null,
    since: null };
}

function resultFor(key, p, ru) {
  const h = (p && p.history) || {};
  const n = h.valid_periods;
  const need = h.reportable_after;
  if (h.state !== 'REPORTABLE') {
    return {
      main: ru ? 'Статистика текущей версии накапливается' : 'Statistics of the current version are accumulating',
      sub: (typeof n === 'number' && typeof need === 'number')
        ? (ru ? `валидных дней: ${n} из ${need} — результат не публикуется до ${need}` : `${n} of ${need} valid days — no result is published before ${need}`)
        : (ru ? 'число валидных дней не измерено' : 'valid days not measured'),
      measured: false,
    };
  }
  // One definition for all three: the current version's realized, annualised paper rate — from the shelf.
  const f = shelfFigures(key);
  if (value(f.apy) == null || f.days == null) {
    return { main: ru ? 'результат не измерен' : 'result not measured',
      sub: ru ? 'в публикуемой витрине нет ставки текущей версии' : 'the published shelf carries no rate for the current version',
      measured: false };
  }
  const since = f.since || h.first_period || '—';
  const start = threshold('start_capital');
  const navTxt = value(f.nav) != null
    ? (ru ? ` · стоимость книги ${figUsd(f.nav, true)} при стартовых ${figUsd(start, true)}` : ` · book value ${figUsd(f.nav)} on a ${figUsd(start)} start`)
    : '';
  return {
    main: figPct(f.apy, ru),
    unit: ru ? 'годовых, фактически на бумаге' : 'annualised, realized on paper',
    sub: ru
      ? `${f.days} дн. с ${since}${navTxt} · замер ${NUMBERS.measured_at || '—'} (публикация раз в неделю)`
      : `${f.days} days since ${since}${navTxt} · measured ${NUMBERS.measured_at || '—'} (published weekly)`,
    measured: true,
  };
}

function drawdownFor(key, p, ru) {
  const h = (p && p.history) || {};
  if (h.state !== 'REPORTABLE') {
    return ru ? 'не публикуется, пока статистика текущей версии накапливается'
      : 'not published while the current version’s statistics accumulate';
  }
  const f = shelfFigures(key);
  if (value(f.drawdown) == null) return ru ? 'наблюдавшаяся просадка не измерена' : 'observed drawdown not measured';
  const s = figPct({ value: Math.abs(value(f.drawdown)) }, ru, 2);
  return ru
    ? `${s} за ${f.days} дн. текущей версии — прошлое наблюдение, не предел убытка`
    : `${s} over ${f.days} days of the current version — a past observation, not a loss limit`;
}

function stopFor(key, ru) {
  const ss = C.sleeve_stops || {};
  const soft = value(threshold('kill_switch_soft'));
  const hard = value(threshold('kill_switch_hard'));
  if (key === 'conservative') {
    if (soft == null || hard == null) return ru ? 'порог не прочитан из витрины' : 'threshold not read from the shelf';
    return ru
      ? `−${soft}% от пика → новые позиции не открываются (держит и сокращает); −${hard}% → всё в кэш`
      : `−${soft}% from peak → no new positions (hold and reduce only); −${hard}% → all to cash`;
  }
  if (key === 'balanced') {
    return ru
      ? `−${ss.balanced_stop_pct}% от пика → книга прекращает сделки, позиции сохраняются`
      : `−${ss.balanced_stop_pct}% from peak → the book stops trading; positions are kept`;
  }
  return ru
    ? `−${ss.aggressive_stop_pct}% от пика → петля закрывается, книга прекращает сделки; раньше петля сама сокращается и закрывается по фактору здоровья и цене USDe`
    : `−${ss.aggressive_stop_pct}% from peak → the loop is unwound and the book stops trading; before that the loop deleverages and unwinds on its own health-factor and USDe-price triggers`;
}

/** The research target, if one is published: the first segment of the canonical tier band. */
export function researchTarget(key, ru) {
  const b = TIER_BANDS[key];
  const band = b && (ru ? b.band_ru : b.band_en);
  if (!band) return null;
  return String(band).split(' · ')[0];
}

/** Everything a card prints, in the fixed order of the owner's format. */
export function cardModel(key, rec, nowMs, lang) {
  const ru = lang === 'ru';
  const p = effective(rec, nowMs);
  if (!p) {
    const na = ru ? 'не измерено' : 'not measured';
    return { key, missing: true, work: { tone: 'warn', label: ru ? 'Статус недоступен' : 'Status unavailable', reason: na } };
  }
  const L = (m, s) => (m[s] || { tone: 'warn', en: s || 'not measured', ru: s || 'не измерено' });
  const w = L(WORK, p.work && p.work.state);
  const d = L(DATA, p.data && p.data.state);
  const dec = L(DECISION, p.decision && p.decision.state);
  const hi = L(HISTORY, p.history && p.history.state);
  const lv = L(LIVE, p.mode && p.mode.live);
  const f = p.freshness || {};
  const pick = (o, k) => (o ? (ru ? o[k + '_ru'] : o[k + '_en']) : null);
  return {
    key,
    expired: !!p.expired,
    // green means «working AND its data is fresh»: a running process with stale or incomplete data is
    // shown as running, in yellow, next to the data warning — never as one green badge
    work: { state: p.work && p.work.state,
      tone: (w.tone === 'ok' && p.data && p.data.state !== 'HEALTHY') ? 'warn' : w.tone,
      label: ru ? w.ru : w.en, reason: pick(p.work, 'reason') },
    data: { state: p.data && p.data.state, tone: d.tone, label: ru ? d.ru : d.en, reason: pick(p.data, 'reason'),
      missed: (p.data && typeof p.data.missed_runs_24h === 'number' && p.data.missed_runs_24h > 0)
        ? (ru ? `пропущено плановых запусков за 24 ч: ${p.data.missed_runs_24h}` : `${p.data.missed_runs_24h} scheduled run(s) missed in 24 h`)
        : null },
    live: { state: p.mode && p.mode.live, tone: lv.tone, label: ru ? lv.ru : lv.en, reason: pick(p.mode, 'live_reason') },
    mode: ru ? 'только бумага, реального капитала нет' : 'paper only, no real capital',
    mechanic: pick(p, 'mechanic_short'),
    version: p.running_version || null,
    experiment: p.experiment_id || null,
    pending: p.new_version_pending ? p.new_version_pending.strategy_version : null,
    decision: { state: p.decision && p.decision.state, label: ru ? dec.ru : dec.en,
      position: pick(p.decision, 'position'), reason: pick(p.decision, 'reason'), defect: pick(p.decision, 'defect'),
      date: p.decision && p.decision.decision_date },
    result: resultFor(key, p, ru),
    costs: ru ? COSTS[key].ru : COSTS[key].en,
    history: { state: p.history && p.history.state,
      label: (ru ? hi.ru : hi.en) + ((p.history && typeof p.history.valid_periods === 'number' && typeof p.history.reportable_after === 'number')
        ? (ru ? ` — валидных дней текущей версии: ${p.history.valid_periods} (отчёт с ${p.history.reportable_after})`
              : ` — ${p.history.valid_periods} valid days of the current version (report from ${p.history.reportable_after})`)
        : ''),
      n: p.history && p.history.valid_periods, need: p.history && p.history.reportable_after,
      since: p.history && p.history.first_period, earlier: p.history && p.history.earlier_rows_kept },
    risk: { profile: ru ? RISK_PROFILE[key].ru : RISK_PROFILE[key].en, drawdown: drawdownFor(key, p, ru), stop: stopFor(key, ru) },
    freshness: { last_run: when(f.last_successful_run_at), observed: when(f.source_observed_at),
      schedule: ru ? f.schedule_ru : f.schedule_en, stale_at: when(f.stale_at) },
    target: researchTarget(key, ru),
  };
}

/** Both languages at once — what a server-rendered node needs for the site's data-ru toggle. */
export function cardModels(key, rec, nowMs) {
  return { en: cardModel(key, rec, nowMs, 'en'), ru: cardModel(key, rec, nowMs, 'ru') };
}
