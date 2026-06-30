import { useState, useEffect } from 'react';
import { getLang, recordPlaygroundTried } from './progress.js';

/*
 * KillSwitchLadder.jsx — the two-tier drawdown ladder (ADR-048).
 *
 * Mirrors spa_core/governance/kill_switch.py thresholds EXACTLY:
 *   NONE          drawdown < 5%
 *   SOFT_DERISK   5% <= drawdown < 10%  → halt new / no INCREASE (hold+reduce OK), WARNING, NO liquidation
 *   HARD_KILL     drawdown >= 10%       → full kill → all-cash {"cash": 1.0}
 *
 * Boundaries are inclusive (>=) matching the ADR-048 reconciliation. Pure, no fetch.
 */

const SOFT = 5.0;
const HARD = 10.0;

const T = {
  title: { ru: 'Лестница kill-switch (ADR-048)', en: 'Kill-switch ladder (ADR-048)' },
  intro: {
    ru: 'Двигай просадку (drawdown) от пика. Два уровня реакции: мягкий de-risk при ≥5%, жёсткий all-cash при ≥10%. Границы inclusive.',
    en: 'Slide the peak-to-current drawdown. Two tiers: soft de-risk at ≥5%, hard all-cash at ≥10%. Inclusive boundaries.',
  },
  drawdown: { ru: 'Просадка от пика (evidenced)', en: 'Peak-to-current drawdown (evidenced)' },
  tier: { ru: 'Текущий уровень', en: 'Current tier' },
  none: { ru: 'NONE — норма', en: 'NONE — normal' },
  soft: { ru: 'SOFT_DERISK — мягкий de-risk', en: 'SOFT_DERISK — soft de-risk' },
  hard: { ru: 'HARD_KILL — жёсткий kill', en: 'HARD_KILL — hard kill' },
  effect: { ru: 'Эффект', en: 'Effect' },
  effNone: { ru: 'Торгуем штатно. Все гейты активны, новые позиции разрешены.', en: 'Trading normally. All gates active, new positions allowed.' },
  effSoft: { ru: 'HALT новых аллокаций / запрет на УВЕЛИЧЕНИЕ экспозиции (hold + reduce OK). Edge-triggered WARNING. НЕ ликвидирует — 5% часто восстановимый депег/волатильность.', en: 'Halt new allocations / no INCREASE (hold + reduce OK). Edge-triggered WARNING. Does NOT liquidate — 5% is often a recoverable wobble.' },
  effHard: { ru: 'Полный kill → всё в кэш {"cash": 1.0}. 10% просадки на стейбл-книге = реальный коллапс протокола, не шум. approved=False нельзя переопределить.', en: 'Full kill → all-cash {"cash": 1.0}. A 10% drawdown on a stablecoin book = real collapse, not noise. approved=False is final.' },
};

const RUNGS = [
  { key: 'none', from: 0, to: SOFT, color: 'var(--ok)', bg: 'rgba(52,211,153,0.12)', label: 'NONE' },
  { key: 'soft', from: SOFT, to: HARD, color: 'var(--warn)', bg: 'rgba(242,179,60,0.12)', label: 'SOFT_DERISK ≥5%' },
  { key: 'hard', from: HARD, to: 15, color: 'var(--danger)', bg: 'rgba(242,109,109,0.12)', label: 'HARD_KILL ≥10%' },
];

export default function KillSwitchLadder() {
  const [lang, setLang] = useState('ru');
  const [dd, setDd] = useState(11);

  useEffect(() => {
    setLang(getLang());
    const onLang = () => setLang(getLang());
    window.addEventListener('storage', onLang);
    const obs = new MutationObserver(() => setLang(getLang()));
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ['lang'] });
    return () => { window.removeEventListener('storage', onLang); obs.disconnect(); };
  }, []);
  const tr = (k) => (T[k] ? (T[k][lang] ?? T[k].ru) : k);

  // tier logic mirrors kill_switch.drawdown_tier (inclusive >=)
  let tierKey = 'none';
  if (dd >= HARD) tierKey = 'hard';
  else if (dd >= SOFT) tierKey = 'soft';

  const tierColor = tierKey === 'hard' ? 'var(--danger)' : tierKey === 'soft' ? 'var(--warn)' : 'var(--ok)';
  const tierLabel = tierKey === 'hard' ? tr('hard') : tierKey === 'soft' ? tr('soft') : tr('none');
  const effectText = tierKey === 'hard' ? tr('effHard') : tierKey === 'soft' ? tr('effSoft') : tr('effNone');

  return (
    <div style={wrap}>
      <div style={head}>{tr('title')}</div>
      <p style={{ fontSize: 14, color: 'var(--text-secondary)', lineHeight: 1.6, marginTop: 0 }}>{tr('intro')}</p>

      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, marginBottom: 6 }}>
        <span style={{ color: 'var(--text-secondary)' }}>{tr('drawdown')}</span>
        <span style={{ fontFamily: 'var(--font-mono)', color: tierColor, fontSize: 18, fontWeight: 700, transition: 'color 220ms var(--ease)' }}>−{dd.toFixed(1)}%</span>
      </div>
      <input type="range" min={0} max={15} step={0.1} value={dd}
        onChange={(e) => { recordPlaygroundTried('KillSwitchLadder'); setDd(parseFloat(e.target.value)); }}
        style={{ width: '100%', accentColor: tierColor }} />

      {/* ladder rungs */}
      <div style={{ display: 'flex', gap: 4, marginTop: 14 }}>
        {RUNGS.map((r) => {
          const active = tierKey === r.key;
          return (
            <div key={r.key} style={{
              flex: r.to - r.from,
              padding: '10px 8px', borderRadius: 'var(--r-sm)', textAlign: 'center',
              border: `1px solid ${active ? r.color : 'var(--border)'}`,
              background: active ? r.bg : 'var(--bg-surface-2)',
              opacity: active ? 1 : 0.5,
              transform: active ? 'translateY(-2px)' : 'none',
              boxShadow: active ? `0 0 0 1px ${r.color}, 0 4px 12px rgba(0,0,0,.35)` : 'none',
              transition: 'opacity 220ms var(--ease), border-color 220ms var(--ease), background 220ms var(--ease), transform 220ms var(--ease), box-shadow 220ms var(--ease)',
            }}>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: active ? r.color : 'var(--text-muted)', fontWeight: 700, transition: 'color 220ms var(--ease)' }}>{r.label}</div>
            </div>
          );
        })}
      </div>

      <div style={{ marginTop: 16, padding: '16px 18px', borderRadius: 'var(--r-md)', border: `1px solid ${tierColor}`, background: 'var(--bg-surface-2)', transition: 'border-color 220ms var(--ease)' }}>
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, letterSpacing: '0.10em', textTransform: 'uppercase', color: 'var(--text-faint)', marginBottom: 6 }}>{tr('tier')}</div>
        <div style={{ fontWeight: 700, color: tierColor, fontSize: 16, marginBottom: 10, transition: 'color 220ms var(--ease)' }}>{tierLabel}</div>
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, letterSpacing: '0.10em', textTransform: 'uppercase', color: 'var(--text-faint)', marginBottom: 6 }}>{tr('effect')}</div>
        <div style={{ fontSize: 14, color: 'var(--text-secondary)', lineHeight: 1.55 }}>{effectText}</div>
      </div>
    </div>
  );
}

const wrap = { background: 'var(--bg-surface)', border: '1px solid var(--border)', borderRadius: 'var(--r-lg)', padding: 24, margin: '28px 0' };
const head = { fontFamily: 'var(--font-mono)', fontSize: 12, letterSpacing: '0.12em', textTransform: 'uppercase', color: 'var(--accent)', marginBottom: 12 };
