import { useState, useEffect, useCallback } from 'react';

/*
 * AggressiveLabLive — the honest "we paper-test N unstable aggressive strategies in parallel" board.
 * Each aggressive book runs its OWN $100k paper book; this shows every one live: current paper P&L +
 * days accrued (N/30) + its risk verdict + its DATED tail. Nothing here is live-allocated — advisory,
 * outside RiskPolicy v1.0, the strategies the desk REFUSES, shown WITH their real risk.
 *
 * Data: /api/aggressive-lab/paper (live per-book P&L, verbatim) + /api/aggressive-lab/scorecard
 * (verdict + backtest + dated tail windows, verbatim). Fail-CLOSED: offline → honest "unavailable".
 * No fabricated number — a thin (<30d) track is labelled accruing; a flat book as awaiting-feed.
 *
 * SWARM enrichment (block 6, docs/SWARM_ARCHITECTURE.md): /api/swarm/regime (GREEN/YELLOW/RED
 * carry weather) + /api/swarm/guardian (per-book L2 guardian: ARMED/DERISKED + live vol-ratio).
 * Both fail-closed — swarm offline → badges simply absent, never invented.
 */

const API =
  typeof window !== 'undefined' &&
  (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1')
    ? 'http://localhost:8765'
    : 'https://api.earn-defi.com';

const POLL_MS = 30_000;
const T = 8_000;

function getLang() {
  if (typeof window === 'undefined') return 'en';
  try {
    return (window.localStorage.getItem('spa_lang') || document.documentElement.lang || 'en').startsWith('ru') ? 'ru' : 'en';
  } catch { return 'en'; }
}

const VERDICT = {
  SEVERE_TAIL:        { en: 'Severe tail',        ru: 'Тяжёлый хвост',      color: '#f87171', bg: 'rgba(248,113,113,0.12)' },
  RISK_COMPENSATION:  { en: 'Risk-compensation',  ru: 'Плата за риск',      color: '#fbbf24', bg: 'rgba(251,191,36,0.12)' },
  INSUFFICIENT_DATA:  { en: 'Insufficient data',  ru: 'Мало данных',        color: '#94a3b8', bg: 'rgba(148,163,184,0.12)' },
};
const STATUS = {
  accruing:      { en: 'accruing', ru: 'копится' },
  awaiting_feed: { en: 'awaiting feed', ru: 'ждёт фид' },
  mature:        { en: 'mature', ru: 'зрелый' },
  killed:        { en: 'killed', ru: 'kill' },
  unknown:       { en: '—', ru: '—' },
};

// Swarm carry-weather (funding regime) + per-book guardian badges — fail-closed: absent when
// the swarm surface is unreachable, NEVER defaulted to green.
const REGIME = {
  GREEN:   { en: 'carry weather: GREEN',   ru: 'погода carry: GREEN',   color: '#34d399', bg: 'rgba(52,211,153,0.12)' },
  YELLOW:  { en: 'carry weather: YELLOW',  ru: 'погода carry: YELLOW',  color: '#fbbf24', bg: 'rgba(251,191,36,0.12)' },
  RED:     { en: 'carry weather: RED',     ru: 'погода carry: RED',     color: '#f87171', bg: 'rgba(248,113,113,0.12)' },
  UNKNOWN: { en: 'carry weather: UNKNOWN (fail-closed)', ru: 'погода carry: UNKNOWN (fail-closed)', color: '#94a3b8', bg: 'rgba(148,163,184,0.12)' },
};
const GUARD = {
  ARMED:    { en: 'guardian armed',    ru: 'страж на посту', color: '#34d399' },
  DERISKED: { en: 'guardian DERISKED', ru: 'страж ДЕ-РИСК',  color: '#f87171' },
};

function fmtPct(x) {
  return (typeof x === 'number' && isFinite(x)) ? `${x >= 0 ? '+' : ''}${x.toFixed(2)}%` : '—';
}
function fmtBt(x) {
  return (typeof x === 'number' && isFinite(x)) ? `${x >= 0 ? '+' : ''}${x.toFixed(1)}%` : '—';
}

export default function AggressiveLabLive() {
  const [paper, setPaper] = useState(undefined);
  const [scores, setScores] = useState(undefined);
  const [swarmGuardian, setSwarmGuardian] = useState(null);
  const [swarmRegime, setSwarmRegime] = useState(null);
  const [lang, setLang] = useState('en');

  useEffect(() => {
    setLang(getLang());
    const onStorage = () => setLang(getLang());
    window.addEventListener('storage', onStorage);
    const obs = new MutationObserver(() => setLang(getLang()));
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ['lang'] });
    return () => { window.removeEventListener('storage', onStorage); obs.disconnect(); };
  }, []);

  const poll = useCallback(async () => {
    const get = async (path) => {
      try {
        const r = await fetch(API + path, { signal: AbortSignal.timeout(T), headers: { Accept: 'application/json' } });
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return await r.json();
      } catch { return null; }
    };
    const [p, s, g, r] = await Promise.all([
      get('/api/aggressive-lab/paper'), get('/api/aggressive-lab/scorecard'),
      get('/api/swarm/guardian'), get('/api/swarm/regime'),
    ]);
    setPaper(p); setScores(s);
    setSwarmGuardian(g && g.available ? g : null);
    setSwarmRegime(r && r.available ? r : null);
  }, []);

  useEffect(() => { poll(); const id = setInterval(poll, POLL_MS); return () => clearInterval(id); }, [poll]);

  const ru = lang === 'ru';
  if (paper === undefined) return <p style={{ color: 'var(--text-muted)' }}>{ru ? 'Загрузка…' : 'Loading…'}</p>;
  if (!paper || !paper.available) {
    return <p style={{ color: 'var(--text-muted)' }}>{ru ? 'Живые paper-данные временно недоступны.' : 'Live paper data temporarily unavailable.'}</p>;
  }

  const rows = (scores && Array.isArray(scores.strategies)) ? scores.strategies : [];
  const byId = {};
  for (const r of rows) byId[r.strategy_id || r.id] = r;

  const books = (paper.books || []).map((b) => {
    const sc = byId[b.id] || {};
    const worst = sc.tail && Array.isArray(sc.tail.windows)
      ? sc.tail.windows.reduce((a, w) => {
          const dd = w.in_sample && w.in_sample.worst_dd_pct;
          return (typeof dd === 'number' && dd > (a.dd || 0)) ? { dd, label: w.label } : a;
        }, {})
      : {};
    return {
      id: b.id,
      name: b.id.replace(/_/g, ' '),
      days: b.days, ret: b.return_pct, days_to_30: b.days_to_30, status: b.status,
      risk_class: sc.risk_class || '—',
      verdict: sc.verdict || 'INSUFFICIENT_DATA',
      backtest: (typeof sc.net_return_pct === 'number') ? sc.net_return_pct : null,
      maxdd: (typeof sc.max_drawdown_pct === 'number') ? Math.abs(sc.max_drawdown_pct) : (sc.tail && sc.tail.worst_tail_dd_pct) || null,
      worstEvent: worst.label || null,
      note: sc.note || '',
    };
  });

  const nSevere = books.filter((b) => b.verdict === 'SEVERE_TAIL').length;

  // Swarm overlays (fail-closed: absent when the swarm surface is down — never invented)
  const gBooks = (swarmGuardian && swarmGuardian.books) || {};
  const nArmed = Object.values(gBooks).filter((g) => g.state === 'ARMED').length;
  const nDerisked = Object.values(gBooks).filter((g) => g.state === 'DERISKED').length;
  const regime = swarmRegime && REGIME[swarmRegime.regime] ? swarmRegime.regime : null;
  const regimeCarry = regime && swarmRegime.symbols && swarmRegime.symbols.ETH
    && swarmRegime.symbols.ETH.metrics ? swarmRegime.symbols.ETH.metrics.carry_ann_pct_7d : null;

  return (
    <div>
      {/* honest header */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '10px', marginBottom: '18px' }}>
        <Stat n={books.length} label={ru ? 'стратегий на живом paper-тесте' : 'strategies on live paper test'} />
        <Stat n={nSevere} label={ru ? 'с тяжёлым хвостом' : 'with a severe tail'} color="#f87171" />
        <Stat n="$100k" label={ru ? 'на каждую книгу' : 'per book'} />
        {swarmGuardian ? (
          <Stat n={nDerisked > 0 ? `${nArmed}/${nDerisked}` : nArmed}
                label={nDerisked > 0
                  ? (ru ? 'стражей на посту / де-риск' : 'guardians armed / derisked')
                  : (ru ? 'стражей на посту (рой)' : 'guardians armed (swarm)')}
                color={nDerisked > 0 ? '#f87171' : '#34d399'} />
        ) : null}
      </div>

      {/* swarm carry-weather strip — shown only when the swarm surface answers (fail-closed) */}
      {regime ? (
        <div style={{ display: 'inline-flex', alignItems: 'center', gap: '8px', marginBottom: '16px',
                      fontSize: '12px', fontWeight: 600, color: REGIME[regime].color,
                      background: REGIME[regime].bg, padding: '5px 12px', borderRadius: '999px' }}>
          <span aria-hidden="true" style={{ width: 8, height: 8, borderRadius: '50%', background: REGIME[regime].color }} />
          {REGIME[regime][lang] || REGIME[regime].en}
          {typeof regimeCarry === 'number' ? <span style={{ fontWeight: 400 }}>· ETH carry ≈ {regimeCarry.toFixed(1)}% ann</span> : null}
        </div>
      ) : null}
      <p style={{ fontSize: '13px', color: 'var(--text-muted)', marginBottom: '18px', lineHeight: 1.6 }}>
        {ru
          ? 'Мы параллельно paper-тестируем несколько нестабильных агрессивных стратегий — у каждой свой $100k и свой хвост. Ни одна НЕ идёт в live-капитал (advisory, вне RiskPolicy). Смотрите, какой ценой даётся доходность. Тонкий трек (<30 дней) — ещё не доверяемое число.'
          : 'We paper-test several unstable aggressive strategies in parallel — each on its own $100k, each with its own tail. NONE is live-allocated (advisory, outside RiskPolicy). See what the yield really costs. A thin track (<30 days) is not yet a trustworthy number.'}
      </p>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: '14px' }}>
        {books.map((b) => {
          const v = VERDICT[b.verdict] || VERDICT.INSUFFICIENT_DATA;
          const st = STATUS[b.status] || STATUS.unknown;
          return (
            <div key={b.id} style={{ border: '1px solid var(--border)', borderRadius: '12px', padding: '16px', background: 'var(--bg-elevated, rgba(255,255,255,0.02))' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '8px', marginBottom: '10px' }}>
                <span style={{ fontWeight: 600, fontSize: '15px', color: 'var(--text-primary)', textTransform: 'capitalize' }}>{b.name}</span>
                <span style={{ fontSize: '10px', fontWeight: 600, color: v.color, background: v.bg, padding: '3px 8px', borderRadius: '999px', whiteSpace: 'nowrap' }}>
                  {v[lang] || v.en} · {b.risk_class}
                </span>
              </div>

              {/* LIVE paper */}
              <div style={{ display: 'flex', alignItems: 'baseline', gap: '8px', marginBottom: '2px' }}>
                <span style={{ fontSize: '22px', fontWeight: 700, color: b.status === 'awaiting_feed' ? 'var(--text-muted)' : (b.ret >= 0 ? '#34d399' : '#f87171') }}>
                  {b.status === 'awaiting_feed' ? '—' : fmtPct(b.ret)}
                </span>
                <span style={{ fontSize: '11px', color: 'var(--text-faint)' }}>
                  {ru ? 'живой paper' : 'live paper'}
                </span>
              </div>
              <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginBottom: '10px' }}>
                {b.status === 'awaiting_feed'
                  ? (ru ? 'ждёт живой фид (0 дней)' : 'awaiting live feed (0 days)')
                  : `${b.days}/30 ${ru ? 'дней' : 'days'} · ${st[lang] || st.en}${b.days_to_30 ? ` · ${b.days_to_30} ${ru ? 'до подтверждения' : 'to verdict'}` : ''}`}
              </div>

              {/* backtest + tail (always shown) */}
              <div style={{ borderTop: '1px solid var(--border)', paddingTop: '10px', fontSize: '12px', color: 'var(--text-muted)', lineHeight: 1.7 }}>
                <div>{ru ? 'Бэктест 2.5г' : 'Backtest 2.5y'}: <b style={{ color: 'var(--text-secondary)' }}>{fmtBt(b.backtest)}</b></div>
                <div style={{ color: '#f87171' }}>
                  {ru ? 'Худшая просадка' : 'Worst drawdown'}: <b>{typeof b.maxdd === 'number' ? `−${b.maxdd.toFixed(1)}%` : '—'}</b>
                  {b.worstEvent ? <span style={{ color: 'var(--text-faint)' }}> · {b.worstEvent}</span> : null}
                </div>
                {(() => {
                  // L2 guardian badge (swarm block 6) — only when the swarm actually reports it
                  const g = gBooks[b.id];
                  if (!g || !GUARD[g.state]) return null;
                  const gd = GUARD[g.state];
                  const ratio = g.signal && typeof g.signal.ratio === 'number' ? g.signal.ratio : null;
                  return (
                    <div style={{ color: gd.color, display: 'flex', alignItems: 'center', gap: '6px' }}>
                      <span aria-hidden="true">🛡</span>
                      <span>{gd[lang] || gd.en}</span>
                      {ratio !== null ? (
                        <span style={{ color: 'var(--text-faint)' }}>
                          · vol {ratio.toFixed(2)}/2.0{ratio >= 1.5 && g.state === 'ARMED' ? (ru ? ' ⚠ близко к порогу' : ' ⚠ near threshold') : ''}
                        </span>
                      ) : null}
                    </div>
                  );
                })()}
              </div>
            </div>
          );
        })}
      </div>

      <p style={{ fontSize: '11px', color: 'var(--text-faint)', marginTop: '16px', lineHeight: 1.6 }}>
        {ru
          ? 'Живой P&L → /api/aggressive-lab/paper · вердикт+хвост → /api/aggressive-lab/scorecard · стражи роя → /api/swarm/guardian · погода carry → /api/swarm/regime (всё verbatim, fail-closed, hash-chain proof в data/swarm/). Advisory / вне RiskPolicy v1.0 / никогда не аллоцируется в live. Числа evidence-tagged, не выдуманы. Рой следит и де-рискует на бумаге; gap-риск (эксплойт/мгновенный депег) стражи НЕ покрывают — он в хвосте.'
          : 'Live P&L → /api/aggressive-lab/paper · verdict+tail → /api/aggressive-lab/scorecard · swarm guardians → /api/swarm/guardian · carry weather → /api/swarm/regime (all verbatim, fail-closed, hash-chain proofs in data/swarm/). Advisory / outside RiskPolicy v1.0 / never live-allocated. Numbers are evidence-tagged, not fabricated. The swarm watches and de-risks on paper; gap risk (exploit/instant depeg) is NOT covered by guardians — it stays in the tail.'}
      </p>
    </div>
  );
}

function Stat({ n, label, color }) {
  return (
    <div style={{ border: '1px solid var(--border)', borderRadius: '10px', padding: '10px 14px', minWidth: '120px' }}>
      <div style={{ fontSize: '22px', fontWeight: 700, color: color || 'var(--text-primary)' }}>{n}</div>
      <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{label}</div>
    </div>
  );
}
