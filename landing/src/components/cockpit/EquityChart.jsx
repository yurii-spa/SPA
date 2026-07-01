/*
 * EquityChart ⚙ — net-of-fees equity curve + drawdown shading + gate/refusal markers.
 * Hand-rolled inline SVG (no charting dep — matches the existing Ring/Bar approach).
 *
 * CRITICAL HONESTY (the load-bearing rule): EVIDENCED bars render DISTINCTLY from
 * warmup / backfill / reconstructed bars. The equity_curve_daily `evidenced` flag drives
 * a solid line on evidenced spans and a DASHED, dimmed line on non-evidenced spans — a
 * backfill peak must NEVER look like a real evidenced day. (The N1 kill-switch lesson,
 * applied to the UI.)
 *
 * 5-question map: "what HAPPENED" — the track itself, with its honesty caveats baked in.
 *
 * FAIL-CLOSED: <2 points ⇒ explicit "insufficient history" (never a fabricated line).
 *
 * Props:
 *   series   — [{ date, value(close_equity), evidenced:bool, drawdown_pct? }]
 *   markers  — optional [{ date, kind:'gate'|'refusal'|'kill', label? }] vertical marks
 *   showDrawdown — shade the underwater region (default true)
 *   height, lang, reducedMotion
 */
import { TABULAR, MONO, toneColor } from '../ui/tokens.js';
import { fmtUsd0, fmtPct, NA } from './lib.js';

const isNum = (v) => v != null && isFinite(Number(v));

export default function EquityChart({
  series, markers, showDrawdown = true, height = 220, lang = 'en', reducedMotion = false,
}) {
  const ru = lang === 'ru';
  const pts = (Array.isArray(series) ? series : []).filter((d) => isNum(d.value));

  if (pts.length < 2) {
    return (
      <div style={{ padding: '18px', borderRadius: 'var(--r-md)', background: 'var(--bg-surface-2)', border: '1px solid var(--border-strong)', textAlign: 'center' }}>
        <span style={{ fontFamily: MONO, fontSize: '.75rem', color: 'var(--text-muted)' }}>
          {ru ? 'Недостаточно истории для кривой (нужно ≥2 точки). Линия не выдумывается.' : 'Insufficient history for a curve (need ≥2 points). No line is fabricated.'}
        </span>
      </div>
    );
  }

  const W = 640, H = height, padL = 8, padR = 8, padT = 12, padB = 22;
  const plotW = W - padL - padR, plotH = H - padT - padB;
  const vals = pts.map((d) => Number(d.value));
  const lo = Math.min(...vals), hi = Math.max(...vals);
  const span = hi - lo || 1;
  const x = (i) => padL + (i / (pts.length - 1)) * plotW;
  const y = (v) => padT + (1 - (v - lo) / span) * plotH;

  // Split into evidenced / non-evidenced runs so we can draw solid vs dashed segments.
  const segs = [];
  let cur = null;
  pts.forEach((d, i) => {
    const ev = d.evidenced !== false; // default-true unless explicitly false
    if (!cur || cur.ev !== ev) { cur = { ev, idx: [i] }; segs.push(cur); }
    else cur.idx.push(i);
    // bridge: include the boundary point in both runs so the line is continuous
    if (cur.idx.length && i > 0 && segs.length > 1 && cur.idx[0] === i) {
      cur.idx.unshift(i - 1);
    }
  });

  const line = (idxs) => idxs.map((i, k) => `${k === 0 ? 'M' : 'L'} ${x(i).toFixed(1)} ${y(vals[i]).toFixed(1)}`).join(' ');

  // drawdown shading: underwater = below running peak
  let ddArea = '';
  if (showDrawdown) {
    let peak = -Infinity;
    const top = [], bot = [];
    pts.forEach((d, i) => {
      peak = Math.max(peak, vals[i]);
      top.push(`${i === 0 ? 'M' : 'L'} ${x(i).toFixed(1)} ${y(peak).toFixed(1)}`);
      bot.push(`L ${x(i).toFixed(1)} ${y(vals[i]).toFixed(1)}`);
    });
    ddArea = top.join(' ') + ' ' + bot.reverse().join(' ') + ' Z';
  }

  const hasBackfill = pts.some((d) => d.evidenced === false);
  const last = pts[pts.length - 1];
  const first = pts[0];
  const totalRet = ((Number(last.value) - Number(first.value)) / Number(first.value)) * 100;

  return (
    <div style={{ display: 'grid', gap: 8 }}>
      {/* legend — the honesty legend */}
      <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', alignItems: 'center' }}>
        <LegendItem swatch={<span style={{ width: 18, height: 2, background: 'var(--data-teal)', display: 'inline-block' }} />} label={ru ? 'evidenced (реальный трек)' : 'evidenced (real track)'} />
        {hasBackfill && <LegendItem swatch={<span style={{ width: 18, height: 0, borderTop: '2px dashed var(--text-muted)', display: 'inline-block' }} />} label={ru ? 'backfill / warmup (не трек)' : 'backfill / warmup (not track)'} />}
        {showDrawdown && <LegendItem swatch={<span style={{ width: 12, height: 8, background: 'var(--danger-bg)', border: '1px solid var(--danger-border)', display: 'inline-block' }} />} label={ru ? 'просадка' : 'drawdown'} />}
      </div>

      <svg width="100%" height={H} viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img" aria-label={ru ? 'Кривая капитала' : 'Equity curve'}>
        {showDrawdown && ddArea && <path d={ddArea} fill="var(--danger-bg)" opacity="0.5" />}
        {/* markers */}
        {Array.isArray(markers) && markers.map((m, k) => {
          const idx = pts.findIndex((d) => d.date === m.date);
          if (idx < 0) return null;
          const mx = x(idx);
          const tone = m.kind === 'kill' ? 'danger' : m.kind === 'refusal' ? 'warn' : 'accent';
          const col = toneColor(tone);
          return <line key={k} x1={mx} y1={padT} x2={mx} y2={H - padB} stroke={col} strokeWidth="1" strokeDasharray="2 3" opacity="0.7" />;
        })}
        {/* evidenced vs backfill line segments */}
        {segs.map((s, k) => (
          <path key={k} d={line(s.idx)} fill="none"
                stroke={s.ev ? 'var(--data-teal)' : 'var(--text-muted)'}
                strokeWidth={s.ev ? 2 : 1.5}
                strokeDasharray={s.ev ? 'none' : '4 3'}
                opacity={s.ev ? 1 : 0.6}
                strokeLinejoin="round" strokeLinecap="round"
                style={reducedMotion ? undefined : { transition: 'opacity 200ms ease' }} />
        ))}
        {/* last point dot */}
        <circle cx={x(pts.length - 1)} cy={y(vals[vals.length - 1])} r="3" fill={last.evidenced === false ? 'var(--text-muted)' : 'var(--data-teal)'} />
      </svg>

      <div style={{ display: 'flex', gap: 18, flexWrap: 'wrap' }}>
        <Foot k={ru ? 'последний' : 'latest'} v={fmtUsd0(last.value)} />
        <Foot k={ru ? 'доходность' : 'return'} v={isNum(totalRet) ? (totalRet >= 0 ? '+' : '') + totalRet.toFixed(2) + '%' : NA} tone={totalRet >= 0 ? 'ok' : 'danger'} />
        <Foot k={ru ? 'точек' : 'points'} v={`${pts.length}${hasBackfill ? ` (${pts.filter((d) => d.evidenced !== false).length} ev)` : ''}`} />
      </div>
    </div>
  );
}

function LegendItem({ swatch, label }) {
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
      {swatch}
      <span style={{ fontFamily: MONO, fontSize: '.625rem', color: 'var(--text-muted)' }}>{label}</span>
    </span>
  );
}
function Foot({ k, v, tone }) {
  return (
    <span style={{ display: 'inline-flex', alignItems: 'baseline', gap: 5 }}>
      <span style={{ fontFamily: MONO, fontSize: '.6rem', textTransform: 'uppercase', letterSpacing: '.05em', color: 'var(--text-faint)' }}>{k}</span>
      <span style={{ ...TABULAR, fontFamily: MONO, fontSize: '.8125rem', fontWeight: 600, color: tone ? toneColor(tone) : 'var(--text-secondary)' }}>{v}</span>
    </span>
  );
}
