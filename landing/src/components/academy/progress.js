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
