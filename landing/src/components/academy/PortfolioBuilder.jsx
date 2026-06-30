import { useState, useEffect } from 'react';
import { getLang, recordPlaygroundTried } from './progress.js';

/*
 * PortfolioBuilder.jsx — «собери книгу сам» → RiskPolicy гейт оценивает её ВЖИВУЮ.
 *
 * Mirrors spa_core/risk/policy.py (RiskConfig + check_portfolio_health-style caps)
 * EXACTLY, deterministically, no LLM, no fabrication:
 *
 *   max_concentration_t1   = 0.40   (≤40% на любой T1)
 *   max_concentration_t2   = 0.20   (≤20% на любой T2)
 *   max_single_protocol    = 0.40   (абсолютный потолок — равен T1, поэтому уже покрыт #6)
 *   max_total_t2_allocation= 0.50   (T2 совокупно ≤50%, ADR-019)
 *   min_cash_pct           = 0.05   (≥5% всегда в кэше)
 *   min_tvl_usd            = 5_000_000  ($5M floor на пул)
 *   max_apy_for_new_position = 30.0 / min = 1.0  (APY-band нового входа 1%…30%)
 *
 * The analyst adds protocols with a % allocation. We re-derive cash = 100% − Σalloc,
 * then run EVERY cap and surface the per-cap PASS/REJECT, blended APY, and the
 * overall verdict (approved iff zero violations) — the same fail-CLOSED AND-logic
 * the gate uses (any violation → approved=False, никем не переопределимо).
 *
 * HONEST: a >40% Aave alloc → REJECT (T1 cap); sUSDe/LRT carry sit at T2 (20% cap,
 * 50% total) with APYs that ALSO trip the 30% APY ceiling for the toxic ones — so
 * the gate teaches WHY the real live book sits at ~4.5% in plain T1 lenders.
 */

const CAP = {
  T1: 0.40,        // max_concentration_t1
  T2: 0.20,        // max_concentration_t2
  T2_TOTAL: 0.50,  // max_total_t2_allocation (ADR-019)
  CASH_MIN: 0.05,  // min_cash_pct
  TVL_MIN: 5_000_000, // min_tvl_usd
  APY_MAX: 30.0,   // max_apy_for_new_position
  APY_MIN: 1.0,    // min_apy_for_new_position
};

// Honest protocol universe. APY/TVL are realistic order-of-magnitude marks for a
// teaching sim (not a live feed); tier matches the desk's adapter registry.
// The "risky" ones carry their real tail (high APY → trips the 30% ceiling and/or
// they're T2 so the 20%/50% caps bite).
const UNIVERSE = [
  { id: 'aave',     ru: 'Aave V3 (USDC)',       en: 'Aave V3 (USDC)',       tier: 'T1', apy: 4.6,  tvl: 1_200_000_000 },
  { id: 'compound', ru: 'Compound V3 (USDC)',   en: 'Compound V3 (USDC)',   tier: 'T1', apy: 4.3,  tvl: 480_000_000 },
  { id: 'morpho',   ru: 'Morpho Steakhouse',    en: 'Morpho Steakhouse',    tier: 'T1', apy: 5.1,  tvl: 210_000_000 },
  { id: 'spark',    ru: 'Spark sUSDS',          en: 'Spark sUSDS',          tier: 'T1', apy: 4.8,  tvl: 1_900_000_000 },
  { id: 'maple',    ru: 'Maple (private credit)', en: 'Maple (private credit)', tier: 'T2', apy: 9.4, tvl: 95_000_000 },
  { id: 'euler',    ru: 'Euler V2',             en: 'Euler V2',             tier: 'T2', apy: 6.2,  tvl: 38_000_000 },
  { id: 'yearn',    ru: 'Yearn V3',             en: 'Yearn V3',             tier: 'T2', apy: 6.8,  tvl: 52_000_000 },
  // — risky / refused-shape books —
  { id: 'susde',    ru: 'sUSDe (Ethena carry)', en: 'sUSDe (Ethena carry)', tier: 'T2', apy: 12.0, tvl: 320_000_000, risky: true },
  { id: 'lrt',      ru: 'LRT-рестейк (ezETH/rsETH)', en: 'LRT restaking (ezETH/rsETH)', tier: 'T2', apy: 31.0, tvl: 140_000_000, risky: true },
  { id: 'pendle',   ru: 'Pendle YT (плечо)',    en: 'Pendle YT (levered)',  tier: 'T2', apy: 28.0, tvl: 7_500_000, risky: true },
  { id: 'loop',     ru: 'Leverage looping ×3',  en: 'Leverage looping ×3',  tier: 'T2', apy: 34.0, tvl: 22_000_000, risky: true },
  { id: 'micropool', ru: 'Микро-пул (sub-$5M TVL)', en: 'Micro pool (sub-$5M TVL)', tier: 'T2', apy: 14.0, tvl: 2_100_000, risky: true },
];

const T = {
  title: { ru: 'Собери книгу → RiskPolicy гейт', en: 'Build a book → RiskPolicy gate' },
  intro: {
    ru: 'Добавляй протоколы и задавай аллокацию. Гейт RiskPolicy (policy.py) проверяет КАЖДЫЙ cap вживую: T1≤40%, любой T2≤20%, T2 суммарно≤50%, кэш≥5%, TVL≥$5M, APY входа 1–30%. Любое нарушение → книга ОТКЛОНЕНА (approved=False, никем не переопределимо).',
    en: 'Add protocols and set allocations. The RiskPolicy gate (policy.py) checks EVERY cap live: T1≤40%, any T2≤20%, total T2≤50%, cash≥5%, TVL≥$5M, entry APY 1–30%. Any violation → the book is REJECTED (approved=False, un-overridable).',
  },
  add: { ru: 'Добавить протокол', en: 'Add protocol' },
  cash: { ru: 'Кэш (1 − Σ аллокаций)', en: 'Cash (1 − Σ allocations)' },
  blended: { ru: 'Смешанный APY книги', en: 'Blended book APY' },
  deployed: { ru: 'Размещено', en: 'Deployed' },
  verdict: { ru: 'Вердикт RiskPolicy', en: 'RiskPolicy verdict' },
  approved: { ru: 'ДОПУЩЕНО (approved=True)', en: 'APPROVED (approved=True)' },
  rejected: { ru: 'ОТКЛОНЕНО (approved=False)', en: 'REJECTED (approved=False)' },
  noViol: { ru: 'Ноль нарушений — книга проходит детерминированный гейт.', en: 'Zero violations — the book passes the deterministic gate.' },
  remove: { ru: 'убрать', en: 'remove' },
  empty: { ru: 'Книга пуста — добавь протокол, чтобы запустить гейт.', en: 'Empty book — add a protocol to run the gate.' },
  checks: { ru: 'Проверки гейта', en: 'Gate checks' },
  pass: { ru: 'PASS', en: 'PASS' },
  fail: { ru: 'REJECT', en: 'REJECT' },
  presets: { ru: 'Пресеты:', en: 'Presets:' },
  presetReal: { ru: 'Реальная книга (~4.5% T1)', en: 'Real book (~4.5% T1)' },
  presetGreedy: { ru: 'Жадная (50% Aave)', en: 'Greedy (50% Aave)' },
  presetToxic: { ru: 'Yield-chase (LRT/loop)', en: 'Yield-chase (LRT/loop)' },
  lessonReal: {
    ru: 'Вот почему живая книга сидит на ~4.5% в простых T1-кредиторах: это единственная аллокация, которая проходит ВСЕ cap\'ы без нарушения. Доходность — следствие гейта, а не цель.',
    en: 'This is why the live book sits at ~4.5% in plain T1 lenders: it\'s the only allocation that clears EVERY cap. The yield is a consequence of the gate, not a target.',
  },
};

// Preset allocations {protocolId: pct(0..100)}
const PRESETS = {
  real: { aave: 35, compound: 25, spark: 20, morpho: 15 },        // cash 5%, all T1≤40, ok
  greedy: { aave: 50, compound: 25, spark: 20 },                  // aave 50% > 40 T1 cap → REJECT
  toxic: { lrt: 25, loop: 20, susde: 18, pendle: 15, aave: 17 },  // T2-total>50, T2 caps, APY>30 → REJECT
};

function pct(v) { return (v).toFixed(1) + '%'; }
function fmtTvl(v) { return v >= 1e9 ? '$' + (v / 1e9).toFixed(1) + 'B' : '$' + (v / 1e6).toFixed(0) + 'M'; }

export default function PortfolioBuilder() {
  const [lang, setLang] = useState('ru');
  // book: { protocolId: allocPct(0..100) }
  const [book, setBook] = useState(PRESETS.real);
  const [toAdd, setToAdd] = useState(UNIVERSE.find((u) => !PRESETS.real[u.id])?.id || UNIVERSE[0].id);

  useEffect(() => {
    setLang(getLang());
    const onLang = () => setLang(getLang());
    window.addEventListener('storage', onLang);
    const obs = new MutationObserver(() => setLang(getLang()));
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ['lang'] });
    return () => { window.removeEventListener('storage', onLang); obs.disconnect(); };
  }, []);
  const tr = (k) => (T[k] ? (T[k][lang] ?? T[k].ru) : k);
  const meta = (id) => UNIVERSE.find((u) => u.id === id);

  // engagement XP + "playground" badge on first interaction (idempotent, SSR-safe)
  const tried = () => recordPlaygroundTried('PortfolioBuilder');
  function setAlloc(id, v) { tried(); setBook((b) => ({ ...b, [id]: Math.max(0, Math.min(100, v)) })); }
  function remove(id) { tried(); setBook((b) => { const n = { ...b }; delete n[id]; return n; }); }
  function add() { tried(); if (toAdd && book[toAdd] == null) setBook((b) => ({ ...b, [toAdd]: 10 })); }
  function applyPreset(p) { tried(); setBook({ ...p }); }

  const entries = Object.entries(book).filter(([id]) => meta(id));
  const deployedPct = entries.reduce((s, [, v]) => s + v, 0);
  const cashPct = 100 - deployedPct;

  // blended APY: Σ(alloc_frac * apy); cash earns 0
  const blendedApy = entries.reduce((s, [id, v]) => s + (v / 100) * meta(id).apy, 0);

  // ── Run the REAL caps (mirror policy.py). Collect violations + per-cap checks. ──
  const violations = [];
  const checks = [];

  // cash buffer
  const cashOk = cashPct >= CAP.CASH_MIN * 100 - 1e-9;
  checks.push({ k: lang === 'ru' ? `Кэш ≥ ${CAP.CASH_MIN * 100}%` : `Cash ≥ ${CAP.CASH_MIN * 100}%`, val: pct(cashPct), ok: cashOk });
  if (!cashOk) violations.push(lang === 'ru'
    ? `Кэш-буфер ${pct(cashPct)} < минимума ${CAP.CASH_MIN * 100}%`
    : `Cash buffer ${pct(cashPct)} < minimum ${CAP.CASH_MIN * 100}%`);

  // over-allocation (can't deploy >100%)
  if (deployedPct > 100 + 1e-9) violations.push(lang === 'ru'
    ? `Размещено ${pct(deployedPct)} > 100% капитала`
    : `Deployed ${pct(deployedPct)} > 100% of capital`);

  // per-protocol concentration (T1≤40 / T2≤20) + TVL + APY-band per added book member
  entries.forEach(([id, v]) => {
    const m = meta(id);
    const cap = (m.tier === 'T1' ? CAP.T1 : CAP.T2) * 100;
    const concOk = v <= cap + 1e-9;
    checks.push({
      k: `${m[lang] ?? m.ru} — ${m.tier} ≤ ${cap}%`, val: pct(v), ok: concOk,
    });
    if (!concOk) violations.push(lang === 'ru'
      ? `Концентрация ${m.ru} ${pct(v)} > ${m.tier}-лимита ${cap}%`
      : `Concentration ${m.en} ${pct(v)} > ${m.tier} cap ${cap}%`);

    // TVL floor
    if (m.tvl < CAP.TVL_MIN) violations.push(lang === 'ru'
      ? `${m.ru}: TVL ${fmtTvl(m.tvl)} < минимума $5M`
      : `${m.en}: TVL ${fmtTvl(m.tvl)} < $5M floor`);

    // APY band (entry)
    if (m.apy > CAP.APY_MAX) violations.push(lang === 'ru'
      ? `${m.ru}: APY ${m.apy}% > потолка входа ${CAP.APY_MAX}% (риск слишком высок)`
      : `${m.en}: APY ${m.apy}% > entry ceiling ${CAP.APY_MAX}% (risk too high)`);
    else if (m.apy < CAP.APY_MIN) violations.push(lang === 'ru'
      ? `${m.ru}: APY ${m.apy}% < минимума входа ${CAP.APY_MIN}%`
      : `${m.en}: APY ${m.apy}% < entry minimum ${CAP.APY_MIN}%`);
  });

  // total T2 ≤ 50%
  const t2Total = entries.filter(([id]) => meta(id).tier === 'T2').reduce((s, [, v]) => s + v, 0);
  const t2Ok = t2Total <= CAP.T2_TOTAL * 100 + 1e-9;
  if (entries.some(([id]) => meta(id).tier === 'T2')) {
    checks.push({ k: lang === 'ru' ? `T2 суммарно ≤ ${CAP.T2_TOTAL * 100}%` : `Total T2 ≤ ${CAP.T2_TOTAL * 100}%`, val: pct(t2Total), ok: t2Ok });
    if (!t2Ok) violations.push(lang === 'ru'
      ? `T2 суммарно ${pct(t2Total)} > лимита ${CAP.T2_TOTAL * 100}%`
      : `Total T2 ${pct(t2Total)} > cap ${CAP.T2_TOTAL * 100}%`);
  }

  // dedup violations (TVL/APY can repeat across members but message is per-protocol; keep unique)
  const uniqViol = [...new Set(violations)];
  const approved = entries.length > 0 && uniqViol.length === 0;
  const verdictColor = approved ? 'var(--ok)' : 'var(--danger)';

  const available = UNIVERSE.filter((u) => book[u.id] == null);

  return (
    <div style={wrap}>
      <div style={head}>{tr('title')}</div>
      <p style={{ fontSize: 14, color: 'var(--text-secondary)', lineHeight: 1.6, marginTop: 0 }}>{tr('intro')}</p>

      <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 14 }}>
        {tr('presets')}{' '}
        <button style={presetBtn} onClick={() => applyPreset(PRESETS.real)}>{tr('presetReal')}</button>
        <button style={{ ...presetBtn, borderColor: 'var(--warn)', color: 'var(--warn)' }} onClick={() => applyPreset(PRESETS.greedy)}>{tr('presetGreedy')}</button>
        <button style={{ ...presetBtn, borderColor: 'var(--danger)', color: 'var(--danger)' }} onClick={() => applyPreset(PRESETS.toxic)}>{tr('presetToxic')}</button>
      </div>

      {/* book rows */}
      {entries.length === 0 && <div style={emptyBox}>{tr('empty')}</div>}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {entries.map(([id, v]) => {
          const m = meta(id);
          const cap = (m.tier === 'T1' ? CAP.T1 : CAP.T2) * 100;
          const concBreach = v > cap + 1e-9;
          return (
            <div key={id} style={{ background: 'var(--bg-surface-2)', border: `1px solid ${concBreach ? 'var(--danger)' : 'var(--border)'}`, borderRadius: 'var(--r-md)', padding: 14 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                <span style={{ fontWeight: 600, color: 'var(--text-primary)', fontSize: 14 }}>
                  {m[lang] ?? m.ru}
                  <span style={{ marginLeft: 8, fontFamily: 'var(--font-mono)', fontSize: 11, padding: '1px 7px', borderRadius: 'var(--r-full)', border: `1px solid ${m.tier === 'T1' ? 'var(--data-teal)' : 'var(--accent)'}`, color: m.tier === 'T1' ? 'var(--data-teal)' : 'var(--accent)' }}>{m.tier}</span>
                  {m.risky && <span style={{ marginLeft: 6, fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--danger)' }}>⚠</span>}
                </span>
                <span style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--text-muted)' }}>APY {m.apy}% · TVL {fmtTvl(m.tvl)}</span>
                  <button style={removeBtn} onClick={() => remove(id)}>{tr('remove')}</button>
                </span>
              </div>
              <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
                <input type="range" min={0} max={100} step={1} value={v}
                  onChange={(e) => setAlloc(id, parseFloat(e.target.value))}
                  style={{ flex: 1, accentColor: concBreach ? 'var(--danger)' : 'var(--accent)' }} />
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 15, fontWeight: 700, width: 56, textAlign: 'right', color: concBreach ? 'var(--danger)' : 'var(--text-primary)' }}>{pct(v)}</span>
              </div>
            </div>
          );
        })}
      </div>

      {/* add row */}
      {available.length > 0 && (
        <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
          <select value={toAdd} onChange={(e) => setToAdd(e.target.value)} style={selectBox}>
            {available.map((u) => <option key={u.id} value={u.id}>{(u[lang] ?? u.ru)} · {u.tier} · {u.apy}%</option>)}
          </select>
          <button style={{ ...presetBtn, marginLeft: 0, borderColor: 'var(--accent)', color: 'var(--accent)' }} onClick={add}>+ {tr('add')}</button>
        </div>
      )}

      {/* summary */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12, marginTop: 18 }}>
        <div style={miniCard}><div style={miniLabel}>{tr('deployed')}</div><div style={{ ...miniVal, color: deployedPct > 100 ? 'var(--danger)' : 'var(--text-primary)' }}>{pct(deployedPct)}</div></div>
        <div style={miniCard}><div style={miniLabel}>{tr('cash')}</div><div style={{ ...miniVal, color: cashPct < 5 ? 'var(--danger)' : 'var(--ok)' }}>{pct(cashPct)}</div></div>
        <div style={miniCard}><div style={miniLabel}>{tr('blended')}</div><div style={{ ...miniVal, color: 'var(--accent)' }}>{blendedApy.toFixed(2)}%</div></div>
      </div>

      {/* gate checks */}
      {checks.length > 0 && (
        <div style={{ marginTop: 16 }}>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, letterSpacing: '0.10em', textTransform: 'uppercase', color: 'var(--text-faint)', marginBottom: 8 }}>{tr('checks')}</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {checks.map((c, i) => (
              <div key={i} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12.5, padding: '5px 10px', borderRadius: 'var(--r-sm)', background: 'var(--bg-surface-2)' }}>
                <span style={{ color: 'var(--text-secondary)' }}>{c.k}</span>
                <span style={{ fontFamily: 'var(--font-mono)' }}>
                  <span style={{ color: 'var(--text-muted)', marginRight: 8 }}>{c.val}</span>
                  <span style={{ color: c.ok ? 'var(--ok)' : 'var(--danger)', fontWeight: 700 }}>{c.ok ? tr('pass') : tr('fail')}</span>
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* verdict */}
      {entries.length > 0 && (
        <div style={{ marginTop: 16, padding: '16px 18px', borderRadius: 'var(--r-md)', border: `1px solid ${verdictColor}`, background: approved ? 'rgba(52,211,153,0.08)' : 'rgba(242,109,109,0.08)' }}>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, letterSpacing: '0.10em', textTransform: 'uppercase', color: 'var(--text-faint)', marginBottom: 6 }}>{tr('verdict')}</div>
          <div style={{ fontWeight: 700, color: verdictColor, fontSize: 16 }}>{approved ? tr('approved') : tr('rejected')}</div>
          {approved
            ? <div style={{ fontSize: 13, color: 'var(--text-secondary)', marginTop: 8, lineHeight: 1.55 }}>{tr('noViol')} {tr('lessonReal')}</div>
            : (
              <ul style={{ margin: '10px 0 0', paddingLeft: 18, fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.55 }}>
                {uniqViol.map((v, i) => <li key={i} style={{ marginBottom: 4 }}>✗ {v}</li>)}
              </ul>
            )}
        </div>
      )}
    </div>
  );
}

const wrap = { background: 'var(--bg-surface)', border: '1px solid var(--border)', borderRadius: 'var(--r-lg)', padding: 24, margin: '28px 0' };
const head = { fontFamily: 'var(--font-mono)', fontSize: 12, letterSpacing: '0.12em', textTransform: 'uppercase', color: 'var(--accent)', marginBottom: 12 };
const miniCard = { background: 'var(--bg-surface-2)', border: '1px solid var(--border)', borderRadius: 'var(--r-md)', padding: '12px 14px', textAlign: 'center' };
const miniLabel = { fontSize: 11, color: 'var(--text-muted)' };
const miniVal = { fontFamily: 'var(--font-mono)', fontSize: 20, fontWeight: 700, marginTop: 4 };
const presetBtn = { marginLeft: 6, padding: '4px 10px', fontSize: 12, borderRadius: 'var(--r-full)', border: '1px solid var(--border)', background: 'transparent', color: 'var(--text-secondary)', cursor: 'pointer', fontFamily: 'var(--font-sans)' };
const removeBtn = { padding: '2px 8px', fontSize: 11, borderRadius: 'var(--r-full)', border: '1px solid var(--border)', background: 'transparent', color: 'var(--text-muted)', cursor: 'pointer', fontFamily: 'var(--font-sans)' };
const selectBox = { flex: 1, padding: '8px 10px', fontSize: 13, borderRadius: 'var(--r-sm)', border: '1px solid var(--border)', background: 'var(--bg-surface-2)', color: 'var(--text-primary)', fontFamily: 'var(--font-sans)' };
const emptyBox = { padding: '16px', borderRadius: 'var(--r-md)', border: '1px dashed var(--border-strong)', color: 'var(--text-muted)', fontSize: 13, textAlign: 'center' };
