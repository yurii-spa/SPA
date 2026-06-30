import { useState, useEffect } from 'react';
import { getLang, markDone } from './progress.js';

/*
 * RiskClassifier.jsx — the A/B/C/D yield-taxonomy card-sort quiz.
 *
 * Given a real yield source, the analyst classifies it:
 *   A = alpha (structural mispricing the desk can harvest)
 *   B = beta  (just market exposure / risk-free-ish carry)
 *   C = risk-compensation (the yield IS payment for a tail you'll eventually pay back)
 *   D = incentive (points / emissions / airdrop — temporary, not fundamental)
 * Instant feedback + explanation. Teaches the core taxonomy.
 *
 * PROPS (optional):
 *   moduleId  string — if set, marks the module done once all sources are classified
 *                      correctly (used by the capstone). If omitted, it's a pure drill.
 */

const T = {
  title: { ru: 'Классификатор риска A/B/C/D', en: 'Risk classifier A/B/C/D' },
  intro: {
    ru: 'Отнеси каждый источник доходности к категории. A=alpha (структурный mispricing), B=beta (рыночная/безрисковая экспозиция), C=risk-comp (доходность — плата за хвост), D=incentive (points/эмиссия).',
    en: 'Classify each yield source. A=alpha (structural mispricing), B=beta (market/near-risk-free), C=risk-comp (yield is payment for a tail), D=incentive (points/emissions).',
  },
  source: { ru: 'Источник доходности', en: 'Yield source' },
  pick: { ru: 'Выбери категорию:', en: 'Pick a category:' },
  correct: { ru: 'Верно', en: 'Correct' },
  wrong: { ru: 'Неверно — правильно:', en: 'Incorrect — correct:' },
  doneAll: { ru: 'Все источники классифицированы ✓', en: 'All sources classified ✓' },
  retry: { ru: 'Заново', en: 'Retry' },
};

const CATS = {
  A: { ru: 'A — alpha', en: 'A — alpha', color: 'var(--data-teal)' },
  B: { ru: 'B — beta', en: 'B — beta', color: 'var(--accent)' },
  C: { ru: 'C — risk-comp', en: 'C — risk-comp', color: 'var(--danger)' },
  D: { ru: 'D — incentive', en: 'D — incentive', color: 'var(--warn)' },
};

const SOURCES = [
  {
    id: 'tbill', label_ru: 'Токенизированные T-bills 3.4% (BUIDL/USYC)', label_en: 'Tokenized T-bills 3.4% (BUIDL/USYC)',
    answer: 'B',
    explain_ru: 'Это safe risk-free floor — чистая beta к ставке ФРС. Не alpha и не плата за хвост: именно с этим floor SPA сравнивает все sleeve\'ы.',
    explain_en: 'A safe risk-free floor — pure beta to the policy rate. The benchmark every SPA sleeve must beat.',
  },
  {
    id: 'susde', label_ru: 'sUSDe 12% (Ethena, funding-carry)', label_en: 'sUSDe 12% (Ethena funding carry)',
    answer: 'C',
    explain_ru: 'Высокий APY = компенсация за funding-flip / depeg-хвост. Когда funding уходит в минус, доходность исчезает, а риск остаётся. Refusal-first это вычисляет.',
    explain_en: 'High APY = compensation for the funding-flip / depeg tail. When funding flips negative the yield vanishes but the risk stays.',
  },
  {
    id: 'aave', label_ru: 'Aave V3 supply 5% (USDC)', label_en: 'Aave V3 supply 5% (USDC)',
    answer: 'B',
    explain_ru: 'Базовая lending-ставка от утилизации — рыночная beta. Скромный спред над floor, без структурного хвоста при низкой утилизации.',
    explain_en: 'Base lending rate from utilization — market beta. Modest spread over the floor, no structural tail at low utilization.',
  },
  {
    id: 'points', label_ru: 'Points-фарм нового протокола (ожидаемый airdrop)', label_en: 'Points farm of a new protocol (expected airdrop)',
    answer: 'D',
    explain_ru: 'Доходность — временный incentive (эмиссия/airdrop), не фундаментальный денежный поток. В SPA — advisory, никогда не аллоцируется live.',
    explain_en: 'The yield is a temporary incentive (emissions/airdrop), not a fundamental cash flow. Advisory only in SPA, never live-allocated.',
  },
  {
    id: 'pt', label_ru: 'Pendle PT mispriced vs fair implied (carry до погашения)', label_en: 'Pendle PT mispriced vs fair implied (carry to maturity)',
    answer: 'A',
    explain_ru: 'Реальный structural alpha: рынок неверно оценил fixed rate, fair-value движок ловит спред. Единственный валидированный live-paper edge Rates Desk.',
    explain_en: 'Real structural alpha: the market mispriced the fixed rate; the fair-value engine harvests the spread. The validated live-paper edge.',
  },
  {
    id: 'loop', label_ru: 'Leverage looping 18% (рекурсивный займ)', label_en: 'Leverage looping 18% (recursive borrow)',
    answer: 'C',
    explain_ru: 'Плечо умножает базовую ставку И хвост ликвидации. APY — компенсация за liquidation-каскад. Высокий structural хейркат → отказ.',
    explain_en: 'Leverage multiplies the base rate AND the liquidation tail. The APY is compensation for a liquidation cascade — refused.',
  },
];

export default function RiskClassifier({ moduleId }) {
  const [lang, setLang] = useState('ru');
  const [answers, setAnswers] = useState({}); // id -> picked cat
  const [completed, setCompleted] = useState(false);

  useEffect(() => {
    setLang(getLang());
    const onLang = () => setLang(getLang());
    window.addEventListener('storage', onLang);
    const obs = new MutationObserver(() => setLang(getLang()));
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ['lang'] });
    return () => { window.removeEventListener('storage', onLang); obs.disconnect(); };
  }, []);
  const tr = (k) => (T[k] ? (T[k][lang] ?? T[k].ru) : k);
  const L = (o, key) => (o && (o[key + '_' + lang] ?? o[key + '_ru'])) || '';

  function pick(srcId, cat) {
    if (answers[srcId]) return; // locked after first pick
    const next = { ...answers, [srcId]: cat };
    setAnswers(next);
    const allDone = SOURCES.every((s) => next[s.id]);
    const allCorrect = SOURCES.every((s) => next[s.id] === s.answer);
    if (allDone) {
      setCompleted(true);
      if (allCorrect && moduleId) markDone(moduleId);
    }
  }
  function reset() { setAnswers({}); setCompleted(false); }

  const correctCount = SOURCES.filter((s) => answers[s.id] === s.answer).length;

  return (
    <div style={wrap}>
      <div style={head}>{tr('title')}</div>
      <p style={{ fontSize: 14, color: 'var(--text-secondary)', lineHeight: 1.6, marginTop: 0 }}>{tr('intro')}</p>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        {SOURCES.map((s) => {
          const picked = answers[s.id];
          const isCorrect = picked === s.answer;
          return (
            <div key={s.id} style={{ background: 'var(--bg-surface-2)', border: '1px solid var(--border)', borderRadius: 'var(--r-md)', padding: 14 }}>
              <div style={{ fontWeight: 600, color: 'var(--text-primary)', marginBottom: 10, fontSize: 15 }}>{L(s, 'label')}</div>
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                {Object.keys(CATS).map((c) => {
                  const sel = picked === c;
                  let bd = 'var(--border)', col = 'var(--text-secondary)';
                  if (picked) {
                    if (c === s.answer) { bd = 'var(--ok)'; col = 'var(--ok)'; }
                    else if (sel) { bd = 'var(--danger)'; col = 'var(--danger)'; }
                  } else { col = CATS[c].color; bd = 'var(--border)'; }
                  return (
                    <button key={c} disabled={!!picked} onClick={() => pick(s.id, c)}
                      style={{
                        padding: '6px 12px', borderRadius: 'var(--r-full)', border: `1px solid ${bd}`,
                        background: 'transparent', color: col, fontSize: 13, fontWeight: 600,
                        cursor: picked ? 'default' : 'pointer', fontFamily: 'var(--font-mono)',
                      }}>
                      {CATS[c][lang] ?? CATS[c].ru}
                    </button>
                  );
                })}
              </div>
              {picked && (
                <div style={{ marginTop: 10, fontSize: 13, lineHeight: 1.55 }}>
                  <span style={{ fontWeight: 700, color: isCorrect ? 'var(--ok)' : 'var(--danger)' }}>
                    {isCorrect ? tr('correct') : `${tr('wrong')} ${CATS[s.answer][lang] ?? CATS[s.answer].ru}`}
                  </span>
                  <span style={{ color: 'var(--text-secondary)' }}> — {L(s, 'explain')}</span>
                </div>
              )}
            </div>
          );
        })}
      </div>

      {completed && (
        <div style={{ marginTop: 16, padding: '14px 16px', borderRadius: 'var(--r-md)', border: `1px solid ${correctCount === SOURCES.length ? 'var(--ok)' : 'var(--border-strong)'}`, background: 'var(--bg-surface-2)', textAlign: 'center' }}>
          <div style={{ fontWeight: 700, color: correctCount === SOURCES.length ? 'var(--ok)' : 'var(--text-primary)' }}>
            {correctCount} / {SOURCES.length}{correctCount === SOURCES.length ? ' · ' + tr('doneAll') : ''}
          </div>
          <button style={{ marginTop: 10, background: 'var(--accent)', color: '#fff', border: 'none', borderRadius: 'var(--r-sm)', padding: '8px 18px', fontSize: 13, fontWeight: 600, cursor: 'pointer' }} onClick={reset}>{tr('retry')}</button>
        </div>
      )}
    </div>
  );
}

const wrap = { background: 'var(--bg-surface)', border: '1px solid var(--border)', borderRadius: 'var(--r-lg)', padding: 24, margin: '28px 0' };
const head = { fontFamily: 'var(--font-mono)', fontSize: 12, letterSpacing: '0.12em', textTransform: 'uppercase', color: 'var(--accent)', marginBottom: 12 };
