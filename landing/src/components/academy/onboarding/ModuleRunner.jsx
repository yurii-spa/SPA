import { useState, useEffect, useCallback, useRef } from 'react';
import {
  apiGet, apiSend, ApiError, getLang, onLangChange, explorerTxUrl,
} from './api.js';
import AuthForm from './AuthForm.jsx';
import SiweBinder from './SiweBinder.jsx';

/*
 * ModuleRunner — the per-module page island (/academy/onboarding/[module]).
 *
 * Structure: Theory → Practice → Verify (on-chain / SIWE / quiz / capstone) →
 * Result → Notes → "What SPA would do". Theory/practice/SPA blocks are STATIC
 * (from moduleData) and always render — reading is never gated. The interactive
 * area (verify, quiz, notes) needs the per-session CSRF token, held in state
 * only; if absent it shows a compact inline sign-in. Fail-closed everywhere.
 *
 * Props:
 *   moduleId    number 0..8
 *   moduleData  static metadata object (title/description/*_html_ru, practice_type, chain)
 */

const AUTO_START = new Set([1, 2, 7, 8]); // server auto-starts these on verify
const NOTE_DEBOUNCE_MS = 2000;

const T = {
  theory: { ru: 'Теория', en: 'Theory' },
  practice: { ru: 'Задание', en: 'Practice' },
  verify: { ru: 'Проверка', en: 'Verification' },
  notes: { ru: 'Мои заметки', en: 'My notes' },
  spaBlock: { ru: 'Связь с SPA', en: 'The SPA connection' },
  loading: { ru: 'Загрузка…', en: 'Loading…' },
  back: { ru: '← к карте курса', en: '← back to course map' },
  signInToAct: {
    ru: 'Войдите, чтобы отправлять проверки и сохранять заметки. Теорию можно читать без входа.',
    en: 'Sign in to submit verifications and save notes. Theory is readable without signing in.',
  },
  offlineActions: {
    ru: 'API офлайн — проверки и заметки временно недоступны. Контент модуля доступен.',
    en: 'API offline — verifications and notes are temporarily unavailable. Module content is available.',
  },
  txHash: { ru: 'Хеш транзакции (0x…)', en: 'Transaction hash (0x…)' },
  approveTx: { ru: 'Хеш approve-транзакции', en: 'Approve tx hash' },
  revokeTx: { ru: 'Хеш revoke-транзакции', en: 'Revoke tx hash' },
  checkOnchain: { ru: 'Проверить on-chain', en: 'Verify on-chain' },
  checkBalance: { ru: 'Проверить баланс', en: 'Check balance' },
  checkQuiz: { ru: 'Проверить квиз', en: 'Verify quiz' },
  checkCapstone: { ru: 'Проверить капстоун', en: 'Verify capstone' },
  bindWallet: { ru: 'Привязать кошелёк', en: 'Bind wallet' },
  checking: { ru: 'Проверяем on-chain…', en: 'Verifying on-chain…' },
  verified: { ru: 'Модуль подтверждён', en: 'Module verified' },
  failed: { ru: 'Проверка не пройдена', en: 'Verification failed' },
  unavailable: { ru: 'Проверка недоступна — попробуйте позже (RPC / сеть).', en: 'Verification unavailable — try again later (RPC / network).' },
  pending: { ru: 'Транзакция ещё не финализирована — подождите и повторите.', en: 'Transaction not final yet — wait and retry.' },
  retry: { ru: 'Повторить', en: 'Retry' },
  alreadyVerified: { ru: 'Этот модуль уже подтверждён ✅', en: 'This module is already verified ✅' },
  onExplorer: { ru: 'Открыть в explorer', en: 'View on explorer' },
  overLimit: {
    ru: 'Внимание: сумма превышает учебный лимит $150. Проверка засчитана, но держитесь лимита.',
    en: 'Note: amount exceeds the $150 educational limit. Counted, but stay within the limit.',
  },
  noteSaving: { ru: 'Сохранение…', en: 'Saving…' },
  noteSaved: { ru: 'Сохранено', en: 'Saved' },
  notePlaceholder: {
    ru: 'Заметки по модулю: что понял, что осталось неясным…',
    en: 'Module notes: what clicked, what is still unclear…',
  },
  reflectionPlaceholder: {
    ru: 'Рефлексия капстоуна: что удивило; что бы автоматизировал (почему); что оставил бы ручным (почему)…',
    en: 'Capstone reflection: what surprised you; what you would automate (why); what you would keep manual (why)…',
  },
  quizErr: { ru: 'Не удалось загрузить квиз.', en: 'Failed to load the quiz.' },
  quizSubmit: { ru: 'Проверить ответы', en: 'Grade answers' },
  quizScore: { ru: 'Результат', en: 'Score' },
  quizPassed: { ru: 'Порог пройден (≥80%)', en: 'Passed (≥80%)' },
  quizFailed: { ru: 'Порог не пройден (нужно ≥80%)', en: 'Not passed (need ≥80%)' },
  quizAnswerAll: { ru: 'Ответьте на все вопросы.', en: 'Answer every question.' },
  quizAttempt: { ru: 'попытка', en: 'attempt' },
  quizThenVerify: {
    ru: 'Наберите ≥80%, затем нажмите «Проверить квиз», чтобы засчитать модуль.',
    en: 'Score ≥80%, then press “Verify quiz” to complete the module.',
  },
  errBad: { ru: 'Проверьте введённые данные.', en: 'Check your input.' },
  errOffline: { ru: 'API недоступен. Попробуйте позже.', en: 'API unavailable. Try again later.' },
};

export default function ModuleRunner({ moduleId, moduleData }) {
  const [lang, setLang] = useState('ru');
  useEffect(() => { setLang(getLang()); return onLangChange(setLang); }, []);
  const tr = (k) => (T[k] ? T[k][lang] ?? T[k].ru : k);

  // 'loading' | 'anon' | 'authed' | 'offline'
  const [phase, setPhase] = useState('loading');
  const [status, setStatus] = useState(null); // this module's progress status
  const [csrf, setCsrf] = useState(null);

  const ptype = moduleData.practice_type;

  const load = useCallback(async () => {
    setPhase('loading');
    try {
      const res = await apiGet('/progress');
      const row = (res && res.progress ? res.progress : []).find((p) => p.lesson_id === moduleId);
      setStatus(row ? row.status : 'not_started');
      setPhase('authed');
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) setPhase('anon');
      else setPhase('offline');
    }
  }, [moduleId]);

  useEffect(() => { load(); }, [load]);

  const onAuthed = useCallback((token) => { setCsrf(token); load(); }, [load]);

  const interactive = phase === 'authed' && !!csrf;

  return (
    <div>
      <a href="/academy/onboarding" style={backLink}>{tr('back')}</a>
      <div style={eyebrow}>МОДУЛЬ M{moduleId}{ptype ? ` · ${ptype}` : ''}</div>
      <h1 style={h1}>{lang === 'en' ? moduleData.title_en : moduleData.title_ru}</h1>
      <p style={lede}>{lang === 'en' ? moduleData.description_en : moduleData.description_ru}</p>

      {/* Theory (static) */}
      <Section title={tr('theory')}>
        <div style={prose} dangerouslySetInnerHTML={{ __html: (lang === 'en' && moduleData.theory_html_en) ? moduleData.theory_html_en : moduleData.theory_html_ru }} />
      </Section>

      {/* Practice (static) */}
      <Section title={tr('practice')}>
        <div style={prose} dangerouslySetInnerHTML={{ __html: (lang === 'en' && moduleData.practice_html_en) ? moduleData.practice_html_en : moduleData.practice_html_ru }} />
      </Section>

      {/* Verify + quiz + notes (interactive) */}
      <Section title={tr('verify')}>
        {phase === 'loading' && <div style={{ color: 'var(--text-muted)', fontSize: 14 }}>{tr('loading')}</div>}

        {phase === 'offline' && (
          <div style={warnBox} role="status">{tr('offlineActions')}</div>
        )}

        {(phase === 'anon' || (phase === 'authed' && !csrf)) && (
          <div>
            <p style={{ ...softNote, marginTop: 0 }}>{tr('signInToAct')}</p>
            <AuthForm onAuthed={onAuthed} lang={lang} compact />
          </div>
        )}

        {interactive && status === 'verified' && (
          <div style={okBox}>{tr('alreadyVerified')}</div>
        )}

        {interactive && status !== 'verified' && (
          <VerifyArea
            moduleId={moduleId}
            ptype={ptype}
            chain={moduleData.chain}
            csrf={csrf}
            status={status}
            setStatus={setStatus}
            lang={lang}
            tr={tr}
          />
        )}
      </Section>

      {/* Notes (interactive; for M8 doubles as the capstone reflection) */}
      {interactive && (
        <Section title={tr('notes')}>
          <NotesArea moduleId={moduleId} csrf={csrf} lang={lang} tr={tr} reflection={ptype === 'capstone'} />
        </Section>
      )}

      {/* SPA connection (static) */}
      <Section title={tr('spaBlock')} accent>
        <div style={prose} dangerouslySetInnerHTML={{ __html: (lang === 'en' && moduleData.spa_connection_html_en) ? moduleData.spa_connection_html_en : moduleData.spa_connection_html_ru }} />
      </Section>
    </div>
  );
}

/* ── Verify area: the module-specific proof form ──────────────────────────── */
function VerifyArea({ moduleId, ptype, chain, csrf, status, setStatus, lang, tr }) {
  const [tx, setTx] = useState('');
  const [approveTx, setApproveTx] = useState('');
  const [revokeTx, setRevokeTx] = useState('');
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null); // {status,message,evidence_summary} | {status:'error',message}
  const [quizPassed, setQuizPassed] = useState(false);

  const runVerify = useCallback(async (body) => {
    setBusy(true);
    setResult(null);
    try {
      if (!AUTO_START.has(moduleId) && status === 'not_started') {
        try {
          await apiSend('/progress', { method: 'POST', body: { lesson_id: moduleId, action: 'start' }, csrf });
        } catch { /* 409 already-started is fine */ }
      }
      const res = await apiSend(`/verify/${moduleId}`, { method: 'POST', body: body || {}, csrf });
      setResult(res);
      if (res.status === 'verified') setStatus('verified');
      else if (res.status === 'failed') setStatus('failed');
    } catch (e) {
      const msg =
        e instanceof ApiError
          ? (e.isOffline ? tr('errOffline') : (typeof e.detail === 'string' ? e.detail : tr('errBad')))
          : tr('errOffline');
      setResult({ status: 'error', message: msg });
    } finally {
      setBusy(false);
    }
  }, [moduleId, status, csrf, setStatus, tr]);

  const needsTx = [0, 3, 5, 6].includes(moduleId);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      {/* M0/M3/M5/M6 — single tx hash */}
      {needsTx && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <label style={fieldLabel}>{tr('txHash')}</label>
          <input value={tx} onChange={(e) => setTx(e.target.value)} placeholder="0x…" style={txInput} />
          <button type="button" disabled={busy || !tx.trim()} onClick={() => runVerify({ tx_hash: tx.trim() })} style={primaryBtn}>
            {busy ? tr('checking') : tr('checkOnchain')}
          </button>
        </div>
      )}

      {/* M1 — SIWE wallet bind, then mark verified */}
      {moduleId === 1 && (
        <SiweBinder
          csrf={csrf}
          lang={lang}
          onVerified={() => runVerify({})}
        />
      )}

      {/* M2 — balance check, no input */}
      {moduleId === 2 && (
        <button type="button" disabled={busy} onClick={() => runVerify({})} style={primaryBtn}>
          {busy ? tr('checking') : tr('checkBalance')}
        </button>
      )}

      {/* M4 — approve + revoke pair */}
      {moduleId === 4 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <label style={fieldLabel}>{tr('approveTx')}</label>
          <input value={approveTx} onChange={(e) => setApproveTx(e.target.value)} placeholder="0x…" style={txInput} />
          <label style={fieldLabel}>{tr('revokeTx')}</label>
          <input value={revokeTx} onChange={(e) => setRevokeTx(e.target.value)} placeholder="0x…" style={txInput} />
          <button
            type="button"
            disabled={busy || !approveTx.trim() || !revokeTx.trim()}
            onClick={() => runVerify({ approve_tx: approveTx.trim(), revoke_tx: revokeTx.trim() })}
            style={primaryBtn}
          >
            {busy ? tr('checking') : tr('checkOnchain')}
          </button>
        </div>
      )}

      {/* M7 — quiz, then verify */}
      {moduleId === 7 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <QuizSection moduleId={7} csrf={csrf} lang={lang} tr={tr} onPassed={() => setQuizPassed(true)} />
          <p style={softNote}>{tr('quizThenVerify')}</p>
          <button type="button" disabled={busy} onClick={() => runVerify({})} style={{ ...primaryBtn, ...(quizPassed ? null : dimBtn) }}>
            {busy ? tr('checking') : tr('checkQuiz')}
          </button>
        </div>
      )}

      {/* M8 — capstone verify (reflection lives in the Notes section below) */}
      {moduleId === 8 && (
        <button type="button" disabled={busy} onClick={() => runVerify({})} style={primaryBtn}>
          {busy ? tr('checking') : tr('checkCapstone')}
        </button>
      )}

      {result && <VerifyResult result={result} chain={chain} lang={lang} tr={tr} onRetry={() => setResult(null)} />}
    </div>
  );
}

function VerifyResult({ result, chain, lang, tr, onRetry }) {
  const s = result.status;
  if (s === 'verified') {
    const ev = result.evidence_summary || {};
    const url = ev.explorer_url || explorerTxUrl(ev.tx_hash, ev.chain || chain);
    return (
      <div style={okBox}>
        <div style={{ fontWeight: 700, color: 'var(--ok)', marginBottom: 6 }}>✅ {tr('verified')}</div>
        {result.message && <p style={{ margin: '0 0 8px', color: 'var(--text-secondary)', fontSize: 14 }}>{result.message}</p>}
        {ev.tx_hash && (
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--text-muted)', wordBreak: 'break-all' }}>
            {ev.tx_hash}
            {url && <> · <a href={url} target="_blank" rel="noopener noreferrer" style={{ color: 'var(--accent)' }}>{tr('onExplorer')} ↗</a></>}
          </div>
        )}
        {ev.advisory_over_limit && <div style={{ ...warnBox, marginTop: 8 }}>{tr('overLimit')}</div>}
      </div>
    );
  }
  const tone = s === 'failed' || s === 'error' ? 'danger' : 'warn';
  const heading = s === 'failed' ? `⚠️ ${tr('failed')}` : s === 'unavailable' ? tr('unavailable') : s === 'pending' ? tr('pending') : `⚠️ ${tr('failed')}`;
  return (
    <div style={{ ...(tone === 'danger' ? dangerBox : warnBox) }}>
      <div style={{ fontWeight: 700, marginBottom: 6 }}>{heading}</div>
      {result.message && <p style={{ margin: '0 0 8px', fontSize: 14, lineHeight: 1.5 }}>{result.message}</p>}
      <button type="button" onClick={onRetry} style={ghostBtn}>{tr('retry')}</button>
    </div>
  );
}

/* ── Quiz section (M7) ────────────────────────────────────────────────────── */
function QuizSection({ moduleId, csrf, lang, tr, onPassed }) {
  const [questions, setQuestions] = useState(null); // null=loading, []=error/empty
  const [answers, setAnswers] = useState({}); // qIndex -> optionIndex
  const [busy, setBusy] = useState(false);
  const [graded, setGraded] = useState(null); // {score,passed,attempt_n,feedback}
  const [err, setErr] = useState(null);

  useEffect(() => {
    let live = true;
    (async () => {
      try {
        const res = await apiGet(`/quiz/${moduleId}`);
        if (live) setQuestions(res && Array.isArray(res.questions) ? res.questions : []);
      } catch {
        if (live) { setQuestions([]); setErr(tr('quizErr')); }
      }
    })();
    return () => { live = false; };
  }, [moduleId, tr]);

  async function submit() {
    if (!questions || questions.length === 0) return;
    if (Object.keys(answers).length < questions.length) { setErr(tr('quizAnswerAll')); return; }
    setBusy(true); setErr(null);
    try {
      const ordered = questions.map((_, i) => answers[i]);
      const res = await apiSend(`/quiz/${moduleId}`, { method: 'POST', body: { answers: ordered }, csrf });
      setGraded(res);
      if (res.passed && onPassed) onPassed();
    } catch (e) {
      setErr(e instanceof ApiError && !e.isOffline && typeof e.detail === 'string' ? e.detail : tr('errOffline'));
    } finally {
      setBusy(false);
    }
  }

  if (questions === null) return <div style={{ color: 'var(--text-muted)', fontSize: 14 }}>{tr('loading')}</div>;
  if (questions.length === 0) return <div style={warnBox}>{err || tr('quizErr')}</div>;

  return (
    <div style={quizWrap}>
      {questions.map((q, qi) => (
        <fieldset key={q.id ?? qi} style={quizQ}>
          <legend style={quizLegend}>{qi + 1}. {q.text}</legend>
          {(q.options || []).map((opt, oi) => (
            <label key={oi} style={quizOpt}>
              <input
                type="radio"
                name={`q-${moduleId}-${qi}`}
                checked={answers[qi] === oi}
                onChange={() => setAnswers((a) => ({ ...a, [qi]: oi }))}
              />
              <span>{opt}</span>
            </label>
          ))}
        </fieldset>
      ))}
      {err && <div style={dangerBox}>{err}</div>}
      <button type="button" disabled={busy} onClick={submit} style={secondaryBtn}>
        {busy ? tr('noteSaving') : tr('quizSubmit')}
      </button>
      {graded && (
        <div style={graded.passed ? okBox : warnBox}>
          <div style={{ fontWeight: 700, marginBottom: 4 }}>
            {tr('quizScore')}: {Math.round(graded.score)}% · {graded.passed ? tr('quizPassed') : tr('quizFailed')}
            <span style={{ color: 'var(--text-faint)', fontWeight: 400, marginLeft: 8, fontSize: 12 }}>
              ({tr('quizAttempt')} {graded.attempt_n})
            </span>
          </div>
          {Array.isArray(graded.feedback) && graded.feedback.length > 0 && (
            <ul style={{ margin: '6px 0 0', paddingLeft: 18, fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.5 }}>
              {graded.feedback.map((f, i) => <li key={i}>{f}</li>)}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

/* ── Notes with debounced autosave ────────────────────────────────────────── */
function NotesArea({ moduleId, csrf, lang, tr, reflection }) {
  const [text, setText] = useState('');
  const [updatedAt, setUpdatedAt] = useState(null);
  const [saveState, setSaveState] = useState('idle'); // idle | saving | saved
  const timer = useRef(null);
  const loaded = useRef(false);

  useEffect(() => {
    let live = true;
    (async () => {
      try {
        const res = await apiGet(`/notes/${moduleId}`);
        if (live && res) { setText(res.text || ''); setUpdatedAt(res.updated_at || null); }
      } catch { /* leave empty */ }
      finally { loaded.current = true; }
    })();
    return () => { live = false; if (timer.current) clearTimeout(timer.current); };
  }, [moduleId]);

  const save = useCallback(async (value) => {
    setSaveState('saving');
    try {
      const res = await apiSend(`/notes/${moduleId}`, { method: 'PUT', body: { text: value }, csrf });
      if (res) setUpdatedAt(res.updated_at || null);
      setSaveState('saved');
    } catch {
      setSaveState('idle');
    }
  }, [moduleId, csrf]);

  function onChange(v) {
    setText(v);
    setSaveState('saving');
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => save(v), NOTE_DEBOUNCE_MS);
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <textarea
        value={text}
        onChange={(e) => onChange(e.target.value)}
        placeholder={reflection ? tr('reflectionPlaceholder') : tr('notePlaceholder')}
        rows={reflection ? 8 : 5}
        style={textarea}
      />
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, color: 'var(--text-faint)' }}>
        <span>
          {saveState === 'saving' ? tr('noteSaving') : saveState === 'saved' ? tr('noteSaved') : ''}
        </span>
        {updatedAt && <span style={{ fontFamily: 'var(--font-mono)' }}>{tr('noteSaved')}: {updatedAt} UTC</span>}
      </div>
    </div>
  );
}

/* ── layout atoms ─────────────────────────────────────────────────────────── */
function Section({ title, children, accent }) {
  return (
    <section style={{ ...sectionBox, ...(accent ? { borderColor: 'var(--accent-dim)' } : null) }}>
      <h2 style={{ ...sectionH, ...(accent ? { color: 'var(--accent)' } : null) }}>{title}</h2>
      {children}
    </section>
  );
}

/* ── styles ───────────────────────────────────────────────────────────────── */
const backLink = { display: 'inline-block', fontFamily: 'var(--font-mono)', fontSize: 13, color: 'var(--text-muted)', textDecoration: 'none', marginBottom: 16 };
const eyebrow = { fontFamily: 'var(--font-mono)', fontSize: 12, letterSpacing: '0.12em', color: 'var(--text-faint)', marginBottom: 10, textTransform: 'uppercase' };
const h1 = { fontSize: '2rem', fontWeight: 700, color: 'var(--text-primary)', margin: '0 0 10px', lineHeight: 1.2 };
const lede = { fontSize: 16, color: 'var(--text-secondary)', margin: '0 0 8px', lineHeight: 1.6 };
const sectionBox = { background: 'var(--bg-surface)', border: '1px solid var(--border)', borderRadius: 'var(--r-lg)', padding: 24, margin: '20px 0' };
const sectionH = { fontSize: 12, fontFamily: 'var(--font-mono)', letterSpacing: '0.12em', textTransform: 'uppercase', color: 'var(--text-muted)', margin: '0 0 14px' };
const prose = { fontSize: 15, lineHeight: 1.7, color: 'var(--text-secondary)' };
const softNote = { fontSize: 13, color: 'var(--text-muted)', lineHeight: 1.5, margin: '0 0 12px' };
const fieldLabel = { fontSize: 12, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' };
const txInput = { padding: '10px 12px', borderRadius: 'var(--r-sm)', border: '1px solid var(--border-strong)', background: 'var(--bg-base)', color: 'var(--text-primary)', fontSize: 14, fontFamily: 'var(--font-mono)' };
const textarea = { padding: '12px 14px', borderRadius: 'var(--r-sm)', border: '1px solid var(--border-strong)', background: 'var(--bg-base)', color: 'var(--text-primary)', fontSize: 15, fontFamily: 'var(--font-sans)', lineHeight: 1.6, resize: 'vertical' };
const primaryBtn = { padding: '11px 18px', borderRadius: 'var(--r-sm)', border: '1px solid var(--accent-border)', background: 'var(--accent-bg)', color: 'var(--accent)', fontSize: 15, fontWeight: 700, cursor: 'pointer', fontFamily: 'var(--font-sans)', alignSelf: 'flex-start' };
const dimBtn = { opacity: 0.75 };
const secondaryBtn = { ...primaryBtn, background: 'var(--bg-surface-2)', color: 'var(--text-primary)', border: '1px solid var(--border-strong)' };
const ghostBtn = { background: 'transparent', border: '1px solid var(--border-strong)', borderRadius: 'var(--r-sm)', color: 'var(--text-secondary)', padding: '7px 14px', cursor: 'pointer', fontSize: 13, fontFamily: 'var(--font-sans)' };
const okBox = { background: 'var(--ok-bg)', border: '1px solid var(--ok-border)', borderRadius: 'var(--r-md)', padding: '14px 16px', color: 'var(--text-secondary)', fontSize: 14 };
const warnBox = { background: 'var(--warn-bg)', border: '1px solid var(--warn-border)', borderRadius: 'var(--r-md)', padding: '12px 16px', color: 'var(--warn)', fontSize: 13.5, lineHeight: 1.5 };
const dangerBox = { background: 'var(--danger-bg)', border: '1px solid var(--danger-border)', borderRadius: 'var(--r-md)', padding: '12px 16px', color: 'var(--danger)', fontSize: 13.5, lineHeight: 1.5 };
const quizWrap = { display: 'flex', flexDirection: 'column', gap: 14 };
const quizQ = { border: '1px solid var(--border)', borderRadius: 'var(--r-md)', padding: '14px 16px', margin: 0 };
const quizLegend = { fontSize: 14.5, fontWeight: 600, color: 'var(--text-primary)', padding: '0 6px', lineHeight: 1.4 };
const quizOpt = { display: 'flex', gap: 10, alignItems: 'flex-start', padding: '7px 0', fontSize: 14, color: 'var(--text-secondary)', cursor: 'pointer', lineHeight: 1.5 };
