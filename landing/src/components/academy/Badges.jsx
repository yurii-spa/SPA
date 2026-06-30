import { useState, useEffect } from 'react';
import { getProgress, getMeta, getGameState, onProgressChange, getLang } from './progress.js';
import { evaluateBadges } from './badges.js';

/*
 * Badges.jsx — celebratory badge shelf island.
 *
 * Reads REAL progress + meta, evaluates each badge predicate live (spoof-proof:
 * "earned" is derived, never stored). Re-renders on the `spa-academy-progress`
 * event so a badge lights up the instant its milestone is met.
 *
 * PROPS:
 *   allIds   string[]   full module id list (from manifest)
 *   modules  object[]   manifest module list (track membership for predicates)
 *   tracks   object     { "1":[ids], "2":[ids], "3":[ids] } for mastery (optional)
 *   compact  bool       smaller chips (used inline on the journey); default false
 */

const T = {
  heading: { ru: 'Награды', en: 'Badges' },
  earned: { ru: 'получено', en: 'earned' },
  locked: { ru: 'ещё не получено', en: 'not yet earned' },
};

export default function Badges({ allIds = [], modules = [], tracks = null, compact = false }) {
  const [lang, setLang] = useState('ru');
  const [, force] = useState(0);

  useEffect(() => {
    setLang(getLang());
    const off = onProgressChange(() => force((n) => n + 1));
    const obs = new MutationObserver(() => setLang(getLang()));
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ['lang'] });
    const onLang = () => setLang(getLang());
    window.addEventListener('storage', onLang);
    return () => { off(); obs.disconnect(); window.removeEventListener('storage', onLang); };
  }, []);

  const tr = (k) => (T[k] ? (T[k][lang] ?? T[k].ru) : k);

  const ctx = {
    progress: getProgress(),
    meta: getMeta(),
    gameState: getGameState(allIds, tracks),
    modules,
  };
  const badges = evaluateBadges(ctx);
  const nEarned = badges.filter((b) => b.earned).length;

  return (
    <div style={{ width: '100%' }}>
      {!compact && (
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 14 }}>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, letterSpacing: '0.12em', textTransform: 'uppercase', color: 'var(--accent)' }}>
            {tr('heading')}
          </span>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 13, color: 'var(--text-secondary)' }}>
            {nEarned} / {badges.length}
          </span>
        </div>
      )}
      <div style={{
        display: 'grid',
        gridTemplateColumns: compact ? 'repeat(auto-fill, minmax(120px,1fr))' : 'repeat(auto-fill, minmax(168px,1fr))',
        gap: compact ? 8 : 12,
      }}>
        {badges.map((b) => (
          <div key={b.id} title={b.earned ? `${b.title_ru} — ${b.desc_ru}` : tr('locked')}
            style={{
              display: 'flex', flexDirection: 'column', gap: 6,
              padding: compact ? '10px 12px' : '14px 14px',
              borderRadius: 'var(--r-md)',
              border: `1px solid ${b.earned ? 'var(--accent)' : 'var(--border)'}`,
              background: b.earned ? 'var(--accent-bg)' : 'var(--bg-surface-2)',
              opacity: b.earned ? 1 : 0.5,
              filter: b.earned ? 'none' : 'grayscale(0.8)',
              transition: 'opacity 200ms, border-color 200ms',
            }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ fontSize: compact ? 18 : 22, lineHeight: 1 }} aria-hidden="true">{b.glyph}</span>
              {b.earned && (
                <span style={{ marginLeft: 'auto', fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--ok)' }}>✓</span>
              )}
            </div>
            <div style={{ fontSize: compact ? 12 : 13, fontWeight: 600, color: b.earned ? 'var(--text-primary)' : 'var(--text-muted)', lineHeight: 1.3 }}>
              {lang === 'en' ? b.title_en : b.title_ru}
            </div>
            {!compact && (
              <div style={{ fontSize: 11, color: 'var(--text-muted)', lineHeight: 1.4 }}>{b.desc_ru}</div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
