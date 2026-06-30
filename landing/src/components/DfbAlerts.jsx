import { useState, useEffect, useMemo, useCallback } from 'react';

/*
 * DfbAlerts.jsx — THE DFB alert feed (Month-2 Lane-B / WS-2.3).
 *
 * "DeBank tells you what changed; DFB tells you when a pool you watch just became one the
 *  desk would REFUSE." The killer alert is REFUSAL_FLIP (SAFE/WATCH → REFUSE).
 *
 * CONSUMES Lane-2's read-only contract (we never recompute or soften the signal):
 *   GET /api/dfb/alerts  → severity-ranked alert feed (REFUSAL_FLIP first); each alert:
 *     { type, severity, severity_rank, pool_id, protocol, chain, asset,
 *       as_of, prev_as_of, message, detail, kill_reason, tail_veto, row_hash }
 *
 * HONESTY CONTRACT (fail-CLOSED, red-team hardened):
 *   - The alert TYPE + severity render STRAIGHT from the API — never recomputed/softened.
 *   - REFUSAL_FLIP renders at the TOP, color-coded critical; it can never be hidden.
 *   - API offline OR no alerts → honest empty-state, never a fabricated alert.
 *
 * WATCHLIST: a single-user, localStorage-only watchlist (key `dfb_watchlist`), exactly like
 * the academy progress — NO accounts, NO server state. A "watch this pool" toggle on each
 * alert + a "Watched only" filter so the analyst tracks specific pools. The API also accepts
 * a pool_id filter (a watchlist consumer can request one pool's set), used by the pool-detail.
 *
 * Bilingual via the site's spa_lang mechanism.
 */

const WATCHLIST_KEY = 'dfb_watchlist';

function apiBase() {
  if (typeof location === 'undefined') return 'https://api.earn-defi.com';
  return (location.hostname === 'localhost' || location.hostname === '127.0.0.1')
    ? 'http://localhost:8765'
    : 'https://api.earn-defi.com';
}
function readLang() {
  try { return (localStorage.getItem('spa_lang') || 'en') === 'ru' ? 'ru' : 'en'; } catch (e) { return 'en'; }
}
function readWatchlist() {
  try {
    const raw = localStorage.getItem(WATCHLIST_KEY);
    const arr = raw ? JSON.parse(raw) : [];
    return Array.isArray(arr) ? arr.filter((x) => typeof x === 'string') : [];
  } catch (e) { return []; }
}
function writeWatchlist(list) {
  try { localStorage.setItem(WATCHLIST_KEY, JSON.stringify(Array.from(new Set(list)))); } catch (e) {}
}

// Severity color tokens (critical worst → medium). Verbatim from the API's severity bucket.
const SEV_STYLE = {
  critical: { bg: 'rgba(242,109,109,.14)', bd: 'rgba(242,109,109,.45)', fg: '#F26D6D', ru: 'критично' },
  high:     { bg: 'rgba(242,150,60,.13)',  bd: 'rgba(242,150,60,.40)',  fg: '#F2963C', ru: 'высокая' },
  medium:   { bg: 'rgba(242,181,60,.12)',  bd: 'rgba(242,181,60,.35)',  fg: '#F2B53C', ru: 'средняя' },
};
const SEV_FALLBACK = { bg: 'rgba(107,114,128,.12)', bd: 'rgba(107,114,128,.30)', fg: '#9aa3b2', ru: 'неизв.' };
function sevStyle(s) { return SEV_STYLE[String(s || '').toLowerCase()] || SEV_FALLBACK; }

// Human alert-type labels (the API gives the machine type; we present it).
const TYPE_LABEL = {
  REFUSAL_FLIP:        { en: 'Refusal flip → REFUSE', ru: 'Флип в ОТКАЗ' },
  EXIT_LIQUIDITY_DROP: { en: 'Exit liquidity collapse', ru: 'Обвал ликвидности выхода' },
  PEG_IL_SPIKE:        { en: 'Peg / structural spike', ru: 'Скачок пега / структуры' },
  APY_COLLAPSE:        { en: 'APY collapse', ru: 'Обвал APY' },
  TVL_DRAIN:           { en: 'TVL drain', ru: 'Отток TVL' },
};
function typeLabel(t, ru) { const m = TYPE_LABEL[t]; return m ? (ru ? m.ru : m.en) : (t || '?'); }

export default function DfbAlerts() {
  const [ru, setRu] = useState(false);
  const [state, setState] = useState('loading'); // loading | live | offline
  const [alerts, setAlerts] = useState([]);
  const [summary, setSummary] = useState(null);
  const [asOf, setAsOf] = useState(null);
  const [watchlist, setWatchlist] = useState([]);

  const [fSev, setFSev] = useState('ALL');     // ALL | critical | high | medium
  const [fType, setFType] = useState('ALL');
  const [watchedOnly, setWatchedOnly] = useState(false);

  // Language sync.
  useEffect(() => {
    setRu(readLang() === 'ru');
    setWatchlist(readWatchlist());
    const onLang = () => setRu(readLang() === 'ru');
    window.addEventListener('spa:lang', onLang);
    const prev = window.__renderLive;
    window.__renderLive = function () { try { onLang(); } catch (e) {} if (typeof prev === 'function') { try { prev(); } catch (e) {} } };
    return () => { window.removeEventListener('spa:lang', onLang); window.__renderLive = prev; };
  }, []);

  const load = useCallback(() => {
    const base = apiBase();
    fetch(base + '/api/dfb/alerts')
      .then((r) => r.json())
      .then((v) => {
        const list = v && Array.isArray(v.alerts) ? v.alerts : null;
        if (list) {
          setAlerts(list);
          setSummary(v);
          setAsOf(v.as_of || null);
          // available=true means the feed is live (even if 0 alerts → a quiet board, still live).
          setState(v.available === false && list.length === 0 ? 'offline' : 'live');
        } else {
          setAlerts([]); setState('offline');
        }
      })
      .catch(() => { setAlerts([]); setState('offline'); });
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, 60_000);
    return () => clearInterval(id);
  }, [load]);

  const isWatched = useCallback((pid) => watchlist.includes(pid), [watchlist]);
  const toggleWatch = useCallback((pid) => {
    setWatchlist((cur) => {
      const next = cur.includes(pid) ? cur.filter((x) => x !== pid) : [...cur, pid];
      writeWatchlist(next);
      return next;
    });
  }, []);

  const types = useMemo(() => {
    const s = new Set();
    alerts.forEach((a) => { if (a.type) s.add(a.type); });
    return Array.from(s);
  }, [alerts]);

  const view = useMemo(() => {
    let rows = alerts.slice();
    if (fSev !== 'ALL') rows = rows.filter((a) => String(a.severity || '').toLowerCase() === fSev);
    if (fType !== 'ALL') rows = rows.filter((a) => a.type === fType);
    if (watchedOnly) rows = rows.filter((a) => watchlist.includes(a.pool_id));
    // The API already severity-ranks (REFUSAL_FLIP first); preserve that order.
    rows.sort((a, b) => (a.severity_rank ?? 99) - (b.severity_rank ?? 99));
    return rows;
  }, [alerts, fSev, fType, watchedOnly, watchlist]);

  const T = (en, r) => (ru ? r : en);
  const nFlips = summary && summary.n_refusal_flips != null
    ? summary.n_refusal_flips
    : alerts.filter((a) => a.type === 'REFUSAL_FLIP').length;

  const tiles = [
    { lbl: T('Active alerts', 'Активных алертов'), v: String(alerts.length) },
    { lbl: T('Refusal flips (killer)', 'Флипы в отказ (killer)'), v: String(nFlips), fg: '#F26D6D' },
    { lbl: T('Watching', 'В наблюдении'), v: String(watchlist.length), fg: '#79A4F5' },
    { lbl: T('As of', 'На дату'), v: asOf || '—' },
  ];

  return (
    <div>
      {/* state chip */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap', marginBottom: 16 }}>
        <span style={{
          display: 'inline-flex', alignItems: 'center', gap: 7, fontFamily: 'var(--font-mono)', fontSize: 12,
          padding: '4px 10px', borderRadius: 999,
          background: state === 'live' ? 'rgba(52,211,153,.10)' : 'rgba(107,114,128,.10)',
          border: '1px solid ' + (state === 'live' ? 'rgba(52,211,153,.30)' : 'var(--border)'),
          color: state === 'live' ? '#34D399' : 'var(--text-muted)',
        }}>
          <span style={{ width: 7, height: 7, borderRadius: '50%', background: state === 'live' ? '#34D399' : 'var(--text-muted)', animation: state === 'live' ? 'pulse 3s ease-in-out infinite' : 'none' }} />
          {state === 'loading' ? T('Loading…', 'Загрузка…') : state === 'live' ? T('Live from api.earn-defi.com', 'Вживую с api.earn-defi.com') : T('API unavailable', 'API недоступно')}
        </span>
      </div>

      {/* summary tiles */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(150px,1fr))', gap: 12, marginBottom: 20 }}>
        {tiles.map((t, i) => (
          <div key={i} style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)', borderRadius: 12, padding: '14px 16px' }}>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, textTransform: 'uppercase', letterSpacing: '.08em', color: 'var(--text-muted)', marginBottom: 6 }}>{t.lbl}</div>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 22, fontWeight: 700, color: t.fg || 'var(--text-primary)' }}>{t.v}</div>
          </div>
        ))}
      </div>

      {/* filters */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, alignItems: 'center', marginBottom: 16 }}>
        <FilterSelect label={T('Severity', 'Серьёзность')} value={fSev} onChange={setFSev}
          options={[['ALL', T('All', 'Все')], ['critical', T('Critical', 'Критич.')], ['high', T('High', 'Высокая')], ['medium', T('Medium', 'Средняя')]]} />
        <FilterSelect label={T('Type', 'Тип')} value={fType} onChange={setFType}
          options={[['ALL', T('All', 'Все')], ...types.map((t) => [t, typeLabel(t, ru)])]} />
        <label style={{ display: 'inline-flex', alignItems: 'center', gap: 7, fontSize: 13, color: 'var(--text-secondary)', cursor: 'pointer' }}>
          <input type="checkbox" checked={watchedOnly} onChange={(e) => setWatchedOnly(e.target.checked)} />
          {T('Watched only', 'Только наблюдаемые')}
        </label>
      </div>

      {/* feed */}
      {state === 'loading' && (
        <div style={{ padding: '32px 16px', textAlign: 'center', color: 'var(--text-muted)' }}>{T('Loading the alert feed…', 'Загрузка ленты алертов…')}</div>
      )}
      {state === 'offline' && (
        <div style={{ padding: '32px 16px', textAlign: 'center', color: 'var(--text-muted)', border: '1px solid var(--border)', borderRadius: 16 }}>
          {T('API unavailable — the alert feed does not show fabricated alerts offline.', 'API недоступно — лента не показывает выдуманные алерты офлайн.')}
        </div>
      )}
      {state === 'live' && view.length === 0 && (
        <div style={{ padding: '32px 16px', textAlign: 'center', color: 'var(--text-muted)', border: '1px solid var(--border)', borderRadius: 16 }}>
          {alerts.length === 0
            ? T('No alerts firing — no pool has crossed a kill threshold. (A quiet board is an honest board.)', 'Нет алертов — ни один пул не пересёк порог. (Тихий борд — честный борд.)')
            : T('No alerts match the filters.', 'Нет алертов по фильтрам.')}
        </div>
      )}
      {state === 'live' && view.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {view.map((a) => (
            <AlertCard key={(a.pool_id || '') + '|' + (a.type || '') + '|' + (a.as_of || '')}
              alert={a} ru={ru} T={T} watched={isWatched(a.pool_id)} onWatch={() => toggleWatch(a.pool_id)} />
          ))}
        </div>
      )}
    </div>
  );
}

function FilterSelect({ label, value, onChange, options }) {
  return (
    <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12, fontFamily: 'var(--font-mono)', color: 'var(--text-muted)' }}>
      {label}
      <select value={value} onChange={(e) => onChange(e.target.value)} style={{
        background: 'var(--bg-surface)', border: '1px solid var(--border)', borderRadius: 8,
        color: 'var(--text-secondary)', padding: '5px 8px', fontFamily: 'var(--font-mono)', fontSize: 12,
      }}>
        {options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
      </select>
    </label>
  );
}

function AlertCard({ alert, ru, T, watched, onWatch }) {
  const ss = sevStyle(alert.severity);
  const isFlip = alert.type === 'REFUSAL_FLIP';
  const detailHref = '/board/pool?id=' + encodeURIComponent(alert.pool_id || '');
  const sevWord = ru ? ss.ru : String(alert.severity || 'unknown');
  return (
    <div style={{
      border: '1px solid ' + ss.bd, borderLeft: '4px solid ' + ss.fg, borderRadius: 12,
      background: isFlip ? ss.bg : 'var(--bg-surface)', padding: '14px 16px',
      display: 'flex', gap: 14, alignItems: 'flex-start', justifyContent: 'space-between', flexWrap: 'wrap',
    }}>
      <div style={{ minWidth: 0, flex: '1 1 320px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 6 }}>
          <span style={{
            display: 'inline-flex', alignItems: 'center', gap: 5, padding: '2px 8px', borderRadius: 6,
            fontFamily: 'var(--font-mono)', fontSize: 11, fontWeight: 700,
            background: ss.bg, border: '1px solid ' + ss.bd, color: ss.fg, textTransform: 'uppercase',
          }}>
            <span style={{ width: 6, height: 6, borderRadius: '50%', background: ss.fg }} />{sevWord}
          </span>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--text-secondary)' }}>
            {typeLabel(alert.type, ru)}
          </span>
          {alert.tail_veto && (
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: '#F26D6D', border: '1px solid rgba(242,109,109,.35)', borderRadius: 5, padding: '1px 5px' }}>tail-veto</span>
          )}
        </div>
        <a href={detailHref} style={{ color: 'var(--text-primary)', fontWeight: 600, fontSize: 14 }}>
          {(alert.protocol || '?')} · {(alert.asset || '?')} <span style={{ color: 'var(--text-muted)', fontWeight: 400 }}>· {(alert.chain || '?')}</span>
        </a>
        <div style={{ fontSize: 13, color: 'var(--text-secondary)', marginTop: 4, lineHeight: 1.5 }}>{alert.message || ''}</div>
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-faint)', marginTop: 5 }}>
          {alert.prev_as_of ? (alert.prev_as_of + ' → ') : ''}{alert.as_of || ''}
          {alert.kill_reason ? ' · engine: ' + alert.kill_reason : ''}
          {alert.row_hash ? ' · #' + String(alert.row_hash).slice(0, 8) : ''}
        </div>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6, alignItems: 'flex-end' }}>
        <button onClick={onWatch} title={watched ? T('Stop watching this pool', 'Перестать наблюдать') : T('Watch this pool', 'Наблюдать за пулом')}
          style={{
            cursor: 'pointer', fontFamily: 'var(--font-mono)', fontSize: 12, padding: '6px 10px', borderRadius: 8,
            background: watched ? 'rgba(121,164,245,.14)' : 'var(--bg-base)',
            border: '1px solid ' + (watched ? 'rgba(121,164,245,.40)' : 'var(--border)'),
            color: watched ? '#79A4F5' : 'var(--text-muted)', whiteSpace: 'nowrap',
          }}>
          {watched ? (ru ? '★ наблюдаю' : '★ watching') : (ru ? '☆ наблюдать' : '☆ watch')}
        </button>
        <a href={detailHref} style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--data-teal)' }}>
          {T('detail →', 'детали →')}
        </a>
      </div>
    </div>
  );
}
