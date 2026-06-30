import { useState, useEffect, useCallback } from 'react';
import { getLang } from './progress.js';

/*
 * LiveAcademyData.jsx — pulls REAL system data so lessons show reality, not theory.
 *
 * One island, three feeds (pick via the `feed` prop):
 *   feed="refusals"   → GET /api/rates-desk/refusals  (the real refusal log)
 *   feed="golive"     → GET /api/v1/golive            (the live go-live track)
 *   feed="contrast"   → GET /api/aggressive-lab/annual-contrast (15%-vs-5% dated drawdowns)
 *
 * HONESTY CONTRACT (the whole point):
 *   - Fail-CLOSED. If the API is offline or returns a bad shape, the widget shows an
 *     honest «нет данных» / "no data" state — it NEVER fabricates a number, and never
 *     paints a stale or fake value as live.
 *
 * PROPS:
 *   feed   "refusals" | "golive" | "contrast"   REQUIRED
 *   limit  number   optional (refusals) — how many rows to show (default 6)
 */

const API =
  typeof window !== 'undefined' &&
  (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1')
    ? 'http://localhost:8765'
    : 'https://api.earn-defi.com';
const FETCH_TIMEOUT_MS = 8000;
const POLL_MS = 30000;

const T = {
  live: { ru: 'Живой API', en: 'Live API' },
  offline: { ru: 'API офлайн', en: 'API offline' },
  noData: { ru: 'Нет данных — API недоступен. Здесь мы НИКОГДА не показываем выдуманное число.', en: 'No data — API offline. We NEVER show a fabricated number here.' },
  loading: { ru: 'Загрузка…', en: 'Loading…' },
  refusalsTitle: { ru: 'Реальный лог отказов (refusal-first)', en: 'Real refusal log (refusal-first)' },
  goliveTitle: { ru: 'Живой go-live трек', en: 'Live go-live track' },
  contrastTitle: { ru: '15% против реальных 5% — датированные drawdown\'ы', en: '15% vs real 5% — dated drawdowns' },
  refused: { ru: 'ОТКАЗ', en: 'REFUSED' },
  approved: { ru: 'допущено', en: 'approved' },
  reason: { ru: 'причина', en: 'reason' },
  days: { ru: 'evidenced дней', en: 'evidenced days' },
  criteria: { ru: 'критериев пройдено', en: 'criteria passed' },
  steady: { ru: 'устойчивая книга', en: 'steady book' },
  aggressive: { ru: 'агрессивная книга', en: 'aggressive book' },
  maxdd: { ru: 'макс. просадка', en: 'max drawdown' },
};

export default function LiveAcademyData({ feed, limit = 6 }) {
  const [lang, setLang] = useState('ru');
  const [state, setState] = useState('loading'); // loading | live | offline
  const [data, setData] = useState(null);

  useEffect(() => {
    setLang(getLang());
    const onLang = () => setLang(getLang());
    window.addEventListener('storage', onLang);
    const obs = new MutationObserver(() => setLang(getLang()));
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ['lang'] });
    return () => { window.removeEventListener('storage', onLang); obs.disconnect(); };
  }, []);
  const tr = (k) => (T[k] ? (T[k][lang] ?? T[k].ru) : k);

  const path =
    feed === 'refusals' ? `/api/rates-desk/refusals?limit=${limit}` :
    feed === 'golive' ? '/api/v1/golive' :
    feed === 'contrast' ? '/api/aggressive-lab/annual-contrast' : null;

  const poll = useCallback(async () => {
    if (!path) { setState('offline'); return; }
    try {
      const r = await fetch(API + path, { signal: AbortSignal.timeout(FETCH_TIMEOUT_MS), headers: { Accept: 'application/json' } });
      if (!r.ok) throw new Error('HTTP ' + r.status);
      const d = await r.json();
      if (!d || typeof d !== 'object') throw new Error('bad shape');
      setData(d); setState('live');
    } catch {
      setData(null); setState('offline'); // fail-CLOSED: honest no-data, never fabricated
    }
  }, [path]);

  useEffect(() => { poll(); const id = setInterval(poll, POLL_MS); return () => clearInterval(id); }, [poll]);

  const title = feed === 'refusals' ? tr('refusalsTitle') : feed === 'golive' ? tr('goliveTitle') : tr('contrastTitle');

  return (
    <div style={wrap}>
      <div style={head}>
        {title}
        <span style={{
          float: 'right', fontFamily: 'var(--font-mono)', fontSize: 10, padding: '2px 8px', borderRadius: 'var(--r-full)',
          border: `1px solid ${state === 'live' ? 'var(--ok)' : 'var(--warn)'}`, color: state === 'live' ? 'var(--ok)' : 'var(--warn)',
        }}>
          {state === 'live' ? '● ' + tr('live') : state === 'loading' ? tr('loading') : '○ ' + tr('offline')}
        </span>
      </div>

      {state === 'offline' && <div style={emptyBox}>{tr('noData')}</div>}
      {state === 'loading' && <div style={{ ...emptyBox, color: 'var(--text-muted)' }}>{tr('loading')}</div>}

      {state === 'live' && feed === 'refusals' && <Refusals data={data} tr={tr} lang={lang} />}
      {state === 'live' && feed === 'golive' && <GoLive data={data} tr={tr} />}
      {state === 'live' && feed === 'contrast' && <Contrast data={data} tr={tr} />}
    </div>
  );
}

function Refusals({ data, tr, lang }) {
  // tolerate several shapes: {refusals:[...]}, {decisions:[...]}, [...]
  const rows = Array.isArray(data) ? data : (data.refusals || data.decisions || data.entries || []);
  if (!Array.isArray(rows) || rows.length === 0) return <div style={emptyBox}>{tr('noData')}</div>;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {rows.slice(0, 8).map((row, i) => {
        const refused = row.approved === false || row.decision === 'REFUSE' || row.refused === true || (row.reason && row.reason !== 'APPROVED');
        const u = row.underlying || row.book || row.asset || '—';
        const reason = row.reason || row.kill_reason || row.detail || '';
        return (
          <div key={i} style={{ display: 'flex', justifyContent: 'space-between', gap: 10, padding: '8px 12px', borderRadius: 'var(--r-sm)', background: 'var(--bg-surface-2)', border: `1px solid ${refused ? 'var(--danger)' : 'var(--ok)'}`, fontSize: 13 }}>
            <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--text-primary)' }}>{String(u)}</span>
            <span style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              {reason && <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-muted)' }}>{String(reason).slice(0, 28)}</span>}
              <span style={{ fontWeight: 700, color: refused ? 'var(--danger)' : 'var(--ok)' }}>{refused ? tr('refused') : tr('approved')}</span>
            </span>
          </div>
        );
      })}
    </div>
  );
}

function GoLive({ data, tr }) {
  const passed = data.criteria_passed ?? data.passed ?? data.pass_count ?? (Array.isArray(data.criteria) ? data.criteria.filter((c) => c.passed || c.status === 'pass').length : null);
  const total = data.criteria_total ?? data.total ?? (Array.isArray(data.criteria) ? data.criteria.length : null);
  const days = data.evidenced_days ?? data.track_days ?? data.real_days ?? data.days ?? null;
  const needed = data.days_needed ?? 30;
  if (passed == null && days == null) return <div style={emptyBox}>{tr('noData')}</div>;
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
      <div style={miniCard}>
        <div style={miniLabel}>{tr('days')}</div>
        <div style={{ ...miniVal, color: 'var(--data-teal)' }}>{days != null ? `${days} / ${needed}` : '—'}</div>
      </div>
      <div style={miniCard}>
        <div style={miniLabel}>{tr('criteria')}</div>
        <div style={{ ...miniVal, color: 'var(--accent)' }}>{passed != null && total != null ? `${passed} / ${total}` : '—'}</div>
      </div>
    </div>
  );
}

function Contrast({ data, tr }) {
  const steady = data.stable_apy_pct ?? data.steady_apy_pct ?? data.conservative_apy_pct ?? null;
  const aggr = data.aggressive_apy_pct ?? data.aggressive_target_pct ?? null;
  const maxdd = data.aggressive_max_drawdown_pct ?? data.max_drawdown_pct ?? null;
  if (steady == null && aggr == null) return <div style={emptyBox}>{tr('noData')}</div>;
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12 }}>
      <div style={miniCard}><div style={miniLabel}>{tr('steady')}</div><div style={{ ...miniVal, color: 'var(--ok)' }}>{steady != null ? Number(steady).toFixed(1) + '%' : '—'}</div></div>
      <div style={miniCard}><div style={miniLabel}>{tr('aggressive')}</div><div style={{ ...miniVal, color: 'var(--warn)' }}>{aggr != null ? Number(aggr).toFixed(1) + '%' : '—'}</div></div>
      <div style={miniCard}><div style={miniLabel}>{tr('maxdd')}</div><div style={{ ...miniVal, color: 'var(--danger)' }}>{maxdd != null ? '−' + Math.abs(Number(maxdd)).toFixed(1) + '%' : '—'}</div></div>
    </div>
  );
}

const wrap = { background: 'var(--bg-surface)', border: '1px solid var(--border)', borderRadius: 'var(--r-lg)', padding: 24, margin: '28px 0' };
const head = { fontFamily: 'var(--font-mono)', fontSize: 12, letterSpacing: '0.12em', textTransform: 'uppercase', color: 'var(--accent)', marginBottom: 16 };
const emptyBox = { padding: '16px', borderRadius: 'var(--r-md)', border: '1px dashed var(--warn)', color: 'var(--warn)', fontSize: 13, lineHeight: 1.55, textAlign: 'center' };
const miniCard = { background: 'var(--bg-surface-2)', border: '1px solid var(--border)', borderRadius: 'var(--r-md)', padding: '12px 14px', textAlign: 'center' };
const miniLabel = { fontSize: 11, color: 'var(--text-muted)' };
const miniVal = { fontFamily: 'var(--font-mono)', fontSize: 20, fontWeight: 700, marginTop: 4 };
