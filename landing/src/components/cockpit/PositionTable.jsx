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

const isNum = (v) => v != null && isFinite(Number(v));

const LEG = {
  SPOT_LONG:  { tone: 'ok',     en: 'spot long',  ru: 'спот long' },
  PERP_SHORT: { tone: 'accent', en: 'perp short', ru: 'перп short' },
  LEND:       { tone: 'teal',   en: 'lend',       ru: 'кредит' },
};

export default function PositionTable({ rows, idle, lang = 'en' }) {
  const ru = lang === 'ru';

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
