import { useState, useEffect, useMemo, useCallback } from 'react';

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

// Risk-class color tokens (A best → D worst). Used by screener + detail.
export const CLASS_STYLE = {
  A: { bg: 'rgba(52,211,153,.12)', bd: 'rgba(52,211,153,.35)', fg: '#34D399' },
  B: { bg: 'rgba(91,141,239,.12)', bd: 'rgba(91,141,239,.35)', fg: '#79A4F5' },
  C: { bg: 'rgba(242,181,60,.12)', bd: 'rgba(242,181,60,.35)', fg: '#F2B53C' },
  D: { bg: 'rgba(242,109,109,.14)', bd: 'rgba(242,109,109,.40)', fg: '#F26D6D' },
};
const CLASS_FALLBACK = { bg: 'rgba(107,114,128,.12)', bd: 'rgba(107,114,128,.30)', fg: '#9aa3b2' };
export function classStyle(c) { return CLASS_STYLE[String(c || '').toUpperCase()] || CLASS_FALLBACK; }

// Refusal-verdict color tokens. Verdict comes verbatim from the API.
export const VERDICT_STYLE = {
  SAFE:   { bg: 'rgba(52,211,153,.12)', bd: 'rgba(52,211,153,.35)', fg: '#34D399', ru: 'БЕЗОПАСНО' },
  WATCH:  { bg: 'rgba(242,181,60,.12)', bd: 'rgba(242,181,60,.35)', fg: '#F2B53C', ru: 'НАБЛЮДЕНИЕ' },
  REFUSE: { bg: 'rgba(242,109,109,.14)', bd: 'rgba(242,109,109,.40)', fg: '#F26D6D', ru: 'ОТКАЗ' },
};
const VERDICT_FALLBACK = { bg: 'rgba(107,114,128,.12)', bd: 'rgba(107,114,128,.30)', fg: '#9aa3b2', ru: 'НЕИЗВЕСТНО' };
export function verdictStyle(v) { return VERDICT_STYLE[String(v || '').toUpperCase()] || VERDICT_FALLBACK; }

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

function Badge({ style, children, title }) {
  return (
    <span title={title} style={{
      display: 'inline-flex', alignItems: 'center', gap: 5, padding: '2px 8px',
      borderRadius: 6, fontFamily: 'var(--font-mono)', fontSize: 11, fontWeight: 600,
      background: style.bg, border: '1px solid ' + style.bd, color: style.fg, whiteSpace: 'nowrap',
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
  const sortMark = (k) => (sortKey === k ? (sortDir === 'asc' ? ' ▲' : ' ▼') : '');

  // ---- summary header ----
  const summaryTiles = summary ? [
    { lbl: T('Pools followed', 'Пулов отслеживается'), v: summary.total_pools != null ? String(summary.total_pools) : (pools.length ? String(pools.length) : '—') },
    { lbl: T('Refused (D / REFUSE)', 'Отказано (D / ОТКАЗ)'), v: summary.refused != null ? String(summary.refused) : '—', fg: '#F26D6D' },
    { lbl: T('Class A', 'Класс A'), v: summary.class_a != null ? String(summary.class_a) : '—', fg: '#34D399' },
    { lbl: T('TVL covered', 'TVL покрыто'), v: usd(summary.total_tvl_usd) },
  ] : [
    { lbl: T('Pools followed', 'Пулов отслеживается'), v: pools.length ? String(pools.length) : '—' },
    { lbl: T('Refused (D / REFUSE)', 'Отказано (D / ОТКАЗ)'), v: pools.length ? String(pools.filter((p) => String(p.refusal && p.refusal.verdict || '').toUpperCase() === 'REFUSE').length) : '—', fg: '#F26D6D' },
    { lbl: T('Class A', 'Класс A'), v: pools.length ? String(pools.filter((p) => String(p.risk_class || '').toUpperCase() === 'A').length) : '—', fg: '#34D399' },
    { lbl: T('TVL covered', 'TVL покрыто'), v: usd(pools.reduce((s, p) => s + (num(p.tvl_usd) || 0), 0) || null) },
  ];

  return (
    <div>
      {/* live / offline state chip + summary */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12, marginBottom: 16 }}>
        <span style={{
          display: 'inline-flex', alignItems: 'center', gap: 7, fontFamily: 'var(--font-mono)', fontSize: 12,
          padding: '4px 10px', borderRadius: 999,
          background: state === 'live' ? 'rgba(52,211,153,.10)' : 'rgba(107,114,128,.10)',
          border: '1px solid ' + (state === 'live' ? 'rgba(52,211,153,.30)' : 'var(--border)'),
          color: state === 'live' ? '#34D399' : 'var(--text-muted)',
        }}>
          <span style={{ width: 7, height: 7, borderRadius: '50%', background: state === 'live' ? '#34D399' : 'var(--text-muted)', animation: state === 'live' ? 'pulse 3s ease-in-out infinite' : 'none' }} />
          {state === 'loading' ? T('Loading…', 'Загрузка…') : state === 'live' ? (T('Live from api.earn-defi.com', 'Вживую с api.earn-defi.com') + (asOf ? ' · ' + asOf : '')) : T('API unavailable', 'API недоступно')}
        </span>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(150px,1fr))', gap: 12, marginBottom: 20 }}>
        {summaryTiles.map((t, i) => (
          <div key={i} style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)', borderRadius: 12, padding: '14px 16px' }}>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, textTransform: 'uppercase', letterSpacing: '.08em', color: 'var(--text-muted)', marginBottom: 6 }}>{t.lbl}</div>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 22, fontWeight: 700, color: t.fg || 'var(--text-primary)' }}>{t.v}</div>
          </div>
        ))}
      </div>

      {/* filters */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, alignItems: 'center', marginBottom: 16 }}>
        <FilterSelect label={T('Risk class', 'Класс риска')} value={fClass} onChange={setFClass}
          options={[['ALL', T('All', 'Все')], ['A', 'A'], ['B', 'B'], ['C', 'C'], ['D', 'D']]} />
        <FilterSelect label={T('Chain', 'Сеть')} value={fChain} onChange={setFChain}
          options={[['ALL', T('All', 'Все')], ...chains.map((c) => [c, c])]} />
        <FilterSelect label={T('Tier', 'Тир')} value={fTier} onChange={setFTier}
          options={[['ALL', T('All', 'Все')], ...tiers.map((t) => [t, t])]} />
        <label style={{ display: 'inline-flex', alignItems: 'center', gap: 7, fontSize: 13, color: 'var(--text-secondary)', cursor: 'pointer' }}>
          <input type="checkbox" checked={refusedOnly} onChange={(e) => setRefusedOnly(e.target.checked)} />
          {T('Refused only', 'Только отказанные')}
        </label>
      </div>

      {/* table */}
      <div style={{ overflowX: 'auto', border: '1px solid var(--border)', borderRadius: 16 }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 980 }}>
          <thead>
            <tr style={{ background: 'var(--bg-surface)', textAlign: 'left' }}>
              <Th onClick={() => toggleSort('protocol')}>{T('Pool', 'Пул') + sortMark('protocol')}</Th>
              <Th onClick={() => toggleSort('apy')} right>{T('APY (base+reward)', 'APY (база+награда)') + sortMark('apy')}</Th>
              <Th onClick={() => toggleSort('tvl')} right>{T('TVL', 'TVL') + sortMark('tvl')}</Th>
              <Th onClick={() => toggleSort('risk')}>{T('Risk', 'Риск') + sortMark('risk')}</Th>
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
    </div>
  );
}

function FilterSelect({ label, value, onChange, options }) {
  return (
    <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12, fontFamily: 'var(--font-mono)', color: 'var(--text-muted)' }}>
      {label}
      <select value={value} onChange={(e) => onChange(e.target.value)} style={{
        background: 'var(--bg-surface)', border: '1px solid var(--border)', borderRadius: 8,
        color: 'var(--text-secondary)', padding: '5px 8px', fontFamily: 'var(--font-mono)', fontSize: 12,
      }}>
        {options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
      </select>
    </label>
  );
}

function Th({ children, onClick, right }) {
  return (
    <th onClick={onClick} style={{
      padding: '11px 14px', fontFamily: 'var(--font-mono)', fontSize: 11, fontWeight: 600,
      textTransform: 'uppercase', letterSpacing: '.06em', color: 'var(--text-muted)',
      textAlign: right ? 'right' : 'left', cursor: onClick ? 'pointer' : 'default',
      whiteSpace: 'nowrap', userSelect: 'none',
    }}>{children}</th>
  );
}

// One exit-liquidity cell — a HOLE renders as "flagged", never a fabricated number.
function ExitCell({ pool, ticket, ru }) {
  const row = exitFor(pool, ticket);
  const hole = isHole(row);
  if (hole) {
    return (
      <td style={{ padding: '10px 14px', textAlign: 'right', fontFamily: 'var(--font-mono)', fontSize: 12, color: '#F26D6D', whiteSpace: 'nowrap' }}
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
        <a href={detailHref} style={{ color: 'var(--text-primary)', fontWeight: 600, fontSize: 13.5 }}>{pool.protocol || '?'}</a>
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>
          {(pool.asset || '?')} · {(pool.chain || '?')}{pool.tier ? ' · ' + pool.tier : ''}
        </div>
      </td>
      <td style={{ padding: '10px 14px', textAlign: 'right', fontFamily: 'var(--font-mono)', fontSize: 13, color: 'var(--text-primary)', whiteSpace: 'nowrap' }}>
        {pct(apy.total)}
        <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
          {pct(apy.base)}<span style={{ color: 'var(--text-faint)' }}> base</span>
          {num(apy.reward) ? <span style={{ color: '#F2B53C' }}> +{pct(apy.reward)} rwd</span> : null}
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
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: '#F26D6D', marginTop: 3 }}>{ru ? 'tail-veto' : 'tail-veto'}</div>
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
