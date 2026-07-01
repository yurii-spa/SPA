/*
 * PositionTable ⚙ — the paper book legs: spot long / perp short, venue, notional,
 * funding accrued, net carry APY. Honestly labeled a PAPER book (no on-chain fills).
 * (From /api/positions + current_positions.json.)
 *
 * 5-question map: "where's the MONEY" — the position-level breakdown of the book.
 *
 * FAIL-CLOSED: empty ⇒ explicit idle-POSITIVE state ("capital parked", teal) when the
 * book is intentionally flat, or "unavailable" when the source is offline. Null cells → "—".
 *
 * Row shape:
 *   { id, leg:'SPOT_LONG'|'PERP_SHORT'|str, asset, venue, notional_usd,
 *     funding_accrued_usd?, net_carry_apy_pct?, side? }
 *
 * Props:
 *   rows    — position rows (array | null=offline | []=idle-positive)
 *   idle    — force the idle-positive empty state (default: [] renders idle-positive)
 *   lang
 */
import { TABULAR, MONO, toneColor } from '../ui/tokens.js';
import { pick, fmtUsd0, fmtPct, usdCompact, fmtSigned, NA } from './lib.js';
import { useIsNarrow } from './hooks.js';

const isNum = (v) => v != null && isFinite(Number(v));

const LEG = {
  SPOT_LONG:  { tone: 'ok',     en: 'spot long',  ru: 'спот long' },
  PERP_SHORT: { tone: 'accent', en: 'perp short', ru: 'перп short' },
  LEND:       { tone: 'teal',   en: 'lend',       ru: 'кредит' },
};

export default function PositionTable({ rows, idle, lang = 'en' }) {
  const ru = lang === 'ru';
  const narrow = useIsNarrow(720);

  if (rows == null) {
    return <Empty msg={ru ? 'Позиции недоступны — /api/positions офлайн.' : 'Positions unavailable — /api/positions offline.'} />;
  }
  const list = Array.isArray(rows) ? rows : [];
  if (list.length === 0 || idle) {
    // idle = POSITIVE: capital parked is a working state, not an error.
    return (
      <div style={{ padding: '18px', borderRadius: 'var(--r-md)', background: 'var(--bg-surface)', border: '1px solid var(--teal-border)', textAlign: 'center' }}>
        <p style={{ fontFamily: MONO, fontSize: '.8125rem', fontWeight: 600, color: 'var(--data-teal)', margin: '0 0 4px' }}>
          {ru ? 'Книга плоская — капитал припаркован ✓' : 'Book flat — capital parked ✓'}
        </p>
        <p style={{ fontSize: '.75rem', color: 'var(--text-muted)', margin: 0 }}>
          {ru ? 'Отсутствие позиций — рабочее состояние (нет риска, который не стоит принимать), а не ошибка.' : 'No positions is a working state (no risk not worth taking), not an error.'}
        </p>
      </div>
    );
  }

  // SPA-504 mobile reflow: below 720px the 6-col table becomes stacked cards — one row per
  // position, label/value pairs — so a phone never has to scroll the book sideways.
  if (narrow) {
    return (
      <div style={{ display: 'grid', gap: 10 }}>
        <span style={{ display: 'inline-flex', alignSelf: 'flex-start', alignItems: 'center', gap: 5, fontFamily: MONO, fontSize: '.625rem', fontWeight: 600, padding: '2px 8px', borderRadius: 'var(--r-sm)', background: 'var(--muted-bg)', border: '1px solid var(--muted-border)', color: 'var(--text-muted)' }}>
          {ru ? 'PAPER · нет on-chain fills' : 'PAPER · no on-chain fills'}
        </span>
        {list.map((r, i) => {
          const leg = LEG[String(r.leg || '').toUpperCase()] || { tone: 'muted', en: r.leg || '?', ru: r.leg || '?' };
          const carry = isNum(r.net_carry_apy_pct) ? Number(r.net_carry_apy_pct) : null;
          const rowStyle = { display: 'flex', justifyContent: 'space-between', gap: 12, padding: '5px 0' };
          const kStyle = { fontFamily: MONO, fontSize: '.625rem', textTransform: 'uppercase', letterSpacing: '.06em', color: 'var(--text-faint)' };
          const vStyle = { fontFamily: MONO, fontSize: '.75rem', color: 'var(--text-secondary)', ...TABULAR, textAlign: 'right' };
          return (
            <div key={r.id || i} style={{ borderRadius: 'var(--r-md)', border: '1px solid var(--border)', background: 'var(--bg-surface)', padding: '12px 14px' }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10, marginBottom: 8 }}>
                <span style={{ fontFamily: MONO, fontSize: '.8125rem', fontWeight: 700, color: 'var(--text-primary)' }}>{r.asset || NA}</span>
                <span style={{ fontSize: '.625rem', padding: '2px 7px', borderRadius: 'var(--r-sm)', border: `1px solid ${toneColor(leg.tone)}`, color: toneColor(leg.tone) }}>{ru ? leg.ru : leg.en}</span>
              </div>
              <div style={rowStyle}><span style={kStyle}>{ru ? 'Площадка' : 'Venue'}</span><span style={vStyle}>{r.venue || NA}</span></div>
              <div style={rowStyle}><span style={kStyle}>{ru ? 'Notional' : 'Notional'}</span><span style={vStyle}>{isNum(r.notional_usd) ? usdCompact(r.notional_usd) : NA}</span></div>
              <div style={rowStyle}><span style={kStyle}>{ru ? 'Funding накоп.' : 'Funding accr.'}</span><span style={vStyle}>{isNum(r.funding_accrued_usd) ? fmtUsd0(r.funding_accrued_usd) : NA}</span></div>
              <div style={rowStyle}><span style={kStyle}>{ru ? 'Net carry APY' : 'Net carry APY'}</span><span style={{ ...vStyle, color: carry == null ? 'var(--text-muted)' : carry >= 0 ? 'var(--ok)' : 'var(--danger)', fontWeight: 600 }}>{carry == null ? NA : fmtSigned(carry, 2)}</span></div>
            </div>
          );
        })}
      </div>
    );
  }

  const th = { fontFamily: MONO, fontSize: '.6rem', textTransform: 'uppercase', letterSpacing: '.06em', color: 'var(--text-faint)', textAlign: 'left', padding: '8px 12px', fontWeight: 500, whiteSpace: 'nowrap' };
  const thR = { ...th, textAlign: 'right' };
  const td = { fontFamily: MONO, fontSize: '.75rem', color: 'var(--text-secondary)', padding: '10px 12px', borderTop: '1px solid var(--border)' };
  const tdR = { ...td, ...TABULAR, textAlign: 'right' };

  return (
    <div style={{ overflowX: 'auto', borderRadius: 'var(--r-lg)', border: '1px solid var(--border)', background: 'var(--bg-surface)' }}>
      <div style={{ padding: '8px 12px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontFamily: MONO, fontSize: '.625rem', fontWeight: 600, padding: '2px 8px', borderRadius: 'var(--r-sm)', background: 'var(--muted-bg)', border: '1px solid var(--muted-border)', color: 'var(--text-muted)' }}>
          {ru ? 'PAPER · нет on-chain fills' : 'PAPER · no on-chain fills'}
        </span>
      </div>
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead>
          <tr>
            <th style={th}>{ru ? 'Актив' : 'Asset'}</th>
            <th style={th}>{ru ? 'Нога' : 'Leg'}</th>
            <th style={th}>{ru ? 'Площадка' : 'Venue'}</th>
            <th style={thR}>{ru ? 'Notional' : 'Notional'}</th>
            <th style={thR}>{ru ? 'Funding накоп.' : 'Funding accr.'}</th>
            <th style={thR}>{ru ? 'Net carry APY' : 'Net carry APY'}</th>
          </tr>
        </thead>
        <tbody>
          {list.map((r, i) => {
            const leg = LEG[String(r.leg || '').toUpperCase()] || { tone: 'muted', en: r.leg || '?', ru: r.leg || '?' };
            const carry = isNum(r.net_carry_apy_pct) ? Number(r.net_carry_apy_pct) : null;
            return (
              <tr key={r.id || i}>
                <td style={{ ...td, color: 'var(--text-primary)', fontWeight: 600 }}>{r.asset || NA}</td>
                <td style={td}>
                  <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: '.625rem', padding: '2px 7px', borderRadius: 'var(--r-sm)', background: 'transparent', border: `1px solid ${toneColor(leg.tone)}`, color: toneColor(leg.tone) }}>
                    {ru ? leg.ru : leg.en}
                  </span>
                </td>
                <td style={td}>{r.venue || NA}</td>
                <td style={tdR}>{isNum(r.notional_usd) ? usdCompact(r.notional_usd) : NA}</td>
                <td style={tdR}>{isNum(r.funding_accrued_usd) ? fmtUsd0(r.funding_accrued_usd) : NA}</td>
                <td style={{ ...tdR, color: carry == null ? 'var(--text-muted)' : carry >= 0 ? 'var(--ok)' : 'var(--danger)', fontWeight: 600 }}>
                  {carry == null ? NA : fmtSigned(carry, 2)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function Empty({ msg }) {
  return (
    <div style={{ padding: '14px 16px', borderRadius: 'var(--r-md)', background: 'var(--bg-surface-2)', border: '1px solid var(--border-strong)' }}>
      <span style={{ fontFamily: MONO, fontSize: '.75rem', color: 'var(--text-muted)' }}>{msg}</span>
    </div>
  );
}
