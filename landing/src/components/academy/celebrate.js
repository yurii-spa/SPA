/*
 * celebrate.js — institutional completion acknowledgement for the academy.
 *
 * REPLACES the earlier falling-confetti burst (consumer-gamification, off-brand for an
 * institutional-rigor desk) with a calm, senior micro-interaction: a centered reveal
 * card with the academy's own geometric glyph (◆), a hairline accent frame, and a brief
 * scale/opacity settle. NO particles, NO emoji. The gamification (XP/badges/rank) is
 * untouched — this only retone the moment of completion.
 *
 * Motion: a single 120/200/400ms settle on the reveal card (spec §3.5 easing). Honors
 * prefers-reduced-motion — in that mode the card appears statically (no transform, no
 * fade), still acknowledging the milestone. SSR-safe; one card at a time; auto-cleans up.
 *
 * Keeps the SAME exported API (fireCelebration({ message, big })) so callers are unchanged.
 */

function prefersReducedMotion() {
  try {
    return window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  } catch {
    return false;
  }
}

/**
 * Acknowledge a completion. opts: { message?: string, big?: boolean }.
 * `big` (capstone) → slightly larger card + longer hold. No particles in either mode.
 */
export function fireCelebration(opts = {}) {
  if (typeof window === 'undefined' || typeof document === 'undefined') return;
  const { message = '', big = false } = opts;
  showRevealCard(message, big, prefersReducedMotion());
}

function showRevealCard(message, big, reduced) {
  // Remove any prior card (one at a time).
  document.querySelectorAll('[data-spa-celebrate-card]').forEach((n) => n.remove());

  const card = document.createElement('div');
  card.setAttribute('data-spa-celebrate-card', '1');
  card.setAttribute('role', 'status');
  card.setAttribute('aria-live', 'polite');

  const glyph = document.createElement('div');
  glyph.setAttribute('aria-hidden', 'true');
  glyph.textContent = '◆';
  Object.assign(glyph.style, {
    fontFamily: 'var(--font-mono, monospace)',
    fontSize: big ? '1.5rem' : '1.25rem',
    color: 'var(--accent, #5B8DEF)',
    lineHeight: '1',
    marginBottom: '10px',
  });

  const label = document.createElement('div');
  label.textContent = message || '';
  Object.assign(label.style, {
    fontFamily: 'var(--font-sans, sans-serif)',
    fontWeight: '600',
    fontSize: big ? '1.15rem' : '1rem',
    color: 'var(--text-primary, #E8EAF0)',
    letterSpacing: '-0.01em',
  });

  card.appendChild(glyph);
  if (message) card.appendChild(label);

  Object.assign(card.style, {
    position: 'fixed',
    left: '50%',
    top: big ? '34%' : '20%',
    transform: 'translate(-50%,-50%)',
    background: 'var(--bg-elevated, #1E232C)',
    border: '1px solid var(--accent-border, rgba(91,141,239,0.30))',
    borderRadius: 'var(--r-lg, 16px)',
    padding: big ? '22px 30px' : '18px 24px',
    boxShadow: 'var(--shadow-md, 0 4px 16px rgba(0,0,0,.45))',
    zIndex: '10000',
    pointerEvents: 'none',
    textAlign: 'center',
    maxWidth: '88vw',
    opacity: reduced ? '1' : '0',
  });
  document.body.appendChild(card);

  const holdMs = big ? 1900 : 1400;

  if (reduced) {
    // Static acknowledgement — no motion.
    setTimeout(() => card.remove(), holdMs + 400);
    return;
  }

  // A single settle (opacity + a subtle scale), no particles.
  const start = performance.now();
  const inMs = 200, outMs = 400;
  function anim() {
    const t = performance.now() - start;
    let o = 1;
    if (t < inMs) o = t / inMs;
    else if (t > inMs + holdMs) o = Math.max(0, 1 - (t - inMs - holdMs) / outMs);
    card.style.opacity = String(o);
    const scale = t < inMs ? 0.96 + 0.04 * (t / inMs) : 1;
    card.style.transform = `translate(-50%,-50%) scale(${scale})`;
    if (t < inMs + holdMs + outMs) requestAnimationFrame(anim);
    else card.remove();
  }
  requestAnimationFrame(anim);
}
