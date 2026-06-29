import { useState, useEffect, useCallback } from 'react';
import { AnnualContrastView, T } from './DashboardLive.jsx';

/*
 * AnnualContrast — the SHAREABLE one-pager island for /annual-contrast.
 *
 * A clean, presentable surface the owner can open in front of a prospect: the two equity curves
 * (the 10-15% aggressive book vs the desk's REAL steady ~5%), the aggressive book's drawdowns
 * DATED + labelled by event, and the side-by-side contrast table. It RENDERS the exact same
 * <AnnualContrastView> the dashboard uses (single source of truth — no duplicated chart logic),
 * fed from /api/aggressive-lab/annual-contrast served VERBATIM, fail-CLOSED.
 *
 * HONESTY CONTRACT (mirrors the dashboard):
 *   - The steady ~5% line is the REAL conservative book (stable_apy_pct/source from the data),
 *     not a flattering fake. Its source string is shown on the page.
 *   - A missing/offline contrast file → honest "unavailable", NEVER a fabricated chart.
 *   - Drawdown annotations carry their REAL dates+events from the data; realized vs modeled are
 *     visually distinct (the view never passes a modeled overlay off as a realized dip).
 *   - This is PAPER / ADVISORY / OUTSIDE-RiskPolicy — the strategies the desk REFUSES, shown
 *     with their real risk. Never live-allocated, never touches the go-live track.
 */

const API =
  typeof window !== 'undefined' &&
  (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1')
    ? 'http://localhost:8765'
    : 'https://api.earn-defi.com';

const POLL_MS = 15_000;
const FETCH_TIMEOUT_MS = 8_000;

function getLang() {
  if (typeof window === 'undefined') return 'en';
  try {
    return (window.localStorage.getItem('spa_lang') || (document.documentElement.lang) || 'en').startsWith('ru') ? 'ru' : 'en';
  } catch {
    return 'en';
  }
}

export default function AnnualContrast() {
  const [contrast, setContrast] = useState(undefined);
  const [lang, setLang] = useState('en');

  // Keep in sync with the site's EN|RU toggle (spa_lang in localStorage + <html lang>).
  useEffect(() => {
    setLang(getLang());
    const onStorage = () => setLang(getLang());
    window.addEventListener('storage', onStorage);
    const obs = new MutationObserver(() => setLang(getLang()));
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ['lang'] });
    return () => { window.removeEventListener('storage', onStorage); obs.disconnect(); };
  }, []);

  const poll = useCallback(async () => {
    try {
      const r = await fetch(API + '/api/aggressive-lab/annual-contrast', {
        signal: AbortSignal.timeout(FETCH_TIMEOUT_MS),
        headers: { Accept: 'application/json' },
      });
      if (!r.ok) throw new Error('HTTP ' + r.status);
      setContrast(await r.json());
    } catch {
      setContrast(null); // offline — the view renders an honest "unavailable", never a fake chart
    }
  }, []);

  useEffect(() => {
    poll();
    const id = setInterval(poll, POLL_MS);
    return () => clearInterval(id);
  }, [poll]);

  const tr = (k) => (T[k] ? (T[k][lang] ?? T[k].en) : k);

  return <AnnualContrastView contrast={contrast} lang={lang} tr={tr} embedded={false} />;
}
