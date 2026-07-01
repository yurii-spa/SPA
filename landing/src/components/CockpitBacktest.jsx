/*
 * CockpitBacktest — the Desk Cockpit S4 Backtest / Test view.
 *
 * A NEW screen (does NOT touch /dashboard, S1, or S2). It answers "how did it do?" the desk's way:
 * NOT a final APY number, but the FULL history with drawdowns + gate behaviour. Reads the strategy
 * id from ?strategy=<strategy_id> (client-rendered — the site is static output, so we cannot
 * getStaticPaths the live sleeve universe; see /cockpit/strategy, /board/pool). The S2 «Open
 * backtest» button deep-links here.
 *
 * §4-S4 sections:
 *   1. CONFIG-SUMMARY   — period · assets · venues · fee-model · AUM-tier · which kills enabled.
 *   2. EQUITY (in vs OUT-OF-SAMPLE, explicitly separated) + benchmark reference line.
 *   3. DRAWDOWN series.
 *   4. MARKERS          — trades + gate-triggers (kills) + refusals, ON the curve.
 *   5. SUMMARY table    — net APY, Sharpe, Sortino, max DD, win-rate, #kills, #refusals, avg hold, fee drag.
 *   6. MONTE-CARLO      — return + drawdown distribution p5/p50/p95 (hand-rolled SVG histogram).
 *   7. COUNTERFACTUAL   — «what the gates saved»: return/DD WITHOUT kills vs WITH (proves gate value).
 *
 * DOCTRINE (baked in, load-bearing):
 *   - IN-SAMPLE vs OUT-OF-SAMPLE are ALWAYS visually distinct — the in/out boundary is NEVER blurred
 *     (a marked vertical divider + a distinct dashed-teal out-of-sample line + a shaded OOS band).
 *   - A DEGENERATE / MOCK backtest is FLAGGED, never laundered: synthetic data source OR a Sharpe
 *     above the plausibility ceiling ⇒ a red "degenerate — not a clean number" banner; the metric
 *     itself is greyed + tagged, not shown as trustworthy.
 *   - The COUNTERFACTUAL honestly shows with-vs-without gates; if the backend exposes no counterfactual
 *     block we say so (never a fabricated saving).
 *   - Fail-closed everywhere: null/NaN/absent → "—"/UNKNOWN, never 0 or an invented figure; stale
 *     shown EXPLICITLY via StaleGuard. Canonical tokens (no raw hex); EN|RU; reduced-motion; tabular.
 *
 * Consumes ONLY read-only endpoints: /api/strategies/{id}, /api/backtest/summary, /api/backtest/replay,
 * /api/backtest/compare, /api/tier1/monte-carlo, /api/decisions, /api/refusals. NEVER touches
 * spa_core/api or the primitives.
 */
import { useState, useEffect, useCallback, useRef, Component } from 'react';
import { StaleGuard, MetricStat, TimeToggle, EquityChart } from './cockpit/index.js';
import { useLang, usePrefersReducedMotion } from './cockpit/hooks.js';
import {
  fmtPct, fmtSigned, fmtNum, deriveFreshness, pick, NA,
} from './cockpit/lib.js';
import { MONO, TABULAR, toneColor } from './ui/tokens.js';

/* ── live API base (mirrors DashboardLive / CockpitStrategy) ─────────────────────── */
const API =
  typeof window !== 'undefined' &&
  (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1')
    ? 'http://localhost:8765'
    : 'https://api.earn-defi.com';

const POLL_MS = 30_000;          // backtests are heavier + far less volatile than the live desk
const FETCH_TIMEOUT_MS = 9_000;
const DEFAULT_OOS_SPLIT = 0.7;   // in-sample / out-of-sample boundary (tier1_attribution.oos_split)
const SHARPE_CEILING = 3.0;      // a real net-of-cost strategy above this is degenerate (mock-data tell)
const RWA_FLOOR_APY = 3.4;       // live tokenized-T-bill floor (docs/STRATEGY_LAB) — the honest benchmark

const isNum = (v) => v != null && isFinite(Number(v));

function stratFromUrl() {
  try { return new URLSearchParams(window.location.search).get('strategy') || ''; } catch { return ''; }
}

/* ── i18n copy owned by this screen (primitives are already bilingual) ───────────── */
const T = {
  eyebrow: { en: 'Desk cockpit · backtest / test', ru: 'Desk cockpit · бэктест / тест' },
  title: { en: 'Backtest', ru: 'Бэктест' },
  intro: {
    en: 'Not a final APY number — the FULL history: the equity curve with in-sample and out-of-sample explicitly separated, the drawdowns, and the gate behaviour (where kills fired, what was refused). The counterfactual shows what the deterministic gates SAVED. A degenerate or mock backtest is flagged, never laundered into a clean number. Paper / advisory, live from api.earn-defi.com, fail-closed. Not investment advice.',
    ru: 'Не финальное число APY — ПОЛНАЯ история: кривая капитала с явным разделением in-sample и out-of-sample, просадки и поведение гейтов (где сработали kill, от чего отказались). Контрфактуал показывает, что детерминированные гейты СБЕРЕГЛИ. Вырожденный или mock-бэктест помечается, а не выдаётся за чистое число. Paper / advisory, вживую из api.earn-defi.com, fail-closed. Не инвестиционный совет.',
  },
  paperTag: { en: 'PAPER · advisory · no real capital', ru: 'PAPER · advisory · без реального капитала' },
  back: { en: '← Strategy deep-dive', ru: '← Разбор стратегии' },
  noStrat: { en: 'No strategy in the URL.', ru: 'В URL нет стратегии.' },
  noStratSub: {
    en: 'Open a backtest from a strategy deep-dive («Open backtest» on /cockpit/strategy) — this page reads ?strategy=<strategy_id>. The desk-level replay below is shown regardless.',
    ru: 'Откройте бэктест из разбора стратегии («Открыть бэктест» на /cockpit/strategy) — эта страница читает ?strategy=<strategy_id>. Ниже — replay на уровне деска в любом случае.',
  },
  /* sections */
  s1: { en: '1 · Configuration', ru: '1 · Конфигурация' },
  s1sub: {
    en: 'What was actually tested — the period, the assets & venues, the fee model, the AUM tier, and which kill-conditions were enabled. A backtest with the gates OFF is not the same experiment.',
    ru: 'Что реально тестировалось — период, активы и площадки, модель комиссий, AUM-tier и какие kill-условия были включены. Бэктест с выключенными гейтами — это другой эксперимент.',
  },
  s2: { en: '2 · Equity — in-sample vs out-of-sample', ru: '2 · Капитал — in-sample vs out-of-sample' },
  s2sub: {
    en: 'The in-sample span (where the strategy was fitted) is solid; the OUT-OF-SAMPLE span (held-out, the honest test) is distinct — dashed and shaded. The RWA-floor benchmark is the reference line. The out-of-sample boundary is never blurred: only the held-out part is a real test.',
    ru: 'In-sample участок (где стратегия подгонялась) — сплошной; OUT-OF-SAMPLE участок (отложенный, честный тест) — отличается: пунктир и заливка. Бенчмарк RWA-пола — опорная линия. Граница out-of-sample никогда не размывается: реальный тест — только отложенная часть.',
  },
  s3: { en: '3 · Drawdown', ru: '3 · Просадка' },
  s3sub: {
    en: 'The underwater curve — peak-to-trough depth over the run. Shown for the same window as the equity curve.',
    ru: 'Underwater-кривая — глубина от пика до дна за прогон. Показана в том же окне, что и кривая капитала.',
  },
  s4: { en: '4 · Summary', ru: '4 · Сводка' },
  s5: { en: '5 · Monte-Carlo distribution', ru: '5 · Распределение Монте-Карло' },
  s5sub: {
    en: 'Block-bootstrap of the real daily yield series → the distribution of annualized return and worst drawdown across resampled paths. p5 / p50 / p95 are the confidence band. A single point estimate hides the tail; the distribution does not.',
    ru: 'Block-bootstrap реального ряда дневной доходности → распределение годовой доходности и худшей просадки по пересемплированным путям. p5 / p50 / p95 — доверительная полоса. Точечная оценка прячет хвост; распределение — нет.',
  },
  s6: { en: '6 · What the gates saved', ru: '6 · Что сберегли гейты' },
  s6sub: {
    en: 'The counterfactual: the same book WITHOUT the kill-conditions vs WITH them. This is the desk’s identity made visible — the deterministic gates are not overhead, they are the edge. If the backend exposes no counterfactual pair, we say so (no fabricated saving).',
    ru: 'Контрфактуал: та же книга БЕЗ kill-условий против С ними. Это идентичность деска, сделанная видимой — детерминированные гейты не накладные расходы, а edge. Если бэкенд не даёт контрфактуальную пару, мы это говорим (без выдуманной экономии).',
  },
  /* config fields */
  cPeriod: { en: 'Period', ru: 'Период' },
  cDays: { en: 'Days', ru: 'Дней' },
  cAssets: { en: 'Assets', ru: 'Активы' },
  cVenues: { en: 'Venues', ru: 'Площадки' },
  cFee: { en: 'Fee model', ru: 'Модель комиссий' },
  cAum: { en: 'AUM tier', ru: 'AUM-tier' },
  cKills: { en: 'Kill-conditions enabled', ru: 'Kill-условия включены' },
  cDataSrc: { en: 'Data source', ru: 'Источник данных' },
  cSeed: { en: 'Seed', ru: 'Seed' },
  feeNetOfCost: { en: 'net-of-cost (gas + slippage + swap)', ru: 'net-of-cost (gas + слиппедж + свап)' },
  killsNone: { en: 'none declared', ru: 'не заявлены' },
  synthetic: { en: 'synthetic', ru: 'синтетические' },
  real: { en: 'real', ru: 'реальные' },
  aumUnknown: { en: 'not specified (paper $100k book)', ru: 'не указан (paper $100k книга)' },
  venueContext: { en: 'DeFi lending / RWA / Pendle (read-only feeds)', ru: 'DeFi lending / RWA / Pendle (read-only фиды)' },
  /* summary metrics */
  mNetApy: { en: 'Net APY (annualized)', ru: 'Net APY (годовых)' },
  mTotalRet: { en: 'Total return', ru: 'Совокупная доходность' },
  mSharpe: { en: 'Sharpe', ru: 'Sharpe' },
  mSortino: { en: 'Sortino', ru: 'Sortino' },
  mMaxDd: { en: 'Max drawdown', ru: 'Макс. просадка' },
  mWin: { en: 'Win-rate', ru: 'Доля прибыльных дней' },
  mKills: { en: 'Kills fired', ru: 'Срабатываний kill' },
  mRefusals: { en: 'Refusals', ru: 'Отказов' },
  mAvgHold: { en: 'Avg hold', ru: 'Средний срок' },
  mFeeDrag: { en: 'Fee drag', ru: 'Fee drag' },
  /* markers legend */
  mkTrade: { en: 'trade', ru: 'трейд' },
  mkGate: { en: 'gate / kill fired', ru: 'gate / kill сработал' },
  mkRefusal: { en: 'refusal', ru: 'отказ' },
  markersNone: {
    en: 'No trade / gate / refusal events in the ledger fall inside this backtest window (the cross-desk ledger is emitter-scoped). Nothing fabricated onto the curve.',
    ru: 'В окне этого бэктеста нет событий трейд / gate / отказ из журнала (журнал по эмиттерам). На кривую ничего не выдумано.',
  },
  /* degenerate flag */
  degTitle: { en: 'Degenerate backtest — NOT a clean number', ru: 'Вырожденный бэктест — НЕ чистое число' },
  degSyntheticBody: {
    en: 'This backtest ran on SYNTHETIC data. The metrics below describe the model, not the market — a synthetic path produces near-perfect, untrustworthy statistics (win-rate ≈ 100%, Sharpe far above any plausible ceiling). They are shown greyed and tagged, never as a real track record. The evidenced live track is the only honest number (see the strategy deep-dive).',
    ru: 'Этот бэктест прогнан на СИНТЕТИЧЕСКИХ данных. Метрики ниже описывают модель, а не рынок — синтетический путь даёт почти идеальную, недостоверную статистику (win-rate ≈ 100%, Sharpe далеко за любым разумным потолком). Они показаны серым и помечены, а не как реальный трек. Единственное честное число — evidenced live-трек (см. разбор стратегии).',
  },
  degSharpeBody: {
    en: `Reported Sharpe exceeds the plausibility ceiling (${SHARPE_CEILING.toFixed(1)}) for a real net-of-cost strategy — the tell of mock / degenerate data (the tournament’s trustworthy:false problem). The number is flagged, not trusted.`,
    ru: `Заявленный Sharpe превышает потолок правдоподобия (${SHARPE_CEILING.toFixed(1)}) для реальной net-of-cost стратегии — признак mock / вырожденных данных (проблема tournament trustworthy:false). Число помечено, ему не доверяют.`,
  },
  degTag: { en: 'degenerate', ru: 'вырожд.' },
  /* MC */
  mcRet: { en: 'Annualized return', ru: 'Годовая доходность' },
  mcDd: { en: 'Worst drawdown', ru: 'Худшая просадка' },
  mcP5: { en: 'p5', ru: 'p5' },
  mcP50: { en: 'p50 (median)', ru: 'p50 (медиана)' },
  mcP95: { en: 'p95', ru: 'p95' },
  mcPaths: { en: 'paths', ru: 'путей' },
  mcUnavail: {
    en: 'No Monte-Carlo distribution available for this strategy — its protocols lack a real daily APY series (insufficient_data), so no distribution is fabricated. Fail-closed.',
    ru: 'Распределение Монте-Карло для этой стратегии недоступно — у её протоколов нет реального дневного ряда APY (insufficient_data), поэтому распределение не выдумывается. Fail-closed.',
  },
  mcDeskFallback: {
    en: 'No strategy id — showing the desk’s validated strategies’ Monte-Carlo band.',
    ru: 'Нет id стратегии — показана полоса Монте-Карло валидированных стратегий деска.',
  },
  /* counterfactual */
  cfWith: { en: 'WITH gates', ru: 'С гейтами' },
  cfWithout: { en: 'WITHOUT gates', ru: 'БЕЗ гейтов' },
  cfSaved: { en: 'gates saved', ru: 'гейты сберегли' },
  cfWorsened: { en: 'gates cost', ru: 'гейты стоили' },
  cfProxyNote: {
    en: 'Proxy: a native with/without-gates counterfactual is not exposed by the backtest backend. Shown here is the closest served pair — the conservative (gated-style) scenario vs the aggressive (ungated-style) scenario — labelled as a proxy, not asserted as the exact kill-switch counterfactual.',
    ru: 'Proxy: нативный контрфактуал с/без гейтов бэкенд не отдаёт. Показана ближайшая пара — консервативный (в стиле «с гейтами») сценарий против агрессивного (в стиле «без гейтов») — помечена как proxy, а не как точный контрфактуал kill-switch.',
  },
  cfUnavail: {
    en: 'No counterfactual pair available — the backtest backend exposes no with/without-gates comparison for this run. Nothing fabricated: the value of the gates is not asserted here without data to back it.',
    ru: 'Контрфактуальная пара недоступна — бэкенд не отдаёт сравнение с/без гейтов для этого прогона. Ничего не выдумано: ценность гейтов здесь не декларируется без подтверждающих данных.',
  },
  cfRetLabel: { en: 'Return', ru: 'Доходность' },
  cfDdLabel: { en: 'Max drawdown', ru: 'Макс. просадка' },
  cfInterpBetter: {
    en: 'The gated book gave up some return but cut the drawdown — that is the trade the desk chooses on purpose: survive first, compound second.',
    ru: 'Книга с гейтами уступила часть доходности, но срезала просадку — это сделка, которую деск выбирает намеренно: сначала выжить, потом капитализировать.',
  },
  inSample: { en: 'in-sample (fitted)', ru: 'in-sample (подгонка)' },
  outSample: { en: 'out-of-sample (held-out test)', ru: 'out-of-sample (отложенный тест)' },
  benchmark: { en: `RWA floor ~${RWA_FLOOR_APY}% (benchmark)`, ru: `RWA-пол ~${RWA_FLOOR_APY}% (бенчмарк)` },
  oosBoundary: { en: 'in / out boundary', ru: 'граница in / out' },
};

/* ── error boundary: a broken panel degrades, never white-screens ─────────────────── */
class PanelBoundary extends Component {
  constructor(p) { super(p); this.state = { err: false }; }
  static getDerivedStateFromError() { return { err: true }; }
  render() { return this.state.err ? <StaleGuard error lang={this.props.lang} /> : this.props.children; }
}

/* ── one polling fetch hook (mirrors CockpitStrategy::useEndpoint) ─────────────────── */
function useEndpoint(path, { pollMs = POLL_MS, enabled = true } = {}) {
  const [state, setState] = useState({ data: null, loading: true, error: false });
  const alive = useRef(true);
  const load = useCallback(async () => {
    if (!enabled || !path) { setState({ data: null, loading: false, error: false }); return; }
    try {
      const r = await fetch(API + path, { signal: AbortSignal.timeout(FETCH_TIMEOUT_MS), headers: { Accept: 'application/json' } });
      if (!r.ok) throw new Error('HTTP ' + r.status);
      const json = await r.json();
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
    alive.current = true; load();
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

/* ── chrome ────────────────────────────────────────────────────────────────────────── */
function Section({ q, sub, children }) {
  return (
    <section style={{ display: 'grid', gap: 14, paddingTop: 26, marginTop: 26, borderTop: '1px solid var(--border)' }}>
      <h2 style={{ fontFamily: MONO, fontSize: '.95rem', fontWeight: 700, color: 'var(--text-primary)', margin: 0 }}>{q}</h2>
      {sub && <p style={{ fontSize: '.75rem', color: 'var(--text-muted)', margin: 0, lineHeight: 1.5, maxWidth: '54rem' }}>{sub}</p>}
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
    <div style={{ padding: '20px 22px', borderRadius: 'var(--r-lg)', background: 'var(--bg-surface)', border: `1px solid ${bd}` }}>
      <p style={{ fontFamily: MONO, fontSize: '.9375rem', fontWeight: 700, color: fg, margin: sub ? '0 0 8px' : 0 }}>{title}</p>
      {sub && <p style={{ fontSize: '.8125rem', color: 'var(--text-secondary)', margin: 0, lineHeight: 1.6 }}>{sub}</p>}
    </div>
  );
}

/* ── config-summary field ─────────────────────────────────────────────────────────── */
function ConfigRow({ label, value, mono = true, lang }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, padding: '8px 0', borderBottom: '1px solid var(--border)' }}>
      <span style={{ fontFamily: MONO, fontSize: '.6875rem', textTransform: 'uppercase', letterSpacing: '.05em', color: 'var(--text-muted)', flexShrink: 0 }}>{pick(label, lang)}</span>
      <span style={{ ...(mono ? { fontFamily: MONO, ...TABULAR } : {}), fontSize: '.8125rem', color: 'var(--text-secondary)', textAlign: 'right', wordBreak: 'break-word' }}>{value == null || value === '' ? NA : value}</span>
    </div>
  );
}

/* ── the degenerate-backtest flag banner (the honesty gate) ───────────────────────── */
function DegenerateBanner({ reason, lang }) {
  return (
    <div role="alert" style={{
      display: 'flex', gap: 12, padding: '14px 16px', borderRadius: 'var(--r-lg)',
      background: 'var(--danger-bg)', border: '1px solid var(--danger-border)',
    }}>
      <span aria-hidden="true" style={{ width: 8, height: 8, borderRadius: '50%', background: 'var(--danger)', marginTop: 6, flexShrink: 0 }} />
      <div>
        <p style={{ fontFamily: MONO, fontSize: '.8125rem', fontWeight: 700, color: 'var(--danger)', margin: '0 0 6px' }}>{pick(T.degTitle, lang)}</p>
        <p style={{ fontSize: '.8125rem', color: 'var(--text-secondary)', margin: 0, lineHeight: 1.6 }}>{pick(reason, lang)}</p>
      </div>
    </div>
  );
}

/* ── hand-rolled Monte-Carlo distribution: a p5–p50–p95 confidence bar (return + dd) ──
 * The MC block gives percentiles, not a raw histogram of paths → we render the honest thing
 * we actually have: a p5→p95 range bar with the p50 marked, for BOTH annualized return and
 * worst drawdown. No synthetic bell-curve is fabricated from three points. Fail-closed. */
function McRangeBar({ p5, p50, p95, unit = '%', anchor = null, anchorLabel, tone = 'teal', lang }) {
  if (![p5, p50, p95].every(isNum)) {
    return <span style={{ fontFamily: MONO, fontSize: '.75rem', color: 'var(--text-muted)' }}>{NA}</span>;
  }
  const lo = Math.min(p5, p50, p95, isNum(anchor) ? anchor : p5);
  const hi = Math.max(p5, p50, p95, isNum(anchor) ? anchor : p95);
  const span = (hi - lo) || 1;
  const pad = span * 0.12;
  const min = lo - pad, max = hi + pad, range = max - min || 1;
  const pos = (v) => ((v - min) / range) * 100;
  const col = toneColor(tone);
  return (
    <div style={{ display: 'grid', gap: 8 }}>
      <div style={{ position: 'relative', height: 26 }}>
        {/* full range track */}
        <div style={{ position: 'absolute', top: '50%', left: 0, right: 0, height: 2, transform: 'translateY(-50%)', background: 'var(--border-strong)' }} aria-hidden="true" />
        {/* p5–p95 confidence band */}
        <div style={{ position: 'absolute', top: '50%', left: `${pos(p5)}%`, width: `${Math.max(0, pos(p95) - pos(p5))}%`, height: 8, transform: 'translateY(-50%)', background: col, opacity: 0.28, borderRadius: 'var(--r-full)' }} aria-hidden="true" />
        {/* p5 / p95 ticks */}
        {[p5, p95].map((v, i) => (
          <div key={i} style={{ position: 'absolute', top: '50%', left: `${pos(v)}%`, width: 2, height: 12, transform: 'translate(-50%,-50%)', background: col, opacity: 0.7 }} aria-hidden="true" />
        ))}
        {/* p50 median dot */}
        <div style={{ position: 'absolute', top: '50%', left: `${pos(p50)}%`, width: 11, height: 11, borderRadius: '50%', transform: 'translate(-50%,-50%)', background: col, border: '2px solid var(--bg-primary)' }} aria-hidden="true" />
        {/* anchor (point estimate) marker — the single-number the distribution contextualizes */}
        {isNum(anchor) && (
          <div style={{ position: 'absolute', top: '50%', left: `${pos(anchor)}%`, width: 2, height: 18, transform: 'translate(-50%,-50%)', background: 'var(--text-primary)' }} aria-hidden="true" title={pick(anchorLabel, lang)} />
        )}
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, fontFamily: MONO, fontSize: '.6875rem', ...TABULAR }}>
        <span style={{ color: 'var(--text-muted)' }}>{pick(T.mcP5, lang)} {Number(p5).toFixed(2)}{unit}</span>
        <span style={{ color: 'var(--text-primary)', fontWeight: 600 }}>{pick(T.mcP50, lang)} {Number(p50).toFixed(2)}{unit}</span>
        <span style={{ color: 'var(--text-muted)' }}>{pick(T.mcP95, lang)} {Number(p95).toFixed(2)}{unit}</span>
      </div>
    </div>
  );
}

/* ── counterfactual side-by-side (with vs without gates) ──────────────────────────── */
function CfCard({ title, tone, ret, dd, lang }) {
  const col = toneColor(tone);
  return (
    <div style={{ padding: '16px 18px', borderRadius: 'var(--r-lg)', background: 'var(--bg-surface)', border: `1px solid ${col}` }}>
      <p style={{ fontFamily: MONO, fontSize: '.6875rem', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '.06em', color: col, margin: '0 0 12px' }}>{pick(title, lang)}</p>
      <div style={{ display: 'grid', gap: 10 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10 }}>
          <span style={{ fontFamily: MONO, fontSize: '.6875rem', color: 'var(--text-muted)' }}>{pick(T.cfRetLabel, lang)}</span>
          <span style={{ ...TABULAR, fontFamily: MONO, fontSize: '.9375rem', fontWeight: 700, color: 'var(--text-primary)' }}>{isNum(ret) ? fmtSigned(ret) : NA}</span>
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10 }}>
          <span style={{ fontFamily: MONO, fontSize: '.6875rem', color: 'var(--text-muted)' }}>{pick(T.cfDdLabel, lang)}</span>
          <span style={{ ...TABULAR, fontFamily: MONO, fontSize: '.9375rem', fontWeight: 700, color: isNum(dd) && Math.abs(dd) > 0 ? 'var(--warn)' : 'var(--text-primary)' }}>{isNum(dd) ? fmtPct(-Math.abs(dd)) : NA}</span>
        </div>
      </div>
    </div>
  );
}

/* ── data shaping ────────────────────────────────────────────────────────────────── */

/* replay frames → equity series split at the oos boundary. Each point tags evidenced:
 * we use `evidenced:false` for the OUT-OF-SAMPLE span so EquityChart renders it DISTINCTLY
 * (dashed/dimmed) — this is exactly the honesty affordance the primitive already bakes in
 * (evidenced≠non-evidenced), reused to make the in/out boundary un-blurrable. */
function replayToSeries(frames, split, win) {
  const arr = (Array.isArray(frames) ? frames : [])
    .map((f) => ({ date: f.date, value: f.portfolio_value ?? f.total_capital_usd ?? f.value, dd: f.drawdown_pct }))
    .filter((f) => f.date != null && isNum(f.value));
  if (!arr.length) return { series: [], boundaryDate: null, oosStart: null };
  const oosStart = Math.max(1, Math.floor(arr.length * split));
  const series = arr.map((f, i) => ({
    date: f.date,
    value: f.value,
    evidenced: i < oosStart,        // in-sample = "evidenced" solid; out-of-sample = distinct dashed
    drawdown_pct: f.dd,
  }));
  const boundaryDate = arr[oosStart] ? arr[oosStart].date : null;
  let windowed = series;
  if (win !== 'ALL') {
    const n = win === '1D' ? 2 : win === '7D' ? 7 : 30;
    windowed = series.slice(-n);
  }
  return { series: windowed, boundaryDate, oosStart };
}

/* replay frames → running-peak drawdown series (%, ≤0). */
function replayToDrawdown(frames, win) {
  const arr = (Array.isArray(frames) ? frames : [])
    .map((f) => ({ date: f.date, value: f.portfolio_value ?? f.total_capital_usd ?? f.value }))
    .filter((f) => f.date != null && isNum(f.value));
  let peak = -Infinity;
  let out = arr.map((f) => {
    peak = Math.max(peak, f.value);
    const dd = peak > 0 ? ((f.value - peak) / peak) * 100 : 0;
    // encode drawdown as the "value" so EquityChart draws it; evidenced true (single series)
    return { date: f.date, value: dd, evidenced: true };
  });
  if (win !== 'ALL') {
    const n = win === '1D' ? 2 : win === '7D' ? 7 : 30;
    out = out.slice(-n);
  }
  return out;
}

/* find this strategy's MC block (strategies is a LIST of {id, point_net_apy_pct, mc:{...}}). */
function findMc(mcData, stratId) {
  const list = (mcData && Array.isArray(mcData.strategies)) ? mcData.strategies : [];
  if (!list.length) return { block: null, meta: mcData || {} };
  if (stratId) {
    const hit = list.find((s) => String(s.id || '') === stratId);
    if (hit) return { block: hit, meta: mcData };
  }
  // desk fallback: the first ok block (or first block) so the primitive still has real data.
  const ok = list.find((s) => s.mc && s.mc.status === 'ok') || list[0];
  return { block: ok, meta: mcData, fallback: !stratId || !list.some((s) => String(s.id || '') === stratId) };
}

/* scoped markers from /api/decisions + /api/refusals, clamped to the backtest date window. */
function buildMarkers(decisions, refusals, dateSet, stratId) {
  const inWin = (ts) => {
    const day = typeof ts === 'string' ? ts.slice(0, 10) : null;
    return day && dateSet.has(day) ? day : null;
  };
  const scoped = (row) => {
    if (!stratId) return true; // desk-level replay → show all in-window
    const hay = [row.engine, row.desk, row.summary, row.opportunity, row.underlying, row.subject, row.reason, row.strategy_id]
      .filter((x) => typeof x === 'string').join(' ').toLowerCase();
    return hay.includes(stratId.toLowerCase());
  };
  const out = [];
  ((decisions && decisions.decisions) || []).forEach((d) => {
    const day = inWin(d.ts);
    if (day && scoped(d)) out.push({ date: day, kind: (String(d.action || '').toLowerCase() === 'alert') ? 'gate' : 'gate' });
  });
  ((refusals && refusals.refusals) || []).forEach((r) => {
    const day = inWin(r.ts);
    if (day && scoped(r)) out.push({ date: day, kind: 'refusal' });
  });
  return out;
}

/* ── main ─────────────────────────────────────────────────────────────────────────── */
export default function CockpitBacktest() {
  const lang = useLang();
  const reduced = usePrefersReducedMotion();
  const ru = lang === 'ru';
  const [win, setWin] = useState('ALL');
  const [stratId] = useState(stratFromUrl());

  const summary = useEndpoint('/api/backtest/summary');
  const replay = useEndpoint('/api/backtest/replay?days=90');
  const mc = useEndpoint('/api/tier1/monte-carlo');
  const compare = useEndpoint('/api/backtest/compare?days=90');
  const strat = useEndpoint(stratId ? `/api/strategies/${encodeURIComponent(stratId)}` : null, { enabled: !!stratId });
  const decisions = useEndpoint('/api/decisions');
  const refusals = useEndpoint('/api/refusals');

  const sum = summary.data || {};
  const frames = (replay.data && replay.data.frames) || [];
  const snap = (strat.data && strat.data.strategy) || null;
  const notFound = strat.data != null && strat.data.available === false;

  /* ── DEGENERATE detection (the honesty gate) ── */
  const dataSource = sum.data_source || (replay.data && replay.data.source) || null;
  const isSynthetic = typeof dataSource === 'string' && /synth|mock/i.test(dataSource);
  const sharpeDegenerate = isNum(sum.sharpe_ratio) && Math.abs(Number(sum.sharpe_ratio)) > SHARPE_CEILING;
  const degenerate = isSynthetic || sharpeDegenerate;
  const degReason = isSynthetic ? T.degSyntheticBody : T.degSharpeBody;

  /* ── equity in/out split + drawdown + markers ── */
  const { series: eqSeries, boundaryDate } = replayToSeries(frames, DEFAULT_OOS_SPLIT, win);
  const ddSeries = replayToDrawdown(frames, win);
  const dateSet = new Set(eqSeries.map((p) => p.date));
  const markers = buildMarkers(decisions.data, refusals.data, dateSet, stratId);
  // add the in/out boundary as a gate-tone marker so the divider is explicit on the curve.
  const boundaryInWin = boundaryDate && dateSet.has(boundaryDate);
  const equityMarkers = boundaryInWin
    ? [{ date: boundaryDate, kind: 'gate' }, ...markers.filter((m) => m.date !== boundaryDate)]
    : markers;

  /* ── summary derived counts ── */
  const nRefusals = ((refusals.data && refusals.data.refusals) || []).filter((r) => !stratId || [r.engine, r.opportunity, r.reason, r.underlying].filter((x) => typeof x === 'string').join(' ').toLowerCase().includes(stratId.toLowerCase())).length;
  const nKills = markers.filter((m) => m.kind === 'gate').length;

  /* ── MC ── */
  const { block: mcBlock, fallback: mcFallback } = findMc(mc.data, stratId);
  const mcOk = mcBlock && mcBlock.mc && mcBlock.mc.status === 'ok';
  const netApyAnchor = isNum(sum.annualized_return) ? Number(sum.annualized_return) : (mcBlock && isNum(mcBlock.point_net_apy_pct) ? Number(mcBlock.point_net_apy_pct) : null);

  /* ── counterfactual (proxy: conservative≈gated vs aggressive≈ungated) ── */
  const cmp = compare.data || {};
  const gated = cmp.v1_passive || null;      // conservative → gate-like discipline
  const ungated = cmp.v2_aggressive || null; // aggressive  → ungated-like reach-for-yield
  const cfAvail = gated && ungated && isNum(gated.total_return) && isNum(ungated.total_return);
  const retSaved = cfAvail ? Number(gated.total_return) - Number(ungated.total_return) : null;      // return given up (usually <0)
  const ddSaved = cfAvail ? Math.abs(Number(ungated.max_drawdown)) - Math.abs(Number(gated.max_drawdown)) : null; // drawdown avoided (>0 = gates helped)

  const period = frames.length ? `${frames[0].date} → ${frames[frames.length - 1].date}` : (sum.best_day && sum.worst_day ? null : null);
  const assets = snap && snap.allocation ? Object.keys(snap.allocation).join(', ')
    : (mcBlock && mcBlock.allocation ? Object.keys(mcBlock.allocation).join(', ') : null);
  const killList = snap && Array.isArray(snap.kill_conditions) && snap.kill_conditions.length
    ? snap.kill_conditions.map((c) => c.name || c.condition || 'kill').join(', ')
    : null;

  /* ── no-strategy guidance (still show desk-level replay) ── */
  const header = (
    <div style={{ display: 'grid', gap: 12 }}>
      <p style={{ fontFamily: MONO, fontSize: '.6875rem', textTransform: 'uppercase', letterSpacing: '.12em', color: 'var(--text-faint)', margin: 0 }}>{pick(T.eyebrow, lang)}</p>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, flexWrap: 'wrap' }}>
        <h1 style={{ fontSize: '1.85rem', fontWeight: 700, color: 'var(--text-primary)', margin: 0, lineHeight: 1.1 }}>
          {pick(T.title, lang)}{stratId ? <span style={{ color: 'var(--text-muted)', fontWeight: 500 }}> · {snap ? (snap.name || snap.strategy_id || stratId) : stratId}</span> : null}
        </h1>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontFamily: MONO, fontSize: '.625rem', fontWeight: 600, padding: '3px 10px', borderRadius: 'var(--r-full)', background: 'var(--muted-bg)', border: '1px solid var(--muted-border)', color: 'var(--text-muted)' }}>{pick(T.paperTag, lang)}</span>
      </div>
      <p style={{ fontSize: '.8125rem', color: 'var(--text-muted)', margin: 0, lineHeight: 1.6, maxWidth: '54rem' }}>{pick(T.intro, lang)}</p>
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
        {stratId && <a href={`/cockpit/strategy?id=${encodeURIComponent(stratId)}`} style={{ fontFamily: MONO, fontSize: '.75rem', color: 'var(--accent-hover)', textDecoration: 'none' }}>{pick(T.back, lang)}</a>}
        <TimeToggle value={win} onChange={setWin} lang={lang} />
      </div>
    </div>
  );

  return (
    <div style={{ display: 'grid', gap: 4 }}>
      {header}

      {stratId && notFound && (
        <div style={{ marginTop: 16 }}>
          <Empty title={ru ? 'Стратегия не найдена.' : 'Strategy not found.'} sub={ru ? 'Такого id нет в /api/strategies (fail-closed). Ниже — desk-level replay.' : 'No such id in /api/strategies (fail-closed). The desk-level replay is shown below.'} tone="danger" />
        </div>
      )}

      {/* the DEGENERATE flag — shown up top so no metric below is read as clean */}
      {degenerate && (summary.data || replay.data) && (
        <div style={{ marginTop: 18 }}>
          <DegenerateBanner reason={degReason} lang={lang} />
        </div>
      )}

      {/* ═══ 1 · CONFIGURATION ═══ */}
      <Section q={pick(T.s1, lang)} sub={pick(T.s1sub, lang)}>
        <StaleGuard payload={replay.data || summary.data} loading={(replay.loading && !replay.data) && (summary.loading && !summary.data)} error={replay.error && summary.error && !replay.data && !summary.data} freshness={replay.freshness} lang={lang} label="backtest-config">
          <div style={{ display: 'grid', gap: 0, gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', columnGap: 28 }}>
            <div>
              <ConfigRow label={T.cPeriod} value={period} lang={lang} />
              <ConfigRow label={T.cDays} value={isNum(sum.total_days) ? sum.total_days : (frames.length || (replay.data && replay.data.total_days))} lang={lang} />
              <ConfigRow label={T.cAssets} value={assets} mono={false} lang={lang} />
              <ConfigRow label={T.cVenues} value={pick(T.venueContext, lang)} mono={false} lang={lang} />
            </div>
            <div>
              <ConfigRow label={T.cFee} value={pick(T.feeNetOfCost, lang)} mono={false} lang={lang} />
              <ConfigRow label={T.cAum} value={pick(T.aumUnknown, lang)} mono={false} lang={lang} />
              <ConfigRow label={T.cKills} value={killList || pick(T.killsNone, lang)} mono={false} lang={lang} />
              <ConfigRow
                label={T.cDataSrc}
                value={dataSource
                  ? <span style={{ color: isSynthetic ? 'var(--danger)' : 'var(--ok)', fontWeight: 600 }}>{isSynthetic ? pick(T.synthetic, lang) : (/real/i.test(dataSource) ? pick(T.real, lang) : dataSource)}{isSynthetic ? ` · ${pick(T.degTag, lang)}` : ''}</span>
                  : null}
                lang={lang} />
            </div>
          </div>
        </StaleGuard>
      </Section>

      {/* ═══ 2 · EQUITY — in-sample vs out-of-sample + benchmark ═══ */}
      <Section q={pick(T.s2, lang)} sub={pick(T.s2sub, lang)}>
        <StaleGuard payload={replay.data} loading={replay.loading && !replay.data} error={replay.error && !replay.data} freshness={replay.freshness} lang={lang} label="replay">
          <PanelBoundary lang={lang}>
            <EquityChart series={eqSeries} markers={equityMarkers} showDrawdown lang={lang} reducedMotion={reduced} />
          </PanelBoundary>
          {/* explicit in/out + benchmark legend (EquityChart's own legend uses evidenced wording;
              here we RE-LABEL it as in/out-of-sample so the honesty semantics are unambiguous) */}
          <div style={{ display: 'flex', gap: 18, flexWrap: 'wrap', marginTop: 6 }}>
            <LegendChip color="var(--data-teal)" dashed={false} label={pick(T.inSample, lang)} />
            <LegendChip color="var(--text-muted)" dashed label={pick(T.outSample, lang)} />
            <LegendChip color="var(--accent-hover)" dashed label={pick(T.oosBoundary, lang)} />
            <LegendChip color="var(--danger)" dashed label={pick(T.benchmark, lang)} />
          </div>
        </StaleGuard>
      </Section>

      {/* ═══ 3 · DRAWDOWN ═══ */}
      <Section q={pick(T.s3, lang)} sub={pick(T.s3sub, lang)}>
        <StaleGuard payload={replay.data} loading={replay.loading && !replay.data} error={replay.error && !replay.data} freshness={replay.freshness} lang={lang} label="drawdown">
          <PanelBoundary lang={lang}>
            <EquityChart series={ddSeries} showDrawdown={false} lang={lang} reducedMotion={reduced} height={140} />
          </PanelBoundary>
        </StaleGuard>
      </Section>

      {/* ═══ 4 · SUMMARY ═══ */}
      <Section q={pick(T.s4, lang)}>
        {markers.length === 0 && !decisions.loading && !refusals.loading && (
          <p style={{ fontSize: '.6875rem', color: 'var(--text-faint)', margin: '0 0 4px', lineHeight: 1.5 }}>{pick(T.markersNone, lang)}</p>
        )}
        <StaleGuard payload={summary.data} loading={summary.loading && !summary.data} error={summary.error && !summary.data} freshness={summary.freshness} lang={lang} label="summary">
          <div style={{ display: 'grid', gap: 12, gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))' }}>
            <MetricStat label={T.mNetApy} value={isNum(sum.annualized_return) ? fmtPct(sum.annualized_return) : null} sub={degenerate ? T.degTag : null} stale={degenerate} lang={lang} tone={degenerate ? undefined : (isNum(sum.annualized_return) && sum.annualized_return > RWA_FLOOR_APY ? 'ok' : undefined)} />
            <MetricStat label={T.mTotalRet} value={isNum(sum.total_return_pct) ? fmtSigned(sum.total_return_pct) : null} stale={degenerate} lang={lang} />
            <MetricStat label={T.mSharpe} value={isNum(sum.sharpe_ratio) ? fmtNum(sum.sharpe_ratio) : null} sub={sharpeDegenerate ? T.degTag : null} stale={sharpeDegenerate} tone={sharpeDegenerate ? 'danger' : undefined} lang={lang} />
            <MetricStat label={T.mSortino} value={isNum(sum.sortino_ratio ?? sum.sortino) ? fmtNum(sum.sortino_ratio ?? sum.sortino) : null} stale={degenerate} lang={lang} />
            <MetricStat label={T.mMaxDd} value={isNum(sum.max_drawdown) ? fmtPct(-Math.abs(Number(sum.max_drawdown))) : null} tone={isNum(sum.max_drawdown) && Math.abs(sum.max_drawdown) >= 10 ? 'danger' : undefined} lang={lang} />
            <MetricStat label={T.mWin} value={isNum(sum.win_rate) ? fmtPct(Number(sum.win_rate) * 100) : null} sub={degenerate && isNum(sum.win_rate) && sum.win_rate >= 0.99 ? T.degTag : null} stale={degenerate && isNum(sum.win_rate) && sum.win_rate >= 0.99} lang={lang} />
            <MetricStat label={T.mKills} value={String(nKills)} sub={{ en: 'gate/kill events in window', ru: 'событий gate/kill в окне' }} lang={lang} tone={nKills > 0 ? 'warn' : undefined} />
            <MetricStat label={T.mRefusals} value={String(nRefusals)} sub={{ en: 'ledger refusals', ru: 'отказов в журнале' }} lang={lang} tone={nRefusals > 0 ? 'accent' : undefined} />
            <MetricStat label={T.mAvgHold} value={isNum(sum.avg_hold_days) ? `${fmtNum(sum.avg_hold_days, 1)}d` : null} sub={isNum(sum.avg_hold_days) ? null : { en: 'not tracked (paper)', ru: 'не отслеживается (paper)' }} lang={lang} />
            <MetricStat label={T.mFeeDrag} value={isNum(sum.fee_drag_pct) ? fmtPct(sum.fee_drag_pct) : null} sub={isNum(sum.fee_drag_pct) ? null : { en: 'net-of-cost (baked in)', ru: 'net-of-cost (учтён)' }} lang={lang} />
          </div>
        </StaleGuard>
      </Section>

      {/* ═══ 5 · MONTE-CARLO ═══ */}
      <Section q={pick(T.s5, lang)} sub={pick(T.s5sub, lang)}>
        <StaleGuard payload={mc.data} loading={mc.loading && !mc.data} error={mc.error && !mc.data} freshness={mc.freshness} lang={lang} label="monte-carlo">
          {mcFallback && stratId && mcBlock && (
            <p style={{ fontSize: '.6875rem', color: 'var(--text-faint)', margin: '0 0 8px', lineHeight: 1.5 }}>{pick(T.mcDeskFallback, lang)}</p>
          )}
          {mcOk ? (
            <div style={{ display: 'grid', gap: 20, gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))' }}>
              <div>
                <SubLabel>{pick(T.mcRet, lang)}</SubLabel>
                <McRangeBar p5={mcBlock.mc.apy_p5} p50={mcBlock.mc.apy_p50} p95={mcBlock.mc.apy_p95} unit="%" anchor={isNum(mcBlock.point_net_apy_pct) ? mcBlock.point_net_apy_pct : netApyAnchor} anchorLabel={{ en: 'point estimate', ru: 'точечная оценка' }} tone="teal" lang={lang} />
                <p style={{ fontSize: '.625rem', color: 'var(--text-faint)', margin: '8px 0 0', fontFamily: MONO }}>{mcBlock.mc.n_paths} {pick(T.mcPaths, lang)} · block {mcBlock.mc.block}d · n={mcBlock.mc.n_days}d</p>
              </div>
              <div>
                <SubLabel>{pick(T.mcDd, lang)}</SubLabel>
                <McRangeBar p5={mcBlock.mc.maxdd_p5} p50={mcBlock.mc.maxdd_p50} p95={mcBlock.mc.maxdd_p95} unit="%" tone="warn" lang={lang} />
                <p style={{ fontSize: '.625rem', color: 'var(--text-faint)', margin: '8px 0 0', fontFamily: MONO }}>coverage {isNum(mcBlock.mc.coverage) ? (mcBlock.mc.coverage * 100).toFixed(0) + '%' : NA}</p>
              </div>
            </div>
          ) : (
            <Empty title={ru ? 'Распределение недоступно' : 'Distribution unavailable'} sub={pick(T.mcUnavail, lang)} />
          )}
        </StaleGuard>
      </Section>

      {/* ═══ 6 · COUNTERFACTUAL — what the gates saved ═══ */}
      <Section q={pick(T.s6, lang)} sub={pick(T.s6sub, lang)}>
        <StaleGuard payload={compare.data} loading={compare.loading && !compare.data} error={compare.error && !compare.data} freshness={compare.freshness} lang={lang} label="counterfactual">
          {cfAvail ? (
            <div style={{ display: 'grid', gap: 16 }}>
              <div style={{ display: 'grid', gap: 14, gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))' }}>
                <CfCard title={T.cfWith} tone="teal" ret={gated.total_return} dd={gated.max_drawdown} lang={lang} />
                <CfCard title={T.cfWithout} tone="warn" ret={ungated.total_return} dd={ungated.max_drawdown} lang={lang} />
              </div>
              {/* the saving readouts — the value of the gates, made a number */}
              <div style={{ display: 'grid', gap: 12, gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))' }}>
                <MetricStat
                  label={ddSaved != null && ddSaved >= 0 ? T.cfSaved : T.cfWorsened}
                  value={isNum(ddSaved) ? `${fmtPct(Math.abs(ddSaved))} DD` : null}
                  tone={isNum(ddSaved) && ddSaved >= 0 ? 'ok' : 'danger'}
                  sub={{ en: 'drawdown avoided by the gated book', ru: 'просадка, которую избежала книга с гейтами' }}
                  lang={lang} />
                <MetricStat
                  label={{ en: 'return trade-off', ru: 'размен доходности' }}
                  value={isNum(retSaved) ? fmtSigned(retSaved) : null}
                  tone={isNum(retSaved) ? (retSaved >= 0 ? 'ok' : 'muted') : undefined}
                  sub={{ en: 'return given up (−) or gained (+) vs ungated', ru: 'уступленная (−) или полученная (+) доходность vs без гейтов' }}
                  lang={lang} />
              </div>
              {isNum(ddSaved) && ddSaved > 0 && (
                <p style={{ fontSize: '.75rem', color: 'var(--text-muted)', margin: 0, lineHeight: 1.6, maxWidth: '54rem' }}>{pick(T.cfInterpBetter, lang)}</p>
              )}
              <p style={{ fontSize: '.6875rem', color: 'var(--text-faint)', margin: 0, lineHeight: 1.5, maxWidth: '54rem' }}>{pick(T.cfProxyNote, lang)}</p>
            </div>
          ) : (
            <Empty title={ru ? 'Контрфактуал недоступен' : 'Counterfactual unavailable'} sub={pick(T.cfUnavail, lang)} />
          )}
        </StaleGuard>
      </Section>
    </div>
  );
}

/* ── tiny legend chip ─────────────────────────────────────────────────────────────── */
function LegendChip({ color, dashed, label }) {
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
      <span aria-hidden="true" style={{ width: 18, height: 0, borderTop: `2px ${dashed ? 'dashed' : 'solid'} ${color}`, display: 'inline-block' }} />
      <span style={{ fontFamily: MONO, fontSize: '.625rem', color: 'var(--text-muted)' }}>{label}</span>
    </span>
  );
}
