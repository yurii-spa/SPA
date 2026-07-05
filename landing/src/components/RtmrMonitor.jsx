/**
 * RtmrMonitor.jsx — live view of the RTMR (ADR-053) real-time monitoring organism.
 *
 * Polls /api/rtmr/status (+ /api/rtmr/signals) and shows what the sense/emergency service is
 * watching, the current defensive posture, and recent de-risk actions. Fail-CLOSED: if the API is
 * offline it says so honestly and shows NO fabricated numbers. Bilingual (follows <html lang>).
 * Paper — this surface never implies live capital movement.
 */
import { useState, useEffect, useCallback } from 'react';

const API =
  typeof window !== 'undefined' &&
  (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1')
    ? 'http://localhost:8765'
    : 'https://api.earn-defi.com';
const FETCH_TIMEOUT_MS = 8000;
const POLL_MS = 30000;

const getLang = () => {
  try {
    if (typeof localStorage !== 'undefined') {
      const l = localStorage.getItem('spa_lang');
      if (l === 'en' || l === 'ru') return l;
    }
  } catch (e) { /* ignore */ }
  return (typeof document !== 'undefined' && document.documentElement.lang === 'en') ? 'en' : 'ru';
};

const T = {
  title: { ru: 'Живой мониторинг риска (RTMR)', en: 'Live risk monitoring (RTMR)' },
  sub: {
    ru: 'Непрерывный сторож: каждые ~45с следит за депегом, TVL, оракулами и ликвидностью по 5–10 источникам. Детерминированный, только снижает риск, на бумаге.',
    en: 'A continuous watchman: every ~45s it checks depeg, TVL, oracles and liquidity across 5–10 sources. Deterministic, de-risk-only, paper.',
  },
  live: { ru: 'сервис жив', en: 'service alive' },
  offline: { ru: 'API офлайн', en: 'API offline' },
  noData: {
    ru: 'Нет данных — API недоступен. Здесь мы НИКОГДА не показываем выдуманное число.',
    en: 'No data — API offline. We NEVER show a fabricated number here.',
  },
  loading: { ru: 'Загрузка…', en: 'Loading…' },
  paper: { ru: 'PAPER · капитал не двигается', en: 'PAPER · no capital moved' },
  watching: { ru: 'Следит за', en: 'Watching' },
  lastTick: { ru: 'последний тик', en: 'last tick' },
  worst: { ru: 'худший сигнал', en: 'worst severity' },
  posture: { ru: 'Защитная поза', en: 'Defensive posture' },
  active: { ru: 'активных де-рисков', en: 'active de-risks' },
  normal: { ru: 'НОРМА — всё спокойно', en: 'NORMAL — all calm' },
  defensive: { ru: 'ОБОРОНА — весь портфель в кэш', en: 'DEFENSIVE — whole book to cash' },
  scopes: { ru: 'под защитой', en: 'under protection' },
  sec: { ru: 'с назад', en: 's ago' },
  sourceNames: {
    peg: { ru: 'депег стейблов', en: 'stablecoin peg' },
    tvl: { ru: 'обвал TVL', en: 'TVL collapse' },
    oracle: { ru: 'здоровье оракула', en: 'oracle health' },
    liquidity: { ru: 'ликвидность выхода', en: 'exit liquidity' },
  },
  sev: {
    info: { ru: 'спокойно', en: 'calm' },
    warn: { ru: 'внимание', en: 'watch' },
    critical: { ru: 'тревога', en: 'alert' },
  },
  stream: { ru: 'Живая лента сигналов', en: 'Live signal stream' },
  reactions: { ru: 'Недавние де-риски (paper)', en: 'Recent de-risks (paper)' },
  noReactions: { ru: 'Пока ни одного — всё спокойно', en: 'None yet — all calm' },
};

const SEV_COLOR = { info: '#2f9e57', warn: '#c78a00', critical: '#c0392b' };

function tr(key, lang) {
  const e = T[key];
  return e ? (e[lang] || e.ru) : key;
}

export default function RtmrMonitor() {
  const [lang, setLang] = useState('ru');
  const [state, setState] = useState('loading'); // loading | live | offline
  const [status, setStatus] = useState(null);
  const [signals, setSignals] = useState([]);
  const [reactions, setReactions] = useState([]);

  useEffect(() => {
    setLang(getLang());
    const obs = new MutationObserver(() => setLang(getLang()));
    if (typeof document !== 'undefined') {
      obs.observe(document.documentElement, { attributes: true, attributeFilter: ['lang'] });
    }
    return () => obs.disconnect();
  }, []);

  const poll = useCallback(async () => {
    const get = (path) => fetch(API + path, {
      signal: AbortSignal.timeout(FETCH_TIMEOUT_MS), headers: { Accept: 'application/json' },
    }).then((r) => (r.ok ? r.json() : null)).catch(() => null);
    try {
      const [d, sig, rx] = await Promise.all([
        get('/api/rtmr/status'), get('/api/rtmr/signals'), get('/api/rtmr/reactions?limit=8'),
      ]);
      if (!d || typeof d !== 'object' || !('portfolio_posture' in d)) throw new Error('bad shape');
      setStatus(d);
      setSignals((sig && Array.isArray(sig.signals)) ? sig.signals : []);
      setReactions((rx && Array.isArray(rx.recent)) ? rx.recent : []);
      setState('live');
    } catch {
      setState('offline');
      setStatus(null);
      setSignals([]);
      setReactions([]);
    }
  }, []);

  useEffect(() => {
    poll();
    const id = setInterval(poll, POLL_MS);
    return () => clearInterval(id);
  }, [poll]);

  const card = {
    border: '1px solid var(--border, #2a2a33)', borderRadius: 12, padding: '20px 22px',
    background: 'var(--panel, #14141a)', maxWidth: 760, margin: '0 auto',
    fontFamily: 'var(--font-sans, system-ui, sans-serif)', color: 'var(--fg, #e8e8ee)',
  };
  const badge = (bg) => ({
    display: 'inline-block', padding: '2px 10px', borderRadius: 999, fontSize: 12,
    fontWeight: 600, background: bg, color: '#fff',
  });

  if (state === 'loading') {
    return <div style={card}>{tr('loading', lang)}</div>;
  }
  if (state === 'offline' || !status) {
    return (
      <div style={card}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <strong>{tr('title', lang)}</strong>
          <span style={badge('#7a7a85')}>{tr('offline', lang)}</span>
        </div>
        <p style={{ opacity: 0.8, marginTop: 10 }}>{tr('noData', lang)}</p>
      </div>
    );
  }

  const isDefensive = status.portfolio_posture === 'DEFENSIVE';
  const worst = status.max_severity || 'info';
  const sources = status.sources || [];
  const active = status.active_postures || 0;

  return (
    <div style={card}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <strong style={{ fontSize: 17 }}>{tr('title', lang)}</strong>
        <span style={{ display: 'flex', gap: 6 }}>
          <span style={badge(status.alive ? '#2f9e57' : '#c0392b')}>
            {status.alive ? tr('live', lang) : tr('offline', lang)}
          </span>
          <span style={badge('#4a4a55')}>{tr('paper', lang)}</span>
        </span>
      </div>
      <p style={{ opacity: 0.75, fontSize: 13, marginTop: 8, lineHeight: 1.5 }}>{tr('sub', lang)}</p>

      <div style={{ display: 'flex', gap: 18, flexWrap: 'wrap', marginTop: 14, fontSize: 13 }}>
        <span>{tr('lastTick', lang)}: <strong>{status.heartbeat_age_sec != null ? status.heartbeat_age_sec + tr('sec', lang) : '—'}</strong></span>
        <span>{tr('worst', lang)}: <strong style={{ color: SEV_COLOR[worst] }}>{tr('sev', lang) && (T.sev[worst] ? T.sev[worst][lang] : worst)}</strong></span>
        <span>{tr('active', lang)}: <strong>{active}</strong></span>
      </div>

      <div style={{ marginTop: 16 }}>
        <div style={{ fontSize: 12, textTransform: 'uppercase', letterSpacing: 0.5, opacity: 0.6, marginBottom: 8 }}>
          {tr('watching', lang)}
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 8 }}>
          {['peg', 'tvl', 'oracle', 'liquidity'].map((src) => {
            const on = sources.includes(src);
            return (
              <div key={src} style={{
                border: '1px solid var(--border, #2a2a33)', borderRadius: 8, padding: '10px 12px',
                opacity: on ? 1 : 0.45,
              }}>
                <div style={{ fontWeight: 600, fontSize: 13 }}>
                  {T.sourceNames[src] ? T.sourceNames[src][lang] : src}
                </div>
                <div style={{ fontSize: 12, marginTop: 4, color: on ? '#2f9e57' : '#7a7a85' }}>
                  {on ? '● ' + (lang === 'ru' ? 'следит' : 'live') : '○ —'}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      <div style={{
        marginTop: 16, padding: '12px 14px', borderRadius: 8,
        background: isDefensive ? 'rgba(192,57,43,0.12)' : 'rgba(47,158,87,0.10)',
        border: '1px solid ' + (isDefensive ? '#c0392b' : '#2f9e57'),
      }}>
        <div style={{ fontSize: 12, textTransform: 'uppercase', letterSpacing: 0.5, opacity: 0.6 }}>
          {tr('posture', lang)}
        </div>
        <div style={{ fontWeight: 600, marginTop: 4, color: isDefensive ? '#e06c5f' : '#57c07f' }}>
          {isDefensive ? tr('defensive', lang) : tr('normal', lang)}
        </div>
        {active > 0 && status.posture_scopes && (
          <div style={{ fontSize: 12, marginTop: 6, opacity: 0.85 }}>
            {tr('scopes', lang)}: {status.posture_scopes.join(', ')}
          </div>
        )}
      </div>

      <div style={{ marginTop: 18 }}>
        <div style={{ fontSize: 12, textTransform: 'uppercase', letterSpacing: 0.5, opacity: 0.6, marginBottom: 8 }}>
          {tr('stream', lang)}
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: 6 }}>
          {signals.slice(0, 24).map((s, i) => (
            <div key={i} style={{
              display: 'flex', justifyContent: 'space-between', alignItems: 'center',
              border: '1px solid var(--border, #2a2a33)', borderRadius: 7, padding: '6px 10px', fontSize: 12,
            }}>
              <span style={{ opacity: 0.85 }}>
                <span style={{ opacity: 0.6 }}>{s.source}:</span> {s.scope}
              </span>
              <span style={{
                color: SEV_COLOR[s.severity] || '#888', fontWeight: 600, fontSize: 11,
              }}>
                {T.sev[s.severity] ? T.sev[s.severity][lang] : s.severity}
              </span>
            </div>
          ))}
        </div>
      </div>

      <div style={{ marginTop: 18 }}>
        <div style={{ fontSize: 12, textTransform: 'uppercase', letterSpacing: 0.5, opacity: 0.6, marginBottom: 8 }}>
          {tr('reactions', lang)}
        </div>
        {reactions.length === 0 ? (
          <div style={{ fontSize: 13, opacity: 0.6 }}>{tr('noReactions', lang)}</div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {reactions.slice().reverse().slice(0, 6).map((rx, i) => (
              <div key={i} style={{ fontSize: 12, opacity: 0.85, borderLeft: '2px solid #c78a00', paddingLeft: 10 }}>
                {(rx.actions || []).map((a) => a.kind + ' ' + a.scope).join(', ')}
                {rx.mode ? ' · ' + rx.mode : ''}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
