# Small-Capital Test Report — <STRATEGY_ID>

> YL-003 template. Produced during `small_capital_testing` (docs/07) — the first REAL capital, a
> capped sleeve, owner/IC-approved. Fill-in. Cross-refs: docs/07, docs/11, docs/34, docs/adr/ADR-YL-008.

## Subject & authorization
- **strategy_id / card:** `<SC-XXXX>` · **product_line target:** `<>`
- **owner/IC approval to fund:** `<name + date>` (MANDATORY)
- **capital tier + cap:** `<tier, capped sleeve size per docs/34>`
- **min live duration:** `<tier-defined, e.g. ≥ 14 live days>`

## Realized vs modeled (the point of small-capital testing)
| Metric | Paper/backtest | Small-capital realized | Delta |
|---|---|---|---|
| net APY | | | |
| **spread over live floor (bps)** | | | |
| slippage (entry/exit) | | | |
| withdrawal/queue time at size | | | |
| max drawdown | | | |
| fee + gas drag | | | |

## ADR-YL-008 spread check at real size
- **realized spread over floor:** `<bps>` · **still fully risk-explained?** `<true|false>`
- **capacity reality:** `does the spread survive at the funded size, or compress? <notes>`
- **unexplained residual at size:** `<bps>` → if > tolerance, **de-risk / reject**.

## Pass thresholds
- realized spread > 0 AND fully explained at size · slippage/queue within model · drawdown ≤ band ·
  no counterparty/venue event · verdict stable across the funded band.

## Auto-fail / freeze
- execution slippage or withdrawal queue materially worse than modeled · drawdown breach ·
  counterparty event · spread collapses to unexplained/≤0 at size.

## Reviews
- [ ] Red-Team re-review AT SCALE (capacity, exit-at-size, counterparty)
- [ ] Risk Scoring v2 refreshed on realized data
- [ ] Owner/IC decision recorded

## Result
- **outcome:** `<small_capital_passed | frozen | rejected>` · **live days:** `<n>` ·
  **realized spread bps @ size:** `<>` · **recommend →:** `<approved_for_* | hold | retire>` · **notes:** `<>`
