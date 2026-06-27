import { useState, useEffect, useCallback } from 'react';

/*
 * DashboardLive — the real-time heart of /dashboard.
 *
 * Mirrors the LiveStatsWidget polling pattern (useEffect + setInterval), but is
 * the FIRST-CLASS dashboard island: it renders inside the site <Layout>, uses the
 * Console design tokens (via inline CSS-var styles so it matches the rest of
 * earn-defi.com pixel-for-pixel), and polls every ~15s.
 *
 * HONESTY CONTRACT (matches /track-record + LiveStatsWidget):
 *   - /api/ssot/facts is the SINGLE SOURCE OF TRUTH (primary fetch).
 *   - /api/live/fleet + /api/live/status + /api/v1/golive enrich detail panels.
 *   - If the API is unreachable we NEVER fabricate measured numbers. Every measured
 *     field falls back to "—" and the freshness badge flips to a clearly-labeled
 *     "snapshot — live API offline" state. We never paint stale data as live.
 *   - Only NON-measured structural constants survive offline (gate total = 29,
 *     days_needed = 30, the go-live plan date) and only because they are labeled
 *     as plan/criteria-count, not results.
 */

const API =
  typeof window !== 'undefined' &&
  (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1')
    ? 'http://localhost:8765'
    : 'https://api.earn-defi.com';

const POLL_MS = 15_000;
const FETCH_TIMEOUT_MS = 8_000;
const DAYS_NEEDED = 30;
const GATES_TOTAL_FALLBACK = 29;
const GOLIVE_TARGET_FALLBACK = '2026-07-21'; // plan date, labeled as such
const NA = '—';

/* ── i18n (mirrors the site's data-ru mechanism, but self-contained for the island) ── */
const T = {
  paperBanner: { en: 'PAPER TRADING', ru: 'БУМАЖНАЯ ТОРГОВЛЯ' },
  paperSub: {
    en: 'Virtual $100,000 USDC — no real capital at risk',
    ru: 'Виртуальные $100,000 USDC — реальный капитал не задействован',
  },
  live: { en: 'Live', ru: 'Вживую' },
  snapshot: { en: 'Snapshot — live API offline', ru: 'Снимок — живой API недоступен' },
  connecting: { en: 'Connecting…', ru: 'Подключение…' },
  updated: { en: 'Updated', ru: 'Обновлено' },
  refresh: { en: 'Refresh', ru: 'Обновить' },
  heroEyebrow: { en: 'The road to go-live', ru: 'Путь к go-live' },
  heroTitle: { en: 'Evidenced track days', ru: 'Подтверждённые дни трека' },
  heroSub: {
    en: 'Only days backed by a real daily-cycle log count. Target: 30 honest days, then owner review.',
    ru: 'Считаются только дни с реальным логом ежедневного цикла. Цель: 30 честных дней, затем ревью владельца.',
  },
  anchor: { en: 'Evidence anchor', ru: 'Якорь подтверждения' },
  target: { en: 'Go-live target', ru: 'Цель go-live' },
  daysLeft: { en: 'days remaining', ru: 'дней осталось' },
  golive: { en: 'Go-live criteria', ru: 'Критерии go-live' },
  goliveSub: {
    en: 'Deterministic checks (ADR-002). All must pass for 7+ consecutive days.',
    ru: 'Детерминированные проверки (ADR-002). Все должны пройти 7+ дней подряд.',
  },
  portfolio: { en: 'Paper portfolio', ru: 'Бумажный портфель' },
  equity: { en: 'Equity', ru: 'Капитал' },
  apyToday: { en: 'APY today', ru: 'APY сегодня' },
  dailyYield: { en: 'Daily yield', ru: 'Доход за день' },
  regime: { en: 'Market regime', ru: 'Рыночный режим' },
  totalReturn: { en: 'Total return', ru: 'Совокупная доходность' },
  nav: { en: 'NAV (reconciled)', ru: 'NAV (сверено)' },
  fleet: { en: 'Agent fleet', ru: 'Парк агентов' },
  fleetSub: {
    en: 'Autonomous launchd agents — daily cycle, monitors, autopush.',
    ru: 'Автономные launchd-агенты — дневной цикл, мониторы, автопуш.',
  },
  healthy: { en: 'Healthy', ru: 'Здоровы' },
  warning: { en: 'Warning', ru: 'Внимание' },
  critical: { en: 'Critical', ru: 'Критич.' },
  safety: { en: 'Safety state', ru: 'Состояние защиты' },
  safetySub: {
    en: 'Deterministic RiskPolicy v1.0 — LLM-free. Kill switch arms at -5% drawdown.',
    ru: 'Детерминированная RiskPolicy v1.0 — без LLM. Kill switch при просадке -5%.',
  },
  killSwitch: { en: 'Kill switch', ru: 'Kill switch' },
  riskPolicy: { en: 'Risk policy', ru: 'Риск-политика' },
  breakers: { en: 'Emergency breakers', ru: 'Аварийные предохранители' },
  positions: { en: 'Current allocation', ru: 'Текущая аллокация' },
  positionsSub: {
    en: 'Live virtual book across whitelisted protocols.',
    ru: 'Живой виртуальный портфель по whitelisted-протоколам.',
  },
  noPositions: {
    en: 'Live allocation unavailable offline.',
    ru: 'Живая аллокация недоступна офлайн.',
  },
  clear: { en: 'CLEAR', ru: 'ЧИСТО' },
  armed: { en: 'ARMED', ru: 'ВЗВЕДЕН' },
  approved: { en: 'Approved', ru: 'Одобрено' },
  blocked: { en: 'Blocked', ru: 'Заблокировано' },
  pass: { en: 'PASS', ru: 'ПРОЙДЕНО' },
  pending: { en: 'PENDING', ru: 'ОЖИДАНИЕ' },
  fail: { en: 'FAIL', ru: 'ПРОВАЛ' },
  ofNeeded: { en: 'of 30 needed', ru: 'из 30 нужных' },
  fullRecord: { en: 'Full track record →', ru: 'Полный трек-рекорд →' },
  methodology: { en: 'How the engine decides →', ru: 'Как движок решает →' },
};

function useLang() {
  const [lang, setLang] = useState('en');
  useEffect(() => {
    function read() {
      try {
        const v = window.localStorage.getItem('spa_lang');
        setLang(v === 'ru' ? 'ru' : 'en');
      } catch {
        setLang('en');
      }
    }
    read();
    // The site's i18n runtime calls window.__renderLive on toggle; also poll storage.
    window.__renderLive = read;
    const onStorage = (e) => { if (e.key === 'spa_lang') read(); };
    window.addEventListener('storage', onStorage);
    const id = setInterval(read, 1000);
    return () => {
      window.removeEventListener('storage', onStorage);
      clearInterval(id);
      if (window.__renderLive === read) delete window.__renderLive;
    };
  }, []);
  return lang;
}

/* ── formatting helpers ── */
const fmtUsd0 = (v) => (v == null ? NA : '$' + Number(v).toLocaleString('en-US', { maximumFractionDigits: 0 }));
const fmtUsd2 = (v) => (v == null ? NA : '$' + Number(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
const fmtPct = (v, d = 2) => (v == null ? NA : Number(v).toFixed(d) + '%');
const fmtSigned = (v, d = 2) => (v == null ? NA : (v >= 0 ? '+' : '') + Number(v).toFixed(d) + '%');

async function getJson(path) {
  const r = await fetch(API + path, {
    signal: AbortSignal.timeout(FETCH_TIMEOUT_MS),
    headers: { Accept: 'application/json' },
  });
  if (!r.ok) throw new Error('HTTP ' + r.status);
  return r.json();
}

/* daysBetween(now, targetISODate) → integer days remaining (>=0) */
function daysUntil(targetDate) {
  if (!targetDate) return null;
  const t = new Date(targetDate + 'T00:00:00Z').getTime();
  const now = Date.now();
  const d = Math.ceil((t - now) / 86_400_000);
  return d > 0 ? d : 0;
}

/* ── small presentational atoms (Console tokens via CSS vars) ── */
const card = {
  background: 'var(--bg-surface)',
  border: '1px solid var(--border)',
  borderRadius: 'var(--r-lg)',
};
const mono = { fontFamily: 'var(--font-mono)' };

function Panel({ children, style }) {
  return <div style={{ ...card, padding: '24px', ...style }}>{children}</div>;
}

function Eyebrow({ children }) {
  return (
    <p
      style={{
        ...mono,
        fontSize: '.6875rem',
        textTransform: 'uppercase',
        letterSpacing: '.12em',
        color: 'var(--text-faint)',
        marginBottom: '10px',
      }}
    >
      {children}
    </p>
  );
}

function Metric({ label, value, sub, accent }) {
  return (
    <div style={{ ...card, padding: '18px 18px 16px' }}>
      <p style={{ ...mono, fontSize: '.6875rem', textTransform: 'uppercase', letterSpacing: '.08em', color: 'var(--text-muted)', marginBottom: '8px' }}>
        {label}
      </p>
      <p style={{ ...mono, fontSize: '1.6rem', fontWeight: 700, color: accent || 'var(--text-primary)', lineHeight: 1.1 }}>
        {value}
      </p>
      {sub && <p style={{ fontSize: '.75rem', color: 'var(--text-muted)', marginTop: '6px' }}>{sub}</p>}
    </div>
  );
}

/* progress ring for the hero days metric */
function Ring({ value, max, label }) {
  const pct = max ? Math.max(0, Math.min(1, value / max)) : 0;
  const r = 64;
  const c = 2 * Math.PI * r;
  const dash = c * pct;
  return (
    <div style={{ position: 'relative', width: 160, height: 160, flexShrink: 0 }}>
      <svg width="160" height="160" viewBox="0 0 160 160" style={{ transform: 'rotate(-90deg)' }} aria-hidden="true">
        <circle cx="80" cy="80" r={r} fill="none" stroke="var(--border)" strokeWidth="10" />
        <circle
          cx="80" cy="80" r={r} fill="none" stroke="var(--data-teal)" strokeWidth="10"
          strokeLinecap="round" strokeDasharray={`${dash} ${c}`}
          style={{ transition: 'stroke-dasharray 600ms cubic-bezier(.4,0,.2,1)' }}
        />
      </svg>
      <div style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center' }}>
        <span style={{ ...mono, fontSize: '2rem', fontWeight: 700, color: 'var(--data-teal)', lineHeight: 1 }}>
          {value == null ? NA : value}
        </span>
        <span style={{ ...mono, fontSize: '.8rem', color: 'var(--text-muted)' }}>/ {max}</span>
        <span style={{ fontSize: '.6875rem', color: 'var(--text-faint)', marginTop: '4px', textTransform: 'uppercase', letterSpacing: '.08em' }}>
          {label}
        </span>
      </div>
    </div>
  );
}

function Bar({ value, max, color }) {
  const pct = max ? Math.max(0, Math.min(100, (value / max) * 100)) : 0;
  return (
    <div style={{ height: 8, borderRadius: 'var(--r-full)', background: 'var(--bg-surface-2)', overflow: 'hidden' }}>
      <div style={{ height: '100%', width: `${pct}%`, background: color, borderRadius: 'var(--r-full)', transition: 'width 600ms cubic-bezier(.4,0,.2,1)' }} />
    </div>
  );
}

function Chip({ tone, children }) {
  const tones = {
    ok: { bg: 'rgba(52,211,153,.12)', bd: 'rgba(52,211,153,.30)', fg: 'var(--ok)' },
    warn: { bg: 'rgba(242,181,60,.12)', bd: 'rgba(242,181,60,.30)', fg: 'var(--warn)' },
    danger: { bg: 'rgba(242,109,109,.12)', bd: 'rgba(242,109,109,.30)', fg: 'var(--danger)' },
    teal: { bg: 'rgba(54,194,180,.12)', bd: 'rgba(54,194,180,.30)', fg: 'var(--data-teal)' },
    muted: { bg: 'var(--bg-surface-2)', bd: 'var(--border-strong)', fg: 'var(--text-muted)' },
  };
  const t = tones[tone] || tones.muted;
  return (
    <span style={{ ...mono, display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: '.6875rem', padding: '4px 10px', borderRadius: 'var(--r-full)', background: t.bg, border: `1px solid ${t.bd}`, color: t.fg, whiteSpace: 'nowrap' }}>
      {children}
    </span>
  );
}

const HEADING = { fontSize: '1.25rem', fontWeight: 600, color: 'var(--text-primary)', lineHeight: 1.3 };
const SUBTEXT = { fontSize: '.8125rem', color: 'var(--text-muted)', lineHeight: 1.55, marginTop: '4px' };

export default function DashboardLive() {
  const lang = useLang();
  const tr = (k) => (T[k] ? T[k][lang] : k);

  const [facts, setFacts] = useState(null);
  const [fleet, setFleet] = useState(null);
  const [status, setStatus] = useState(null);
  const [golive, setGolive] = useState(null);
  const [isLive, setIsLive] = useState(false);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [phase, setPhase] = useState('connecting'); // connecting | live | offline

  const poll = useCallback(async () => {
    // SSOT first — it is the single source of truth and decides live/offline.
    try {
      const f = await getJson('/api/ssot/facts');
      setFacts(f);
      setIsLive(true);
      setPhase('live');
      setLastUpdated(new Date());
    } catch {
      setIsLive(false);
      setPhase('offline');
      // keep last-known facts? No — never paint stale as live. Null measured fields.
      setFacts(null);
      // detail panels also go offline
      setFleet(null);
      setStatus(null);
      setGolive(null);
      return;
    }
    // Detail enrichers — best-effort, independent (a 404 on one must not kill others).
    getJson('/api/live/fleet').then(setFleet).catch(() => setFleet(null));
    getJson('/api/live/status').then(setStatus).catch(() => setStatus(null));
    getJson('/api/v1/golive').then(setGolive).catch(() => setGolive(null));
  }, []);

  useEffect(() => {
    poll();
    const id = setInterval(poll, POLL_MS);
    return () => clearInterval(id);
  }, [poll]);

  /* ── derive display values (honest fallbacks) ── */
  const f = facts || {};
  const days = f.real_track_days ?? f.track_days ?? null;
  const target = f.go_live_target ?? (isLive ? null : GOLIVE_TARGET_FALLBACK);
  const anchor = f.evidenced_anchor ?? null;
  const gatesPass = f.golive_passed ?? null;
  const gatesTotal = f.golive_total ?? GATES_TOTAL_FALLBACK;
  const remaining = days != null ? Math.max(0, DAYS_NEEDED - days) : null;
  const targetDaysLeft = daysUntil(target);

  const ps = (status && status.paper_trading_status) || {};
  const killActive = ps.kill_switch_active === true;
  const killClear = ps.kill_switch_active === false;
  const riskApproved = ps.risk_policy_approved;
  const breakersClear = !ps.safety_check_failed && killClear;
  const positions = ps.current_positions && typeof ps.current_positions === 'object' ? ps.current_positions : null;
  const regime = f.regime ?? ps.market_regime ?? null;

  const fl = fleet && fleet.available !== false ? fleet : null;
  const fleetTotal = fl ? fl.total : null;

  /* go-live criteria rows from /api/v1/golive */
  const criteria = (golive && Array.isArray(golive.criteria)) ? golive.criteria : null;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      {/* Paper banner — the only persistent amber surface (design system §3.1) */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap', padding: '10px 16px', borderRadius: 'var(--r-md)', background: 'rgba(242,181,60,.10)', border: '1px solid rgba(242,181,60,.20)' }}>
        <span style={{ width: 8, height: 8, borderRadius: '50%', background: 'var(--warn)', animation: 'pulse 3s ease-in-out infinite', flexShrink: 0 }} aria-hidden="true" />
        <span style={{ ...mono, fontSize: '.75rem', fontWeight: 600, color: 'var(--warn)', letterSpacing: '.05em' }}>{tr('paperBanner')}</span>
        <span style={{ fontSize: '.8125rem', color: 'rgba(242,181,60,.75)' }}>{tr('paperSub')}</span>
      </div>

      {/* Freshness bar */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          {phase === 'live' ? (
            <Chip tone="ok">
              <span style={{ width: 7, height: 7, borderRadius: '50%', background: 'var(--ok)', animation: 'pulse 3s ease-in-out infinite' }} aria-hidden="true" />
              {tr('live')}
            </Chip>
          ) : phase === 'offline' ? (
            <Chip tone="warn">
              <span style={{ width: 7, height: 7, borderRadius: '50%', background: 'var(--warn)' }} aria-hidden="true" />
              {tr('snapshot')}
            </Chip>
          ) : (
            <Chip tone="muted">{tr('connecting')}</Chip>
          )}
          {lastUpdated && (
            <span style={{ ...mono, fontSize: '.6875rem', color: 'var(--text-muted)' }}>
              {tr('updated')} {lastUpdated.toLocaleTimeString(lang === 'ru' ? 'ru-RU' : 'en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
            </span>
          )}
        </div>
        <button
          onClick={poll}
          style={{ ...mono, fontSize: '.6875rem', color: 'var(--text-secondary)', background: 'transparent', border: '1px solid var(--border)', borderRadius: 'var(--r-sm)', padding: '6px 12px', cursor: 'pointer' }}
        >
          ↻ {tr('refresh')}
        </button>
      </div>

      {/* HERO — track days (the headline metric on the road to go-live) */}
      <Panel style={{ background: 'linear-gradient(180deg, rgba(54,194,180,.06), transparent)', border: '1px solid rgba(54,194,180,.22)', padding: '28px' }}>
        <Eyebrow>{tr('heroEyebrow')}</Eyebrow>
        <div style={{ display: 'flex', gap: 28, alignItems: 'center', flexWrap: 'wrap' }}>
          <Ring value={days} max={DAYS_NEEDED} label={lang === 'ru' ? 'дней' : 'days'} />
          <div style={{ flex: 1, minWidth: 240 }}>
            <h2 style={{ ...HEADING, fontSize: '1.5rem' }}>{tr('heroTitle')}</h2>
            <p style={{ ...SUBTEXT, maxWidth: 460 }}>{tr('heroSub')}</p>
            <div style={{ marginTop: 16, marginBottom: 12 }}>
              <Bar value={days || 0} max={DAYS_NEEDED} color="var(--data-teal)" />
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))', gap: 10 }}>
              <div style={{ ...card, padding: '10px 12px', background: 'var(--bg-base)' }}>
                <p style={{ ...mono, fontSize: '.625rem', textTransform: 'uppercase', letterSpacing: '.08em', color: 'var(--text-faint)', marginBottom: 4 }}>{tr('anchor')}</p>
                <p style={{ ...mono, fontSize: '.8125rem', color: 'var(--text-secondary)' }}>{anchor ?? NA}</p>
              </div>
              <div style={{ ...card, padding: '10px 12px', background: 'var(--bg-base)' }}>
                <p style={{ ...mono, fontSize: '.625rem', textTransform: 'uppercase', letterSpacing: '.08em', color: 'var(--text-faint)', marginBottom: 4 }}>{tr('target')}</p>
                <p style={{ ...mono, fontSize: '.8125rem', color: 'var(--data-teal)' }}>
                  {target ?? NA}
                  {targetDaysLeft != null && <span style={{ color: 'var(--text-muted)' }}> · {targetDaysLeft} {tr('daysLeft')}</span>}
                </p>
              </div>
              <div style={{ ...card, padding: '10px 12px', background: 'var(--bg-base)' }}>
                <p style={{ ...mono, fontSize: '.625rem', textTransform: 'uppercase', letterSpacing: '.08em', color: 'var(--text-faint)', marginBottom: 4 }}>{lang === 'ru' ? 'Осталось' : 'Remaining'}</p>
                <p style={{ ...mono, fontSize: '.8125rem', color: 'var(--text-secondary)' }}>{remaining == null ? NA : `${remaining} ${tr('ofNeeded')}`}</p>
              </div>
            </div>
          </div>
        </div>
      </Panel>

      {/* PORTFOLIO metric grid */}
      <div>
        <div style={{ marginBottom: 12 }}>
          <h2 style={HEADING}>{tr('portfolio')}</h2>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 12 }}>
          <Metric label={tr('equity')} value={fmtUsd0(f.current_equity)} sub={lang === 'ru' ? 'база $100k' : '$100k base'} />
          <Metric label={tr('apyToday')} value={fmtPct(f.apy_today_pct, 2)} accent="var(--data-teal)" sub={lang === 'ru' ? 'переменный' : 'variable'} />
          <Metric label={tr('dailyYield')} value={fmtUsd2(f.daily_yield_usd)} sub={lang === 'ru' ? 'бумажный' : 'paper'} />
          <Metric label={tr('totalReturn')} value={fmtSigned(f.total_return_pct, 2)} accent={(f.total_return_pct ?? 0) >= 0 ? 'var(--ok)' : 'var(--danger)'} />
          <Metric label={tr('regime')} value={regime ?? NA} />
          <Metric label={tr('nav')} value={fmtUsd0(f.nav)} accent="var(--data-teal)" sub={f.nav_reconciliation_ok ? (lang === 'ru' ? 'сверено ✓' : 'reconciled ✓') : undefined} />
        </div>
      </div>

      {/* Two-up: Go-live criteria + Safety state */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: 16 }}>
        <Panel>
          <Eyebrow>{tr('golive')}</Eyebrow>
          <div style={{ display: 'flex', alignItems: 'flex-end', gap: 8, marginBottom: 10 }}>
            <span style={{ ...mono, fontSize: '2.5rem', fontWeight: 700, color: 'var(--warn)', lineHeight: 1 }}>{gatesPass ?? NA}</span>
            <span style={{ ...mono, fontSize: '1.1rem', color: 'var(--text-muted)', marginBottom: 4 }}>/ {gatesTotal}</span>
          </div>
          <Bar value={gatesPass || 0} max={gatesTotal} color="var(--warn)" />
          <p style={{ ...SUBTEXT, marginTop: 10 }}>{tr('goliveSub')}</p>
          {criteria && (
            <div style={{ marginTop: 14, display: 'flex', flexDirection: 'column', gap: 6, maxHeight: 280, overflowY: 'auto' }}>
              {criteria.map((c) => {
                const st = (c.status || '').toUpperCase();
                const tone = st === 'PASS' ? 'ok' : st === 'FAIL' ? 'danger' : 'warn';
                const lbl = st === 'PASS' ? tr('pass') : st === 'FAIL' ? tr('fail') : tr('pending');
                return (
                  <div key={c.name} style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: '.8125rem' }}>
                    <span style={{ width: 62, flexShrink: 0 }}><Chip tone={tone}>{lbl}</Chip></span>
                    <span style={{ color: st === 'PASS' ? 'var(--text-muted)' : 'var(--text-secondary)' }}>
                      {c.name.replace(/_/g, ' ')}
                    </span>
                  </div>
                );
              })}
            </div>
          )}
        </Panel>

        <Panel>
          <Eyebrow>{tr('safety')}</Eyebrow>
          <p style={{ ...SUBTEXT, marginTop: 0, marginBottom: 16 }}>{tr('safetySub')}</p>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10 }}>
              <span style={{ fontSize: '.8125rem', color: 'var(--text-secondary)' }}>{tr('killSwitch')}</span>
              {status == null ? <Chip tone="muted">{NA}</Chip>
                : killActive ? <Chip tone="danger">{tr('armed')}</Chip>
                : <Chip tone="ok">{tr('clear')}</Chip>}
            </div>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10 }}>
              <span style={{ fontSize: '.8125rem', color: 'var(--text-secondary)' }}>{tr('riskPolicy')}</span>
              {status == null ? <Chip tone="muted">{NA}</Chip>
                : riskApproved === true ? <Chip tone="ok">v1.0 · {tr('approved')}</Chip>
                : riskApproved === false ? <Chip tone="danger">{tr('blocked')}</Chip>
                : <Chip tone="muted">{NA}</Chip>}
            </div>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10 }}>
              <span style={{ fontSize: '.8125rem', color: 'var(--text-secondary)' }}>{tr('breakers')}</span>
              {status == null ? <Chip tone="muted">{NA}</Chip>
                : breakersClear ? <Chip tone="ok">{tr('clear')}</Chip>
                : <Chip tone="warn">{ps.safety_check_reason || tr('armed')}</Chip>}
            </div>
          </div>
        </Panel>
      </div>

      {/* Fleet health */}
      <Panel>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
          <div>
            <Eyebrow>{tr('fleet')}</Eyebrow>
            <p style={{ ...SUBTEXT, marginTop: 0 }}>{tr('fleetSub')}</p>
          </div>
          {fl && (
            <Chip tone={fl.critical > 0 ? 'danger' : fl.warning > 0 ? 'warn' : 'ok'}>
              {fl.overall_status || (fl.critical > 0 ? 'CRIT' : fl.warning > 0 ? 'WARN' : 'OK')}
              {fl.stale ? ' · stale' : ''}
            </Chip>
          )}
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(110px, 1fr))', gap: 12, marginTop: 16 }}>
          <Metric label={tr('healthy')} value={fl ? fl.healthy : NA} accent="var(--ok)" />
          <Metric label={tr('warning')} value={fl ? fl.warning : NA} accent={fl && fl.warning > 0 ? 'var(--warn)' : undefined} />
          <Metric label={tr('critical')} value={fl ? fl.critical : NA} accent={fl && fl.critical > 0 ? 'var(--danger)' : undefined} />
          <Metric label={lang === 'ru' ? 'Всего' : 'Total'} value={fleetTotal ?? NA} />
        </div>
      </Panel>

      {/* Current allocation */}
      <Panel>
        <Eyebrow>{tr('positions')}</Eyebrow>
        <p style={{ ...SUBTEXT, marginTop: 0, marginBottom: 16 }}>{tr('positionsSub')}</p>
        {positions ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            {Object.entries(positions)
              .sort((a, b) => b[1] - a[1])
              .map(([name, amt]) => {
                const total = Object.values(positions).reduce((s, v) => s + v, 0) || 1;
                const pct = (amt / total) * 100;
                return (
                  <div key={name} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '8px 0', borderTop: '1px solid var(--border)' }}>
                    <span style={{ fontSize: '.8125rem', color: 'var(--text-secondary)', width: 150, flexShrink: 0 }}>{name.replace(/_/g, ' ')}</span>
                    <div style={{ flex: 1 }}><Bar value={pct} max={100} color="var(--accent)" /></div>
                    <span style={{ ...mono, fontSize: '.8125rem', color: 'var(--text-primary)', width: 88, textAlign: 'right', flexShrink: 0 }}>{fmtUsd0(amt)}</span>
                    <span style={{ ...mono, fontSize: '.75rem', color: 'var(--text-muted)', width: 48, textAlign: 'right', flexShrink: 0 }}>{pct.toFixed(0)}%</span>
                  </div>
                );
              })}
          </div>
        ) : (
          <p style={{ fontSize: '.8125rem', color: 'var(--text-muted)' }}>
            {tr('noPositions')} <a href="/track-record" style={{ color: 'var(--accent)' }}>/track-record</a>
          </p>
        )}
      </Panel>

      {/* deep links */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 12 }}>
        <a href="/track-record" style={{ ...card, padding: '16px 18px', color: 'var(--accent)', fontSize: '.875rem', fontWeight: 500 }}>{tr('fullRecord')}</a>
        <a href="/methodology" style={{ ...card, padding: '16px 18px', color: 'var(--accent)', fontSize: '.875rem', fontWeight: 500 }}>{tr('methodology')}</a>
      </div>
    </div>
  );
}
