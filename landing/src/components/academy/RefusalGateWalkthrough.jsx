import { useState, useEffect } from 'react';
import { getLang, recordPlaygroundTried } from './progress.js';

/*
 * RefusalGateWalkthrough.jsx — step a candidate opportunity THROUGH the refusal-first
 * gate one animated step at a time and watch it «think».
 *
 * Mirrors the refusal-first pipeline CONCEPTUALLY (deterministic, no LLM, fail-CLOSED):
 *   1. INPUT       — a yield + its risk shape
 *   2. CLASSIFY    — A/B/C/D taxonomy (alpha / beta / risk-comp / incentive)
 *   3. HAIRCUTS    — peg + funding + oracle + protocol structural haircuts
 *   4. TAIL-VETO   — structural_haircut > MAX_STRUCTURAL (0.06) → REFUSE at ANY size
 *                    (mirrors rate_policy.py: the veto is on the SIZE-INDEPENDENT term)
 *   5. CAPS        — global RiskPolicy (policy.py): APY-band 1–30%, TVL≥$5M, tier caps
 *   6. VERDICT     — SAFE / WATCH / REFUSE with the reason
 *
 * Calibrated constants pinned from contracts.py / config.py defaults (same as HaircutVetoSim):
 *   MAX_STRUCTURAL = 0.06, MAX_TOTAL = 0.12.
 *
 * Pre-loaded REAL examples reach the correct verdict at ANY size:
 *   ezETH 35% (LRT)  → REFUSE (structural tail-veto + APY>30 ceiling)
 *   sUSDe 12% carry  → WATCH  (elevated but sub-veto structural tail; class C)
 *   Aave V3 5%       → SAFE   (clean T1 beta, structural tail tiny)
 */

const MAX_STRUCTURAL = 0.06; // CALIBRATED_MAX_STRUCTURAL_HAIRCUT
const MAX_TOTAL = 0.12;      // CALIBRATED_MAX_TOTAL_HAIRCUT
const APY_MAX = 30.0, APY_MIN = 1.0, TVL_MIN = 5_000_000;

// Real examples. Haircut contributions are honest order-of-magnitude marks per the
// rates-desk haircut model (peg/funding/oracle/protocol), NOT fabricated favourably.
const EXAMPLES = [
  {
    id: 'ezeth', ru: 'ezETH 35% (LRT-рестейк, плечо)', en: 'ezETH 35% (LRT restaking, levered)',
    apy: 35.0, tvl: 140_000_000, tier: 'T2', cls: 'C',
    hc: { peg: 0.040, funding: 0.025, oracle: 0.012, protocol: 0.020 }, // structural ≈ 0.097 > 0.06
    expect: 'REFUSE',
  },
  {
    id: 'susde', ru: 'sUSDe 12% (Ethena funding carry)', en: 'sUSDe 12% (Ethena funding carry)',
    apy: 12.0, tvl: 320_000_000, tier: 'T2', cls: 'C',
    hc: { peg: 0.020, funding: 0.018, oracle: 0.006, protocol: 0.010 }, // structural ≈ 0.054 < 0.06, but elevated
    expect: 'WATCH',
  },
  {
    id: 'aave', ru: 'Aave V3 5% (USDC supply)', en: 'Aave V3 5% (USDC supply)',
    apy: 5.0, tvl: 1_200_000_000, tier: 'T1', cls: 'B',
    hc: { peg: 0.003, funding: 0.0, oracle: 0.003, protocol: 0.006 }, // structural ≈ 0.012 — tiny
    expect: 'SAFE',
  },
];

const CLS = {
  A: { ru: 'A — alpha (структурный edge)', en: 'A — alpha (structural edge)' },
  B: { ru: 'B — beta (рыночная экспозиция)', en: 'B — beta (market exposure)' },
  C: { ru: 'C — risk-comp (плата за хвост)', en: 'C — risk-comp (paid for a tail)' },
  D: { ru: 'D — incentive (эмиссия/points)', en: 'D — incentive (emissions/points)' },
};

const T = {
  title: { ru: 'Прогон через refusal-first гейт', en: 'Refusal-first gate walkthrough' },
  intro: {
    ru: 'Выбери кандидата и шагай через гейт по одному шагу. Видно, как гейт «думает»: классификация A/B/C/D → структурные хейркаты → TAIL-VETO → cap\'ы RiskPolicy → вердикт SAFE/WATCH/REFUSE. Токсичность отказывается при ЛЮБОМ размере.',
    en: 'Pick a candidate and step through the gate one step at a time. Watch it «think»: A/B/C/D classify → structural haircuts → TAIL-VETO → RiskPolicy caps → SAFE/WATCH/REFUSE. Toxicity is refused at ANY size.',
  },
  pick: { ru: 'Кандидат:', en: 'Candidate:' },
  next: { ru: 'Следующий шаг →', en: 'Next step →' },
  restart: { ru: '↻ Заново', en: '↻ Restart' },
  auto: { ru: '▶ Авто', en: '▶ Auto' },
  step: { ru: 'Шаг', en: 'Step' },
  of: { ru: 'из', en: 'of' },
  // step labels
  s_input: { ru: '1 · Вход', en: '1 · Input' },
  s_classify: { ru: '2 · Классификация A/B/C/D', en: '2 · Classify A/B/C/D' },
  s_haircuts: { ru: '3 · Структурные хейркаты', en: '3 · Structural haircuts' },
  s_veto: { ru: '4 · TAIL-VETO (size-independent)', en: '4 · TAIL-VETO (size-independent)' },
  s_caps: { ru: '5 · Cap\'ы RiskPolicy', en: '5 · RiskPolicy caps' },
  s_verdict: { ru: '6 · Вердикт', en: '6 · Verdict' },
  // copy
  inputDesc: { ru: 'Доходность и её risk shape поступают в гейт. Высокий APY — не «хорошо», а сигнал: за что платят?', en: 'A yield + its risk shape enter the gate. High APY isn\'t «good» — it\'s a signal: paid for what?' },
  clsDesc: { ru: 'Гейт сперва спрашивает: это alpha (A), beta (B), плата за хвост (C) или incentive (D)? Только A — настоящий edge.', en: 'The gate first asks: is this alpha (A), beta (B), tail-comp (C) or incentive (D)? Only A is real edge.' },
  hcDesc: { ru: 'Считаем четыре структурных хейрката. Их сумма — size-INDEPENDENT хвост: peg + funding + oracle + protocol.', en: 'Compute four structural haircuts. Their sum is the size-INDEPENDENT tail: peg + funding + oracle + protocol.' },
  vetoDesc: { ru: 'Если структурный хейркат > cap (6%) — TAIL-VETO. Вето на size-independent члене ⇒ уменьшение размера НЕ спасает: отказ при любом размере.', en: 'If the structural haircut > cap (6%) — TAIL-VETO. The veto is on the size-independent term ⇒ sizing down can\'t save it: refused at any size.' },
  capsDesc: { ru: 'Под refusal-гейтом — глобальный RiskPolicy: APY входа 1–30%, TVL≥$5M, tier-cap\'ы. Логика AND, не OR.', en: 'Under the refusal gate sits the global RiskPolicy: entry APY 1–30%, TVL≥$5M, tier caps. AND-logic, not OR.' },
  structural: { ru: 'Структурный хейркат', en: 'Structural haircut' },
  cap: { ru: 'cap', en: 'cap' },
  vetoFired: { ru: 'TAIL-VETO СРАБОТАЛ — структурный cap пробит', en: 'TAIL-VETO FIRED — structural cap breached' },
  vetoClear: { ru: 'Вето НЕ сработало — структурный хвост ниже cap', en: 'Veto did NOT fire — structural tail below cap' },
  capApyHi: { ru: 'APY > 30% — потолок входа пробит (риск слишком высок)', en: 'APY > 30% — entry ceiling breached (risk too high)' },
  capOk: { ru: 'Cap\'ы RiskPolicy пройдены (APY-band, TVL, tier)', en: 'RiskPolicy caps cleared (APY-band, TVL, tier)' },
  verdict: { ru: 'Финальный вердикт', en: 'Final verdict' },
  SAFE: { ru: 'SAFE — допущено', en: 'SAFE — admitted' },
  WATCH: { ru: 'WATCH — под наблюдением, не входить агрессивно', en: 'WATCH — monitor, no aggressive entry' },
  REFUSE: { ru: 'REFUSE — отказ', en: 'REFUSE — refused' },
  reason: { ru: 'Причина', en: 'Reason' },
  rEzeth: { ru: 'Структурный хейркат ~9.7% > 6% → TAIL-VETO (peg+funding LRT-хвост), и APY 35% > 30% потолка. Отказ при любом размере — это ровно паттерн ezETH/over-levered-USDe, от которого деск отказывается.', en: 'Structural haircut ~9.7% > 6% → TAIL-VETO (LRT peg+funding tail), and APY 35% > 30% ceiling. Refused at any size — exactly the ezETH/over-levered-USDe pattern the desk refuses.' },
  rSusde: { ru: 'Структурный хвост ~5.4% — ниже 6% cap, но повышен (funding-flip риск, класс C). Гейт не отказывает, но и не допускает агрессивно: WATCH. Доходность — компенсация за хвост, а не alpha.', en: 'Structural tail ~5.4% — below the 6% cap but elevated (funding-flip risk, class C). The gate neither refuses nor admits aggressively: WATCH. The yield is tail-comp, not alpha.' },
  rAave: { ru: 'Структурный хвост ~1.2% — крошечный; APY 5% в band\'е; TVL $1.2B ≫ $5M; чистая T1 beta. Гейт допускает: SAFE.', en: 'Structural tail ~1.2% — tiny; APY 5% in band; TVL $1.2B ≫ $5M; clean T1 beta. The gate admits: SAFE.' },
  expectMatch: { ru: 'Ожидаемый вердикт', en: 'Expected verdict' },
};

function pct(v) { return (v * 100).toFixed(2) + '%'; }
function fmtTvl(v) { return v >= 1e9 ? '$' + (v / 1e9).toFixed(1) + 'B' : '$' + (v / 1e6).toFixed(0) + 'M'; }

const STEPS = ['s_input', 's_classify', 's_haircuts', 's_veto', 's_caps', 's_verdict'];

export default function RefusalGateWalkthrough() {
  const [lang, setLang] = useState('ru');
  const [exId, setExId] = useState(EXAMPLES[0].id);
  const [step, setStep] = useState(0);

  useEffect(() => {
    setLang(getLang());
    const onLang = () => setLang(getLang());
    window.addEventListener('storage', onLang);
    const obs = new MutationObserver(() => setLang(getLang()));
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ['lang'] });
    return () => { window.removeEventListener('storage', onLang); obs.disconnect(); };
  }, []);
  const tr = (k) => (T[k] ? (T[k][lang] ?? T[k].ru) : k);

  const ex = EXAMPLES.find((e) => e.id === exId);
  const structural = ex.hc.peg + ex.hc.funding + ex.hc.oracle + ex.hc.protocol;
  const vetoFired = structural > MAX_STRUCTURAL;
  const apyHi = ex.apy > APY_MAX, apyLo = ex.apy < APY_MIN, tvlLow = ex.tvl < TVL_MIN;
  const capsFail = apyHi || apyLo || tvlLow;

  // verdict — deterministic. REFUSE if veto or caps fail; else WATCH if class C / elevated tail; else SAFE.
  let verdict;
  if (vetoFired || capsFail) verdict = 'REFUSE';
  else if (ex.cls === 'C' || ex.cls === 'D' || structural > MAX_STRUCTURAL * 0.7) verdict = 'WATCH';
  else verdict = 'SAFE';

  const vColor = verdict === 'REFUSE' ? 'var(--danger)' : verdict === 'WATCH' ? 'var(--warn)' : 'var(--ok)';
  const reasonKey = ex.id === 'ezeth' ? 'rEzeth' : ex.id === 'susde' ? 'rSusde' : 'rAave';

  // engagement XP + "playground" badge on first interaction (idempotent, SSR-safe)
  const tried = () => recordPlaygroundTried('RefusalGateWalkthrough');
  function pickEx(id) { tried(); setExId(id); setStep(0); }

  return (
    <div style={wrap}>
      <div style={head}>{tr('title')}</div>
      <p style={{ fontSize: 14, color: 'var(--text-secondary)', lineHeight: 1.6, marginTop: 0 }}>{tr('intro')}</p>

      {/* example picker */}
      <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 14 }}>
        {tr('pick')}{' '}
        {EXAMPLES.map((e) => (
          <button key={e.id} onClick={() => pickEx(e.id)}
            style={{ ...pillBtn, borderColor: exId === e.id ? 'var(--accent)' : 'var(--border)', color: exId === e.id ? 'var(--accent)' : 'var(--text-secondary)' }}>
            {(e[lang] ?? e.ru).split(' ')[0]}
          </button>
        ))}
      </div>

      {/* step controls */}
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 14 }}>
        <button style={{ ...ctrlBtn, borderColor: 'var(--accent)', color: 'var(--accent)' }} disabled={step >= STEPS.length - 1} onClick={() => { tried(); setStep((s) => Math.min(STEPS.length - 1, s + 1)); }}>
          {tr('next')}
        </button>
        <button style={ctrlBtn} onClick={() => { tried(); setStep(STEPS.length - 1); }}>{tr('auto')}</button>
        <button style={ctrlBtn} onClick={() => { tried(); setStep(0); }}>{tr('restart')}</button>
        <span style={{ marginLeft: 'auto', fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--text-muted)' }}>{tr('step')} {step + 1} {tr('of')} {STEPS.length}</span>
      </div>

      {/* step rail */}
      <div style={{ display: 'flex', gap: 4, marginBottom: 16 }}>
        {STEPS.map((s, i) => (
          <div key={s} style={{ flex: 1, height: 4, borderRadius: 'var(--r-full)', background: i <= step ? 'var(--accent)' : 'var(--bg-surface-2)', transition: 'background 250ms' }} />
        ))}
      </div>

      {/* progressive panels */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        {/* 1 input */}
        <Panel show={step >= 0} label={tr('s_input')} active={step === 0}>
          <div style={{ fontWeight: 600, color: 'var(--text-primary)', fontSize: 15 }}>{ex[lang] ?? ex.ru}</div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 13, color: 'var(--text-muted)', marginTop: 6 }}>
            APY {ex.apy}% · TVL {fmtTvl(ex.tvl)} · {ex.tier}
          </div>
          <div style={{ fontSize: 13, color: 'var(--text-secondary)', marginTop: 8, lineHeight: 1.55 }}>{tr('inputDesc')}</div>
        </Panel>

        {/* 2 classify */}
        <Panel show={step >= 1} label={tr('s_classify')} active={step === 1}>
          <div style={{ fontWeight: 700, color: ex.cls === 'A' ? 'var(--data-teal)' : ex.cls === 'B' ? 'var(--accent)' : ex.cls === 'C' ? 'var(--danger)' : 'var(--warn)', fontSize: 15 }}>
            {CLS[ex.cls][lang] ?? CLS[ex.cls].ru}
          </div>
          <div style={{ fontSize: 13, color: 'var(--text-secondary)', marginTop: 8, lineHeight: 1.55 }}>{tr('clsDesc')}</div>
        </Panel>

        {/* 3 haircuts */}
        <Panel show={step >= 2} label={tr('s_haircuts')} active={step === 2}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
            {['peg', 'funding', 'oracle', 'protocol'].map((k) => (
              <div key={k} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, padding: '4px 0' }}>
                <span style={{ color: 'var(--text-secondary)' }}>{k}</span>
                <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--text-primary)' }}>{pct(ex.hc[k])}</span>
              </div>
            ))}
          </div>
          <div style={{ fontSize: 13, color: 'var(--text-secondary)', marginTop: 8, lineHeight: 1.55 }}>{tr('hcDesc')}</div>
        </Panel>

        {/* 4 veto */}
        <Panel show={step >= 3} label={tr('s_veto')} active={step === 3}>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, marginBottom: 6 }}>
            <span style={{ color: 'var(--text-secondary)' }}>{tr('structural')}</span>
            <span style={{ fontFamily: 'var(--font-mono)', color: vetoFired ? 'var(--danger)' : 'var(--text-primary)' }}>{pct(structural)} / {tr('cap')} {pct(MAX_STRUCTURAL)}</span>
          </div>
          <div style={{ height: 8, background: 'var(--bg-surface-2)', borderRadius: 'var(--r-full)', overflow: 'hidden' }}>
            <div style={{ width: Math.min(100, (structural / MAX_STRUCTURAL) * 100) + '%', height: '100%', background: vetoFired ? 'var(--danger)' : 'var(--ok)', transition: 'width 300ms' }} />
          </div>
          <div style={{ fontWeight: 700, color: vetoFired ? 'var(--danger)' : 'var(--ok)', fontSize: 14, marginTop: 10 }}>{vetoFired ? tr('vetoFired') : tr('vetoClear')}</div>
          <div style={{ fontSize: 13, color: 'var(--text-secondary)', marginTop: 8, lineHeight: 1.55 }}>{tr('vetoDesc')}</div>
        </Panel>

        {/* 5 caps */}
        <Panel show={step >= 4} label={tr('s_caps')} active={step === 4}>
          <div style={{ fontWeight: 700, color: capsFail ? 'var(--danger)' : 'var(--ok)', fontSize: 14 }}>
            {apyHi ? tr('capApyHi') : capsFail ? '✗ caps' : tr('capOk')}
          </div>
          <div style={{ fontSize: 13, color: 'var(--text-secondary)', marginTop: 8, lineHeight: 1.55 }}>{tr('capsDesc')}</div>
        </Panel>

        {/* 6 verdict */}
        <Panel show={step >= 5} label={tr('s_verdict')} active={step === 5}>
          <div style={{ padding: '14px 16px', borderRadius: 'var(--r-md)', border: `1px solid ${vColor}`, background: verdict === 'REFUSE' ? 'rgba(242,109,109,0.08)' : verdict === 'WATCH' ? 'rgba(242,179,60,0.08)' : 'rgba(52,211,153,0.08)' }}>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, letterSpacing: '0.10em', textTransform: 'uppercase', color: 'var(--text-faint)', marginBottom: 6 }}>{tr('verdict')}</div>
            <div style={{ fontWeight: 700, color: vColor, fontSize: 18 }}>{tr(verdict)}</div>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>
              {tr('expectMatch')}: {ex.expect} {verdict === ex.expect ? '✓' : '✗'}
            </div>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, letterSpacing: '0.10em', textTransform: 'uppercase', color: 'var(--text-faint)', margin: '10px 0 6px' }}>{tr('reason')}</div>
            <div style={{ fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.55 }}>{tr(reasonKey)}</div>
          </div>
        </Panel>
      </div>
    </div>
  );
}

function Panel({ show, label, active, children }) {
  if (!show) return null;
  return (
    <div style={{ background: 'var(--bg-surface-2)', border: `1px solid ${active ? 'var(--accent)' : 'var(--border)'}`, borderRadius: 'var(--r-md)', padding: 14, opacity: active ? 1 : 0.92 }}>
      <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, letterSpacing: '0.10em', textTransform: 'uppercase', color: active ? 'var(--accent)' : 'var(--text-faint)', marginBottom: 8 }}>{label}</div>
      {children}
    </div>
  );
}

const wrap = { background: 'var(--bg-surface)', border: '1px solid var(--border)', borderRadius: 'var(--r-lg)', padding: 24, margin: '28px 0' };
const head = { fontFamily: 'var(--font-mono)', fontSize: 12, letterSpacing: '0.12em', textTransform: 'uppercase', color: 'var(--accent)', marginBottom: 12 };
const ctrlBtn = { padding: '7px 14px', fontSize: 13, fontWeight: 600, borderRadius: 'var(--r-sm)', border: '1px solid var(--border)', background: 'transparent', color: 'var(--text-secondary)', cursor: 'pointer', fontFamily: 'var(--font-sans)' };
const pillBtn = { marginLeft: 6, padding: '4px 12px', fontSize: 12, fontWeight: 600, borderRadius: 'var(--r-full)', border: '1px solid var(--border)', background: 'transparent', cursor: 'pointer', fontFamily: 'var(--font-sans)' };
