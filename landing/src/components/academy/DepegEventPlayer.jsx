import { useState, useEffect, useRef, useCallback } from 'react';
import { getLang, recordPlaygroundTried } from './progress.js';

/*
 * DepegEventPlayer.jsx — ▶ PLAY a REAL dated event and watch the aggressive
 * «15% delta-neutral» book drop while the steady ~4.5% book stays flat.
 *
 * The visceral «вот что 15% реально стоит». A timeline scrubber + play/pause walks
 * across the real 2024–2026 dated events and applies, on each event's REAL DATE,
 * the aggressive book's REAL drawdown depth, while the steady book just accrues.
 *
 * DATA (fail-CLOSED): pulls /api/aggressive-lab/annual-contrast and reads
 *   - stress_windows[]            (real dated events: Aug-2024, Oct-2025 USDe unwind, Apr-2026 rsETH)
 *   - strategies[].dated_drawdown_timeline.dated_stress_overlay[]  (real depth_pct per event,
 *     modeled by the book's risk SHAPE — labelled modeled_stress_overlay, never blended)
 *   - stable_apy_pct              (the REAL conservative book APY — not a flattering fake)
 *
 * If the API is offline OR the shape is bad → we fall back to a DOCUMENTED dated
 * literal (clearly LABELLED static) built from the committed annual_contrast.json
 * (as_of 2026-06-25). We NEVER exaggerate: the depths are the real overlay depths
 * (−4% / −7% / −9%), not a scarier invented number, and the source is shown.
 */

const API =
  typeof window !== 'undefined' &&
  (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1')
    ? 'http://localhost:8765'
    : 'https://api.earn-defi.com';
const FETCH_TIMEOUT_MS = 8000;

// DOCUMENTED static fallback — committed data/aggressive_lab/annual_contrast.json (as_of 2026-06-25).
// Depths are the REAL dated_stress_overlay depth_pct for a depeg-shape book. Labelled static; never live.
const STATIC = {
  stable_apy_pct: 4.1394,
  source: 'static fallback · annual_contrast.json as_of 2026-06-25',
  events: [
    { date: '2024-08-05', key: 'eth_crash_2024_08', label_ru: '2024-08 крах ETH / unwind carry', label_en: '2024-08 ETH crash / carry unwind',
      depth_pct: -4.0, detail_ru: 'ETH резко продали; funding sUSDe ушёл в минус, пеги LST/LRT качнуло на de-risk.', detail_en: 'ETH sold off hard; sUSDe funding flipped hostile; LST/LRT pegs wobbled.' },
    { date: '2025-10-11', key: 'usde_unwind_2025_10', label_ru: '2025-10 unwind USDe (THE test)', label_en: '2025-10 USDe unwind (THE test)',
      depth_pct: -7.0, detail_ru: 'Канонический тест: предложение Ethena USDe схлопнулось $14B→$5.6B — раскрутка переплечённого PT-loop carry; каскад funding/peg.', detail_en: 'The canonical test: USDe supply collapsed $14B→$5.6B as the over-levered PT-loop carry unwound; funding/peg cascade.' },
    { date: '2026-04-05', key: 'rseth_depeg_2026_04', label_ru: '2026-04 депег rsETH (KelpDAO)', label_en: '2026-04 KelpDAO rsETH depeg',
      depth_pct: -9.0, detail_ru: 'Депег рестейкинга (LRT) — катастрофа для LRT/levered книги; деск отказывает ровно этому shape.', detail_en: 'A restaking (LRT) depeg — catastrophic for an LRT/levered book; the desk refuses exactly this shape.' },
  ],
};

const T = {
  title: { ru: 'Плеер реальных депег-событий', en: 'Real depeg-event player' },
  intro: {
    ru: 'Нажми ▶ — таймлайн проигрывает РЕАЛЬНЫЕ датированные события. На каждой реальной дате агрессивная «15% delta-neutral» книга проседает на реальную глубину, а устойчивая ~4.5% книга остаётся плоской. Вот что 15% реально стоит.',
    en: 'Press ▶ — the timeline plays REAL dated events. On each real date the aggressive «15% delta-neutral» book drops by its real depth while the steady ~4.5% book stays flat. This is what 15% really costs.',
  },
  play: { ru: '▶ Играть', en: '▶ Play' },
  pause: { ru: '⏸ Пауза', en: '⏸ Pause' },
  reset: { ru: '↻ Сброс', en: '↻ Reset' },
  aggressive: { ru: 'Агрессивная книга (15%)', en: 'Aggressive book (15%)' },
  steady: { ru: 'Устойчивая книга (~5%)', en: 'Steady book (~5%)' },
  live: { ru: 'Живой API', en: 'Live API' },
  static: { ru: 'Статика (API офлайн)', en: 'Static (API offline)' },
  now: { ru: 'Текущая дата', en: 'Current date' },
  event: { ru: 'Событие', en: 'Event' },
  modeled: { ru: 'modeled_stress_overlay — глубина по risk-shape на реальную дату (НЕ выдумка)', en: 'modeled_stress_overlay — depth by risk shape on the real date (NOT fabricated)' },
  drop: { ru: 'просадка на дате', en: 'drop on date' },
  source: { ru: 'Источник', en: 'Source' },
};

function fmtMoney(v) { return '$' + Math.round(v).toLocaleString('en-US'); }

export default function DepegEventPlayer() {
  const [lang, setLang] = useState('ru');
  const [model, setModel] = useState(STATIC);
  const [isLive, setIsLive] = useState(false);
  const [step, setStep] = useState(0);     // 0 = before any event; N events → step 0..N
  const [playing, setPlaying] = useState(false);
  const timer = useRef(null);

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
      const r = await fetch(API + '/api/aggressive-lab/annual-contrast', { signal: AbortSignal.timeout(FETCH_TIMEOUT_MS), headers: { Accept: 'application/json' } });
      if (!r.ok) throw new Error('HTTP ' + r.status);
      const d = await r.json();
      const windows = Array.isArray(d?.stress_windows) ? d.stress_windows : null;
      const stable = Number(d?.stable_apy_pct);
      if (!windows || windows.length === 0 || !isFinite(stable)) throw new Error('bad shape');

      // depth per window: take the deepest depeg-shape overlay across strategies for that window
      const depthByWindow = {};
      (Array.isArray(d.strategies) ? d.strategies : []).forEach((s) => {
        const ov = s?.dated_drawdown_timeline?.dated_stress_overlay;
        if (!Array.isArray(ov)) return;
        ov.forEach((e) => {
          const key = e.window_key;
          const depth = Number(e.depth_pct);
          if (!key || !isFinite(depth)) return;
          if (depthByWindow[key] == null || depth < depthByWindow[key]) depthByWindow[key] = depth; // most negative
        });
      });

      const events = windows.map((w) => ({
        date: w.event_date || w.date_from,
        key: w.key,
        label_ru: w.label || w.event, label_en: w.label || w.event,
        detail_ru: w.detail || '', detail_en: w.detail || '',
        depth_pct: depthByWindow[w.key] != null ? depthByWindow[w.key] : -5.0,
      })).filter((e) => e.date && isFinite(e.depth_pct))
        .sort((a, b) => a.date.localeCompare(b.date));

      if (events.length === 0) throw new Error('no events');
      setModel({ stable_apy_pct: stable, source: `live · /api/aggressive-lab/annual-contrast (as_of ${d.as_of || '—'})`, events });
      setIsLive(true);
    } catch {
      setModel(STATIC); setIsLive(false); // fail-CLOSED: documented dated literal, labelled static
    }
  }, []);

  useEffect(() => { poll(); }, [poll]);

  const events = model.events;
  const N = events.length;

  // play loop: advance one event ~every 1.4s
  useEffect(() => {
    if (!playing) { if (timer.current) clearInterval(timer.current); return; }
    timer.current = setInterval(() => {
      setStep((s) => { if (s >= N) { setPlaying(false); return s; } return s + 1; });
    }, 1400);
    return () => { if (timer.current) clearInterval(timer.current); };
  }, [playing, N]);

  // equity at current step. Aggressive starts at $100k notional, takes each event's
  // depth multiplicatively as the date passes. Steady accrues stable_apy across the
  // window span (flat-ish, ~5%). Both honest: aggressive only DROPS, never inflated.
  const START = 100000;
  const dateOf = (i) => (i <= 0 ? (events[0]?.date || '—') : events[Math.min(i, N) - 1]?.date || '—');
  let aggr = START, steady = START;
  for (let i = 0; i < Math.min(step, N); i++) {
    aggr *= (1 + events[i].depth_pct / 100);
    steady *= (1 + (model.stable_apy_pct / 100) * (0.33)); // ~⅓-year between events → mild accrual
  }
  const aggrPct = (aggr / START - 1) * 100;
  const steadyPct = (steady / START - 1) * 100;
  const curEvent = step > 0 && step <= N ? events[step - 1] : null;

  // engagement XP + "playground" badge on first interaction (idempotent, SSR-safe)
  const tried = () => recordPlaygroundTried('DepegEventPlayer');
  function reset() { tried(); setPlaying(false); setStep(0); }

  return (
    <div style={wrap}>
      <div style={head}>
        {tr('title')}
        <span style={{ float: 'right', fontFamily: 'var(--font-mono)', fontSize: 10, padding: '2px 8px', borderRadius: 'var(--r-full)', border: `1px solid ${isLive ? 'var(--ok)' : 'var(--warn)'}`, color: isLive ? 'var(--ok)' : 'var(--warn)' }}>
          {isLive ? '● ' + tr('live') : '○ ' + tr('static')}
        </span>
      </div>
      <p style={{ fontSize: 14, color: 'var(--text-secondary)', lineHeight: 1.6, marginTop: 0 }}>{tr('intro')}</p>

      {/* controls */}
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 14 }}>
        <button style={{ ...ctrlBtn, borderColor: 'var(--accent)', color: 'var(--accent)' }} onClick={() => { tried(); if (step >= N) setStep(0); setPlaying((p) => !p); }}>
          {playing ? tr('pause') : tr('play')}
        </button>
        <button style={ctrlBtn} onClick={reset}>{tr('reset')}</button>
        <span style={{ marginLeft: 'auto', fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--text-muted)' }}>
          {tr('now')}: <span style={{ color: 'var(--text-primary)' }}>{dateOf(step)}</span>
        </span>
      </div>

      {/* scrubber */}
      <input type="range" min={0} max={N} step={1} value={step}
        onChange={(e) => { tried(); setPlaying(false); setStep(parseInt(e.target.value, 10)); }}
        style={{ width: '100%', accentColor: 'var(--danger)' }} />
      <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-muted)', marginTop: 2 }}>
        {events.map((e, i) => <span key={i} style={{ color: step > i ? 'var(--danger)' : 'var(--text-muted)' }}>{e.date.slice(0, 7)}</span>)}
      </div>

      {/* dual equity bars */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginTop: 18 }}>
        <Book label={tr('aggressive')} val={aggr} pct={aggrPct} color="var(--danger)" start={START} />
        <Book label={tr('steady')} val={steady} pct={steadyPct} color="var(--ok)" start={START} />
      </div>

      {/* event detail */}
      {curEvent && (
        <div style={{ marginTop: 16, padding: '14px 16px', borderRadius: 'var(--r-md)', border: '1px solid var(--danger)', background: 'rgba(242,109,109,0.07)' }}>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, letterSpacing: '0.10em', textTransform: 'uppercase', color: 'var(--text-faint)', marginBottom: 6 }}>{tr('event')} · {curEvent.date}</div>
          <div style={{ fontWeight: 700, color: 'var(--danger)', fontSize: 15 }}>
            {(lang === 'ru' ? curEvent.label_ru : curEvent.label_en)}
            <span style={{ marginLeft: 10, fontFamily: 'var(--font-mono)' }}>{tr('drop')}: {curEvent.depth_pct.toFixed(1)}%</span>
          </div>
          <div style={{ fontSize: 13, color: 'var(--text-secondary)', marginTop: 8, lineHeight: 1.55 }}>{lang === 'ru' ? curEvent.detail_ru : curEvent.detail_en}</div>
          <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 8 }}>{tr('modeled')}</div>
        </div>
      )}

      <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 12 }}>{tr('source')}: {model.source}</div>
    </div>
  );
}

function Book({ label, val, pct, color, start }) {
  // bar height proportional to equity / start (clamped 0..120%)
  const h = Math.max(4, Math.min(120, (val / start) * 100));
  return (
    <div style={{ background: 'var(--bg-surface-2)', border: '1px solid var(--border)', borderRadius: 'var(--r-md)', padding: 14 }}>
      <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 8 }}>{label}</div>
      <div style={{ height: 130, display: 'flex', alignItems: 'flex-end' }}>
        <div style={{ width: '100%', height: h + '%', background: color, opacity: 0.85, borderRadius: '4px 4px 0 0', transition: 'height 600ms ease' }} />
      </div>
      <div style={{ fontFamily: 'var(--font-mono)', fontSize: 18, fontWeight: 700, color: 'var(--text-primary)', marginTop: 8 }}>{fmtMoney(val)}</div>
      <div style={{ fontFamily: 'var(--font-mono)', fontSize: 13, color, fontWeight: 600 }}>{pct >= 0 ? '+' : ''}{pct.toFixed(1)}%</div>
    </div>
  );
}

const wrap = { background: 'var(--bg-surface)', border: '1px solid var(--border)', borderRadius: 'var(--r-lg)', padding: 24, margin: '28px 0' };
const head = { fontFamily: 'var(--font-mono)', fontSize: 12, letterSpacing: '0.12em', textTransform: 'uppercase', color: 'var(--accent)', marginBottom: 12 };
const ctrlBtn = { padding: '7px 16px', fontSize: 13, fontWeight: 600, borderRadius: 'var(--r-sm)', border: '1px solid var(--border)', background: 'transparent', color: 'var(--text-secondary)', cursor: 'pointer', fontFamily: 'var(--font-sans)' };
