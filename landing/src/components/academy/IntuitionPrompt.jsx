import { useState, useEffect } from 'react';
import { getLang, recordStudyDay } from './progress.js';

/*
 * IntuitionPrompt.jsx — "guess before the reveal" micro-mechanic island.
 *
 * Teaches by prediction: ask the analyst to GUESS a number / pick a side, then
 * reveal the real answer with how close they were. Two modes:
 *   - numeric: a slider/number guess vs `answer` (with `unit`, optional `min/max`)
 *   - choice : pick one of `options`; `correctIndex` is the truth.
 *
 * No grading penalty — guessing is always "right" to engage; the reveal teaches.
 * Marks today as a study day on reveal. RU-first.
 *
 * Driven by IntuitionPrompt.astro (preferred authoring surface).
 */

const T = {
  guess: { ru: 'Угадай', en: 'Guess' },
  reveal: { ru: 'Показать ответ', en: 'Reveal' },
  yourGuess: { ru: 'Твоя догадка', en: 'Your guess' },
  actual: { ru: 'На самом деле', en: 'Actual' },
  close: { ru: 'Близко!', en: 'Close!' },
  off: { ru: 'Мимо — но теперь запомнишь', en: 'Off — but now it sticks' },
  spotOn: { ru: 'В точку!', en: 'Spot on!' },
  again: { ru: 'Ещё раз', en: 'Try again' },
};

export default function IntuitionPrompt({
  question_ru, question_en,
  mode = 'numeric',
  answer, unit = '', min = 0, max = 100, step = 0.1,
  options = [], correctIndex = 0,
  explain_ru = '', explain_en = '',
}) {
  const [lang, setLang] = useState('ru');
  const [val, setVal] = useState(typeof answer === 'number' ? (min + max) / 2 : 0);
  const [pick, setPick] = useState(null);
  const [revealed, setRevealed] = useState(false);

  useEffect(() => {
    setLang(getLang());
    const obs = new MutationObserver(() => setLang(getLang()));
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ['lang'] });
    const onLang = () => setLang(getLang());
    window.addEventListener('storage', onLang);
    return () => { obs.disconnect(); window.removeEventListener('storage', onLang); };
  }, []);

  const tr = (k) => (T[k] ? (T[k][lang] ?? T[k].ru) : k);
  const q = lang === 'en' ? (question_en || question_ru) : question_ru;
  const explain = lang === 'en' ? (explain_en || explain_ru) : explain_ru;

  function doReveal() {
    setRevealed(true);
    recordStudyDay();
  }
  function reset() { setRevealed(false); setPick(null); }

  // Numeric closeness band (within 15% of the span).
  let verdict = '', verdictColor = 'var(--text-secondary)';
  if (revealed && mode === 'numeric') {
    const span = Math.max(1e-9, max - min);
    const err = Math.abs(val - answer) / span;
    if (err < 0.04) { verdict = tr('spotOn'); verdictColor = 'var(--ok)'; }
    else if (err < 0.15) { verdict = tr('close'); verdictColor = 'var(--data-teal)'; }
    else { verdict = tr('off'); verdictColor = 'var(--warn)'; }
  }
  if (revealed && mode === 'choice') {
    if (pick === correctIndex) { verdict = tr('spotOn'); verdictColor = 'var(--ok)'; }
    else { verdict = tr('off'); verdictColor = 'var(--warn)'; }
  }

  return (
    <div style={wrap}>
      <div style={head}>{tr('guess')} 🤔</div>
      <div style={{ fontWeight: 600, color: 'var(--text-primary)', marginBottom: 16, lineHeight: 1.5 }}>{q}</div>

      {mode === 'numeric' && (
        <div style={{ marginBottom: 14 }}>
          <input type="range" min={min} max={max} step={step} value={val}
            disabled={revealed}
            onChange={(e) => setVal(parseFloat(e.target.value))}
            style={{ width: '100%', accentColor: 'var(--accent)' }} />
          <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: 'var(--font-mono)', fontSize: 13, color: 'var(--text-secondary)', marginTop: 6 }}>
            <span>{tr('yourGuess')}: <strong style={{ color: 'var(--text-primary)' }}>{val}{unit}</strong></span>
          </div>
        </div>
      )}

      {mode === 'choice' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 14 }}>
          {options.map((opt, i) => {
            const sel = pick === i;
            let bd = sel ? 'var(--accent)' : 'var(--border)';
            let bg = 'var(--bg-surface-2)';
            if (revealed) {
              if (i === correctIndex) { bd = 'var(--ok)'; bg = 'rgba(52,211,153,0.10)'; }
              else if (sel) { bd = 'var(--danger)'; bg = 'rgba(242,109,109,0.10)'; }
            }
            return (
              <button key={i} disabled={revealed} onClick={() => setPick(i)}
                style={{ textAlign: 'left', padding: '11px 14px', borderRadius: 'var(--r-md)', border: `1px solid ${bd}`, background: bg, color: 'var(--text-secondary)', cursor: revealed ? 'default' : 'pointer', fontSize: 14.5, fontFamily: 'var(--font-sans)' }}>
                {lang === 'en' ? (opt.en ?? opt.ru ?? opt) : (opt.ru ?? opt.en ?? opt)}
              </button>
            );
          })}
        </div>
      )}

      {!revealed ? (
        <button style={{ ...btn, opacity: (mode === 'choice' && pick === null) ? 0.5 : 1 }}
          disabled={mode === 'choice' && pick === null} onClick={doReveal}>{tr('reveal')}</button>
      ) : (
        <div style={{ marginTop: 4, padding: '14px', borderRadius: 'var(--r-md)', background: 'var(--bg-surface-2)', border: '1px solid var(--border)' }}>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, flexWrap: 'wrap', marginBottom: explain ? 8 : 0 }}>
            <span style={{ fontWeight: 700, color: verdictColor }}>{verdict}</span>
            {mode === 'numeric' && (
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 14, color: 'var(--text-secondary)' }}>
                {tr('actual')}: <strong style={{ color: 'var(--text-primary)' }}>{answer}{unit}</strong>
              </span>
            )}
          </div>
          {explain && <div style={{ fontSize: 14, color: 'var(--text-secondary)', lineHeight: 1.55 }}>{explain}</div>}
          <button style={{ ...btnGhost, marginTop: 12 }} onClick={reset}>{tr('again')}</button>
        </div>
      )}
    </div>
  );
}

const wrap = { background: 'var(--bg-surface)', border: '1px solid var(--border)', borderRadius: 'var(--r-lg)', padding: 22, marginTop: 24, marginBottom: 24 };
const head = { fontFamily: 'var(--font-mono)', fontSize: 12, letterSpacing: '0.12em', textTransform: 'uppercase', color: 'var(--data-teal)', marginBottom: 14 };
const btn = { background: 'var(--accent)', color: '#fff', border: 'none', borderRadius: 'var(--r-sm)', padding: '10px 22px', fontSize: 14, fontWeight: 600, cursor: 'pointer', fontFamily: 'var(--font-sans)' };
const btnGhost = { background: 'transparent', color: 'var(--text-secondary)', border: '1px solid var(--border)', borderRadius: 'var(--r-sm)', padding: '8px 16px', fontSize: 13, cursor: 'pointer', fontFamily: 'var(--font-sans)' };
