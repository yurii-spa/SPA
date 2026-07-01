import { useState, useEffect } from 'react';
import { markDone, isDone, getLang, recordQuizPass } from './progress.js';
import { fireCelebration } from './celebrate.js';

/*
 * Quiz.jsx — the interactive island behind Quiz.astro. Multiple-choice, instant
 * check + explanation, marks the module complete in localStorage on a pass.
 *
 * Imported via Quiz.astro (which auto-derives moduleId). Agents 1+2 should use
 * Quiz.astro, not this island directly.
 *
 * QUESTION SCHEMA (RU-first plain strings):
 *   { q: string, options: string[], correct: number (index), explanation: string }
 * It also tolerates a bilingual richer form ({ q_ru, q_en, options:[{ru,en,correct}], explain_ru }).
 *
 * PROPS:
 *   moduleId  string   the localStorage completion key (auto-derived by Quiz.astro).
 *   questions Array    the questions (schema above).
 *   passAll   bool     require ALL correct to mark done (default true).
 *
 * Honesty: completion only fires after the learner actually answers per `passAll`.
 */

const T = {
  heading: { ru: 'Проверка знаний', en: 'Knowledge check' },
  check: { ru: 'Проверить', en: 'Check' },
  correct: { ru: 'Верно', en: 'Correct' },
  wrong: { ru: 'Неверно', en: 'Incorrect' },
  next: { ru: 'Следующий вопрос', en: 'Next question' },
  finish: { ru: 'Завершить', en: 'Finish' },
  done: { ru: 'Модуль пройден ✓', en: 'Module complete ✓' },
  partial: { ru: 'Квиз завершён', en: 'Quiz finished' },
  retry: { ru: 'Пройти заново', en: 'Retry' },
  progress: { ru: 'Вопрос', en: 'Question' },
  of: { ru: 'из', en: 'of' },
  alreadyDone: { ru: 'Этот модуль уже отмечен пройденным.', en: 'This module is already marked complete.' },
};

// Normalize either schema into { text, options:[{text, correct}], explain }.
function normalize(q, lang) {
  const text = q.q ?? q.q_ru ?? q.q_en ?? '';
  let options;
  if (Array.isArray(q.options) && q.options.length && typeof q.options[0] === 'object') {
    // bilingual object form
    options = q.options.map((o) => ({ text: o[lang] ?? o.ru ?? o.en ?? '', correct: !!o.correct }));
  } else {
    // plain-string form with a `correct` index
    options = (q.options || []).map((o, i) => ({ text: String(o), correct: i === q.correct }));
  }
  const explain = q.explanation ?? q.explain_ru ?? q.explain_en ?? '';
  return { text, options, explain };
}

export default function Quiz({ moduleId, questions = [], passAll = true }) {
  const [lang, setLang] = useState('ru');
  const [idx, setIdx] = useState(0);
  const [picked, setPicked] = useState(null);
  const [checked, setChecked] = useState(false);
  const [correctCount, setCorrectCount] = useState(0);
  const [wrongCount, setWrongCount] = useState(0);
  const [finished, setFinished] = useState(false);
  const [alreadyDone, setAlreadyDone] = useState(false);

  useEffect(() => {
    setLang(getLang());
    setAlreadyDone(isDone(moduleId));
    const onLang = () => setLang(getLang());
    window.addEventListener('storage', onLang);
    const obs = new MutationObserver(() => setLang(getLang()));
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ['lang'] });
    return () => { window.removeEventListener('storage', onLang); obs.disconnect(); };
  }, [moduleId]);

  const tr = (k) => (T[k] ? (T[k][lang] ?? T[k].ru) : k);

  if (!Array.isArray(questions) || questions.length === 0) return null;

  const total = questions.length;
  const cur = normalize(questions[idx], lang);

  function onCheck() {
    if (picked === null || checked) return;
    setChecked(true);
    if (cur.options[picked]?.correct) setCorrectCount((c) => c + 1);
    else setWrongCount((w) => w + 1);
  }

  function onNext() {
    const last = idx === total - 1;
    if (!last) { setIdx((i) => i + 1); setPicked(null); setChecked(false); return; }
    setFinished(true);
    const pass = passAll ? correctCount === total : true;
    if (pass) {
      const wasDone = isDone(moduleId);
      markDone(moduleId);
      setAlreadyDone(true);
      // First-try = passed AND never picked a wrong answer this run.
      recordQuizPass(moduleId, wrongCount === 0);
      // Celebrate a genuinely new completion (capstone gets the big burst).
      if (!wasDone) {
        const isCapstone = moduleId === 'capstone';
        fireCelebration({
          big: isCapstone,
          message: isCapstone
            ? (lang === 'en' ? 'Capstone passed' : 'Капстоун сдан')
            : (lang === 'en' ? 'Module complete' : 'Модуль пройден'),
        });
      }
    }
  }

  function onRetry() { setIdx(0); setPicked(null); setChecked(false); setCorrectCount(0); setWrongCount(0); setFinished(false); }

  const ok = 'var(--ok)', danger = 'var(--danger)', accent = 'var(--accent)';

  if (finished) {
    const passed = passAll ? correctCount === total : true;
    return (
      <div style={wrap}>
        <div style={head}>{tr('heading')}</div>
        <div style={{ ...resultBox, borderColor: passed ? ok : 'var(--border-strong)' }}>
          <div style={{ fontSize: 28, fontWeight: 700, color: passed ? ok : 'var(--text-primary)' }}>{correctCount} / {total}</div>
          <div style={{ marginTop: 8, color: passed ? ok : 'var(--text-secondary)', fontWeight: 600 }}>{passed ? tr('done') : tr('partial')}</div>
          <button style={{ ...btn, marginTop: 16 }} onClick={onRetry}>{tr('retry')}</button>
        </div>
      </div>
    );
  }

  const isCorrect = checked && picked !== null && cur.options[picked]?.correct;

  return (
    <div style={wrap}>
      <div style={head}>
        {tr('heading')}
        <span style={{ float: 'right', fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--text-muted)' }}>
          {tr('progress')} {idx + 1} {tr('of')} {total}
        </span>
      </div>
      {alreadyDone && <div style={{ fontSize: 12, color: 'var(--ok)', marginBottom: 10 }}>{tr('alreadyDone')}</div>}
      <div style={{ fontWeight: 600, color: 'var(--text-primary)', marginBottom: 14, lineHeight: 1.5 }}>{cur.text}</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {cur.options.map((opt, i) => {
          const selected = picked === i;
          let bg = 'var(--bg-surface-2)', bd = 'var(--border)';
          if (checked) {
            if (opt.correct) { bg = 'rgba(52,211,153,0.10)'; bd = ok; }
            else if (selected) { bg = 'rgba(242,109,109,0.10)'; bd = danger; }
          } else if (selected) { bd = accent; }
          return (
            <button key={i} onClick={() => !checked && setPicked(i)} disabled={checked}
              style={{ textAlign: 'left', padding: '12px 14px', borderRadius: 'var(--r-md)', border: `1px solid ${bd}`, background: bg, color: 'var(--text-secondary)', cursor: checked ? 'default' : 'pointer', fontSize: 15, lineHeight: 1.45, fontFamily: 'var(--font-sans)', transition: 'border-color 120ms, background 120ms' }}>
              {opt.text}
            </button>
          );
        })}
      </div>

      {checked && (
        <div style={{ marginTop: 14, padding: '12px 14px', borderRadius: 'var(--r-md)', background: isCorrect ? 'rgba(52,211,153,0.08)' : 'rgba(242,179,60,0.08)', border: `1px solid ${isCorrect ? ok : 'var(--warn)'}` }}>
          <div style={{ fontWeight: 700, color: isCorrect ? ok : 'var(--warn)', marginBottom: 6 }}>{isCorrect ? tr('correct') : tr('wrong')}</div>
          <div style={{ fontSize: 14, color: 'var(--text-secondary)', lineHeight: 1.55 }}>{cur.explain}</div>
        </div>
      )}

      <div style={{ marginTop: 16 }}>
        {!checked ? (
          <button style={{ ...btn, opacity: picked === null ? 0.5 : 1 }} disabled={picked === null} onClick={onCheck}>{tr('check')}</button>
        ) : (
          <button style={btn} onClick={onNext}>{idx === total - 1 ? tr('finish') : tr('next')}</button>
        )}
      </div>
    </div>
  );
}

const wrap = { background: 'var(--bg-surface)', border: '1px solid var(--border)', borderRadius: 'var(--r-lg)', padding: 24, marginTop: 32 };
const head = { fontFamily: 'var(--font-mono)', fontSize: 12, letterSpacing: '0.12em', textTransform: 'uppercase', color: 'var(--accent)', marginBottom: 16 };
const btn = { background: 'var(--accent)', color: '#fff', border: 'none', borderRadius: 'var(--r-sm)', padding: '10px 22px', fontSize: 14, fontWeight: 600, cursor: 'pointer', fontFamily: 'var(--font-sans)' };
const resultBox = { textAlign: 'center', padding: '28px 20px', border: '1px solid var(--border-strong)', borderRadius: 'var(--r-md)', background: 'var(--bg-surface-2)' };
