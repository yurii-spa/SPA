# Performance / Attribution Report — <PERIOD>

> REPORT-001 template (companion to docs/41). **Every number carries an evidence level (docs/37);
> paper is never presented as live; backtest is never presented as realized.** Fill-in. Cross-refs:
> docs/41, docs/37, docs/adr/ADR-YL-008.

## Scope
- **subject:** `<sleeve / portfolio / strategy_id>` · **period:** `<from–to>` · **basis:** `<paper | small-capital | live>`
- **as_of:** `<ISO-8601 UTC>` · **prepared by:** `<name>`

## Returns (each cell needs an evidence level L0–L6)
| Metric | Value | Evidence level | Source | Notes |
|---|---|---|---|---|
| Gross APY | | | | |
| Net APY (after fees/slippage/gas) | | | | |
| **Spread over live RWA floor (bps)** | | | | ADR-YL-008 — the headline metric |
| Risk-adjusted (vs floor, stress) | | | | forward_analytics |
| Max drawdown | | | | |
| Realized vs paper/backtest delta | | | | if applicable |

## Attribution (where the return came from)
- funding/carry: `<>` · basis: `<>` · staking: `<>` · RWA/floor: `<>` · price (≈0 if neutral): `<>` · fees/gas drag: `<>`
- **sum reconciles to net return?** `<yes/no>`

## Spread attribution (ADR-YL-008)
- **spread over floor:** `<bps>` · **explained by:** `<itemized risk → bps>` · **unexplained residual:** `<bps>`
- **spread_fully_explained:** `<true|false>` — if false, this is flagged, not smoothed over.

## Honesty statement (mandatory)
- Basis stated (paper/backtest/live); no paper shown as live; every number evidence-levelled;
  unverified = `requires verification`; refusals in the period counted as positive results.

## Provenance
- **created_at:** `<ISO-8601 UTC>` · **reviewer:** `<name>`
