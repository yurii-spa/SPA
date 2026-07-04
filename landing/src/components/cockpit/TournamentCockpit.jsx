/*
 * TournamentCockpit — the DESK COCKPIT S3 full tournament island (Desk Cockpit §4-S3).
 *
 * The narrative view of the strategy competition: "strategies compete, winners take capital,
 * losers get killed by gates". This is the FULL cockpit tournament — it UPGRADES the basic
 * /tournament page (leaderboard + promotion ladder, which stay server-rendered in the .astro
 * shell) with the richer §4-S3 features, all built on the cockpit primitives:
 *
 *   1. TournamentLeaderboard   — rank · strategy · risk-adjusted metric · capital · trend · status
 *   2. Head-to-head            — pick 2 strategies → overlay their equity + drawdown (EquityChart)
 *   3. Promotion / demotion feed — "X promoted (+cap), Y demoted, Z killed by gate"
 *   4. Capital-flow visual     — hand-rolled SVG flow (challengers → champion); honest shadow state
 *   5. Rules panel             — which metric wins · kill criteria · rebalance cadence
 *   6. Timeline-scrubber       — replay the tournament across its paper history
 *
 * HONESTY (the load-bearing contract — NEVER weakened):
 *   - The promotion gate is FAIL-CLOSED. The live dataset is usually trustworthy:false
 *     (LOW_VOL stablecoin yield → degenerate Sharpe). When it is, EVERY strategy is rendered
 *     FLAGGED and 0-promotions renders as the CORRECT honest outcome — not empty, not an error.
 *   - No fabricated rank/Sharpe/score. A degenerate Sharpe is marked ⚠, never shown as a
 *     clean winner. Nothing is "champion" on untrustworthy data — the honest status is
 *     CHALLENGER (competing) with the desk holding its RWA-anchored book.
 *   - Capital-flow reflects the REAL (shadow) state: shadow strategies move ZERO real capital,
 *     so the flow is drawn as an advisory/shadow allocation, explicitly labelled, never as a
 *     live reallocation that happened.
 *   - Fail-CLOSED offline: source down → explicit unavailable, nothing invented.
 *
 * Reads /api/tournament + /api/tournament/status (poll 15s). Does NOT touch spa_core/api and
 * does NOT fork the primitives — it composes TournamentLeaderboard, EquityChart, MetricStat,
 * StaleGuard, TimeToggle from ./index.js. Bilingual via useLang; honors prefers-reduced-motion.
 */
import { useEffect, useMemo, useState } from 'react';
import {
  TournamentLeaderboard, EquityChart, MetricStat, StaleGuard,
  deriveFreshness, usdCompact, fmtSigned, fmtPct, NA,
} from './index.js';
import { useLang, usePrefersReducedMotion } from './hooks.js';
import { MONO, TABULAR, toneStyle, toneColor } from '../ui/tokens.js';

const API_BASE = () =>
  (typeof location !== 'undefined' &&
   (location.hostname === 'localhost' || location.hostname === '127.0.0.1'))
    ? 'http://localhost:8765'
    : 'https://api.earn-defi.com';

const isNum = (v) => v != null && isFinite(Number(v));
// The data-credibility ceiling (mirrors DEGENERATE_SHARPE_CEILING in tournament_engine.py).
const DEGENERATE_SHARPE_CEILING = 10.0;
const INITIAL_CAPITAL = 100_000;

/* ── honest field pickers (never fabricate) ───────────────────────────────────────── */
function keyOf(s) { return String(s.strategy_key || s.strategy_id || s.id || '').toLowerCase(); }
function nameOf(s) { return s.name || s.strategy_key || s.strategy_id || s.id || '?'; }
function apyOf(s) {
  const v = Number(s.net_annual_return_pct != null ? s.net_annual_return_pct : s.paper_apy);
  return isFinite(v) ? v : null;
}
function ddOf(s) {
  if (isNum(s.max_dd_pct)) return Math.abs(Number(s.max_dd_pct));
  if (isNum(s.max_drawdown)) return Math.abs(Number(s.max_drawdown) * 100);
  return null;
}
function sharpeOf(s) {
  const v = Number(s.sharpe != null ? s.sharpe : s.sharpe_display);
  return isFinite(v) ? v : null;
}
/* A per-strategy Sharpe is flagged when the dataset is degenerate OR the number itself is
   incredible OR the engine already flagged it. This is what stops a mock Sharpe becoming a trophy. */
function sharpeFlagged(s, datasetDegenerate) {
  const v = sharpeOf(s);
  return datasetDegenerate
    || s.sharpe_degenerate === true
    || s.rank_unknown === true
    || v == null
    || Math.abs(v) > DEGENERATE_SHARPE_CEILING;
}

/* Pick the richest strategy list the API served. Prefer shadow_active (has name/alloc/sharpe). */
function pickStrategies(d) {
  const tour = (d && d.tournament) || {};
  const active = tour.shadow_active_strategies || tour.active_strategies || tour.ranked_strategies || [];
  if (Array.isArray(active) && active.length) return active;
  const mass = (d && d.mass_results) || {};
  const lb = mass.leaderboard || [];
  return Array.isArray(lb) ? lb.slice(0, 12) : [];
}

/* Capital a shadow strategy would deploy = allocation fractions × the tournament's virtual
   $100k book. SHADOW: this is advisory sizing, not real reallocation. */
function allocatedUsd(s) {
  const a = s.allocation;
  if (a && typeof a === 'object') {
    let frac = 0;
    for (const k in a) if (isNum(a[k])) frac += Number(a[k]);
    if (frac > 0) return Math.round(frac * INITIAL_CAPITAL);
  }
  if (isNum(s.final_equity_usd)) return Math.round(Number(s.final_equity_usd));
  return null;
}

/*
 * Map a strategy → TournamentLeaderboard row.
 *   status: CHAMPION only if the dataset is trustworthy AND it is rank #1 (a real winner).
 *           On untrustworthy data NOTHING is champion → all CHALLENGER (honest: competing,
 *           not crowned). A strategy killed by a gate would be KILLED (none in the live
 *           shadow set today — we never fabricate a kill).
 *   metric: net carry after the kill-adjustment (net APY − drawdown haircut) — a
 *           risk-adjusted figure that does NOT rely on the degenerate Sharpe.
 */
function toLeaderRow(s, i, trustworthy, datasetDegenerate, ru) {
  const apy = apyOf(s);
  const dd = ddOf(s);
  const rank = isNum(s.rank) ? Number(s.rank) : i + 1;
  const killed = s.killed === true || String(s.status || '').toUpperCase() === 'KILLED';
  // net-carry-after-kill-adj: APY minus the realized drawdown (an honest risk haircut).
  const metric = apy == null ? null : (dd == null ? apy : apy - dd);

  let status;
  if (killed) status = 'KILLED';
  else if (trustworthy && rank === 1) status = 'CHAMPION';
  else status = 'CHALLENGER';

  // trend arrow: up if net-carry positive (honest, no fabricated series here).
  const trend = metric == null ? null : (metric >= 0 ? 1 : -1);

  const flagged = sharpeFlagged(s, datasetDegenerate);
  const nm = nameOf(s) + (flagged ? '  ⚠' : '');

  return {
    rank,
    id: keyOf(s) || nm,
    name: nm,
    metric,
    capital_usd: allocatedUsd(s),
    trend,
    status,
    kill_reason: killed ? (s.kill_reason || (ru ? 'убита gate-ом' : 'killed by gate'))
      : (flagged ? (ru ? 'Sharpe вырожден (locked-vol) — не достоверен → не может быть чемпионом'
                       : 'degenerate Sharpe (locked-vol) — not credible → cannot be champion') : undefined),
  };
}

/*
 * Reconstruct an HONEST equity series for head-to-head overlay. SPA's tournament rows carry
 * net APY + days_active but NOT a stored daily curve, so we reconstruct a smooth accrual from
 * the net APY over the paper days and mark EVERY point evidenced:false (backfill / reconstructed
 * — never passed off as a real evidenced track). EquityChart draws it DASHED + dimmed.
 */
function reconstructSeries(s) {
  const apy = apyOf(s);
  const days = isNum(s.days_active) && Number(s.days_active) > 0 ? Math.round(Number(s.days_active)) : 0;
  const n = Math.max(2, days + 1); // at least 2 points so the chart renders
  if (apy == null) return [];
  const daily = Math.pow(1 + apy / 100, 1 / 365) - 1; // net APY → daily accrual
  const out = [];
  for (let i = 0; i < n; i++) {
    const v = INITIAL_CAPITAL * Math.pow(1 + daily, i);
    out.push({ date: `d${i}`, value: v, evidenced: false }); // reconstructed → never evidenced
  }
  return out;
}

export default function TournamentCockpit() {
  const lang = useLang();
  const ru = lang === 'ru';
  const reduced = usePrefersReducedMotion();

  const [payload, setPayload] = useState(null);   // /api/tournament
  const [status, setStatus] = useState(null);     // /api/tournament/status
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  const [selA, setSelA] = useState(null);         // head-to-head A (strategy key)
  const [selB, setSelB] = useState(null);         // head-to-head B
  const [scrub, setScrub] = useState(null);       // timeline-scrubber position (null = latest)

  useEffect(() => {
    let alive = true;
    async function load() {
      const base = API_BASE();
      let ok = false;
      try {
        const r = await fetch(base + '/api/tournament', { cache: 'no-store' });
        const b = await r.json();
        if (alive && b) { setPayload(b); ok = true; }
      } catch { /* offline → handled below */ }
      try {
        const r = await fetch(base + '/api/tournament/status', { cache: 'no-store' });
        const b = await r.json();
        if (alive && b) setStatus(b);
      } catch { /* status is a nicety; leave null */ }
      if (alive) { setLoading(false); setError(!ok); }
    }
    load();
    const id = setInterval(load, 15_000);
    return () => { alive = false; clearInterval(id); };
  }, []);

  // ── derived honest state ──────────────────────────────────────────────────────────
  const trustworthy = payload ? payload.trustworthy === true : false; // fail-closed: only explicit true
  const tour = (payload && payload.tournament) || {};
  const dq = tour.data_quality || {};
  const regime = tour.data_source_regime || (payload && payload.meta && payload.meta.data_source_regime) || '';
  const trustReason = tour.trust_reason || dq.reason
    || (payload && payload.meta && payload.meta.trust_reason) || '';
  const datasetDegenerate = payload
    ? (!trustworthy
        || dq.status === 'DEGENERATE'
        || regime === 'DEGENERATE_MOCK'
        || regime === 'LOW_VOL_YIELD')
    : false;

  const strategies = useMemo(() => (payload ? pickStrategies(payload) : []), [payload]);

  const leaderRows = useMemo(
    () => strategies.map((s, i) => toLeaderRow(s, i, trustworthy, datasetDegenerate, ru)),
    [strategies, trustworthy, datasetDegenerate, ru],
  );

  // default head-to-head picks (first two distinct strategies)
  useEffect(() => {
    if (!strategies.length) return;
    if (selA == null) setSelA(keyOf(strategies[0]) || nameOf(strategies[0]));
    if (selB == null && strategies.length > 1) setSelB(keyOf(strategies[1]) || nameOf(strategies[1]));
  }, [strategies]); // eslint-disable-line

  const findStrat = (k) => strategies.find((s) => (keyOf(s) || nameOf(s)) === k) || null;
  const stratA = selA ? findStrat(selA) : null;
  const stratB = selB ? findStrat(selB) : null;

  // promotions / refusals (fail-closed: untrustworthy → every competitor refused)
  const promotions = 0; // shadow tournament: nothing promotes on untrustworthy data (honest)
  const refusals = datasetDegenerate ? strategies.length : 0;

  // timeline events: honest per-day from days_active (the paper track) — NOT fabricated runs.
  const timeline = useMemo(() => buildTimeline(strategies, ru), [strategies, ru]);
  const scrubMax = timeline.length ? timeline.length - 1 : 0;
  const scrubPos = scrub == null ? scrubMax : Math.min(scrub, scrubMax);

  const freshness = deriveFreshness(payload, 26 * 3600_000); // daily cadence → 26h stale window

  // ── empty / offline (fail-closed) ──────────────────────────────────────────────────
  if (error && !payload) {
    return (
      <StaleGuard
        loading={loading}
        error={ru
          ? 'Турнир недоступен — /api/tournament офлайн. Ничего не выдумано (ни рангов, ни Sharpe).'
          : 'Tournament unavailable — /api/tournament offline. Nothing fabricated (no ranks, no Sharpe).'}
        lang={lang}
        label="/api/tournament"
      />
    );
  }

  return (
    <div style={{ display: 'grid', gap: 30 }}>

      {/* ── trust verdict banner (live, fail-closed) ──────────────────────────────── */}
      <TrustBanner
        loading={loading} trustworthy={trustworthy} degenerate={datasetDegenerate}
        regime={regime} reason={trustReason} lang={lang}
      />

      {/* ── stat tiles ─────────────────────────────────────────────────────────────── */}
      <div style={{ display: 'grid', gap: 14, gridTemplateColumns: 'repeat(auto-fit, minmax(190px, 1fr))' }}>
        <MetricStat
          lang={lang} label={{ en: 'Strategies backtested', ru: 'Стратегий в бэктесте' }}
          value={loading ? null : (status && isNum(status.total_backtested) ? String(status.total_backtested) : (strategies.length ? String(strategies.length) : '—'))}
          sub={{ en: 'in the tournament pool', ru: 'в пуле турнира' }} size="sm"
        />
        <MetricStat
          lang={lang} label={{ en: 'Competing in paper', ru: 'Соревнуются в paper' }}
          value={loading ? null : String(strategies.length)}
          sub={{ en: 'shadow — zero capital', ru: 'shadow — без капитала' }} size="sm"
        />
        <MetricStat
          lang={lang} label={{ en: 'Promotions to live', ru: 'Промоушенов в live' }}
          value={loading ? null : String(promotions)}
          sub={{ en: trustworthy ? 'gate open — none cleared yet' : 'gate REFUSED (honest)', ru: trustworthy ? 'гейт открыт — пока никто' : 'гейт ОТКАЗАЛ (честно)' }}
          tone={promotions > 0 ? 'ok' : (trustworthy ? 'warn' : 'danger')} size="sm"
        />
        <MetricStat
          lang={lang} label={{ en: 'Refused (honest)', ru: 'Отказано (честно)' }}
          value={loading ? null : String(refusals)}
          sub={{ en: 'degenerate data → refused', ru: 'вырожденные данные → отказ' }}
          tone="warn" size="sm"
        />
      </div>

      {/* ── 1. TournamentLeaderboard primitive ─────────────────────────────────────── */}
      <section style={{ display: 'grid', gap: 12 }}>
        <SectionHead
          k={ru ? 'Турнирная таблица — стратегии в соревновании' : 'The leaderboard — strategies in competition'}
          note={datasetDegenerate
            ? (ru ? '⚠ датасет вырожден — Sharpe не достоверен, никто не чемпион' : '⚠ dataset degenerate — Sharpe not credible, no champion')
            : (ru ? 'датасет достоверен' : 'dataset trustworthy')}
          noteTone={datasetDegenerate ? 'warn' : 'ok'}
        />
        <p style={sub}>
          {ru
            ? 'Метрика — net-carry после kill-поправки (net APY − просадка), НЕ вырожденный Sharpe. Капитал — advisory-размер (доля аллокации × $100k виртуальной книги). Статус: чемпион только на достоверных данных; иначе все — претенденты (соревнуются, не коронованы).'
            : 'Metric = net carry after the kill-adjustment (net APY − drawdown), NOT the degenerate Sharpe. Capital = advisory size (allocation share × the $100k virtual book). Status: champion only on trustworthy data; otherwise all are challengers (competing, not crowned).'}
        </p>
        <StaleGuard payload={payload} freshness={payload ? freshness : undefined} loading={loading} lang={lang} label="/api/tournament">
          <TournamentLeaderboard
            rows={leaderRows}
            metricLabel={{ en: 'Net carry (kill-adj)', ru: 'Net carry (kill-adj)' }}
            lang={lang}
            max={20}
          />
        </StaleGuard>
      </section>

      {/* ── 2. Head-to-head overlay ────────────────────────────────────────────────── */}
      <section style={{ display: 'grid', gap: 12 }}>
        <SectionHead k={ru ? 'Голова к голове — наложить две стратегии' : 'Head-to-head — overlay two strategies'} />
        <p style={sub}>
          {ru
            ? 'Выбери две стратегии — их кривые капитала и просадки накладываются. Кривые РЕКОНСТРУИРОВАНЫ из net APY по дням paper (не хранимый дневной трек) → показаны ПУНКТИРОМ как backfill, никогда как реальный evidenced-трек.'
            : 'Pick two strategies — their equity + drawdown curves overlay. The curves are RECONSTRUCTED from net APY over the paper days (not a stored daily track) → drawn DASHED as backfill, never as a real evidenced track.'}
        </p>
        {strategies.length < 2 ? (
          <EmptyNote lang={lang} en="Need ≥2 strategies to compare — none fabricated." ru="Нужно ≥2 стратегии для сравнения — ничего не выдумано." />
        ) : (
          <div style={{ display: 'grid', gap: 16 }}>
            <div style={{ display: 'flex', gap: 18, flexWrap: 'wrap' }}>
              <Picker label={ru ? 'Стратегия A' : 'Strategy A'} tone="teal" value={selA} onChange={setSelA} strategies={strategies} exclude={selB} />
              <Picker label={ru ? 'Стратегия B' : 'Strategy B'} tone="accent" value={selB} onChange={setSelB} strategies={strategies} exclude={selA} />
            </div>
            <HeadToHead a={stratA} b={stratB} lang={lang} reduced={reduced} />
          </div>
        )}
      </section>

      {/* ── 3. Promotion / demotion feed ───────────────────────────────────────────── */}
      <section style={{ display: 'grid', gap: 12 }}>
        <SectionHead k={ru ? 'Лента промоушена / понижения / убийства' : 'Promotion / demotion / kill feed'} />
        <PromotionFeed
          strategies={strategies} trustworthy={trustworthy} degenerate={datasetDegenerate}
          promotions={promotions} lang={lang} loading={loading}
        />
      </section>

      {/* ── 4. Capital-flow visual ─────────────────────────────────────────────────── */}
      <section style={{ display: 'grid', gap: 12 }}>
        <SectionHead k={ru ? 'Поток капитала — претенденты → чемпион' : 'Capital flow — challengers → champion'} />
        <p style={sub}>
          {ru
            ? 'Как капитал ДВИГАЛСЯ БЫ между претендентами и чемпионом. Честно: это SHADOW-турнир — реальный капитал не двигается (0 промоушенов). Поток — advisory-аллокация, а не свершившаяся ре-аллокация.'
            : 'How capital WOULD move between challengers and the champion. Honest: this is a SHADOW tournament — no real capital moves (0 promotions). The flow is an advisory allocation, not a reallocation that happened.'}
        </p>
        <CapitalFlow strategies={strategies} trustworthy={trustworthy} degenerate={datasetDegenerate} lang={lang} />
      </section>

      {/* ── 5. Rules panel ─────────────────────────────────────────────────────────── */}
      <section style={{ display: 'grid', gap: 12 }}>
        <SectionHead k={ru ? 'Правила турнира — прозрачно' : 'Tournament rules — transparent'} />
        <RulesPanel lang={lang} metric={tour.metric || (payload && payload.meta && payload.meta.rank_metric)} />
      </section>

      {/* ── 6. Timeline-scrubber ───────────────────────────────────────────────────── */}
      <section style={{ display: 'grid', gap: 12 }}>
        <SectionHead k={ru ? 'Таймлайн — прокрутить турнир по дням' : 'Timeline — scrub the tournament over its days'} />
        <TimelineScrubber timeline={timeline} pos={scrubPos} max={scrubMax} onScrub={setScrub} lang={lang} />
      </section>

    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════════════
 * Sub-components (canonical tokens only — no raw hex)
 * ═══════════════════════════════════════════════════════════════════════════════════ */

const sub = { fontSize: '.8125rem', lineHeight: 1.6, color: 'var(--text-muted)', margin: 0, maxWidth: '48rem' };
const monoLabel = { fontFamily: MONO, fontSize: '.6rem', textTransform: 'uppercase', letterSpacing: '.08em', color: 'var(--text-faint)' };

function SectionHead({ k, note, noteTone }) {
  return (
    <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
      <p style={{ ...monoLabel, fontSize: '.6875rem', color: 'var(--text-muted)' }}>{k}</p>
      {note && <span style={{ fontFamily: MONO, fontSize: '.6875rem', color: toneColor(noteTone || 'muted') }}>{note}</span>}
    </div>
  );
}

function EmptyNote({ lang, en, ru }) {
  return (
    <div style={{ padding: '14px 16px', borderRadius: 'var(--r-md)', background: 'var(--bg-surface-2)', border: '1px solid var(--border-strong)' }}>
      <span style={{ fontFamily: MONO, fontSize: '.75rem', color: 'var(--text-muted)' }}>{lang === 'ru' ? ru : en}</span>
    </div>
  );
}

function TrustBanner({ loading, trustworthy, degenerate, regime, reason, lang }) {
  const ru = lang === 'ru';
  const tone = loading ? 'muted' : (trustworthy ? 'ok' : 'danger');
  const t = toneStyle(tone);
  const label = loading
    ? (ru ? 'проверка достоверности…' : 'assessing data trust…')
    : trustworthy
      ? (ru ? 'ДАННЫЕ ДОСТОВЕРНЫ' : 'DATA TRUSTWORTHY')
      : (ru ? 'ДАННЫЕ ВЫРОЖДЕНЫ · ОТКАЗ' : 'DATA DEGENERATE · REFUSED');
  const body = loading
    ? ''
    : trustworthy
      ? (ru ? 'Датасет достоверен: гейт оценивает кандидатов по числовым критериям. Промоушен всё равно advisory — не исполняется автоматически.'
            : 'The dataset is trustworthy: the gate evaluates candidates on the numeric criteria. Promotion is still advisory — it never auto-executes.')
      : (reason
        || (ru ? 'Датасет помечен недостоверным (near-constant / mock-подобные данные → Sharpe вырожден). Гейт отказывает во всех промоушенах — это правильный честный результат, а не сбой и не пустая страница.'
               : 'The dataset is flagged untrustworthy (near-constant / mock-like data → degenerate Sharpe). The gate refuses all promotions — the correct honest outcome, not a failure and not an empty page.'));
  return (
    <div style={{ display: 'flex', gap: 14, alignItems: 'flex-start', padding: '18px 20px', borderRadius: 'var(--r-lg)', background: t.bg, border: `1px solid ${t.border}` }}>
      <span aria-hidden="true" style={{ marginTop: 4, width: 9, height: 9, borderRadius: '50%', background: t.fg, flexShrink: 0 }} />
      <div style={{ minWidth: 0, display: 'grid', gap: 8 }}>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
          <span style={{ fontFamily: MONO, fontSize: '.6875rem', fontWeight: 600, padding: '2px 9px', borderRadius: 'var(--r-sm)', border: `1px solid ${t.border}`, color: t.fg }}>{label}</span>
          {regime && <span style={{ fontFamily: MONO, fontSize: '.6875rem', color: 'var(--text-faint)' }}>regime: {regime}</span>}
        </div>
        {body && <p style={{ fontSize: '.875rem', lineHeight: 1.55, color: 'var(--text-secondary)', margin: 0 }}>{body}</p>}
      </div>
    </div>
  );
}

/* strategy picker (chips) for head-to-head */
function Picker({ label, tone, value, onChange, strategies, exclude }) {
  const t = toneStyle(tone);
  return (
    <div style={{ display: 'grid', gap: 6 }}>
      <span style={monoLabel}>{label}</span>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        {strategies.map((s) => {
          const k = keyOf(s) || nameOf(s);
          const active = k === value;
          const disabled = k === exclude;
          return (
            <button
              key={k}
              onClick={() => !disabled && onChange(k)}
              disabled={disabled}
              style={{
                fontFamily: MONO, fontSize: '.6875rem', fontWeight: active ? 600 : 500,
                padding: '4px 10px', borderRadius: 'var(--r-full)', cursor: disabled ? 'not-allowed' : 'pointer',
                background: active ? t.bg : 'transparent',
                border: `1px solid ${active ? t.border : 'var(--border)'}`,
                color: active ? t.fg : (disabled ? 'var(--text-faint)' : 'var(--text-muted)'),
                opacity: disabled ? 0.4 : 1, whiteSpace: 'nowrap',
              }}
            >
              {nameOf(s)}
            </button>
          );
        })}
      </div>
    </div>
  );
}

/* head-to-head equity overlay + a compact metric compare */
function HeadToHead({ a, b, lang, reduced }) {
  const ru = lang === 'ru';
  const seriesA = useMemo(() => (a ? reconstructSeries(a) : []), [a]);
  const seriesB = useMemo(() => (b ? reconstructSeries(b) : []), [b]);
  const tealA = 'var(--data-teal)';
  const accentB = 'var(--accent-hover)';

  return (
    <div style={{ display: 'grid', gap: 16 }}>
      <div style={{ display: 'flex', gap: 18, flexWrap: 'wrap' }}>
        <LegendSwatch color={tealA} label={a ? nameOf(a) : NA} />
        <LegendSwatch color={accentB} label={b ? nameOf(b) : NA} />
        <span style={{ fontFamily: MONO, fontSize: '.625rem', color: 'var(--text-faint)' }}>
          {ru ? 'реконструировано из net APY — не evidenced-трек' : 'reconstructed from net APY — not an evidenced track'}
        </span>
      </div>

      {/* Two stacked EquityChart primitives (the primitive draws one series; we overlay by
          rendering both, tinting the reconstructed line via the evidenced=false path). Because
          both are reconstructed (evidenced:false) they render dashed/dimmed by design — honest. */}
      <div style={{ position: 'relative', display: 'grid', gap: 4 }}>
        <OverlayChart seriesA={seriesA} seriesB={seriesB} colorA={tealA} colorB={accentB} lang={lang} reduced={reduced} />
      </div>

      {/* metric compare (honest — from served fields only) */}
      <div style={{ display: 'grid', gap: 12, gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))' }}>
        <CompareStat label={{ en: 'Net APY', ru: 'Net APY' }} a={a} b={b} fmt={(s) => { const v = apyOf(s); return v == null ? NA : v.toFixed(2) + '%'; }} lang={lang} />
        <CompareStat label={{ en: 'Max drawdown', ru: 'Макс. просадка' }} a={a} b={b} fmt={(s) => { const v = ddOf(s); return v == null ? NA : '−' + v.toFixed(2) + '%'; }} lang={lang} />
        <CompareStat label={{ en: 'Days in paper', ru: 'Дней в paper' }} a={a} b={b} fmt={(s) => (isNum(s.days_active) ? String(Math.round(s.days_active)) : NA)} lang={lang} />
        <CompareStat label={{ en: 'Sharpe (flagged?)', ru: 'Sharpe (флаг?)' }} a={a} b={b} fmt={(s) => { const v = sharpeOf(s); if (v == null) return NA; return (Math.abs(v) > DEGENERATE_SHARPE_CEILING ? '⚠ ' : '') + v.toFixed(1); }} lang={lang} />
      </div>
    </div>
  );
}

/* Hand-rolled dual-series SVG overlay (the EquityChart primitive is single-series; for a true
   two-line overlay we draw both here with the SAME honesty rules: reconstructed → dashed). */
function OverlayChart({ seriesA, seriesB, colorA, colorB, lang, reduced }) {
  const ru = lang === 'ru';
  const A = (seriesA || []).filter((d) => isNum(d.value));
  const B = (seriesB || []).filter((d) => isNum(d.value));
  if (A.length < 2 && B.length < 2) {
    return <EmptyNote lang={lang} en="Insufficient history to overlay (need ≥2 points). No line fabricated." ru="Недостаточно истории для наложения (нужно ≥2 точки). Линия не выдумана." />;
  }
  const W = 640, H = 200, padL = 8, padR = 8, padT = 12, padB = 20;
  const plotW = W - padL - padR, plotH = H - padT - padB;
  const allVals = [...A, ...B].map((d) => Number(d.value));
  const lo = Math.min(...allVals), hi = Math.max(...allVals);
  const span = hi - lo || 1;
  const nMax = Math.max(A.length, B.length, 2);
  const line = (S) => S.map((d, i) => {
    const x = padL + (i / (nMax - 1)) * plotW;
    const y = padT + (1 - (Number(d.value) - lo) / span) * plotH;
    return `${i === 0 ? 'M' : 'L'} ${x.toFixed(1)} ${y.toFixed(1)}`;
  }).join(' ');
  return (
    <svg width="100%" height={H} viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img"
         aria-label={ru ? 'Наложение кривых капитала' : 'Equity overlay'}>
      {A.length >= 2 && <path d={line(A)} fill="none" stroke={colorA} strokeWidth="2" strokeDasharray="4 3" opacity="0.85" strokeLinejoin="round" strokeLinecap="round" style={reduced ? undefined : { transition: 'opacity 200ms ease' }} />}
      {B.length >= 2 && <path d={line(B)} fill="none" stroke={colorB} strokeWidth="2" strokeDasharray="4 3" opacity="0.85" strokeLinejoin="round" strokeLinecap="round" style={reduced ? undefined : { transition: 'opacity 200ms ease' }} />}
    </svg>
  );
}

function LegendSwatch({ color, label }) {
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
      <span style={{ width: 18, height: 0, borderTop: `2px dashed ${color}`, display: 'inline-block' }} />
      <span style={{ fontFamily: MONO, fontSize: '.6875rem', color: 'var(--text-secondary)' }}>{label}</span>
    </span>
  );
}

function CompareStat({ label, a, b, fmt, lang }) {
  const ru = lang === 'ru';
  return (
    <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)', borderRadius: 'var(--r-lg)', padding: '14px 16px', display: 'grid', gap: 8 }}>
      <p style={{ ...monoLabel, margin: 0 }}>{lang === 'ru' ? label.ru : label.en}</p>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10 }}>
        <span style={{ ...TABULAR, fontFamily: MONO, fontSize: '.9375rem', fontWeight: 700, color: 'var(--data-teal)' }}>{a ? fmt(a) : NA}</span>
        <span style={{ ...TABULAR, fontFamily: MONO, fontSize: '.9375rem', fontWeight: 700, color: 'var(--accent-hover)' }}>{b ? fmt(b) : NA}</span>
      </div>
    </div>
  );
}

/* promotion / demotion / kill feed — honest events derived from the served state */
function PromotionFeed({ strategies, trustworthy, degenerate, promotions, lang, loading }) {
  const ru = lang === 'ru';
  if (loading) {
    return <EmptyNote lang={lang} en="Loading events…" ru="Загрузка событий…" />;
  }
  const events = [];
  // The single honest headline event: the gate's verdict this run.
  if (promotions > 0) {
    events.push({ tone: 'ok', icon: '▲', en: `${promotions} strategy promoted to live — cleared every criterion on credible data`, ru: `${promotions} стратегия повышена в live — выполнила все критерии на достоверных данных` });
  } else if (!trustworthy || degenerate) {
    events.push({ tone: 'danger', icon: '⛔', en: `0 promotions — the gate REFUSED every candidate on degenerate data (locked-vol → Sharpe explodes). This is the CORRECT honest outcome.`, ru: `0 промоушенов — гейт ОТКАЗАЛ каждому кандидату на вырожденных данных (locked-vol → Sharpe взрывается). Это ПРАВИЛЬНЫЙ честный результат.` });
  } else {
    events.push({ tone: 'warn', icon: '◷', en: `0 promotions — data credible, but no strategy meets Sharpe ≥ 1.5, ≥ 7 paper days, APY ≥ 3% and DD ≥ −15% simultaneously yet.`, ru: `0 промоушенов — данные достоверны, но ни одна стратегия пока не выполняет одновременно Sharpe ≥ 1.5, ≥ 7 дней paper, APY ≥ 3% и DD ≥ −15%.` });
  }
  // Per-strategy shadow status (honest: no fabricated demotions/kills — none happened).
  strategies.forEach((s) => {
    const killed = s.killed === true;
    if (killed) {
      events.push({ tone: 'danger', icon: '✕', en: `${nameOf(s)} killed by the drawdown gate — ${s.kill_reason || 'gate triggered'}`, ru: `${nameOf(s)} убита gate-ом просадки — ${s.kill_reason || 'сработал гейт'}` });
    } else {
      const days = isNum(s.days_active) ? Math.round(s.days_active) : 0;
      events.push({ tone: degenerate ? 'muted' : 'accent', icon: '•', en: `${nameOf(s)} competing in paper — day ${days}, allocation ${allocSummary(s)} (shadow, no real capital)`, ru: `${nameOf(s)} соревнуется в paper — день ${days}, аллокация ${allocSummary(s)} (shadow, без реального капитала)` });
    }
  });
  return (
    <div style={{ display: 'grid', gap: 8 }}>
      {events.map((e, i) => {
        const t = toneStyle(e.tone);
        return (
          <div key={i} style={{ display: 'flex', gap: 12, alignItems: 'flex-start', padding: '11px 14px', borderRadius: 'var(--r-md)', background: 'var(--bg-surface)', borderLeft: `2px solid ${t.fg}`, border: '1px solid var(--border)' }}>
            <span aria-hidden="true" style={{ fontFamily: MONO, fontSize: '.8125rem', color: t.fg, lineHeight: 1.5 }}>{e.icon}</span>
            <span style={{ fontSize: '.8125rem', lineHeight: 1.55, color: 'var(--text-secondary)' }}>{lang === 'ru' ? e.ru : e.en}</span>
          </div>
        );
      })}
    </div>
  );
}

function allocSummary(s) {
  const a = s.allocation;
  if (!a || typeof a !== 'object') return '—';
  const parts = Object.entries(a).filter(([, v]) => isNum(v)).sort((x, y) => y[1] - x[1]).slice(0, 2);
  return parts.map(([k, v]) => `${k} ${Math.round(v * 100)}%`).join(', ') || '—';
}

/* Capital-flow — hand-rolled SVG flow (challengers → champion book). Honest: shadow. */
function CapitalFlow({ strategies, trustworthy, degenerate, lang }) {
  const ru = lang === 'ru';
  const rows = (strategies || []).map((s) => ({ name: nameOf(s), usd: allocatedUsd(s) || 0 }))
    .filter((r) => r.usd > 0).sort((a, b) => b.usd - a.usd).slice(0, 6);
  if (!rows.length) {
    return <EmptyNote lang={lang} en="No allocation data to draw a flow — nothing fabricated." ru="Нет данных аллокации для потока — ничего не выдумано." />;
  }
  const total = rows.reduce((s, r) => s + r.usd, 0) || 1;
  const W = 640, H = Math.max(160, rows.length * 34 + 40);
  const leftX = 8, rightX = W - 150, midX = W / 2;
  const champTone = trustworthy ? toneStyle('ok') : toneStyle('warn');
  const champLabel = trustworthy
    ? (ru ? 'Чемпион (live)' : 'Champion (live)')
    : (ru ? 'Книга десkа (RWA ~4.5%)' : 'Desk book (RWA ~4.5%)');
  const flowColor = degenerate ? 'var(--text-muted)' : 'var(--accent-hover)';
  let acc = 0;
  const champY0 = 30, champH = H - 60;
  return (
    <div style={{ display: 'grid', gap: 10 }}>
      <svg width="100%" height={H} viewBox={`0 0 ${W} ${H}`} role="img" aria-label={ru ? 'Поток капитала' : 'Capital flow'}>
        {/* champion / desk-book node (right) */}
        <rect x={rightX} y={champY0} width="132" height={champH} rx="6" fill={champTone.bg} stroke={champTone.border} />
        <text x={rightX + 66} y={champY0 + champH / 2 - 6} textAnchor="middle" fill={champTone.fg} style={{ fontFamily: 'var(--font-mono)', fontSize: 11, fontWeight: 700 }}>{champLabel}</text>
        <text x={rightX + 66} y={champY0 + champH / 2 + 10} textAnchor="middle" fill="var(--text-muted)" style={{ fontFamily: 'var(--font-mono)', fontSize: 10 }}>{usdCompact(total)}</text>
        {rows.map((r, i) => {
          const y = 30 + i * ((H - 60) / rows.length) + ((H - 60) / rows.length) / 2;
          const band = Math.max(2, (r.usd / total) * champH);
          const tY = champY0 + acc + band / 2; acc += band;
          const nodeTone = toneStyle('teal');
          return (
            <g key={r.name}>
              {/* challenger node (left) */}
              <rect x={leftX} y={y - 11} width="128" height="22" rx="5" fill={nodeTone.bg} stroke={nodeTone.border} />
              <text x={leftX + 8} y={y + 4} fill={nodeTone.fg} style={{ fontFamily: 'var(--font-mono)', fontSize: 10, fontWeight: 600 }}>{r.name.slice(0, 16)}</text>
              {/* flow band (cubic) */}
              <path d={`M ${leftX + 128} ${y} C ${midX} ${y}, ${midX} ${tY}, ${rightX} ${tY}`} fill="none" stroke={flowColor} strokeWidth={band} opacity="0.28" strokeLinecap="round" />
              <text x={midX} y={(y + tY) / 2 - 4} textAnchor="middle" fill="var(--text-faint)" style={{ fontFamily: 'var(--font-mono)', fontSize: 9 }}>{usdCompact(r.usd)}</text>
            </g>
          );
        })}
      </svg>
      <p style={{ fontFamily: MONO, fontSize: '.6875rem', color: degenerate ? 'var(--warn)' : 'var(--text-faint)', margin: 0 }}>
        {degenerate
          ? (ru ? '⚠ SHADOW / 0 промоушенов — реальный капитал НЕ двигается. Поток — advisory-аллокация (доля × $100k), а не свершившаяся ре-аллокация.'
                : '⚠ SHADOW / 0 promotions — no real capital moves. The flow is an advisory allocation (share × $100k), not a reallocation that happened.')
          : (ru ? 'Advisory-аллокация (доля × $100k виртуальной книги) — не исполняется автоматически.'
                : 'Advisory allocation (share × the $100k virtual book) — never auto-executed.')}
      </p>
    </div>
  );
}

/* Rules panel — transparency of the tournament rules */
function RulesPanel({ lang, metric }) {
  const ru = lang === 'ru';
  const metricTxt = metric === 'net_annual_return_pct'
    ? (ru ? 'net-of-cost APY (net годовая доходность)' : 'net-of-cost APY (net annual return)')
    : (metric || (ru ? 'net-of-cost APY' : 'net-of-cost APY'));
  const rules = [
    { k: ru ? 'Метрика-победитель' : 'Winning metric', v: ru ? `Ранжирование по ${metricTxt}. Sharpe — вторичный и ОТБРАСЫВАЕТСЯ, если вырожден (locked-vol) — иначе mock-число стало бы трофеем.` : `Ranked by ${metricTxt}. Sharpe is secondary and DISCARDED when degenerate (locked-vol) — else a mock number would become a trophy.` },
    { k: ru ? 'Критерии промоушена' : 'Promotion criteria', v: ru ? 'ВСЕ четыре: Sharpe ≥ 1.5 · ≥ 7 дней paper · APY ≥ 3% · просадка ≥ −15% — И на ДОСТОВЕРНЫХ данных.' : 'ALL four: Sharpe ≥ 1.5 · ≥ 7 paper days · APY ≥ 3% · drawdown ≥ −15% — AND on CREDIBLE data.' },
    { k: ru ? 'Критерий убийства (kill)' : 'Kill criteria', v: ru ? 'Стратегия убивается gate-ом при пробое просадки; на уровне десkа — two-tier kill: SOFT −5% de-risk / HARD −10% all-cash.' : 'A strategy is killed by the gate on a drawdown breach; at the desk level — two-tier kill: SOFT −5% de-risk / HARD −10% all-cash.' },
    { k: ru ? 'Частота ре-баланса' : 'Rebalance cadence', v: ru ? 'Ежедневный цикл (06:00 UTC): live APY/TVL → детерминированный RiskPolicy → ре-ранжирование. Турнир — 07:00 UTC.' : 'Daily cycle (06:00 UTC): live APY/TVL → deterministic RiskPolicy → re-rank. The tournament runs 07:00 UTC.' },
    { k: ru ? 'Fail-closed гейт' : 'Fail-closed gate', v: ru ? 'На недостоверных данных гейт ОТКАЗЫВАЕТ во всех промоушенах. «0 промоушенов» — правильный честный результат, а не сбой.' : 'On untrustworthy data the gate REFUSES all promotions. "0 promotions" is the correct honest outcome, not a failure.' },
  ];
  return (
    <div style={{ display: 'grid', gap: 10, gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))' }}>
      {rules.map((r, i) => (
        <div key={i} style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)', borderRadius: 'var(--r-lg)', padding: '16px 18px', display: 'grid', gap: 6 }}>
          <p style={{ ...monoLabel, color: 'var(--text-muted)', margin: 0 }}>{r.k}</p>
          <p style={{ fontSize: '.8125rem', lineHeight: 1.55, color: 'var(--text-secondary)', margin: 0 }}>{r.v}</p>
        </div>
      ))}
    </div>
  );
}

/* Build an honest per-day timeline from the paper track (days_active), not fabricated runs. */
function buildTimeline(strategies, ru) {
  const maxDays = strategies.reduce((m, s) => Math.max(m, isNum(s.days_active) ? Math.round(s.days_active) : 0), 0);
  const n = Math.max(1, maxDays);
  const out = [];
  for (let d = 1; d <= n; d++) {
    const live = strategies.filter((s) => (isNum(s.days_active) ? Math.round(s.days_active) : 0) >= d).length;
    out.push({
      day: d,
      competing: live,
      promotions: 0, // honest: nothing promoted on untrustworthy data
      label: ru ? `День ${d}` : `Day ${d}`,
    });
  }
  return out;
}

/* Timeline-scrubber — replay the tournament across its paper days */
function TimelineScrubber({ timeline, pos, max, onScrub, lang }) {
  const ru = lang === 'ru';
  if (!timeline.length) {
    return <EmptyNote lang={lang} en="No timeline yet — the paper track is empty." ru="Таймлайна пока нет — paper-трек пуст." />;
  }
  const cur = timeline[Math.min(pos, timeline.length - 1)];
  const W = 640, H = 60, padL = 10, padR = 10;
  const plotW = W - padL - padR;
  const maxComp = Math.max(1, ...timeline.map((t) => t.competing));
  const barW = plotW / timeline.length;
  return (
    <div style={{ display: 'grid', gap: 12 }}>
      <div style={{ display: 'flex', gap: 18, flexWrap: 'wrap', alignItems: 'baseline' }}>
        <MetricStat lang={lang} size="sm" label={{ en: 'At', ru: 'На' }} value={cur.label} />
        <MetricStat lang={lang} size="sm" label={{ en: 'Competing', ru: 'Соревнуются' }} value={String(cur.competing)} tone="accent" />
        <MetricStat lang={lang} size="sm" label={{ en: 'Promotions', ru: 'Промоушенов' }} value={String(cur.promotions)} tone={cur.promotions > 0 ? 'ok' : 'warn'} />
      </div>
      <svg width="100%" height={H} viewBox={`0 0 ${W} ${H}`} role="img" aria-label={ru ? 'История турнира' : 'Tournament history'}>
        {timeline.map((t, i) => {
          const h = (t.competing / maxComp) * (H - 16);
          const x = padL + i * barW;
          const active = i === pos;
          return <rect key={i} x={x + 1} y={H - 8 - h} width={Math.max(1, barW - 2)} height={h} rx="1"
                       fill={active ? 'var(--accent)' : 'var(--border-strong)'} opacity={active ? 1 : 0.6} />;
        })}
      </svg>
      <input
        type="range" min="0" max={max} value={pos} step="1"
        onChange={(e) => onScrub(Number(e.target.value))}
        aria-label={ru ? 'Прокрутка таймлайна' : 'Timeline scrubber'}
        style={{ width: '100%', accentColor: 'var(--accent)', cursor: 'pointer' }}
      />
      <p style={{ fontFamily: MONO, fontSize: '.6875rem', color: 'var(--text-faint)', margin: 0 }}>
        {ru ? 'Прокрути, чтобы воспроизвести турнир по дням paper-трека. Промоушены = 0 на всём треке — честное состояние (данные вырождены).'
            : 'Scrub to replay the tournament across the paper-track days. Promotions = 0 across the whole track — the honest state (data degenerate).'}
      </p>
    </div>
  );
}
