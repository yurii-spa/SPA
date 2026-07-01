import { useState, useEffect, useCallback } from 'react';
import { classStyle, verdictStyle } from './ui/riskStyles.js';

/*
 * DfbPortfolio.jsx — the DFB READ-ONLY portfolio risk lens (Lane-C / WS-2.4).
 *
 * "DeBank tells you WHAT you hold; DFB tells you HOW RISKY it is and whether the desk would hold it."
 *
 * Paste a READ-ONLY address + declared holdings (pool_id + value) → each position risk-graded with
 * the SAME overlay the screener uses (A/B/C/D + refusal verdict + exit-liquidity-by-size) + a
 * portfolio-level risk summary. CONSUMES Lane-2:
 *   GET /api/dfb/portfolio/{address}?holdings=<url-encoded JSON>
 *   GET /api/dfb/pools  → to offer a pool_id picker (so the declared holdings map onto real pools)
 *
 * HONESTY CONTRACT (fail-CLOSED, read-only, no custody):
 *   - READ-ONLY ADDRESS ONLY. No wallet-connect, no signing, no key — the address is a label.
 *   - The DATA-SOURCE LIMIT is shown loudly: SPA is keyless and does NOT auto-read multi-chain
 *     balances; positions are the caller's DECLARED holdings against the followed universe.
 *   - risk_class + refusal verdict render STRAIGHT from the API; never recomputed/softened.
 *   - REFUSE-grade / class-D / tail-veto holdings are surfaced in the summary, never hidden.
 *   - Flag OFF (API 404 portfolio_lens_disabled) → an honest "owner-gated / coming soon" state.
 *   - API offline → honest "unavailable"; never a stale-as-live or fabricated portfolio.
 *
 * Bilingual via the site's spa_lang mechanism.
 */

const TICKETS = [1_000_000, 5_000_000, 10_000_000];

function apiBase() {
  if (typeof location === 'undefined') return 'https://api.earn-defi.com';
  return (location.hostname === 'localhost' || location.hostname === '127.0.0.1')
    ? 'http://localhost:8765'
    : 'https://api.earn-defi.com';
}
function readLang() {
  try { return (localStorage.getItem('spa_lang') || 'en') === 'ru' ? 'ru' : 'en'; } catch (e) { return 'en'; }
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
function pct(x) { const n = num(x); return n == null ? '—' : n.toFixed(1) + '%'; }

// One badge geometry, shared across all DFB islands (matches ui/Badge.astro §3.4).
function Badge({ style, children, title }) {
  return (
    <span title={title} style={{
      display: 'inline-flex', alignItems: 'center', gap: 6, padding: '4px 10px',
      borderRadius: 'var(--r-full)', fontFamily: 'var(--font-mono)', fontSize: 11, fontWeight: 500,
      lineHeight: 1, background: style.bg, border: '1px solid ' + style.bd, color: style.fg, whiteSpace: 'nowrap',
    }}>{children}</span>
  );
}

export default function DfbPortfolio() {
  const [ru, setRu] = useState(false);
  const T = useCallback((en, rux) => (ru ? rux : en), [ru]);

  const [address, setAddress] = useState('');
  const [poolIds, setPoolIds] = useState([]);          // the followed universe ids (for the picker)
  const [rows, setRows] = useState([{ pool_id: '', value_usd: '' }]); // declared holdings (editable)
  const [state, setState] = useState('idle');          // idle | loading | live | offline | disabled
  const [view, setView] = useState(null);

  useEffect(() => {
    setRu(readLang() === 'ru');
    const onLang = () => setRu(readLang() === 'ru');
    window.addEventListener('spa:lang', onLang);
    const prev = window.__renderLive;
    window.__renderLive = function () { try { onLang(); } catch (e) {} if (typeof prev === 'function') { try { prev(); } catch (e) {} } };
    return () => { window.removeEventListener('spa:lang', onLang); window.__renderLive = prev; };
  }, []);

  // load the followed-universe pool ids so declared holdings map onto real, gradable pools.
  useEffect(() => {
    let alive = true;
    fetch(apiBase() + '/api/dfb/pools')
      .then((r) => r.json())
      .then((d) => { if (alive && d && Array.isArray(d.pools)) setPoolIds(d.pools.map((p) => p.pool_id).filter(Boolean).sort()); })
      .catch(() => {});
    return () => { alive = false; };
  }, []);

  const setRow = (i, key, val) => setRows((rs) => rs.map((r, j) => (j === i ? { ...r, [key]: val } : r)));
  const addRow = () => setRows((rs) => [...rs, { pool_id: '', value_usd: '' }]);
  const delRow = (i) => setRows((rs) => (rs.length > 1 ? rs.filter((_, j) => j !== i) : rs));

  const run = useCallback(() => {
    const addr = address.trim();
    if (!addr) return;
    const holdings = rows
      .map((r) => ({ pool_id: (r.pool_id || '').trim(), value_usd: Number(r.value_usd) }))
      .filter((h) => h.pool_id && Number.isFinite(h.value_usd) && h.value_usd >= 0);
    setState('loading');
    setView(null);
    const enc = encodeURIComponent(addr);
    const hq = encodeURIComponent(JSON.stringify(holdings));
    fetch(apiBase() + '/api/dfb/portfolio/' + enc + '?holdings=' + hq)
      .then((r) => {
        if (r.status === 404) {
          // distinguish the OWNER-GATED flag-OFF case from a bad address.
          return r.json().then((j) => {
            if (j && j.detail && j.detail.error === 'portfolio_lens_disabled') { setState('disabled'); return null; }
            setState('live'); setView({ address_validated: false, n_positions: 0, positions: [], unresolved: [], summary: null, note: (j && j.detail && j.detail.note) || 'invalid address' }); return null;
          });
        }
        return r.json();
      })
      .then((d) => { if (d) { setState('live'); setView(d); } })
      .catch(() => setState('offline'));
  }, [address, rows]);

  // ── OWNER-GATED state (flag OFF) — honest "coming soon", never a fabricated portfolio ──
  if (state === 'disabled') {
    return (
      <div style={{ borderRadius: 12, padding: 28, background: 'var(--bg-surface)', border: '1px solid var(--accent-dim)' }}>
        <p style={{ fontFamily: 'var(--font-mono)', fontSize: 12, letterSpacing: '.12em', textTransform: 'uppercase', color: 'var(--accent-hover)', marginBottom: 10 }}>
          {T('Owner-gated — coming soon', 'Под решением владельца — скоро')}
        </p>
        <p style={{ color: 'var(--text-secondary)', lineHeight: 1.6, fontSize: 15 }}>
          {T(
            'The read-only portfolio lens is built but OWNER-GATED behind the SPA_DFB_PORTFOLIO_LENS flag (default OFF). It is not enabled until the owner signs off on the honesty of its position coverage. No fabricated portfolio is ever shown.',
            'Read-only портфельная линза собрана, но закрыта флагом SPA_DFB_PORTFOLIO_LENS (по умолчанию OFF) под решением владельца — пока он не подтвердит честность покрытия позиций. Выдуманный портфель не показывается никогда.'
          )}
        </p>
      </div>
    );
  }

  const summary = view && view.summary;
  const positions = (view && view.positions) || [];
  const unresolved = (view && view.unresolved) || [];

  return (
    <div>
      {/* ── the data-source limit, stated loudly up front ── */}
      <div style={{ borderRadius: 12, padding: 18, background: 'var(--bg-surface)', border: '1px solid var(--border)', marginBottom: 20 }}>
        <p style={{ fontFamily: 'var(--font-mono)', fontSize: 11, letterSpacing: '.1em', textTransform: 'uppercase', color: 'var(--text-faint)', marginBottom: 8 }}>
          {T('Read-only · no custody · no signing — and an honest limit', 'Read-only · без кастодиана · без подписи — и честное ограничение')}
        </p>
        <p style={{ color: 'var(--text-secondary)', fontSize: 13.5, lineHeight: 1.6 }}>
          {T(
            'SPA is keyless and does NOT auto-read multi-chain balances. You paste a READ-ONLY address (a label only — no wallet-connect, no key) and DECLARE your holdings against the followed universe; DFB grades each with the same risk engine the desk runs. Nothing is signed or moved.',
            'SPA работает без ключей и НЕ читает мультичейн-балансы автоматически. Вы вставляете READ-ONLY адрес (только метка — без wallet-connect, без ключа) и ОБЪЯВЛЯЕТЕ позиции по отслеживаемой вселенной; DFB оценивает каждую тем же риск-движком, что и сам стол. Ничего не подписывается и не перемещается.'
          )}
        </p>
      </div>

      {/* ── inputs ── */}
      <div style={{ borderRadius: 12, padding: 20, background: 'var(--bg-surface)', border: '1px solid var(--border)', marginBottom: 24 }}>
        <label htmlFor="dfb-pf-address" style={{ display: 'block', fontFamily: 'var(--font-mono)', fontSize: 11, letterSpacing: '.1em', textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: 6 }}>
          {T('Read-only address', 'Read-only адрес')}
        </label>
        <input
          id="dfb-pf-address"
          value={address}
          onChange={(e) => setAddress(e.target.value)}
          placeholder="0x… / name.eth"
          spellCheck={false}
          style={{ width: '100%', padding: '10px 12px', borderRadius: 8, fontFamily: 'var(--font-mono)', fontSize: 14, background: 'var(--bg-base)', border: '1px solid var(--border)', color: 'var(--text-primary)', marginBottom: 16 }}
        />

        <span id="dfb-pf-holdings-label" style={{ display: 'block', fontFamily: 'var(--font-mono)', fontSize: 11, letterSpacing: '.1em', textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: 6 }}>
          {T('Declared holdings (pool + value USD)', 'Объявленные позиции (пул + сумма USD)')}
        </span>
        {rows.map((r, i) => (
          <div key={i} role="group" aria-labelledby="dfb-pf-holdings-label" style={{ display: 'flex', gap: 8, marginBottom: 8, flexWrap: 'wrap' }}>
            <input
              list="dfb-pool-ids"
              aria-label={T('Pool id for holding ' + (i + 1), 'pool_id позиции ' + (i + 1))}
              value={r.pool_id}
              onChange={(e) => setRow(i, 'pool_id', e.target.value)}
              placeholder={T('pool_id', 'pool_id')}
              spellCheck={false}
              style={{ flex: '2 1 240px', padding: '8px 10px', borderRadius: 8, fontFamily: 'var(--font-mono)', fontSize: 13, background: 'var(--bg-base)', border: '1px solid var(--border)', color: 'var(--text-primary)' }}
            />
            <input
              type="number" min="0" step="any"
              aria-label={T('Value in USD for holding ' + (i + 1), 'сумма USD позиции ' + (i + 1))}
              value={r.value_usd}
              onChange={(e) => setRow(i, 'value_usd', e.target.value)}
              placeholder={T('value USD', 'сумма USD')}
              style={{ flex: '1 1 130px', padding: '8px 10px', borderRadius: 8, fontFamily: 'var(--font-mono)', fontSize: 13, background: 'var(--bg-base)', border: '1px solid var(--border)', color: 'var(--text-primary)' }}
            />
            <button onClick={() => delRow(i)} title={T('remove', 'удалить')} aria-label={T('Remove holding ' + (i + 1), 'Удалить позицию ' + (i + 1))}
              style={{ padding: '8px 12px', borderRadius: 8, background: 'transparent', border: '1px solid var(--border)', color: 'var(--text-muted)', cursor: 'pointer' }}>×</button>
          </div>
        ))}
        <datalist id="dfb-pool-ids">{poolIds.map((id) => <option key={id} value={id} />)}</datalist>

        <div style={{ display: 'flex', gap: 10, marginTop: 6, flexWrap: 'wrap' }}>
          <button onClick={addRow}
            style={{ padding: '8px 14px', borderRadius: 8, background: 'transparent', border: '1px solid var(--border)', color: 'var(--text-secondary)', cursor: 'pointer', fontSize: 13 }}>
            + {T('add holding', 'добавить позицию')}
          </button>
          <button onClick={run} disabled={!address.trim()}
            style={{ padding: '8px 18px', borderRadius: 8, background: 'var(--accent)', border: '1px solid var(--accent)', color: '#fff', cursor: address.trim() ? 'pointer' : 'not-allowed', fontWeight: 600, fontSize: 13, opacity: address.trim() ? 1 : 0.5 }}>
            {T('Grade my portfolio', 'Оценить портфель')}
          </button>
        </div>
      </div>

      {/* ── status ── */}
      {state === 'loading' && <p style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: 13 }}>{T('Grading…', 'Оцениваю…')}</p>}
      {state === 'offline' && <p style={{ color: 'var(--danger)', fontFamily: 'var(--font-mono)', fontSize: 13 }}>{T('API unavailable — no fabricated portfolio shown (fail-closed).', 'API недоступно — выдуманный портфель не показан (fail-closed).')}</p>}

      {/* ── results ── */}
      {state === 'live' && view && (
        <div>
          {view.address_validated === false && (
            <p style={{ color: 'var(--danger)', fontFamily: 'var(--font-mono)', fontSize: 13, marginBottom: 16 }}>
              {T('Address did not validate as a read-only address label.', 'Адрес не прошёл проверку как read-only метка.')}
            </p>
          )}

          {/* portfolio risk summary */}
          {summary && (
            <div style={{ borderRadius: 12, padding: 20, background: 'var(--bg-surface)', border: '1px solid var(--border)', marginBottom: 20 }}>
              <p style={{ fontFamily: 'var(--font-mono)', fontSize: 11, letterSpacing: '.1em', textTransform: 'uppercase', color: 'var(--text-faint)', marginBottom: 12 }}>
                {T('Portfolio risk summary', 'Сводка риска портфеля')}
              </p>
              <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap', marginBottom: 14 }}>
                <div><div style={{ fontSize: 12, color: 'var(--text-muted)' }}>{T('Total declared', 'Всего объявлено')}</div><div style={{ fontSize: 20, fontWeight: 700, color: 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}>{usd(summary.total_value_usd)}</div></div>
                <div><div style={{ fontSize: 12, color: 'var(--text-muted)' }}>{T('Positions', 'Позиций')}</div><div style={{ fontSize: 20, fontWeight: 700, color: 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}>{summary.n_positions}</div></div>
                <div><div style={{ fontSize: 12, color: 'var(--text-muted)' }}>{T('In REFUSE-grade', 'В REFUSE-классе')}</div><div style={{ fontSize: 20, fontWeight: 700, fontFamily: 'var(--font-mono)', color: summary.has_refuse_grade_holdings ? 'var(--danger)' : 'var(--text-primary)' }}>{pct(summary.pct_in_refuse_grade)}</div></div>
              </div>

              {/* class breakdown */}
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 14 }}>
                {['A', 'B', 'C', 'D', 'UNKNOWN'].map((cls) => {
                  const v = summary.pct_by_risk_class[cls] || 0;
                  const st = classStyle(cls === 'UNKNOWN' ? '' : cls);
                  return (
                    <span key={cls} style={{ display: 'inline-flex', gap: 6, alignItems: 'center', padding: '4px 10px', borderRadius: 6, fontFamily: 'var(--font-mono)', fontSize: 12, background: st.bg, border: '1px solid ' + st.bd, color: st.fg }}>
                      <strong>{cls}</strong> {pct(v)}
                    </span>
                  );
                })}
              </div>

              {/* the loud flag */}
              {summary.has_refuse_grade_holdings && (
                <div style={{ borderRadius: 8, padding: 12, background: 'var(--danger-bg)', border: '1px solid var(--danger-border)' }}>
                  <p style={{ color: 'var(--danger)', fontWeight: 600, fontSize: 13, marginBottom: 6 }}>
                    <span aria-hidden="true">▲</span> {T('The desk would REFUSE', 'Стол бы ОТКАЗАЛ')} {summary.n_refuse_grade_holdings} {T('of your holdings', 'из ваших позиций')} ({usd(summary.value_in_refuse_grade_usd)})
                  </p>
                  <ul style={{ margin: 0, paddingLeft: 18, color: 'var(--text-secondary)', fontSize: 12.5, lineHeight: 1.6 }}>
                    {summary.refuse_grade_holdings.map((h) => (
                      <li key={h.pool_id}>
                        <span style={{ fontFamily: 'var(--font-mono)' }}>{h.pool_id}</span> — {usd(h.value_usd)} · {T('class', 'класс')} {h.risk_class} · {h.refusal_verdict} ({h.refusal_reason}){h.tail_veto ? ' · tail-veto' : ''}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}

          {/* graded positions table */}
          {positions.length > 0 && (
            <div style={{ overflowX: 'auto', borderRadius: 12, border: '1px solid var(--border)' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                <thead>
                  <tr style={{ background: 'var(--bg-surface)', textAlign: 'left' }}>
                    <th style={{ padding: '10px 12px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: 11, textTransform: 'uppercase', letterSpacing: '.06em', fontWeight: 600 }}>{T('Pool', 'Пул')}</th>
                    <th style={{ padding: '10px 12px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: 11, textTransform: 'uppercase', letterSpacing: '.06em', fontWeight: 600 }}>{T('Value', 'Сумма')}</th>
                    <th style={{ padding: '10px 12px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: 11, textTransform: 'uppercase', letterSpacing: '.06em', fontWeight: 600 }}>{T('Class', 'Класс')}</th>
                    <th style={{ padding: '10px 12px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: 11, textTransform: 'uppercase', letterSpacing: '.06em', fontWeight: 600 }}>{T('Verdict', 'Вердикт')}</th>
                    <th style={{ padding: '10px 12px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: 11, textTransform: 'uppercase', letterSpacing: '.06em', fontWeight: 600 }}>{T('Exit @ $1M', 'Выход @ $1M')}</th>
                  </tr>
                </thead>
                <tbody>
                  {positions.map((p) => {
                    const cs = classStyle(p.risk_class);
                    const vs = verdictStyle(p.refusal_verdict);
                    const t1 = (p.exit_liquidity || []).find((c) => c.ticket_usd === 1_000_000);
                    const exitCell = !t1 ? '—' : (t1.flagged || !Number.isFinite(Number(t1.absorbable_usd)))
                      ? T('flagged', 'флаг') : usd(t1.absorbable_usd);
                    return (
                      <tr key={p.pool_id} style={{ borderTop: '1px solid var(--border)' }}>
                        <td style={{ padding: '10px 12px', fontFamily: 'var(--font-mono)', color: 'var(--text-primary)' }}>
                          <a href={'/board/pool?id=' + encodeURIComponent(p.pool_id)} style={{ color: 'var(--text-primary)' }}>{p.pool_id}</a>
                          <div style={{ fontSize: 11, color: 'var(--text-faint)' }}>{p.protocol} · {p.chain} · {p.asset}</div>
                        </td>
                        <td style={{ padding: '10px 12px', fontFamily: 'var(--font-mono)', color: 'var(--text-secondary)' }}>{usd(p.value_usd)}</td>
                        <td style={{ padding: '10px 12px' }}><Badge style={cs} title={p.risk_class_label}>{p.risk_class}</Badge></td>
                        <td style={{ padding: '10px 12px' }}><Badge style={vs} title={p.refusal_reason}>{p.refusal_verdict}{p.tail_veto ? ' · tail-veto' : ''}</Badge></td>
                        <td style={{ padding: '10px 12px', fontFamily: 'var(--font-mono)', color: (t1 && (t1.flagged || !Number.isFinite(Number(t1.absorbable_usd)))) ? 'var(--warn)' : 'var(--text-secondary)' }}>{exitCell}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}

          {/* unresolved (honest holes — never fabricated) */}
          {unresolved.length > 0 && (
            <div style={{ marginTop: 16, borderRadius: 8, padding: 12, background: 'var(--bg-surface)', border: '1px dashed var(--border)' }}>
              <p style={{ fontSize: 12, color: 'var(--text-faint)', marginBottom: 6 }}>
                {T('Not in the followed universe (cannot risk-grade — not fabricated):', 'Нет в отслеживаемой вселенной (не можем оценить риск — не выдумываем):')}
              </p>
              <ul style={{ margin: 0, paddingLeft: 18, color: 'var(--text-muted)', fontSize: 12.5 }}>
                {unresolved.map((u) => <li key={u.pool_id}><span style={{ fontFamily: 'var(--font-mono)' }}>{u.pool_id}</span> — {usd(u.value_usd)}</li>)}
              </ul>
            </div>
          )}

          {view.note && positions.length === 0 && unresolved.length === 0 && (
            <p style={{ color: 'var(--text-muted)', fontSize: 13 }}>{view.note}</p>
          )}
        </div>
      )}
    </div>
  );
}
