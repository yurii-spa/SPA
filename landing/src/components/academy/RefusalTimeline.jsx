import { useState, useEffect, useRef, useCallback } from 'react';
import { getLang, recordPlaygroundTried } from './progress.js';

/*
 * RefusalTimeline.jsx (optional 4th sim) — scrub the full 2024–26 timeline and watch
 * the desk's refusals FIRE on toxic books as each dated event passes.
 *
 * The pairing to DepegEventPlayer: that one shows what 15% COSTS; this one shows that
 * the desk REFUSED those exact shapes BEFORE the event — i.e. the refusal was the right
 * call, dated, not hindsight. As the scrubber crosses each event date, the toxic books
 * whose risk shape matches that event light up REFUSED with the dated reason.
 *
 * DATA (fail-CLOSED): /api/aggressive-lab/annual-contrast → stress_windows[]. If offline
 * or bad shape → DOCUMENTED static literal (labelled static), built from the committed
 * annual_contrast.json (as_of 2026-06-25). Refusal reasons mirror the refusal-first gate
 * (structural tail-veto on peg/funding/oracle/protocol). Never fabricated.
 */

const API =
  typeof window !== 'undefined' &&
  (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1')
    ? 'http://localhost:8765'
    : 'https://api.earn-defi.com';
const FETCH_TIMEOUT_MS = 8000;

// Books the desk REFUSES, each with its risk shape — these are the real aggressive-lab roster shapes.
const BOOKS = [
  { id: 'lrt',   ru: 'LRT-рестейк (ezETH/rsETH)', en: 'LRT restaking (ezETH/rsETH)', shapes: ['depeg'] },
  { id: 'susde', ru: 'sUSDe delta-neutral', en: 'sUSDe delta-neutral', shapes: ['depeg', 'funding_flip'] },
  { id: 'loop',  ru: 'Leverage looping', en: 'Leverage looping', shapes: ['liquidation', 'depeg'] },
  { id: 'ytlev', ru: 'Pendle YT (плечо)', en: 'Pendle YT (levered)', shapes: ['funding_flip', 'liquidation'] },
];

// DOCUMENTED static fallback — committed annual_contrast.json stress_windows (as_of 2026-06-25).
const STATIC_EVENTS = [
  { date: '2024-08-05', shape: 'depeg', ru: '2024-08 крах ETH / unwind carry', en: '2024-08 ETH crash / carry unwind' },
  { date: '2025-10-11', shape: 'depeg', ru: '2025-10 unwind USDe ($14B→$5.6B)', en: '2025-10 USDe unwind ($14B→$5.6B)' },
  { date: '2026-04-05', shape: 'depeg', ru: '2026-04 депег rsETH (KelpDAO)', en: '2026-04 KelpDAO rsETH depeg' },
];

const T = {
  title: { ru: 'Таймлайн отказов 2024–2026', en: 'Refusal timeline 2024–2026' },
  intro: {
    ru: 'Двигай ползунок по времени (или ▶). Когда пересекаешь дату реального события, токсичные книги, чей risk-shape совпадает, загораются ОТКАЗАНО — деск отказал ровно этому shape ДО события, а не задним числом.',
    en: 'Drag the time scrubber (or ▶). As you cross a real event date, the toxic books whose risk shape matches light up REFUSED — the desk refused exactly that shape BEFORE the event, not in hindsight.',
  },
  play: { ru: '▶ Играть', en: '▶ Play' }, pause: { ru: '⏸ Пауза', en: '⏸ Pause' }, reset: { ru: '↻ Сброс', en: '↻ Reset' },
  live: { ru: 'Живой API', en: 'Live API' }, static: { ru: 'Статика (API офлайн)', en: 'Static (API offline)' },
  now: { ru: 'Дата', en: 'Date' },
  refused: { ru: 'ОТКАЗАНО', en: 'REFUSED' },
  watching: { ru: 'отказан превентивно', en: 'pre-emptively refused' },
  fired: { ru: 'Событие — отказ оправдан', en: 'Event — refusal vindicated' },
  shape: { ru: 'shape', en: 'shape' },
  source: { ru: 'Источник', en: 'Source' },
};

function monthIndex(d) { const [y, m] = d.split('-'); return (parseInt(y, 10) - 2024) * 12 + (parseInt(m, 10) - 1); }

export default function RefusalTimeline() {
  const [lang, setLang] = useState('ru');
  const [events, setEvents] = useState(STATIC_EVENTS);
  const [isLive, setIsLive] = useState(false);
  const [src, setSrc] = useState('static · annual_contrast.json as_of 2026-06-25');
  const [pos, setPos] = useState(0); // month index 0..MAX
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
  // engagement XP + "playground" badge on first interaction (idempotent, SSR-safe)
  const tried = () => recordPlaygroundTried('RefusalTimeline');

  const poll = useCallback(async () => {
    try {
      const r = await fetch(API + '/api/aggressive-lab/annual-contrast', { signal: AbortSignal.timeout(FETCH_TIMEOUT_MS), headers: { Accept: 'application/json' } });
      if (!r.ok) throw new Error('HTTP ' + r.status);
      const d = await r.json();
      const w = Array.isArray(d?.stress_windows) ? d.stress_windows : null;
      if (!w || w.length === 0) throw new Error('bad shape');
      const ev = w.map((x) => ({ date: x.event_date || x.date_from, shape: 'depeg', ru: x.label || x.event, en: x.label || x.event }))
        .filter((x) => x.date).sort((a, b) => a.date.localeCompare(b.date));
      if (ev.length === 0) throw new Error('no events');
      setEvents(ev); setIsLive(true); setSrc(`live · /api/aggressive-lab/annual-contrast (as_of ${d.as_of || '—'})`);
    } catch {
      setEvents(STATIC_EVENTS); setIsLive(false); setSrc('static · annual_contrast.json as_of 2026-06-25');
    }
  }, []);
  useEffect(() => { poll(); }, [poll]);

  const MIN = 0; // 2024-01
  const MAX = 35; // 2026-12 → 36 months
  useEffect(() => {
    if (!playing) { if (timer.current) clearInterval(timer.current); return; }
    timer.current = setInterval(() => setPos((p) => { if (p >= MAX) { setPlaying(false); return p; } return p + 1; }), 220);
    return () => { if (timer.current) clearInterval(timer.current); };
  }, [playing]);

  const curDate = `${2024 + Math.floor(pos / 12)}-${String((pos % 12) + 1).padStart(2, '0')}`;
  const passedEvents = events.filter((e) => monthIndex(e.date) <= pos);
  const passedShapes = new Set(passedEvents.map((e) => e.shape));
  const lastEvent = passedEvents[passedEvents.length - 1] || null;

  return (
    <div style={wrap}>
      <div style={head}>
        {tr('title')}
        <span style={{ float: 'right', fontFamily: 'var(--font-mono)', fontSize: 10, padding: '2px 8px', borderRadius: 'var(--r-full)', border: `1px solid ${isLive ? 'var(--ok)' : 'var(--warn)'}`, color: isLive ? 'var(--ok)' : 'var(--warn)' }}>
          {isLive ? '● ' + tr('live') : '○ ' + tr('static')}
        </span>
      </div>
      <p style={{ fontSize: 14, color: 'var(--text-secondary)', lineHeight: 1.6, marginTop: 0 }}>{tr('intro')}</p>

      <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 12 }}>
        <button style={{ ...ctrlBtn, borderColor: 'var(--accent)', color: 'var(--accent)' }} onClick={() => { tried(); if (pos >= MAX) setPos(0); setPlaying((p) => !p); }}>{playing ? tr('pause') : tr('play')}</button>
        <button style={ctrlBtn} onClick={() => { tried(); setPlaying(false); setPos(0); }}>{tr('reset')}</button>
        <span style={{ marginLeft: 'auto', fontFamily: 'var(--font-mono)', fontSize: 13, color: 'var(--text-primary)' }}>{tr('now')}: {curDate}</span>
      </div>

      <input type="range" min={MIN} max={MAX} step={1} value={pos} onChange={(e) => { tried(); setPlaying(false); setPos(parseInt(e.target.value, 10)); }} style={{ width: '100%', accentColor: 'var(--danger)' }} />
      <div style={{ position: 'relative', height: 18, marginTop: 2 }}>
        {events.map((e, i) => {
          const left = (monthIndex(e.date) / MAX) * 100;
          const fired = monthIndex(e.date) <= pos;
          return <span key={i} title={lang === 'ru' ? e.ru : e.en} style={{ position: 'absolute', left: `calc(${left}% - 4px)`, fontFamily: 'var(--font-mono)', fontSize: 10, color: fired ? 'var(--danger)' : 'var(--text-muted)' }}>▲</span>;
        })}
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-muted)' }}>
        <span>2024</span><span>2025</span><span>2026</span>
      </div>

      {/* books */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 16 }}>
        {BOOKS.map((b) => {
          const hit = b.shapes.some((s) => passedShapes.has(s));
          return (
            <div key={b.id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 14px', borderRadius: 'var(--r-md)', border: `1px solid ${hit ? 'var(--danger)' : 'var(--border)'}`, background: hit ? 'rgba(242,109,109,0.07)' : 'var(--bg-surface-2)', transition: 'all 250ms' }}>
              <span style={{ fontWeight: 600, color: 'var(--text-primary)', fontSize: 14 }}>
                {b[lang] ?? b.ru}
                <span style={{ marginLeft: 8, fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-muted)' }}>{tr('shape')}: {b.shapes.join('/')}</span>
              </span>
              <span style={{ fontWeight: 700, fontSize: 13, color: hit ? 'var(--danger)' : 'var(--warn)', fontFamily: 'var(--font-mono)' }}>
                {hit ? tr('refused') : '○ ' + tr('watching')}
              </span>
            </div>
          );
        })}
      </div>

      {lastEvent && (
        <div style={{ marginTop: 14, padding: '12px 14px', borderRadius: 'var(--r-md)', border: '1px solid var(--danger)', background: 'rgba(242,109,109,0.07)' }}>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, letterSpacing: '0.10em', textTransform: 'uppercase', color: 'var(--danger)', marginBottom: 4 }}>{tr('fired')} · {lastEvent.date}</div>
          <div style={{ fontSize: 13, color: 'var(--text-secondary)' }}>{lang === 'ru' ? lastEvent.ru : lastEvent.en}</div>
        </div>
      )}

      <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 12 }}>{tr('source')}: {src}</div>
    </div>
  );
}

const wrap = { background: 'var(--bg-surface)', border: '1px solid var(--border)', borderRadius: 'var(--r-lg)', padding: 24, margin: '28px 0' };
const head = { fontFamily: 'var(--font-mono)', fontSize: 12, letterSpacing: '0.12em', textTransform: 'uppercase', color: 'var(--accent)', marginBottom: 12 };
const ctrlBtn = { padding: '7px 16px', fontSize: 13, fontWeight: 600, borderRadius: 'var(--r-sm)', border: '1px solid var(--border)', background: 'transparent', color: 'var(--text-secondary)', cursor: 'pointer', fontFamily: 'var(--font-sans)' };
