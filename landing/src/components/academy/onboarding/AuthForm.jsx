import { useState } from 'react';
import { apiSend, ApiError } from './api.js';

/*
 * AuthForm — inline login / register for the onboarding sub-app.
 *
 * Reused by OnboardingApp (the course hub) AND ModuleRunner (per-page action
 * gate). No redirect: on success it calls onAuthed(csrf_token, user) and the
 * parent swaps to the authenticated view. The CSRF token is handed UP to the
 * parent's React state ONLY — never persisted (localStorage/cookie/window) — per
 * the security contract. Because the SSG site is multi-page and the token is
 * state-only, each page that needs to mutate re-issues one via a quick sign-in;
 * reading (theory, progress) is never blocked by it.
 *
 * Props:
 *   onAuthed(csrf, user)  required — called with the fresh per-session csrf token
 *   lang                  'ru' | 'en'
 *   compact               bool — slim variant used inline on a module's action area
 *   defaultMode           'login' | 'register'
 */

const T = {
  loginTab: { ru: 'Войти', en: 'Sign in' },
  registerTab: { ru: 'Зарегистрироваться', en: 'Register' },
  email: { ru: 'E-mail', en: 'Email' },
  password: { ru: 'Пароль', en: 'Password' },
  invite: { ru: 'Инвайт-код', en: 'Invite code' },
  submitLogin: { ru: 'Войти', en: 'Sign in' },
  submitRegister: { ru: 'Создать аккаунт', en: 'Create account' },
  working: { ru: 'Отправка…', en: 'Working…' },
  inviteHint: {
    ru: 'Онбординг доступен по приглашению. Код выдаёт владелец.',
    en: 'Onboarding is invite-only. The owner issues codes.',
  },
  errInvalid: { ru: 'Неверный e-mail или пароль.', en: 'Invalid email or password.' },
  errDup: { ru: 'Этот e-mail уже зарегистрирован.', en: 'That email is already registered.' },
  errRate: {
    ru: 'Слишком много попыток. Подождите и попробуйте снова.',
    en: 'Too many attempts. Wait a moment and retry.',
  },
  errBad: { ru: 'Проверьте введённые данные.', en: 'Please check your input.' },
  errOffline: {
    ru: 'Сервис онбординга недоступен. Попробуйте позже.',
    en: 'Onboarding service is unavailable. Try again later.',
  },
};

export default function AuthForm({ onAuthed, lang = 'ru', compact = false, defaultMode = 'login' }) {
  const tr = (k) => (T[k] ? T[k][lang] ?? T[k].ru : k);
  const [mode, setMode] = useState(defaultMode === 'register' ? 'register' : 'login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [invite, setInvite] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const messageFor = (e) => {
    if (!(e instanceof ApiError)) return tr('errOffline');
    if (e.isOffline) return tr('errOffline');
    if (e.status === 401) return tr('errInvalid');
    if (e.status === 409) return tr('errDup');
    if (e.status === 429) return tr('errRate');
    return typeof e.detail === 'string' ? e.detail : tr('errBad');
  };

  async function submit(ev) {
    ev.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const path = mode === 'register' ? '/auth/register' : '/auth/login';
      const body =
        mode === 'register'
          ? { email: email.trim(), password, invite_code: invite.trim() }
          : { email: email.trim(), password };
      const res = await apiSend(path, { method: 'POST', body });
      // csrf_token is returned in the BODY; hand it to the parent's state only.
      if (!res || !res.csrf_token) throw new ApiError(0, 'no csrf in response');
      onAuthed(res.csrf_token, res.user || null);
    } catch (e) {
      setError(messageFor(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} style={compact ? wrapCompact : wrap} aria-label="Academy sign in">
      <div style={tabs} role="tablist">
        {['login', 'register'].map((m) => (
          <button
            key={m}
            type="button"
            role="tab"
            aria-selected={mode === m}
            onClick={() => { setMode(m); setError(null); }}
            style={{ ...tab, ...(mode === m ? tabActive : null) }}
          >
            {m === 'login' ? tr('loginTab') : tr('registerTab')}
          </button>
        ))}
      </div>

      <label style={field}>
        <span style={label}>{tr('email')}</span>
        <input
          type="email"
          autoComplete="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          style={input}
        />
      </label>

      <label style={field}>
        <span style={label}>{tr('password')}</span>
        <input
          type="password"
          autoComplete={mode === 'register' ? 'new-password' : 'current-password'}
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          style={input}
        />
      </label>

      {mode === 'register' && (
        <label style={field}>
          <span style={label}>{tr('invite')}</span>
          <input
            type="text"
            required
            value={invite}
            onChange={(e) => setInvite(e.target.value)}
            style={input}
          />
          <span style={hint}>{tr('inviteHint')}</span>
        </label>
      )}

      {error && <div style={errBox} role="alert">{error}</div>}

      <button type="submit" disabled={busy} style={{ ...submitBtn, ...(busy ? btnBusy : null) }}>
        {busy ? tr('working') : mode === 'register' ? tr('submitRegister') : tr('submitLogin')}
      </button>
    </form>
  );
}

/* ── styles (design tokens) ───────────────────────────────────────────────── */
const wrap = {
  display: 'flex', flexDirection: 'column', gap: 14,
  background: 'var(--bg-surface)', border: '1px solid var(--border)',
  borderRadius: 'var(--r-lg)', padding: 24, maxWidth: 420, margin: '0 auto',
};
const wrapCompact = { ...wrap, padding: 18, maxWidth: '100%', margin: 0 };
const tabs = { display: 'flex', gap: 4, background: 'var(--bg-surface-2)', borderRadius: 'var(--r-sm)', padding: 4 };
const tab = {
  flex: 1, padding: '8px 10px', border: 'none', cursor: 'pointer', borderRadius: 'var(--r-sm)',
  background: 'transparent', color: 'var(--text-muted)', fontFamily: 'var(--font-sans)',
  fontSize: 14, fontWeight: 600,
};
const tabActive = { background: 'var(--accent-bg)', color: 'var(--accent)' };
const field = { display: 'flex', flexDirection: 'column', gap: 6 };
const label = { fontSize: 12, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' };
const input = {
  padding: '10px 12px', borderRadius: 'var(--r-sm)', border: '1px solid var(--border-strong)',
  background: 'var(--bg-base)', color: 'var(--text-primary)', fontSize: 15, fontFamily: 'var(--font-sans)',
};
const hint = { fontSize: 12, color: 'var(--text-faint)', lineHeight: 1.4 };
const errBox = {
  padding: '10px 12px', borderRadius: 'var(--r-sm)', border: '1px solid var(--danger-border)',
  background: 'var(--danger-bg)', color: 'var(--danger)', fontSize: 13, lineHeight: 1.45,
};
const submitBtn = {
  padding: '11px 16px', borderRadius: 'var(--r-sm)', border: '1px solid var(--accent-border)',
  background: 'var(--accent-bg)', color: 'var(--accent)', fontSize: 15, fontWeight: 700,
  cursor: 'pointer', fontFamily: 'var(--font-sans)',
};
const btnBusy = { opacity: 0.6, cursor: 'progress' };
