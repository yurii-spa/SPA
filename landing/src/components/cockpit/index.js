/*
 * cockpit/index.js — barrel for the Desk Cockpit primitives library (SPA-004/005, Lane B).
 *
 * The compilable vocabulary every Cockpit screen (S1–S7) is assembled from. All primitives
 * extend the canonical design system (ui/tokens.js, ui/kit.jsx) — they NEVER fork the palette.
 * Doctrine baked in: «history, not a number» · fail-closed (stale/missing shown EXPLICITLY) ·
 * idle = «capital parked» is POSITIVE · tabular figures · no gamification.
 *
 * ⭐ SIGNATURE elements: KillGauge, RefusalFeed, AttributionWaterfall.
 */
export { default as StaleGuard, FreshnessStamp } from './StaleGuard.jsx';
export { default as MetricStat } from './MetricStat.jsx';
export { default as TimeToggle } from './TimeToggle.jsx';
export { default as KillGauge, KillPanel } from './KillGauge.jsx';
export { default as AttributionWaterfall, AttributionBar } from './AttributionWaterfall.jsx';
export { default as RefusalFeed, DecisionFeed, DecisionRow, ChainBadge } from './RefusalFeed.jsx';
export { default as RiskStrip } from './RiskStrip.jsx';
export { default as EquityChart } from './EquityChart.jsx';
export { default as RegimeBadge } from './RegimeBadge.jsx';
export { default as PositionTable } from './PositionTable.jsx';
export { default as LiqNavTierChart } from './LiqNavTierChart.jsx';
export { default as TournamentLeaderboard } from './TournamentLeaderboard.jsx';

export * from './lib.js';
export { useLang, usePrefersReducedMotion } from './hooks.js';
