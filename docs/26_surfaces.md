# 26 (surfaces) — Card / Evidence Surface Mockups (read-only, PLAN)

> DASH-002 — companion to the docs/26 dashboard-expansion PLAN. **Plan/mockup only; no code; the
> existing public dashboard/cockpit/board are NOT touched (STOP-and-ask before any `landing/` edit).**
> These are read-only internal surfaces for the research layer. Cross-refs: docs/26, docs/11–14,
> docs/37, docs/adr/ADR-YL-008.

## Principle
Every surface shows **evidence-level badges** and the **spread-over-floor** framing (ADR-YL-008), never
a bare APY. Refused candidates are first-class (the refusal log is a surface, not an error state).

## Surfaces (mockup sketches, ASCII)

### Strategy Card surface
```
[SC-RDFC-001] Rates Desk — Fixed Carry            status: paper_testing   line: Enhanced(target)
net APY  6.09% [L1 backtest]   live 0.01% [L3 thin]      floor 3.4% (live)
SPREAD over floor: backtest +269bps · realized 0bps [INSUFFICIENT_DATA]
spread_fully_explained: FALSE   ⚠ held — realized spread not yet risk-attributed
```

### Refusal-log surface (positive results)
```
REFUSED  leverage_loop   nominal +1160bps   realized -8.95%   reason: unexplained_spread (liq tail)
REFUSED  lrt_carry       nominal + …         realized -3.60%   reason: tail-comp
```

### Evidence-level legend
```
L0 idea · L1 hist · L2 source-verified · L3 paper · L4 small-cap · L5 live · L6 multi-cycle
```

### Portfolio / capital-tier surface
Per-tier caps (RiskPolicy > tier > model), deployed-vs-idle, spread-weighted allocation (advisory).

## Build note
Implementation is deferred; when built it must reuse the existing site design system and NOT alter the
live dashboard/cockpit/board without an owner decision. **TODO: expand at MVP 2-3 stage.**
