import { useState, useEffect } from 'react';
import { getLang } from './progress.js';

/*
 * HaircutVetoSim.jsx — the «токсичность нельзя обойти размером» simulator.
 *
 * Mirrors spa_core/strategy_lab/rates_desk/rate_policy.py + fair_value_engine.py
 * CONCEPTUALLY (deterministic, no LLM, no fabrication):
 *
 *   structural_haircut = peg_hc + funding_hc + oracle_hc + protocol_hc
 *       (the SIZE-INDEPENDENT tail — EXCLUDES the liquidity term)
 *   total_haircut      = structural_haircut + liquidity_hc   (liquidity grows with size)
 *
 *   TAIL_VETO (the REFUSE) fires when structural_haircut > MAX_STRUCTURAL_HAIRCUT (0.06).
 *   Because the veto is on the SIZE-INDEPENDENT term, sizing DOWN only shrinks the
 *   liquidity term — it can NEVER lift a structural-cap breach. That is the lesson:
 *   a toxic book is refused at ANY size.
 *
 * The sliders are the four structural risk inputs (peg/funding/oracle/protocol) each
 * already expressed as their haircut contribution (0..cap), plus a size slider that
 * only feeds the liquidity term — to demonstrate the verdict does not move with size.
 *
 * Calibrated constants pinned from contracts.py / config.py defaults.
 */

const MAX_STRUCTURAL = 0.06; // CALIBRATED_MAX_STRUCTURAL_HAIRCUT
const MAX_TOTAL = 0.12;      // CALIBRATED_MAX_TOTAL_HAIRCUT
const CAP = { peg: 0.10, funding: 0.04, oracle: 0.04, protocol: 0.06, liquidity: 0.05 };

const T = {
  title: { ru: 'Симулятор вето структурным хейркатом', en: 'Structural-haircut veto simulator' },
  intro: {
    ru: 'Двигай ползунки риска. Структурный хейркат (peg+funding+oracle+protocol) НЕ зависит от размера. Если он превышает cap — позиция отклонена при ЛЮБОМ размере.',
    en: 'Move the risk sliders. The structural haircut (peg+funding+oracle+protocol) is size-independent. If it exceeds the cap, the position is refused at ANY size.',
  },
  peg: { ru: 'Peg-риск (депег обеспечения)', en: 'Peg risk' },
  funding: { ru: 'Funding-риск (отрицательный funding)', en: 'Funding risk' },
  oracle: { ru: 'Oracle-риск (устаревание оракула)', en: 'Oracle risk' },
  protocol: { ru: 'Protocol-риск (вложенность/концентрация)', en: 'Protocol risk' },
  size: { ru: 'Размер позиции (% от exit-ликвидности)', en: 'Position size (% of exit liquidity)' },
  structural: { ru: 'Структурный хейркат (size-independent)', en: 'Structural haircut (size-independent)' },
  liquidity: { ru: 'Liquidity-хейркат (зависит от размера)', en: 'Liquidity haircut (size-dependent)' },
  total: { ru: 'Полный хейркат', en: 'Total haircut' },
  cap: { ru: 'cap', en: 'cap' },
  verdict: { ru: 'Вердикт', en: 'Verdict' },
  approved: { ru: 'ДОПУЩЕНО', en: 'APPROVED' },
  tailVeto: { ru: 'ОТКАЗ — TAIL_VETO (структурный cap пробит)', en: 'REFUSED — TAIL_VETO (structural cap breached)' },
  totalVeto: { ru: 'ОТКАЗ — TAIL_VETO (полный хейркат > cap)', en: 'REFUSED — TAIL_VETO (total > cap)' },
  lessonRefused: {
    ru: 'Двигай размер вниз до 1% — вердикт НЕ меняется. Структурный хейркат size-independent: токсичность нельзя обойти размером.',
    en: 'Drag size down to 1% — the verdict does NOT change. The structural haircut is size-independent: toxicity cannot be sized around.',
  },
  lessonApproved: {
    ru: 'Структурный хвост ниже cap — книга проходит refusal-first гейт. Дальше её ещё проверит экономика и глобальный RiskPolicy.',
    en: 'Structural tail below the cap — the book passes the refusal-first gate. Economics + the global RiskPolicy still check it next.',
  },
  preset: { ru: 'Пресеты:', en: 'Presets:' },
  presetClean: { ru: 'Чистый carry (PT)', en: 'Clean carry (PT)' },
  presetLst: { ru: 'Чистый LST', en: 'Clean LST' },
  presetToxic: { ru: 'Токсичный LRT-рестейк', en: 'Toxic LRT restaking' },
};

const PRESETS = {
  clean: { peg: 0.005, funding: 0.0, oracle: 0.003, protocol: 0.007, size: 20 },   // ≈0.0153 structural
  lst: { peg: 0.020, funding: 0.0, oracle: 0.006, protocol: 0.020, size: 20 },      // ≈0.046 structural
  toxic: { peg: 0.040, funding: 0.025, oracle: 0.012, protocol: 0.020, size: 20 },  // ≈0.097 structural
};

function Slider({ label, value, max, onChange, color }) {
  return (
    <div style={{ marginBottom: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, marginBottom: 6 }}>
        <span style={{ color: 'var(--text-secondary)' }}>{label}</span>
        <span style={{ fontFamily: 'var(--font-mono)', color: color || 'var(--text-primary)' }}>
          {(value * 100).toFixed(2)}%
        </span>
      </div>
      <input type="range" min={0} max={max} step={max / 200} value={value}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        style={{ width: '100%', accentColor: color || 'var(--accent)' }} />
    </div>
  );
}

export default function HaircutVetoSim() {
  const [lang, setLang] = useState('ru');
  const [peg, setPeg] = useState(PRESETS.toxic.peg);
  const [funding, setFunding] = useState(PRESETS.toxic.funding);
  const [oracle, setOracle] = useState(PRESETS.toxic.oracle);
  const [protocol, setProtocol] = useState(PRESETS.toxic.protocol);
  const [sizePct, setSizePct] = useState(PRESETS.toxic.size);

  useEffect(() => {
    setLang(getLang());
    const onLang = () => setLang(getLang());
    window.addEventListener('storage', onLang);
    const obs = new MutationObserver(() => setLang(getLang()));
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ['lang'] });
    return () => { window.removeEventListener('storage', onLang); obs.disconnect(); };
  }, []);
  const tr = (k) => (T[k] ? (T[k][lang] ?? T[k].ru) : k);

  function applyPreset(p) {
    setPeg(p.peg); setFunding(p.funding); setOracle(p.oracle); setProtocol(p.protocol); setSizePct(p.size);
  }

  // liquidity haircut grows linearly with size fraction (k_liquidity * ratio, clamped to cap)
  const sizeFrac = sizePct / 100;
  const liquidityHc = Math.min(CAP.liquidity, 0.20 * sizeFrac); // conceptual k_liquidity≈0.20

  const structural = peg + funding + oracle + protocol;
  const total = structural + liquidityHc;

  const structuralBreach = structural > MAX_STRUCTURAL;
  const totalBreach = total > MAX_TOTAL;
  const refused = structuralBreach || totalBreach;

  const verdictColor = refused ? 'var(--danger)' : 'var(--ok)';
  const verdictText = structuralBreach ? tr('tailVeto') : totalBreach ? tr('totalVeto') : tr('approved');

  const bar = (val, cap, color) => (
    <div style={{ height: 8, background: 'var(--bg-surface-2)', borderRadius: 'var(--r-full)', overflow: 'hidden', marginTop: 4 }}>
      <div style={{ width: Math.min(100, (val / cap) * 100) + '%', height: '100%', background: color, transition: 'width 200ms' }} />
    </div>
  );

  return (
    <div style={wrap}>
      <div style={head}>{tr('title')}</div>
      <p style={{ fontSize: 14, color: 'var(--text-secondary)', lineHeight: 1.6, marginTop: 0 }}>{tr('intro')}</p>

      <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 12 }}>
        {tr('preset')}{' '}
        <button style={presetBtn} onClick={() => applyPreset(PRESETS.clean)}>{tr('presetClean')}</button>
        <button style={presetBtn} onClick={() => applyPreset(PRESETS.lst)}>{tr('presetLst')}</button>
        <button style={{ ...presetBtn, borderColor: 'var(--danger)', color: 'var(--danger)' }} onClick={() => applyPreset(PRESETS.toxic)}>{tr('presetToxic')}</button>
      </div>

      <Slider label={tr('peg')} value={peg} max={CAP.peg} onChange={setPeg} color="var(--accent)" />
      <Slider label={tr('funding')} value={funding} max={CAP.funding} onChange={setFunding} color="var(--accent)" />
      <Slider label={tr('oracle')} value={oracle} max={CAP.oracle} onChange={setOracle} color="var(--accent)" />
      <Slider label={tr('protocol')} value={protocol} max={CAP.protocol} onChange={setProtocol} color="var(--accent)" />

      <div style={{ borderTop: '1px solid var(--border)', margin: '18px 0', paddingTop: 14 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, marginBottom: 6 }}>
          <span style={{ color: 'var(--text-secondary)' }}>{tr('size')}</span>
          <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--data-teal)' }}>{sizePct.toFixed(0)}%</span>
        </div>
        <input type="range" min={1} max={100} step={1} value={sizePct}
          onChange={(e) => setSizePct(parseFloat(e.target.value))}
          style={{ width: '100%', accentColor: 'var(--data-teal)' }} />
      </div>

      {/* computed haircuts */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr', gap: 12, marginTop: 8 }}>
        <div>
          <div style={metricRow}>
            <span>{tr('structural')}</span>
            <span style={{ fontFamily: 'var(--font-mono)', color: structuralBreach ? 'var(--danger)' : 'var(--text-primary)' }}>
              {(structural * 100).toFixed(2)}% / {tr('cap')} {(MAX_STRUCTURAL * 100).toFixed(0)}%
            </span>
          </div>
          {bar(structural, MAX_STRUCTURAL, structuralBreach ? 'var(--danger)' : 'var(--ok)')}
        </div>
        <div>
          <div style={metricRow}>
            <span>{tr('liquidity')}</span>
            <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--data-teal)' }}>{(liquidityHc * 100).toFixed(2)}%</span>
          </div>
          {bar(liquidityHc, CAP.liquidity, 'var(--data-teal)')}
        </div>
        <div>
          <div style={metricRow}>
            <span>{tr('total')}</span>
            <span style={{ fontFamily: 'var(--font-mono)', color: totalBreach ? 'var(--danger)' : 'var(--text-primary)' }}>
              {(total * 100).toFixed(2)}% / {tr('cap')} {(MAX_TOTAL * 100).toFixed(0)}%
            </span>
          </div>
          {bar(total, MAX_TOTAL, totalBreach ? 'var(--danger)' : 'var(--text-secondary)')}
        </div>
      </div>

      {/* verdict */}
      <div style={{
        marginTop: 18, padding: '16px 18px', borderRadius: 'var(--r-md)',
        border: `1px solid ${verdictColor}`, background: refused ? 'rgba(242,109,109,0.08)' : 'rgba(52,211,153,0.08)',
      }}>
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, letterSpacing: '0.10em', textTransform: 'uppercase', color: 'var(--text-faint)', marginBottom: 6 }}>
          {tr('verdict')}
        </div>
        <div style={{ fontWeight: 700, color: verdictColor, fontSize: 16 }}>{verdictText}</div>
        <div style={{ fontSize: 13, color: 'var(--text-secondary)', marginTop: 8, lineHeight: 1.55 }}>
          {refused ? tr('lessonRefused') : tr('lessonApproved')}
        </div>
      </div>
    </div>
  );
}

const wrap = { background: 'var(--bg-surface)', border: '1px solid var(--border)', borderRadius: 'var(--r-lg)', padding: 24, margin: '28px 0' };
const head = { fontFamily: 'var(--font-mono)', fontSize: 12, letterSpacing: '0.12em', textTransform: 'uppercase', color: 'var(--accent)', marginBottom: 12 };
const metricRow = { display: 'flex', justifyContent: 'space-between', fontSize: 13, color: 'var(--text-secondary)' };
const presetBtn = { marginLeft: 6, padding: '4px 10px', fontSize: 12, borderRadius: 'var(--r-full)', border: '1px solid var(--border)', background: 'transparent', color: 'var(--text-secondary)', cursor: 'pointer', fontFamily: 'var(--font-sans)' };
