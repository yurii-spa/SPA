/*
 * api.js — shared client for the Academy: Real-Money Onboarding sub-app.
 *
 * The onboarding API is a SEPARATE FastAPI sub-app (own CORS, own credentialed
 * cookie). In production it is mounted at `/academy` on api.earn-defi.com; in
 * local dev it is served standalone on port 8801 (routes at root). We fold the
 * mount point INTO the base so every call site uses the same bare paths
 * (`/auth/login`, `/progress`, `/verify/3`, …) and they resolve correctly in
 * both environments.
 *
 * SECURITY CONTRACT (must not regress):
 *   - Every request is credentialed (`credentials: 'include'`) so the HttpOnly
 *     `academy_session` cookie round-trips. Cookie path is "/".
 *   - The per-session CSRF token is returned in the login/register BODY and kept
 *     ONLY in React state (never localStorage / cookie / window). It is passed
 *     into `apiSend(..., { csrf })` and echoed as the `X-CSRF-Token` header on
 *     every mutating (POST/PUT) request — the backend's double-submit check.
 *   - Fail-CLOSED / graceful-degraded: helpers surface a typed error object with
 *     a `.status` so the UI can distinguish 401 (auth) / 5xx (offline) / other,
 *     and never fabricate progress.
 */

const isLocal =
  typeof window !== 'undefined' &&
  (window.location.hostname === 'localhost' ||
    window.location.hostname === '127.0.0.1');

// Base already includes the prod mount point. Dev = standalone sub-app on 8801.
export const ACADEMY_API = isLocal
  ? 'http://localhost:8801'
  : 'https://api.earn-defi.com/academy';

export const FETCH_TIMEOUT_MS = 10000;

/** Error carrying the HTTP status (0 = network/offline) plus a parsed detail. */
export class ApiError extends Error {
  constructor(status, detail, message) {
    super(message || detail || `HTTP ${status}`);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
  }
  get isAuth() {
    return this.status === 401 || this.status === 403;
  }
  get isOffline() {
    // 0 = fetch threw (network / CORS / timeout); 5xx = server down/erroring.
    return this.status === 0 || this.status >= 500;
  }
}

function timeoutSignal() {
  // AbortSignal.timeout isn't universal on older Safari — fall back gracefully.
  try {
    return AbortSignal.timeout(FETCH_TIMEOUT_MS);
  } catch {
    return undefined;
  }
}

async function parseBody(res) {
  const ct = res.headers.get('content-type') || '';
  if (ct.includes('application/json')) {
    try {
      return await res.json();
    } catch {
      return null;
    }
  }
  return null;
}

async function run(path, options) {
  let res;
  try {
    res = await fetch(ACADEMY_API + path, {
      credentials: 'include',
      signal: timeoutSignal(),
      ...options,
    });
  } catch (e) {
    // Network failure / CORS / timeout → treat as offline (status 0).
    throw new ApiError(0, String(e && e.message ? e.message : e));
  }
  const body = await parseBody(res);
  if (!res.ok) {
    const detail =
      (body && (body.detail || body.message)) || `HTTP ${res.status}`;
    throw new ApiError(res.status, detail);
  }
  return body;
}

/** GET a JSON endpoint (credentialed). Throws ApiError on any non-2xx. */
export function apiGet(path) {
  return run(path, { method: 'GET', headers: { Accept: 'application/json' } });
}

/**
 * Mutating request (POST/PUT). Injects the CSRF token header when supplied.
 * @param {string} path
 * @param {object} opts { method='POST', body?, csrf? }
 */
export function apiSend(path, { method = 'POST', body, csrf } = {}) {
  const headers = { Accept: 'application/json' };
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (csrf) headers['X-CSRF-Token'] = csrf;
  return run(path, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
}

/* ── i18n: reuse the academy RU-first language reader ─────────────────────── */
export function getLang() {
  if (typeof window === 'undefined') return 'ru';
  try {
    const v = window.localStorage.getItem('spa_lang');
    return v === 'en' ? 'en' : 'ru';
  } catch {
    return 'ru';
  }
}

/** Subscribe to language changes (storage + <html lang> mutations). */
export function onLangChange(cb) {
  if (typeof window === 'undefined') return () => {};
  const handler = () => cb(getLang());
  window.addEventListener('storage', handler);
  const obs = new MutationObserver(handler);
  try {
    obs.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['lang'],
    });
  } catch {
    /* no-op */
  }
  return () => {
    window.removeEventListener('storage', handler);
    obs.disconnect();
  };
}

/* ── shared module presentation metadata ──────────────────────────────────── */
export const STATUS_META = {
  not_started: { icon: '🔒', tone: 'muted', ru: 'не начат', en: 'not started' },
  in_progress: { icon: '⏳', tone: 'warn', ru: 'в процессе', en: 'in progress' },
  submitted: { icon: '⏳', tone: 'warn', ru: 'на проверке', en: 'submitted' },
  failed: { icon: '⚠️', tone: 'danger', ru: 'не пройдено', en: 'failed' },
  verified: { icon: '✅', tone: 'ok', ru: 'подтверждён', en: 'verified' },
};

export const TONE_COLOR = {
  muted: 'var(--text-muted)',
  warn: 'var(--warn)',
  danger: 'var(--danger)',
  ok: 'var(--ok)',
};

/** basescan / sepolia.basescan explorer URL for a tx on a given chain. */
export function explorerTxUrl(tx, chain) {
  if (!tx) return null;
  if (chain === 'base_sepolia') return `https://sepolia.basescan.org/tx/${tx}`;
  return `https://basescan.org/tx/${tx}`;
}
