import { useState, useEffect } from 'react';
import { getProgress, getGameState, onProgressChange, getLang, isDone } from './progress.js';

/*
 * JourneyMap.jsx — the academy home dashboard: a visual LEARNING PATH.
 *
 *   - Rank / level / XP / streak / overall mastery header (prominent, game-like).
 *   - Per-track node rail: one node per module, connecting line, done-nodes lit,
 *     the CURRENT (next-undone) node highlighted + pulsing.
 *   - "Продолжить" CTA jumps straight to the next undone module.
 *   - Free navigation: every node is a link (no hard lock), but undone-after-gap
 *     nodes get a subtle "locked-look" so the path reads as a journey.
 *
 * All state is DERIVED from real progress (getGameState) and re-reads on the
 * progress event. RU-first.
 *
 * PROPS:
 *   modules  object[]  manifest module list ({id, track, order, title_ru,...})
 *   tracksMeta object  manifest tracks meta { "1": {title_ru, subtitle_ru}, ... }
 */

const T = {
  rank: { ru: 'Ранг', en: 'Rank' },
  xp: { ru: 'XP', en: 'XP' },
  toNext: { ru: 'до следующего ранга', en: 'to next rank' },
  maxRank: { ru: 'максимальный ранг', en: 'max rank' },
  streak: { ru: 'серия', en: 'streak' },
  days: { ru: 'дн.', en: 'd' },
  mastery: { ru: 'освоение', en: 'mastery' },
  continue: { ru: 'Продолжить', en: 'Continue' },
  start: { ru: 'Начать путь', en: 'Start the path' },
  allDone: { ru: 'Весь курс пройден', en: 'Whole course complete' },
  cert: { ru: 'Открыть сертификат', en: 'Open certificate' },
  track: { ru: 'ТРЕК', en: 'TRACK' },
  done: { ru: 'пройдено', en: 'done' },
};

const TRACK_COLOR = { 1: 'var(--data-teal)', 2: 'var(--accent)', 3: 'var(--warn)' };

export default function JourneyMap({ modules = [], tracksMeta = {} }) {
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

  const ordered = [...modules].sort((a, b) => a.order - b.order);
  const allIds = ordered.map((m) => m.id);
  const tracksIds = { 1: [], 2: [], 3: [] };
  ordered.forEach((m) => { if (tracksIds[m.track]) tracksIds[m.track].push(m.id); });

  const gs = getGameState(allIds, tracksIds);
  const progress = getProgress();
  const nextUndone = ordered.find((m) => progress[m.id] !== true);
  const allComplete = !nextUndone;

  const lvl = gs.level;
  const nextMin = lvl.next ? lvl.next.min : null;
  const span = nextMin !== null ? nextMin - lvl.min : 1;
  const into = gs.xp - lvl.min;
  const lvlPct = nextMin !== null ? Math.min(100, Math.round((into / span) * 100)) : 100;

  const grouped = [1, 2, 3].map((t) => ({
    t,
    meta: tracksMeta[String(t)] || {},
    mods: ordered.filter((m) => m.track === t),
  }));

  return (
    <div style={{ width: '100%' }}>
      {/* ── Game header ───────────────────────────────────────────── */}
      <div style={hdr}>
        <div style={hdrRank}>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, letterSpacing: '0.14em', textTransform: 'uppercase', color: 'var(--text-faint)' }}>{tr('rank')}</div>
          <div style={{ fontSize: '1.5rem', fontWeight: 800, color: 'var(--text-primary)', lineHeight: 1.1, marginTop: 4 }}>
            {lang === 'en' ? lvl.title_en : lvl.title_ru}
          </div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--text-muted)', marginTop: 6 }}>
            {tr('xp')} {gs.xp}{nextMin !== null ? ` · ${nextMin - gs.xp} ${tr('toNext')}` : ` · ${tr('maxRank')}`}
          </div>
          <div style={lvlBarOuter}>
            <div style={{ ...lvlBarInner, width: lvlPct + '%' }} />
          </div>
        </div>

        <div style={statRow}>
          <div style={stat}>
            <div style={statNum}><span aria-hidden="true" style={{ color: 'var(--warn)', marginRight: 4 }}>≡</span>{gs.streak.current}</div>
            <div style={statLbl}>{tr('streak')} ({tr('days')})</div>
          </div>
          <div style={stat}>
            <div style={statNum}>{gs.overallMastery}%</div>
            <div style={statLbl}>{tr('mastery')}</div>
          </div>
          <div style={stat}>
            <div style={statNum}>{gs.done}/{gs.total}</div>
            <div style={statLbl}>{tr('done')}</div>
          </div>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 8, justifyContent: 'center' }}>
          {allComplete ? (
            <>
              <div style={{ fontWeight: 700, color: 'var(--ok)' }}>{tr('allDone')}</div>
              <a href="/academy/certificate" style={ctaPrimary}>{tr('cert')} →</a>
            </>
          ) : (
            <a href={`/academy/${nextUndone.id}`} style={ctaPrimary}>
              {gs.done === 0 ? tr('start') : tr('continue')} →
              <span style={{ display: 'block', fontSize: 12, fontWeight: 400, opacity: 0.85, marginTop: 2 }}>
                {String(nextUndone.order).padStart(2, '0')} · {nextUndone.title_ru}
              </span>
            </a>
          )}
        </div>
      </div>

      {/* ── Track rails ───────────────────────────────────────────── */}
      {grouped.map((g) => {
        const color = TRACK_COLOR[g.t];
        const tDone = g.mods.filter((m) => progress[m.id] === true).length;
        return (
          <section key={g.t} style={{ marginTop: 36 }}>
            <div style={{ borderLeft: `3px solid ${color}`, paddingLeft: 14, marginBottom: 18 }}>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: 12, letterSpacing: '0.12em', color }}>{tr('track')} {g.t} · {tDone}/{g.mods.length}</div>
              <div style={{ fontSize: '1.3rem', fontWeight: 700, color: 'var(--text-primary)', marginTop: 4 }}>{g.meta.title_ru}</div>
              <div style={{ fontSize: 14, color: 'var(--text-secondary)', marginTop: 2 }}>{g.meta.subtitle_ru}</div>
            </div>

            <ol style={rail}>
              {g.mods.map((m, i) => {
                const done = progress[m.id] === true;
                const isCurrent = nextUndone && m.id === nextUndone.id;
                // "ahead" look: undone and there's an earlier undone in the global order
                const aheadOfCurrent = nextUndone && m.order > nextUndone.order && !done;
                const nodeColor = done ? color : isCurrent ? 'var(--accent)' : 'var(--border-strong)';
                return (
                  <li key={m.id} style={railItem}>
                    {i < g.mods.length - 1 && (
                      <span style={{ ...connector, background: done ? color : 'var(--border)' }} aria-hidden="true" />
                    )}
                    <a href={`/academy/${m.id}`} style={{ ...nodeLink, opacity: aheadOfCurrent ? 0.62 : 1 }}>
                      <span style={{
                        ...node,
                        borderColor: nodeColor,
                        background: done ? color : isCurrent ? 'var(--accent-bg)' : 'var(--bg-surface-2)',
                        color: done ? 'var(--bg-base)' : isCurrent ? 'var(--accent)' : 'var(--text-muted)',
                        boxShadow: isCurrent ? '0 0 0 4px var(--accent-bg)' : 'none',
                        animation: isCurrent ? 'pulse 2s infinite' : 'none',
                      }}>
                        {done ? '✓' : String(m.order).padStart(2, '0')}
                      </span>
                      <span style={nodeBody}>
                        <span style={{ fontSize: 14, fontWeight: 600, color: done || isCurrent ? 'var(--text-primary)' : 'var(--text-secondary)', lineHeight: 1.3 }}>
                          {m.title_ru}
                        </span>
                        {m.widget && <span style={widgetTag}>интерактив</span>}
                        {isCurrent && <span style={{ ...widgetTag, borderColor: 'var(--accent)', color: 'var(--accent)' }}>текущий</span>}
                      </span>
                    </a>
                  </li>
                );
              })}
            </ol>
          </section>
        );
      })}
    </div>
  );
}

const hdr = { display: 'grid', gridTemplateColumns: 'minmax(220px,1.2fr) auto minmax(200px,1fr)', gap: 24, alignItems: 'stretch', background: 'var(--bg-surface)', border: '1px solid var(--border)', borderRadius: 'var(--r-xl)', padding: 24 };
const hdrRank = { display: 'flex', flexDirection: 'column' };
const lvlBarOuter = { marginTop: 12, height: 8, borderRadius: 'var(--r-full)', background: 'var(--bg-surface-2)', border: '1px solid var(--border)', overflow: 'hidden' };
const lvlBarInner = { height: '100%', background: 'linear-gradient(90deg, var(--accent), var(--data-teal))', transition: 'width 400ms var(--ease)' };
const statRow = { display: 'flex', gap: 18, alignItems: 'center' };
const stat = { textAlign: 'center', minWidth: 64 };
const statNum = { fontSize: '1.35rem', fontWeight: 800, color: 'var(--text-primary)', fontFamily: 'var(--font-mono)' };
const statLbl = { fontSize: 11, color: 'var(--text-muted)', marginTop: 3, fontFamily: 'var(--font-mono)', letterSpacing: '0.04em' };
const ctaPrimary = { background: 'var(--accent)', color: '#fff', textDecoration: 'none', borderRadius: 'var(--r-md)', padding: '14px 22px', fontWeight: 700, fontSize: 15, boxShadow: 'var(--shadow-cta)', textAlign: 'center', lineHeight: 1.2 };

const rail = { listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: 4 };
const railItem = { position: 'relative', paddingLeft: 0 };
const connector = { position: 'absolute', left: 19, top: 40, width: 2, height: 'calc(100% - 36px)', zIndex: 0 };
const nodeLink = { display: 'flex', alignItems: 'center', gap: 14, textDecoration: 'none', padding: '6px 0', position: 'relative', zIndex: 1 };
const node = { flex: '0 0 auto', width: 40, height: 40, borderRadius: '50%', border: '2px solid', display: 'flex', alignItems: 'center', justifyContent: 'center', fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: 14 };
const nodeBody = { display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' };
const widgetTag = { fontFamily: 'var(--font-mono)', fontSize: 10, letterSpacing: '0.06em', textTransform: 'uppercase', padding: '2px 8px', borderRadius: 'var(--r-full)', border: '1px solid var(--data-teal)', color: 'var(--data-teal)' };
