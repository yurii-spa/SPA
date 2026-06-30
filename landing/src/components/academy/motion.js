/*
 * motion.js — SPA Академия shared motion utilities (RU-first, accessibility-first).
 *
 * The single source of motion for the academy. Lightweight, stdlib-JS only (no deps).
 * Everything degrades to NO motion when the user prefers reduced motion — in that
 * mode content is shown immediately and fully (counters jump to final value,
 * reveals are visible, charts draw instantly with no path animation).
 *
 * PUBLIC API (Agents B + C reuse these directly — no extra wiring needed):
 *
 *   import { initMotion, prefersReducedMotion, revealOnScroll, countUp, observeInView }
 *     from './motion.js';
 *
 *   - initMotion()                 — auto-wires every [data-reveal] and [data-countup]
 *                                    element on the page. Idempotent; safe to call once
 *                                    per island/layout. SSR-safe (no-op on server).
 *   - prefersReducedMotion()       — boolean; honor it before any bespoke animation.
 *   - revealOnScroll(el, opts?)    — make ONE element fade/slide in when scrolled into
 *                                    view. opts: { y=14, dur=400, delay=0 }.
 *   - countUp(el, to, opts?)       — animate a number from 0→`to` when scrolled into
 *                                    view. opts: { dur=1100, decimals, prefix, suffix,
 *                                    format(fn) }. Reduced-motion → sets final immediately.
 *   - observeInView(el, cb, opts?) — low-level: fire `cb(el)` ONCE when `el` enters the
 *                                    viewport. Returns an unobserve fn. Reduced-motion →
 *                                    fires `cb` synchronously. (AnimatedChart/B/C use this
 *                                    to trigger their own draw-in.)
 *
 * The CSS that powers [data-reveal] lives in MotionStyles.astro (loaded once globally by
 * the academy LessonLayout). React widgets that want reveal/draw-in can just call
 * observeInView / countUp from a useEffect.
 */

const REDUCE_QUERY = '(prefers-reduced-motion: reduce)';

/** SSR-safe reduced-motion check. */
export function prefersReducedMotion() {
  if (typeof window === 'undefined' || !window.matchMedia) return false;
  try {
    return window.matchMedia(REDUCE_QUERY).matches;
  } catch {
    return false;
  }
}

const supportsIO =
  typeof window !== 'undefined' && 'IntersectionObserver' in window;

/**
 * Fire `cb(el)` exactly once when `el` scrolls into view.
 * Reduced-motion OR no-IntersectionObserver → fire immediately (full content, no wait).
 * Returns an unobserve() fn (no-op when fired synchronously).
 */
export function observeInView(el, cb, opts = {}) {
  if (!el || typeof cb !== 'function') return () => {};
  if (prefersReducedMotion() || !supportsIO) {
    cb(el);
    return () => {};
  }
  const io = new IntersectionObserver(
    (entries, obs) => {
      for (const entry of entries) {
        if (entry.isIntersecting) {
          obs.unobserve(entry.target);
          cb(entry.target);
        }
      }
    },
    { threshold: opts.threshold ?? 0.15, rootMargin: opts.rootMargin ?? '0px 0px -8% 0px' }
  );
  io.observe(el);
  return () => io.disconnect();
}

/**
 * Reveal ONE element (fade + slight upward slide) when scrolled into view.
 * Adds the `.in` class which MotionStyles.astro transitions. Reduced-motion → reveal now.
 */
export function revealOnScroll(el, opts = {}) {
  if (!el) return;
  if (prefersReducedMotion() || !supportsIO) {
    el.classList.add('in');
    el.style.removeProperty('transition-delay');
    return;
  }
  if (opts.y != null) el.style.setProperty('--reveal-y', `${opts.y}px`);
  if (opts.dur != null) el.style.setProperty('--reveal-dur', `${opts.dur}ms`);
  if (opts.delay) el.style.transitionDelay = `${opts.delay}ms`;
  observeInView(el, (t) => t.classList.add('in'), { threshold: opts.threshold });
}

const easeOutCubic = (t) => 1 - Math.pow(1 - t, 3);

function parseTargetFromAttr(el) {
  // data-countup="12.85" or read the element's own text content as the number
  const attr = el.getAttribute('data-countup');
  const raw = attr && attr.trim() !== '' ? attr : el.textContent;
  const n = parseFloat(String(raw).replace(/[^0-9.+-]/g, ''));
  return Number.isFinite(n) ? n : null;
}

/**
 * Count a number up from 0 → `to` when scrolled into view.
 * opts: { dur=1100, decimals, prefix='', suffix='', from=0, format(value)->string }.
 * Honors reduced-motion: writes the final value immediately, no animation.
 */
export function countUp(el, to, opts = {}) {
  if (!el || !Number.isFinite(to)) return;
  const decimals =
    opts.decimals != null
      ? opts.decimals
      : (String(to).split('.')[1] || '').length;
  const prefix = opts.prefix ?? '';
  const suffix = opts.suffix ?? '';
  const from = opts.from ?? 0;
  const fmt =
    typeof opts.format === 'function'
      ? opts.format
      : (v) => prefix + v.toFixed(decimals) + suffix;

  const write = (v) => {
    el.textContent = fmt(v);
  };

  if (prefersReducedMotion() || !supportsIO) {
    write(to);
    return;
  }

  observeInView(el, () => {
    const dur = opts.dur ?? 1100;
    const start = performance.now();
    const step = (now) => {
      const p = Math.min(1, (now - start) / dur);
      write(from + (to - from) * easeOutCubic(p));
      if (p < 1) requestAnimationFrame(step);
      else write(to);
    };
    requestAnimationFrame(step);
  });
}

/**
 * Auto-wire the page:
 *   - every [data-reveal]  → revealOnScroll (optional data-reveal-delay ms,
 *                            data-reveal-y px)
 *   - every [data-countup] → countUp to the attr/text value (optional
 *                            data-countup-prefix / -suffix / -decimals)
 * Idempotent per element (marks data-motion-wired). SSR-safe.
 */
export function initMotion(root) {
  if (typeof document === 'undefined') return;
  const scope = root || document;

  scope.querySelectorAll('[data-reveal]').forEach((el) => {
    if (el.getAttribute('data-motion-wired') === '1') return;
    el.setAttribute('data-motion-wired', '1');
    revealOnScroll(el, {
      delay: parseFloat(el.getAttribute('data-reveal-delay')) || 0,
      y: el.hasAttribute('data-reveal-y') ? parseFloat(el.getAttribute('data-reveal-y')) : undefined,
    });
  });

  scope.querySelectorAll('[data-countup]').forEach((el) => {
    if (el.getAttribute('data-motion-wired') === '1') return;
    const to = parseTargetFromAttr(el);
    if (to == null) return;
    el.setAttribute('data-motion-wired', '1');
    countUp(el, to, {
      prefix: el.getAttribute('data-countup-prefix') ?? '',
      suffix: el.getAttribute('data-countup-suffix') ?? '',
      decimals: el.hasAttribute('data-countup-decimals')
        ? parseInt(el.getAttribute('data-countup-decimals'), 10)
        : undefined,
    });
  });
}
