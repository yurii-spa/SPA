import { useState, useEffect, useRef, useMemo } from 'react';
import { observeInView, prefersReducedMotion } from './motion.js';

/*
 * AnimatedChart.jsx — reusable inline-SVG line chart that DRAWS IN on scroll.
 *
 * The line path animates (stroke-dashoffset) from blank to full once the chart scrolls
 * into view; optional drawdown markers "drop" to their REAL depth on their date. Used for
 * equity curves, the edge-at-scale curve, the floor benchmark, the 15%-vs-5% contrast.
 *
 * HONESTY (red-team requirement): the chart only ever renders the data points it is given.
 * It does NOT fabricate or exaggerate — a −66% drawdown animates to −66%, never deeper.
 * Animation is presentation only; the y-extent is taken straight from the data. Under
 * `prefers-reduced-motion` the final chart is drawn instantly with no path animation.
 *
 * Agents B+C reuse this directly:
 *   import AnimatedChart from './AnimatedChart.jsx';
 *   <AnimatedChart
 *     series={[{ points:[{x,y}...], color, label, fill? }, ...]}  // x,y in data units
 *     markers={[{ x, y, label, color }]}    // optional dots/annotations (e.g. drawdowns)
 *     height={220} yLabel="$" xLabels={['2025','2026']}
 *     client:visible />
 *
 * `points` x/y are arbitrary data units; the component computes the domain from the data
 * (or from explicit yMin/yMax/xMin/xMax props). No external chart lib — pure SVG.
 */

const PAD = { top: 16, right: 16, bottom: 26, left: 44 };

function domain(values, min, max) {
  if (min != null && max != null) return [min, max];
  let lo = Infinity, hi = -Infinity;
  for (const v of values) { if (v < lo) lo = v; if (v > hi) hi = v; }
  if (!Number.isFinite(lo) || !Number.isFinite(hi)) return [0, 1];
  if (lo === hi) { lo -= 1; hi += 1; }
  const padY = (hi - lo) * 0.08;
  return [lo - padY, hi + padY];
}

export default function AnimatedChart({
  series = [],
  markers = [],
  height = 220,
  width = 640,
  yMin, yMax, xMin, xMax,
  xLabels = [],
  yFormat,
  ariaLabel = 'график',
}) {
  const ref = useRef(null);
  const [drawn, setDrawn] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const unobserve = observeInView(el, () => setDrawn(true));
    return unobserve;
  }, []);

  const reduce = typeof window !== 'undefined' && prefersReducedMotion();

  const geom = useMemo(() => {
    const allX = [], allY = [];
    for (const s of series) for (const p of s.points || []) { allX.push(p.x); allY.push(p.y); }
    for (const m of markers) { allX.push(m.x); allY.push(m.y); }
    const [yLo, yHi] = domain(allY, yMin, yMax);
    const [xLo, xHi] = domain(allX, xMin, xMax);
    const W = width, H = height;
    const sx = (x) => PAD.left + ((x - xLo) / (xHi - xLo || 1)) * (W - PAD.left - PAD.right);
    const sy = (y) => PAD.top + (1 - (y - yLo) / (yHi - yLo || 1)) * (H - PAD.top - PAD.bottom);
    const fmtY = yFormat || ((v) => (Math.abs(v) >= 1000 ? (v / 1000).toFixed(0) + 'k' : v.toFixed(0)));
    // 4 horizontal gridlines
    const grid = [0, 1, 2, 3].map((i) => {
      const v = yLo + (i / 3) * (yHi - yLo);
      return { y: sy(v), label: fmtY(v) };
    });
    return { sx, sy, W, H, grid };
  }, [series, markers, height, width, yMin, yMax, xMin, xMax, yFormat]);

  function pathFor(points) {
    if (!points || points.length === 0) return '';
    return points
      .map((p, i) => `${i === 0 ? 'M' : 'L'}${geom.sx(p.x).toFixed(1)},${geom.sy(p.y).toFixed(1)}`)
      .join(' ');
  }
  function areaFor(points) {
    if (!points || points.length === 0) return '';
    const top = points.map((p) => `${geom.sx(p.x).toFixed(1)},${geom.sy(p.y).toFixed(1)}`).join(' L');
    const x0 = geom.sx(points[0].x).toFixed(1);
    const xN = geom.sx(points[points.length - 1].x).toFixed(1);
    const yB = (geom.H - PAD.bottom).toFixed(1);
    return `M${top} L${xN},${yB} L${x0},${yB} Z`;
  }

  return (
    <div ref={ref} style={{ width: '100%' }}>
      <svg
        viewBox={`0 0 ${geom.W} ${geom.H}`}
        role="img"
        aria-label={ariaLabel}
        style={{ width: '100%', height: 'auto', display: 'block' }}
        preserveAspectRatio="xMidYMid meet"
      >
        {/* gridlines + y labels */}
        {geom.grid.map((g, i) => (
          <g key={'g' + i}>
            <line x1={PAD.left} x2={geom.W - PAD.right} y1={g.y} y2={g.y} stroke="var(--border)" strokeWidth="1" />
            <text x={PAD.left - 8} y={g.y + 3} textAnchor="end" fontSize="10" fill="var(--text-muted)" fontFamily="var(--font-mono)">{g.label}</text>
          </g>
        ))}
        {/* x labels */}
        {xLabels.map((lbl, i) => {
          const x = PAD.left + (xLabels.length > 1 ? (i / (xLabels.length - 1)) : 0.5) * (geom.W - PAD.left - PAD.right);
          return <text key={'x' + i} x={x} y={geom.H - 8} textAnchor={i === 0 ? 'start' : i === xLabels.length - 1 ? 'end' : 'middle'} fontSize="10" fill="var(--text-muted)" fontFamily="var(--font-mono)">{lbl}</text>;
        })}

        {/* series */}
        {series.map((s, i) => {
          const d = pathFor(s.points);
          const color = s.color || 'var(--accent)';
          return (
            <g key={'s' + i}>
              {s.fill && (
                <path
                  d={areaFor(s.points)}
                  fill={color}
                  opacity={drawn ? 0.10 : 0}
                  style={{ transition: reduce ? 'none' : 'opacity 600ms ease 300ms' }}
                />
              )}
              <path
                d={d}
                fill="none"
                stroke={color}
                strokeWidth={s.width || 2}
                strokeLinejoin="round"
                strokeLinecap="round"
                pathLength={1}
                strokeDasharray={reduce ? 'none' : 1}
                strokeDashoffset={reduce ? 0 : (drawn ? 0 : 1)}
                style={{ transition: reduce ? 'none' : 'stroke-dashoffset 1200ms cubic-bezier(.4,0,.2,1)' }}
              />
            </g>
          );
        })}

        {/* markers (e.g. dated drawdowns) — fade/scale in to REAL depth, never exaggerated */}
        {markers.map((m, i) => {
          const cx = geom.sx(m.x), cy = geom.sy(m.y);
          const color = m.color || 'var(--danger)';
          const delay = reduce ? 0 : 700 + i * 120;
          return (
            <g key={'m' + i} style={{ opacity: drawn || reduce ? 1 : 0, transition: reduce ? 'none' : `opacity 300ms ease ${delay}ms` }}>
              <circle cx={cx} cy={cy} r="4" fill={color} stroke="var(--bg-base)" strokeWidth="1.5" />
              {m.label && (
                <text x={cx} y={cy - 9} textAnchor="middle" fontSize="10" fontWeight="700" fill={color} fontFamily="var(--font-mono)">{m.label}</text>
              )}
            </g>
          );
        })}
      </svg>
      {series.some((s) => s.label) && (
        <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', justifyContent: 'center', marginTop: 8 }}>
          {series.filter((s) => s.label).map((s, i) => (
            <span key={i} style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12, color: 'var(--text-secondary)' }}>
              <span style={{ width: 12, height: 2, background: s.color || 'var(--accent)', display: 'inline-block', borderRadius: 2 }} />
              {s.label}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
