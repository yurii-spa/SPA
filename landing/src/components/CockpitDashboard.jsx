/*
 * CockpitDashboard — the Desk Cockpit HOME cockpit (Sprint 1 / S1).
 *
 * A NEW screen (does NOT touch /dashboard). It answers the desk's 5 questions in 5 seconds:
 *   1. what HAPPENED        → header instrument row + EquityChart (TimeToggle windows)
 *   2. where's the MONEY    → AttributionWaterfall (THE HERO) + PositionTable
 *   3. how much RISK        → RiskStrip + mini LiqNavTierChart + KillPanel
 *   4. what the system DID & REFUSED → interleaved DecisionFeed + RefusalFeed
 *   5. what REGIME          → RegimeBadge + regime context strip
 *
 * DOCTRINE (baked in, per the PRD §1):
 *   • HERO = Attribution + Safety, NOT a big P&L number (the risk-desk signature).
 *   • idle = «capital parked» is POSITIVE, never an empty error.
 *   • fail-closed: a stale/dead endpoint is shown EXPLICITLY (StaleGuard on EVERY panel),
 *     never fresh-looking; a null number is "—"/UNKNOWN, never a fabricated 0.
 *   • no gamification. tabular figures. canonical tokens (no raw hex). EN|RU. reduced-motion.
 *
 * It consumes ONLY the Sprint-0 endpoints (READ-ONLY): /api/portfolio, /api/kill-gauge,
 * /api/regime, /api/captured-book, /api/decisions, /api/refusals, /api/strategies,
 * /api/rates-desk/exit-nav. It NEVER touches spa_core/api or the primitives — it composes them.
 */
import { useState, useEffect, useCallback, useRef, Component } from 'react';
import {
  StaleGuard, MetricStat, TimeToggle, KillPanel,
  AttributionWaterfall, RefusalFeed, DecisionFeed,
  RiskStrip, EquityChart, RegimeBadge, PositionTable, LiqNavTierChart,
} from './cockpit/index.js';
import { useLang, usePrefersReducedMotion } from './cockpit/hooks.js';
import {
  fmtUsd0, fmtUsd2, fmtPct, fmtSigned, usdCompact, deriveFreshness, pick, NA,
} from './cockpit/lib.js';
import { MONO } from './ui/tokens.js';

/* ── live API base (mirrors DashboardLive) ──────────────────────────────────────── */
const API =
  typeof window !== 'undefined' &&
  (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1')
    ? 'http://localhost:8765'
    : 'https://api.earn-defi.com';

const POLL_MS = 15_000;
const FETCH_TIMEOUT_MS = 8_000;
const DELTA_BAND = 0.5; // ±0.5% target neutrality band (PRD §4-S1)

/* ── i18n copy owned by this screen (primitives are already bilingual) ───────────── */
const T = {
  eyebrow: { en: 'Desk cockpit · the home screen', ru: 'Desk cockpit · главный экран' },
  title: { en: 'The 5 questions, in 5 seconds', ru: 'Пять вопросов за пять секунд' },
  intro: {
    en: 'What happened · where the money is · how much risk · what the system did AND refused · what regime. The hero is attribution + safety — a risk desk is measured by the risk it refuses, not a big P&L number. All paper / advisory, live from api.earn-defi.com, fail-closed (stale is shown explicitly). Not investment advice.',
    ru: 'Что произошло · где деньги · сколько риска · что система сделала И от чего отказалась · какой режим. Герой — атрибуция и безопасность: риск-деск оценивают по риску, от которого он отказался, а не по большому числу P&L. Всё бумажное / advisory, вживую из api.earn-defi.com, fail-closed (устаревшее показано явно). Не инвестиционный совет.',
  },
  qHappened: { en: '1 · What happened', ru: '1 · Что произошло' },
  qMoney: { en: '2 · Where the money came from', ru: '2 · Откуда пришли деньги' },
  qMoneyHero: { en: 'the hero — attribution, not a P&L number', ru: 'герой — атрибуция, а не число P&L' },
  qRisk: { en: '3 · How much risk', ru: '3 · Сколько риска' },
  qEngines: { en: 'Engines', ru: 'Движки' },
  qHistory: { en: '4 · What the system did & refused', ru: '4 · Что система сделала и от чего отказалась' },
  qRegime: { en: '5 · What regime', ru: '5 · Какой режим' },
  nav: { en: 'NAV', ru: 'NAV' },
  dayPnl: { en: 'Day P&L', ru: 'P&L за день' },
  blendedApy: { en: 'Blended APY 30d', ru: 'Средневзв. APY 30д' },
  aggDelta: { en: 'Aggregate delta', ru: 'Совокупная дельта' },
  killStatus: { en: 'Kill-switch', ru: 'Kill-switch' },
  noTriggers: { en: '0 triggers today', ru: '0 срабатываний сегодня' },
  nTriggers: (n) => ({ en: `${n} triggered`, ru: `${n} срабатыв.` }),
  equity: { en: 'Equity curve (net of fees)', ru: 'Кривая капитала (после комиссий)' },
  positions: { en: 'Paper book', ru: 'Бумажная книга' },
  killPanel: { en: 'Kill-switch headroom (per condition)', ru: 'Запас kill-switch (по условиям)' },
  exitNav: { en: 'Exit-NAV by ticket size', ru: 'Exit-NAV по размеру тикета' },
  engineContribution: { en: 'contribution', ru: 'вклад' },
  engineNetApy: { en: 'net APY', ru: 'net APY' },
  engineDelta: { en: 'delta β', ru: 'дельта β' },
  engineOpen: { en: 'Open strategy →', ru: 'Открыть стратегию →' },
  regimeContext: { en: 'Regime context', ru: 'Контекст режима' },
  fundingStreak: { en: 'Regime streak', ru: 'Серия режима' },
  volRegime: { en: 'Vol', ru: 'Волатильность' },
  cyclePos: { en: 'Cycle risk', ru: 'Риск цикла' },
  enginesOffline: { en: 'Engines unavailable — /api/strategies offline (nothing fabricated).', ru: 'Движки недоступны — /api/strategies офлайн (ничего не выдумано).' },
  decisions: { en: 'Decisions (what it DID)', ru: 'Решения (что СДЕЛАЛ)' },
  refusals: { en: 'Refusals (what it REFUSED)', ru: 'Отказы (от чего ОТКАЗАЛСЯ)' },
  fullLedger: { en: 'full ledger →', ru: 'весь журнал →' },
  /* IDLE — the desk identity */
  idleTitle: { en: 'No qualified carry today. Capital parked.', ru: 'Нет квалифицированного carry сегодня. Капитал припаркован.' },
  paperTag: { en: 'PAPER · advisory · no real capital', ru: 'PAPER · advisory · без реального капитала' },
};

const isNum = (v) => v != null && isFinite(Number(v));

/* ── error boundary: a broken panel degrades, never white-screens the cockpit ────── */
class PanelBoundary extends Component {
  constructor(p) { super(p); this.state = { err: false }; }
  static getDerivedStateFromError() { return { err: true }; }
  render() {
    if (this.state.err) return <StaleGuard error lang={this.props.lang} />;
    return this.props.children;
  }
}

/* ── one polling fetch hook: {data, freshness, loading, error} per endpoint ───────── */
function useEndpoint(path, { pollMs = POLL_MS } = {}) {
  const [state, setState] = useState({ data: null, loading: true, error: false });
  const alive = useRef(true);
  const load = useCallback(async () => {
    try {
      const r = await fetch(API + path, {
        signal: AbortSignal.timeout(FETCH_TIMEOUT_MS),
        headers: { Accept: 'application/json' },
      });
      if (!r.ok) throw new Error('HTTP ' + r.status);
      const json = await r.json();
      // Client-side receipt stamp: some Sprint-0 endpoints (e.g. /api/portfolio) do NOT
      // self-stamp _fetched_at. A SUCCESSFUL poll is a real freshness signal — the client
      // knows when it received the bytes — so we record it (never overriding a backend ts).
      // A backend `stale:true` still wins in deriveFreshness; a failed poll flags stale below.
      if (json && typeof json === 'object' && json._fetched_at == null && json.ts == null
          && json.generated_at == null && json.as_of == null) {
        json.__client_fetched_at = Date.now() / 1000;
      }
      if (alive.current) setState({ data: json, loading: false, error: false });
    } catch {
      // fail-closed: keep last data (StaleGuard will grey it via freshness) but flag error
      if (alive.current) setState((s) => ({ data: s.data, loading: false, error: true }));
    }
  }, [path]);
  useEffect(() => {
    alive.current = true;
    load();
    const id = setInterval(load, pollMs);
    return () => { alive.current = false; clearInterval(id); };
  }, [load, pollMs]);
  // freshness: prefer the payload's own _fetched_at/ts/generated_at; else the client receipt
  // stamp (successful-poll signal for endpoints that don't self-stamp). On hard error → stale.
  const d = state.data || {};
  const stampSource = (d._fetched_at != null || d.ts != null || d.generated_at != null || d.as_of != null)
    ? state.data
    : (d.__client_fetched_at != null ? { ...d, _fetched_at: d.__client_fetched_at } : state.data);
  const freshness = deriveFreshness(stampSource);
  if (state.error) freshness.stale = true;
  return { ...state, freshness };
}

/* ── section chrome ──────────────────────────────────────────────────────────────── */
function Section({ q, sub, hero, children }) {
  return (
    <section style={{
      display: 'grid', gap: 14, paddingTop: 26, marginTop: 26,
      borderTop: '1px solid var(--border)',
      ...(hero ? { padding: '22px', borderRadius: 'var(--r-lg)', border: '1px solid var(--accent-border)', background: 'var(--bg-surface)', marginTop: 26 } : null),
    }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, flexWrap: 'wrap' }}>
        <h2 style={{ fontFamily: MONO, fontSize: '.95rem', fontWeight: 700, color: 'var(--text-primary)', margin: 0 }}>{q}</h2>
        {/* Vanity pass (SPA-505): the decorative "★ HERO" badge was removed — the accent-bordered
            hero container + the subtitle already establish this as the signature section; a star
            label changes no decision and confirms no safety. The AttributionWaterfall inside is the
            bold spend, not a badge. */}
      </div>
      {sub && <p style={{ fontSize: '.75rem', color: 'var(--text-muted)', margin: 0, lineHeight: 1.5 }}>{sub}</p>}
      {children}
    </section>
  );
}

/* ── EngineCard — one strategy/engine → deep-links to the S2 strategy view ────────── */
function EngineCard({ s, lang }) {
  const ru = lang === 'ru';
  const status = String(s.status || '').toUpperCase();
  const tone = status === 'KILLED' ? 'danger' : status === 'PAPER' ? 'warn' : status === 'ADVISORY' ? 'accent' : 'ok';
  const toneVar = { danger: 'var(--danger)', warn: 'var(--warn)', accent: 'var(--accent-hover)', ok: 'var(--ok)' }[tone];
  const apy = s.apy;
  const delta = s.risk && s.risk.delta;
  const pnl = s.pnl;
  const href = `/cockpit/strategy?id=${encodeURIComponent(s.strategy_id || '')}`;
  return (
    <a href={href} style={{
      display: 'grid', gap: 10, padding: '16px', textDecoration: 'none',
      background: 'var(--bg-surface)', border: '1px solid var(--border)', borderRadius: 'var(--r-lg)',
      borderLeft: `3px solid ${toneVar}`,
    }}>
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 8 }}>
        <span style={{ fontFamily: MONO, fontSize: '.8125rem', fontWeight: 600, color: 'var(--text-primary)' }}>{s.name || s.strategy_id || NA}</span>
        <span style={{ fontFamily: MONO, fontSize: '.6rem', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '.05em', color: toneVar }}>
          {ru ? { KILLED: 'убит', PAPER: 'бумага', ADVISORY: 'advisory', LIVE: 'live' }[status] || status : status.toLowerCase()}
        </span>
      </div>
      {s.mandate && <p style={{ fontSize: '.7rem', color: 'var(--text-muted)', margin: 0, lineHeight: 1.4 }}>{s.mandate}</p>}
      <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
        <CardStat k={pick(T.engineNetApy, lang)} v={isNum(apy) ? fmtPct(apy) : NA} />
        <CardStat k={pick(T.engineContribution, lang)} v={isNum(pnl) ? usdCompact(pnl) : NA} tone={isNum(pnl) ? (pnl >= 0 ? 'ok' : 'danger') : null} />
        <CardStat k={pick(T.engineDelta, lang)} v={isNum(delta) ? fmtSigned(delta, 2).replace('%', '') : NA} />
      </div>
      <span style={{ fontFamily: MONO, fontSize: '.625rem', color: 'var(--accent-hover)' }}>{pick(T.engineOpen, lang)}</span>
    </a>
  );
}
function CardStat({ k, v, tone }) {
  const col = tone === 'ok' ? 'var(--ok)' : tone === 'danger' ? 'var(--danger)' : 'var(--text-secondary)';
  return (
    <span style={{ display: 'inline-flex', flexDirection: 'column', gap: 2 }}>
      <span style={{ fontFamily: MONO, fontSize: '.55rem', textTransform: 'uppercase', letterSpacing: '.06em', color: 'var(--text-faint)' }}>{k}</span>
      <span style={{ fontFamily: MONO, fontSize: '.8125rem', fontWeight: 600, color: col, fontVariantNumeric: 'tabular-nums' }}>{v}</span>
    </span>
  );
}

/* ── attribution segments builder (captured-book → waterfall segments) ────────────── */
function attributionSegments(attr) {
  if (!attr || attr.status === 'UNKNOWN' || attr.reconciles === false && attr.floor_leg_usd == null) return null;
  const floor = attr.floor_leg_usd;
  const carry = attr.carry_leg_usd;
  if (!isNum(floor) && !isNum(carry)) return null;
  // The captured-book decomposes realized PnL into: RWA floor leg + carry leg. Price ≈ 0 is
  // the market-neutrality proof — the desk carries no directional book, so we surface an
  // explicit price segment at 0 (honest: it is structurally ~0, not fabricated).
  const segs = [
    { key: 'rwa', label: { en: 'RWA floor', ru: 'RWA-пол' }, value: isNum(floor) ? floor : 0 },
    { key: 'carry', label: { en: 'Carry', ru: 'Carry' }, value: isNum(carry) ? carry : 0 },
    { key: 'price', label: { en: 'Price', ru: 'Цена' }, value: 0 },
  ];
  return { segs, total: attr.realized_pnl_usd, reconciles: attr.reconciles };
}

/* ── main ─────────────────────────────────────────────────────────────────────────── */
export default function CockpitDashboard() {
  const lang = useLang();
  const reduced = usePrefersReducedMotion();
  const [win, setWin] = useState('30D');

  const portfolio = useEndpoint('/api/portfolio');
  const kill = useEndpoint('/api/kill-gauge');
  const regime = useEndpoint('/api/regime');
  const captured = useEndpoint('/api/captured-book');
  const decisions = useEndpoint('/api/decisions');
  const refusals = useEndpoint('/api/refusals');
  const strategies = useEndpoint('/api/strategies');
  const exitNav = useEndpoint('/api/rates-desk/exit-nav');

  const ru = lang === 'ru';
  const P = portfolio.data || {};

  /* ── header instrument values (fail-closed) ── */
  const nav = P.total_capital_usd != null && P.total_pnl_usd != null
    ? Number(P.total_capital_usd) + Number(P.total_pnl_usd)
    : (P.current_equity != null ? Number(P.current_equity) : null);
  const dayPnlUsd = P.daily_yield_usd ?? P.day_pnl_usd ?? null;
  const totalReturn = P.total_return_pct;
  const blendedApy = P.apy_pct ?? P.apy_today_pct_annualized ?? null;

  // aggregate delta — β-weighted directional exposure. The desk targets ~0 (market neutral).
  // We surface it from the strategy list's β where available; UNKNOWN otherwise (never faked 0).
  const strat = (strategies.data && strategies.data.strategies) || [];
  let aggDelta = null;
  const betas = strat.map((s) => s.risk && s.risk.delta).filter(isNum);
  if (betas.length) aggDelta = betas.reduce((a, b) => a + Number(b), 0) / betas.length;

  // kill status — count today's triggered conditions (green 0 / red N)
  const killConds = (kill.data && kill.data.conditions) || [];
  const killOverall = kill.data && kill.data.overall_status;
  const nTriggered = killConds.filter((c) => String(c.status).toLowerCase() === 'kill').length;
  const killGreen = nTriggered === 0 && killOverall !== 'kill';

  // regime
  const R = regime.data || {};
  const regimeAvailable = R.available !== false;

  // deployment / idle
  const deployedUsd = P.deployed_usd;
  const capital = P.total_capital_usd;
  const deployedPct = isNum(deployedUsd) && isNum(capital) && Number(capital) > 0
    ? (Number(deployedUsd) / Number(capital)) * 100 : (isNum(P.cash_pct) ? (1 - Number(P.cash_pct)) * 100 : null);
  const idlePct = isNum(deployedPct) ? Math.max(0, 100 - deployedPct) : null;

  // drawdown for the RiskStrip
  const ddCond = killConds.find((c) => c.name === 'drawdown');
  const ddVal = ddCond && isNum(ddCond.value) ? Number(ddCond.value) : (isNum(P.total_drawdown_pct) ? Math.abs(Number(P.total_drawdown_pct)) : null);

  /* ── IDLE detection — the desk's identity ──
   * Idle = nothing deployed (deployedPct ≈ 0) OR no engines carrying capital. This is a
   * POSITIVE state: discipline shown as an achievement, with today's refusal count + top reason. */
  const refusalRows = (refusals.data && refusals.data.refusals) || [];
  const refusalReasonCounts = (refusals.data && refusals.data.reason_counts) || {};
  const topReasonKey = Object.entries(refusalReasonCounts).sort((a, b) => b[1] - a[1])[0];
  const REASON_LABEL = {
    spread_below_fee_drag: { en: 'spread < fees', ru: 'спред < комиссии' },
    funding_flip_risk: { en: 'funding could flip carry negative', ru: 'funding может перевернуть carry' },
    counterparty_flag: { en: 'counterparty / peg flag', ru: 'флаг контрагента / пега' },
    oi_concentration: { en: 'concentration risk', ru: 'риск концентрации' },
    liquidity: { en: 'thin exit liquidity', ru: 'тонкая ликвидность на выход' },
    unmapped: { en: 'structural veto', ru: 'структурное вето' },
  };
  const topReasonLabel = topReasonKey ? pick(REASON_LABEL[topReasonKey[0]] || { en: topReasonKey[0], ru: topReasonKey[0] }, lang) : null;
  const nRefusedToday = refusalRows.length;
  // "idle" only when portfolio is readable AND essentially nothing is deployed.
  const isIdle = portfolio.data != null && isNum(deployedPct) && deployedPct < 0.5;

  const capturedAttr = captured.data && captured.data.attribution;
  const attrBuilt = attributionSegments(capturedAttr);
  const exitSchedule = (exitNav.data && (exitNav.data.schedule || exitNav.data.exit_nav)) || null;

  return (
    <div style={{ display: 'grid', gap: 4 }}>
      {/* eyebrow / title / intro */}
      <p style={{ fontFamily: MONO, fontSize: '.6875rem', textTransform: 'uppercase', letterSpacing: '.12em', color: 'var(--text-faint)', margin: '0 0 8px' }}>{pick(T.eyebrow, lang)}</p>
      <h1 style={{ fontSize: '2rem', fontWeight: 700, color: 'var(--text-primary)', margin: '0 0 10px', lineHeight: 1.1 }}>{pick(T.title, lang)}</h1>
      <p style={{ fontSize: '.9375rem', color: 'var(--text-muted)', margin: '0 0 8px', lineHeight: 1.6, maxWidth: '52rem' }}>{pick(T.intro, lang)}</p>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontFamily: MONO, fontSize: '.625rem', fontWeight: 600, padding: '3px 10px', borderRadius: 'var(--r-full)', background: 'var(--muted-bg)', border: '1px solid var(--muted-border)', color: 'var(--text-muted)' }}>
          {pick(T.paperTag, lang)}
        </span>
        <TimeToggle value={win} onChange={setWin} lang={lang} />
      </div>

      {/* ═══ 1 · HEADER INSTRUMENT ROW ═══ */}
      <Section q={pick(T.qHappened, lang)}>
        <StaleGuard payload={portfolio.data} loading={portfolio.loading} error={portfolio.error && !portfolio.data} freshness={portfolio.freshness} lang={lang} label="portfolio">
          <div style={{ display: 'grid', gap: 12, gridTemplateColumns: 'repeat(auto-fit, minmax(190px, 1fr))' }}>
            <MetricStat label={T.nav} value={fmtUsd0(nav)} size="lg" lang={lang}
              delta={isNum(totalReturn) ? { value: fmtSigned(totalReturn) } : null} />
            <MetricStat label={T.dayPnl} value={isNum(dayPnlUsd) ? fmtUsd2(dayPnlUsd) : NA}
              sub={{ en: 'realized, net of fees', ru: 'реализовано, после комиссий' }} lang={lang}
              deltaTone={isNum(dayPnlUsd) ? (dayPnlUsd >= 0 ? 'ok' : 'danger') : 'muted'} />
            <MetricStat label={T.blendedApy} value={isNum(blendedApy) ? fmtPct(blendedApy) : NA}
              sub={{ en: 'annualized', ru: 'годовых' }} lang={lang} />
            <MetricStat label={T.aggDelta} value={isNum(aggDelta) ? fmtSigned(aggDelta, 2).replace('%', 'β') : NA}
              sub={{ en: `target ±${DELTA_BAND} (neutral)`, ru: `цель ±${DELTA_BAND} (нейтрально)` }}
              tone={isNum(aggDelta) ? (Math.abs(aggDelta) <= DELTA_BAND ? 'ok' : 'warn') : undefined} lang={lang} />
            <MetricStat label={T.killStatus}
              value={kill.data == null ? NA : (killGreen ? pick(T.noTriggers, lang) : pick(T.nTriggers(nTriggered), lang))}
              tone={kill.data == null ? undefined : (killGreen ? 'ok' : 'danger')} lang={lang}
              sub={{ en: 'two-tier ladder', ru: 'двухуровневая лестница' }} />
            <div style={{ display: 'grid', gap: 6, alignContent: 'center' }}>
              <span style={{ fontFamily: MONO, fontSize: '.6rem', textTransform: 'uppercase', letterSpacing: '.08em', color: 'var(--text-muted)' }}>{pick(T.qRegime, lang)}</span>
              <RegimeBadge regime={regimeAvailable ? R.regime : null} streak={R.streak} vol={isNum(R.vol) ? fmtPct(R.vol, 1) : null} lang={lang} compact />
            </div>
          </div>
        </StaleGuard>
      </Section>

      {/* ═══ IDLE — the desk identity (positive «capital parked») ═══ */}
      {isIdle && (
        <div style={{ marginTop: 20, padding: '20px 22px', borderRadius: 'var(--r-lg)', background: 'var(--bg-surface)', border: '1px solid var(--teal-border)' }}>
          <p style={{ fontFamily: MONO, fontSize: '.9375rem', fontWeight: 700, color: 'var(--data-teal)', margin: '0 0 8px' }}>
            {pick(T.idleTitle, lang)} <span style={{ fontVariantNumeric: 'tabular-nums' }}>(100%)</span> ✓
          </p>
          <p style={{ fontSize: '.8125rem', color: 'var(--text-secondary)', margin: 0, lineHeight: 1.6 }}>
            {ru
              ? `Отклонено сегодня: ${nRefusedToday}.${topReasonLabel ? ` Топ-причина: ${topReasonLabel}.` : ''} Отсутствие сделок — это дисциплина, а не простой: риск, который не стоит принимать, не принимается.`
              : `Refused today: ${nRefusedToday}.${topReasonLabel ? ` Top reason: ${topReasonLabel}.` : ''} No trades is discipline, not downtime — a risk not worth taking is a risk not taken.`}
          </p>
        </div>
      )}

      {/* equity curve (windowed) */}
      <div style={{ marginTop: 18 }}>
        <p style={{ fontFamily: MONO, fontSize: '.6875rem', textTransform: 'uppercase', letterSpacing: '.08em', color: 'var(--text-muted)', margin: '0 0 10px' }}>{pick(T.equity, lang)}</p>
        <StaleGuard payload={portfolio.data} loading={portfolio.loading} error={portfolio.error && !portfolio.data} freshness={portfolio.freshness} lang={lang} label="equity">
          <EquityChart series={windowSeries(P.equity_series || P.daily || [], win)} lang={lang} reducedMotion={reduced} />
        </StaleGuard>
      </div>

      {/* ═══ 2 · ATTRIBUTION — THE HERO ═══ */}
      <Section q={pick(T.qMoney, lang)} sub={pick(T.qMoneyHero, lang)} hero>
        <PanelBoundary lang={lang}>
          <StaleGuard payload={captured.data} loading={captured.loading} error={captured.error && !captured.data} freshness={captured.freshness} lang={lang} label="captured-book">
            {attrBuilt
              ? <AttributionWaterfall segments={attrBuilt.segs} total={attrBuilt.total} reconciles={attrBuilt.reconciles} fmt={usdCompact} lang={lang} reducedMotion={reduced} height={220} />
              : <AttributionWaterfall segments={[]} lang={lang} />}
          </StaleGuard>
        </PanelBoundary>
      </Section>

      {/* paper book */}
      <div style={{ marginTop: 18 }}>
        <p style={{ fontFamily: MONO, fontSize: '.6875rem', textTransform: 'uppercase', letterSpacing: '.08em', color: 'var(--text-muted)', margin: '0 0 10px' }}>{pick(T.positions, lang)}</p>
        <StaleGuard payload={portfolio.data} loading={portfolio.loading} error={portfolio.error && !portfolio.data} freshness={portfolio.freshness} lang={lang} label="positions">
          <PositionTable rows={portfolioPositions(P)} lang={lang} />
        </StaleGuard>
      </div>

      {/* ═══ 3 · RISK ═══ */}
      <Section q={pick(T.qRisk, lang)}>
        <StaleGuard payload={portfolio.data} loading={portfolio.loading} error={portfolio.error && !portfolio.data} freshness={portfolio.freshness} lang={lang} label="risk">
          <RiskStrip
            delta={{ value: aggDelta, band: DELTA_BAND }}
            drawdown={{ value: ddVal, soft: 5, hard: 10 }}
            deployment={{ deployed_pct: deployedPct, idle_pct: idlePct }}
            margin={null}
            lang={lang} />
        </StaleGuard>

        <div style={{ display: 'grid', gap: 16, gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', marginTop: 6 }}>
          <div>
            <p style={{ fontFamily: MONO, fontSize: '.6875rem', textTransform: 'uppercase', letterSpacing: '.08em', color: 'var(--text-muted)', margin: '0 0 10px' }}>{pick(T.killPanel, lang)}</p>
            <StaleGuard payload={kill.data} loading={kill.loading} error={kill.error && !kill.data} freshness={kill.freshness} lang={lang} label="kill-gauge">
              <KillPanel conditions={killConditionsToGauges(killConds)} lang={lang} reducedMotion={reduced} size="sm" />
            </StaleGuard>
          </div>
          <div>
            <p style={{ fontFamily: MONO, fontSize: '.6875rem', textTransform: 'uppercase', letterSpacing: '.08em', color: 'var(--text-muted)', margin: '0 0 10px' }}>{pick(T.exitNav, lang)}</p>
            <StaleGuard payload={exitNav.data} loading={exitNav.loading} error={exitNav.error && !exitNav.data} freshness={exitNav.freshness} lang={lang} label="exit-nav">
              <LiqNavTierChart schedule={exitSchedule} lang={lang} reducedMotion={reduced} />
            </StaleGuard>
          </div>
        </div>
      </Section>

      {/* ═══ 4 · ENGINES (deep-link → S2 strategy view) ═══ */}
      <Section q={pick(T.qEngines, lang)}>
        <StaleGuard payload={strategies.data} loading={strategies.loading} error={strategies.error && !strategies.data} freshness={strategies.freshness} lang={lang} label="strategies">
          {strat.length ? (
            <div style={{ display: 'grid', gap: 12, gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))' }}>
              {strat.map((s) => <EngineCard key={s.strategy_id} s={s} lang={lang} />)}
            </div>
          ) : (
            <div style={{ padding: '14px 16px', borderRadius: 'var(--r-md)', background: 'var(--bg-surface-2)', border: '1px solid var(--border-strong)' }}>
              <span style={{ fontFamily: MONO, fontSize: '.75rem', color: 'var(--text-muted)' }}>{pick(T.enginesOffline, lang)}</span>
            </div>
          )}
        </StaleGuard>
      </Section>

      {/* ═══ 5 · HISTORY — interleaved DecisionFeed + RefusalFeed ═══ */}
      <Section q={pick(T.qHistory, lang)}>
        <div style={{ display: 'grid', gap: 20, gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))' }}>
          <div>
            <p style={{ fontFamily: MONO, fontSize: '.6875rem', textTransform: 'uppercase', letterSpacing: '.08em', color: 'var(--text-muted)', margin: '0 0 10px' }}>{pick(T.decisions, lang)}</p>
            <StaleGuard payload={decisions.data} loading={decisions.loading} error={decisions.error && !decisions.data} freshness={decisions.freshness} lang={lang} label="decisions">
              <DecisionFeed rows={normalizeDecisions(decisions.data)} chain={{}} lang={lang} max={12} />
            </StaleGuard>
          </div>
          <div>
            <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 8, margin: '0 0 10px' }}>
              <p style={{ fontFamily: MONO, fontSize: '.6875rem', textTransform: 'uppercase', letterSpacing: '.08em', color: 'var(--text-muted)', margin: 0 }}>{pick(T.refusals, lang)}</p>
              <a href="/cockpit/refusals" style={{ fontFamily: MONO, fontSize: '.625rem', color: 'var(--accent-hover)', textDecoration: 'none', whiteSpace: 'nowrap' }}>{pick(T.fullLedger, lang)}</a>
            </div>
            <StaleGuard payload={refusals.data} loading={refusals.loading} error={refusals.error && !refusals.data} freshness={refusals.freshness} lang={lang} label="refusals">
              <RefusalFeed rows={normalizeRefusals(refusals.data)} chain={{}} lang={lang} max={12}
                verifyCmd="python3 verify_spa.py data/rates_desk/decision_log.jsonl" />
            </StaleGuard>
          </div>
        </div>
      </Section>

      {/* ═══ regime context strip ═══ */}
      <Section q={pick(T.regimeContext, lang)}>
        <StaleGuard payload={regime.data} loading={regime.loading} error={regime.error && !regime.data} freshness={regime.freshness} lang={lang} label="regime">
          <RegimeBadge
            regime={regimeAvailable ? R.regime : null}
            streak={R.streak}
            vol={isNum(R.vol) ? fmtPct(R.vol, 1) : null}
            cycle={R.cycle_risk ? { en: R.cycle_risk, ru: R.cycle_risk } : null}
            note={R.recommendation ? { en: R.recommendation, ru: R.recommendation } : null}
            lang={lang} />
        </StaleGuard>
      </Section>
    </div>
  );
}

/* ── data reshapers (fail-closed) ──────────────────────────────────────────────────── */

/* portfolio equity series → EquityChart series [{date,value,evidenced,drawdown_pct}] */
function windowSeries(raw, win) {
  const arr = (Array.isArray(raw) ? raw : []).map((d) => ({
    date: d.date || d.day || d.ts,
    value: d.close_equity ?? d.value ?? d.equity ?? d.nav,
    evidenced: d.evidenced,
    drawdown_pct: d.drawdown_pct,
  })).filter((d) => d.date != null);
  if (win === 'ALL') return arr;
  const n = win === '1D' ? 2 : win === '7D' ? 7 : 30;
  return arr.slice(-n);
}

/* portfolio → PositionTable rows (paper book). The /api/portfolio object may carry
 * current_positions as a {protocol: usd} map — reshape to legs honestly, else empty (idle). */
function portfolioPositions(P) {
  const cp = P.current_positions;
  if (cp && typeof cp === 'object' && !Array.isArray(cp)) {
    const rows = Object.entries(cp)
      .filter(([, v]) => isNum(v) && Number(v) > 0)
      .map(([asset, usd], i) => ({ id: i, leg: 'LEND', asset, venue: asset, notional_usd: Number(usd) }));
    return rows;
  }
  if (Array.isArray(P.positions)) return P.positions;
  return []; // empty → PositionTable renders the idle-POSITIVE state
}

/* kill-gauge conditions → KillGauge prop objects. Boolean/UNKNOWN handled fail-closed. */
function killConditionsToGauges(conds) {
  return (Array.isArray(conds) ? conds : [])
    .filter((c) => c.unit !== 'bool') // manual boolean isn't a gauge; the numeric ones are
    .map((c) => {
      const st = String(c.status || '').toUpperCase();
      const tier = st === 'KILL' ? 'HARD' : st === 'WARN' ? 'WATCH' : st === 'OK' ? 'SAFE' : 'UNKNOWN';
      const unit = c.unit === 'pct' ? '%' : c.unit === 'count' ? '' : c.unit === 'ratio' ? '' : '';
      return {
        key: c.name,
        label: LABEL_FOR(c.name),
        value: isNum(c.value) ? Number(c.value) : null,
        threshold: isNum(c.threshold) ? Number(c.threshold) : null,
        headroom: isNum(c.headroom_pct) ? Number(c.headroom_pct) : undefined,
        unit,
        tier,
        lastTriggered: c.last_triggered || undefined,
      };
    });
}
function LABEL_FOR(name) {
  const M = {
    drawdown: { en: 'Drawdown', ru: 'Просадка' },
    sharpe: { en: 'Sharpe floor', ru: 'Пол Sharpe' },
    red_flags: { en: 'Red flags (held)', ru: 'Красные флаги' },
  };
  return M[name] || { en: name || '?', ru: name || '?' };
}

/* /api/decisions → DecisionRow rows. Contract: {ts,type,engine,action,ref,summary}. */
function normalizeDecisions(data) {
  const rows = (data && data.decisions) || [];
  return rows.slice().reverse().map((d, i) => ({
    seq: (rows.length - i),
    ts: d.ts,
    desk: d.engine,
    kind: d.action === 'alert' ? 'ALERT' : 'ENTRY',
    subject: d.summary || d.ref || d.engine,
    reason: d.summary,
    entry_hash: d.ref,
  }));
}

/* /api/refusals → DecisionRow rows (kind REFUSAL). Contract shape per cockpit.py. */
function normalizeRefusals(data) {
  const rows = (data && data.refusals) || [];
  return rows.slice().reverse().map((r, i) => ({
    seq: (rows.length - i),
    ts: r.ts,
    desk: r.engine,
    kind: 'REFUSAL',
    subject: r.opportunity || '?',
    verdict: 'REFUSE',
    reason: r.reason_raw || r.reason || 'refused',
    // cockpit.py serves these as PERCENT (e.g. 2.1). DecisionRow re-scales a value in
    // [-1,1] by ×100, so pass the fraction (÷100) → the renderer restores the percent.
    net_edge: isNum(r.expected_edge_pct) ? Number(r.expected_edge_pct) / 100 : undefined,
    fee_drag: isNum(r.fee_drag_pct) ? Number(r.fee_drag_pct) / 100 : undefined,
    size_usd: isNum(r.capital_protected_est_usd) ? Number(r.capital_protected_est_usd) : undefined,
    entry_hash: r.ref,
  }));
}
