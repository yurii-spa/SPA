/*
 * CockpitPosition — the Desk Cockpit S6 Position / Trade lifecycle drill-down (one position,
 * end to end). A NEW screen (does NOT touch /dashboard, S1, or the primitives). It reads the
 * position key from ?id=<protocol_key> (or ?strategy=, client-rendered — the site is static
 * output, so we cannot getStaticPaths the live paper book; see /board/pool + /cockpit/strategy).
 * S2 (/cockpit/strategy) deep-links here.
 *
 * HONEST FRAMING (load-bearing — the whole reason this file is written carefully):
 * SPA is a PAPER desk holding STABLECOIN LENDING positions (aave / compound / morpho / spark
 * / euler / maple / yearn / …), NOT delta-neutral spot-long/perp-short pairs. So a «position»
 * here is a paper LENDING position: { protocol, asset(stablecoin), size_usd, accrued_yield }.
 * This screen renders THAT, honestly:
 *   1. THE LIFECYCLE:
 *        entry rationale  → the cycle rebalance (/api/trades) that first allocated this protocol
 *        legs             → PositionTable, one LEND leg (protocol · stablecoin · size · net APY).
 *                           The delta-neutral spot-long / perp-short legs DO NOT EXIST for
 *                           lending → rendered UNKNOWN / n-a (NEVER a fabricated spot+perp pair).
 *        funding accrual  → the REAL per-day accrual series (equity_curve_daily.daily[].positions
 *                           + daily_yield_usd, size-weighted to this protocol) — real, not modeled.
 *        delta drift      → n-a: stablecoin lending is β≈0 by construction (no ETH exposure to drift).
 *        exit rationale   → if the protocol left the book, the rebalance that dropped it (which
 *                           condition), else «still open».
 *        realized net     → accrued yield attributable to this position over its life (paper).
 *   2. TIMELINE: hand-rolled SVG lifecycle rail — entry ● · rebalances (size changes) · funding
 *      accrual ticks · exit ●. Events sourced from /api/trades + the per-day accrual series.
 *
 * If the paper book is thin (few days, no per-day accrual for this protocol), it renders what
 * is REAL + an honest «lifecycle detail limited — paper lending position», never a trade story.
 *
 * DOCTRINE: fail-closed (stale shown via StaleGuard; a null number is «—»/UNKNOWN, never a
 * fabricated 0); idle / never-held → positive «capital parked» / honest empty; unknown id →
 * honest «not found»; canonical tokens (no raw hex); EN|RU; reduced-motion; tabular figures.
 * Consumes ONLY read-only endpoints. NEVER touches spa_core/api or the primitives.
 */
import { useState, useEffect, useCallback, useRef, Component } from 'react';
import {
  StaleGuard, MetricStat, PositionTable, EquityChart,
} from './cockpit/index.js';
import { useLang, usePrefersReducedMotion } from './cockpit/hooks.js';
import {
  fmtUsd0, fmtUsd2, fmtPct, fmtSigned, usdCompact, deriveFreshness, pick, NA,
} from './cockpit/lib.js';
import { MONO, TABULAR, toneColor } from './ui/tokens.js';

/* ── live API base (mirrors DashboardLive / CockpitStrategy) ─────────────────────── */
const API =
  typeof window !== 'undefined' &&
  (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1')
    ? 'http://localhost:8765'
    : 'https://api.earn-defi.com';

const POLL_MS = 15_000;
const FETCH_TIMEOUT_MS = 8_000;

const isNum = (v) => v != null && isFinite(Number(v));

function paramsFromUrl() {
  try {
    const q = new URLSearchParams(window.location.search);
    return { id: q.get('id') || '', strategy: q.get('strategy') || '' };
  } catch { return { id: '', strategy: '' }; }
}

/* Protocol-key → a human-ish display name + the stablecoin it lends. Best-effort; unknowns
 * fall through to the raw key + UNKNOWN asset (NEVER fabricate a specific stablecoin). */
const PROTO_META = {
  aave_v3: { name: 'Aave V3', asset: 'USDC' }, aave_arbitrum: { name: 'Aave V3 (Arbitrum)', asset: 'USDC' },
  aave_v3_optimism: { name: 'Aave V3 (Optimism)', asset: 'USDC' }, aave_v3_polygon: { name: 'Aave V3 (Polygon)', asset: 'USDC' },
  aave_v3_base: { name: 'Aave V3 (Base)', asset: 'USDC' }, compound_v3: { name: 'Compound V3', asset: 'USDC' },
  morpho_steakhouse: { name: 'Morpho Steakhouse', asset: 'USDC' }, morpho_blue: { name: 'Morpho Blue', asset: 'USDC' },
  morpho_blue_base: { name: 'Morpho Blue (Base)', asset: 'USDC' }, spark_susds: { name: 'Spark sUSDS', asset: 'sUSDS' },
  euler_v2: { name: 'Euler V2', asset: 'USDC' }, maple: { name: 'Maple', asset: 'USDC' },
  yearn_v3: { name: 'Yearn V3', asset: 'USDC' }, fluid_fusdc: { name: 'Fluid fUSDC', asset: 'USDC' },
  sfrax: { name: 'sFRAX', asset: 'FRAX' }, frax: { name: 'Frax', asset: 'FRAX' }, sdai: { name: 'sDAI', asset: 'DAI' },
  susde: { name: 'Ethena sUSDe', asset: 'sUSDe' }, pendle: { name: 'Pendle PT', asset: 'USDC' },
  wusdm: { name: 'wUSDM', asset: 'USDM' }, scrvusd: { name: 'scrvUSD', asset: 'crvUSD' }, stusd: { name: 'stUSD', asset: 'USDA' },
  moonwell_base: { name: 'Moonwell (Base)', asset: 'USDC' }, extra_finance_base: { name: 'Extra Finance (Base)', asset: 'USDC' },
};
function protoName(key) { return (PROTO_META[key] && PROTO_META[key].name) || key; }
function protoAsset(key) { return (PROTO_META[key] && PROTO_META[key].asset) || null; }

/* ── i18n copy owned by this screen (primitives are already bilingual) ───────────── */
const T = {
  eyebrow: { en: 'Desk cockpit · position lifecycle', ru: 'Desk cockpit · жизненный цикл позиции' },
  intro: {
    en: 'One paper position, end to end — the entry, the legs, the accrued yield over time, the timeline, and (if closed) the exit and realized net. HONEST: SPA is a paper desk holding STABLECOIN LENDING, not a delta-neutral spot/perp trade — so this renders the real lending position; the perp/spot-hedge fields a lending position does not have are shown UNKNOWN / n-a, never fabricated. Live from api.earn-defi.com, fail-closed. Not investment advice.',
    ru: 'Одна бумажная позиция от входа до выхода — вход, ноги, накопленный доход во времени, таймлайн и (если закрыта) выход и реализованный нетто. ЧЕСТНО: SPA — бумажный деск в СТЕЙБЛ-ЛЕНДИНГЕ, а не дельта-нейтральный спот/перп-трейд — поэтому здесь реальная кредитная позиция; поля перп/спот-хеджа, которых у ленда нет, показаны UNKNOWN / н-д, никогда не выдуманы. Вживую из api.earn-defi.com, fail-closed. Не инвестиционный совет.',
  },
  paperTag: { en: 'PAPER · stablecoin lending · no on-chain fills', ru: 'PAPER · стейбл-лендинг · без on-chain fills' },
  lendingNote: {
    en: 'A position here is a PAPER LENDING position (protocol · stablecoin · size · accrued yield) — NOT a delta-neutral spot-long / perp-short pair. The hedge legs a lending position does not carry are shown n-a, never fabricated.',
    ru: 'Позиция здесь — БУМАЖНАЯ КРЕДИТНАЯ позиция (протокол · стейбл · размер · накопленный доход) — НЕ дельта-нейтральная пара спот-long / перп-short. Ноги-хеджа, которых у ленда нет, показаны н-д, никогда не выдуманы.',
  },
  /* header metrics */
  mProtocol: { en: 'Protocol', ru: 'Протокол' },
  mAsset: { en: 'Asset', ru: 'Актив' },
  mTier: { en: 'Tier', ru: 'Tier' },
  mSize: { en: 'Current size', ru: 'Текущий размер' },
  mApy: { en: 'Supply APY', ru: 'APY кредита' },
  mAccrued: { en: 'Accrued yield', ru: 'Накоплено' },
  mDaysHeld: { en: 'Days held', ru: 'Дней в позиции' },
  status: { en: 'Status', ru: 'Статус' },
  open: { en: 'open', ru: 'открыта' },
  closed: { en: 'closed', ru: 'закрыта' },
  annualized: { en: 'annualized', ru: 'годовых' },
  /* sections */
  s1: { en: '1 · Lifecycle', ru: '1 · Жизненный цикл' },
  s1sub: {
    en: 'Entry → legs → funding accrual over time → delta drift → exit → realized net. Rendered for a paper lending position (β≈0 by construction — a stablecoin has no ETH exposure to drift; the spot/perp hedge legs do not exist).',
    ru: 'Вход → ноги → накопление funding во времени → дрейф дельты → выход → реализованный нетто. Для бумажной кредитной позиции (β≈0 по построению — у стейбла нет ETH-экспозиции для дрейфа; ноги спот/перп-хеджа отсутствуют).',
  },
  entryTitle: { en: 'Entry rationale', ru: 'Обоснование входа' },
  entryNone: {
    en: 'No entry rebalance for this protocol is in the trades ledger (ring-buffer 500). Position present in the current book but its allocating rebalance has rolled off the buffer — honest gap, nothing fabricated.',
    ru: 'В журнале трейдов (кольцевой буфер 500) нет ребаланса-входа для этого протокола. Позиция есть в текущей книге, но её ребаланс-вход вытеснен из буфера — честный пробел, ничего не выдумано.',
  },
  entryLine: {
    en: 'Allocated by the daily cycle rebalance — the deterministic RiskPolicy gate approved this protocol (TVL ≥ $5M · APY in band · caps respected) and the allocator sized it.',
    ru: 'Аллоцировано дневным ребалансом цикла — детерминированный гейт RiskPolicy одобрил протокол (TVL ≥ $5M · APY в диапазоне · cap-ы соблюдены), аллокатор задал размер.',
  },
  legsTitle: { en: 'Legs (paper book)', ru: 'Ноги (бумажная книга)' },
  legsSub: {
    en: 'One LEND leg. The delta-neutral spot-long / perp-short legs are n-a — this desk holds stablecoin lending, not a hedged spot/perp pair, so those legs are honestly absent (not a fabricated zero-delta trade).',
    ru: 'Одна нога LEND. Дельта-нейтральные ноги спот-long / перп-short — н-д: деск держит стейбл-лендинг, а не хеджированную спот/перп-пару, поэтому эти ноги честно отсутствуют (не выдуманный zero-delta трейд).',
  },
  accrualTitle: { en: 'Funding accrual over time', ru: 'Накопление дохода во времени' },
  accrualSub: {
    en: 'The REAL per-day yield accrued by this position (equity_curve_daily · size-weighted). Evidenced bars are distinct from any backfill. This is realized paper accrual, not a modeled projection.',
    ru: 'РЕАЛЬНЫЙ дневной доход, накопленный этой позицией (equity_curve_daily · взвешенный по размеру). Evidenced-бары отличаются от backfill. Это реализованный бумажный доход, не модельная проекция.',
  },
  driftTitle: { en: 'Delta drift', ru: 'Дрейф дельты' },
  driftNa: {
    en: 'n-a — stablecoin lending is delta-neutral by construction (β≈0). There is no directional ETH leg to drift; the hedge-ratio drift a spot+perp position tracks does not apply here. Honest n-a, not a fabricated β.',
    ru: 'н-д — стейбл-лендинг дельта-нейтрален по построению (β≈0). Нет направленной ETH-ноги для дрейфа; дрейф хедж-коэффициента спот+перп-позиции здесь неприменим. Честное н-д, не выдуманная β.',
  },
  exitTitle: { en: 'Exit rationale & realized net', ru: 'Выход и реализованный нетто' },
  exitOpen: {
    en: 'Still open — this position is in the current paper book. No exit rebalance yet. Realized net is the yield accrued to date (paper).',
    ru: 'Ещё открыта — позиция в текущей бумажной книге. Ребаланса-выхода пока нет. Реализованный нетто — доход, накопленный на сегодня (paper).',
  },
  exitClosed: {
    en: 'Closed by a daily cycle rebalance — the allocator rotated capital out of this protocol (a higher risk-adjusted opportunity, a cap, or a policy floor). Realized net = the yield accrued while held.',
    ru: 'Закрыта дневным ребалансом — аллокатор вывел капитал из протокола (более выгодная risk-adjusted возможность, cap или policy-floor). Реализованный нетто = доход, накопленный за время удержания.',
  },
  realizedNet: { en: 'Realized net (accrued, paper)', ru: 'Реализованный нетто (накопл., paper)' },
  /* timeline */
  s2: { en: '2 · Position timeline', ru: '2 · Таймлайн позиции' },
  s2sub: {
    en: 'The lifecycle rail — entry, each rebalance that resized the position, funding accrual ticks, and (if any) exit. Real events from the trades ledger + the per-day accrual series.',
    ru: 'Рельс жизненного цикла — вход, каждый ребаланс, менявший размер, тики накопления funding и (если есть) выход. Реальные события из журнала трейдов + дневной серии дохода.',
  },
  evEntry: { en: 'entry', ru: 'вход' },
  evRebal: { en: 'rebalance', ru: 'ребаланс' },
  evAccrual: { en: 'accrual', ru: 'доход' },
  evExit: { en: 'exit', ru: 'выход' },
  thinTimeline: {
    en: 'Lifecycle detail limited — paper lending position with a thin timeline (few ledger events / accrual points). Showing what is real; nothing fabricated.',
    ru: 'Детали цикла ограничены — бумажная кредитная позиция с тонким таймлайном (мало событий / точек дохода). Показано реальное; ничего не выдумано.',
  },
  legendEvidenced: { en: 'evidenced', ru: 'evidenced' },
  /* deep links */
  backStrategy: { en: 'Strategy deep-dive →', ru: 'Разбор стратегии →' },
  openStrategyFor: { en: 'the strategy that holds this book', ru: 'стратегия, держащая эту книгу' },
  /* not-found / idle / offline */
  noId: { en: 'No position id in the URL.', ru: 'В URL нет id позиции.' },
  noIdSub: {
    en: 'Open a position from a strategy on the desk cockpit — this page reads ?id=<protocol_key> (or ?strategy=). Example: ?id=aave_v3.',
    ru: 'Откройте позицию из стратегии на desk cockpit — эта страница читает ?id=<protocol_key> (или ?strategy=). Пример: ?id=aave_v3.',
  },
  notFound: { en: 'Position not found in the paper book.', ru: 'Позиция не найдена в бумажной книге.' },
  notFoundSub: {
    en: 'No position with this key is in the current paper book and no trade for it is in the ledger (ring-buffer 500). Fail-closed — no fabricated position. It may never have been held, or its history has rolled off the buffer.',
    ru: 'Позиции с таким ключом нет ни в текущей бумажной книге, ни в журнале трейдов (кольцевой буфер 500). Fail-closed — без выдуманной позиции. Возможно, её никогда не держали или её история вытеснена из буфера.',
  },
  strategyMode: {
    en: 'A ?strategy= link was followed, but this desk exposes no per-leg paper book per strategy (the book is portfolio-level, keyed by protocol). Open a specific position with ?id=<protocol_key>, or return to the strategy.',
    ru: 'Перешли по ссылке ?strategy=, но деск не раскрывает бумажную книгу по ногам на стратегию (книга — на уровне портфеля, по протоколу). Откройте конкретную позицию через ?id=<protocol_key> или вернитесь к стратегии.',
  },
  pickPosition: { en: 'Positions in the current book:', ru: 'Позиции в текущей книге:' },
};

const TIER_TONE = { T1: 'ok', T2: 'accent', T3: 'warn' };

/* ── error boundary: a broken panel degrades, never white-screens the screen ─────── */
class PanelBoundary extends Component {
  constructor(p) { super(p); this.state = { err: false }; }
  static getDerivedStateFromError() { return { err: true }; }
  render() {
    if (this.state.err) return <StaleGuard error lang={this.props.lang} />;
    return this.props.children;
  }
}

/* ── one polling fetch hook (mirrors CockpitStrategy::useEndpoint) ─────────────────── */
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
      if (json && typeof json === 'object' && !Array.isArray(json)
          && json._fetched_at == null && json.ts == null && json.generated_at == null && json.as_of == null) {
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
  const d = (state.data && !Array.isArray(state.data)) ? state.data : {};
  const stampSource = (d._fetched_at != null || d.ts != null || d.generated_at != null || d.as_of != null)
    ? state.data
    : (d.__client_fetched_at != null ? { ...d, _fetched_at: d.__client_fetched_at } : state.data);
  const freshness = deriveFreshness(Array.isArray(state.data) ? { __client_fetched_at: Date.now() / 1000, _fetched_at: Date.now() / 1000 } : stampSource);
  if (state.error) freshness.stale = true;
  return { ...state, freshness };
}

/* ── section chrome (mirrors CockpitStrategy) ─────────────────────────────────────── */
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
  const bd = tone === 'teal' ? 'var(--teal-border)' : tone === 'danger' ? 'var(--danger-border)' : tone === 'ok' ? 'var(--ok-border)' : 'var(--border-strong)';
  const fg = tone === 'teal' ? 'var(--data-teal)' : tone === 'danger' ? 'var(--danger)' : tone === 'ok' ? 'var(--ok)' : 'var(--text-secondary)';
  return (
    <div style={{ padding: '12px 14px', borderRadius: 'var(--r-md)', background: 'var(--bg-surface)', border: `1px solid ${bd}` }}>
      <p style={{ fontSize: '.8125rem', color: fg, margin: 0, lineHeight: 1.6 }}>{children}</p>
    </div>
  );
}
function Empty({ title, sub, tone = 'muted', children }) {
  const bd = tone === 'teal' ? 'var(--teal-border)' : tone === 'danger' ? 'var(--danger-border)' : 'var(--border-strong)';
  const fg = tone === 'teal' ? 'var(--data-teal)' : tone === 'danger' ? 'var(--danger)' : 'var(--text-primary)';
  return (
    <div style={{ marginTop: 20, padding: '20px 22px', borderRadius: 'var(--r-lg)', background: 'var(--bg-surface)', border: `1px solid ${bd}` }}>
      <p style={{ fontFamily: MONO, fontSize: '.9375rem', fontWeight: 700, color: fg, margin: (sub || children) ? '0 0 8px' : 0 }}>{title}</p>
      {sub && <p style={{ fontSize: '.8125rem', color: 'var(--text-secondary)', margin: 0, lineHeight: 1.6 }}>{sub}</p>}
      {children}
    </div>
  );
}

/* ── extract the position's size over time from the daily accrual series ────────────
 * equity_curve_daily.daily[] carries per-day positions{protocol:usd} + daily_yield_usd +
 * evidenced. We size-weight the day's total yield to THIS protocol's share of the deployed
 * book → the real per-day yield accrued by this position. Fail-closed: a day missing the
 * protocol contributes size 0 (never a fabricated size), a day missing yield → accrual UNKNOWN. */
function accrualSeries(daily, protoKey) {
  const arr = Array.isArray(daily) ? daily : [];
  const out = [];
  let cumYield = 0;
  for (const d of arr) {
    const positions = (d && d.positions) || {};
    const size = isNum(positions[protoKey]) ? Number(positions[protoKey]) : 0;
    if (size <= 0) continue; // not held this day → not part of THIS position's lifecycle
    const deployed = Object.values(positions).reduce((a, v) => a + (isNum(v) ? Number(v) : 0), 0);
    const dayYield = isNum(d.daily_yield_usd) ? Number(d.daily_yield_usd) : null;
    // size-weight the day's realized yield to this protocol's share of the deployed book.
    const share = deployed > 0 && dayYield != null ? dayYield * (size / deployed) : null;
    if (share != null) cumYield += share;
    out.push({
      date: d.date,
      size,
      dayYield: share,
      cumYield: share != null ? cumYield : null,
      apy: isNum(d.apy_today) ? Number(d.apy_today) : null,
      evidenced: d.evidenced !== false,
    });
  }
  return out;
}

/* ── build the timeline events from trades + the accrual series ─────────────────────
 * Real events only: entry (first rebalance that gave this protocol >0), each rebalance that
 * changed its size, exit (rebalance that dropped it to 0), plus accrual ticks (daily bars). */
function buildTimeline(trades, series, protoKey) {
  const events = [];
  const list = Array.isArray(trades) ? trades.slice().sort((a, b) => String(a.ts).localeCompare(String(b.ts))) : [];
  let prev = 0;
  for (const t of list) {
    if (String(t.type) !== 'rebalance') continue;
    const to = (t.to_allocation && isNum(t.to_allocation[protoKey])) ? Number(t.to_allocation[protoKey]) : 0;
    const from = (t.from_allocation && isNum(t.from_allocation[protoKey])) ? Number(t.from_allocation[protoKey]) : prev;
    if (from <= 0 && to > 0) {
      events.push({ kind: 'entry', ts: t.ts, size: to, trade: t });
    } else if (from > 0 && to <= 0) {
      events.push({ kind: 'exit', ts: t.ts, size: 0, prevSize: from, trade: t });
    } else if (to > 0 && Math.abs(to - from) > 0.5) {
      events.push({ kind: 'rebalance', ts: t.ts, size: to, prevSize: from, trade: t });
    }
    prev = to;
  }
  // accrual ticks — one per evidenced accrual day (dedup dates already in the rebalance set kept separate).
  for (const s of series) {
    events.push({ kind: 'accrual', ts: s.date, size: s.size, dayYield: s.dayYield, evidenced: s.evidenced });
  }
  return events.sort((a, b) => String(a.ts).localeCompare(String(b.ts)));
}

/* ── hand-rolled SVG lifecycle rail — a horizontal timeline of the events ─────────── */
const EV_TONE = { entry: 'ok', rebalance: 'accent', accrual: 'teal', exit: 'danger' };
function TimelineRail({ events, lang, reducedMotion }) {
  const ru = lang === 'ru';
  const evs = Array.isArray(events) ? events : [];
  if (evs.length < 2) {
    return <Note tone="muted">{pick(T.thinTimeline, lang)}</Note>;
  }
  const W = 640, H = 96, padL = 14, padR = 14, railY = 46;
  const plotW = W - padL - padR;
  // position by index order (dates may repeat / be sparse — index gives a stable readable rail).
  const n = evs.length;
  const xAt = (i) => padL + (n === 1 ? plotW / 2 : (i / (n - 1)) * plotW);
  // accrual ticks are small marks; entry/rebalance/exit are labeled dots.
  return (
    <div style={{ overflowX: 'auto', borderRadius: 'var(--r-lg)', border: '1px solid var(--border)', background: 'var(--bg-surface)', padding: '10px 4px 4px' }}>
      <svg width="100%" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="xMidYMid meet" role="img"
        aria-label={ru ? 'Рельс жизненного цикла позиции' : 'Position lifecycle rail'}>
        {/* the rail */}
        <line x1={padL} y1={railY} x2={W - padR} y2={railY} stroke="var(--border-strong)" strokeWidth="2" />
        {evs.map((e, i) => {
          const x = xAt(i);
          const col = toneColor(EV_TONE[e.kind] || 'muted');
          if (e.kind === 'accrual') {
            const dim = e.evidenced === false;
            return (
              <line key={i} x1={x} y1={railY - 5} x2={x} y2={railY + 5}
                stroke={col} strokeWidth="1.5" opacity={dim ? 0.4 : 0.8}
                strokeDasharray={dim ? '2 2' : undefined} />
            );
          }
          const up = e.kind === 'entry' || e.kind === 'rebalance';
          const labelY = up ? railY - 14 : railY + 22;
          const lbl = pick(e.kind === 'entry' ? T.evEntry : e.kind === 'exit' ? T.evExit : T.evRebal, lang);
          return (
            <g key={i}>
              <circle cx={x} cy={railY} r="5" fill={col} stroke="var(--bg-primary)" strokeWidth="1.5">
                {!reducedMotion && (e.kind === 'entry' || e.kind === 'exit') && (
                  <animate attributeName="r" values="5;6.5;5" dur="3s" repeatCount="indefinite" />
                )}
              </circle>
              <text x={x} y={labelY} textAnchor="middle" fontFamily="var(--font-mono)" fontSize="9"
                fill={col} style={{ textTransform: 'uppercase', letterSpacing: '.04em' }}>{lbl}</text>
              <text x={x} y={up ? railY - 24 : railY + 33} textAnchor="middle" fontFamily="var(--font-mono)"
                fontSize="7.5" fill="var(--text-faint)">{typeof e.ts === 'string' ? e.ts.slice(0, 10) : ''}</text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

function TimelineLegend({ events, lang }) {
  const evs = Array.isArray(events) ? events : [];
  const kinds = ['entry', 'rebalance', 'accrual', 'exit'].filter((k) => evs.some((e) => e.kind === k));
  if (!kinds.length) return null;
  const LBL = { entry: T.evEntry, rebalance: T.evRebal, accrual: T.evAccrual, exit: T.evExit };
  return (
    <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', marginTop: 8 }}>
      {kinds.map((k) => (
        <span key={k} style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontFamily: MONO, fontSize: '.6875rem', color: 'var(--text-muted)' }}>
          <span style={{ width: 8, height: 8, borderRadius: k === 'accrual' ? 1 : '50%', background: toneColor(EV_TONE[k]) }} aria-hidden="true" />
          {pick(LBL[k], lang)} <span style={{ color: 'var(--text-faint)' }}>({evs.filter((e) => e.kind === k).length})</span>
        </span>
      ))}
    </div>
  );
}

/* ── main ─────────────────────────────────────────────────────────────────────────── */
export default function CockpitPosition() {
  const lang = useLang();
  const reduced = usePrefersReducedMotion();
  const ru = lang === 'ru';
  const [{ id, strategy }] = useState(paramsFromUrl());

  const enabled = !!id; // strategy-only is handled below (no per-strategy book on this desk)
  const port = useEndpoint('/api/live/portfolio', { enabled: true });
  const trades = useEndpoint('/api/trades?limit=500', { enabled: true });
  const positions = useEndpoint('/api/positions', { enabled: true });

  const eyebrow = (
    <p style={{ fontFamily: MONO, fontSize: '.6875rem', textTransform: 'uppercase', letterSpacing: '.12em', color: 'var(--text-faint)', margin: '0 0 8px' }}>{pick(T.eyebrow, lang)}</p>
  );

  /* ── the live paper book ── */
  const bundle = port.data || {};
  const curPos = bundle.current_positions || {};
  const posMap = (curPos && curPos.positions) || {};
  const posDetail = (curPos && curPos.positions_detail) || {};
  const daily = (bundle.equity_curve_daily && bundle.equity_curve_daily.daily) || [];
  // live PaperTrader per-position detail (days_held / current_apy / unrealized_pnl), keyed by protocol.
  const liveRows = Array.isArray(positions.data) ? positions.data : [];
  const liveRow = id ? liveRows.find((p) => p.protocol_key === id) : null;

  /* ── the known universe of position keys (for the pick-list on no-id / strategy) ── */
  const bookKeys = Object.keys(posMap).filter((k) => isNum(posMap[k]) && Number(posMap[k]) > 0);

  /* ── no id ── */
  if (!id) {
    // strategy= link → honest: this desk has no per-strategy leg book; offer the book pick-list.
    return (
      <div>
        {eyebrow}
        <Empty title={pick(strategy ? T.strategyMode : T.noId, lang)} sub={pick(strategy ? T.strategyMode : T.noIdSub, lang)}>
          {bookKeys.length > 0 && (
            <div style={{ marginTop: 14 }}>
              <SubLabel>{pick(T.pickPosition, lang)}</SubLabel>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                {bookKeys.map((k) => (
                  <a key={k} href={`/cockpit/position?id=${encodeURIComponent(k)}`}
                    style={{ fontFamily: MONO, fontSize: '.6875rem', color: 'var(--accent-hover)', textDecoration: 'none', padding: '4px 10px', borderRadius: 'var(--r-full)', border: '1px solid var(--accent-border)', background: 'var(--accent-bg)' }}>
                    {protoName(k)} · {usdCompact(posMap[k])}
                  </a>
                ))}
              </div>
            </div>
          )}
        </Empty>
        <p style={{ marginTop: 14 }}>
          {strategy
            ? <a href={`/cockpit/strategy?id=${encodeURIComponent(strategy)}`} style={{ fontFamily: MONO, fontSize: '.75rem', color: 'var(--accent-hover)' }}>← {pick(T.backStrategy, lang)}</a>
            : <a href="/cockpit" style={{ fontFamily: MONO, fontSize: '.75rem', color: 'var(--accent-hover)' }}>← Desk cockpit</a>}
        </p>
      </div>
    );
  }

  /* ── derive this position's lifecycle ── */
  const series = accrualSeries(daily, id);
  const tradeList = Array.isArray(trades.data) ? trades.data : [];
  const timeline = buildTimeline(tradeList, series, id);
  const entryEvent = timeline.find((e) => e.kind === 'entry') || null;
  const exitEvent = [...timeline].reverse().find((e) => e.kind === 'exit') || null;

  const inBook = isNum(posMap[id]) && Number(posMap[id]) > 0;
  const everTraded = tradeList.some((t) =>
    (t.to_allocation && isNum(t.to_allocation[id]) && Number(t.to_allocation[id]) > 0) ||
    (t.from_allocation && isNum(t.from_allocation[id]) && Number(t.from_allocation[id]) > 0));

  // fail-closed unknown id: not in the current book AND never appears in the ledger → not found.
  const loadedOnce = (port.data != null || port.error) && (trades.data != null || trades.error);
  const notFound = loadedOnce && !inBook && !everTraded;

  if (notFound) {
    return (
      <div>
        {eyebrow}
        <Empty title={pick(T.notFound, lang)} sub={pick(T.notFoundSub, lang)} tone="danger">
          {bookKeys.length > 0 && (
            <div style={{ marginTop: 14 }}>
              <SubLabel>{pick(T.pickPosition, lang)}</SubLabel>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                {bookKeys.map((k) => (
                  <a key={k} href={`/cockpit/position?id=${encodeURIComponent(k)}`}
                    style={{ fontFamily: MONO, fontSize: '.6875rem', color: 'var(--accent-hover)', textDecoration: 'none', padding: '4px 10px', borderRadius: 'var(--r-full)', border: '1px solid var(--accent-border)', background: 'var(--accent-bg)' }}>
                    {protoName(k)} · {usdCompact(posMap[k])}
                  </a>
                ))}
              </div>
            </div>
          )}
        </Empty>
      </div>
    );
  }

  /* ── the position's live facts (fail-closed: null → UNKNOWN, never fabricated) ── */
  const detail = posDetail[id] || {};
  const size = inBook ? Number(posMap[id]) : (exitEvent ? 0 : (liveRow && isNum(liveRow.amount_usd) ? Number(liveRow.amount_usd) : null));
  const apy = isNum(detail.apy_pct) ? Number(detail.apy_pct)
    : (liveRow && isNum(liveRow.current_apy) ? Number(liveRow.current_apy) : null);
  const tier = liveRow && liveRow.tier ? String(liveRow.tier) : null;
  const daysHeld = liveRow && isNum(liveRow.days_held) ? Number(liveRow.days_held) : (series.length || null);
  const asset = protoAsset(id);
  const name = protoName(id);
  const isOpen = inBook && !exitEvent;

  // accrued yield = the cumulative size-weighted realized yield over the position's life.
  const lastCum = [...series].reverse().find((s) => s.cumYield != null);
  const accrued = lastCum ? lastCum.cumYield : (liveRow && isNum(liveRow.unrealized_pnl_usd) ? Number(liveRow.unrealized_pnl_usd) : null);

  // net carry APY for the LEND leg row (positive supply APY; no funding cost — lending, not a perp hedge).
  const legRows = [{
    id, leg: 'LEND', asset: asset || (ru ? 'стейбл (UNKNOWN)' : 'stablecoin (UNKNOWN)'),
    venue: name, notional_usd: isNum(size) ? size : null,
    funding_accrued_usd: isNum(accrued) ? accrued : null,
    net_carry_apy_pct: apy, // supply APY — the whole carry (no perp funding leg for lending)
  }];

  // equity-style accrual chart series (cumulative accrued yield line, evidenced-aware).
  const accrualChart = series
    .filter((s) => s.cumYield != null)
    .map((s) => ({ date: s.date, value: 100000 + s.cumYield, evidenced: s.evidenced }));
  // markers: entry + exit dates overlaid on the accrual curve.
  const chartMarkers = [
    ...(entryEvent && typeof entryEvent.ts === 'string' ? [{ date: entryEvent.ts.slice(0, 10), kind: 'gate' }] : []),
    ...(exitEvent && typeof exitEvent.ts === 'string' ? [{ date: exitEvent.ts.slice(0, 10), kind: 'kill' }] : []),
  ];

  const statusKey = isOpen ? 'open' : 'closed';
  const statusVar = isOpen ? 'var(--ok)' : 'var(--text-muted)';
  const thinBook = series.length < 2 && !entryEvent;

  return (
    <div style={{ display: 'grid', gap: 4 }}>
      {eyebrow}

      <StaleGuard payload={port.data} loading={port.loading && !port.data} error={port.error && !port.data} freshness={port.freshness} lang={lang} label={`position:${id}`}>
        {/* ═══ HEADER ═══ */}
        <div style={{ display: 'grid', gap: 12 }}>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, flexWrap: 'wrap' }}>
            <h1 style={{ fontSize: '1.85rem', fontWeight: 700, color: 'var(--text-primary)', margin: 0, lineHeight: 1.1 }}>{name}</h1>
            <span style={{ fontFamily: MONO, fontSize: '.7rem', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '.05em', padding: '3px 10px', borderRadius: 'var(--r-full)', color: statusVar, background: 'var(--bg-surface-2)', border: `1px solid ${statusVar}` }}>
              {pick(statusKey === 'open' ? T.open : T.closed, lang)}
            </span>
          </div>
          <p style={{ fontSize: '.8125rem', color: 'var(--text-muted)', margin: 0, lineHeight: 1.6, maxWidth: '52rem' }}>{pick(T.intro, lang)}</p>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontFamily: MONO, fontSize: '.625rem', fontWeight: 600, padding: '3px 10px', borderRadius: 'var(--r-full)', background: 'var(--muted-bg)', border: '1px solid var(--muted-border)', color: 'var(--text-muted)' }}>{pick(T.paperTag, lang)}</span>
          </div>

          {/* header instrument row */}
          <div style={{ display: 'grid', gap: 12, gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', marginTop: 6 }}>
            <MetricStat label={T.mAsset} value={asset || NA} sub={asset ? null : { en: 'stablecoin (not resolved)', ru: 'стейбл (не определён)' }} lang={lang} />
            <MetricStat label={T.mTier} value={tier || NA} lang={lang} tone={tier && TIER_TONE[tier] ? TIER_TONE[tier] : undefined} />
            <MetricStat label={T.mSize} value={isNum(size) ? fmtUsd0(size) : NA} lang={lang} idle={isNum(size) && size === 0} />
            <MetricStat label={T.mApy} value={isNum(apy) ? fmtPct(apy) : NA} sub={T.annualized} lang={lang} tone={isNum(apy) ? 'ok' : undefined} />
            <MetricStat label={T.mAccrued} value={isNum(accrued) ? fmtUsd2(accrued) : NA} lang={lang}
              sub={isNum(accrued) ? null : { en: 'no evidenced accrual yet', ru: 'ещё нет evidenced дохода' }}
              deltaTone={isNum(accrued) ? (accrued >= 0 ? 'ok' : 'danger') : 'muted'} />
            <MetricStat label={T.mDaysHeld} value={isNum(daysHeld) ? String(daysHeld) : NA} lang={lang} />
          </div>

          <Note tone="muted">{pick(T.lendingNote, lang)}</Note>
        </div>

        {/* ═══ 1 · LIFECYCLE ═══ */}
        <Section q={pick(T.s1, lang)} sub={pick(T.s1sub, lang)}>
          {/* entry */}
          <div>
            <SubLabel>{pick(T.entryTitle, lang)}</SubLabel>
            {entryEvent ? (
              <Note tone="ok">
                <strong style={{ fontFamily: MONO }}>{typeof entryEvent.ts === 'string' ? entryEvent.ts.slice(0, 10) : NA}</strong>
                {' — '}{pick(T.entryLine, lang)}{' '}
                <span style={{ fontFamily: MONO, color: 'var(--text-muted)' }}>({fmtUsd0(entryEvent.size)})</span>
              </Note>
            ) : (
              <Note tone="muted">{pick(T.entryNone, lang)}</Note>
            )}
          </div>

          {/* legs */}
          <div style={{ marginTop: 6 }}>
            <SubLabel>{pick(T.legsTitle, lang)}</SubLabel>
            <p style={{ fontSize: '.75rem', color: 'var(--text-muted)', margin: '0 0 10px', lineHeight: 1.5 }}>{pick(T.legsSub, lang)}</p>
            <PanelBoundary lang={lang}>
              <PositionTable rows={legRows} lang={lang} />
            </PanelBoundary>
          </div>

          {/* funding accrual over time */}
          <div style={{ marginTop: 10 }}>
            <SubLabel>{pick(T.accrualTitle, lang)}</SubLabel>
            <p style={{ fontSize: '.75rem', color: 'var(--text-muted)', margin: '0 0 10px', lineHeight: 1.5 }}>{pick(T.accrualSub, lang)}</p>
            <PanelBoundary lang={lang}>
              <EquityChart series={accrualChart} markers={chartMarkers} showDrawdown={false} lang={lang} reducedMotion={reduced} height={180} />
            </PanelBoundary>
          </div>

          {/* delta drift — honest n-a */}
          <div style={{ marginTop: 10 }}>
            <SubLabel>{pick(T.driftTitle, lang)}</SubLabel>
            <Note tone="muted">{pick(T.driftNa, lang)}</Note>
          </div>

          {/* exit + realized net */}
          <div style={{ marginTop: 10 }}>
            <SubLabel>{pick(T.exitTitle, lang)}</SubLabel>
            {exitEvent ? (
              <Note tone="danger">
                <strong style={{ fontFamily: MONO }}>{typeof exitEvent.ts === 'string' ? exitEvent.ts.slice(0, 10) : NA}</strong>
                {' — '}{pick(T.exitClosed, lang)}
              </Note>
            ) : (
              <Note tone="teal">{pick(T.exitOpen, lang)}</Note>
            )}
            <div style={{ marginTop: 10, maxWidth: 280 }}>
              <MetricStat label={T.realizedNet} value={isNum(accrued) ? fmtUsd2(accrued) : NA} lang={lang}
                tone={isNum(accrued) ? (accrued >= 0 ? 'ok' : 'danger') : undefined}
                sub={{ en: 'yield accrued over the position life (paper)', ru: 'доход за время жизни позиции (paper)' }} />
            </div>
          </div>
        </Section>

        {/* ═══ 2 · TIMELINE ═══ */}
        <Section q={pick(T.s2, lang)} sub={pick(T.s2sub, lang)}>
          {thinBook ? (
            <Note tone="muted">{pick(T.thinTimeline, lang)}</Note>
          ) : (
            <PanelBoundary lang={lang}>
              <TimelineRail events={timeline} lang={lang} reducedMotion={reduced} />
              <TimelineLegend events={timeline} lang={lang} />
            </PanelBoundary>
          )}
        </Section>

        {/* ═══ deep-links ═══ */}
        <div style={{ marginTop: 26, paddingTop: 20, borderTop: '1px solid var(--border)', display: 'flex', gap: 16, flexWrap: 'wrap', alignItems: 'center' }}>
          <a href="/cockpit/strategy" style={{
            display: 'inline-flex', alignItems: 'center', gap: 8, fontFamily: MONO, fontSize: '.8125rem', fontWeight: 600,
            padding: '10px 16px', borderRadius: 'var(--r-md)', textDecoration: 'none',
            color: 'var(--accent-hover)', background: 'var(--accent-bg)', border: '1px solid var(--accent-border)',
          }}>{pick(T.backStrategy, lang)}</a>
          <span style={{ fontSize: '.6875rem', color: 'var(--text-faint)' }}>{pick(T.openStrategyFor, lang)}</span>
        </div>
      </StaleGuard>
    </div>
  );
}
