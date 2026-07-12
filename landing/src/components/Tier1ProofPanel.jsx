import { useState, useEffect } from 'react';

/*
 * Tier1ProofPanel — the Tier-1 differentiator strip on /track-record (swarm round-2).
 * Shows what NO yield product publishes: a real-time SHADOW guardian watching the live
 * conservative track (signal-only, zero authority — RiskPolicy v1.0 is the sole gate) and the
 * S2 lead-time ledger INCLUDING false alarms (the cost side, published with the same weight).
 * Data: /api/tier1/proof (verbatim, fail-closed). API down → the strip simply doesn't render —
 * proof surfaces are never faked.
 */

const API =
  typeof window !== 'undefined' &&
  (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1')
    ? 'http://localhost:8765'
    : 'https://api.earn-defi.com';

function getLang() {
  if (typeof window === 'undefined') return 'en';
  try {
    return (window.localStorage.getItem('spa_lang') || document.documentElement.lang || 'en').startsWith('ru') ? 'ru' : 'en';
  } catch { return 'en'; }
}

export default function Tier1ProofPanel() {
  const [doc, setDoc] = useState(null);
  const [lang, setLang] = useState('en');

  useEffect(() => {
    setLang(getLang());
    const obs = new MutationObserver(() => setLang(getLang()));
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ['lang'] });
    (async () => {
      try {
        const r = await fetch(API + '/api/tier1/proof', { signal: AbortSignal.timeout(8000) });
        if (r.ok) setDoc(await r.json());
      } catch { /* fail-closed: no strip */ }
    })();
    return () => obs.disconnect();
  }, []);

  if (!doc) return null;
  const ru = lang === 'ru';
  const g = doc.shadow_guardian_live_track || {};
  const lt = doc.leadtime_ledger || {};
  const score = lt.score || {};
  const armed = g.state === 'ARMED';

  const Card = ({ title, value, sub, color }) => (
    <div style={{ border: '1px solid var(--border)', borderRadius: '10px', padding: '12px 14px', flex: '1 1 180px', minWidth: '170px' }}>
      <div style={{ fontSize: '10px', textTransform: 'uppercase', letterSpacing: '0.08em', color: 'var(--text-faint)', marginBottom: '4px' }}>{title}</div>
      <div style={{ fontSize: '17px', fontWeight: 700, color: color || 'var(--text-primary)' }}>{value}</div>
      {sub ? <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '2px', lineHeight: 1.5 }}>{sub}</div> : null}
    </div>
  );

  return (
    <div style={{ margin: '18px 0' }}>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '10px' }}>
        {g.available ? (
          <Card
            title={ru ? '🛡 Страж-тень на живом треке' : '🛡 Shadow guardian on the live track'}
            value={armed ? (ru ? 'НА ПОСТУ' : 'ARMED') : g.state || '—'}
            color={armed ? '#34d399' : '#fbbf24'}
            sub={(typeof g.vol_ratio === 'number' ? `vol ${g.vol_ratio.toFixed(2)}/2.0 · ` : '')
              + (ru ? `${g.days_watched || 0} дней под наблюдением · полномочий НОЛЬ (только сигнал)` : `${g.days_watched || 0} days watched · ZERO authority (signal-only)`)}
          />
        ) : null}
        {lt.available ? (
          <Card
            title={ru ? 'Леджер опережения (S2)' : 'Lead-time ledger (S2)'}
            value={`${score.led ?? 0} ${ru ? 'спасений' : 'saves'} · ${score.false_alarms ?? 0} ${ru ? 'ложных' : 'false alarms'}`}
            color={(score.false_alarms ?? 0) > (score.led ?? 0) ? '#fbbf24' : 'var(--text-primary)'}
            sub={ru
              ? `эпизодов: ${score.episodes ?? 0} · пропущено: ${score.missed ?? 0} — ложные тревоги публикуем с тем же весом, что и спасения`
              : `episodes: ${score.episodes ?? 0} · missed: ${score.missed ?? 0} — false alarms are published with the same weight as saves`}
          />
        ) : null}
      </div>
      <p style={{ fontSize: '11px', color: 'var(--text-faint)', marginTop: '8px', lineHeight: 1.6 }}>
        {ru
          ? 'Источник: /api/tier1/proof (verbatim, fail-closed). Тень наблюдает — но НЕ управляет: единственный гейт капитала — детерминированная RiskPolicy v1.0. Включение сигнала в живой цикл возможно только отдельным ADR после накопления леджера.'
          : 'Source: /api/tier1/proof (verbatim, fail-closed). The shadow watches — it does NOT act: the sole capital gate is the deterministic RiskPolicy v1.0. Wiring the signal into the live cycle requires a separate ADR once the ledger matures.'}
      </p>
    </div>
  );
}
