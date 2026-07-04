import { useState, useEffect, useCallback } from 'react';
import { apiGet, ApiError, getLang, onLangChange, explorerTxUrl } from './api.js';
import AuthForm from './AuthForm.jsx';

/*
 * CertificateView — the onboarding completion certificate.
 *
 * GET /certificate is delivered in stage 9; in stage 8 the route does not exist
 * yet, so this island GRACEFULLY handles 404 → "finish all 9 modules" prompt.
 * When the endpoint lands it renders: issue date, bound address, a proof table
 * (M0–M8 tx hashes → basescan), total gas, and quiz results. Shapes are read
 * defensively so a stage-9 payload variation degrades instead of crashing.
 */

const T = {
  title: { ru: 'Сертификат онбординга', en: 'Onboarding certificate' },
  loading: { ru: 'Загрузка…', en: 'Loading…' },
  signIn: { ru: 'Войдите, чтобы увидеть свой сертификат.', en: 'Sign in to view your certificate.' },
  notReady: {
    ru: 'Завершите все 9 модулей практики, чтобы получить сертификат.',
    en: 'Complete all 9 practice modules to earn the certificate.',
  },
  toCourse: { ru: 'К карте курса →', en: 'To the course map →' },
  offline: { ru: 'API недоступен — сертификат временно недоступен.', en: 'API unavailable — certificate temporarily unavailable.' },
  retry: { ru: 'Повторить', en: 'Retry' },
  issued: { ru: 'Выдан', en: 'Issued' },
  address: { ru: 'Привязанный адрес', en: 'Bound address' },
  gasTotal: { ru: 'Суммарный газ', en: 'Total gas' },
  proofs: { ru: 'Доказательства on-chain (M0–M8)', en: 'On-chain proofs (M0–M8)' },
  quiz: { ru: 'Результаты квизов', en: 'Quiz results' },
  module: { ru: 'Модуль', en: 'Module' },
  tx: { ru: 'Транзакция', en: 'Transaction' },
  score: { ru: 'Балл', en: 'Score' },
  share: { ru: 'Поделиться', en: 'Share' },
  shareSoon: { ru: 'Публичная ссылка появится в этапе 9.', en: 'A public link ships in stage 9.' },
  none: { ru: '—', en: '—' },
};

export default function CertificateView() {
  const [lang, setLang] = useState('ru');
  useEffect(() => { setLang(getLang()); return onLangChange(setLang); }, []);
  const tr = (k) => (T[k] ? T[k][lang] ?? T[k].ru : k);

  // 'loading' | 'anon' | 'ready' | 'notReady' | 'offline'
  const [phase, setPhase] = useState('loading');
  const [cert, setCert] = useState(null);

  const load = useCallback(async () => {
    setPhase('loading');
    try {
      const res = await apiGet('/certificate');
      setCert(res);
      setPhase('ready');
    } catch (e) {
      if (e instanceof ApiError) {
        if (e.status === 404) setPhase('notReady');
        else if (e.status === 401) setPhase('anon');
        else setPhase('offline');
      } else {
        setPhase('offline');
      }
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  if (phase === 'loading') {
    return <div style={{ color: 'var(--text-muted)', padding: '40px 0', textAlign: 'center' }}>{tr('loading')}</div>;
  }

  if (phase === 'anon') {
    return (
      <div>
        <p style={note}>{tr('signIn')}</p>
        <AuthForm onAuthed={() => load()} lang={lang} />
      </div>
    );
  }

  if (phase === 'offline') {
    return (
      <div style={warnBox} role="status">
        <span>{tr('offline')}</span>
        <button type="button" onClick={load} style={ghostBtn}>{tr('retry')}</button>
      </div>
    );
  }

  if (phase === 'notReady') {
    return (
      <div style={lockedBox}>
        <div style={{ fontSize: 34, marginBottom: 10 }}>🔒</div>
        <p style={{ ...note, fontSize: 15 }}>{tr('notReady')}</p>
        <a href="/academy/onboarding" style={linkCta}>{tr('toCourse')}</a>
      </div>
    );
  }

  // ── ready: read the stage-9 payload defensively ──────────────────────────
  const c = cert || {};
  const issued = c.issued_at || c.date || c.created_at || null;
  const address = c.address || c.wallet || (c.wallets && c.wallets[0]) || null;
  const gasTotal = c.gas_total ?? c.total_gas ?? c.gas_total_eth ?? null;
  const proofs = c.proofs || c.modules || c.tx_proofs || [];
  const quizzes = c.quiz_results || c.quizzes || [];

  return (
    <div style={certCard}>
      <div style={certHead}>
        <h2 style={{ margin: 0, fontSize: '1.6rem', color: 'var(--text-primary)' }}>{tr('title')}</h2>
        <span style={sealBadge}>SPA</span>
      </div>

      <dl style={metaGrid}>
        {issued && <Meta label={tr('issued')} value={String(issued)} mono />}
        {address && <Meta label={tr('address')} value={String(address)} mono />}
        {gasTotal != null && <Meta label={tr('gasTotal')} value={String(gasTotal)} mono />}
      </dl>

      {Array.isArray(proofs) && proofs.length > 0 && (
        <div style={{ marginTop: 18 }}>
          <h3 style={subH}>{tr('proofs')}</h3>
          <div style={tableWrap}>
            <table style={table}>
              <thead>
                <tr><th style={th}>{tr('module')}</th><th style={th}>{tr('tx')}</th></tr>
              </thead>
              <tbody>
                {proofs.map((p, i) => {
                  const id = p.lesson_id ?? p.module ?? p.id ?? i;
                  const txh = p.tx_hash || p.tx || null;
                  const url = p.explorer_url || explorerTxUrl(txh, p.chain);
                  return (
                    <tr key={i}>
                      <td style={td}>M{id}</td>
                      <td style={{ ...td, fontFamily: 'var(--font-mono)', fontSize: 12, wordBreak: 'break-all' }}>
                        {txh ? (url ? <a href={url} target="_blank" rel="noopener noreferrer" style={{ color: 'var(--accent)' }}>{txh}</a> : txh) : tr('none')}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {Array.isArray(quizzes) && quizzes.length > 0 && (
        <div style={{ marginTop: 18 }}>
          <h3 style={subH}>{tr('quiz')}</h3>
          <div style={tableWrap}>
            <table style={table}>
              <thead><tr><th style={th}>{tr('module')}</th><th style={th}>{tr('score')}</th></tr></thead>
              <tbody>
                {quizzes.map((q, i) => (
                  <tr key={i}>
                    <td style={td}>M{q.lesson_id ?? q.module ?? i}</td>
                    <td style={td}>{q.score != null ? `${Math.round(q.score)}%` : tr('none')}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div style={{ marginTop: 22, display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        <button type="button" onClick={() => alert(tr('shareSoon'))} style={ghostBtn}>{tr('share')}</button>
        <span style={{ fontSize: 12, color: 'var(--text-faint)' }}>{tr('shareSoon')}</span>
      </div>
    </div>
  );
}

function Meta({ label, value, mono }) {
  return (
    <div>
      <dt style={{ fontSize: 11, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>{label}</dt>
      <dd style={{ margin: '4px 0 0', color: 'var(--text-primary)', fontSize: 14, fontFamily: mono ? 'var(--font-mono)' : 'var(--font-sans)', wordBreak: 'break-all' }}>{value}</dd>
    </div>
  );
}

/* ── styles ───────────────────────────────────────────────────────────────── */
const note = { fontSize: 15, color: 'var(--text-secondary)', lineHeight: 1.6, margin: '0 0 16px', textAlign: 'center' };
const warnBox = { display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap', background: 'var(--warn-bg)', border: '1px solid var(--warn-border)', borderRadius: 'var(--r-md)', padding: '14px 18px', color: 'var(--warn)', fontSize: 14 };
const ghostBtn = { background: 'transparent', border: '1px solid var(--border-strong)', borderRadius: 'var(--r-sm)', color: 'var(--text-secondary)', padding: '8px 16px', cursor: 'pointer', fontSize: 13, fontFamily: 'var(--font-sans)' };
const lockedBox = { textAlign: 'center', padding: '48px 24px', background: 'var(--bg-surface)', border: '1px dashed var(--border-strong)', borderRadius: 'var(--r-lg)' };
const linkCta = { color: 'var(--accent)', fontWeight: 600, textDecoration: 'none', fontSize: 15 };
const certCard = { background: 'var(--bg-surface)', border: '1px solid var(--accent-dim)', borderRadius: 'var(--r-xl)', padding: 28 };
const certHead = { display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, marginBottom: 18, borderBottom: '1px solid var(--border)', paddingBottom: 16 };
const sealBadge = { fontFamily: 'var(--font-mono)', fontWeight: 700, color: 'var(--accent)', border: '1px solid var(--accent-border)', borderRadius: 'var(--r-full)', padding: '4px 12px', fontSize: 13 };
const metaGrid = { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 16, margin: 0 };
const subH = { fontSize: 12, fontFamily: 'var(--font-mono)', letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--text-muted)', margin: '0 0 10px' };
const tableWrap = { overflowX: 'auto' };
const table = { width: '100%', borderCollapse: 'collapse', fontSize: 14 };
const th = { textAlign: 'left', padding: '8px 10px', color: 'var(--text-muted)', fontWeight: 600, borderBottom: '1px solid var(--border)', fontSize: 12, whiteSpace: 'nowrap' };
const td = { padding: '8px 10px', color: 'var(--text-secondary)', borderBottom: '1px solid var(--border)' };
