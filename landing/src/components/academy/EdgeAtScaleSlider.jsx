import { useState, useEffect, useCallback } from 'react';
import { getLang, recordPlaygroundTried } from './progress.js';
import AnimatedChart from './AnimatedChart.jsx';

/*
 * EdgeAtScaleSlider.jsx — the «$1M cliff» visualizer.
 *
 * Slides AUM $100k → $10M and shows the optimizer uplift (pp) collapsing as
 * pool-capacity caps bind: +1.08pp @ $100k → negative past ~$1M. Capacity-capped
 * capital becomes idle cash earning 0 — the honest, conservative drag.
 *
 * DATA: tries the live API (/api/edge-at-scale) first; on offline/failure falls
 * back to a DOCUMENTED static curve (the committed data/edge_at_scale.json shape,
 * universe 2026-06-29). The fallback is clearly labelled as static — NEVER shown
 * as live. Between ladder points we interpolate log-linearly (clearly a model line).
 */

const API =
  typeof window !== 'undefined' &&
  (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1')
    ? 'http://localhost:8765'
    : 'https://api.earn-defi.com';
const FETCH_TIMEOUT_MS = 8000;

// DOCUMENTED static fallback — the committed data/edge_at_scale.json curve (universe 2026-06-29).
const STATIC_CURVE = [
  { aum_usd: 100000, uplift_pp: 1.080005, optimized_yield_on_capital_pct: 5.58, legacy_yield_on_capital_pct: 4.499995, uplift_material: true },
  { aum_usd: 1000000, uplift_pp: -2.003445, optimized_yield_on_capital_pct: 1.38, legacy_yield_on_capital_pct: 3.383445, uplift_material: false },
  { aum_usd: 10000000, uplift_pp: -2.6, optimized_yield_on_capital_pct: 0.78, legacy_yield_on_capital_pct: 3.38, uplift_material: false },
];

const T = {
  title: { ru: 'Edge на масштабе: обрыв $1M', en: 'Edge at scale: the $1M cliff' },
  intro: {
    ru: 'Двигай AUM. Оптимизаторный uplift положителен на малом капитале, но схлопывается после ~$1M: pool-capacity cap\'ы (1% TVL, 3% T1>$1B) бьют — лишний капитал становится idle cash под 0%.',
    en: 'Slide AUM. The optimizer uplift is positive at small size but collapses past ~$1M: pool-capacity caps bind and excess capital becomes idle cash at 0%.',
  },
  aum: { ru: 'AUM (капитал под управлением)', en: 'AUM (assets under management)' },
  uplift: { ru: 'Uplift оптимизатора', en: 'Optimizer uplift' },
  optimized: { ru: 'Оптимизированная доходность', en: 'Optimized yield' },
  legacy: { ru: 'Базовая доходность', en: 'Legacy yield' },
  material: { ru: 'материальный', en: 'material' },
  notMaterial: { ru: 'НЕ материальный', en: 'NOT material' },
  cliff: { ru: 'За обрывом: edge отрицателен — масштабировать невыгодно', en: 'Past the cliff: edge is negative — scaling destroys value' },
  belowCliff: { ru: 'До обрыва: edge реален и материальный', en: 'Below the cliff: edge is real and material' },
  live: { ru: 'Живой API', en: 'Live API' },
  static: { ru: 'Статическая кривая (API офлайн)', en: 'Static curve (API offline)' },
  source: { ru: 'Источник', en: 'Source' },
};

function fmtAum(v) {
  if (v >= 1e6) return '$' + (v / 1e6).toFixed(v % 1e6 === 0 ? 0 : 2) + 'M';
  return '$' + (v / 1e3).toFixed(0) + 'k';
}

// log-interp the curve at an arbitrary AUM
function interp(curve, aum) {
  const pts = [...curve].sort((a, b) => a.aum_usd - b.aum_usd);
  if (aum <= pts[0].aum_usd) return pts[0];
  if (aum >= pts[pts.length - 1].aum_usd) return pts[pts.length - 1];
  for (let i = 0; i < pts.length - 1; i++) {
    const a = pts[i], b = pts[i + 1];
    if (aum >= a.aum_usd && aum <= b.aum_usd) {
      const t = (Math.log(aum) - Math.log(a.aum_usd)) / (Math.log(b.aum_usd) - Math.log(a.aum_usd));
      const mix = (k) => a[k] + t * (b[k] - a[k]);
      return {
        aum_usd: aum,
        uplift_pp: mix('uplift_pp'),
        optimized_yield_on_capital_pct: mix('optimized_yield_on_capital_pct'),
        legacy_yield_on_capital_pct: mix('legacy_yield_on_capital_pct'),
        uplift_material: mix('uplift_pp') >= 0.25,
      };
    }
  }
  return pts[0];
}

export default function EdgeAtScaleSlider() {
  const [lang, setLang] = useState('ru');
  const [curve, setCurve] = useState(STATIC_CURVE);
  const [isLive, setIsLive] = useState(false);
  // slider is a log position 0..1000 mapped to $100k..$10M
  const [pos, setPos] = useState(0);

  useEffect(() => {
    setLang(getLang());
    const onLang = () => setLang(getLang());
    window.addEventListener('storage', onLang);
    const obs = new MutationObserver(() => setLang(getLang()));
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ['lang'] });
    return () => { window.removeEventListener('storage', onLang); obs.disconnect(); };
  }, []);
  const tr = (k) => (T[k] ? (T[k][lang] ?? T[k].ru) : k);

  const poll = useCallback(async () => {
    try {
      const r = await fetch(API + '/api/edge-at-scale', {
        signal: AbortSignal.timeout(FETCH_TIMEOUT_MS),
        headers: { Accept: 'application/json' },
      });
      if (!r.ok) throw new Error('HTTP ' + r.status);
      const d = await r.json();
      if (d && Array.isArray(d.curve) && d.curve.length >= 2) {
        setCurve(d.curve);
        setIsLive(true);
        return;
      }
      throw new Error('bad shape');
    } catch {
      // fail-closed: keep the documented static curve, label it static (never fabricate)
      setCurve(STATIC_CURVE);
      setIsLive(false);
    }
  }, []);

  useEffect(() => { poll(); }, [poll]);

  const minLog = Math.log(100000), maxLog = Math.log(10000000);
  const aum = Math.exp(minLog + (pos / 1000) * (maxLog - minLog));
  const p = interp(curve, aum);
  const negative = p.uplift_pp < 0;
  const upColor = negative ? 'var(--danger)' : 'var(--ok)';

  // honest uplift-vs-AUM curve for the draw-in chart: sample the SAME interp() the slider
  // uses, log-spaced across $100k..$10M. x = log10(aum) so the cliff sits where it really is.
  const chartPoints = [];
  for (let i = 0; i <= 40; i++) {
    const a = Math.exp(minLog + (i / 40) * (maxLog - minLog));
    chartPoints.push({ x: Math.log10(a), y: interp(curve, a).uplift_pp });
  }
  // zero-line reference so the sign flip (the cliff) is visually unambiguous
  const zeroLine = [
    { x: Math.log10(100000), y: 0 },
    { x: Math.log10(10000000), y: 0 },
  ];
  // marker at the current slider AUM (real value, never exaggerated)
  const cursor = [{ x: Math.log10(aum), y: p.uplift_pp, color: upColor, label: fmtAum(aum) }];

  return (
    <div style={wrap}>
      <div style={head}>
        {tr('title')}
        <span style={{
          float: 'right', fontFamily: 'var(--font-mono)', fontSize: 10, padding: '2px 8px', borderRadius: 'var(--r-full)',
          border: `1px solid ${isLive ? 'var(--ok)' : 'var(--warn)'}`, color: isLive ? 'var(--ok)' : 'var(--warn)',
        }}>
          {isLive ? '● ' + tr('live') : '○ ' + tr('static')}
        </span>
      </div>
      <p style={{ fontSize: 14, color: 'var(--text-secondary)', lineHeight: 1.6, marginTop: 0 }}>{tr('intro')}</p>

      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, marginBottom: 6 }}>
        <span style={{ color: 'var(--text-secondary)' }}>{tr('aum')}</span>
        <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--data-teal)', fontSize: 18, fontWeight: 700 }}>{fmtAum(aum)}</span>
      </div>
      <input type="range" min={0} max={1000} step={1} value={pos}
        onChange={(e) => { recordPlaygroundTried('EdgeAtScaleSlider'); setPos(parseFloat(e.target.value)); }}
        style={{ width: '100%', accentColor: 'var(--data-teal)' }} />
      <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>
        <span>$100k</span><span>$1M</span><span>$10M</span>
      </div>

      {/* honest uplift curve that DRAWS IN on scroll — the $1M cliff is the sign flip */}
      <div style={{ marginTop: 16, background: 'var(--bg-surface-2)', border: '1px solid var(--border)', borderRadius: 'var(--r-md)', padding: '12px 8px 6px' }}>
        <AnimatedChart
          series={[
            { points: zeroLine, color: 'var(--text-faint)', width: 1 },
            { points: chartPoints, color: 'var(--accent)', width: 2.5, label: tr('uplift') + ' (pp)' },
          ]}
          markers={cursor}
          height={180}
          xLabels={['$100k', '$1M', '$10M']}
          yFormat={(v) => (v >= 0 ? '+' : '') + v.toFixed(1)}
          ariaLabel={tr('title')}
        />
      </div>

      <div style={{ marginTop: 18, textAlign: 'center', padding: '18px 0', border: `1px solid ${upColor}`, borderRadius: 'var(--r-md)', background: negative ? 'rgba(242,109,109,0.06)' : 'rgba(52,211,153,0.06)', transition: 'border-color 200ms var(--ease), background 200ms var(--ease)' }}>
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, letterSpacing: '0.10em', textTransform: 'uppercase', color: 'var(--text-faint)' }}>{tr('uplift')}</div>
        <div style={{ fontSize: 34, fontWeight: 700, color: upColor, fontFamily: 'var(--font-mono)', transition: 'color 200ms var(--ease)' }}>
          {p.uplift_pp >= 0 ? '+' : ''}{p.uplift_pp.toFixed(2)}pp
        </div>
        <div style={{ fontSize: 12, color: upColor, transition: 'color 200ms var(--ease)' }}>{p.uplift_material ? tr('material') : tr('notMaterial')}</div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginTop: 14 }}>
        <div style={miniCard}>
          <div style={miniLabel}>{tr('optimized')}</div>
          <div style={{ ...miniVal, color: 'var(--accent)' }}>{p.optimized_yield_on_capital_pct.toFixed(2)}%</div>
        </div>
        <div style={miniCard}>
          <div style={miniLabel}>{tr('legacy')}</div>
          <div style={{ ...miniVal, color: 'var(--text-secondary)' }}>{p.legacy_yield_on_capital_pct.toFixed(2)}%</div>
        </div>
      </div>

      <div style={{ marginTop: 14, fontSize: 13, color: negative ? 'var(--danger)' : 'var(--ok)', fontWeight: 600 }}>
        {negative ? tr('cliff') : tr('belowCliff')}
      </div>
    </div>
  );
}

const wrap = { background: 'var(--bg-surface)', border: '1px solid var(--border)', borderRadius: 'var(--r-lg)', padding: 24, margin: '28px 0' };
const head = { fontFamily: 'var(--font-mono)', fontSize: 12, letterSpacing: '0.12em', textTransform: 'uppercase', color: 'var(--accent)', marginBottom: 12 };
const miniCard = { background: 'var(--bg-surface-2)', border: '1px solid var(--border)', borderRadius: 'var(--r-md)', padding: '12px 14px' };
const miniLabel = { fontSize: 12, color: 'var(--text-muted)' };
const miniVal = { fontFamily: 'var(--font-mono)', fontSize: 22, fontWeight: 700, marginTop: 4 };
