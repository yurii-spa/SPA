/*
 * CockpitKit — the Storybook-lite showcase island. Renders EVERY Cockpit primitive in
 * EVERY state (healthy / degraded / killed / idle-positive / loading / error-stale) so the
 * hard-gate can be eyeballed: signature elements distinctive, evidenced≠backfill, idle
 * positive, stale explicit, tabular figures, fail-closed to UNKNOWN — never fabricated.
 *
 * Data below is SYNTHETIC fixture data (clearly a showcase, no live API) — it exists only
 * to drive the states. Bilingual + reduced-motion aware via the shared hooks.
 */
import {
  StaleGuard, MetricStat, TimeToggle, KillGauge, KillPanel,
  AttributionWaterfall, AttributionBar, RefusalFeed, DecisionFeed,
  RiskStrip, EquityChart, RegimeBadge, PositionTable, LiqNavTierChart, TournamentLeaderboard,
} from './index.js';
import { useLang, usePrefersReducedMotion } from './hooks.js';
import { useState } from 'react';
import { fmtUsd0, fmtPct, fmtSigned, usdCompact } from './lib.js';
import { MONO } from '../ui/tokens.js';

const now = Date.now();

/* ── fixtures ─────────────────────────────────────────────────────────────────────── */
const FRESH = { _fetched_at: Math.floor(now / 1000), stale: false };
const STALE = { _fetched_at: Math.floor((now - 6 * 60_000) / 1000), stale: false }; // 6m old → stale
const NOTS = { some: 'payload' }; // no timestamp → fail-closed stale

const KILL_HEALTHY = [
  { key: 'dd', label: { en: 'Drawdown', ru: 'Просадка' }, value: 1.2, threshold: 5, unit: '%', tier: 'SAFE', lastTriggered: 'never' },
  { key: 'sharpe', label: 'Sharpe floor', value: null, threshold: null, unit: '', tier: 'UNKNOWN' },
  { key: 'flags', label: { en: 'Red flags (held)', ru: 'Красные флаги' }, value: 0, threshold: 5, unit: '', tier: 'SAFE' },
];
const KILL_DEGRADED = [
  { key: 'dd', label: { en: 'Drawdown', ru: 'Просадка' }, value: 4.3, threshold: 5, unit: '%', tier: 'SOFT' },
  { key: 'flags', label: 'Red flags (held)', value: 3, threshold: 5, unit: '', tier: 'WATCH' },
];
const KILL_BREACHED = [
  { key: 'dd', label: { en: 'Drawdown', ru: 'Просадка' }, value: 10.4, threshold: 10, unit: '%', tier: 'HARD', lastTriggered: '2026-06-30' },
];

const ATTR = [
  { key: 'funding', label: { en: 'Funding', ru: 'Funding' }, value: 4200 },
  { key: 'basis', label: 'Basis', value: 1850 },
  { key: 'staking', label: { en: 'Staking', ru: 'Стейкинг' }, value: 2600 },
  { key: 'rwa', label: 'RWA floor', value: 3100 },
  { key: 'price', label: { en: 'Price', ru: 'Цена' }, value: 40 }, // ≈0 → market-neutral by eye
  { key: 'fees', label: { en: 'Fees', ru: 'Комиссии' }, value: -520 },
];
const ATTR_TOTAL = ATTR.reduce((a, s) => a + s.value, 0);
const ATTR_BROKEN = [{ key: 'funding', label: 'Funding', value: 4200 }, { key: 'basis', label: 'Basis', value: 1850 }];

const REFUSALS = [
  { seq: 812, as_of: '2026-06-30', desk: 'rates', kind: 'REFUSAL', underlying: 'rsETH-PT', verdict: 'REFUSE',
    plain_en: 'Implied yield is tail-risk compensation, not mispriced carry — structural haircut vetoes entry.',
    plain_ru: 'Implied yield — компенсация хвостового риска, а не mispriced carry — структурный хейркат вето.',
    net_edge: 0.021, fee_drag: 0.004, advisory_size_usd: 250000, entry_hash: '9f3a…c21', prev_hash: '77b1…4de', proof_hash: 'aa02…9f1', verified: true },
  { seq: 811, as_of: '2026-06-30', desk: 'rates', kind: 'ENTRY', underlying: 'sUSDe-PT', verdict: 'ENTRY',
    plain_en: 'Fixed carry to maturity clears the RWA floor risk-adjusted after fees.',
    plain_ru: 'Fixed carry до погашения проходит RWA-пол после комиссий.',
    net_edge: 0.038, fee_drag: 0.003, advisory_size_usd: 500000, entry_hash: '77b1…4de', prev_hash: '55c0…9ab', proof_hash: 'bb13…7c2', verified: true },
  { seq: 810, as_of: '2026-06-29', desk: 'dfb', kind: 'ALERT', underlying: 'USDC/Aave', verdict: 'WATCH',
    plain_en: 'Utilization spiked above 92% — monitoring exit liquidity.',
    plain_ru: 'Utilization выше 92% — мониторим ликвидность на выход.',
    net_edge: null, advisory_size_usd: 0 },
];
const CHAIN_OK = { verified: true, head_hash: 'aa02f…9f1', chain_length: 812 };
const CHAIN_BROKEN = { verified: false, head_hash: 'deadb…eef', chain_length: 812 };

const EQUITY = (() => {
  const out = [];
  let v = 100000;
  for (let i = 0; i < 24; i++) {
    v += (Math.sin(i / 3) * 120) + (i < 8 ? 30 : 55) - (i === 14 ? 800 : 0);
    out.push({ date: `2026-06-${String(i + 1).padStart(2, '0')}`, value: Math.round(v), evidenced: i >= 8 });
  }
  return out;
})();
const EQ_MARKERS = [{ date: '2026-06-15', kind: 'refusal' }, { date: '2026-06-20', kind: 'gate' }];

const POSITIONS = [
  { id: 1, leg: 'SPOT_LONG', asset: 'eETH', venue: 'Aave', notional_usd: 320000, funding_accrued_usd: 1240, net_carry_apy_pct: 6.8 },
  { id: 2, leg: 'PERP_SHORT', asset: 'ETH', venue: 'Hyperliquid', notional_usd: 318000, funding_accrued_usd: 2110, net_carry_apy_pct: 4.2 },
  { id: 3, leg: 'LEND', asset: 'USDC', venue: 'Morpho', notional_usd: 150000, funding_accrued_usd: 640, net_carry_apy_pct: null },
];

const EXIT_NAV = [
  { size_usd: 100000, net_proceeds_usd: 99400, haircut_pct: 0.6, time_to_exit_days: 1 },
  { size_usd: 500000, net_proceeds_usd: 489000, haircut_pct: 2.2, time_to_exit_days: 2 },
  { size_usd: 1000000, net_proceeds_usd: 948000, haircut_pct: 5.2, time_to_exit_days: 4, flagged: true },
  { size_usd: 5000000, net_proceeds_usd: null, haircut_pct: null }, // hole — depth doesn't cover
];

const TOURNEY = [
  { rank: 1, name: 'FixedCarry-sUSDe', metric: 5.8, capital_usd: 500000, trend: [1, 1.2, 1.15, 1.4, 1.6], status: 'CHAMPION' },
  { rank: 2, name: 'eth_lst_neutral', metric: 4.1, capital_usd: 250000, trend: [1, 0.9, 1.1, 1.2], status: 'CHALLENGER' },
  { rank: 3, name: 'RWA-floor', metric: 3.4, capital_usd: 0, trend: 0.1, status: 'PAPER' },
  { rank: 4, name: 'LRT-carry-degen', metric: null, capital_usd: 0, trend: [1, 0.8, 0.5], status: 'KILLED', kill_reason: 'depeg tail exceeded −15% in stress replay' },
];

/* ── layout helpers ───────────────────────────────────────────────────────────────── */
function Section({ title, sig, children, note }) {
  return (
    <section style={{ display: 'grid', gap: 14, paddingTop: 28, borderTop: '1px solid var(--border)' }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, flexWrap: 'wrap' }}>
        <h2 style={{ fontFamily: MONO, fontSize: '.95rem', fontWeight: 700, color: 'var(--text-primary)', margin: 0 }}>{title}</h2>
        {sig && <span style={{ fontFamily: MONO, fontSize: '.6rem', fontWeight: 700, letterSpacing: '.08em', padding: '2px 8px', borderRadius: 'var(--r-full)', background: 'var(--accent-bg)', border: '1px solid var(--accent-border)', color: 'var(--accent-hover)' }}>★ SIGNATURE</span>}
      </div>
      {note && <p style={{ fontSize: '.75rem', color: 'var(--text-muted)', margin: 0, lineHeight: 1.5 }}>{note}</p>}
      {children}
    </section>
  );
}
function StateLabel({ children }) {
  return <p style={{ fontFamily: MONO, fontSize: '.625rem', textTransform: 'uppercase', letterSpacing: '.08em', color: 'var(--text-faint)', margin: '4px 0 0' }}>{children}</p>;
}
const grid = (min = 240) => ({ display: 'grid', gap: 12, gridTemplateColumns: `repeat(auto-fit, minmax(${min}px, 1fr))` });

export default function CockpitKit() {
  const lang = useLang();
  const reduced = usePrefersReducedMotion();
  const [win, setWin] = useState('7D');
  const [filter, setFilter] = useState('ALL');
  const rm = reduced;

  return (
    <div style={{ display: 'grid', gap: 8 }}>
      <p style={{ fontFamily: MONO, fontSize: '.6875rem', color: 'var(--text-muted)', margin: 0 }}>
        {reduced ? '● prefers-reduced-motion: ON (transitions disabled)' : '○ prefers-reduced-motion: off'} · synthetic fixture data · toggle EN|RU in the header
      </p>

      {/* 1. StaleGuard */}
      <Section title="1 · StaleGuard" note="The fail-closed freshness substrate. Fresh → green live stamp; 6-min-old → grey + 'stale' + explicit 'not refreshing'; no-timestamp → fail-closed stale; loading → skeleton; error → explicit offline.">
        <div style={grid(260)}>
          <div><StateLabel>healthy (fresh)</StateLabel><StaleGuard payload={FRESH} lang={lang} label="portfolio"><MetricStat label="Equity" value={fmtUsd0(100180)} lang={lang} /></StaleGuard></div>
          <div><StateLabel>degraded (stale 6m)</StateLabel><StaleGuard payload={STALE} lang={lang} label="portfolio"><MetricStat label="Equity" value={fmtUsd0(100180)} lang={lang} /></StaleGuard></div>
          <div><StateLabel>fail-closed (no ts)</StateLabel><StaleGuard payload={NOTS} lang={lang}><MetricStat label="Equity" value={fmtUsd0(100180)} lang={lang} /></StaleGuard></div>
          <div><StateLabel>loading</StateLabel><StaleGuard loading lang={lang} /></div>
          <div><StateLabel>error / offline</StateLabel><StaleGuard error lang={lang} /></div>
        </div>
      </Section>

      {/* 2. MetricStat */}
      <Section title="2 · MetricStat" note="Number + label + Δ + trend, tabular figures. Null → '—' (never 0). idle → POSITIVE teal.">
        <div style={grid(200)}>
          <div><StateLabel>healthy + Δ + trend</StateLabel><MetricStat label={{ en: 'Total return', ru: 'Доходность' }} value={fmtSigned(2.14)} delta={{ value: '+0.18%' }} trend={[1, 1.1, 1.05, 1.2, 1.3, 1.28]} tone="ok" lang={lang} /></div>
          <div><StateLabel>degraded (down)</StateLabel><MetricStat label="APY today" value={fmtPct(3.1)} delta="-0.4%" tone="warn" lang={lang} /></div>
          <div><StateLabel>killed / breach</StateLabel><MetricStat label={{ en: 'Drawdown', ru: 'Просадка' }} value={fmtPct(-10.4)} delta="-2.1%" tone="danger" lang={lang} /></div>
          <div><StateLabel>idle-POSITIVE</StateLabel><MetricStat label={{ en: 'Cash buffer', ru: 'Кэш' }} value={fmtPct(38)} idle lang={lang} /></div>
          <div><StateLabel>fail-closed (null)</StateLabel><MetricStat label="Sharpe" value={null} sub={{ en: 'THIN — n/a', ru: 'THIN — н/д' }} lang={lang} /></div>
          <div><StateLabel>stale</StateLabel><MetricStat label="Equity" value={fmtUsd0(100180)} stale lang={lang} /></div>
        </div>
      </Section>

      {/* 3. TimeToggle */}
      <Section title="3 · TimeToggle" note="One shared window selector. Controlled.">
        <TimeToggle value={win} onChange={setWin} lang={lang} />
        <StateLabel>active: {win}</StateLabel>
      </Section>

      {/* 4. KillGauge — SIGNATURE */}
      <Section title="4 · KillGauge / KillPanel" sig note="One kill-condition as a manometer. Needle at live value, arc fills toward threshold, tone escalates green→amber→kill-red. UNKNOWN condition = explicit grey, NO fabricated headroom.">
        <div style={grid(240)}>
          <div><StateLabel>healthy (safe headroom)</StateLabel><KillGauge label={{ en: 'Drawdown', ru: 'Просадка' }} value={1.2} threshold={5} unit="%" tier="SAFE" lastTriggered="never" reducedMotion={rm} lang={lang} /></div>
          <div><StateLabel>degraded (nearing)</StateLabel><KillGauge label={{ en: 'Drawdown', ru: 'Просадка' }} value={4.3} threshold={5} unit="%" tier="SOFT" reducedMotion={rm} lang={lang} /></div>
          <div><StateLabel>killed (breached)</StateLabel><KillGauge label={{ en: 'Drawdown', ru: 'Просадка' }} value={10.4} threshold={10} unit="%" tier="HARD" lastTriggered="2026-06-30" reducedMotion={rm} lang={lang} /></div>
          <div><StateLabel>fail-closed UNKNOWN</StateLabel><KillGauge label="Sharpe floor" value={null} threshold={null} tier="UNKNOWN" reducedMotion={rm} lang={lang} /></div>
        </div>
        <StateLabel>KillPanel (healthy grid) — idle-positive book</StateLabel>
        <KillPanel conditions={KILL_HEALTHY} reducedMotion={rm} lang={lang} />
        <StateLabel>KillPanel (breached)</StateLabel>
        <KillPanel conditions={KILL_BREACHED} reducedMotion={rm} lang={lang} />
        <StateLabel>KillPanel (empty → fail-closed)</StateLabel>
        <KillPanel conditions={[]} lang={lang} />
      </Section>

      {/* 5. AttributionWaterfall — SIGNATURE */}
      <Section title="5 · AttributionWaterfall / AttributionBar" sig note="P&L by source; the waterfall SUMS to total. price≈0 renders as a faint sliver → proves market-neutrality by eye. Non-reconciling → red badge, NOT rescaled.">
        <StateLabel>healthy (reconciles)</StateLabel>
        <AttributionWaterfall segments={ATTR} total={ATTR_TOTAL} reducedMotion={rm} lang={lang} fmt={usdCompact} />
        <StateLabel>degraded (does NOT reconcile — no rescale)</StateLabel>
        <AttributionWaterfall segments={ATTR_BROKEN} total={ATTR_TOTAL} reducedMotion={rm} lang={lang} />
        <StateLabel>fail-closed (empty)</StateLabel>
        <AttributionWaterfall segments={[]} lang={lang} />
        <StateLabel>AttributionBar (compact, same data)</StateLabel>
        <AttributionBar segments={ATTR} lang={lang} />
      </Section>

      {/* 6. RefusalFeed — SIGNATURE */}
      <Section title="6 · RefusalFeed" sig note="The public refusal ledger — the moat. ts · opportunity · reason · exp-edge · fee-drag · verdict + verified proof badge. Chain badge 3-state (verified/broken/absent-neutral).">
        <StateLabel>healthy (verified chain)</StateLabel>
        <RefusalFeed rows={REFUSALS} chain={CHAIN_OK} verifyCmd="python3 verify_spa.py decision_log.jsonl" lang={lang} />
        <StateLabel>degraded (BROKEN chain — never green)</StateLabel>
        <RefusalFeed rows={REFUSALS} chain={CHAIN_BROKEN} lang={lang} />
        <StateLabel>fail-closed (absent chain → neutral, empty rows)</StateLabel>
        <RefusalFeed rows={[]} chain={{}} lang={lang} />
      </Section>

      {/* 7. DecisionFeed */}
      <Section title="7 · DecisionFeed" note="The full decisions ledger (ENTRY ∥ REFUSAL ∥ ALERT). Filter tabs. Shares the row renderer with RefusalFeed.">
        <DecisionFeed rows={REFUSALS} chain={CHAIN_OK} filter={filter} onFilter={setFilter} lang={lang} />
      </Section>

      {/* 8. RiskStrip */}
      <Section title="8 · RiskStrip" note="delta-band (±0.5%) · drawdown vs ladder · deployed vs idle (idle POSITIVE) · margin health.">
        <StateLabel>healthy</StateLabel>
        <RiskStrip delta={{ value: 0.12, band: 0.5 }} drawdown={{ value: 1.2 }} deployment={{ deployed_pct: 62 }} margin={{ health: 1.9 }} lang={lang} />
        <StateLabel>degraded</StateLabel>
        <RiskStrip delta={{ value: 0.9 }} drawdown={{ value: 6.1 }} deployment={{ deployed_pct: 95 }} margin={{ health: 1.3 }} lang={lang} />
        <StateLabel>killed</StateLabel>
        <RiskStrip delta={{ value: 1.8 }} drawdown={{ value: 10.5 }} deployment={{ deployed_pct: 100 }} margin={{ health: 1.1 }} lang={lang} />
        <StateLabel>fail-closed (nulls → '—', margin n/a paper)</StateLabel>
        <RiskStrip delta={{}} drawdown={{}} deployment={{}} margin={null} lang={lang} />
      </Section>

      {/* 9. EquityChart */}
      <Section title="9 · EquityChart" note="Net-of-fees curve + drawdown shading + gate/refusal markers. CRITICAL: evidenced bars SOLID teal, backfill/warmup bars DASHED grey — a backfill peak never looks like real track.">
        <StateLabel>healthy (evidenced + backfill split, markers)</StateLabel>
        <EquityChart series={EQUITY} markers={EQ_MARKERS} reducedMotion={rm} lang={lang} />
        <StateLabel>fail-closed (insufficient history)</StateLabel>
        <EquityChart series={[{ date: '2026-06-01', value: 100000, evidenced: true }]} lang={lang} />
      </Section>

      {/* 10. RegimeBadge */}
      <Section title="10 · RegimeBadge" note="Funding regime + streak + vol + cycle. Unknown → muted, never fabricated STABLE.">
        <div style={grid(300)}>
          <div><StateLabel>stable</StateLabel><RegimeBadge regime="STABLE" streak={12} vol="8.2%" note={{ en: 'carry favorable', ru: 'carry благоприятен' }} lang={lang} /></div>
          <div><StateLabel>high yield</StateLabel><RegimeBadge regime="HIGH_YIELD" streak={3} vol="14%" lang={lang} /></div>
          <div><StateLabel>volatile</StateLabel><RegimeBadge regime="VOLATILE" streak={1} vol="31%" lang={lang} /></div>
          <div><StateLabel>fail-closed unknown</StateLabel><RegimeBadge regime={null} lang={lang} /></div>
        </div>
      </Section>

      {/* 11. PositionTable */}
      <Section title="11 · PositionTable" note="Paper book legs (spot long / perp short / lend), venue, notional, funding, net carry APY. Honestly labeled PAPER (no on-chain fills). Empty = idle-POSITIVE.">
        <StateLabel>healthy</StateLabel>
        <PositionTable rows={POSITIONS} lang={lang} />
        <StateLabel>idle-POSITIVE (flat book)</StateLabel>
        <PositionTable rows={[]} lang={lang} />
        <StateLabel>fail-closed (offline)</StateLabel>
        <PositionTable rows={null} lang={lang} />
      </Section>

      {/* 12. LiqNavTierChart */}
      <Section title="12 · LiqNavTierChart" note="Exit-NAV by ticket size — the liquidation-NAV ladder. Haircut climbs with size; flagged/depth-limited tiers amber; uncovered size = a HOLE, not a fabricated fill.">
        <StateLabel>healthy (with a depth hole)</StateLabel>
        <LiqNavTierChart schedule={EXIT_NAV} reducedMotion={rm} lang={lang} />
        <StateLabel>fail-closed (empty)</StateLabel>
        <LiqNavTierChart schedule={[]} lang={lang} />
      </Section>

      {/* 13. TournamentLeaderboard */}
      <Section title="13 · TournamentLeaderboard" note="rank · strategy · risk-adj metric · capital · trend · status (champion/challenger/killed). Null metric → n/a (never a fabricated Sharpe); killed row unmistakably kill-toned.">
        <StateLabel>healthy (incl. a killed row)</StateLabel>
        <TournamentLeaderboard rows={TOURNEY} metricLabel={{ en: 'Net return', ru: 'Net доходность' }} lang={lang} />
        <StateLabel>fail-closed (empty)</StateLabel>
        <TournamentLeaderboard rows={[]} lang={lang} />
      </Section>
    </div>
  );
}
