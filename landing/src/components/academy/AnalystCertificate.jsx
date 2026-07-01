import { useState, useEffect } from 'react';
import {
  getGameState, getProgress, getMeta, onProgressChange, getLang,
  getAnalystName, setAnalystName, isCapstonePassed,
} from './progress.js';
import { evaluateBadges } from './badges.js';

/*
 * AnalystCertificate.jsx — printable / shareable completion certificate.
 *
 * HONESTY GATE: the certificate is only "issued" when the capstone is genuinely
 * passed (isCapstonePassed → progress['capstone'] === true). Before that it shows
 * a locked preview with the remaining requirement. The verifiable-ish stamp is a
 * deterministic short hash of (name + done-module-ids + mastery + date) so two
 * different progress states never produce the same stamp — it is NOT a crypto
 * proof, just a tamper-visible fingerprint the owner can eyeball.
 *
 * PROPS: allIds string[], modules object[], tracks object (same as Badges).
 */

const T = {
  title: { ru: 'Сертификат аналитика', en: 'Analyst Certificate' },
  locked_h: { ru: 'Сертификат ещё не открыт', en: 'Certificate not yet unlocked' },
  locked_p: { ru: 'Сдай капстоун (финальный разбор), чтобы получить сертификат SPA Analyst Academy.', en: 'Pass the capstone to unlock the SPA Analyst Academy certificate.' },
  nameLabel: { ru: 'Ваше имя для сертификата', en: 'Your name for the certificate' },
  namePlaceholder: { ru: 'Имя Фамилия', en: 'Full name' },
  completed: { ru: 'прошёл(ла) SPA Analyst Academy', en: 'has completed the SPA Analyst Academy' },
  issued: { ru: 'Выдан', en: 'Issued' },
  modulesDone: { ru: 'Модулей пройдено', en: 'Modules completed' },
  mastery: { ru: 'Освоение', en: 'Mastery' },
  rank: { ru: 'Ранг', en: 'Rank' },
  badges: { ru: 'Награды', en: 'Badges' },
  stamp: { ru: 'Отпечаток', en: 'Stamp' },
  print: { ru: 'Печать / PDF', en: 'Print / PDF' },
  stampNote: { ru: 'Детерминированный отпечаток прогресса (не криптодоказательство) — владелец может сверить.', en: 'Deterministic progress fingerprint (not a cryptographic proof) — the owner can verify.' },
  honest: { ru: 'Учебный сертификат. Подтверждает прохождение курса, не квалификацию.', en: 'Educational certificate. Confirms course completion, not a qualification.' },
};

// Small deterministic hash → short hex stamp (DJB2-ish). Not security; just a fingerprint.
function stampOf(str) {
  let h = 5381;
  for (let i = 0; i < str.length; i++) h = ((h << 5) + h + str.charCodeAt(i)) >>> 0;
  let h2 = 52711;
  for (let i = str.length - 1; i >= 0; i--) h2 = ((h2 << 5) + h2 + str.charCodeAt(i)) >>> 0;
  return (h.toString(16) + h2.toString(16)).slice(0, 12).toUpperCase();
}

export default function AnalystCertificate({ allIds = [], modules = [], tracks = null }) {
  const [lang, setLang] = useState('ru');
  const [name, setName] = useState('');
  const [, force] = useState(0);

  useEffect(() => {
    setLang(getLang());
    setName(getAnalystName());
    const off = onProgressChange(() => force((n) => n + 1));
    const obs = new MutationObserver(() => setLang(getLang()));
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ['lang'] });
    const onLang = () => setLang(getLang());
    window.addEventListener('storage', onLang);
    return () => { off(); obs.disconnect(); window.removeEventListener('storage', onLang); };
  }, []);

  const tr = (k) => (T[k] ? (T[k][lang] ?? T[k].ru) : k);

  const passed = isCapstonePassed();
  const gs = getGameState(allIds, tracks);
  const progress = getProgress();
  const doneIds = allIds.filter((id) => progress[id] === true).sort();
  const ctx = { progress, meta: getMeta(), gameState: gs, modules };
  const earnedBadges = evaluateBadges(ctx).filter((b) => b.earned);
  const issuedDate = new Date().toLocaleDateString(lang === 'en' ? 'en-US' : 'ru-RU', { year: 'numeric', month: 'long', day: 'numeric' });
  const displayName = (name || '').trim() || (lang === 'en' ? 'Analyst' : 'Аналитик');
  const stamp = stampOf(`${displayName}|${doneIds.join(',')}|${gs.overallMastery}|${issuedDate}`);

  function onName(e) {
    setName(e.target.value);
    setAnalystName(e.target.value);
  }

  if (!passed) {
    return (
      <div className="ac-cert-locked">
        <div className="ac-cert-glyph" aria-hidden="true">★</div>
        <h2>{tr('locked_h')}</h2>
        <p>{tr('locked_p')}</p>
        <a className="ac-cert-cta" href="/academy/capstone">{lang === 'en' ? 'Go to capstone →' : 'К капстоуну →'}</a>
        <style>{lockedCss}</style>
      </div>
    );
  }

  return (
    <div className="ac-cert-wrap">
      <div className="ac-cert-controls no-print">
        <label>
          <span>{tr('nameLabel')}</span>
          <input type="text" value={name} onChange={onName} placeholder={tr('namePlaceholder')} maxLength={80} />
        </label>
        <button onClick={() => window.print()}>{tr('print')}</button>
      </div>

      <div className="ac-cert" role="img" aria-label={tr('title')}>
        <div className="ac-cert-border">
          <div className="ac-cert-eyebrow">SPA ANALYST ACADEMY</div>
          <div className="ac-cert-title">{tr('title')}</div>
          <div className="ac-cert-name">{displayName}</div>
          <div className="ac-cert-sub">{tr('completed')}</div>

          <div className="ac-cert-grid">
            <div><span>{tr('modulesDone')}</span><strong>{gs.done} / {gs.total}</strong></div>
            <div><span>{tr('mastery')}</span><strong>{gs.overallMastery}%</strong></div>
            <div><span>{tr('rank')}</span><strong>{lang === 'en' ? gs.level.title_en : gs.level.title_ru}</strong></div>
            <div><span>XP</span><strong>{gs.xp}</strong></div>
            <div><span>{tr('badges')}</span><strong>{earnedBadges.length}</strong></div>
            <div><span>{tr('issued')}</span><strong>{issuedDate}</strong></div>
          </div>

          <div className="ac-cert-badges">
            {earnedBadges.map((b) => (
              <span key={b.id} className="ac-cert-badge" title={b.title_ru}>{b.glyph}</span>
            ))}
          </div>

          <div className="ac-cert-stamp">
            <span className="ac-cert-stamp-label">{tr('stamp')}</span>
            <code>{stamp}</code>
          </div>
          <p className="ac-cert-note">{tr('stampNote')}</p>
          <p className="ac-cert-honest">{tr('honest')}</p>
        </div>
      </div>

      <style>{certCss}</style>
    </div>
  );
}

const lockedCss = `
  .ac-cert-locked { text-align:center; max-width:520px; margin:0 auto; padding:48px 24px; border:1px dashed var(--border-strong); border-radius:var(--r-lg); background:var(--bg-surface); }
  .ac-cert-glyph { font-family:var(--font-mono); font-size:40px; line-height:1; color:var(--text-faint); }
  .ac-cert-locked h2 { color:var(--text-primary); font-size:1.4rem; margin:14px 0 8px; }
  .ac-cert-locked p { color:var(--text-secondary); line-height:1.6; margin:0 0 20px; }
  .ac-cert-cta { background:var(--accent); color:#fff; text-decoration:none; padding:10px 22px; border-radius:var(--r-sm); font-weight:600; }
`;

const certCss = `
  .ac-cert-wrap { max-width:760px; margin:0 auto; }
  .ac-cert-controls { display:flex; gap:16px; align-items:flex-end; flex-wrap:wrap; margin-bottom:24px; }
  .ac-cert-controls label { display:flex; flex-direction:column; gap:6px; flex:1; min-width:220px; }
  .ac-cert-controls span { font-size:12px; font-family:var(--font-mono); letter-spacing:.08em; text-transform:uppercase; color:var(--text-faint); }
  .ac-cert-controls input { background:var(--bg-surface-2); border:1px solid var(--border); border-radius:var(--r-sm); padding:10px 12px; color:var(--text-primary); font-size:15px; font-family:var(--font-sans); }
  .ac-cert-controls input:focus { outline:none; border-color:var(--accent); }
  .ac-cert-controls button { background:var(--accent); color:#fff; border:none; border-radius:var(--r-sm); padding:11px 20px; font-weight:600; font-size:14px; cursor:pointer; }

  /* Printable certificate is a deliberate LIGHT artifact (ink on paper). The light ramp is
     tokenized once here so the values aren't scattered hexes; hues track the canonical
     accent (#5B8DEF), ink (#0A0C10/#11141A), and neutral greys (§3.3 muted family). */
  .ac-cert {
    --cert-paper:#ffffff; --cert-paper-2:#f6f8fc; --cert-ink:#0A0C10; --cert-ink-2:#11141A;
    --cert-body:#374151; --cert-label:#6B7280; --cert-faint:#9CA3AF;
    --cert-accent:#5B8DEF; --cert-frame:#1E232C;
    background:var(--cert-paper); border-radius:var(--r-lg); padding:10px; box-shadow:var(--shadow-md);
  }
  .ac-cert-border { border:2px solid var(--cert-frame); border-radius:12px; padding:40px 36px; text-align:center; color:var(--cert-ink-2); background:linear-gradient(180deg,var(--cert-paper),var(--cert-paper-2)); }
  .ac-cert-eyebrow { font-family:var(--font-mono); font-size:12px; letter-spacing:.28em; color:var(--cert-accent); margin-bottom:18px; }
  .ac-cert-title { font-size:1.05rem; letter-spacing:.16em; text-transform:uppercase; color:var(--cert-label); margin-bottom:22px; }
  .ac-cert-name { font-size:2.2rem; font-weight:800; color:var(--cert-ink); margin-bottom:8px; line-height:1.1; }
  .ac-cert-sub { font-size:1rem; color:var(--cert-body); margin-bottom:26px; }
  .ac-cert-grid { display:grid; grid-template-columns:repeat(3,1fr); gap:14px 18px; max-width:520px; margin:0 auto 22px; }
  .ac-cert-grid > div { display:flex; flex-direction:column; gap:3px; }
  .ac-cert-grid span { font-size:10px; font-family:var(--font-mono); letter-spacing:.1em; text-transform:uppercase; color:var(--cert-faint); }
  .ac-cert-grid strong { font-size:15px; color:var(--cert-ink-2); }
  .ac-cert-badges { display:flex; flex-wrap:wrap; gap:10px; justify-content:center; margin-bottom:22px; font-family:var(--font-mono); font-size:20px; color:var(--cert-accent); }
  .ac-cert-stamp { display:inline-flex; align-items:center; gap:10px; padding:8px 16px; border:1px solid var(--cert-accent); border-radius:var(--r-full); margin-bottom:10px; }
  .ac-cert-stamp-label { font-size:10px; font-family:var(--font-mono); letter-spacing:.14em; text-transform:uppercase; color:var(--cert-accent); }
  .ac-cert-stamp code { font-family:var(--font-mono); font-size:14px; letter-spacing:.06em; color:var(--cert-ink); }
  .ac-cert-note { font-size:11px; color:var(--cert-faint); margin:0 0 4px; }
  .ac-cert-honest { font-size:11px; color:var(--cert-faint); margin:0; }

  @media print {
    .no-print { display:none !important; }
    .ac-cert { box-shadow:none; }
    body * { visibility:hidden; }
    .ac-cert-wrap, .ac-cert-wrap * { visibility:visible; }
    .ac-cert-wrap { position:absolute; left:0; top:0; width:100%; }
  }
  @media (max-width:560px) {
    .ac-cert-grid { grid-template-columns:repeat(2,1fr); }
    .ac-cert-name { font-size:1.6rem; }
  }
`;
