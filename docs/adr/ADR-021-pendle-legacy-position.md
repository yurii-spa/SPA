# ADR-021 Legacy Exception: Pendle Position

**Date:** 2026-06-20  
**Status:** MONITORING  
**Amount:** $2,592.58  
**ADR ref:** ADR-021-pendle-yt-t3-classification (Pendle YT T3-SPEC — advisory only)

## Context

ADR-021 classifies Pendle YT as T3-SPEC: positions are advisory-only and must not be
opened automatically by the allocator. However, at the time ADR-021 was adopted, a
legacy `pendle` entry already existed in `data/current_positions.json` ($2,592.58)
carried over from earlier paper-trading cycles before the T3-SPEC classification.

## Decision

This legacy position is kept as-is for the following reasons:

1. **Paper-trading context** — no real capital at risk; closing the position in
   `current_positions.json` would create a synthetic loss event that distorts the
   equity-curve track record without providing any safety benefit.
2. **Slippage avoidance** — forcing a virtual zero-out mid-cycle can cascade into
   RiskPolicy re-triggers and misleading drawdown signals.
3. **Small size** — $2,592.58 represents ~2.6% of the portfolio, within T2 per-protocol
   cap (20%), and no new allocation will be added.

## Action

- The allocator will **not** increase this position.
- Monitoring: reviewed on each cycle run via `tournament_results.json` (S10 signals).
- Closure: position will be zeroed to cash at the **next rebalancing window** where
  Pendle APY falls below the RiskPolicy floor (1%) or at go-live preparation
  (whichever comes first).
- This document supersedes no other ADR; ADR-021 T3-SPEC classification remains
  fully in effect for all future position decisions.

## Owner

Paper-trading Owner / GoLive reviewer.
