/*
 * progress.js — SPA Академия localStorage progress utility (RU-first).
 *
 * Single source of truth for per-module completion + portal-wide %.
 * localStorage key: `spa_academy_progress` → JSON { "<moduleId>": true, ... }.
 *
 * Pure, dependency-free, SSR-safe (guards `typeof window`). Used by Quiz.jsx,
 * ModuleProgress.jsx, LessonLayout chrome, and the /academy index.
 */

export const STORAGE_KEY = 'spa_academy_progress';

/** Read the raw progress map { moduleId: true }. SSR-safe, fail-soft to {}. */
export function getProgress() {
  if (typeof window === 'undefined') return {};
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch {
    return {};
  }
}

/** Is a single module marked done? */
export function isDone(moduleId) {
  if (!moduleId) return false;
  return getProgress()[moduleId] === true;
}

/** Mark a module done (idempotent). Dispatches a `spa-academy-progress` event so
 *  any mounted island (progress bar, index cards) re-reads without a reload. */
export function markDone(moduleId) {
  if (typeof window === 'undefined' || !moduleId) return;
  try {
    const p = getProgress();
    if (p[moduleId] === true) return;
    p[moduleId] = true;
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(p));
    window.dispatchEvent(new CustomEvent('spa-academy-progress', { detail: { moduleId } }));
    // Completing a module counts as studying today (streak). Defined below; guard
    // for definition order since markDone may be called from other modules.
    try { recordStudyDay(); } catch { /* recordStudyDay defined later in this module */ }
  } catch {
    /* fail-soft: progress is a convenience, never blocks the lesson */
  }
}

/** Un-mark a module (used by the "сбросить" reset). */
export function clearDone(moduleId) {
  if (typeof window === 'undefined' || !moduleId) return;
  try {
    const p = getProgress();
    if (!(moduleId in p)) return;
    delete p[moduleId];
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(p));
    window.dispatchEvent(new CustomEvent('spa-academy-progress', { detail: { moduleId } }));
  } catch {
    /* fail-soft */
  }
}

/** Wipe all progress. */
export function resetAll() {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.removeItem(STORAGE_KEY);
    window.dispatchEvent(new CustomEvent('spa-academy-progress', { detail: { reset: true } }));
  } catch {
    /* fail-soft */
  }
}

/** Count done modules out of a provided list of ids. */
export function doneCount(moduleIds) {
  const p = getProgress();
  if (!Array.isArray(moduleIds)) return 0;
  return moduleIds.reduce((n, id) => (p[id] === true ? n + 1 : n), 0);
}

/** Portal-wide percent complete (0–100, integer) over a list of ids. */
export function percentComplete(moduleIds) {
  if (!Array.isArray(moduleIds) || moduleIds.length === 0) return 0;
  return Math.round((doneCount(moduleIds) / moduleIds.length) * 100);
}

/** Subscribe to progress changes (storage events from other tabs + same-tab custom event).
 *  Returns an unsubscribe fn. */
export function onProgressChange(cb) {
  if (typeof window === 'undefined') return () => {};
  const handler = () => cb(getProgress());
  window.addEventListener('storage', handler);
  window.addEventListener('spa-academy-progress', handler);
  return () => {
    window.removeEventListener('storage', handler);
    window.removeEventListener('spa-academy-progress', handler);
  };
}

/** Read the site language (RU-first: default 'ru' for the academy). */
export function getLang() {
  if (typeof window === 'undefined') return 'ru';
  try {
    const v = window.localStorage.getItem('spa_lang');
    if (v === 'en') return 'en';
    return 'ru'; // academy default = RU
  } catch {
    return 'ru';
  }
}

/* ===========================================================================
 * GAMIFICATION LAYER (XP · levels · streaks · badges · certificate name)
 *
 * Design honesty / red-team-safe:
 *   - XP is DERIVED deterministically from real progress, never stored as a
 *     spoofable counter. capstone XP exists IFF progress['capstone'] === true.
 *   - The only *extra* persisted facts are: quiz first-try passes, the set of
 *     study dates (for streaks), playground-tried flags, and the analyst's name.
 *     None of these can fabricate a "capstone passed" — that lives in the
 *     module-done map and is awarded only by Quiz.jsx on a real pass.
 *   - No leaderboard / no "other analysts" — single-user self-progress only.
 *
 * Stored under a SEPARATE key (`spa_academy_meta`) so the original done-map
 * (`spa_academy_progress`) keeps its exact shape for existing islands.
 * ======================================================================== */

export const META_KEY = 'spa_academy_meta';

/* XP economy (deterministic) */
export const XP_PER_MODULE = 100;      // any module marked done
export const XP_QUIZ_FIRST_TRY = 50;   // bonus: quiz passed with no wrong answers, first attempt
export const XP_CAPSTONE_BONUS = 500;  // big bonus, only on real capstone completion
export const XP_PLAYGROUND_TRIED = 25; // per playground widget tried (engagement)

/* Level ladder — XP thresholds → rank (RU-first labels). */
export const LEVELS = [
  { level: 1, min: 0,    title_ru: 'Новичок',            title_en: 'Beginner' },
  { level: 2, min: 200,  title_ru: 'Стажёр',             title_en: 'Trainee' },
  { level: 3, min: 600,  title_ru: 'Аналитик',           title_en: 'Analyst' },
  { level: 4, min: 1200, title_ru: 'Старший аналитик',   title_en: 'Senior Analyst' },
  { level: 5, min: 2000, title_ru: 'Структурный андеррайтер', title_en: 'Structural Underwriter' },
];

function todayKey(d = new Date()) {
  // Local-date YYYY-MM-DD (streaks are about calendar days the analyst studied).
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

/** Read the raw meta object. SSR-safe, fail-soft. */
export function getMeta() {
  if (typeof window === 'undefined') return { quizFirstTry: {}, studyDates: [], playground: {}, name: '' };
  try {
    const raw = window.localStorage.getItem(META_KEY);
    const parsed = raw ? JSON.parse(raw) : null;
    const m = parsed && typeof parsed === 'object' ? parsed : {};
    return {
      quizFirstTry: m.quizFirstTry && typeof m.quizFirstTry === 'object' ? m.quizFirstTry : {},
      studyDates: Array.isArray(m.studyDates) ? m.studyDates : [],
      playground: m.playground && typeof m.playground === 'object' ? m.playground : {},
      name: typeof m.name === 'string' ? m.name : '',
    };
  } catch {
    return { quizFirstTry: {}, studyDates: [], playground: {}, name: '' };
  }
}

function saveMeta(m, detail = {}) {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(META_KEY, JSON.stringify(m));
    window.dispatchEvent(new CustomEvent('spa-academy-progress', { detail }));
  } catch {
    /* fail-soft */
  }
}

/** Record that today is a study day (call on any meaningful interaction). Idempotent per day. */
export function recordStudyDay() {
  if (typeof window === 'undefined') return;
  const m = getMeta();
  const t = todayKey();
  if (m.studyDates.includes(t)) return;
  m.studyDates = [...m.studyDates, t].sort();
  saveMeta(m, { studyDay: t });
}

/** Record a quiz pass; firstTry=true awards the no-wrong-answer bonus (idempotent per module). */
export function recordQuizPass(moduleId, firstTry) {
  if (typeof window === 'undefined' || !moduleId) return;
  const m = getMeta();
  // Once first-try is earned it sticks; a later retry can't downgrade, but can't
  // upgrade a non-first-try pass into first-try either.
  if (m.quizFirstTry[moduleId] === undefined) {
    m.quizFirstTry[moduleId] = !!firstTry;
    saveMeta(m, { quizFirstTry: moduleId });
  }
  recordStudyDay();
}

/** Mark a playground widget as tried (engagement XP + the "all tried" badge). */
export function recordPlaygroundTried(widgetId) {
  if (typeof window === 'undefined' || !widgetId) return;
  const m = getMeta();
  if (m.playground[widgetId] === true) return;
  m.playground[widgetId] = true;
  saveMeta(m, { playground: widgetId });
  recordStudyDay();
}

/** Analyst display name for the certificate (localStorage). */
export function getAnalystName() { return getMeta().name || ''; }
export function setAnalystName(name) {
  if (typeof window === 'undefined') return;
  const m = getMeta();
  m.name = String(name || '').slice(0, 80);
  saveMeta(m, { name: true });
}

/** Current consecutive-day streak ending today (or yesterday — grace so it
 *  doesn't read 0 first thing the next morning). Returns { current, longest }. */
export function getStreak() {
  const dates = getMeta().studyDates;
  if (!dates.length) return { current: 0, longest: 0 };
  const set = new Set(dates);
  // longest run anywhere
  let longest = 0;
  for (const d of dates) {
    // only count run-starts (no previous day) to avoid O(n^2) blowup on dupes
    const prev = addDays(d, -1);
    if (set.has(prev)) continue;
    let len = 1, cur = d;
    while (set.has(addDays(cur, 1))) { len++; cur = addDays(cur, 1); }
    if (len > longest) longest = len;
  }
  // current run: must include today or yesterday
  const today = todayKey();
  const yest = addDays(today, -1);
  let anchor = set.has(today) ? today : set.has(yest) ? yest : null;
  let current = 0;
  if (anchor) {
    current = 1;
    let cur = anchor;
    while (set.has(addDays(cur, -1))) { current++; cur = addDays(cur, -1); }
  }
  return { current, longest };
}

function addDays(key, delta) {
  const [y, m, d] = key.split('-').map(Number);
  const dt = new Date(y, m - 1, d);
  dt.setDate(dt.getDate() + delta);
  return todayKey(dt);
}

/** Total XP — fully derived from real progress (cannot be spoofed independently). */
export function getXP(moduleIds) {
  const p = getProgress();
  const meta = getMeta();
  const ids = Array.isArray(moduleIds) ? moduleIds : Object.keys(p);
  let xp = 0;
  for (const id of ids) {
    if (p[id] !== true) continue;
    xp += XP_PER_MODULE;
    if (meta.quizFirstTry[id] === true) xp += XP_QUIZ_FIRST_TRY;
    if (id === 'capstone') xp += XP_CAPSTONE_BONUS; // ONLY when capstone genuinely done
  }
  for (const w of Object.keys(meta.playground)) {
    if (meta.playground[w] === true) xp += XP_PLAYGROUND_TRIED;
  }
  return xp;
}

/** Resolve XP → { level, title_ru, title_en, min, next } (next = XP threshold of next level or null). */
export function getLevel(xp) {
  let cur = LEVELS[0];
  for (const l of LEVELS) if (xp >= l.min) cur = l;
  const idx = LEVELS.indexOf(cur);
  const next = idx < LEVELS.length - 1 ? LEVELS[idx + 1] : null;
  return { ...cur, next };
}

/** Per-track mastery % (0–100) over the modules in that track. */
export function trackMastery(moduleIds) {
  return percentComplete(moduleIds);
}

/** Whether the capstone (final exam) is genuinely passed. Single source of truth. */
export function isCapstonePassed() {
  return isDone('capstone');
}

/** Convenience: full gamification snapshot for UI islands. */
export function getGameState(allIds, tracks) {
  const xp = getXP(allIds);
  const level = getLevel(xp);
  const streak = getStreak();
  const meta = getMeta();
  const masteryByTrack = {};
  if (tracks && typeof tracks === 'object') {
    for (const [t, ids] of Object.entries(tracks)) masteryByTrack[t] = percentComplete(ids);
  }
  return {
    xp, level, streak,
    overallMastery: percentComplete(allIds),
    masteryByTrack,
    done: doneCount(allIds),
    total: Array.isArray(allIds) ? allIds.length : 0,
    quizFirstTry: meta.quizFirstTry,
    playground: meta.playground,
    name: meta.name,
    capstonePassed: isCapstonePassed(),
  };
}

/** Wipe gamification meta too (used by the full reset). */
export function resetMeta() {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.removeItem(META_KEY);
    window.dispatchEvent(new CustomEvent('spa-academy-progress', { detail: { reset: true } }));
  } catch { /* fail-soft */ }
}
