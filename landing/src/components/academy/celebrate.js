/*
 * celebrate.js — tasteful, self-contained celebration burst for the academy.
 *
 * Used on module/quiz completion and capstone pass. Pure DOM + requestAnimationFrame,
 * no dependencies. Respects prefers-reduced-motion: in that mode it skips the
 * confetti and shows a calm, static reveal badge instead (still rewarding, no motion).
 *
 * SSR-safe (no-op when window is absent). One overlay at a time; auto-cleans up.
 *
 * NOTE: this is owned by the gamification agent and does NOT touch Agent A's
 * motion utils / LessonLayout. If Agent A later ships a shared motion util, this
 * can be swapped, but it intentionally has zero import dependency on it.
 */

const PALETTE = ['#5B8DEF', '#36C2B4', '#34D399', '#F2B53C', '#79A4F5'];

function prefersReducedMotion() {
  try {
    return window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  } catch {
    return false;
  }
}

function makeOverlay() {
  const el = document.createElement('div');
  el.setAttribute('data-spa-celebrate', '1');
  el.setAttribute('aria-hidden', 'true');
  Object.assign(el.style, {
    position: 'fixed', inset: '0', pointerEvents: 'none', zIndex: '9999', overflow: 'hidden',
  });
  document.body.appendChild(el);
  return el;
}

/**
 * Fire a celebration. opts: { message?: string, big?: boolean }.
 * `big` (capstone) → more, longer-lived particles + a centered reveal card.
 */
export function fireCelebration(opts = {}) {
  if (typeof window === 'undefined' || typeof document === 'undefined') return;
  const { message = '', big = false } = opts;

  // Reduced motion: calm static reveal, no particles.
  if (prefersReducedMotion()) {
    if (message) showRevealCard(message, big, /*reduced*/ true);
    return;
  }

  const overlay = makeOverlay();
  const count = big ? 90 : 48;
  const W = window.innerWidth;
  const now = () => performance.now();
  const start = now();
  const duration = big ? 2600 : 1800;

  const particles = [];
  for (let i = 0; i < count; i++) {
    const p = document.createElement('div');
    const size = 6 + Math.random() * 6;
    Object.assign(p.style, {
      position: 'absolute',
      top: '-12px',
      left: `${Math.random() * W}px`,
      width: `${size}px`,
      height: `${size * (0.6 + Math.random() * 0.8)}px`,
      background: PALETTE[i % PALETTE.length],
      borderRadius: Math.random() > 0.5 ? '2px' : '50%',
      opacity: '0',
      willChange: 'transform, opacity',
    });
    overlay.appendChild(p);
    particles.push({
      el: p,
      x: parseFloat(p.style.left),
      vx: (Math.random() - 0.5) * 0.18,
      vy: 0.18 + Math.random() * 0.22,
      rot: Math.random() * 360,
      vrot: (Math.random() - 0.5) * 8,
      delay: Math.random() * (big ? 600 : 300),
    });
  }

  if (message) showRevealCard(message, big, false);

  function frame() {
    const t = now() - start;
    for (const pt of particles) {
      const local = t - pt.delay;
      if (local < 0) continue;
      const y = pt.vy * local * 0.5;
      pt.x += pt.vx * 16;
      pt.rot += pt.vrot;
      const life = Math.min(1, local / duration);
      pt.el.style.opacity = String(local < 200 ? local / 200 : 1 - life);
      pt.el.style.transform = `translate(${pt.x - parseFloat(pt.el.style.left)}px, ${y}px) rotate(${pt.rot}deg)`;
    }
    if (t < duration + 200) {
      requestAnimationFrame(frame);
    } else {
      overlay.remove();
    }
  }
  requestAnimationFrame(frame);
}

function showRevealCard(message, big, reduced) {
  const card = document.createElement('div');
  card.setAttribute('data-spa-celebrate-card', '1');
  card.setAttribute('role', 'status');
  card.textContent = message;
  Object.assign(card.style, {
    position: 'fixed',
    left: '50%',
    top: big ? '38%' : '22%',
    transform: 'translate(-50%,-50%)',
    background: 'var(--bg-elevated, #1E232C)',
    border: '1px solid var(--accent, #5B8DEF)',
    color: 'var(--text-primary, #E8EAF0)',
    fontFamily: 'var(--font-sans, sans-serif)',
    fontWeight: '700',
    fontSize: big ? '1.25rem' : '1.05rem',
    padding: big ? '18px 28px' : '14px 22px',
    borderRadius: '16px',
    boxShadow: '0 12px 40px rgba(0,0,0,.55)',
    zIndex: '10000',
    pointerEvents: 'none',
    textAlign: 'center',
    maxWidth: '88vw',
    opacity: reduced ? '1' : '0',
  });
  document.body.appendChild(card);

  if (reduced) {
    setTimeout(() => card.remove(), 2400);
    return;
  }
  // fade in/out without CSS transitions (reduced-motion global rule kills transitions)
  const start = performance.now();
  const inMs = 220, holdMs = big ? 1900 : 1300, outMs = 360;
  function anim() {
    const t = performance.now() - start;
    let o = 1;
    if (t < inMs) o = t / inMs;
    else if (t > inMs + holdMs) o = Math.max(0, 1 - (t - inMs - holdMs) / outMs);
    card.style.opacity = String(o);
    const scale = t < inMs ? 0.92 + 0.08 * (t / inMs) : 1;
    card.style.transform = `translate(-50%,-50%) scale(${scale})`;
    if (t < inMs + holdMs + outMs) requestAnimationFrame(anim);
    else card.remove();
  }
  requestAnimationFrame(anim);
}
