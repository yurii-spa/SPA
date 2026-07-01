/*
 * LiqNavTierChart ⚙ — Liquidation-NAV by ticket size (the exit-nav ticket ladder).
 * A descending bar chart of net proceeds per exit size, with the haircut climbing as size
 * grows — the honest "what you actually realize on exit" surface. Depth-limited / flagged
 * tiers are marked, never hidden. (From /api/rates-desk/exit-nav::schedule.)
 *
 * 5-question map: "how much RISK" — liquidity risk made concrete: bigger ticket ⇒ bigger
 * haircut ⇒ less net. Conservative lower bound, honestly labeled.
 *
 * FAIL-CLOSED: empty ⇒ explicit unavailable. A `flagged` / depth-limited tier is amber; a
 * tier with no net_proceeds renders a hole, not a fabricated fill.
 *
 * Row shape (per ticket size):
 *   { size_usd, net_proceeds_usd, haircut_pct, price_impact_frac?, time_to_exit_days?, flagged? }
 *
 * Props:
 *   schedule — ticket-ladder rows (array)
 *   lang, reducedMotion
 */
import { TABULAR, MONO } from '../ui/tokens.js';
import { usdCompact, fmtPct, NA } from './lib.js';

const isNum = (v) => v != null && isFinite(Number(v));

export default function LiqNavTierChart({ schedule, lang = 'en', reducedMotion = false }) {
  const ru = lang === 'ru';
  const rows = (Array.isArray(schedule) ? schedule : []).filter((r) => isNum(r.size_usd));

  if (!rows.length) {
    return (
      <div style={{ padding: '16px', borderRadius: 'var(--r-md)', background: 'var(--bg-surface-2)', border: '1px solid var(--border-strong)' }}>
        <span style={{ fontFamily: MONO, fontSize: '.75rem', color: 'var(--text-muted)' }}>
          {ru ? 'Exit-NAV недоступен — расписание пусто (заливки не выдуманы).' : 'Exit-NAV unavailable — schedule empty (no fills fabricated).'}
        </span>
      </div>
    );
  }

  const maxNet = Math.max(...rows.map((r) => (isNum(r.net_proceeds_usd) ? Number(r.net_proceeds_usd) : 0)), 1);

  return (
    <div style={{ display: 'grid', gap: 10, padding: '14px 16px', borderRadius: 'var(--r-lg)', background: 'var(--bg-surface)', border: '1px solid var(--border)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <span style={{ fontFamily: MONO, fontSize: '.6875rem', textTransform: 'uppercase', letterSpacing: '.07em', color: 'var(--text-muted)' }}>
          {ru ? 'Exit-NAV по размеру тикета' : 'Exit-NAV by ticket size'}
        </span>
        <span style={{ fontFamily: MONO, fontSize: '.6rem', color: 'var(--text-faint)' }}>
          {ru ? 'консервативная нижняя граница · не реализованные выходы' : 'conservative lower bound · not realized exits'}
        </span>
      </div>
      <div style={{ display: 'grid', gap: 8 }}>
        {rows.map((r, i) => {
          const net = isNum(r.net_proceeds_usd) ? Number(r.net_proceeds_usd) : null;
          const w = net == null ? 0 : Math.max(2, (net / maxNet) * 100);
          const flagged = r.flagged === true || (isNum(r.haircut_pct) && Number(r.haircut_pct) >= 5);
          const barColor = net == null ? 'var(--border-strong)' : flagged ? 'var(--warn)' : 'var(--data-teal)';
          return (
            <div key={r.size_usd || i} style={{ display: 'grid', gridTemplateColumns: '70px 1fr auto', gap: 10, alignItems: 'center' }}>
              <span style={{ ...TABULAR, fontFamily: MONO, fontSize: '.6875rem', color: 'var(--text-secondary)', textAlign: 'right' }}>{usdCompact(r.size_usd)}</span>
              <div style={{ height: 18, borderRadius: 'var(--r-sm)', background: 'var(--bg-surface-2)', overflow: 'hidden', position: 'relative' }}>
                {net == null ? (
                  <span style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', paddingLeft: 8, fontFamily: MONO, fontSize: '.6rem', color: 'var(--text-faint)' }}>
                    {ru ? 'дыра — глубина не покрывает' : 'hole — depth does not cover'}
                  </span>
                ) : (
                  <div style={{ height: '100%', width: `${w}%`, background: barColor, opacity: 0.85, borderRadius: 'var(--r-sm)', transition: reducedMotion ? undefined : 'width 400ms cubic-bezier(.4,0,.2,1)' }} />
                )}
              </div>
              <div style={{ display: 'flex', gap: 10, alignItems: 'baseline', whiteSpace: 'nowrap' }}>
                <span style={{ ...TABULAR, fontFamily: MONO, fontSize: '.75rem', fontWeight: 600, color: net == null ? 'var(--text-muted)' : 'var(--text-primary)' }}>{net == null ? NA : usdCompact(net)}</span>
                <span style={{ ...TABULAR, fontFamily: MONO, fontSize: '.625rem', color: flagged ? 'var(--warn)' : 'var(--text-faint)' }}>
                  −{isNum(r.haircut_pct) ? fmtPct(r.haircut_pct, 2) : NA}
                </span>
                {isNum(r.time_to_exit_days) && (
                  <span style={{ ...TABULAR, fontFamily: MONO, fontSize: '.6rem', color: 'var(--text-faint)' }}>{Number(r.time_to_exit_days).toFixed(0)}{ru ? 'д' : 'd'}</span>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
