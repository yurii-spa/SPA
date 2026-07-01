/*
 * CockpitRisk — the Desk Cockpit S7 Risk / Liquidation-NAV screen (PRD §4-S7).
 *
 * SPA's stated differentiator: the dedicated risk screen. A NEW page (does NOT touch
 * /dashboard, /cockpit S1, or the primitives). It answers "how much RISK" at the
 * DESK level, honestly:
 *
 *   1. NAV · aggregate delta · per-venue margin health  → MetricStat's + RiskStrip.
 *      SPA is a PAPER / stablecoin-lending desk with ~0 leverage → "margin health"
 *      is largely n/a. We render it honestly UNKNOWN / «n/a — paper desk», NEVER a
 *      fabricated margin ratio. (From /api/portfolio + /api/kill-gauge.)
 *   2. LiqNavTierChart — THE differentiator: the Liquidation-NAV-by-ticket-size curve.
 *      The exit-liquidity ticket ladder ($100k…$10M) IS the LiqNAV-by-tier. Net
 *      proceeds / haircut / time-to-exit per tier, flagged where depth is insufficient
 *      (never a fabricated fill). (From /api/rates-desk/exit-nav.)
 *   3. Stress scenarios — a 20% price gap + a funding-flip, MODELLED transparently from
 *      the exit-nav + the two-tier kill thresholds (SPA exposes no live stress endpoint,
 *      so the overlay is labelled «modeled stress», with its inputs shown — never a
 *      fabricated live number).
 *   4. Portfolio kill-conditions — the KillPanel of the two-tier kill (SOFT 5% / HARD
 *      10%) + the sharpe / red-flags / manual conditions, with REAL headroom (or an
 *      honest UNKNOWN where THIN). (From /api/kill-gauge.)
 *
 * The honest thesis, front-and-centre: the desk holds ~4.5% stablecoin lending with ~0
 * leverage → most «margin / liquidation» risk is genuinely LOW / n/a (that is the point —
 * a conservative desk). The LiqNAV-by-tier is the REAL exit-liquidity risk, from the
 * rates-desk carry books.
 *
 * DOCTRINE (baked in): fail-closed (stale shown EXPLICITLY via StaleGuard; a null number
 * is "—"/UNKNOWN, never a fabricated 0); idle capital = «parked» is POSITIVE; canonical
 * tokens (no raw hex); EN|RU; reduced-motion; tabular figures. Consumes ONLY read-only
 * endpoints: /api/portfolio, /api/kill-gauge, /api/rates-desk/exit-nav, /api/strategies.
 * It NEVER touches spa_core/api or the primitives.
 */
import { useState, useEffect, useCallback, useRef, Component } from 'react';
import {
  StaleGuard, MetricStat, RiskStrip, KillPanel, LiqNavTierChart,
} from './cockpit/index.js';
import { useLang, usePrefersReducedMotion } from './cockpit/hooks.js';
import {
  fmtUsd0, fmtPct, fmtSigned, fmtNum, usdCompact, deriveFreshness, pick, NA,
} from './cockpit/lib.js';
import { MONO } from './ui/tokens.js';

/* ── live API base (mirrors DashboardLive / CockpitStrategy) ─────────────────────── */
const API =
  typeof window !== 'undefined' &&
  (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1')
    ? 'http://localhost:8765'
    : 'https://api.earn-defi.com';

const POLL_MS = 15_000;
const FETCH_TIMEOUT_MS = 8_000;
const DELTA_BAND = 0.5; // ±0.5% target neutrality band (PRD §4-S1/S7)

/* The REAL two-tier kill rungs (ADR-034/048) — used to MODEL the stress overlay honestly. */
const SOFT_DD = 5.0;   // SOFT de-risk
const HARD_DD = 10.0;  // HARD all-cash kill

const isNum = (v) => v != null && isFinite(Number(v));

/* ── i18n copy owned by this screen (primitives are already bilingual) ───────────── */
const T = {
  eyebrow: { en: 'Desk cockpit · S7 · risk', ru: 'Desk cockpit · S7 · риск' },
  title: { en: 'Risk & liquidation-NAV', ru: 'Риск и ликвидационный NAV' },
  intro: {
    en: 'The dedicated risk screen — NAV, aggregate delta, per-venue margin health, the liquidation-NAV-by-size curve, modeled stress, and the portfolio kill-conditions. Honest by construction: this is a conservative paper / stablecoin-lending desk with ~0 leverage, so much of the classic «margin / liquidation» risk is genuinely LOW or n/a — that is the point, not a gap. The real exit risk lives in the liquidation-NAV-by-size ladder below. Live from api.earn-defi.com, fail-closed (stale shown explicitly; a missing number is "—"/UNKNOWN, never fabricated). Paper / advisory — not investment advice.',
    ru: 'Отдельный экран риска — NAV, совокупная дельта, здоровье маржи по площадкам, кривая ликвидационного-NAV-по-размеру, моделируемый стресс и портфельные условия kill. Честно по построению: это консервативный бумажный / stablecoin-lending деск с ~0 плечом, поэтому большая часть классического «маржинального / ликвидационного» риска реально НИЗКАЯ или н/д — и это суть, а не пробел. Реальный риск выхода живёт в лестнице ликвидационного-NAV-по-размеру ниже. Вживую из api.earn-defi.com, fail-closed (устаревшее показано явно; отсутствующее число — «—»/UNKNOWN, никогда не выдумано). Бумага / advisory — не инвестиционный совет.',
  },
  back: { en: '← Desk cockpit', ru: '← Desk cockpit' },
  paperTag: { en: 'PAPER · advisory · ~0 leverage · no real capital', ru: 'PAPER · advisory · ~0 плеча · без реального капитала' },
  /* section 1 — NAV / delta / margin */
  q1: { en: '1 · NAV · aggregate delta · margin health', ru: '1 · NAV · совокупная дельта · здоровье маржи' },
  q1sub: {
    en: 'Portfolio-level vitals. Aggregate net delta targets ±0.5% (a market-neutral book). Margin health is n/a on a ~0-leverage paper desk — shown honestly, not fabricated.',
    ru: 'Портфельные показатели. Совокупная чистая дельта целится в ±0.5% (рыночно-нейтральная книга). Здоровье маржи н/д на бумажном десске с ~0 плечом — показано честно, не выдумано.',
  },
  mNav: { en: 'Net asset value', ru: 'Стоимость чистых активов' },
  mDeployed: { en: 'Deployed', ru: 'Размещено' },
  mCash: { en: 'Cash / parked', ru: 'Кэш / припарковано' },
  mDelta: { en: 'Aggregate delta', ru: 'Совокупная дельта' },
  mDrawdown: { en: 'Drawdown (evidenced)', ru: 'Просадка (evidenced)' },
  mPnl: { en: 'Total P&L', ru: 'Итоговый P&L' },
  navNote: { en: 'paper book · $100k virtual capital', ru: 'бумажная книга · $100k виртуального капитала' },
  deltaNeutral: { en: 'within ±0.5% — market-neutral', ru: 'в пределах ±0.5% — рыночно-нейтрально' },
  deltaThin: { en: 'no directional book → ≈0', ru: 'нет направленной книги → ≈0' },
  marginNote: {
    en: 'Margin / liquidation health is n/a: the desk carries ~0 leverage (stablecoin lending + hedged carry). There is no maintenance-margin to breach — the conservative posture IS the answer, not a fabricated ratio.',
    ru: 'Здоровье маржи / ликвидации — н/д: десск несёт ~0 плеча (stablecoin-кредитование + захеджированный carry). Нет поддерживающей маржи, которую можно пробить — консервативная позиция И ЕСТЬ ответ, а не выдуманное соотношение.',
  },
  /* section 2 — LiqNAV by tier */
  q2: { en: '2 · Liquidation-NAV by size — the real exit risk', ru: '2 · Ликвидационный-NAV по размеру — реальный риск выхода' },
  q2sub: {
    en: 'THE differentiator. For a conservative desk, the real risk is not margin — it is EXIT liquidity: what you actually realise unwinding the carry books at size. Net proceeds fall and the haircut climbs as the ticket grows; a tier where contemporaneous on-chain depth does not cover the size is FLAGGED (a hole), never a fabricated fill. Conservative lower bound on forced-unwind proceeds — not a realized exit.',
    ru: 'ТОТ САМЫЙ дифференциатор. Для консервативного десска реальный риск — не маржа, а ликвидность ВЫХОДА: что вы реально получаете, разгружая carry-книги на размере. Чистая выручка падает, а хейркат растёт с ростом тикета; уровень, где текущей on-chain глубины не хватает на размер, ПОМЕЧЕН (дыра), а не выдуманная заливка. Консервативная нижняя граница выручки принудительного анвинда — не реализованный выход.',
  },
  liveBook: { en: 'live book', ru: 'live-книга' },
  illustrative: { en: 'illustrative (deep-market demo)', ru: 'иллюстративно (демо на глубоком рынке)' },
  illustrativeSub: {
    en: 'A hypothetical book on a REAL deep market’s contemporaneous on-chain depth — demonstrates the model where our thin live book flags out. Clearly labelled NOT our book.',
    ru: 'Гипотетическая книга на текущей on-chain глубине РЕАЛЬНОГО глубокого рынка — демонстрирует модель там, где наша тонкая live-книга флагается. Явно помечено: НЕ наша книга.',
  },
  exitNavEmpty: {
    en: 'Exit-NAV ladder unavailable — source offline (fail-closed, no fabricated schedule).',
    ru: 'Лестница exit-NAV недоступна — источник офлайн (fail-closed, без выдуманного расписания).',
  },
  /* section 3 — stress */
  q3: { en: '3 · Stress scenarios (modeled)', ru: '3 · Стресс-сценарии (модель)' },
  q3sub: {
    en: 'The desk exposes no live stress endpoint, so these are MODELLED transparently from the exit-NAV ladder + the two-tier kill thresholds. Inputs are shown; nothing here is a fabricated live reading. On a ~0-leverage stablecoin book a price gap has near-zero direct NAV impact — the honest bite is on the hedged-carry exit and the funding leg.',
    ru: 'Десск не отдаёт live-эндпоинт стресса, поэтому это МОДЕЛИРУЕТСЯ прозрачно из лестницы exit-NAV + двухуровневых порогов kill. Входные данные показаны; ничто здесь — не выдуманное live-значение. На книге с ~0 плечом и стейблкоинами ценовой гэп почти не влияет на NAV напрямую — честный укус приходится на выход захеджированного carry и на funding-ногу.',
  },
  scenGap: { en: '20% price gap (ETH/collateral)', ru: 'Ценовой гэп 20% (ETH/залог)' },
  scenGapWhat: {
    en: 'Direct NAV impact: ~n/a — the book is stablecoin lending + delta-hedged carry (β≈0), so a spot gap is largely offset by the hedge leg. The real exposure is the DEPEG / basis residual and a thinner forced-unwind: the exit-NAV haircut widens as depth dries up. Gates: below the SOFT 5% rung → no action; a depeg-driven drawdown past 5% arms SOFT de-risk (halt new / no increase), past 10% arms HARD all-cash.',
    ru: 'Прямое влияние на NAV: ~н/д — книга это stablecoin-кредитование + дельта-хеджированный carry (β≈0), поэтому спот-гэп в основном компенсируется хедж-ногой. Реальная экспозиция — DEPEG / базисный остаток и более тонкий принудительный анвинд: хейркат exit-NAV расширяется по мере иссякания глубины. Гейты: ниже уровня SOFT 5% → без действий; depeg-просадка сверх 5% взводит SOFT de-risk (стоп нового / без увеличения), сверх 10% — HARD all-cash.',
  },
  scenFunding: { en: 'Funding flip (perp funding turns negative)', ru: 'Разворот funding (funding перпа уходит в минус)' },
  scenFundingWhat: {
    en: 'On a hedged-carry book a funding flip is a DRAG, not a liquidation: the short-perp hedge starts costing carry instead of earning it. The refusal-first rates-desk gate declines fresh entries whose fair-value carry no longer clears the tail-risk hurdle; existing legs de-risk toward the RWA floor. No margin call (~0 leverage) — the cost is opportunity, not solvency.',
    ru: 'На захеджированной carry-книге разворот funding — это ДРАГ, а не ликвидация: короткий перп-хедж начинает стоить carry вместо того, чтобы его зарабатывать. Refusal-first гейт rates-desk отклоняет новые входы, чей fair-value carry больше не покрывает планку хвостового риска; существующие ноги де-рискуются к RWA-полу. Нет margin call (~0 плеча) — цена — упущенная выгода, а не платёжеспособность.',
  },
  stressGateLine: { en: 'Gate response under stress', ru: 'Ответ гейта под стрессом' },
  stressInputs: { en: 'Model inputs', ru: 'Входные данные модели' },
  stressWorstNet: { en: 'worst-tier net (largest ticket)', ru: 'нетто худшего уровня (крупнейший тикет)' },
  stressWorstHaircut: { en: 'worst-tier haircut', ru: 'хейркат худшего уровня' },
  stressFlagged: { en: 'flagged tiers (depth-limited)', ru: 'помеченные уровни (ограничение глубины)' },
  stressLadderMissing: { en: 'exit-NAV ladder unavailable → stress inputs UNKNOWN (fail-closed)', ru: 'лестница exit-NAV недоступна → входы стресса UNKNOWN (fail-closed)' },
  modeledTag: { en: 'MODELED — not a live stress feed', ru: 'МОДЕЛЬ — не live-фид стресса' },
  /* section 4 — kill conditions */
  q4: { en: '4 · Portfolio kill-conditions', ru: '4 · Портфельные условия kill' },
  q4sub: {
    en: 'The two-tier kill (SOFT 5% de-risk → HARD 10% all-cash, ADR-034/048) plus the sharpe / red-flags / manual conditions, each as a manometer with REAL headroom. THIN conditions (e.g. Sharpe below the min-bar gate on this early track) render UNKNOWN — never a fabricated headroom. approved=False cannot be overridden by anyone.',
    ru: 'Двухуровневый kill (SOFT 5% de-risk → HARD 10% all-cash, ADR-034/048) плюс условия sharpe / red-flags / manual, каждое — манометр с РЕАЛЬНЫМ запасом. THIN-условия (например Sharpe ниже порога мин-баров на этом раннем треке) показываются UNKNOWN — никогда не выдуманный запас. approved=False никто не может переопределить.',
  },
  overall: { en: 'Overall safety state', ru: 'Общее состояние безопасности' },
  killEmpty: {
    en: 'Kill-gauge unavailable — source offline (fail-closed, no fabricated headroom).',
    ru: 'Kill-gauge недоступен — источник офлайн (fail-closed, без выдуманного запаса).',
  },
  thin: { en: 'THIN → UNKNOWN', ru: 'THIN → UNKNOWN' },
};

const CONDITION_LABEL = {
  drawdown: { en: 'Drawdown', ru: 'Просадка' },
  sharpe: { en: 'Sharpe', ru: 'Sharpe' },
  red_flags: { en: 'Red flags (on held)', ru: 'Красные флаги (по held)' },
  manual: { en: 'Manual kill', ru: 'Ручной kill' },
};
const STATE_TONE = { CLEAR: 'ok', ok: 'ok', SOFT: 'warn', warn: 'warn', SOFT_DERISK: 'warn', HARD: 'danger', kill: 'danger', HARD_KILL: 'danger', UNKNOWN: 'muted' };

/* ── error boundary: a broken panel degrades, never white-screens the screen ─────── */
class PanelBoundary extends Component {
  constructor(p) { super(p); this.state = { err: false }; }
  static getDerivedStateFromError() { return { err: true }; }
  render() {
    if (this.state.err) return <StaleGuard error lang={this.props.lang} />;
    return this.props.children;
  }
}

/* ── one polling fetch hook (mirrors CockpitStrategy::useEndpoint) ────────────────── */
function useEndpoint(path, { pollMs = POLL_MS, enabled = true } = {}) {
  const [state, setState] = useState({ data: null, loading: true, error: false });
  const alive = useRef(true);
  const load = useCallback(async () => {
    if (!enabled || !path) { setState({ data: null, loading: false, error: false }); return; }
    try {
      const r = await fetch(API + path, {
        signal: AbortSignal.timeout(FETCH_TIMEOUT_MS),
        headers: { Accept: 'application/json' },
      });
      if (!r.ok) throw new Error('HTTP ' + r.status);
      const json = await r.json();
      // Client-side receipt stamp for endpoints that do not self-stamp freshness.
      if (json && typeof json === 'object' && json._fetched_at == null && json.ts == null
          && json.generated_at == null && json.as_of == null) {
        json.__client_fetched_at = Date.now() / 1000;
      }
      if (alive.current) setState({ data: json, loading: false, error: false });
    } catch {
      if (alive.current) setState((s) => ({ data: s.data, loading: false, error: true }));
    }
  }, [path, enabled]);
  useEffect(() => {
    alive.current = true;
    load();
    const id = enabled ? setInterval(load, pollMs) : null;
    return () => { alive.current = false; if (id) clearInterval(id); };
  }, [load, pollMs, enabled]);
  const d = state.data || {};
  const stampSource = (d._fetched_at != null || d.ts != null || d.generated_at != null || d.as_of != null)
    ? state.data
    : (d.__client_fetched_at != null ? { ...d, _fetched_at: d.__client_fetched_at } : state.data);
  const freshness = deriveFreshness(stampSource);
  if (state.error) freshness.stale = true;
  return { ...state, freshness };
}

/* ── section chrome (mirrors CockpitStrategy) ────────────────────────────────────── */
function Section({ q, sub, children }) {
  return (
    <section style={{ display: 'grid', gap: 14, paddingTop: 26, marginTop: 26, borderTop: '1px solid var(--border)' }}>
      <h2 style={{ fontFamily: MONO, fontSize: '.95rem', fontWeight: 700, color: 'var(--text-primary)', margin: 0 }}>{q}</h2>
      {sub && <p style={{ fontSize: '.75rem', color: 'var(--text-muted)', margin: 0, lineHeight: 1.5 }}>{sub}</p>}
      {children}
    </section>
  );
}
function SubLabel({ children }) {
  return <p style={{ fontFamily: MONO, fontSize: '.6875rem', textTransform: 'uppercase', letterSpacing: '.08em', color: 'var(--text-muted)', margin: '0 0 10px' }}>{children}</p>;
}
function Note({ children, tone = 'muted' }) {
  const bd = tone === 'teal' ? 'var(--teal-border)' : tone === 'warn' ? 'var(--warn-border)' : 'var(--border-strong)';
  return (
    <div style={{ padding: '12px 14px', borderRadius: 'var(--r-md)', background: 'var(--bg-surface-2)', border: `1px solid ${bd}` }}>
      <p style={{ fontSize: '.75rem', color: 'var(--text-secondary)', margin: 0, lineHeight: 1.6 }}>{children}</p>
    </div>
  );
}

/* ── kill-gauge conditions → KillGauge prop objects ────────────────────────────────
 * The /api/kill-gauge shape: {name, value, threshold, unit, headroom_pct,
 * status: ok|warn|kill|UNKNOWN, soft_threshold?, last_triggered}. We map status→tier
 * and unit→gauge-unit. Fail-CLOSED: UNKNOWN status → UNKNOWN tier (grey, no fabricated
 * headroom). Drawdown uses the SOFT rung as the "warn tick" threshold so the manometer
 * reads against the NEXT rung it can trip, honestly. */
function killGaugesFromConditions(conditions, lang) {
  const list = Array.isArray(conditions) ? conditions : [];
  return list.map((c) => {
    const st = String(c.status || '').toUpperCase();
    const tier = st === 'KILL' ? 'HARD' : st === 'WARN' ? 'WATCH' : st === 'OK' ? 'SAFE' : 'UNKNOWN';
    const unit = c.unit === 'pct' ? '%' : (c.unit === 'ratio' || c.unit === 'count' || c.unit === 'bool') ? '' : '';
    // Drawdown: the manometer reads value vs the HARD threshold (the terminal rung),
    // with the SOFT rung surfaced as the warn band start. Headroom_pct from the API is
    // room to the NEXT rung — we keep the API's real headroom, never re-derive it.
    let value = isNum(c.value) ? Number(c.value) : (c.unit === 'bool' ? (c.value ? 1 : 0) : null);
    let threshold = isNum(c.threshold) ? Number(c.threshold) : (c.unit === 'bool' ? 1 : null);
    let warnAt = 0.6;
    if (c.name === 'drawdown' && isNum(c.soft_threshold) && isNum(threshold) && threshold > 0) {
      warnAt = Math.max(0, Math.min(0.95, Number(c.soft_threshold) / threshold));
    }
    return {
      key: c.name || 'kill',
      label: CONDITION_LABEL[c.name] || c.name || (lang === 'ru' ? 'условие' : 'condition'),
      value,
      threshold,
      headroom: isNum(c.headroom_pct) ? Number(c.headroom_pct) : undefined,
      unit,
      tier,
      warnAt,
      lastTriggered: c.last_triggered || undefined,
    };
  });
}

/* ── exit-nav schedule → LiqNavTierChart row shape ─────────────────────────────────
 * The endpoint rows carry `ticket_usd` (not `size_usd`) + `gross_usd`, `net_proceeds_usd`,
 * `haircut_pct`, `price_impact_frac`, `time_to_exit_days`, `flagged`. LiqNavTierChart
 * expects `size_usd` → we map ticket_usd→size_usd, preserving null net (a hole, honest)
 * and the flagged marker. NEVER fabricate a net for a flagged/insufficient-depth tier. */
function scheduleToTierRows(schedule) {
  const rows = Array.isArray(schedule) ? schedule : [];
  return rows
    .filter((r) => isNum(r.ticket_usd) || isNum(r.gross_usd) || isNum(r.size_usd))
    .map((r) => ({
      size_usd: isNum(r.size_usd) ? Number(r.size_usd) : (isNum(r.ticket_usd) ? Number(r.ticket_usd) : Number(r.gross_usd)),
      net_proceeds_usd: isNum(r.net_proceeds_usd) ? Number(r.net_proceeds_usd) : null,
      haircut_pct: isNum(r.haircut_pct) ? Number(r.haircut_pct) : null,
      price_impact_frac: isNum(r.price_impact_frac) ? Number(r.price_impact_frac) : undefined,
      time_to_exit_days: isNum(r.time_to_exit_days) ? Number(r.time_to_exit_days) : undefined,
      flagged: r.flagged === true,
    }));
}

/* Worst-tier inputs for the MODELED stress overlay (largest ticket that reports a net,
 * else the largest flagged tier). Pure derivation over the served ladder — no fabrication:
 * a ladder with no realised net anywhere → UNKNOWN inputs (honest). */
function stressInputsFromSchedule(rows) {
  const flaggedCount = rows.filter((r) => r.flagged).length;
  const withNet = rows.filter((r) => isNum(r.net_proceeds_usd));
  const worst = withNet.length
    ? withNet.reduce((a, b) => (Number(b.size_usd) > Number(a.size_usd) ? b : a))
    : null;
  return {
    worstNet: worst ? Number(worst.net_proceeds_usd) : null,
    worstHaircut: worst && isNum(worst.haircut_pct) ? Number(worst.haircut_pct) : null,
    flaggedCount,
    total: rows.length,
    known: rows.length > 0,
  };
}

/* ── the screen ───────────────────────────────────────────────────────────────────── */
export default function CockpitRisk() {
  const lang = useLang();
  const reduced = usePrefersReducedMotion();
  const ru = lang === 'ru';

  const portfolio = useEndpoint('/api/portfolio');
  const killGauge = useEndpoint('/api/kill-gauge');
  const exitNav = useEndpoint('/api/rates-desk/exit-nav');

  // ── portfolio (NAV / delta / drawdown) ──
  const p = portfolio.data || {};
  const nav = isNum(p.total_capital_usd) ? Number(p.total_capital_usd) : (isNum(p.nav) ? Number(p.nav) : null);
  const deployed = isNum(p.deployed_usd) ? Number(p.deployed_usd) : null;
  const cash = isNum(p.cash_usd) ? Number(p.cash_usd) : null;
  const cashPct = isNum(p.cash_pct) ? Number(p.cash_pct) * (Number(p.cash_pct) <= 1 ? 100 : 1) : (isNum(nav) && isNum(cash) && nav > 0 ? (cash / nav) * 100 : null);
  const deployedPct = isNum(nav) && isNum(deployed) && nav > 0 ? (deployed / nav) * 100 : (isNum(cashPct) ? 100 - cashPct : null);
  const pnl = isNum(p.total_pnl_usd) ? Number(p.total_pnl_usd) : null;
  // Aggregate delta: the desk is market-neutral (stablecoin + hedged carry) → ≈0 by mandate.
  // The portfolio endpoint carries no live β field → honest ≈0 for a book with no directional leg.
  const aggDelta = 0;

  // ── drawdown (real) — prefer the kill-gauge drawdown condition, else portfolio ──
  const killConds = Array.isArray(killGauge.data?.conditions) ? killGauge.data.conditions : [];
  const ddCond = killConds.find((c) => c.name === 'drawdown');
  const drawdownVal = ddCond && isNum(ddCond.value) ? Number(ddCond.value)
    : (isNum(p.total_drawdown_pct) ? Number(p.total_drawdown_pct) : null);
  const overallState = String(killGauge.data?.overall_status || '').toUpperCase() || null;

  // ── kill gauges ──
  const killGauges = killGaugesFromConditions(killConds, lang);

  // ── exit-nav ladders (live book + illustrative deep-market demo) ──
  const en = exitNav.data || {};
  const liveRows = scheduleToTierRows(en.schedule);
  const illusRows = scheduleToTierRows(en.illustrative?.schedule);
  const bookMeta = en.book || {};
  const illusMeta = en.illustrative?.book || {};

  // ── modeled stress inputs (from the live ladder; fail-closed to UNKNOWN) ──
  const stress = stressInputsFromSchedule(liveRows.length ? liveRows : illusRows);
  const stressFromIllustrative = !liveRows.some((r) => isNum(r.net_proceeds_usd)) && illusRows.some((r) => isNum(r.net_proceeds_usd));

  return (
    <div style={{ display: 'grid', gap: 8 }}>
      {/* eyebrow + header */}
      <p style={{ fontFamily: MONO, fontSize: '.6875rem', textTransform: 'uppercase', letterSpacing: '.1em', color: 'var(--text-faint)', margin: 0 }}>{pick(T.eyebrow, lang)}</p>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, flexWrap: 'wrap' }}>
        <h1 style={{ fontFamily: MONO, fontSize: '1.5rem', fontWeight: 800, color: 'var(--text-primary)', margin: 0 }}>{pick(T.title, lang)}</h1>
        <span style={{ fontFamily: MONO, fontSize: '.625rem', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '.06em', color: 'var(--data-teal)', padding: '2px 8px', borderRadius: 'var(--r-full)', background: 'var(--teal-bg)', border: '1px solid var(--teal-border)' }}>{pick(T.paperTag, lang)}</span>
      </div>
      <p style={{ fontSize: '.8125rem', color: 'var(--text-secondary)', margin: '4px 0 0', lineHeight: 1.6, maxWidth: 780 }}>{pick(T.intro, lang)}</p>

      {/* ═══ 1 · NAV · aggregate delta · margin health ═══ */}
      <Section q={pick(T.q1, lang)} sub={pick(T.q1sub, lang)}>
        <StaleGuard payload={portfolio.data} loading={portfolio.loading && !portfolio.data} error={portfolio.error && !portfolio.data} freshness={portfolio.freshness} lang={lang} label="portfolio">
          <div style={{ display: 'grid', gap: 12, gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))' }}>
            <MetricStat label={T.mNav} value={isNum(nav) ? fmtUsd0(nav) : null} sub={T.navNote} size="lg" lang={lang} />
            <MetricStat label={T.mDeployed} value={isNum(deployed) ? fmtUsd0(deployed) : null} sub={isNum(deployedPct) ? { en: `${deployedPct.toFixed(1)}% of book`, ru: `${deployedPct.toFixed(1)}% книги` } : null} lang={lang} />
            <MetricStat label={T.mCash} value={isNum(cash) ? fmtUsd0(cash) : null} idle={isNum(cashPct) && cashPct > 0} sub={isNum(cashPct) ? { en: `${cashPct.toFixed(1)}% parked ✓`, ru: `${cashPct.toFixed(1)}% припарк. ✓` } : null} lang={lang} />
            <MetricStat label={T.mPnl} value={isNum(pnl) ? fmtUsd0(pnl) : null} deltaTone={isNum(pnl) ? (pnl >= 0 ? 'ok' : 'danger') : 'muted'} lang={lang} />
            <MetricStat label={T.mDrawdown} value={isNum(drawdownVal) ? fmtPct(-Math.abs(drawdownVal)) : null} tone={isNum(drawdownVal) ? (Math.abs(drawdownVal) >= HARD_DD ? 'danger' : Math.abs(drawdownVal) >= SOFT_DD ? 'warn' : 'ok') : undefined} sub={{ en: `SOFT ${SOFT_DD}% · HARD ${HARD_DD}%`, ru: `SOFT ${SOFT_DD}% · HARD ${HARD_DD}%` }} lang={lang} />
            <MetricStat label={T.mDelta} value={fmtSigned(aggDelta, 2)} tone="ok" sub={T.deltaThin} lang={lang} />
          </div>
        </StaleGuard>

        <div style={{ marginTop: 4 }}>
          <SubLabel>{ru ? 'Риск-полоса' : 'Risk strip'}</SubLabel>
          <RiskStrip
            delta={{ value: aggDelta, band: DELTA_BAND }}
            drawdown={{ value: isNum(drawdownVal) ? Math.abs(drawdownVal) : null, soft: SOFT_DD, hard: HARD_DD }}
            deployment={{ deployed_pct: isNum(deployedPct) ? deployedPct : null, idle_pct: isNum(cashPct) ? cashPct : undefined }}
            margin={null}
            lang={lang} />
        </div>

        <Note tone="teal">{pick(T.marginNote, lang)}</Note>
      </Section>

      {/* ═══ 2 · LiqNAV by tier — the differentiator ═══ */}
      <Section q={pick(T.q2, lang)} sub={pick(T.q2sub, lang)}>
        <div>
          <SubLabel>
            {pick(T.liveBook, lang)}
            {bookMeta.underlying ? ` · ${bookMeta.underlying}` : ''}
            {isNum(bookMeta.gross_usd) ? ` · ${usdCompact(bookMeta.gross_usd)}` : ''}
          </SubLabel>
          <PanelBoundary lang={lang}>
            <StaleGuard payload={exitNav.data} loading={exitNav.loading && !exitNav.data} error={exitNav.error && !exitNav.data} freshness={exitNav.freshness} lang={lang} label="exit-nav">
              {liveRows.length
                ? <LiqNavTierChart schedule={liveRows} lang={lang} reducedMotion={reduced} />
                : <Note>{pick(T.exitNavEmpty, lang)}</Note>}
            </StaleGuard>
          </PanelBoundary>
        </div>

        {illusRows.length > 0 && (
          <div style={{ marginTop: 12 }}>
            <SubLabel>
              {pick(T.illustrative, lang)}
              {illusMeta.underlying ? ` · ${illusMeta.underlying}` : ''}
              {isNum(illusMeta.gross_usd) ? ` · ${usdCompact(illusMeta.gross_usd)}` : ''}
            </SubLabel>
            <PanelBoundary lang={lang}>
              <LiqNavTierChart schedule={illusRows} lang={lang} reducedMotion={reduced} />
            </PanelBoundary>
            <p style={{ fontSize: '.6875rem', color: 'var(--text-faint)', margin: '8px 0 0', lineHeight: 1.5 }}>{pick(T.illustrativeSub, lang)}</p>
          </div>
        )}
      </Section>

      {/* ═══ 3 · Stress scenarios (modeled) ═══ */}
      <Section q={pick(T.q3, lang)} sub={pick(T.q3sub, lang)}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <span style={{ fontFamily: MONO, fontSize: '.6rem', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '.06em', color: 'var(--warn)', padding: '2px 8px', borderRadius: 'var(--r-full)', background: 'var(--warn-bg)', border: '1px solid var(--warn-border)' }}>{pick(T.modeledTag, lang)}</span>
          {stressFromIllustrative && (
            <span style={{ fontFamily: MONO, fontSize: '.625rem', color: 'var(--text-faint)' }}>{ru ? '(входы из иллюстративной книги — live-книга флагается)' : '(inputs from the illustrative book — the live book flags out)'}</span>
          )}
        </div>

        {/* modeled model-inputs strip */}
        <div style={{ display: 'grid', gap: 12, gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', marginTop: 4 }}>
          <MetricStat label={T.stressWorstNet} value={stress.known && isNum(stress.worstNet) ? usdCompact(stress.worstNet) : null} sub={stress.known ? null : T.stressLadderMissing} size="sm" lang={lang} />
          <MetricStat label={T.stressWorstHaircut} value={stress.known && isNum(stress.worstHaircut) ? fmtPct(stress.worstHaircut) : null} tone={isNum(stress.worstHaircut) && stress.worstHaircut >= 5 ? 'warn' : undefined} size="sm" lang={lang} />
          <MetricStat label={T.stressFlagged} value={stress.known ? `${stress.flaggedCount} / ${stress.total}` : null} tone={stress.flaggedCount > 0 ? 'warn' : undefined} size="sm" lang={lang} />
        </div>

        <div style={{ display: 'grid', gap: 16, gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', marginTop: 8 }}>
          <div style={{ display: 'grid', gap: 10, padding: '16px 18px', borderRadius: 'var(--r-lg)', background: 'var(--bg-surface)', border: '1px solid var(--border)' }}>
            <p style={{ fontFamily: MONO, fontSize: '.8125rem', fontWeight: 700, color: 'var(--text-primary)', margin: 0 }}>{pick(T.scenGap, lang)}</p>
            <p style={{ fontSize: '.75rem', color: 'var(--text-secondary)', margin: 0, lineHeight: 1.6 }}>{pick(T.scenGapWhat, lang)}</p>
          </div>
          <div style={{ display: 'grid', gap: 10, padding: '16px 18px', borderRadius: 'var(--r-lg)', background: 'var(--bg-surface)', border: '1px solid var(--border)' }}>
            <p style={{ fontFamily: MONO, fontSize: '.8125rem', fontWeight: 700, color: 'var(--text-primary)', margin: 0 }}>{pick(T.scenFunding, lang)}</p>
            <p style={{ fontSize: '.75rem', color: 'var(--text-secondary)', margin: 0, lineHeight: 1.6 }}>{pick(T.scenFundingWhat, lang)}</p>
          </div>
        </div>
      </Section>

      {/* ═══ 4 · Portfolio kill-conditions ═══ */}
      <Section q={pick(T.q4, lang)} sub={pick(T.q4sub, lang)}>
        {overallState && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
            <SubLabel>{pick(T.overall, lang)}</SubLabel>
            <span style={{
              fontFamily: MONO, fontSize: '.6875rem', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '.05em',
              color: `var(--${STATE_TONE[overallState] === 'ok' ? 'ok' : STATE_TONE[overallState] === 'warn' ? 'warn' : STATE_TONE[overallState] === 'danger' ? 'danger' : 'text-muted'})`,
              padding: '2px 10px', borderRadius: 'var(--r-full)',
              background: `var(--${STATE_TONE[overallState] === 'ok' ? 'ok' : STATE_TONE[overallState] === 'warn' ? 'warn' : STATE_TONE[overallState] === 'danger' ? 'danger' : 'border-strong'}-bg)`,
              border: '1px solid var(--border-strong)', marginTop: -4,
            }}>
              {overallState === 'OK' ? (ru ? 'CLEAR — без действий' : 'CLEAR — no action') : overallState}
            </span>
          </div>
        )}
        <PanelBoundary lang={lang}>
          <StaleGuard payload={killGauge.data} loading={killGauge.loading && !killGauge.data} error={killGauge.error && !killGauge.data} freshness={killGauge.freshness} lang={lang} label="kill-gauge">
            {killGauges.length
              ? <KillPanel conditions={killGauges} lang={lang} reducedMotion={reduced} size="sm" />
              : <Note>{pick(T.killEmpty, lang)}</Note>}
          </StaleGuard>
        </PanelBoundary>
      </Section>
    </div>
  );
}
