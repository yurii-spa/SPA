/*
 * RefusalFeed ⭐ SIGNATURE + DecisionFeed — the public ledgers. This is THE MOAT in UI.
 *
 * RefusalFeed = the public refusal ledger: ts · opportunity · reason · expected-edge ·
 * fee-drag · verdict, each row carrying a `verified` proof badge (hash-chain) with a
 * public / shareable feel. "We publish what we refuse, not just what we trade."
 * DecisionFeed = the full decisions ledger (ENTRY ∥ REFUSAL ∥ ALERT interleaved).
 * They share ONE row renderer (DecisionRow) — RefusalFeed just filters kind===REFUSAL.
 *
 * 5-question map: "what the system DID and what it REFUSED" — the honesty ledger. The
 * refusal half is the differentiator no competitor publishes.
 *
 * FAIL-CLOSED: chain badge is 3-STATE — verified→green / broken→red / absent→NEUTRAL
 * (NEVER green on absent). Empty feed ⇒ explicit "no decisions" not a blank success.
 *
 * Row shape (normalized, matches SPA-001 aggregator + /api/rates-desk/refusals):
 *   { seq?, ts|as_of, desk?, kind:'ENTRY'|'REFUSAL'|'ALERT', subject|underlying,
 *     verdict?, reason|headline, plain_en?, plain_ru?, net_edge?, fee_drag?,
 *     size_usd?|advisory_size_usd?, proof_hash?, entry_hash?, prev_hash?, verified? }
 *
 * Props (both feeds):
 *   rows        — normalized decision rows (array)
 *   chain       — { verified:bool|null, head_hash?, chain_length? } (feed-level proof)
 *   filter      — optional kind filter override ('ALL'|'ENTRY'|'REFUSAL'|'ALERT')
 *   onFilter    — controlled filter setter; if omitted, filters are internal (uncontrolled)
 *   verifyCmd   — the "verify it yourself" command string (shareable)
 *   lang, max
 */
import { useState } from 'react';
import { TABULAR, MONO, toneForVerdict, toneStyle } from '../ui/tokens.js';
import { pick, fmtPct, usdCompact, NA } from './lib.js';

const isNum = (v) => v != null && isFinite(Number(v));

/* Chain badge — the 3-state proof (verified / broken / absent-neutral). */
export function ChainBadge({ chain, lang = 'en' }) {
  const ru = lang === 'ru';
  const v = chain && typeof chain.verified === 'boolean' ? chain.verified : null;
  const map = v === true
    ? { tone: 'ok', en: 'VERIFIED · chain intact', ru: 'ПОДТВЕРЖДЕНО · цепочка цела' }
    : v === false
      ? { tone: 'danger', en: 'NOT VERIFIED · chain broken', ru: 'НЕ ПОДТВЕРЖДЕНО · цепочка нарушена' }
      : { tone: 'muted', en: 'verification unavailable', ru: 'проверка недоступна' };
  const t = toneStyle(map.tone);
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 6, fontFamily: MONO, fontSize: '.6875rem', fontWeight: 600,
      padding: '4px 10px', borderRadius: 'var(--r-md)', background: t.bg, border: `1px solid ${t.border}`, color: t.fg,
    }}>
      <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'currentColor' }} aria-hidden="true" />
      {ru ? map.ru : map.en}
      {chain && chain.chain_length != null && (
        <span style={{ ...TABULAR, color: 'var(--text-faint)', fontWeight: 500 }}>· {chain.chain_length}</span>
      )}
    </span>
  );
}

const KIND = {
  REFUSAL: { verdict: 'REFUSE', en: 'REFUSE', ru: 'ОТКАЗ' },
  ENTRY:   { verdict: 'ENTRY',  en: 'ENTRY',  ru: 'ВХОД' },
  ALERT:   { verdict: 'WATCH',  en: 'ALERT',  ru: 'АЛЕРТ' },
};

/* One decision row with a collapsible proof block (hashes). Shared by both feeds. */
export function DecisionRow({ row, lang = 'en' }) {
  const ru = lang === 'ru';
  const [open, setOpen] = useState(false);
  const kind = String(row.kind || '').toUpperCase();
  const meta = KIND[kind] || KIND.ENTRY;
  const tone = toneForVerdict(row.verdict || meta.verdict);
  const t = toneStyle(tone);

  const subject = row.subject || row.underlying || '?';
  const ts = row.ts || row.as_of || null;
  const reason = pick({ en: row.plain_en || row.reason || row.headline || '', ru: row.plain_ru || row.reason || row.headline || '' }, lang);
  const edge = isNum(row.net_edge) ? (Number(row.net_edge) <= 1 && Number(row.net_edge) >= -1 ? fmtPct(Number(row.net_edge) * 100) : fmtPct(row.net_edge)) : null;
  const fee = isNum(row.fee_drag) ? (Number(row.fee_drag) <= 1 ? fmtPct(Number(row.fee_drag) * 100) : fmtPct(row.fee_drag)) : null;
  const size = row.size_usd ?? row.advisory_size_usd;
  const hashes = [['entry_hash', row.entry_hash], ['prev_hash', row.prev_hash], ['proof_hash', row.proof_hash]].filter(([, v]) => v);
  const verified = typeof row.verified === 'boolean' ? row.verified : null;

  return (
    <div style={{
      padding: '12px 14px', borderRadius: 'var(--r-md)', background: 'var(--bg-surface)',
      borderLeft: `3px solid ${t.fg}`, border: `1px solid ${t.border}`, borderLeftWidth: 3,
    }}>
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap', minWidth: 0 }}>
          <span style={{
            display: 'inline-flex', alignItems: 'center', gap: 5, fontFamily: MONO, fontSize: '.625rem', fontWeight: 600,
            padding: '2px 8px', borderRadius: 'var(--r-sm)', background: t.bg, border: `1px solid ${t.border}`, color: t.fg,
          }}>
            <span style={{ width: 5, height: 5, borderRadius: '50%', background: 'currentColor' }} aria-hidden="true" />
            {ru ? meta.ru : meta.en}
          </span>
          <span style={{ fontFamily: MONO, fontSize: '.8125rem', fontWeight: 600, color: 'var(--text-primary)' }}>{subject}</span>
          {row.desk && <span style={{ fontFamily: MONO, fontSize: '.625rem', color: 'var(--text-faint)' }}>{row.desk}</span>}
          {ts && <span style={{ ...TABULAR, fontFamily: MONO, fontSize: '.625rem', color: 'var(--text-faint)' }}>{ts}</span>}
        </div>
        {row.seq != null && <span style={{ ...TABULAR, fontFamily: MONO, fontSize: '.625rem', color: 'var(--text-faint)' }}>#{row.seq}</span>}
      </div>

      {reason && <p style={{ fontSize: '.8125rem', color: 'var(--text-secondary)', lineHeight: 1.5, margin: '8px 0 6px' }}>{reason}</p>}

      <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap' }}>
        {edge != null && <Stat k={ru ? 'ожид. edge' : 'exp. edge'} v={edge} />}
        {fee != null && <Stat k={ru ? 'fee-drag' : 'fee drag'} v={fee} />}
        <Stat k={ru ? 'размер' : 'size'} v={size != null ? usdCompact(size) : NA} />
      </div>

      {hashes.length > 0 && (
        <>
          <button onClick={() => setOpen((o) => !o)} style={{
            marginTop: 8, background: 'none', border: 'none', cursor: 'pointer', padding: 0,
            fontFamily: MONO, fontSize: '.625rem', color: 'var(--accent-hover)', display: 'inline-flex', alignItems: 'center', gap: 5,
          }}>
            <span aria-hidden="true" style={{ display: 'inline-block', transform: open ? 'rotate(90deg)' : 'none', transition: 'transform 120ms' }}>▸</span>
            {ru ? 'доказательство' : 'proof'}
            {verified === true && <span style={{ color: 'var(--ok)' }}>✓ {ru ? 'проверено' : 'verified'}</span>}
          </button>
          {open && (
            <div style={{ marginTop: 8, padding: '10px 12px', borderRadius: 'var(--r-sm)', background: 'var(--bg-base)', border: '1px solid var(--border)', display: 'grid', gap: 5 }}>
              {hashes.map(([k, v]) => (
                <div key={k} style={{ display: 'flex', gap: 8, alignItems: 'baseline', flexWrap: 'wrap' }}>
                  <span style={{ fontFamily: MONO, fontSize: '.625rem', color: 'var(--text-muted)', flexShrink: 0 }}>{k}</span>
                  <span style={{ fontFamily: MONO, fontSize: '.625rem', color: 'var(--data-teal)', wordBreak: 'break-all' }}>{v}</span>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}

function Stat({ k, v }) {
  return (
    <span style={{ display: 'inline-flex', alignItems: 'baseline', gap: 5 }}>
      <span style={{ fontFamily: MONO, fontSize: '.6rem', textTransform: 'uppercase', letterSpacing: '.05em', color: 'var(--text-faint)' }}>{k}</span>
      <span style={{ ...TABULAR, fontFamily: MONO, fontSize: '.75rem', color: 'var(--text-secondary)' }}>{v}</span>
    </span>
  );
}

/* Shared feed shell (filters + chain badge + rows + verify CTA). */
function Feed({ rows, chain, filter, onFilter, verifyCmd, lang, max = 60, refusalOnly = false, title }) {
  const ru = lang === 'ru';
  const [localFilter, setLocalFilter] = useState('ALL');
  const active = filter ?? localFilter;
  const setFilter = onFilter ?? setLocalFilter;

  const all = Array.isArray(rows) ? rows : [];
  const base = refusalOnly ? all.filter((r) => String(r.kind).toUpperCase() === 'REFUSAL') : all;
  const shown = (active === 'ALL' ? base : base.filter((r) => String(r.kind).toUpperCase() === active)).slice(0, max);
  const counts = base.reduce((a, r) => { const k = String(r.kind).toUpperCase(); a[k] = (a[k] || 0) + 1; return a; }, {});

  const FILTERS = refusalOnly ? ['ALL'] : ['ALL', 'REFUSAL', 'ENTRY', 'ALERT'];

  return (
    <div style={{ display: 'grid', gap: 12 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10, flexWrap: 'wrap' }}>
        <ChainBadge chain={chain} lang={lang} />
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
          <span style={{ ...TABULAR, fontFamily: MONO, fontSize: '.6875rem', color: 'var(--danger)' }}>{counts.REFUSAL || 0} {ru ? 'отказов' : 'refused'}</span>
          {!refusalOnly && <span style={{ ...TABULAR, fontFamily: MONO, fontSize: '.6875rem', color: 'var(--ok)' }}>{counts.ENTRY || 0} {ru ? 'входов' : 'entered'}</span>}
        </div>
      </div>

      {!refusalOnly && FILTERS.length > 1 && (
        <div style={{ display: 'inline-flex', gap: 2, padding: 3, borderRadius: 'var(--r-full)', background: 'var(--bg-surface-2)', border: '1px solid var(--border)', width: 'fit-content' }}>
          {FILTERS.map((f) => (
            <button key={f} onClick={() => setFilter(f)} style={{
              fontFamily: MONO, fontSize: '.625rem', fontWeight: f === active ? 600 : 500, padding: '4px 10px',
              borderRadius: 'var(--r-full)', border: 'none', cursor: 'pointer',
              background: f === active ? 'var(--accent-bg)' : 'transparent', color: f === active ? 'var(--accent-hover)' : 'var(--text-muted)',
            }}>{f}</button>
          ))}
        </div>
      )}

      <div style={{ display: 'grid', gap: 8 }}>
        {shown.length === 0 ? (
          <div style={{ padding: '14px 16px', borderRadius: 'var(--r-md)', background: 'var(--bg-surface-2)', border: '1px solid var(--border-strong)' }}>
            <span style={{ fontFamily: MONO, fontSize: '.75rem', color: 'var(--text-muted)' }}>
              {ru ? 'Решений ещё не записано (или фид офлайн). Ничего не показано вместо выдуманного.' : 'No decisions recorded yet (or feed offline). Nothing shown, rather than fabricated.'}
            </span>
          </div>
        ) : shown.map((r, i) => <DecisionRow key={r.seq ?? r.entry_hash ?? i} row={r} lang={lang} />)}
      </div>

      {verifyCmd && (
        <div style={{ padding: '10px 12px', borderRadius: 'var(--r-sm)', background: 'var(--bg-base)', border: '1px solid var(--accent-border)' }}>
          <p style={{ fontFamily: MONO, fontSize: '.6rem', textTransform: 'uppercase', letterSpacing: '.06em', color: 'var(--text-faint)', margin: '0 0 4px' }}>
            {ru ? 'Проверьте сами' : 'Verify it yourself'}
          </p>
          <code style={{ fontFamily: MONO, fontSize: '.75rem', color: 'var(--data-teal)', wordBreak: 'break-all' }}>{verifyCmd}</code>
        </div>
      )}
    </div>
  );
}

export default function RefusalFeed(props) { return <Feed {...props} refusalOnly />; }
export function DecisionFeed(props) { return <Feed {...props} refusalOnly={false} />; }
