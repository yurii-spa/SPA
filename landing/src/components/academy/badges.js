/*
 * badges.js — milestone badge definitions + an honest, deterministic awarder.
 *
 * Each badge has an `earned(ctx)` predicate evaluated against REAL progress
 * (the done-map + meta), so a badge can never be displayed without the
 * underlying milestone genuinely met. No badge is independently persisted —
 * "earned" is recomputed from progress every render (spoof-proof).
 *
 * ctx = { progress, meta, gameState, modules } where:
 *   progress  : { moduleId: true }              (done map)
 *   meta      : { quizFirstTry, studyDates, playground, name }
 *   gameState : output of getGameState (xp, level, streak, masteryByTrack, …)
 *   modules   : the manifest module list (for track membership)
 *
 * RU-first labels; emoji glyphs kept tasteful + monochrome-friendly.
 */

// Playground widget ids — the full interactive roster (the "all tried" badge).
// Kept in sync with the academy widgets; if any is absent the badge simply waits.
// First four are the original drills; the last four are the new sandbox sims.
export const PLAYGROUND_WIDGETS = [
  'RiskClassifier',
  'HaircutVetoSim',
  'KillSwitchLadder',
  'EdgeAtScaleSlider',
  'PortfolioBuilder',
  'DepegEventPlayer',
  'RefusalGateWalkthrough',
  'RefusalTimeline',
];

// The four newer sandbox sims — earn a dedicated "Песочница пройдена" badge.
export const SANDBOX_WIDGETS = [
  'PortfolioBuilder',
  'DepegEventPlayer',
  'RefusalGateWalkthrough',
  'RefusalTimeline',
];

function trackIds(modules, track) {
  return modules.filter((m) => m.track === track).map((m) => m.id);
}
function allDone(progress, ids) {
  return ids.length > 0 && ids.every((id) => progress[id] === true);
}

export const BADGES = [
  {
    id: 'defi-basics',
    glyph: '🧱',
    title_ru: 'DeFi-основы пройдены',
    title_en: 'DeFi fundamentals done',
    desc_ru: 'Весь трек 1 — база DeFi от нуля.',
    earned: ({ progress, modules }) => allDone(progress, trackIds(modules, 1)),
  },
  {
    id: 'refusal-first',
    glyph: '🛡️',
    title_ru: 'Понял refusal-first',
    title_en: 'Got refusal-first',
    desc_ru: 'Модуль про отказ ДО экономики пройден.',
    earned: ({ progress }) => progress['11-refusal-first'] === true,
  },
  {
    id: 'haircut-veto',
    glyph: '✂️',
    title_ru: 'Вето хейркатом',
    title_en: 'Haircut veto',
    desc_ru: 'Токсичность нельзя обойти размером — усвоено.',
    earned: ({ progress }) => progress['12-structural-haircut-veto'] === true,
  },
  {
    id: 'edge-at-scale',
    glyph: '📉',
    title_ru: 'Прошёл edge-at-scale',
    title_en: 'Edge-at-scale done',
    desc_ru: 'Обрыв $1M и честная кривая масштаба.',
    earned: ({ progress }) => progress['15-edge-at-scale'] === true,
  },
  {
    id: 'spa-track',
    glyph: '🧩',
    title_ru: 'Изобретения SPA пройдены',
    title_en: 'SPA inventions done',
    desc_ru: 'Весь трек 2 — refusal-first, вето, kill-switch, edge.',
    earned: ({ progress, modules }) => allDone(progress, trackIds(modules, 2)),
  },
  {
    id: 'all-playground',
    glyph: '🎛️',
    title_ru: 'Все тренажёры опробованы',
    title_en: 'All playgrounds tried',
    desc_ru: 'Каждый интерактивный виджет был запущен хотя бы раз.',
    earned: ({ meta }) => PLAYGROUND_WIDGETS.every((w) => meta.playground[w] === true),
  },
  {
    id: 'sandbox-complete',
    glyph: '🧪',
    title_ru: 'Песочница пройдена',
    title_en: 'Sandbox complete',
    desc_ru: 'Все четыре симулятора-песочницы (книга, депег, прогон через гейт, таймлайн отказов) опробованы.',
    desc_en: 'All four sandbox sims (book builder, depeg, gate walkthrough, refusal timeline) tried.',
    earned: ({ meta }) => SANDBOX_WIDGETS.every((w) => meta.playground[w] === true),
  },
  {
    id: 'streak-3',
    glyph: '🔥',
    title_ru: 'Серия 3 дня',
    title_en: '3-day streak',
    desc_ru: 'Учился три календарных дня подряд.',
    earned: ({ gameState }) => (gameState?.streak?.longest || 0) >= 3,
  },
  {
    id: 'streak-7',
    glyph: '🔥🔥',
    title_ru: 'Серия 7 дней',
    title_en: '7-day streak',
    desc_ru: 'Неделя занятий без пропусков.',
    earned: ({ gameState }) => (gameState?.streak?.longest || 0) >= 7,
  },
  {
    id: 'capstone',
    glyph: '🎓',
    title_ru: 'Сдал capstone',
    title_en: 'Capstone passed',
    desc_ru: 'Финальный разбор реальной возможности через refusal-first.',
    // Honest: only the real capstone-done flag awards this.
    earned: ({ progress }) => progress['capstone'] === true,
  },
];

/** Return [{...badge, earned:bool}] for the given context. */
export function evaluateBadges(ctx) {
  return BADGES.map((b) => {
    let earned = false;
    try { earned = !!b.earned(ctx); } catch { earned = false; }
    return { ...b, earned };
  });
}

/** Count earned badges. */
export function earnedCount(ctx) {
  return evaluateBadges(ctx).filter((b) => b.earned).length;
}
