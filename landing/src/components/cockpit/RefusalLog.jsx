/*
 * RefusalLog — the COCKPIT S5 public refusal LEDGER island (Desk Cockpit §4-S5).
 *
 * The signature differentiator, cockpit-grade: a fuller, filterable, stats-rich public
 * refusal LEDGER built on the RefusalFeed primitive + the unified /api/refusals endpoint
 * (which merges rates-desk + DFB refusals, maps reasons to the contract enum, estimates
 * capital-protected). Distinct from the marketing /refusals page (kept intact).
 *
 * Doctrine baked in (via the primitives — NEVER re-implemented here):
 *   - fail-CLOSED: no refusals / offline → an HONEST state, never fabricated. "0 refusals"
 *     and thin-data are honest states, not errors.
 *   - the `verified` proof badge is 3-STATE (verified→green / broken→red / absent→NEUTRAL);
 *     NEVER green on absent. The feed-level chain state comes from the REAL hash-chain
 *     verification (/api/rates-desk/refusals::chain.verified), not fabricated.
 *   - capital-protected is an HONEST ESTIMATE (labelled "est", summed from the API's
 *     capital_protected_est_usd; UNKNOWN rows contribute nothing) — never a claim.
 *   - the reason enum matches the API contract exactly (REFUSAL_REASONS).
 *
 * Data (fetched client-side, api-base detection + graceful offline):
 *   GET /api/refusals?limit=200 →
 *     { ts, stale, newest_ts, reason_enum, reason_counts, n_refusals,
 *       refusals:[{ ts, opportunity, reason(enum|null), reason_raw, expected_edge_pct,
 *                   fee_drag_pct, verdict:"REFUSE", capital_protected_est_usd, engine, ref }] }
 *   GET /api/rates-desk/refusals?limit=1 → { chain:{ verified, head_hash, chain_length } }
 *     (the REAL hash-chain verification for the honest proof badge).
 */
import { useEffect, useMemo, useState } from 'react';
import {
  RefusalFeed, MetricStat, StaleGuard, TimeToggle,
  usdCompact, deriveFreshness,
} from './index.js';
import { useLang } from './hooks.js';
import { MONO, TABULAR, toneStyle } from '../ui/tokens.js';

/* The contract enum + human labels (EN|RU). MUST match REFUSAL_REASONS in the API. */
const REASON_META = {
  spread_below_fee_drag: { en: 'Spread below fee drag', ru: 'Спред ниже комиссий' },
  funding_flip_risk:     { en: 'Funding-flip risk', ru: 'Риск разворота funding' },
  counterparty_flag:     { en: 'Counterparty flag', ru: 'Флаг контрагента' },
  oi_concentration:      { en: 'OI concentration', ru: 'Концентрация OI' },
  liquidity:             { en: 'Liquidity / thin exit', ru: 'Ликвидность / тонкий выход' },
  unmapped:              { en: 'Other (unmapped)', ru: 'Другое (без маппинга)' },
};

const API_BASE = () =>
  (typeof location !== 'undefined' &&
   (location.hostname === 'localhost' || location.hostname === '127.0.0.1'))
    ? 'http://localhost:8765'
    : 'https://api.earn-defi.com';

/* window → milliseconds cutoff (null = inception/ALL) */
const WINDOW_MS = { '1D': 864e5, '7D': 7 * 864e5, '30D': 30 * 864e5, ALL: null };

const epochOf = (ts) => {
  if (ts == null) return null;
  if (typeof ts === 'number' && isFinite(ts)) return ts > 1e12 ? ts : ts * 1000;
  const p = Date.parse(String(ts));
  return isNaN(p) ? null : p;
};

/*
 * Map ONE /api/refusals row → the RefusalFeed DecisionRow shape.
 *   - kind: always REFUSAL (this feed is refusalOnly).
 *   - reason: the human label for the enum (honest; unmapped preserves reason_raw).
 *   - net_edge / fee_drag: the API returns PERCENT → RefusalFeed's DecisionRow treats
 *     |v|>1 as already-percent (it only *×100 when |v|≤1), so pass percent straight.
 *   - size_usd: the capital-protected estimate (labelled by the stat card, not a claim).
 *   - entry_hash: the row's proof ref → drives the collapsible proof block.
 *   - verified: the REAL feed-level chain verdict (true→green / false→red / null→neutral);
 *     never a fabricated per-row "verified".
 */
function toRow(r, lang, chainVerified) {
  const enumKey = r.reason || 'unmapped';
  const meta = REASON_META[enumKey] || REASON_META.unmapped;
  const label = lang === 'ru' ? meta.ru : meta.en;
  const raw = enumKey === 'unmapped' && r.reason_raw ? ` (${r.reason_raw})` : '';
  return {
    kind: 'REFUSAL',
    verdict: 'REFUSE',
    ts: r.ts || null,
    subject: r.opportunity || '?',
    desk: r.engine || undefined,
    reason: label + raw,
    net_edge: (r.expected_edge_pct != null && isFinite(r.expected_edge_pct)) ? Number(r.expected_edge_pct) : undefined,
    fee_drag: (r.fee_drag_pct != null && isFinite(r.fee_drag_pct)) ? Number(r.fee_drag_pct) : undefined,
    size_usd: (r.capital_protected_est_usd != null && isFinite(r.capital_protected_est_usd)) ? Number(r.capital_protected_est_usd) : undefined,
    entry_hash: r.ref || undefined,
    // honest 3-state: only green when the WHOLE chain verified; broken→false; absent→null.
    verified: typeof chainVerified === 'boolean' ? chainVerified : null,
    _reasonKey: enumKey,
    _engine: r.engine || 'unknown',
  };
}

export default function RefusalLog() {
  const lang = useLang();
  const ru = lang === 'ru';

  const [payload, setPayload] = useState(null);   // /api/refusals body
  const [chain, setChain] = useState(null);        // { verified, head_hash, chain_length }
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  const [win, setWin] = useState('ALL');
  const [reasonFilter, setReasonFilter] = useState('ALL'); // enum key | 'ALL'
  const [engineFilter, setEngineFilter] = useState('ALL'); // engine | 'ALL'

  useEffect(() => {
    let alive = true;
    async function load() {
      const base = API_BASE();
      // Primary: the unified enum ledger + stats. Fail-CLOSED on any error.
      let ok = false;
      try {
        const res = await fetch(base + '/api/refusals?limit=200', { cache: 'no-store' });
        const body = await res.json();
        if (alive && body && Array.isArray(body.refusals)) { setPayload(body); ok = true; }
      } catch { /* offline → handled below */ }
      // Chain badge: the REAL hash-chain verdict (separate endpoint). Absent → neutral.
      try {
        const res = await fetch(base + '/api/rates-desk/refusals?limit=1', { cache: 'no-store' });
        const body = await res.json();
        if (alive && body && body.chain) setChain(body.chain);
      } catch { /* leave chain null → neutral badge (never green on absent) */ }
      if (alive) { setLoading(false); setError(!ok); }
    }
    load();
    const id = setInterval(load, 60_000); // poll (refusals cadence is hours; 60s is ample)
    return () => { alive = false; clearInterval(id); };
  }, []);

  const chainVerified = chain && typeof chain.verified === 'boolean' ? chain.verified : null;
  const allRows = payload && Array.isArray(payload.refusals) ? payload.refusals : [];

  // window filter (client-side, on ts)
  const winRows = useMemo(() => {
    const span = WINDOW_MS[win];
    if (span == null) return allRows;
    const cut = Date.now() - span;
    return allRows.filter((r) => { const e = epochOf(r.ts); return e == null || e >= cut; });
  }, [allRows, win]);

  // engine set (for the engine filter)
  const engines = useMemo(() => {
    const s = new Set();
    for (const r of winRows) if (r.engine) s.add(r.engine);
    return Array.from(s).sort();
  }, [winRows]);

  // reason + engine filter → the rows shown in the ledger
  const filtered = useMemo(() => winRows.filter((r) => {
    const key = r.reason || 'unmapped';
    if (reasonFilter !== 'ALL' && key !== reasonFilter) return false;
    if (engineFilter !== 'ALL' && (r.engine || 'unknown') !== engineFilter) return false;
    return true;
  }), [winRows, reasonFilter, engineFilter]);

  const feedRows = useMemo(
    () => filtered.map((r) => toRow(r, lang, chainVerified)),
    [filtered, lang, chainVerified],
  );

  // ── stats (from the WINDOW rows, honest) ──────────────────────────────────────────
  // reason histogram over the window (recomputed client-side so it respects the window;
  // matches the API's reason_counts semantics: enum key or 'unmapped').
  const reasonCounts = useMemo(() => {
    const m = {};
    for (const r of winRows) { const k = r.reason || 'unmapped'; m[k] = (m[k] || 0) + 1; }
    return m;
  }, [winRows]);

  const topReasons = useMemo(
    () => Object.entries(reasonCounts).sort((a, b) => b[1] - a[1]).slice(0, 3),
    [reasonCounts],
  );

  const nRefused = winRows.length;

  // capital protected — HONEST sum of the est field; rows with UNKNOWN contribute nothing.
  // We also count how many rows HAD an estimate, so the stat can be labelled honestly.
  const { protectedSum, nWithEst } = useMemo(() => {
    let sum = 0, n = 0;
    for (const r of winRows) {
      const v = r.capital_protected_est_usd;
      if (v != null && isFinite(v)) { sum += Number(v); n += 1; }
    }
    return { protectedSum: sum, nWithEst: n };
  }, [winRows]);

  const freshness = deriveFreshness(payload, 3 * 3600_000); // refusals cadence ~ hours

  const verifyCmd = 'python3 verify_spa.py decision_log.jsonl';

  return (
    <div style={{ display: 'grid', gap: 28 }}>
      {/* ── controls: window + reason + engine ─────────────────────────────────── */}
      <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', alignItems: 'center' }}>
        <div style={{ display: 'grid', gap: 5 }}>
          <span style={filterLabel}>{ru ? 'Окно' : 'Window'}</span>
          <TimeToggle value={win} onChange={setWin} lang={lang} size="sm" />
        </div>
        <div style={{ display: 'grid', gap: 5 }}>
          <span style={filterLabel}>{ru ? 'Причина' : 'Reason'}</span>
          <Chips
            options={[['ALL', ru ? 'Все' : 'All'], ...Object.keys(REASON_META).map((k) => [k, (ru ? REASON_META[k].ru : REASON_META[k].en)])]}
            value={reasonFilter} onChange={setReasonFilter}
          />
        </div>
        {engines.length > 1 && (
          <div style={{ display: 'grid', gap: 5 }}>
            <span style={filterLabel}>{ru ? 'Движок' : 'Engine'}</span>
            <Chips
              options={[['ALL', ru ? 'Все' : 'All'], ...engines.map((e) => [e, e])]}
              value={engineFilter} onChange={setEngineFilter}
            />
          </div>
        )}
      </div>

      {/* ── stats (MetricStat cards) ───────────────────────────────────────────── */}
      <div style={{ display: 'grid', gap: 14, gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))' }}>
        <MetricStat
          lang={lang}
          label={{ en: 'Refused', ru: 'Отказано' }}
          value={loading ? null : String(nRefused)}
          sub={{ en: win === 'ALL' ? 'in the ledger' : `in ${win}`, ru: win === 'ALL' ? 'в журнале' : `за ${win}` }}
          tone="danger"
        />
        <MetricStat
          lang={lang}
          label={{ en: 'Capital protected (est)', ru: 'Капитал защищён (оц)' }}
          value={loading ? null : (nWithEst > 0 ? usdCompact(protectedSum) : '—')}
          sub={{
            en: nWithEst > 0 ? `est · ${nWithEst}/${nRefused} rows sized` : 'no sized rows — honest unknown',
            ru: nWithEst > 0 ? `оценка · ${nWithEst}/${nRefused} строк с размером` : 'нет размеров — честный unknown',
          }}
          tone="teal"
        />
        <MetricStat
          lang={lang}
          label={{ en: 'Top reason', ru: 'Топ причина' }}
          value={loading ? null : (topReasons[0] ? (ru ? (REASON_META[topReasons[0][0]] || REASON_META.unmapped).ru : (REASON_META[topReasons[0][0]] || REASON_META.unmapped).en) : '—')}
          sub={topReasons[0] ? { en: `${topReasons[0][1]} of ${nRefused}`, ru: `${topReasons[0][1]} из ${nRefused}` } : undefined}
          size="sm"
        />
        <ReasonBreakdown topReasons={topReasons} total={nRefused} lang={lang} />
      </div>

      {/* honesty framing */}
      <p style={{ fontSize: '.8125rem', lineHeight: 1.6, color: 'var(--text-muted)', margin: 0, maxWidth: '46rem' }}>
        {ru
          ? 'Отказ — это и есть эдж стола. Большая часть доходности 10–15% — компенсация за хвостовой риск, от которой стол ОТКАЗЫВАЕТСЯ, а не mispriced carry. «Защищённый капитал» — честная оценка (est), не заявление.'
          : "Refusal is the desk's edge. Most 10–15% yield is risk-compensation the desk REFUSES, not mispriced carry. “Capital protected” is an honest estimate (est), not a claim."}
      </p>

      {/* ── the ledger (RefusalFeed primitive, wrapped in StaleGuard) ───────────── */}
      <StaleGuard
        payload={payload}
        freshness={payload ? freshness : undefined}
        loading={loading}
        error={error && !payload
          ? (ru ? 'Журнал отказов недоступен — источник офлайн. Значок цепочки остаётся нейтральным (никогда не зелёный при отсутствии). Ничего не выдумано.'
                : 'Refusal ledger unavailable — source offline. The chain badge stays neutral (never green on absent). Nothing fabricated.')
          : false}
        lang={lang}
        label="/api/refusals"
      >
        <RefusalFeed
          rows={feedRows}
          chain={chain ? { verified: chainVerified, head_hash: chain.head_hash, chain_length: chain.chain_length } : { verified: null }}
          verifyCmd={verifyCmd}
          lang={lang}
          max={200}
        />
      </StaleGuard>
    </div>
  );
}

/* ── small local UI (canonical tokens only) ─────────────────────────────────────── */
const filterLabel = {
  fontFamily: MONO, fontSize: '.6rem', textTransform: 'uppercase', letterSpacing: '.08em',
  color: 'var(--text-faint)',
};

function Chips({ options, value, onChange }) {
  return (
    <div style={{
      display: 'inline-flex', gap: 2, padding: 3, borderRadius: 'var(--r-full)',
      background: 'var(--bg-surface-2)', border: '1px solid var(--border)', flexWrap: 'wrap',
    }}>
      {options.map(([key, label]) => {
        const active = key === value;
        return (
          <button
            key={key}
            onClick={() => onChange(key)}
            aria-pressed={active}
            style={{
              fontFamily: MONO, fontSize: '.625rem', fontWeight: active ? 600 : 500,
              padding: '4px 10px', borderRadius: 'var(--r-full)', border: 'none', cursor: 'pointer',
              whiteSpace: 'nowrap',
              background: active ? 'var(--accent-bg)' : 'transparent',
              color: active ? 'var(--accent-hover)' : 'var(--text-muted)',
              transition: 'color 120ms ease, background 120ms ease',
            }}
          >
            {label}
          </button>
        );
      })}
    </div>
  );
}

/* A tiny "top reasons" breakdown as its own card (the stats-rich §4-S5 breakdown). */
function ReasonBreakdown({ topReasons, total, lang }) {
  const ru = lang === 'ru';
  const t = toneStyle('danger');
  return (
    <div style={{
      background: 'var(--bg-surface)', border: '1px solid var(--border)', borderRadius: 'var(--r-lg)',
      padding: '18px 18px 16px', display: 'grid', gap: 10, minWidth: 0,
    }}>
      <p style={{ fontFamily: MONO, fontSize: '.6875rem', textTransform: 'uppercase', letterSpacing: '.08em', color: 'var(--text-muted)', margin: 0 }}>
        {ru ? 'Разбивка причин' : 'Reason breakdown'}
      </p>
      {topReasons.length === 0 ? (
        <span style={{ fontFamily: MONO, fontSize: '.75rem', color: 'var(--text-muted)' }}>
          {ru ? 'нет отказов в окне' : 'no refusals in window'}
        </span>
      ) : (
        <div style={{ display: 'grid', gap: 8 }}>
          {topReasons.map(([key, n]) => {
            const meta = REASON_META[key] || REASON_META.unmapped;
            const pct = total > 0 ? Math.round((n / total) * 100) : 0;
            return (
              <div key={key} style={{ display: 'grid', gap: 3 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'baseline' }}>
                  <span style={{ fontSize: '.75rem', color: 'var(--text-secondary)' }}>{ru ? meta.ru : meta.en}</span>
                  <span style={{ ...TABULAR, fontFamily: MONO, fontSize: '.6875rem', color: 'var(--text-muted)' }}>{n} · {pct}%</span>
                </div>
                <div style={{ height: 5, borderRadius: 'var(--r-full)', background: 'var(--bg-surface-2)', overflow: 'hidden' }}>
                  <div style={{ height: '100%', width: `${pct}%`, background: t.fg, opacity: 0.75, borderRadius: 'var(--r-full)' }} />
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
