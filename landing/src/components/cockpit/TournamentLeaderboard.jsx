/*
 * TournamentLeaderboard ⚙ — rank · strategy · risk-adjusted metric · capital · trend · status.
 * Status ∈ champion / challenger / killed. (From /api/tournament leaderboard.)
 *
 * 5-question map: "what the system DID" — which strategies won/lost the deterministic
 * tournament, honestly flagged (a degenerate Sharpe on near-zero stablecoin vol is marked
 * n/a, not shown as a trophy number).
 *
 * FAIL-CLOSED: empty ⇒ explicit unavailable. A null metric renders "n/a", never a
 * fabricated Sharpe. A `killed` row is unmistakably kill-toned.
 *
 * Row shape:
 *   { rank, id|name, metric:number|null, metric_label?, capital_usd?, trend?:number[]|number,
 *     status:'CHAMPION'|'CHALLENGER'|'KILLED'|str, kill_reason? }
 *
 * Props:
 *   rows, metricLabel (default 'Net return'), lang, max
 */
import { TABULAR, MONO, toneStyle } from '../ui/tokens.js';
import { pick, fmtSigned, usdCompact, NA } from './lib.js';

const isNum = (v) => v != null && isFinite(Number(v));

const STATUS = {
  CHAMPION:   { tone: 'ok',     en: 'champion',   ru: 'чемпион' },
  CHALLENGER: { tone: 'accent', en: 'challenger', ru: 'претендент' },
  KILLED:     { tone: 'danger', en: 'killed',     ru: 'убит' },
  PAPER:      { tone: 'warn',   en: 'paper',      ru: 'бумага' },
  LIVE:       { tone: 'ok',     en: 'live',       ru: 'live' },
};

function TrendCell({ trend }) {
  if (Array.isArray(trend) && trend.length >= 2) {
    const w = 44, h = 14;
    const min = Math.min(...trend), max = Math.max(...trend), span = max - min || 1;
    const pts = trend.map((v, i) => `${(i / (trend.length - 1)) * w},${h - ((v - min) / span) * h}`).join(' ');
    const up = trend[trend.length - 1] >= trend[0];
    return <svg width={w} height={h} aria-hidden="true"><polyline points={pts} fill="none" stroke={up ? 'var(--ok)' : 'var(--danger)'} strokeWidth="1.25" /></svg>;
  }
  if (isNum(trend)) {
    const up = Number(trend) >= 0;
    return <span style={{ color: up ? 'var(--ok)' : 'var(--danger)', fontSize: '.75rem' }}>{up ? '▲' : '▼'}</span>;
  }
  return <span style={{ color: 'var(--text-faint)' }}>{NA}</span>;
}

export default function TournamentLeaderboard({ rows, metricLabel = 'Net return', lang = 'en', max = 20 }) {
  const ru = lang === 'ru';
  const list = (Array.isArray(rows) ? rows : []).slice(0, max);

  if (!list.length) {
    return (
      <div style={{ padding: '14px 16px', borderRadius: 'var(--r-md)', background: 'var(--bg-surface-2)', border: '1px solid var(--border-strong)' }}>
        <span style={{ fontFamily: MONO, fontSize: '.75rem', color: 'var(--text-muted)' }}>
          {ru ? 'Лидерборд недоступен — /api/tournament офлайн (без выдуманного ранкинга).' : 'Leaderboard unavailable — /api/tournament offline (no fabricated ranking).'}
        </span>
      </div>
    );
  }

  const th = { fontFamily: MONO, fontSize: '.6rem', textTransform: 'uppercase', letterSpacing: '.06em', color: 'var(--text-faint)', textAlign: 'left', padding: '8px 12px', fontWeight: 500, whiteSpace: 'nowrap' };
  const thR = { ...th, textAlign: 'right' };
  const td = { fontFamily: MONO, fontSize: '.75rem', color: 'var(--text-secondary)', padding: '10px 12px', borderTop: '1px solid var(--border)' };
  const tdR = { ...td, ...TABULAR, textAlign: 'right' };

  return (
    <div style={{ overflowX: 'auto', borderRadius: 'var(--r-lg)', border: '1px solid var(--border)', background: 'var(--bg-surface)' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead>
          <tr>
            <th style={thR}>#</th>
            <th style={th}>{ru ? 'Стратегия' : 'Strategy'}</th>
            <th style={thR}>{pick(metricLabel, lang)}</th>
            <th style={thR}>{ru ? 'Капитал' : 'Capital'}</th>
            <th style={thR}>{ru ? 'Тренд' : 'Trend'}</th>
            <th style={th}>{ru ? 'Статус' : 'Status'}</th>
          </tr>
        </thead>
        <tbody>
          {list.map((r, i) => {
            const st = STATUS[String(r.status || '').toUpperCase()] || { tone: 'muted', en: r.status || '?', ru: r.status || '?' };
            const t = toneStyle(st.tone);
            const killed = String(r.status || '').toUpperCase() === 'KILLED';
            const metric = isNum(r.metric) ? fmtSigned(r.metric, 2) : (ru ? 'н/д' : 'n/a');
            return (
              <tr key={r.id || r.name || i} style={killed ? { opacity: 0.75 } : undefined}>
                <td style={{ ...tdR, color: 'var(--text-muted)' }}>{isNum(r.rank) ? r.rank : i + 1}</td>
                <td style={{ ...td, color: 'var(--text-primary)', fontWeight: 600, textDecoration: killed ? 'line-through' : 'none' }}>{r.name || r.id || NA}</td>
                <td style={{ ...tdR, color: isNum(r.metric) ? (Number(r.metric) >= 0 ? 'var(--ok)' : 'var(--danger)') : 'var(--text-muted)', fontWeight: 600 }}>{metric}</td>
                <td style={tdR}>{isNum(r.capital_usd) ? usdCompact(r.capital_usd) : NA}</td>
                <td style={tdR}><TrendCell trend={r.trend} /></td>
                <td style={td}>
                  <span title={r.kill_reason || undefined} style={{
                    display: 'inline-flex', alignItems: 'center', gap: 5, fontFamily: MONO, fontSize: '.625rem', fontWeight: 600,
                    padding: '2px 8px', borderRadius: 'var(--r-sm)', background: t.bg, border: `1px solid ${t.border}`, color: t.fg,
                  }}>
                    <span style={{ width: 5, height: 5, borderRadius: '50%', background: 'currentColor' }} aria-hidden="true" />
                    {ru ? st.ru : st.en}
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
