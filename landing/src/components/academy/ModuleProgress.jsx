import { useState, useEffect } from 'react';
import { percentComplete, doneCount, onProgressChange, isDone, getLang } from './progress.js';

/*
 * ModuleProgress.jsx — the portal-wide progress bar island.
 *
 * Two render modes (one component, controlled by props):
 *   - bar (default): a % progress bar over ALL modules (used on the /academy index).
 *   - badge:         a small "пройдено ✓" / "не пройдено" badge for ONE module
 *                    (used in LessonLayout chrome) when `moduleId` is set.
 *
 * PROPS:
 *   moduleIds  string[]  for the bar — the full list of module ids (from the manifest).
 *   moduleId   string    for the badge — a single module slug.
 *   label_ru   string    optional bar label override.
 */

const T = {
  progress: { ru: 'Прогресс', en: 'Progress' },
  modules: { ru: 'модулей', en: 'modules' },
  done: { ru: 'пройдено', en: 'completed' },
  doneBadge: { ru: 'Пройдено ✓', en: 'Completed ✓' },
  notDone: { ru: 'Не пройдено', en: 'Not completed' },
};

export default function ModuleProgress({ moduleIds, moduleId, label_ru }) {
  const [lang, setLang] = useState('ru');
  const [, force] = useState(0);

  useEffect(() => {
    setLang(getLang());
    const off = onProgressChange(() => force((n) => n + 1));
    const onLang = () => setLang(getLang());
    window.addEventListener('storage', onLang);
    const obs = new MutationObserver(() => setLang(getLang()));
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ['lang'] });
    return () => { off(); window.removeEventListener('storage', onLang); obs.disconnect(); };
  }, []);

  const tr = (k) => (T[k] ? (T[k][lang] ?? T[k].ru) : k);

  // Badge mode (single module)
  if (moduleId) {
    const done = isDone(moduleId);
    return (
      <span style={{
        display: 'inline-flex', alignItems: 'center', gap: 6,
        fontFamily: 'var(--font-mono)', fontSize: 11, padding: '4px 10px',
        borderRadius: 'var(--r-full)',
        border: `1px solid ${done ? 'var(--ok)' : 'var(--border)'}`,
        color: done ? 'var(--ok)' : 'var(--text-muted)',
        background: done ? 'rgba(52,211,153,0.08)' : 'transparent',
      }}>
        {done ? tr('doneBadge') : tr('notDone')}
      </span>
    );
  }

  // Bar mode (whole portal)
  const ids = Array.isArray(moduleIds) ? moduleIds : [];
  const pct = percentComplete(ids);
  const n = doneCount(ids);

  return (
    <div style={{ width: '100%' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 8 }}>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, letterSpacing: '0.08em', textTransform: 'uppercase', color: 'var(--text-faint)' }}>
          {label_ru && lang === 'ru' ? label_ru : tr('progress')}
        </span>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 13, color: 'var(--text-secondary)' }}>
          {n} / {ids.length} {tr('done')} · {pct}%
        </span>
      </div>
      <div style={{ height: 10, borderRadius: 'var(--r-full)', background: 'var(--bg-surface-2)', border: '1px solid var(--border)', overflow: 'hidden' }}>
        <div style={{
          width: pct + '%', height: '100%',
          background: 'linear-gradient(90deg, var(--accent), var(--data-teal))',
          transition: 'width 400ms cubic-bezier(.4,0,.2,1)',
        }} />
      </div>
    </div>
  );
}
