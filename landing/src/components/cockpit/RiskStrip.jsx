/*
 * RiskStrip ⚙ — a compact horizontal strip of the live risk posture:
 *   delta-band (target ±0.5%) · drawdown · deployed vs idle · margin health.
 * (From /api/risk + /api/live/safety + /api/portfolio.)
 *
 * 5-question map: "how much RISK" — the at-a-glance risk vitals. idle (deployed<100%) is
 * rendered as a POSITIVE "capital parked" reading (teal), NOT a warning.
 *
 * FAIL-CLOSED: any null cell → "—" (never 0). A breach (dd past a rung, delta out of band,
 * margin critical) is tone-escalated so it is unmistakable.
 *
 * Props:
 *   delta      — { value:number(%), band?:number(±%) }  net portfolio delta vs target 0
 *   drawdown   — { value:number(%), soft?:5, hard?:10 } live drawdown vs the ladder rungs
 *   deployment — { deployed_pct:number, idle_pct?:number }  deployed vs idle capital
 *   margin     — { health:number, unit?:'x'|'%', tone? } | null  margin health (paper: often n/a)
 *   lang
 */
import { TABULAR, MONO, toneColor } from '../ui/tokens.js';
import { pick, fmtPct, fmtSigned, NA } from './lib.js';

const isNum = (v) => v != null && isFinite(Number(v));

function Cell({ label, value, tone = 'muted', sub, lang }) {
  return (
    <div style={{ display: 'grid', gap: 3, minWidth: 96, flex: '1 1 96px' }}>
      <span style={{ fontFamily: MONO, fontSize: '.6rem', textTransform: 'uppercase', letterSpacing: '.06em', color: 'var(--text-faint)' }}>{pick(label, lang)}</span>
      <span style={{ ...TABULAR, fontFamily: MONO, fontSize: '1rem', fontWeight: 700, color: toneColor(tone), lineHeight: 1 }}>{value}</span>
      {sub && <span style={{ fontFamily: MONO, fontSize: '.6rem', color: 'var(--text-faint)' }}>{pick(sub, lang)}</span>}
    </div>
  );
}

export default function RiskStrip({ delta, drawdown, deployment, margin, lang = 'en' }) {
  const ru = lang === 'ru';

  // delta band
  let dTone = 'muted', dVal = NA, dSub = null;
  if (delta && isNum(delta.value)) {
    const band = isNum(delta.band) ? Number(delta.band) : 0.5;
    const out = Math.abs(Number(delta.value)) > band;
    dTone = out ? 'warn' : 'ok';
    dVal = fmtSigned(delta.value, 2);
    dSub = { en: `target ±${band}%`, ru: `цель ±${band}%` };
  }

  // drawdown
  let ddTone = 'muted', ddVal = NA, ddSub = null;
  if (drawdown && isNum(drawdown.value)) {
    const soft = isNum(drawdown.soft) ? drawdown.soft : 5;
    const hard = isNum(drawdown.hard) ? drawdown.hard : 10;
    const v = Math.abs(Number(drawdown.value));
    ddTone = v >= hard ? 'danger' : v >= soft ? 'warn' : 'ok';
    ddVal = fmtPct(-v, 2);
    ddSub = { en: `soft ${soft}% · hard ${hard}%`, ru: `soft ${soft}% · hard ${hard}%` };
  }

  // deployment / idle — idle is POSITIVE
  let depTone = 'teal', depVal = NA, depSub = null;
  if (deployment && isNum(deployment.deployed_pct)) {
    const dep = Number(deployment.deployed_pct);
    const idle = isNum(deployment.idle_pct) ? Number(deployment.idle_pct) : Math.max(0, 100 - dep);
    depVal = fmtPct(dep, 1);
    depTone = 'teal';
    depSub = idle > 0
      ? { en: `${idle.toFixed(1)}% parked ✓`, ru: `${idle.toFixed(1)}% припарк. ✓` }
      : { en: 'fully deployed', ru: 'полностью размещён' };
  }

  // margin
  let mTone = 'muted', mVal = NA, mSub = null;
  if (margin && isNum(margin.health)) {
    const u = margin.unit || 'x';
    mVal = Number(margin.health).toFixed(2) + (u === 'x' ? '×' : u);
    mTone = margin.tone || (Number(margin.health) < 1.2 ? 'danger' : Number(margin.health) < 1.5 ? 'warn' : 'ok');
  } else {
    mSub = { en: 'n/a (paper)', ru: 'н/д (paper)' };
  }

  return (
    <div style={{
      display: 'flex', gap: 20, flexWrap: 'wrap', padding: '14px 18px',
      borderRadius: 'var(--r-lg)', background: 'var(--bg-surface)', border: '1px solid var(--border)',
    }}>
      <Cell label={{ en: 'Net delta', ru: 'Чистая дельта' }} value={dVal} tone={dTone} sub={dSub} lang={lang} />
      <Cell label={{ en: 'Drawdown', ru: 'Просадка' }} value={ddVal} tone={ddTone} sub={ddSub} lang={lang} />
      <Cell label={{ en: 'Deployed', ru: 'Размещено' }} value={depVal} tone={depTone} sub={depSub} lang={lang} />
      <Cell label={{ en: 'Margin health', ru: 'Здоровье маржи' }} value={mVal} tone={mTone} sub={mSub} lang={lang} />
    </div>
  );
}
