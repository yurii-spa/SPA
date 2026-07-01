import { useState, useEffect, useMemo, useCallback } from 'react';
import { classStyle, verdictStyle } from './ui/riskStyles.js';

/*
 * DfbScreener.jsx — THE DFB risk-first pool screener (Lane-3 / WS-1.4).
 *
 * "DeBank shows you the yield; DFB shows you the RISK behind the yield — provably."
 *
 * CONSUMES Lane-2's read-only contract (we never recompute or soften the risk):
 *   GET /api/dfb/summary   → header stats
 *   GET /api/dfb/pools     → the screener list; each pool:
 *     { pool_id, protocol, chain, asset, tier, apy:{total,base,reward}, tvl_usd,
 *       risk_class (A/B/C/D), structural_haircut, total_haircut,
 *       exit_liquidity:[{ticket_usd,absorbable_usd,dex_exit_frac,flagged}],
 *       refusal:{verdict,reason,tail_veto}, as_of, data_source, feed_coverage, proof_hash }
 *
 * HONESTY CONTRACT (fail-CLOSED, red-team hardened):
 *   - The risk_class + refusal.verdict render STRAIGHT from the API — never recomputed,
 *     never softened in the UI.
 *   - An exit-liquidity ticket the API marks `flagged` (or with null absorbable_usd) renders
 *     as a HOLE ("flagged" / "—"), NEVER a fabricated absorbable number.
 *   - API offline → honest "Unavailable" empty-state, never a stale-as-live or fabricated table.
 *   - Numbers print "—" when null; nothing is 0-coerced.
 *
 * Bilingual via the site's spa_lang mechanism (re-renders on the spa:lang event; window.__renderLive
 * is also hooked by Layout's i18n runtime).
 */

const TICKETS = [1_000_000, 5_000_000, 10_000_000]; // $1M / $5M / $10M OUT — the differentiator columns

function apiBase() {
  if (typeof location === 'undefined') return 'https://api.earn-defi.com';
  return (location.hostname === 'localhost' || location.hostname === '127.0.0.1')
    ? 'http://localhost:8765'
    : 'https://api.earn-defi.com';
}
function readLang() {
  try { return (localStorage.getItem('spa_lang') || 'en') === 'ru' ? 'ru' : 'en'; } catch (e) { return 'en'; }
}
function num(x) { const n = Number(x); return Number.isFinite(n) ? n : null; }
function usd(x) {
  const n = num(x);
  if (n == null) return '—';
  if (Math.abs(n) >= 1e9) return '$' + (n / 1e9).toFixed(2) + 'B';
  if (Math.abs(n) >= 1e6) return '$' + (n / 1e6).toFixed(2) + 'M';
  if (Math.abs(n) >= 1e3) return '$' + (n / 1e3).toFixed(1) + 'k';
  return '$' + n.toFixed(0);
}
function pct(x) { const n = num(x); return n == null ? '—' : n.toFixed(2) + '%'; }

// Risk-class + refusal-verdict colors come from the ONE canonical map
// (ui/riskStyles.js → ui/tokens.js), so the board renders the risk language
// identically to the dashboard / academy / marketing. Re-exported here because
// DfbPoolDetail + DfbPortfolio historically import them from this module.
export { classStyle, verdictStyle };

// Find the exit-liquidity row for a given ticket size, fail-closed.
function exitFor(pool, ticket) {
  const rows = Array.isArray(pool.exit_liquidity) ? pool.exit_liquidity : [];
  return rows.find((r) => num(r.ticket_usd) === ticket) || null;
}
// Is a ticket a hole? (flagged OR absorbable unknown) → never show a fabricated number.
function isHole(row) {
  if (!row) return true;
  if (row.flagged === true) return true;
  return num(row.absorbable_usd) == null;
}

// One badge geometry, shared across all DFB islands (matches ui/Badge.astro §3.4).
function Badge({ style, children, title }) {
  return (
    <span title={title} style={{
      display: 'inline-flex', alignItems: 'center', gap: 6, padding: '4px 10px',
      borderRadius: 'var(--r-full)', fontFamily: 'var(--font-mono)', fontSize: 11, fontWeight: 500,
      lineHeight: 1, background: style.bg, border: '1px solid ' + style.bd, color: style.fg, whiteSpace: 'nowrap',
    }}>{children}</span>
  );
}

export default function DfbScreener() {
  const [ru, setRu] = useState(false);
  const [state, setState] = useState('loading'); // loading | live | offline
  const [pools, setPools] = useState([]);
  const [summary, setSummary] = useState(null);
  const [asOf, setAsOf] = useState(null);

  // Filters
  const [fClass, setFClass] = useState('ALL');  // ALL | A | B | C | D
  const [fChain, setFChain] = useState('ALL');
  const [fTier, setFTier] = useState('ALL');
  const [refusedOnly, setRefusedOnly] = useState(false);
  const [sortKey, setSortKey] = useState('risk'); // risk | apy | tvl | protocol
  const [sortDir, setSortDir] = useState('asc');

  // Sync language with the site toggle.
  useEffect(() => {
    setRu(readLang() === 'ru');
    const onLang = () => setRu(readLang() === 'ru');
    window.addEventListener('spa:lang', onLang);
    // Layout calls window.__renderLive on toggle; piggyback that too.
    const prev = window.__renderLive;
    window.__renderLive = function () { try { onLang(); } catch (e) {} if (typeof prev === 'function') { try { prev(); } catch (e) {} } };
    return () => { window.removeEventListener('spa:lang', onLang); window.__renderLive = prev; };
  }, []);

  const load = useCallback(() => {
    const base = apiBase();
    Promise.allSettled([
      fetch(base + '/api/dfb/pools').then((r) => r.json()),
      fetch(base + '/api/dfb/summary').then((r) => r.json()),
    ]).then(([poolsRes, sumRes]) => {
      let list = null;
      if (poolsRes.status === 'fulfilled' && poolsRes.value) {
        const v = poolsRes.value;
        list = Array.isArray(v) ? v : (Array.isArray(v.pools) ? v.pools : null);
        if (v && v.as_of) setAsOf(v.as_of);
      }
      if (list && list.length) {
        setPools(list);
        setState('live');
      } else {
        // Fail CLOSED — no list → honest offline, never a fabricated table.
        setPools([]);
        setState('offline');
      }
      if (sumRes.status === 'fulfilled' && sumRes.value) setSummary(sumRes.value);
    }).catch(() => { setPools([]); setState('offline'); });
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, 60_000); // poll ~60s
    return () => clearInterval(id);
  }, [load]);

  const chains = useMemo(() => {
    const s = new Set();
    pools.forEach((p) => { if (p.chain) s.add(p.chain); });
    return Array.from(s).sort();
  }, [pools]);
  const tiers = useMemo(() => {
    const s = new Set();
    pools.forEach((p) => { if (p.tier) s.add(p.tier); });
    return Array.from(s).sort();
  }, [pools]);

  const view = useMemo(() => {
    let rows = pools.slice();
    if (fClass !== 'ALL') rows = rows.filter((p) => String(p.risk_class || '').toUpperCase() === fClass);
    if (fChain !== 'ALL') rows = rows.filter((p) => p.chain === fChain);
    if (fTier !== 'ALL') rows = rows.filter((p) => p.tier === fTier);
    if (refusedOnly) rows = rows.filter((p) => String(p.refusal && p.refusal.verdict || '').toUpperCase() === 'REFUSE');
    const classRank = { A: 0, B: 1, C: 2, D: 3 };
    const dir = sortDir === 'asc' ? 1 : -1;
    rows.sort((a, b) => {
      let av, bv;
      if (sortKey === 'apy') { av = num(a.apy && a.apy.total) ?? -1; bv = num(b.apy && b.apy.total) ?? -1; }
      else if (sortKey === 'tvl') { av = num(a.tvl_usd) ?? -1; bv = num(b.tvl_usd) ?? -1; }
      else if (sortKey === 'protocol') { av = String(a.protocol || ''); bv = String(b.protocol || ''); }
      else { av = classRank[String(a.risk_class || '').toUpperCase()] ?? 9; bv = classRank[String(b.risk_class || '').toUpperCase()] ?? 9; }
      if (av < bv) return -1 * dir;
      if (av > bv) return 1 * dir;
      return 0;
    });
    return rows;
  }, [pools, fClass, fChain, fTier, refusedOnly, sortKey, sortDir]);

  function toggleSort(k) {
    if (sortKey === k) setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    else { setSortKey(k); setSortDir(k === 'protocol' ? 'asc' : (k === 'risk' ? 'asc' : 'desc')); }
  }
  const T = (en, r) => (ru ? r : en);

  // ---- summary header ----
  const summaryTiles = summary ? [
    { lbl: T('Pools followed', 'Пулов отслеживается'), v: summary.total_pools != null ? String(summary.total_pools) : (pools.length ? String(pools.length) : '—') },
    { lbl: T('Refused (D / REFUSE)', 'Отказано (D / ОТКАЗ)'), v: summary.refused != null ? String(summary.refused) : '—', fg: 'var(--danger)' },
    { lbl: T('Class A', 'Класс A'), v: summary.class_a != null ? String(summary.class_a) : '—', fg: 'var(--data-teal)' },
    { lbl: T('TVL covered', 'TVL покрыто'), v: usd(summary.total_tvl_usd) },
  ] : [
    { lbl: T('Pools followed', 'Пулов отслеживается'), v: pools.length ? String(pools.length) : '—' },
    { lbl: T('Refused (D / REFUSE)', 'Отказано (D / ОТКАЗ)'), v: pools.length ? String(pools.filter((p) => String(p.refusal && p.refusal.verdict || '').toUpperCase() === 'REFUSE').length) : '—', fg: 'var(--danger)' },
    { lbl: T('Class A', 'Класс A'), v: pools.length ? String(pools.filter((p) => String(p.risk_class || '').toUpperCase() === 'A').length) : '—', fg: 'var(--data-teal)' },
    { lbl: T('TVL covered', 'TVL покрыто'), v: usd(pools.reduce((s, p) => s + (num(p.tvl_usd) || 0), 0) || null) },
  ];

  return (
    <div>
      {/* live / offline state chip + summary */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12, marginBottom: 16 }}>
        <LiveChip state={state} label={state === 'loading' ? T('Loading…', 'Загрузка…') : state === 'live' ? (T('Live from api.earn-defi.com', 'Вживую с api.earn-defi.com') + (asOf ? ' · ' + asOf : '')) : T('API unavailable', 'API недоступно')} />
      </div>

      <h2 style={srOnly}>{T('Coverage summary', 'Сводка покрытия')}</h2>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(150px,1fr))', gap: 12, marginBottom: 20 }}>
        {summaryTiles.map((t, i) => (
          <div key={i} style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)', borderRadius: 12, padding: '14px 16px' }}>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, textTransform: 'uppercase', letterSpacing: '.08em', color: 'var(--text-muted)', marginBottom: 6 }}>{t.lbl}</div>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 22, fontWeight: 700, color: t.fg || 'var(--text-primary)' }}>{t.v}</div>
          </div>
        ))}
      </div>

      {/* filters */}
      <h2 style={srOnly}>{T('Filter the pools', 'Фильтры пулов')}</h2>
      <div role="group" aria-label={T('Filter the pools', 'Фильтры пулов')} style={{ display: 'flex', flexWrap: 'wrap', gap: 10, alignItems: 'center', marginBottom: 16 }}>
        <FilterSelect label={T('Risk class', 'Класс риска')} value={fClass} onChange={setFClass}
          options={[['ALL', T('All', 'Все')], ['A', 'A'], ['B', 'B'], ['C', 'C'], ['D', 'D']]} />
        <FilterSelect label={T('Chain', 'Сеть')} value={fChain} onChange={setFChain}
          options={[['ALL', T('All', 'Все')], ...chains.map((c) => [c, c])]} />
        <FilterSelect label={T('Tier', 'Тир')} value={fTier} onChange={setFTier}
          options={[['ALL', T('All', 'Все')], ...tiers.map((t) => [t, t])]} />
        <label style={{ display: 'inline-flex', alignItems: 'center', gap: 7, fontSize: 13, color: 'var(--text-secondary)', cursor: 'pointer' }}>
          <input type="checkbox" checked={refusedOnly} onChange={(e) => setRefusedOnly(e.target.checked)} style={{ accentColor: 'var(--accent)', width: 15, height: 15 }} />
          {T('Refused only', 'Только отказанные')}
        </label>
      </div>

      {/* table (desktop / wide) — hidden on narrow viewports where the card list takes over */}
      <h2 style={srOnly}>{T('Pools by risk', 'Пулы по риску')}</h2>
      <div className="dfb-screener-table" style={{ overflowX: 'auto', border: '1px solid var(--border)', borderRadius: 'var(--r-lg)' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 980 }}>
          <caption style={srOnly}>{T('DeFi pools ranked by risk class, with exit-liquidity by ticket size and a refusal verdict.', 'Пулы DeFi по классу риска, с ликвидностью на выход по размеру тикета и вердиктом отказа.')}</caption>
          <thead>
            <tr style={{ background: 'var(--bg-surface-2)', textAlign: 'left' }}>
              <Th sortKey="protocol" activeKey={sortKey} dir={sortDir} onSort={toggleSort}>{T('Pool', 'Пул')}</Th>
              <Th right sortKey="apy" activeKey={sortKey} dir={sortDir} onSort={toggleSort}>{T('APY (base+reward)', 'APY (база+награда)')}</Th>
              <Th right sortKey="tvl" activeKey={sortKey} dir={sortDir} onSort={toggleSort}>{T('TVL', 'TVL')}</Th>
              <Th sortKey="risk" activeKey={sortKey} dir={sortDir} onSort={toggleSort}>{T('Risk', 'Риск')}</Th>
              <Th right>{T('Exit @ $1M', 'Выход @ $1M')}</Th>
              <Th right>{T('@ $5M', '@ $5M')}</Th>
              <Th right>{T('@ $10M', '@ $10M')}</Th>
              <Th>{T('Verdict', 'Вердикт')}</Th>
              <Th right>{T('Proof', 'Proof')}</Th>
            </tr>
          </thead>
          <tbody>
            {state === 'loading' && (
              <tr><td colSpan={9} style={{ padding: '32px 16px', textAlign: 'center', color: 'var(--text-muted)' }}>{T('Loading the risk board…', 'Загрузка риск-борда…')}</td></tr>
            )}
            {state === 'offline' && (
              <tr><td colSpan={9} style={{ padding: '32px 16px', textAlign: 'center', color: 'var(--text-muted)' }}>
                {T('API unavailable — the risk board does not show fabricated data offline.', 'API недоступно — риск-борд не показывает выдуманные данные офлайн.')}
              </td></tr>
            )}
            {state === 'live' && view.length === 0 && (
              <tr><td colSpan={9} style={{ padding: '32px 16px', textAlign: 'center', color: 'var(--text-muted)' }}>{T('No pools match the filters.', 'Нет пулов по фильтрам.')}</td></tr>
            )}
            {state === 'live' && view.map((p) => <PoolRow key={p.pool_id} pool={p} ru={ru} T={T} />)}
          </tbody>
        </table>
      </div>

      {/* mobile / narrow — a stacked card per pool (the 9-col table forces horizontal scroll on a phone) */}
      <div className="dfb-screener-cards" style={{ display: 'none', flexDirection: 'column', gap: 12 }}>
        {state === 'loading' && <div style={emptyCard}>{T('Loading the risk board…', 'Загрузка риск-борда…')}</div>}
        {state === 'offline' && <div style={emptyCard}>{T('API unavailable — the risk board does not show fabricated data offline.', 'API недоступно — риск-борд не показывает выдуманные данные офлайн.')}</div>}
        {state === 'live' && view.length === 0 && <div style={emptyCard}>{T('No pools match the filters.', 'Нет пулов по фильтрам.')}</div>}
        {state === 'live' && view.map((p) => <PoolCard key={p.pool_id} pool={p} ru={ru} T={T} />)}
      </div>

      {/* responsive switch: table ≥720px, card list below */}
      <style>{`
        @media (max-width: 720px) {
          .dfb-screener-table { display: none; }
          .dfb-screener-cards { display: flex !important; }
        }
      `}</style>
    </div>
  );
}

export const srOnly = { position: 'absolute', width: 1, height: 1, padding: 0, margin: -1, overflow: 'hidden', clip: 'rect(0 0 0 0)', whiteSpace: 'nowrap', border: 0 };
const emptyCard = { padding: '28px 16px', textAlign: 'center', color: 'var(--text-muted)', border: '1px solid var(--border)', borderRadius: 'var(--r-lg)' };

// Live/offline chip — one dialect across DFB islands (green pulse live / muted offline).
export function LiveChip({ state, label }) {
  const live = state === 'live';
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 7, fontFamily: 'var(--font-mono)', fontSize: 12,
      padding: '4px 10px', borderRadius: 'var(--r-full)',
      background: live ? 'var(--ok-bg)' : 'var(--bg-surface-2)',
      border: '1px solid ' + (live ? 'var(--ok-border)' : 'var(--border)'),
      color: live ? 'var(--ok)' : 'var(--text-muted)',
    }}>
      <span style={{ width: 7, height: 7, borderRadius: '50%', background: live ? 'var(--ok)' : 'var(--text-muted)', animation: live ? 'pulse 3s cubic-bezier(.4,0,.6,1) infinite' : 'none' }} />
      {label}
    </span>
  );
}

export function FilterSelect({ label, value, onChange, options }) {
  return (
    <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12, fontFamily: 'var(--font-mono)', color: 'var(--text-muted)' }}>
      {label}
      <select value={value} onChange={(e) => onChange(e.target.value)} style={{
        background: 'var(--bg-surface-2)', border: '1px solid var(--border)', borderRadius: 'var(--r-md)',
        color: 'var(--text-primary)', padding: '6px 10px', fontFamily: 'var(--font-mono)', fontSize: 12,
        appearance: 'none', WebkitAppearance: 'none', cursor: 'pointer',
        backgroundImage: 'url("data:image/svg+xml,%3Csvg xmlns=\'http://www.w3.org/2000/svg\' width=\'12\' height=\'12\' viewBox=\'0 0 12 12\'%3E%3Cpath fill=\'%236B7280\' d=\'M3 4.5L6 7.5L9 4.5\'/%3E%3C/svg%3E")',
        backgroundRepeat: 'no-repeat', backgroundPosition: 'right 8px center', paddingRight: 26,
      }}>
        {options.map(([v, l]) => <option key={v} value={v} style={{ background: 'var(--bg-surface-2)', color: 'var(--text-primary)' }}>{l}</option>)}
      </select>
    </label>
  );
}

// Keyboard-operable, SR-announced sortable header (P0 a11y fix).
// A sortable <th> gets role=button + tabindex=0 + Enter/Space activation + aria-sort;
// non-sortable headers are plain. Contrast raised to --text-secondary (text-muted failed AA).
function Th({ children, sortKey, activeKey, dir, onSort, right }) {
  const sortable = !!sortKey && typeof onSort === 'function';
  const active = sortable && activeKey === sortKey;
  const ariaSort = active ? (dir === 'asc' ? 'ascending' : 'descending') : (sortable ? 'none' : undefined);
  const mark = active ? (dir === 'asc' ? '▲' : '▼') : '';
  const activate = () => sortable && onSort(sortKey);
  return (
    <th
      aria-sort={ariaSort}
      role={sortable ? 'button' : undefined}
      tabIndex={sortable ? 0 : undefined}
      onClick={sortable ? activate : undefined}
      onKeyDown={sortable ? (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); activate(); } } : undefined}
      style={{
        padding: '11px 14px', fontFamily: 'var(--font-mono)', fontSize: 11, fontWeight: 600,
        textTransform: 'uppercase', letterSpacing: '.06em',
        color: active ? 'var(--text-primary)' : 'var(--text-secondary)',
        textAlign: right ? 'right' : 'left', cursor: sortable ? 'pointer' : 'default',
        whiteSpace: 'nowrap', userSelect: 'none',
      }}
    >
      {children}{mark ? <span aria-hidden="true"> {mark}</span> : ''}
    </th>
  );
}

// One exit-liquidity cell — a HOLE renders as "flagged", never a fabricated number.
function ExitCell({ pool, ticket, ru }) {
  const row = exitFor(pool, ticket);
  const hole = isHole(row);
  if (hole) {
    return (
      <td style={{ padding: '10px 14px', textAlign: 'right', fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--danger)', whiteSpace: 'nowrap' }}
          title={ru ? 'недостаточно ликвидности на выход — не заполняется выдуманным числом' : 'insufficient exit liquidity — never backfilled with a fabricated number'}>
        {ru ? 'флаг' : 'flagged'}
      </td>
    );
  }
  const frac = num(row.dex_exit_frac);
  return (
    <td style={{ padding: '10px 14px', textAlign: 'right', fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--text-primary)', whiteSpace: 'nowrap' }}
        title={(ru ? 'поглощается ' : 'absorbable ') + usd(row.absorbable_usd) + (frac != null ? ' · ' + (frac * 100).toFixed(0) + '%' : '')}>
      {usd(row.absorbable_usd)}
      {frac != null && <span style={{ color: 'var(--text-muted)', fontSize: 11 }}> · {(frac * 100).toFixed(0)}%</span>}
    </td>
  );
}

function PoolRow({ pool, ru, T }) {
  const cs = classStyle(pool.risk_class);
  const verdict = String(pool.refusal && pool.refusal.verdict || '').toUpperCase();
  const vs = verdictStyle(verdict);
  const vLabel = ru ? vs.ru : (verdict || (ru ? 'НЕИЗВ.' : 'UNKNOWN'));
  const apy = pool.apy || {};
  const ph = pool.proof_hash ? String(pool.proof_hash) : '';
  const detailHref = '/board/pool?id=' + encodeURIComponent(pool.pool_id);
  return (
    <tr style={{ borderTop: '1px solid var(--border)' }}>
      <td style={{ padding: '10px 14px' }}>
        <a href={detailHref} style={{ color: 'var(--text-primary)', fontWeight: 600, fontSize: 13 }}>{pool.protocol || '?'}</a>
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>
          {(pool.asset || '?')} · {(pool.chain || '?')}{pool.tier ? ' · ' + pool.tier : ''}
        </div>
      </td>
      <td style={{ padding: '10px 14px', textAlign: 'right', fontFamily: 'var(--font-mono)', fontSize: 13, color: 'var(--text-primary)', whiteSpace: 'nowrap' }}>
        {pct(apy.total)}
        <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
          {pct(apy.base)}<span style={{ color: 'var(--text-faint)' }}> base</span>
          {num(apy.reward) ? <span style={{ color: 'var(--warn)' }}> +{pct(apy.reward)} rwd</span> : null}
        </div>
      </td>
      <td style={{ padding: '10px 14px', textAlign: 'right', fontFamily: 'var(--font-mono)', fontSize: 13, color: 'var(--text-secondary)', whiteSpace: 'nowrap' }}>{usd(pool.tvl_usd)}</td>
      <td style={{ padding: '10px 14px' }}>
        <Badge style={cs} title={(ru ? 'класс риска ' : 'risk class ') + (pool.risk_class || '?')}>{pool.risk_class || '?'}</Badge>
      </td>
      <ExitCell pool={pool} ticket={1_000_000} ru={ru} />
      <ExitCell pool={pool} ticket={5_000_000} ru={ru} />
      <ExitCell pool={pool} ticket={10_000_000} ru={ru} />
      <td style={{ padding: '10px 14px' }}>
        <Badge style={vs} title={pool.refusal && pool.refusal.reason ? pool.refusal.reason : ''}>
          <span style={{ width: 6, height: 6, borderRadius: '50%', background: vs.fg }} />{vLabel}
        </Badge>
        {pool.refusal && pool.refusal.tail_veto && (
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--danger)', marginTop: 3 }}>tail-veto</div>
        )}
      </td>
      <td style={{ padding: '10px 14px', textAlign: 'right', whiteSpace: 'nowrap' }}>
        <a href={detailHref} style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--data-teal)' }} title={ph}>
          {ph ? '#' + ph.slice(0, 8) : '—'}
        </a>
      </td>
    </tr>
  );
}

// Mobile card — the same pool, stacked (no horizontal scroll on a phone).
function PoolCard({ pool, ru, T }) {
  const cs = classStyle(pool.risk_class);
  const verdict = String(pool.refusal && pool.refusal.verdict || '').toUpperCase();
  const vs = verdictStyle(verdict);
  const vLabel = ru ? vs.ru : (verdict || (ru ? 'НЕИЗВ.' : 'UNKNOWN'));
  const apy = pool.apy || {};
  const ph = pool.proof_hash ? String(pool.proof_hash) : '';
  const detailHref = '/board/pool?id=' + encodeURIComponent(pool.pool_id);
  const exitLabel = (ticket) => {
    const row = exitFor(pool, ticket);
    return isHole(row) ? (ru ? 'флаг' : 'flagged') : usd(row.absorbable_usd);
  };
  const exitHole = (ticket) => isHole(exitFor(pool, ticket));
  return (
    <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)', borderRadius: 'var(--r-lg)', padding: 16 }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12 }}>
        <div style={{ minWidth: 0 }}>
          <a href={detailHref} style={{ color: 'var(--text-primary)', fontWeight: 600, fontSize: 15 }}>{pool.protocol || '?'}</a>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>
            {(pool.asset || '?')} · {(pool.chain || '?')}{pool.tier ? ' · ' + pool.tier : ''}
          </div>
        </div>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
          <Badge style={cs} title={(ru ? 'класс риска ' : 'risk class ') + (pool.risk_class || '?')}>{pool.risk_class || '?'}</Badge>
          <Badge style={vs} title={pool.refusal && pool.refusal.reason ? pool.refusal.reason : ''}>
            <span style={{ width: 6, height: 6, borderRadius: '50%', background: vs.fg }} />{vLabel}
          </Badge>
        </div>
      </div>
      <dl style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px 16px', margin: '12px 0 0', fontFamily: 'var(--font-mono)', fontSize: 12 }}>
        <div><dt style={cardDt}>APY</dt><dd style={cardDd}>{pct(apy.total)} <span style={{ color: 'var(--text-muted)' }}>({pct(apy.base)} base)</span></dd></div>
        <div><dt style={cardDt}>TVL</dt><dd style={cardDd}>{usd(pool.tvl_usd)}</dd></div>
        <div><dt style={cardDt}>{T('Exit @ $1M', 'Выход @ $1M')}</dt><dd style={{ ...cardDd, color: exitHole(1_000_000) ? 'var(--danger)' : 'var(--text-primary)' }}>{exitLabel(1_000_000)}</dd></div>
        <div><dt style={cardDt}>{T('Exit @ $10M', 'Выход @ $10M')}</dt><dd style={{ ...cardDd, color: exitHole(10_000_000) ? 'var(--danger)' : 'var(--text-primary)' }}>{exitLabel(10_000_000)}</dd></div>
      </dl>
      {pool.refusal && pool.refusal.tail_veto && (
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--danger)', marginTop: 8 }}>tail-veto</div>
      )}
      <div style={{ marginTop: 10, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <a href={detailHref} style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--data-teal)' }} title={ph}>
          {ph ? '#' + ph.slice(0, 8) : '—'}
        </a>
        <a href={detailHref} style={{ fontSize: 12, color: 'var(--accent)' }}>{T('detail →', 'детали →')}</a>
      </div>
    </div>
  );
}

const cardDt = { fontSize: 10, textTransform: 'uppercase', letterSpacing: '.06em', color: 'var(--text-muted)', margin: 0 };
const cardDd = { margin: '2px 0 0', color: 'var(--text-primary)' };
