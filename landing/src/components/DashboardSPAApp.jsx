/**
 * DashboardSPAApp.jsx — Phase-1 B1: true SPA shell for /dashboard-preview
 *
 * Sidebar switches central VIEW with no page reload. ONE shared live-data connection
 * (single poll for /api/ssot/facts + /api/live/fleet) feeds the KPI strip independently
 * of which view is active. Hash-based per-view URL routing:
 *   /dashboard-preview#overview   (default)
 *   /dashboard-preview#positions
 *   /dashboard-preview#monitoring
 *   /dashboard-preview#research
 *
 * Hard invariants: DashboardLive UNCHANGED (imported as-is). No LLM. No fabricated data.
 * Fails gracefully — every section shows "—" / offline, never fabricated numbers.
 * Fleet-card fix: STALE is presented distinctly from WARNING (not "WARNING · stale").
 */
import { useState, useEffect, useCallback } from 'react';
import DashboardLive from './DashboardLive.jsx';
import DfbScreener from './DfbScreener.jsx';
import RtmrMonitor from './RtmrMonitor.jsx';

const API =
  typeof window !== 'undefined' &&
  (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1')
    ? 'http://localhost:8765'
    : 'https://api.earn-defi.com';

const POLL_FACTS_MS = 15_000;
const POLL_FLEET_MS = 30_000;
const FETCH_TIMEOUT_MS = 8_000;

/* ── views ──────────────────────────────────────────────────────────────── */
const VIEWS = [
  { id: 'overview',   label: 'Overview',   ru: 'Обзор',        icon: '▦' },
  { id: 'positions',  label: 'Positions',  ru: 'Позиции',      icon: '▤' },
  { id: 'monitoring', label: 'Monitoring', ru: 'Мониторинг',   icon: '◉' },
  { id: 'research',   label: 'Research',   ru: 'Исследования', icon: '❋' },
];

/* ── helpers ─────────────────────────────────────────────────────────────── */
const getLang = () => {
  try {
    const l = localStorage.getItem('spa_lang');
    if (l === 'en' || l === 'ru') return l;
  } catch (_) {}
  return typeof document !== 'undefined' && document.documentElement.lang === 'ru' ? 'ru' : 'en';
};

const fmtUsd = (n) =>
  n == null ? '—' : '$' + Number(n).toLocaleString('en-US', { maximumFractionDigits: 0 });
const fmtPct = (n) => (n == null ? '—' : Number(n).toFixed(2) + '%');
const fmtTime = (d) =>
  d
    ? d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })
    : '—';

function readHash() {
  try {
    const h = (window.location.hash || '').replace(/^#\/?/, '');
    return VIEWS.some((v) => v.id === h) ? h : 'overview';
  } catch (_) {
    return 'overview';
  }
}

async function fetchJson(url) {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), FETCH_TIMEOUT_MS);
  try {
    const r = await fetch(url, { signal: ctrl.signal });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    return await r.json();
  } finally {
    clearTimeout(t);
  }
}

/* ── fleet chip — fix: STALE distinct from WARNING ──────────────────────── */
function FleetChip({ fl }) {
  const style = (color) => ({
    display: 'inline-block',
    padding: '2px 8px',
    borderRadius: 4,
    fontSize: '.6875rem',
    fontFamily: 'var(--font-mono)',
    fontWeight: 700,
    color,
    border: `1px solid ${color}55`,
    background: `${color}11`,
    whiteSpace: 'nowrap',
  });

  if (!fl || fl.available === false)
    return <span style={style('var(--text-muted)')}>Fleet: —</span>;

  /* STALE = data-freshness issue, not an operational alert — show as dim warning, not ERROR */
  if (fl.stale)
    return (
      <span style={{ ...style('var(--warn)'), opacity: 0.75, fontStyle: 'italic' }}>
        Fleet: STALE
      </span>
    );

  if ((fl.critical || 0) > 0)
    return (
      <span style={style('var(--danger)')}>
        Fleet: CRIT {fl.critical}
      </span>
    );

  if ((fl.warning || 0) > 0)
    return (
      <span style={style('var(--warn)')}>
        Fleet: WARN {fl.warning}
      </span>
    );

  return <span style={style('var(--ok)')}>Fleet: OK</span>;
}

/* ── research view ───────────────────────────────────────────────────────── */
const DESKS = [
  {
    id: 'rates',
    nameEn: 'Rates Desk',
    nameRu: 'Rates Desk',
    tag: 'GO',
    tagColor: 'var(--ok)',
    descEn:
      'Refusal-first fair-value engine: harvests mispriced carry, refuses tail-risk compensation. FixedCarry validated → live paper track.',
    descRu:
      'Refusal-first fair-value: харвест mispriced carry, отказывает tail-comp. FixedCarry валидирован → live-paper трек.',
    href: '/rates-desk',
  },
  {
    id: 'rwa',
    nameEn: 'RWA Backstop',
    nameRu: 'RWA Backstop',
    tag: 'measurement-GO',
    tagColor: 'var(--warn)',
    descEn:
      'Liquidation-NAV underwriter for tokenized-RWA collateral. Measurement GO; book NO-GO (relationships + capital + legal are off-code).',
    descRu:
      'Underwriter ликвидационного NAV для tokenized-RWA. Measurement GO; book NO-GO (отношения + капитал + legal — вне кода).',
    href: '/rwa-backstop',
  },
  {
    id: 'liq',
    nameEn: 'Liquidator Research',
    nameRu: 'Ликвидатор',
    tag: 'NO-GO',
    tagColor: 'var(--danger)',
    descEn:
      'Balance-sheet liquidator probe for long-tail/nested collateral. Addressable ~$2–4M/yr gross << $20M bar.',
    descRu:
      'Исследование balance-sheet ликвидатора. Адресуемый ~$2–4M/yr << планка $20M.',
    href: '/structural-desk',
  },
];

function ResearchView({ lang }) {
  const tr = (en, ru) => (lang === 'ru' ? ru : en);
  return (
    <div style={{ padding: '24px', maxWidth: 820 }}>
      <p style={{ fontSize: '.875rem', color: 'var(--text-muted)', marginBottom: 24 }}>
        {tr(
          'Three research theses — edge is structural measurement / underwriting, not rate.',
          'Три research-тезиса — edge = структурное измерение/андеррайтинг, не ставка.',
        )}
      </p>
      {DESKS.map((d) => (
        <a
          key={d.id}
          href={d.href}
          style={{
            display: 'block',
            padding: '16px 20px',
            marginBottom: 12,
            border: '1px solid var(--border)',
            borderRadius: 'var(--r-md)',
            background: 'var(--bg-surface)',
            textDecoration: 'none',
            color: 'var(--text-primary)',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6 }}>
            <strong style={{ fontSize: '.9375rem' }}>
              {lang === 'ru' ? d.nameRu : d.nameEn}
            </strong>
            <span
              style={{
                padding: '2px 8px',
                borderRadius: 4,
                fontSize: '.625rem',
                fontFamily: 'var(--font-mono)',
                fontWeight: 700,
                color: d.tagColor,
                background: `${d.tagColor}22`,
                border: `1px solid ${d.tagColor}44`,
              }}
            >
              {d.tag}
            </span>
          </div>
          <p style={{ margin: 0, fontSize: '.8125rem', color: 'var(--text-secondary)' }}>
            {lang === 'ru' ? d.descRu : d.descEn}
          </p>
        </a>
      ))}
      <a href="/structural-desk" style={{ fontSize: '.8125rem', color: 'var(--accent)' }}>
        {tr('Full Structural Desk index →', 'Structural Desk — полный индекс →')}
      </a>
    </div>
  );
}

/* ── main SPA app ────────────────────────────────────────────────────────── */
export default function DashboardSPAApp({ initialFacts = null }) {
  const [view, setView] = useState(readHash);
  const [collapsed, setCollapsed] = useState(() => {
    try { return localStorage.getItem('spa-shell-collapsed') === '1'; } catch (_) { return false; }
  });
  const [lang, setLang] = useState(getLang);

  /* shared live-data connection */
  const [facts, setFacts] = useState(initialFacts);
  const [fleet, setFleet] = useState(null);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [live, setLive] = useState(false);

  /* ── shared polls ────────────────────────────────────────────────────── */
  const pollFacts = useCallback(async () => {
    try {
      const data = await fetchJson(`${API}/api/ssot/facts`);
      setFacts(data);
      setLastUpdated(new Date());
      setLive(true);
    } catch (_) { /* stay on snapshot; live=false */ }
  }, []);

  const pollFleet = useCallback(async () => {
    try {
      const data = await fetchJson(`${API}/api/live/fleet`);
      setFleet(data);
    } catch (_) {
      setFleet({ available: false });
    }
  }, []);

  useEffect(() => {
    pollFacts();
    pollFleet();
    const tiF = setInterval(pollFacts, POLL_FACTS_MS);
    const tiL = setInterval(pollFleet, POLL_FLEET_MS);
    return () => { clearInterval(tiF); clearInterval(tiL); };
  }, [pollFacts, pollFleet]);

  /* ── hash routing ────────────────────────────────────────────────────── */
  useEffect(() => {
    const onHash = () => setView(readHash());
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);

  const navigate = (id) => {
    window.history.pushState(null, '', window.location.pathname + '#' + id);
    setView(id);
  };

  /* ── language sync ───────────────────────────────────────────────────── */
  useEffect(() => {
    const onLang = () => setLang(getLang());
    window.addEventListener('spa:lang', onLang);
    return () => window.removeEventListener('spa:lang', onLang);
  }, []);

  /* ── sidebar collapse ────────────────────────────────────────────────── */
  const toggleCollapse = () => {
    setCollapsed((c) => {
      try { localStorage.setItem('spa-shell-collapsed', c ? '0' : '1'); } catch (_) {}
      return !c;
    });
  };

  const tr = (en, ru) => (lang === 'ru' ? ru : en);

  /* ── KPI strip (shared live-data: single source) ─────────────────────── */
  const nav = facts?.nav_usd ?? facts?.current_equity ?? null;
  const apy = facts?.paper_apy_pct ?? facts?.apy_today_pct ?? null;
  const trackDays = facts?.track_days ?? facts?.real_track_days ?? null;
  const gatesPassed = facts?.golive_passed ?? null;
  const gatesTotal = facts?.golive_total ?? null;

  const kpis = [
    { label: tr('NAV (paper)', 'NAV (бумага)'), value: fmtUsd(nav), ok: false },
    { label: tr('Paper APY', 'Paper APY'), value: fmtPct(apy), ok: true },
    { label: tr('Track days', 'Дней трека'), value: (trackDays ?? '—') + ' / 30', ok: false },
    { label: tr('Go-live gates', 'Гейты go-live'), value: (gatesPassed ?? '—') + ' / ' + (gatesTotal ?? '—'), ok: false },
  ];

  /* ── view content ────────────────────────────────────────────────────── */
  const renderView = () => {
    switch (view) {
      case 'overview':   return <DashboardLive initialFacts={facts} />;
      case 'positions':  return <DfbScreener />;
      case 'monitoring': return <RtmrMonitor />;
      case 'research':   return <ResearchView lang={lang} />;
      default:           return <DashboardLive initialFacts={facts} />;
    }
  };

  const viewMeta = VIEWS.find((v) => v.id === view) || VIEWS[0];
  const sidebarW = collapsed ? 64 : 256;

  /* ── render ──────────────────────────────────────────────────────────── */
  return (
    <>
      {/* global responsive rules injected once — avoids CSS-in-JS dependency */}
      <style>{`
        .spa-root{display:flex;align-items:flex-start;min-height:100vh;background:var(--bg-base);color:var(--text-primary)}
        .spa-sidebar{box-sizing:border-box;align-self:stretch;position:sticky;top:0;min-height:100vh;border-right:1px solid var(--border);background:var(--bg-surface);padding:16px 12px;transition:width 140ms ease,flex-basis 140ms ease}
        .spa-body{flex:1 1 auto;min-width:0;display:flex;flex-direction:column}
        .spa-topbar{position:sticky;top:0;z-index:30;display:flex;align-items:center;justify-content:space-between;gap:16px;height:60px;padding:0 24px;background:color-mix(in srgb,var(--bg-base) 88%,transparent);backdrop-filter:blur(8px);border-bottom:1px solid var(--border);box-sizing:border-box}
        .spa-kpi{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px;padding:14px 24px;border-bottom:1px solid var(--border);background:var(--bg-surface)}
        .spa-kpi-cell{padding:11px 14px;background:var(--bg-base);border:1px solid var(--border);border-radius:var(--r-md)}
        .spa-kpi-label{font-size:.625rem;text-transform:uppercase;letter-spacing:.06em;color:var(--text-muted);font-family:var(--font-mono);margin-bottom:4px}
        .spa-kpi-value{font-size:1.125rem;font-weight:800;font-family:var(--font-mono)}
        .spa-nav{display:flex;flex-direction:column;gap:4px}
        .spa-navbtn{display:flex;align-items:center;width:100%;padding:9px 12px;margin-bottom:4px;border:none;border-radius:var(--r-md);cursor:pointer;text-align:left;font-size:.875rem;white-space:nowrap;background:transparent;color:var(--text-secondary);transition:background 120ms ease,color 120ms ease;font-family:var(--font-sans)}
        .spa-navbtn:hover{background:var(--bg-surface-2,var(--bg-base));color:var(--text-primary)}
        .spa-navbtn[aria-current=page]{background:var(--accent-bg);color:var(--accent)}
        .spa-collapse-btn{display:inline-flex;align-items:center;justify-content:center;width:28px;height:28px;border:1px solid var(--border);border-radius:4px;background:var(--bg-base);color:var(--text-muted);cursor:pointer;font-size:.75rem;font-family:var(--font-mono);transition:color 120ms ease}
        .spa-collapse-btn:hover{color:var(--text-primary)}
        @media(max-width:900px){
          .spa-root{flex-direction:column}
          .spa-sidebar{flex-basis:auto !important;width:100% !important;min-height:0 !important;position:sticky;top:0;z-index:31;border-right:none;border-bottom:1px solid var(--border)}
          .spa-nav{flex-direction:row;overflow-x:auto;gap:4px}
          .spa-navbtn{white-space:nowrap}
        }
      `}</style>

      <div className="spa-root">
        {/* ── sidebar ── */}
        <aside
          className="spa-sidebar"
          style={{ flexBasis: sidebarW + 'px', width: sidebarW + 'px' }}
          aria-label={tr('App navigation', 'Навигация приложения')}
        >
          {/* brand + collapse */}
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20 }}>
            {!collapsed && (
              <a href="/" style={{ color: 'var(--text-primary)', textDecoration: 'none', fontWeight: 700, fontSize: '.9375rem', lineHeight: 1 }}>
                SPA <span style={{ color: 'var(--accent)', fontSize: '.75rem', fontWeight: 400 }}>earn-defi</span>
              </a>
            )}
            <button
              className="spa-collapse-btn"
              style={{ marginLeft: collapsed ? 'auto' : 0 }}
              onClick={toggleCollapse}
              aria-label={collapsed ? tr('Expand sidebar', 'Развернуть меню') : tr('Collapse sidebar', 'Свернуть меню')}
            >
              {collapsed ? '»' : '«'}
            </button>
          </div>

          {/* nav */}
          <nav className="spa-nav" aria-label={tr('App sections', 'Разделы приложения')}>
            {VIEWS.map((v) => {
              const active = view === v.id;
              return (
                <button
                  key={v.id}
                  className="spa-navbtn"
                  onClick={() => navigate(v.id)}
                  aria-current={active ? 'page' : undefined}
                  title={collapsed ? (lang === 'ru' ? v.ru : v.label) : undefined}
                  style={{
                    justifyContent: collapsed ? 'center' : 'flex-start',
                    gap: collapsed ? 0 : 12,
                    background: active ? 'var(--accent-bg)' : undefined,
                    color: active ? 'var(--accent)' : undefined,
                  }}
                >
                  <span aria-hidden="true" style={{ width: 20, textAlign: 'center', fontSize: '1rem', flex: '0 0 auto' }}>
                    {v.icon}
                  </span>
                  {!collapsed && <span>{lang === 'ru' ? v.ru : v.label}</span>}
                </button>
              );
            })}
          </nav>

          {/* footer links */}
          {!collapsed && (
            <div style={{ marginTop: 24, paddingTop: 16, borderTop: '1px solid var(--border)' }}>
              <a href="/dashboard" style={{ display: 'block', fontSize: '.75rem', color: 'var(--text-faint)', textDecoration: 'none', padding: '3px 0' }}>
                {tr('← Live dashboard', '← Живой дашборд')}
              </a>
              <a href="https://checkup.earn-defi.com/check" target="_blank" rel="noopener noreferrer"
                style={{ display: 'block', fontSize: '.75rem', color: 'var(--accent)', textDecoration: 'none', padding: '3px 0', marginTop: 4 }}>
                {tr('Check wallet →', 'Проверить кошелёк →')}
              </a>
            </div>
          )}
        </aside>

        {/* ── main body ── */}
        <div className="spa-body">
          {/* compact topbar */}
          <header className="spa-topbar">
            <h1 style={{ margin: 0, fontSize: '1.0625rem', fontWeight: 700, color: 'var(--text-primary)' }}>
              {lang === 'ru' ? (viewMeta.ru || viewMeta.label) : viewMeta.label}
            </h1>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexShrink: 0 }}>
              <FleetChip fl={fleet} />
              <a
                href={`https://checkup.earn-defi.com/check?utm_source=dashboard-preview&utm_campaign=spa-topbar`}
                target="_blank"
                rel="noopener noreferrer"
                style={{
                  padding: '7px 14px',
                  borderRadius: 'var(--r-sm)',
                  background: 'var(--accent)',
                  color: '#fff',
                  fontSize: '.8125rem',
                  fontWeight: 600,
                  textDecoration: 'none',
                  whiteSpace: 'nowrap',
                }}
              >
                {tr('Check wallet →', 'Проверить кошелёк →')}
              </a>
            </div>
          </header>

          {/* KPI strip — ONE shared live-data connection for all views */}
          <div className="spa-kpi">
            {kpis.map((k) => (
              <div key={k.label} className="spa-kpi-cell">
                <div className="spa-kpi-label">{k.label}</div>
                <div className="spa-kpi-value" style={{ color: k.ok ? 'var(--ok)' : 'var(--text-primary)' }}>
                  {k.value}
                </div>
              </div>
            ))}
            {/* Last updated HH:MM:SS (spec requirement) */}
            <div className="spa-kpi-cell" style={{ display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
              <div className="spa-kpi-label">{tr('Last updated', 'Обновлено')}</div>
              <div className="spa-kpi-value" style={{ fontSize: '.9375rem', color: live ? 'var(--ok)' : 'var(--text-faint)' }}>
                {lastUpdated ? fmtTime(lastUpdated) : tr('connecting…', 'подключение…')}
              </div>
              {!live && initialFacts && (
                <div style={{ fontSize: '.5625rem', color: 'var(--text-faint)', fontFamily: 'var(--font-mono)', marginTop: 2 }}>
                  {tr('snapshot', 'снимок')}
                </div>
              )}
            </div>
          </div>

          {/* active view */}
          <main id="spa-main" style={{ flex: '1 1 auto' }}>
            {renderView()}
          </main>
        </div>
      </div>
    </>
  );
}
