import { useState, useEffect, useCallback } from 'react';
import {
  apiGet, apiSend, ApiError, getLang, onLangChange, STATUS_META, TONE_COLOR,
} from './api.js';
import AuthForm from './AuthForm.jsx';
import manifest from '../../../data/onboarding_modules.json';

/*
 * OnboardingApp — the /academy/onboarding hub island.
 *
 *   loading  → spinner
 *   anon     → inline AuthForm (no redirect) + browsable module list
 *   offline  → honest degraded banner ("progress unavailable, content available")
 *   authed   → CourseMap: 9 module cards with live per-module progress
 *
 * The CSRF token from login/register lives ONLY in this component's state and is
 * passed down to mutating calls. On a fresh page load with an existing session
 * cookie we can still READ progress (GET), so the map renders; a not_started
 * "start" POST is best-effort (skipped when no csrf is held).
 */

const MODULES = manifest.modules;

const T = {
  title: { ru: 'Практика перед реальными деньгами', en: 'Practice before real money' },
  intro: {
    ru: 'Девять модулей: пройди путь кошелёк → сеть → первая транзакция → approvals → депозит и вывод в Aave → инциденты → капстоун. Каждый шаг подтверждается on-chain или подписью. Учебный лимит кошелька ≤ $150.',
    en: 'Nine modules: wallet → network → first transaction → approvals → Aave supply & withdraw → incidents → capstone. Every step is proven on-chain or by signature. Educational wallet limit ≤ $150.',
  },
  signInLead: {
    ru: 'Войдите или зарегистрируйтесь по инвайту, чтобы отслеживать прогресс и отправлять проверки.',
    en: 'Sign in or register with an invite to track progress and submit verifications.',
  },
  browse: { ru: 'Модули курса', en: 'Course modules' },
  browseNote: {
    ru: 'Теорию каждого модуля можно читать без входа. Вход нужен только для проверок и прогресса.',
    en: 'You can read each module’s theory without signing in. Sign-in is only needed for checks and progress.',
  },
  degraded: {
    ru: 'API недоступен — прогресс временно недоступен, контент модулей доступен.',
    en: 'API unavailable — progress is temporarily unavailable, module content is available.',
  },
  loading: { ru: 'Загрузка…', en: 'Loading…' },
  retry: { ru: 'Повторить', en: 'Retry' },
  signedInAs: { ru: 'Вы вошли как', en: 'Signed in as' },
  logout: { ru: 'Выйти', en: 'Sign out' },
  progressLabel: { ru: 'модулей подтверждено', en: 'modules verified' },
  open: { ru: 'Открыть', en: 'Open' },
  actionsNote: {
    ru: 'Прогресс виден, но для отправки проверок войдите заново на странице модуля.',
    en: 'Progress is visible; to submit checks, sign in again on the module page.',
  },
};

function moduleTitle(m, lang) {
  return lang === 'en' ? m.title_en : m.title_ru;
}
function moduleDesc(m, lang) {
  return lang === 'en' ? m.description_en : m.description_ru;
}

export default function OnboardingApp() {
  const [lang, setLang] = useState('ru');
  useEffect(() => { setLang(getLang()); return onLangChange(setLang); }, []);
  const tr = (k) => (T[k] ? T[k][lang] ?? T[k].ru : k);

  // phase: 'loading' | 'anon' | 'authed' | 'offline'
  const [phase, setPhase] = useState('loading');
  const [progress, setProgress] = useState({}); // lesson_id -> status
  const [email, setEmail] = useState(null);
  const [csrf, setCsrf] = useState(null);

  const load = useCallback(async () => {
    setPhase('loading');
    try {
      const res = await apiGet('/progress');
      const map = {};
      (res && res.progress ? res.progress : []).forEach((p) => { map[p.lesson_id] = p.status; });
      setProgress(map);
      setPhase('authed');
      // best-effort email for the account bar
      try {
        const me = await apiGet('/auth/me');
        if (me && me.email) setEmail(me.email);
      } catch { /* non-fatal */ }
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) setPhase('anon');
      else setPhase('offline');
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const onAuthed = useCallback((token, user) => {
    setCsrf(token);
    if (user && user.email) setEmail(user.email);
    load();
  }, [load]);

  async function logout() {
    try { await apiSend('/auth/logout', { method: 'POST', csrf }); } catch { /* ignore */ }
    setCsrf(null); setEmail(null); setProgress({}); setPhase('anon');
  }

  async function openModule(id, status) {
    // Best-effort: mark not_started → in_progress before navigating (needs csrf).
    if (status === 'not_started' && csrf) {
      try {
        await apiSend('/progress', { method: 'POST', body: { lesson_id: id, action: 'start' }, csrf });
      } catch { /* non-fatal — the module page can start it too */ }
    }
    window.location.href = `/academy/onboarding/${id}`;
  }

  if (phase === 'loading') {
    return (
      <div style={centerBox}>
        <div style={spinner} aria-hidden="true" />
        <span style={{ color: 'var(--text-muted)', fontSize: 14 }}>{tr('loading')}</span>
      </div>
    );
  }

  const verifiedCount = MODULES.filter((m) => progress[m.id] === 'verified').length;

  return (
    <div>
      <header style={{ marginBottom: 28 }}>
        <h1 style={h1}>{tr('title')}</h1>
        <p style={lede}>{tr('intro')}</p>
      </header>

      {phase === 'authed' && (
        <div style={accountBar}>
          <span style={{ fontSize: 13, color: 'var(--text-muted)' }}>
            {email ? `${tr('signedInAs')} ` : ''}
            {email && <span style={{ color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)' }}>{email}</span>}
            <span style={{ marginLeft: email ? 12 : 0 }}>
              <strong style={{ color: 'var(--ok)' }}>{verifiedCount}/9</strong> {tr('progressLabel')}
            </span>
          </span>
          <button type="button" onClick={logout} style={ghostBtn}>{tr('logout')}</button>
        </div>
      )}

      {!csrf && phase === 'authed' && (
        <p style={softNote}>{tr('actionsNote')}</p>
      )}

      {phase === 'offline' && (
        <div style={degradedBanner} role="status">
          <span>{tr('degraded')}</span>
          <button type="button" onClick={load} style={ghostBtn}>{tr('retry')}</button>
        </div>
      )}

      {phase === 'anon' && (
        <section style={{ marginBottom: 36 }}>
          <p style={{ ...lede, marginBottom: 18 }}>{tr('signInLead')}</p>
          <AuthForm onAuthed={onAuthed} lang={lang} />
        </section>
      )}

      <section>
        {(phase === 'anon' || phase === 'offline') && (
          <>
            <h2 style={h2}>{tr('browse')}</h2>
            <p style={{ ...softNote, marginTop: 0 }}>{tr('browseNote')}</p>
          </>
        )}
        <div style={grid}>
          {MODULES.map((m) => {
            const status = progress[m.id] || (phase === 'authed' ? 'not_started' : null);
            const meta = status ? STATUS_META[status] : null;
            const clickable = phase === 'authed';
            const inner = (
              <>
                <div style={cardTop}>
                  <span style={cardIndex}>M{m.id}</span>
                  {meta && (
                    <span style={{ ...statusPill, color: TONE_COLOR[meta.tone], borderColor: TONE_COLOR[meta.tone] }}>
                      {meta.icon} {lang === 'en' ? meta.en : meta.ru}
                    </span>
                  )}
                </div>
                <h3 style={cardTitle}>{moduleTitle(m, lang)}</h3>
                <p style={cardDesc}>{moduleDesc(m, lang)}</p>
                <span style={cardCta}>{tr('open')} →</span>
              </>
            );
            return clickable ? (
              <button
                key={m.id}
                type="button"
                onClick={() => openModule(m.id, status)}
                style={{ ...card, textAlign: 'left', cursor: 'pointer' }}
              >
                {inner}
              </button>
            ) : (
              <a key={m.id} href={`/academy/onboarding/${m.id}`} style={card}>
                {inner}
              </a>
            );
          })}
        </div>
      </section>

      {phase === 'authed' && verifiedCount === 9 && (
        <div style={certBanner}>
          <span>{lang === 'en' ? 'All 9 modules verified.' : 'Все 9 модулей подтверждены.'}</span>
          <a href="/academy/onboarding/certificate" style={certLink}>
            {lang === 'en' ? 'View certificate →' : 'Открыть сертификат →'}
          </a>
        </div>
      )}
    </div>
  );
}

/* ── styles ───────────────────────────────────────────────────────────────── */
const h1 = { fontSize: '2.2rem', fontWeight: 700, color: 'var(--text-primary)', margin: '0 0 12px' };
const h2 = { fontSize: '1.3rem', fontWeight: 700, color: 'var(--text-primary)', margin: '0 0 6px' };
const lede = { fontSize: 16, lineHeight: 1.65, color: 'var(--text-secondary)', margin: 0, maxWidth: 760 };
const softNote = { fontSize: 13, color: 'var(--text-muted)', lineHeight: 1.5, margin: '10px 0 16px' };
const centerBox = { display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 14, padding: '80px 0' };
const spinner = {
  width: 32, height: 32, borderRadius: '50%',
  border: '3px solid var(--border)', borderTopColor: 'var(--accent)',
  animation: 'spin 800ms linear infinite',
};
const accountBar = {
  display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap',
  background: 'var(--bg-surface)', border: '1px solid var(--border)', borderRadius: 'var(--r-md)',
  padding: '12px 16px', marginBottom: 20,
};
const ghostBtn = {
  background: 'transparent', border: '1px solid var(--border-strong)', borderRadius: 'var(--r-sm)',
  color: 'var(--text-secondary)', padding: '6px 12px', cursor: 'pointer', fontSize: 13, fontFamily: 'var(--font-sans)',
};
const degradedBanner = {
  display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap',
  background: 'var(--warn-bg)', border: '1px solid var(--warn-border)', borderRadius: 'var(--r-md)',
  color: 'var(--warn)', padding: '12px 16px', marginBottom: 24, fontSize: 14, lineHeight: 1.5,
};
const grid = { display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 14 };
const card = {
  display: 'flex', flexDirection: 'column', gap: 8,
  background: 'var(--bg-surface)', border: '1px solid var(--border)', borderRadius: 'var(--r-lg)',
  padding: 20, textDecoration: 'none', transition: 'border-color 120ms, transform 200ms',
  fontFamily: 'var(--font-sans)', width: '100%',
};
const cardTop = { display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 };
const cardIndex = { fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--text-faint)', letterSpacing: '0.08em' };
const statusPill = {
  fontFamily: 'var(--font-mono)', fontSize: 11, padding: '3px 8px', borderRadius: 'var(--r-full)',
  border: '1px solid', whiteSpace: 'nowrap',
};
const cardTitle = { fontSize: 16, fontWeight: 700, color: 'var(--text-primary)', margin: 0, lineHeight: 1.3 };
const cardDesc = { fontSize: 13.5, color: 'var(--text-secondary)', margin: 0, lineHeight: 1.5, flex: 1 };
const cardCta = { fontSize: 13, color: 'var(--accent)', fontWeight: 600, marginTop: 4 };
const certBanner = {
  display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap',
  marginTop: 28, background: 'var(--ok-bg)', border: '1px solid var(--ok-border)',
  borderRadius: 'var(--r-md)', padding: '14px 18px', color: 'var(--ok)', fontSize: 15, fontWeight: 600,
};
const certLink = { color: 'var(--ok)', fontWeight: 700, textDecoration: 'underline' };
