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

function fmtPct(x) {
  return (typeof x === 'number' && isFinite(x)) ? `${x >= 0 ? '+' : ''}${x.toFixed(2)}%` : '—';
}
function fmtBt(x) {
  return (typeof x === 'number' && isFinite(x)) ? `${x >= 0 ? '+' : ''}${x.toFixed(1)}%` : '—';
}

export default function AggressiveLabLive() {
  const [paper, setPaper] = useState(undefined);
  const [scores, setScores] = useState(undefined);
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
    const [p, s] = await Promise.all([get('/api/aggressive-lab/paper'), get('/api/aggressive-lab/scorecard')]);
    setPaper(p); setScores(s);
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

  return (
    <div>
      {/* honest header */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '10px', marginBottom: '18px' }}>
        <Stat n={books.length} label={ru ? 'стратегий на живом paper-тесте' : 'strategies on live paper test'} />
        <Stat n={nSevere} label={ru ? 'с тяжёлым хвостом' : 'with a severe tail'} color="#f87171" />
        <Stat n="$100k" label={ru ? 'на каждую книгу' : 'per book'} />
      </div>
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
              </div>
            </div>
          );
        })}
      </div>

      <p style={{ fontSize: '11px', color: 'var(--text-faint)', marginTop: '16px', lineHeight: 1.6 }}>
        {ru
          ? 'Живой P&L → /api/aggressive-lab/paper · вердикт+хвост → /api/aggressive-lab/scorecard (verbatim, fail-closed). Advisory / вне RiskPolicy v1.0 / никогда не аллоцируется в live. Числа evidence-tagged, не выдуманы.'
          : 'Live P&L → /api/aggressive-lab/paper · verdict+tail → /api/aggressive-lab/scorecard (verbatim, fail-closed). Advisory / outside RiskPolicy v1.0 / never live-allocated. Numbers are evidence-tagged, not fabricated.'}
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
