import { useState, useEffect, useMemo, useCallback } from 'react';
import AnimatedChart from './academy/AnimatedChart.jsx';
import { classStyle, verdictStyle } from './DfbScreener.jsx';

/*
 * DfbPoolDetail.jsx — DFB pool detail (Lane-3 / WS-1.4).
 *
 * Client-rendered (the site builds output:'static', so we cannot getStaticPaths the live
 * universe at build time). Reads the pool id from ?id=<pool_id> and CONSUMES:
 *   GET /api/dfb/pool/{id}          → the full overlay object (same shape as a screener row)
 *   GET /api/dfb/pool/{id}/history  → [{date|ts, apy_total, apy_base, apy_reward, tvl_usd, ...}]
 *   GET /api/dfb/pool/{id}/proof    → { proof_hash, prev_hash, inputs, outputs, verify_with, spec }
 *
 * HONESTY CONTRACT (fail-CLOSED, red-team hardened):
 *   - risk_class + refusal verdict + haircuts render STRAIGHT from the API; not recomputed/softened.
 *   - An exit-NAV ticket flagged / with null absorbable renders as a HOLE ("no clearing exit"),
 *     never a fabricated absorbable number.
 *   - API offline / unknown id → honest "unavailable", never a stale-as-live or fabricated table.
 *   - Thin history (<2 points) → "INSUFFICIENT_DATA", never an extrapolated line.
 *   - The proof block shows the published hash + how to re-derive — "don't trust us, check us".
 */

function apiBase() {
  if (typeof location === 'undefined') return 'https://api.earn-defi.com';
  return (location.hostname === 'localhost' || location.hostname === '127.0.0.1')
    ? 'http://localhost:8765'
    : 'https://api.earn-defi.com';
}
function readLang() {
  try { return (localStorage.getItem('spa_lang') || 'en') === 'ru' ? 'ru' : 'en'; } catch (e) { return 'en'; }
}
function poolIdFromUrl() {
  try { return new URLSearchParams(location.search).get('id') || ''; } catch (e) { return ''; }
}
function num(x) { const n = Number(x); return Number.isFinite(n) ? n : null; }
function usd(x) {
  const n = num(x);
  if (n == null) return '—';
  if (Math.abs(n) >= 1e9) return '$' + (n / 1e9).toFixed(2) + 'B';
  if (Math.abs(n) >= 1e6) return '$' + (n / 1e6).toFixed(2) + 'M';
  if (Math.abs(n) >= 1e3) return '$' + (n / 1e3).toFixed(1) + 'k';
  return '$' + n.toFixed(0);
}
function pct(x) { const n = num(x); return n == null ? '—' : n.toFixed(2) + '%'; }
function fracPct(x) { const n = num(x); return n == null ? '—' : (n * 100).toFixed(1) + '%'; }

function Badge({ style, children, title }) {
  return (
    <span title={title} style={{
      display: 'inline-flex', alignItems: 'center', gap: 6, padding: '3px 10px',
      borderRadius: 6, fontFamily: 'var(--font-mono)', fontSize: 12, fontWeight: 600,
      background: style.bg, border: '1px solid ' + style.bd, color: style.fg, whiteSpace: 'nowrap',
    }}>{children}</span>
  );
}

export default function DfbPoolDetail() {
  const [ru, setRu] = useState(false);
  const [poolId] = useState(poolIdFromUrl());
  const [state, setState] = useState('loading'); // loading | live | offline | notfound
  const [pool, setPool] = useState(null);
  const [history, setHistory] = useState(null);
  const [proof, setProof] = useState(null);

  useEffect(() => {
    setRu(readLang() === 'ru');
    const onLang = () => setRu(readLang() === 'ru');
    window.addEventListener('spa:lang', onLang);
    const prev = window.__renderLive;
    window.__renderLive = function () { try { onLang(); } catch (e) {} if (typeof prev === 'function') { try { prev(); } catch (e) {} } };
    return () => { window.removeEventListener('spa:lang', onLang); window.__renderLive = prev; };
  }, []);

  const load = useCallback(() => {
    if (!poolId) { setState('notfound'); return; }
    const base = apiBase();
    const enc = encodeURIComponent(poolId);
    fetch(base + '/api/dfb/pool/' + enc).then((r) => {
      if (r.status === 404) { setState('notfound'); return null; }
      return r.json();
    }).then((d) => {
      if (d === null) return;            // 404 already handled
      if (!d || !d.pool_id) { setState('offline'); return; }
      setPool(d);
      setState('live');
    }).catch(() => setState('offline'));

    fetch(base + '/api/dfb/pool/' + enc + '/history').then((r) => r.json())
      .then((d) => { setHistory(Array.isArray(d) ? d : (d && Array.isArray(d.history) ? d.history : null)); })
      .catch(() => setHistory(null));

    fetch(base + '/api/dfb/pool/' + enc + '/proof').then((r) => r.json())
      .then((d) => { if (d && (d.proof_hash || d.verify_with)) setProof(d); })
      .catch(() => setProof(null));
  }, [poolId]);

  useEffect(() => { load(); }, [load]);

  const T = (en, r) => (ru ? r : en);

  if (state === 'loading') {
    return <P>{T('Loading the pool overlay…', 'Загрузка риск-оверлея пула…')}</P>;
  }
  if (state === 'notfound') {
    return <Empty title={T('Pool not found', 'Пул не найден')}
      body={poolId
        ? T('No pool with id "' + poolId + '" — DFB does not fabricate an entry.', 'Нет пула с id «' + poolId + '» — DFB не выдумывает запись.')
        : T('No pool id supplied. Open a pool from the board.', 'Не указан id пула. Откройте пул с риск-борда.')} />;
  }
  if (state === 'offline' || !pool) {
    return <Empty title={T('Unavailable', 'Недоступно')}
      body={T('API unavailable — the risk board does not show fabricated data offline.', 'API недоступно — риск-борд не показывает выдуманные данные офлайн.')} />;
  }

  const cs = classStyle(pool.risk_class);
  const verdict = String(pool.refusal && pool.refusal.verdict || '').toUpperCase();
  const vs = verdictStyle(verdict);
  const vLabel = ru ? vs.ru : (verdict || (ru ? 'НЕИЗВЕСТНО' : 'UNKNOWN'));
  const apy = pool.apy || {};
  const exitRows = Array.isArray(pool.exit_liquidity) ? pool.exit_liquidity : [];

  // ---- history chart (REAL series only; thin → INSUFFICIENT_DATA) ----
  const hist = Array.isArray(history) ? history : [];
  const apySeries = useMemo(() => {
    const pts = hist
      .map((h, i) => ({ x: num(h.ts) ?? i, y: num(h.apy_total != null ? h.apy_total : (h.apy && h.apy.total)) }))
      .filter((p) => p.y != null);
    return pts;
  }, [history]);
  const tvlSeries = useMemo(() => {
    const pts = hist
      .map((h, i) => ({ x: num(h.ts) ?? i, y: num(h.tvl_usd) }))
      .filter((p) => p.y != null);
    return pts;
  }, [history]);
  const histLabels = useMemo(() => {
    if (!hist.length) return [];
    const first = hist[0], last = hist[hist.length - 1];
    const lbl = (h) => String(h.date || h.day || (h.ts != null ? new Date(h.ts * 1000).toISOString().slice(0, 10) : ''));
    return [lbl(first), lbl(last)].filter(Boolean);
  }, [history]);

  return (
    <div>
      {/* live chip */}
      <div style={{ marginBottom: 14 }}>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 7, fontFamily: 'var(--font-mono)', fontSize: 12, padding: '4px 10px', borderRadius: 999, background: 'rgba(52,211,153,.10)', border: '1px solid rgba(52,211,153,.30)', color: '#34D399' }}>
          <span style={{ width: 7, height: 7, borderRadius: '50%', background: '#34D399', animation: 'pulse 3s ease-in-out infinite' }} />
          {T('Live from api.earn-defi.com', 'Вживую с api.earn-defi.com')}{pool.as_of ? ' · ' + pool.as_of : ''}
        </span>
      </div>

      {/* header: protocol/asset/chain + risk class + verdict */}
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', flexWrap: 'wrap', gap: 16, marginBottom: 8 }}>
        <div>
          <h1 style={{ fontSize: 32, fontWeight: 700, color: 'var(--text-primary)', lineHeight: 1.1, margin: 0 }}>{pool.protocol || '?'}</h1>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 13, color: 'var(--text-muted)', marginTop: 6 }}>
            {(pool.asset || '?')} · {(pool.chain || '?')}{pool.tier ? ' · ' + pool.tier : ''} · <span title={pool.pool_id}>{pool.pool_id}</span>
          </div>
        </div>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
          <Badge style={cs} title={(ru ? 'класс риска' : 'risk class')}>{T('Class', 'Класс')} {pool.risk_class || '?'}</Badge>
          <Badge style={vs}><span style={{ width: 7, height: 7, borderRadius: '50%', background: vs.fg }} />{vLabel}</Badge>
        </div>
      </div>

      {/* APY base/reward split + TVL tiles */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(150px,1fr))', gap: 12, margin: '20px 0 28px' }}>
        <Tile lbl={T('APY total', 'APY всего')} v={pct(apy.total)} big />
        <Tile lbl={T('APY base', 'APY база')} v={pct(apy.base)} />
        <Tile lbl={T('APY reward', 'APY награда')} v={pct(apy.reward)} fg={num(apy.reward) ? '#F2B53C' : undefined} />
        <Tile lbl={T('TVL', 'TVL')} v={usd(pool.tvl_usd)} />
      </div>
      {num(apy.reward) > 0 && (
        <p style={{ fontSize: 12.5, color: 'var(--text-muted)', marginTop: -16, marginBottom: 28 }}>
          {T('Reward-heavy APY — base is the durable yield; reward (incentives) can stop at any time.',
             'APY с большой долей наград — устойчива только база; награды (стимулы) могут прекратиться в любой момент.')}
        </p>
      )}

      {/* ============================ EXIT-NAV BY SIZE ============================ */}
      <Section title={T('Exit-liquidity by size', 'Ликвидность на выход по размеру')}
        sub={T('For each ticket: how much of it the pool can absorb on exit, and the haircut. A flagged ticket has no clearing exit — shown as a hole, never backfilled.',
               'Для каждого тикета: сколько пул может поглотить на выходе и хейркат. Помеченный тикет не имеет расчищающего выхода — показан как дыра, не заполняется.')}>
        <div style={{ overflowX: 'auto', border: '1px solid var(--border)', borderRadius: 12 }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 520 }}>
            <thead>
              <tr style={{ background: 'var(--bg-surface)', textAlign: 'left' }}>
                <Th>{T('Ticket OUT', 'Тикет на выход')}</Th>
                <Th right>{T('Absorbable', 'Поглощается')}</Th>
                <Th right>{T('DEX exit frac', 'Доля через DEX')}</Th>
                <Th right>{T('Status', 'Статус')}</Th>
              </tr>
            </thead>
            <tbody>
              {exitRows.length === 0 && (
                <tr><td colSpan={4} style={{ padding: '20px 14px', textAlign: 'center', color: 'var(--text-muted)' }}>{T('No exit schedule published.', 'График выхода не опубликован.')}</td></tr>
              )}
              {exitRows.map((r, i) => {
                const hole = (r.flagged === true) || (num(r.absorbable_usd) == null);
                return (
                  <tr key={i} style={{ borderTop: '1px solid var(--border)', background: hole ? 'rgba(242,109,109,.04)' : 'transparent' }}>
                    <td style={{ padding: '10px 14px', fontFamily: 'var(--font-mono)', fontSize: 13, color: 'var(--text-primary)' }}>{usd(r.ticket_usd)}</td>
                    <td style={{ padding: '10px 14px', textAlign: 'right', fontFamily: 'var(--font-mono)', fontSize: 13, color: hole ? '#F26D6D' : 'var(--text-primary)' }}>
                      {hole ? (ru ? 'нет расчищающего выхода' : 'no clearing exit') : usd(r.absorbable_usd)}
                    </td>
                    <td style={{ padding: '10px 14px', textAlign: 'right', fontFamily: 'var(--font-mono)', fontSize: 13, color: 'var(--text-secondary)' }}>{hole ? '—' : fracPct(r.dex_exit_frac)}</td>
                    <td style={{ padding: '10px 14px', textAlign: 'right' }}>
                      {hole
                        ? <Badge style={verdictStyle('REFUSE')}>{ru ? 'флаг' : 'flagged'}</Badge>
                        : <Badge style={verdictStyle('SAFE')}>{ru ? 'ок' : 'ok'}</Badge>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Section>

      {/* ============================ REFUSAL DECOMPOSITION ============================ */}
      <Section title={T('Why ' + (vLabel) + '? — the refusal decomposition', 'Почему ' + (vLabel) + '? — разбор отказа')}
        sub={T('The verdict is deterministic (no LLM): structural haircuts + a tail-veto, straight from the desk engine.',
               'Вердикт детерминирован (без LLM): структурные хейркаты + tail-veto, прямо из движка стола.')}>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(180px,1fr))', gap: 12 }}>
          <Tile lbl={T('Structural haircut', 'Структурный хейркат')} v={fracPct(pool.structural_haircut)} />
          <Tile lbl={T('Total haircut', 'Полный хейркат')} v={fracPct(pool.total_haircut)} />
          <Tile lbl={T('Tail-veto', 'Tail-veto')}
            v={pool.refusal && pool.refusal.tail_veto ? T('FIRED', 'СРАБОТАЛ') : T('not fired', 'не сработал')}
            fg={pool.refusal && pool.refusal.tail_veto ? '#F26D6D' : '#34D399'} />
          <Tile lbl={T('Risk class', 'Класс риска')} v={pool.risk_class || '?'} fg={cs.fg} />
        </div>
        {pool.refusal && pool.refusal.reason && (
          <div style={{ marginTop: 14, padding: '14px 16px', background: 'var(--bg-surface)', border: '1px solid ' + vs.bd, borderRadius: 12 }}>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, textTransform: 'uppercase', letterSpacing: '.08em', color: 'var(--text-muted)', marginBottom: 6 }}>{T('Reason', 'Причина')}</div>
            <div style={{ fontSize: 14, color: 'var(--text-secondary)' }}>{pool.refusal.reason}</div>
          </div>
        )}
      </Section>

      {/* ============================ HISTORY ============================ */}
      <Section title={T('History', 'История')}
        sub={T('APY (total) and TVL over time, from our own captured series. Thin history is labeled, never extrapolated.',
               'APY (всего) и TVL во времени, из нашей собственной захваченной серии. Тонкая история помечается, не экстраполируется.')}>
        {apySeries.length >= 2 ? (
          <>
            <AnimatedChart
              series={[{ points: apySeries, color: 'var(--accent)', label: ru ? 'APY всего %' : 'APY total %', fill: true }]}
              height={200} xLabels={histLabels} yFormat={(v) => v.toFixed(1) + '%'}
              ariaLabel={ru ? 'история APY' : 'APY history'} client:visible />
            {tvlSeries.length >= 2 && (
              <div style={{ marginTop: 16 }}>
                <AnimatedChart
                  series={[{ points: tvlSeries, color: 'var(--data-teal)', label: 'TVL' }]}
                  height={160} xLabels={histLabels}
                  yFormat={(v) => (Math.abs(v) >= 1e6 ? (v / 1e6).toFixed(0) + 'M' : (v / 1e3).toFixed(0) + 'k')}
                  ariaLabel={ru ? 'история TVL' : 'TVL history'} client:visible />
              </div>
            )}
          </>
        ) : (
          <div style={{ padding: '20px 16px', textAlign: 'center', border: '1px dashed var(--border)', borderRadius: 12, fontFamily: 'var(--font-mono)', fontSize: 13, color: 'var(--text-muted)' }}>
            INSUFFICIENT_DATA — {T('not enough captured points to draw a trend (need ≥ 2). No line is extrapolated.',
                                   'недостаточно точек для тренда (нужно ≥ 2). Линия не экстраполируется.')}
          </div>
        )}
      </Section>

      {/* ============================ VERIFY THIS POOL ============================ */}
      <Section title={T('Verify this pool', 'Проверить этот пул')}
        sub={T("Don't trust us — check us. The verdict above carries a proof hash you can re-derive yourself from its stated inputs.",
               'Не верь — проверь. Вердикт выше несёт proof-хеш, который ты можешь пересчитать сам из заявленных входов.')}>
        <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--accent-dim)', borderRadius: 16, padding: 20 }}>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 16, marginBottom: 14 }}>
            <KV k="proof_hash" v={(proof && proof.proof_hash) || pool.proof_hash || '—'} mono break />
            {proof && proof.prev_hash && <KV k="prev_hash" v={proof.prev_hash} mono break />}
            <KV k="as_of" v={pool.as_of || '—'} mono />
            <KV k={T('data source', 'источник данных')} v={pool.data_source || '—'} mono />
            <KV k={T('feed coverage', 'покрытие фидов')} v={pool.feed_coverage != null ? String(pool.feed_coverage) : '—'} mono />
          </div>
          <div style={{ background: 'var(--bg-base)', border: '1px solid var(--border)', borderRadius: 10, padding: 14, overflowX: 'auto' }}>
            <code style={{ fontFamily: 'var(--font-mono)', fontSize: 13, color: 'var(--data-teal)', wordBreak: 'break-all' }}>
              {(proof && proof.verify_with) || ('python3 verify_dfb_pool.py ' + pool.pool_id)}
            </code>
          </div>
          <p style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-faint)', marginTop: 10 }}>
            spec: {(proof && proof.spec) || 'docs/DFB_METHODOLOGY.md'} · {T('re-derive on a clean machine, zero spa_core import', 'пересчитать на чистой машине, без импорта spa_core')}
          </p>
        </div>
      </Section>

      <p style={{ marginTop: 28 }}>
        <a href="/board" style={{ color: 'var(--accent)', fontSize: 14 }}>← {T('Back to the board', 'Назад на риск-борд')}</a>
      </p>
    </div>
  );
}

function P({ children }) {
  return <p style={{ padding: '40px 0', textAlign: 'center', color: 'var(--text-muted)' }}>{children}</p>;
}
function Empty({ title, body }) {
  return (
    <div style={{ padding: '48px 24px', textAlign: 'center', border: '1px dashed var(--border)', borderRadius: 16 }}>
      <h1 style={{ fontSize: 24, fontWeight: 700, color: 'var(--text-primary)', marginBottom: 10 }}>{title}</h1>
      <p style={{ color: 'var(--text-muted)', maxWidth: 520, margin: '0 auto' }}>{body}</p>
      <p style={{ marginTop: 20 }}><a href="/board" style={{ color: 'var(--accent)' }}>← Board</a></p>
    </div>
  );
}
function Section({ title, sub, children }) {
  return (
    <section style={{ padding: '28px 0', borderTop: '1px solid var(--border)' }}>
      <h2 style={{ fontSize: 20, fontWeight: 600, color: 'var(--text-primary)', margin: 0 }}>{title}</h2>
      {sub && <p style={{ fontSize: 13.5, color: 'var(--text-muted)', margin: '8px 0 18px', maxWidth: 680, lineHeight: 1.55 }}>{sub}</p>}
      {children}
    </section>
  );
}
function Tile({ lbl, v, big, fg }) {
  return (
    <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)', borderRadius: 12, padding: '14px 16px' }}>
      <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, textTransform: 'uppercase', letterSpacing: '.08em', color: 'var(--text-muted)', marginBottom: 6 }}>{lbl}</div>
      <div style={{ fontFamily: 'var(--font-mono)', fontSize: big ? 26 : 18, fontWeight: 700, color: fg || 'var(--text-primary)' }}>{v}</div>
    </div>
  );
}
function Th({ children, right }) {
  return <th style={{ padding: '11px 14px', fontFamily: 'var(--font-mono)', fontSize: 11, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '.06em', color: 'var(--text-muted)', textAlign: right ? 'right' : 'left', whiteSpace: 'nowrap' }}>{children}</th>;
}
function KV({ k, v, mono, break: br }) {
  return (
    <div style={{ minWidth: 0 }}>
      <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10.5, textTransform: 'uppercase', letterSpacing: '.06em', color: 'var(--text-muted)', marginBottom: 3 }}>{k}</div>
      <div style={{ fontFamily: mono ? 'var(--font-mono)' : 'inherit', fontSize: 12.5, color: 'var(--text-secondary)', wordBreak: br ? 'break-all' : 'normal', maxWidth: br ? 320 : 'none' }}>{v}</div>
    </div>
  );
}
