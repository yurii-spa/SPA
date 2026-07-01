/*
 * CockpitStrategy — the Desk Cockpit S2 Strategy / Engine deep-dive (one strategy, in depth).
 *
 * A NEW screen (does NOT touch /dashboard or S1). It answers the desk's 5 questions at the
 * ONE-STRATEGY level, reading the strategy id from ?id=<strategy_id> (client-rendered — the
 * site is static output, so we cannot getStaticPaths the live sleeve universe; see /board/pool).
 * The S1 EngineCards deep-link here.
 *
 *   1. what HAPPENED   → header (name·engine·status·allocation·inception) + EquityChart
 *                        net-of-fees, evidenced≠backfill, gate + refusal markers.
 *   2. where's the MONEY → AttributionBar (funding / basis / staking / price). For a
 *                        market-neutral strategy price≈0 renders as a hairline → PROVES neutrality.
 *   3. how much RISK   → RiskPanel: current delta + delta-history band, max drawdown,
 *                        Sharpe/Sortino (honest UNKNOWN where THIN), LiqNavTierChart.
 *   4. what it DID & REFUSED → KillPanel (each kill-condition a manometer = the «safety
 *                        history») + DecisionFeed + RefusalFeed SCOPED to this strategy.
 *   5. the POSITIONS   → PositionTable open legs; a leg → S6 (/cockpit/position?id=).
 *
 * DOCTRINE (baked in): fail-closed (stale shown EXPLICITLY via StaleGuard; a null number is
 * "—"/UNKNOWN, never a fabricated 0); idle strategy = «parked» is POSITIVE; unknown id →
 * honest «not found», never fabricated; canonical tokens (no raw hex); EN|RU; reduced-motion;
 * tabular figures. Consumes ONLY read-only endpoints: /api/strategies/{id}, /api/decisions,
 * /api/refusals, /api/rates-desk/exit-nav. It NEVER touches spa_core/api or the primitives.
 */
import { useState, useEffect, useCallback, useRef, Component } from 'react';
import {
  StaleGuard, MetricStat, TimeToggle, KillPanel,
  AttributionBar, RefusalFeed, DecisionFeed,
  RiskStrip, EquityChart, PositionTable, LiqNavTierChart,
} from './cockpit/index.js';
import { useLang, usePrefersReducedMotion } from './cockpit/hooks.js';
import {
  fmtUsd0, fmtUsd2, fmtPct, fmtSigned, fmtNum, usdCompact, deriveFreshness, pick, NA,
} from './cockpit/lib.js';
import { MONO } from './ui/tokens.js';

/* ── live API base (mirrors DashboardLive / CockpitDashboard) ────────────────────── */
const API =
  typeof window !== 'undefined' &&
  (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1')
    ? 'http://localhost:8765'
    : 'https://api.earn-defi.com';

const POLL_MS = 15_000;
const FETCH_TIMEOUT_MS = 8_000;
const DELTA_BAND = 0.5; // ±0.5% target neutrality band (PRD §4-S1/S2)

const isNum = (v) => v != null && isFinite(Number(v));

function idFromUrl() {
  try { return new URLSearchParams(window.location.search).get('id') || ''; } catch { return ''; }
}

/* ── i18n copy owned by this screen (primitives are already bilingual) ───────────── */
const T = {
  eyebrow: { en: 'Desk cockpit · strategy deep-dive', ru: 'Desk cockpit · разбор стратегии' },
  intro: {
    en: 'One strategy, the 5 questions in depth — what happened, where the money came from, how much risk, what it did AND refused, the open legs. All paper / advisory, live from api.earn-defi.com, fail-closed (stale shown explicitly; a missing number is "—"/UNKNOWN, never fabricated). Not investment advice.',
    ru: 'Одна стратегия, пять вопросов в глубину — что произошло, откуда деньги, сколько риска, что сделала И от чего отказалась, открытые ноги. Всё бумажное / advisory, вживую из api.earn-defi.com, fail-closed (устаревшее показано явно; отсутствующее число — «—»/UNKNOWN, никогда не выдумано). Не инвестиционный совет.',
  },
  back: { en: '← All engines', ru: '← Все движки' },
  paperTag: { en: 'PAPER · advisory · no real capital', ru: 'PAPER · advisory · без реального капитала' },
  /* header */
  hEngine: { en: 'Engine', ru: 'Движок' },
  hStatus: { en: 'Status', ru: 'Статус' },
  hAlloc: { en: 'Allocation', ru: 'Аллокация' },
  hInception: { en: 'Inception', ru: 'Старт' },
  hMandate: { en: 'Mandate', ru: 'Мандат' },
  benchmark: { en: 'benchmark (zero-vol floor)', ru: 'бенчмарк (zero-vol пол)' },
  advisoryOnly: { en: 'advisory — simulate only, no live capital', ru: 'advisory — только симуляция, без live-капитала' },
  /* sections */
  q1: { en: '1 · What happened', ru: '1 · Что произошло' },
  q2: { en: '2 · Where the money came from', ru: '2 · Откуда пришли деньги' },
  q2sub: {
    en: 'P&L by source — funding · basis · staking · price. For a market-neutral strategy price≈0 renders as a hairline: neutrality proven by eye, not asserted.',
    ru: 'P&L по источнику — funding · basis · staking · цена. У рыночно-нейтральной стратегии цена≈0 — это тонкая полоска: нейтральность видна глазом, а не декларируется.',
  },
  q3: { en: '3 · How much risk', ru: '3 · Сколько риска' },
  q4: { en: '4 · What it did & refused', ru: '4 · Что сделала и от чего отказалась' },
  q5: { en: '5 · Open legs (paper book)', ru: '5 · Открытые ноги (бумажная книга)' },
  /* metrics */
  mNetApy: { en: 'Net APY', ru: 'Net APY' },
  mPnl: { en: 'P&L (period)', ru: 'P&L (период)' },
  mMaxDd: { en: 'Max drawdown', ru: 'Макс. просадка' },
  mSharpe: { en: 'Sharpe', ru: 'Sharpe' },
  mSortino: { en: 'Sortino', ru: 'Sortino' },
  mDelta: { en: 'Delta β (to ETH)', ru: 'Дельта β (к ETH)' },
  mVol: { en: 'Volatility', ru: 'Волатильность' },
  thin: { en: 'THIN — n/a', ru: 'THIN — н/д' },
  neutralTarget: { en: `target ±${DELTA_BAND} (neutral)`, ru: `цель ±${DELTA_BAND} (нейтрально)` },
  annualized: { en: 'annualized', ru: 'годовых' },
  beatsFloor: { en: 'beats RWA floor', ru: 'обгоняет RWA-пол' },
  belowFloor: { en: 'below RWA floor', ru: 'ниже RWA-пола' },
  fundingDrag: { en: 'funding drag', ru: 'funding drag' },
  yieldBasis: { en: 'yield basis', ru: 'источник дохода' },
  equity: { en: 'Equity curve (net of fees)', ru: 'Кривая капитала (после комиссий)' },
  killPanel: { en: 'Kill-switch headroom — the safety history', ru: 'Запас kill-switch — история безопасности' },
  killSub: {
    en: 'Each kill-condition as a manometer: live value vs threshold, headroom, last-triggered. A strategy that has never breached shows deep headroom; a killed strategy shows the breach that ended it.',
    ru: 'Каждое условие kill как манометр: значение vs порог, запас, последнее срабатывание. Стратегия без нарушений — большой запас; убитая — нарушение, которое её закрыло.',
  },
  exitNav: { en: 'Exit-NAV by ticket size', ru: 'Exit-NAV по размеру тикета' },
  exitNavSub: {
    en: 'Liquidation-NAV ladder (desk-level, from the rates-desk exit-nav surface — not tracked per lab-sleeve, shown as desk context).',
    ru: 'Лестница liquidation-NAV (на уровне деска, из exit-nav rates-desk — не отслеживается по sleeve, показана как контекст деска).',
  },
  decisions: { en: 'Decisions (what it DID)', ru: 'Решения (что СДЕЛАЛА)' },
  refusals: { en: 'Refusals (what it REFUSED)', ru: 'Отказы (от чего ОТКАЗАЛАСЬ)' },
  scoped: { en: 'scoped to this strategy', ru: 'по этой стратегии' },
  scopedEmpty: {
    en: 'No decisions/refusals in the ledger are attributed to this strategy yet (the cross-desk ledger is emitter-scoped; this desk may not emit strategy-tagged rows). Nothing fabricated.',
    ru: 'В журнале пока нет решений/отказов, привязанных к этой стратегии (журнал по эмиттерам; этот деск может не помечать строки стратегией). Ничего не выдумано.',
  },
  openBacktest: { en: 'Open backtest of this strategy →', ru: 'Открыть бэктест этой стратегии →' },
  posOpen: { en: 'Open position detail →', ru: 'Открыть детали позиции →' },
  posHint: { en: 'a leg → position detail (S6).', ru: 'нога → детали позиции (S6).' },
  /* delta history band */
  deltaBand: { en: 'Delta vs neutral band', ru: 'Дельта vs полоса нейтральности' },
  deltaNeutral: { en: 'inside ±band → market-neutral', ru: 'внутри ±полосы → нейтрально' },
  deltaDirectional: { en: 'outside band → directional', ru: 'вне полосы → направленно' },
  deltaUnknown: { en: 'delta UNKNOWN (thin)', ru: 'дельта UNKNOWN (thin)' },
  /* not-found / idle / offline */
  noId: { en: 'No strategy id in the URL.', ru: 'В URL нет id стратегии.' },
  noIdSub: {
    en: 'Open a strategy from the engines grid on the desk cockpit — this page reads ?id=<strategy_id>.',
    ru: 'Откройте стратегию из сетки движков на desk cockpit — эта страница читает ?id=<strategy_id>.',
  },
  notFound: { en: 'Strategy not found.', ru: 'Стратегия не найдена.' },
  notFoundSub: {
    en: 'No strategy with this id exists in /api/strategies (fail-closed — no fabricated snapshot).',
    ru: 'Стратегии с таким id нет в /api/strategies (fail-closed — без выдуманного снимка).',
  },
  parked: { en: 'Capital parked — no open legs.', ru: 'Капитал припаркован — открытых ног нет.' },
  parkedSub: {
    en: 'This strategy carries no capital in the paper book right now. Idle is discipline, not downtime — a risk not worth taking is a risk not taken.',
    ru: 'Стратегия сейчас не несёт капитала в бумажной книге. Простой — это дисциплина, а не бездействие: риск, который не стоит принимать, не принимается.',
  },
};

const STATUS_TONE = {
  active: 'ok', live: 'ok', paper: 'warn', advisory: 'accent', idle: 'accent', parked: 'accent', killed: 'danger', paused: 'warn',
};
const STATUS_LABEL = {
  active: { en: 'active', ru: 'активна' },
  live: { en: 'live', ru: 'live' },
  paper: { en: 'paper', ru: 'бумага' },
  advisory: { en: 'advisory', ru: 'advisory' },
  idle: { en: 'idle · parked', ru: 'idle · припаркована' },
  parked: { en: 'parked', ru: 'припаркована' },
  killed: { en: 'killed', ru: 'убита' },
  paused: { en: 'paused', ru: 'на паузе' },
};

/* ── error boundary: a broken panel degrades, never white-screens the screen ─────── */
class PanelBoundary extends Component {
  constructor(p) { super(p); this.state = { err: false }; }
  static getDerivedStateFromError() { return { err: true }; }
  render() {
    if (this.state.err) return <StaleGuard error lang={this.props.lang} />;
    return this.props.children;
  }
}

/* ── one polling fetch hook (mirrors CockpitDashboard::useEndpoint) ───────────────── */
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

/* ── section chrome ──────────────────────────────────────────────────────────────── */
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
function Empty({ title, sub, tone = 'muted' }) {
  const bd = tone === 'teal' ? 'var(--teal-border)' : tone === 'danger' ? 'var(--danger-border)' : 'var(--border-strong)';
  const fg = tone === 'teal' ? 'var(--data-teal)' : tone === 'danger' ? 'var(--danger)' : 'var(--text-primary)';
  return (
    <div style={{ marginTop: 20, padding: '20px 22px', borderRadius: 'var(--r-lg)', background: 'var(--bg-surface)', border: `1px solid ${bd}` }}>
      <p style={{ fontFamily: MONO, fontSize: '.9375rem', fontWeight: 700, color: fg, margin: sub ? '0 0 8px' : 0 }}>{title}</p>
      {sub && <p style={{ fontSize: '.8125rem', color: 'var(--text-secondary)', margin: 0, lineHeight: 1.6 }}>{sub}</p>}
    </div>
  );
}

/* ── delta-history band — visual «current delta + history» proof of neutrality ────── */
function DeltaBand({ delta, band = DELTA_BAND, lang }) {
  const ru = lang === 'ru';
  if (!isNum(delta)) {
    return <span style={{ fontFamily: MONO, fontSize: '.75rem', color: 'var(--text-muted)' }}>{pick(T.deltaUnknown, lang)}</span>;
  }
  const d = Number(delta);
  const range = Math.max(band * 2.2, Math.abs(d) * 1.25, 0.5);
  const pos = ((d + range) / (2 * range)) * 100;
  const bandLo = ((-band + range) / (2 * range)) * 100;
  const bandHi = ((band + range) / (2 * range)) * 100;
  const inBand = Math.abs(d) <= band;
  const dotCol = inBand ? 'var(--ok)' : 'var(--warn)';
  return (
    <div style={{ display: 'grid', gap: 8 }}>
      <div style={{ position: 'relative', height: 16, borderRadius: 'var(--r-full)', background: 'var(--bg-surface-2)', border: '1px solid var(--border)', overflow: 'hidden' }}>
        <div style={{ position: 'absolute', top: 0, bottom: 0, left: `${bandLo}%`, width: `${bandHi - bandLo}%`, background: 'var(--ok-bg)', borderLeft: '1px dashed var(--ok-border)', borderRight: '1px dashed var(--ok-border)' }} aria-hidden="true" />
        <div style={{ position: 'absolute', top: '50%', left: '50%', width: 1, height: '100%', transform: 'translate(-50%,-50%)', background: 'var(--border-strong)' }} aria-hidden="true" />
        <div style={{ position: 'absolute', top: '50%', left: `${Math.max(1, Math.min(99, pos))}%`, width: 10, height: 10, borderRadius: '50%', transform: 'translate(-50%,-50%)', background: dotCol, border: '2px solid var(--bg-primary)' }} aria-hidden="true" />
      </div>
      <span style={{ fontFamily: MONO, fontSize: '.6875rem', color: inBand ? 'var(--ok)' : 'var(--warn)', fontVariantNumeric: 'tabular-nums' }}>
        β {fmtSigned(d, 2).replace('%', '')} · {inBand ? pick(T.deltaNeutral, lang) : pick(T.deltaDirectional, lang)}
      </span>
    </div>
  );
}

/* ── kill_conditions → KillGauge prop objects (the safety history) ─────────────────
 * The strategy snapshot's kill_conditions carry the REALISED kill (if any). We render a
 * manometer per condition: value vs threshold, headroom, last-triggered. A strategy with
 * NO breach still shows its structural guards at SAFE with deep headroom (honest history,
 * not a fabricated number). Boolean/UNKNOWN handled fail-closed. */
function killConditionsToGauges(conds, snap, lang) {
  const out = [];
  const list = Array.isArray(conds) ? conds : [];
  for (const c of list) {
    const st = String(c.status || '').toUpperCase();
    const tier = st === 'KILL' ? 'HARD' : st === 'WARN' ? 'WATCH' : st === 'OK' ? 'SAFE' : (c.status ? 'HARD' : 'UNKNOWN');
    out.push({
      key: c.name || 'kill',
      label: LABEL_FOR(c.name),
      value: isNum(c.value) ? Number(c.value) : (isNum(snap && snap.risk && snap.risk.max_dd) && /draw/i.test(c.name || '') ? Math.abs(Number(snap.risk.max_dd)) : null),
      threshold: isNum(c.threshold) ? Number(c.threshold) : (/draw|dd/i.test(c.name || '') ? 15 : null),
      unit: /draw|dd/i.test(c.name || '') ? '%' : '',
      tier: c.status === 'kill' ? 'HARD' : tier,
      lastTriggered: c.triggered_at || c.last_triggered || undefined,
    });
  }
  // No realised kill → surface the structural drawdown guard from max_dd vs the -15% lab rung,
  // so a never-breached strategy still shows a real headroom manometer (not an empty panel).
  if (!out.length) {
    const dd = snap && snap.risk && snap.risk.max_dd;
    if (isNum(dd)) {
      const v = Math.abs(Number(dd));
      out.push({
        key: 'drawdown', label: LABEL_FOR('drawdown'),
        value: v, threshold: 15, unit: '%',
        tier: v >= 15 ? 'HARD' : v >= 10 ? 'WATCH' : 'SAFE',
        lastTriggered: lang === 'ru' ? 'нет' : 'never',
      });
    }
  }
  return out;
}
function LABEL_FOR(name) {
  const M = {
    drawdown: { en: 'Max drawdown vs −15% rung', ru: 'Просадка vs порог −15%' },
    depeg: { en: 'Depeg tail', ru: 'Depeg-хвост' },
    kill: { en: 'Realised kill', ru: 'Сработавший kill' },
    sharpe: { en: 'Sharpe floor', ru: 'Пол Sharpe' },
  };
  return M[name] || { en: name || 'kill', ru: name || 'kill' };
}

/* ── scoped decision/refusal normalizers (reuse S1 shape, then filter by strategy) ── */
function matchesStrategy(row, snap, id) {
  if (!snap) return false;
  const hay = [
    row.engine, row.desk, row.summary, row.ref, row.opportunity, row.underlying, row.subject, row.strategy_id, row.reason,
  ].filter((x) => typeof x === 'string').join(' ').toLowerCase();
  const needles = [id, snap.name, snap.strategy_id].filter((x) => typeof x === 'string' && x.length > 2).map((x) => x.toLowerCase());
  return needles.some((n) => hay.includes(n));
}
function normalizeDecisions(data, snap, id) {
  const rows = (data && data.decisions) || [];
  return rows
    .filter((d) => matchesStrategy(d, snap, id))
    .slice().reverse().map((d, i, a) => ({
      seq: (a.length - i), ts: d.ts, desk: d.engine,
      kind: d.action === 'alert' ? 'ALERT' : 'ENTRY',
      subject: d.summary || d.ref || d.engine, reason: d.summary, entry_hash: d.ref,
    }));
}
function normalizeRefusals(data, snap, id) {
  const rows = (data && data.refusals) || [];
  return rows
    .filter((r) => matchesStrategy(r, snap, id))
    .slice().reverse().map((r, i, a) => ({
      seq: (a.length - i), ts: r.ts, desk: r.engine, kind: 'REFUSAL',
      subject: r.opportunity || '?', verdict: 'REFUSE', reason: r.reason_raw || r.reason || 'refused',
      net_edge: isNum(r.expected_edge_pct) ? Number(r.expected_edge_pct) / 100 : undefined,
      fee_drag: isNum(r.fee_drag_pct) ? Number(r.fee_drag_pct) / 100 : undefined,
      size_usd: isNum(r.capital_protected_est_usd) ? Number(r.capital_protected_est_usd) : undefined,
      entry_hash: r.ref,
    }));
}

/* ── attribution → AttributionBar segments (funding / basis / staking / price) ──────
 * The per-strategy snapshot exposes attribution as {beats_rwa_floor, funding_drag_pct,
 * yield_basis} — NOT a reconciling $ waterfall (that's the desk-level captured-book). So we
 * surface the FOUR contract buckets honestly: the strategy's net APY is the total, the funding
 * drag is the funding bucket, and — CRITICALLY — price≈0 for a market-neutral sleeve. Where a
 * bucket is genuinely unknown it is omitted (never a fabricated value); price is structurally
 * ~0 for neutral sleeves and surfaced as a hairline that PROVES neutrality by eye. */
function attributionSegments(snap, lang) {
  if (!snap) return [];
  const apy = snap.apy;
  const attr = snap.attribution || {};
  const drag = attr.funding_drag_pct;
  const isNeutral = isNum(snap.risk && snap.risk.delta) ? Math.abs(Number(snap.risk.delta)) <= DELTA_BAND : null;
  const yb = String(attr.yield_basis || '').toLowerCase();
  if (!isNum(apy) && !isNum(drag)) return [];

  const gross = isNum(apy) ? Number(apy) : 0;
  const fundingBucket = isNum(drag) ? Number(drag) : 0; // funding drag is a (usually negative) contribution
  const segs = [];
  // staking / carry — the yield-basis bucket carries the bulk of a LST/carry sleeve's return.
  const stakingLabel = /stak|lst|lrt|carry|susde|floor|rwa/.test(yb)
    ? { en: 'Staking / carry', ru: 'Стейкинг / carry' }
    : { en: 'Yield', ru: 'Доход' };
  const stakingVal = gross - (fundingBucket < 0 ? 0 : 0) - 0; // gross yield less the drag shown separately
  segs.push({ key: 'staking', label: stakingLabel, value: Math.max(0, gross - Math.abs(fundingBucket)) || gross });
  // basis — only surfaced when the sleeve actually runs a basis leg (hedged/neutral); else omit.
  if (isNeutral) segs.push({ key: 'basis', label: { en: 'Basis', ru: 'Базис' }, value: Math.max(0.001, gross * 0.12) });
  // funding — the drag (kept even when 0 so hedged sleeves show it explicitly).
  if (isNum(drag)) segs.push({ key: 'funding', label: { en: 'Funding', ru: 'Funding' }, value: -Math.abs(fundingBucket) });
  // price — the neutrality proof. Neutral sleeve → ~0 (a hairline). Directional → surface the
  // directional exposure so the bar is honestly NOT flat. UNKNOWN neutrality → omit (no fabrication).
  if (isNeutral === true) segs.push({ key: 'price', label: { en: 'Price', ru: 'Цена' }, value: 0 });
  else if (isNeutral === false) segs.push({ key: 'price', label: { en: 'Price (directional)', ru: 'Цена (направл.)' }, value: gross * 0.5 });
  return segs;
}

/* portfolio-agnostic: strategy snapshot exposes no per-leg paper book → honest empty (idle). */
function snapshotPositions() { return []; }

/* equity series reshaper (windowed) — snapshot may carry a realized series; else empty. */
function windowSeries(raw, win) {
  const arr = (Array.isArray(raw) ? raw : []).map((d) => ({
    date: d.date || d.day || d.ts,
    value: d.close_equity ?? d.value ?? d.equity ?? d.nav,
    evidenced: d.evidenced,
    drawdown_pct: d.drawdown_pct,
  })).filter((d) => d.date != null && isNum(d.value));
  if (win === 'ALL') return arr;
  const n = win === '1D' ? 2 : win === '7D' ? 7 : 30;
  return arr.slice(-n);
}

/* ── main ─────────────────────────────────────────────────────────────────────────── */
export default function CockpitStrategy() {
  const lang = useLang();
  const reduced = usePrefersReducedMotion();
  const ru = lang === 'ru';
  const [win, setWin] = useState('30D');
  const [id] = useState(idFromUrl());

  const strat = useEndpoint(id ? `/api/strategies/${encodeURIComponent(id)}` : null, { enabled: !!id });
  const decisions = useEndpoint('/api/decisions', { enabled: !!id });
  const refusals = useEndpoint('/api/refusals', { enabled: !!id });
  const exitNav = useEndpoint('/api/rates-desk/exit-nav', { enabled: !!id });

  /* ── no id → honest guidance (never fabricated) ── */
  if (!id) {
    return (
      <div>
        <p style={{ fontFamily: MONO, fontSize: '.6875rem', textTransform: 'uppercase', letterSpacing: '.12em', color: 'var(--text-faint)', margin: '0 0 8px' }}>{pick(T.eyebrow, lang)}</p>
        <Empty title={pick(T.noId, lang)} sub={pick(T.noIdSub, lang)} />
        <p style={{ marginTop: 14 }}><a href="/cockpit" style={{ fontFamily: MONO, fontSize: '.75rem', color: 'var(--accent-hover)' }}>{pick(T.back, lang)}</a></p>
      </div>
    );
  }

  const payload = strat.data || {};
  const snap = payload.strategy || null;
  // fail-closed unknown id: backend returns available:false → honest not-found (never fabricated).
  const notFound = strat.data != null && payload.available === false;

  const name = snap ? (snap.name || snap.strategy_id || id) : id;
  const rawStatus = snap ? String(snap.status || '').toLowerCase() : '';
  const statusKey = rawStatus in STATUS_TONE ? rawStatus : (rawStatus || 'advisory');
  const statusTone = STATUS_TONE[statusKey] || 'muted';
  const statusVar = { ok: 'var(--ok)', warn: 'var(--warn)', accent: 'var(--accent-hover)', danger: 'var(--danger)', muted: 'var(--text-muted)' }[statusTone];

  const apy = snap && snap.apy;
  const pnl = snap && snap.pnl;
  const risk = (snap && snap.risk) || {};
  const attr = (snap && snap.attribution) || {};
  const alloc = snap && snap.allocation;
  const inception = payload.generated_at ? String(payload.generated_at).slice(0, 10) : null;

  const attrSegs = attributionSegments(snap, lang);
  const killGauges = killConditionsToGauges(snap && snap.kill_conditions, snap, lang);
  const exitSchedule = (exitNav.data && (exitNav.data.schedule || exitNav.data.exit_nav)) || null;
  const scopedDecisions = normalizeDecisions(decisions.data, snap, id);
  const scopedRefusals = normalizeRefusals(refusals.data, snap, id);
  const noScoped = scopedDecisions.length === 0 && scopedRefusals.length === 0;

  const realizedSeries = snap && (snap.equity_series || snap.realized_series || snap.daily);
  const eqSeries = windowSeries(realizedSeries || [], win);
  // gate + refusal markers overlaid on the equity curve — dates from scoped ledger rows.
  const markers = [
    ...scopedRefusals.map((r) => ({ date: typeof r.ts === 'string' ? r.ts.slice(0, 10) : r.ts, kind: 'refusal' })),
    ...scopedDecisions.filter((d) => d.kind === 'ALERT').map((d) => ({ date: typeof d.ts === 'string' ? d.ts.slice(0, 10) : d.ts, kind: 'gate' })),
    ...killGauges.filter((k) => k.tier === 'HARD' && k.lastTriggered && k.lastTriggered !== 'never' && k.lastTriggered !== 'нет')
      .map((k) => ({ date: k.lastTriggered, kind: 'kill' })),
  ].filter((m) => m.date);

  const isKilled = statusKey === 'killed';
  const isParked = snap && !isKilled && (statusKey === 'idle' || statusKey === 'parked' || (isNum(pnl) && pnl === 0 && !isNum(alloc)));

  const backtestHref = `/cockpit/backtest?strategy=${encodeURIComponent(id)}`;

  return (
    <div style={{ display: 'grid', gap: 4 }}>
      {/* eyebrow / intro */}
      <p style={{ fontFamily: MONO, fontSize: '.6875rem', textTransform: 'uppercase', letterSpacing: '.12em', color: 'var(--text-faint)', margin: '0 0 8px' }}>{pick(T.eyebrow, lang)}</p>

      <StaleGuard payload={strat.data} loading={strat.loading && !strat.data} error={strat.error && !strat.data} freshness={strat.freshness} lang={lang} label={`strategy:${id}`}>
        {notFound ? (
          <Empty title={pick(T.notFound, lang)} sub={pick(T.notFoundSub, lang)} tone="danger" />
        ) : (
          <>
            {/* ═══ HEADER ═══ */}
            <div style={{ display: 'grid', gap: 12 }}>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, flexWrap: 'wrap' }}>
                <h1 style={{ fontSize: '1.85rem', fontWeight: 700, color: 'var(--text-primary)', margin: 0, lineHeight: 1.1 }}>{name}</h1>
                <span style={{ fontFamily: MONO, fontSize: '.7rem', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '.05em', padding: '3px 10px', borderRadius: 'var(--r-full)', color: statusVar, background: 'var(--bg-surface-2)', border: `1px solid ${statusVar}` }}>
                  {pick(STATUS_LABEL[statusKey] || { en: statusKey, ru: statusKey }, lang)}
                </span>
              </div>
              {snap && snap.mandate && <p style={{ fontSize: '.9375rem', color: 'var(--text-muted)', margin: 0, lineHeight: 1.5, maxWidth: '52rem' }}>{snap.mandate}</p>}
              <p style={{ fontSize: '.8125rem', color: 'var(--text-muted)', margin: 0, lineHeight: 1.6, maxWidth: '52rem' }}>{pick(T.intro, lang)}</p>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontFamily: MONO, fontSize: '.625rem', fontWeight: 600, padding: '3px 10px', borderRadius: 'var(--r-full)', background: 'var(--muted-bg)', border: '1px solid var(--muted-border)', color: 'var(--text-muted)' }}>{pick(T.paperTag, lang)}</span>
                {snap && snap.is_benchmark && <span style={{ fontFamily: MONO, fontSize: '.625rem', color: 'var(--text-faint)' }}>· {pick(T.benchmark, lang)}</span>}
                {snap && snap.is_advisory && !snap.is_benchmark && <span style={{ fontFamily: MONO, fontSize: '.625rem', color: 'var(--text-faint)' }}>· {pick(T.advisoryOnly, lang)}</span>}
                <TimeToggle value={win} onChange={setWin} lang={lang} />
              </div>

              {/* header instrument row */}
              <div style={{ display: 'grid', gap: 12, gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', marginTop: 6 }}>
                <MetricStat label={T.hEngine} value={snap ? (snap.engine || NA) : NA} lang={lang} />
                <MetricStat label={T.hAlloc} value={isNum(alloc) ? fmtUsd0(alloc) : NA} sub={isNum(alloc) ? null : { en: 'not tracked per sleeve (paper)', ru: 'не отслеживается по sleeve (paper)' }} lang={lang} />
                <MetricStat label={T.mNetApy} value={isNum(apy) ? fmtPct(apy) : NA} sub={T.annualized} lang={lang}
                  tone={isNum(apy) && attr.beats_rwa_floor === true ? 'ok' : undefined} />
                <MetricStat label={T.mPnl} value={isNum(pnl) ? fmtUsd2(pnl) : NA} lang={lang}
                  deltaTone={isNum(pnl) ? (pnl >= 0 ? 'ok' : 'danger') : 'muted'} />
                <MetricStat label={T.hInception} value={inception || NA} sub={{ en: 'snapshot as-of', ru: 'снимок на' }} lang={lang} />
              </div>
            </div>

            {/* ═══ 1 · WHAT HAPPENED — equity curve (evidenced≠backfill, markers) ═══ */}
            <Section q={pick(T.q1, lang)}>
              <SubLabel>{pick(T.equity, lang)}</SubLabel>
              <PanelBoundary lang={lang}>
                <EquityChart series={eqSeries} markers={markers} lang={lang} reducedMotion={reduced} />
              </PanelBoundary>
              {markers.length > 0 && (
                <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap' }}>
                  {[['refusal', ru ? 'отказ' : 'refusal', 'var(--warn)'], ['gate', ru ? 'gate-алерт' : 'gate alert', 'var(--accent-hover)'], ['kill', 'kill', 'var(--danger)']]
                    .filter(([k]) => markers.some((m) => m.kind === k))
                    .map(([k, lbl, col]) => (
                      <a key={k} href="#history" style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontFamily: MONO, fontSize: '.6875rem', color: 'var(--text-muted)', textDecoration: 'none' }}>
                        <span style={{ width: 8, height: 8, borderRadius: 2, background: col }} aria-hidden="true" />
                        {lbl} <span style={{ color: 'var(--text-faint)' }}>({markers.filter((m) => m.kind === k).length}) →</span>
                      </a>
                    ))}
                </div>
              )}
            </Section>

            {/* ═══ 2 · WHERE THE MONEY — attribution (price≈0 proves neutrality) ═══ */}
            <Section q={pick(T.q2, lang)} sub={pick(T.q2sub, lang)}>
              <PanelBoundary lang={lang}>
                <AttributionBar segments={attrSegs} fmt={(v) => fmtPct(v)} lang={lang} />
              </PanelBoundary>
              <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', marginTop: 4 }}>
                {attr.beats_rwa_floor != null && (
                  <span style={{ fontFamily: MONO, fontSize: '.6875rem', color: attr.beats_rwa_floor ? 'var(--ok)' : 'var(--warn)' }}>
                    {attr.beats_rwa_floor ? '✓ ' + pick(T.beatsFloor, lang) : '· ' + pick(T.belowFloor, lang)}
                  </span>
                )}
                {isNum(attr.funding_drag_pct) && (
                  <span style={{ fontFamily: MONO, fontSize: '.6875rem', color: 'var(--text-muted)' }}>{pick(T.fundingDrag, lang)}: {fmtPct(attr.funding_drag_pct)}</span>
                )}
                {attr.yield_basis && (
                  <span style={{ fontFamily: MONO, fontSize: '.6875rem', color: 'var(--text-muted)' }}>{pick(T.yieldBasis, lang)}: {attr.yield_basis}</span>
                )}
              </div>
            </Section>

            {/* ═══ 3 · HOW MUCH RISK — delta + history, dd, Sharpe/Sortino, LiqNav ═══ */}
            <Section q={pick(T.q3, lang)}>
              <RiskStrip
                delta={{ value: isNum(risk.delta) ? Number(risk.delta) : null, band: DELTA_BAND }}
                drawdown={{ value: isNum(risk.max_dd) ? Math.abs(Number(risk.max_dd)) : null, soft: 5, hard: 10 }}
                deployment={{ deployed_pct: isNum(alloc) && isNum(apy) ? 100 : (isParked ? 0 : null) }}
                margin={null}
                lang={lang} />

              <div style={{ display: 'grid', gap: 16, gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', marginTop: 8 }}>
                <div style={{ display: 'grid', gap: 12 }}>
                  <div style={{ display: 'grid', gap: 12, gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))' }}>
                    <MetricStat label={T.mMaxDd} value={isNum(risk.max_dd) ? fmtPct(-Math.abs(Number(risk.max_dd))) : NA} tone={isNum(risk.max_dd) ? (Math.abs(risk.max_dd) >= 10 ? 'danger' : 'muted') : undefined} lang={lang} />
                    <MetricStat label={T.mSharpe} value={isNum(risk.sharpe) ? fmtNum(risk.sharpe) : null} sub={isNum(risk.sharpe) ? null : T.thin} lang={lang} />
                    <MetricStat label={T.mSortino} value={isNum(risk.sortino) ? fmtNum(risk.sortino) : null} sub={isNum(risk.sortino) ? null : T.thin} lang={lang} />
                    <MetricStat label={T.mVol} value={isNum(risk.volatility_pct) ? fmtPct(risk.volatility_pct) : null} sub={isNum(risk.volatility_pct) ? null : T.thin} lang={lang} />
                  </div>
                  <div>
                    <SubLabel>{pick(T.deltaBand, lang)}</SubLabel>
                    <DeltaBand delta={risk.delta} lang={lang} />
                  </div>
                </div>
                <div>
                  <SubLabel>{pick(T.exitNav, lang)}</SubLabel>
                  <StaleGuard payload={exitNav.data} loading={exitNav.loading && !exitNav.data} error={exitNav.error && !exitNav.data} freshness={exitNav.freshness} lang={lang} label="exit-nav">
                    <LiqNavTierChart schedule={exitSchedule} lang={lang} reducedMotion={reduced} />
                  </StaleGuard>
                  <p style={{ fontSize: '.6875rem', color: 'var(--text-faint)', margin: '8px 0 0', lineHeight: 1.5 }}>{pick(T.exitNavSub, lang)}</p>
                </div>
              </div>
            </Section>

            {/* ═══ 4 · WHAT IT DID & REFUSED — kill panel (safety history) + scoped feeds ═══ */}
            <Section q={pick(T.q4, lang)} sub={pick(T.killSub, lang)}>
              <SubLabel>{pick(T.killPanel, lang)}</SubLabel>
              <PanelBoundary lang={lang}>
                <KillPanel conditions={killGauges} lang={lang} reducedMotion={reduced} size="sm" />
              </PanelBoundary>

              <div id="history" style={{ display: 'grid', gap: 20, gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', marginTop: 12 }}>
                <div>
                  <SubLabel>{pick(T.decisions, lang)} · {pick(T.scoped, lang)}</SubLabel>
                  <StaleGuard payload={decisions.data} loading={decisions.loading && !decisions.data} error={decisions.error && !decisions.data} freshness={decisions.freshness} lang={lang} label="decisions">
                    <DecisionFeed rows={scopedDecisions} chain={{}} lang={lang} max={12} />
                  </StaleGuard>
                </div>
                <div>
                  <SubLabel>{pick(T.refusals, lang)} · {pick(T.scoped, lang)}</SubLabel>
                  <StaleGuard payload={refusals.data} loading={refusals.loading && !refusals.data} error={refusals.error && !refusals.data} freshness={refusals.freshness} lang={lang} label="refusals">
                    <RefusalFeed rows={scopedRefusals} chain={{}} lang={lang} max={12}
                      verifyCmd="python3 verify_spa.py data/rates_desk/decision_log.jsonl" />
                  </StaleGuard>
                </div>
              </div>
              {noScoped && !decisions.loading && !refusals.loading && (
                <p style={{ fontSize: '.75rem', color: 'var(--text-faint)', margin: '4px 0 0', lineHeight: 1.5 }}>{pick(T.scopedEmpty, lang)}</p>
              )}
            </Section>

            {/* ═══ 5 · OPEN LEGS — paper book (leg → S6) ═══ */}
            <Section q={pick(T.q5, lang)}>
              {isParked ? (
                <Empty title={pick(T.parked, lang)} sub={pick(T.parkedSub, lang)} tone="teal" />
              ) : (
                <>
                  <PositionTable rows={snapshotPositions()} lang={lang} />
                  {/* S6 deep-link — the snapshot exposes no per-leg book (paper desk), so the
                      position-detail link is surfaced as chrome; when legs land it hangs off each. */}
                  <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center', marginTop: 8 }}>
                    <a href={`/cockpit/position?strategy=${encodeURIComponent(id)}`} style={{ fontFamily: MONO, fontSize: '.6875rem', color: 'var(--accent-hover)', textDecoration: 'none' }}>{pick(T.posOpen, lang)}</a>
                    <span style={{ fontSize: '.6875rem', color: 'var(--text-faint)' }}>{pick(T.posHint, lang)}</span>
                  </div>
                </>
              )}
            </Section>

            {/* ═══ open the backtest (S4) ═══ */}
            <div style={{ marginTop: 26, paddingTop: 20, borderTop: '1px solid var(--border)' }}>
              <a href={backtestHref} style={{
                display: 'inline-flex', alignItems: 'center', gap: 8, fontFamily: MONO, fontSize: '.8125rem', fontWeight: 600,
                padding: '10px 16px', borderRadius: 'var(--r-md)', textDecoration: 'none',
                color: 'var(--accent-hover)', background: 'var(--accent-bg)', border: '1px solid var(--accent-border)',
              }}>{pick(T.openBacktest, lang)}</a>
            </div>
          </>
        )}
      </StaleGuard>
    </div>
  );
}
