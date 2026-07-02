# Paper-Test Plan — <STRATEGY_ID>

> YL-002 template. A candidate enters `paper_testing` only with an approved plan (docs/07 lifecycle).
> Fill-in; no live capital moves. Cross-refs: docs/07, docs/11, docs/14, docs/37, docs/adr/ADR-YL-008.

## Subject
- **strategy_id / card:** `<SC-XXXX>` (link the Strategy Card)
- **sleeve / module:** `<spa_core/strategy_lab/... if it maps to code>`
- **product_line target:** `<Preserve|Core|Enhanced|MaxYield|Experimental>`
- **analyst sign-off to start:** `<name + date>`

## Hypothesis (what we are testing)
- **yield-source claim:** `<one line>`
- **spread claim (ADR-YL-008):** `expected spread over the live floor = <bps>; the risks that should explain it = <list>`
- **falsifiable prediction:** `<what result would DISPROVE the thesis>`

## Duration & cadence
- **min duration:** `≥ 30 evidenced days` (docs/07) — cycle-log-backed days only, backfill excluded
- **cadence:** `daily tick`
- **evidence level target on pass:** `L3 (paper-tracked)`

## Pass thresholds (all must hold)
- **realized spread over floor:** `> 0 AND fully risk-explained (spread_fully_explained=true)`
- **risk-adjusted:** `beats the RWA floor across the stress overlay (forward_analytics)`
- **max drawdown:** `≤ tier band (e.g. ≤ 15%)`
- **no kill in window; no falsified assumption**

## Auto-fail conditions (any → reject/frozen)
- `drawdown past tier limit` · `depeg / exploit / withdrawal-freeze event` · `yield-source assumption
  falsified` · `evidence gap` · `unexplained spread persists (ADR-YL-008)` · `realized spread ≤ 0`

## Monitoring
- **feeds/data:** `<real, cited feeds>`
- **alerts:** `<peg / funding / drawdown / gate-flip>`
- **artifacts written:** `<paper series + proof-chain path>`

## Reviews required before exit → paper_passed
- [ ] Red-Team review (mandatory for Enhanced/Max/…, incl. ADR-YL-008 spread-attribution Q19)
- [ ] Risk Scoring v2 (advisory) complete
- [ ] Protocol + Stablecoin cards reviewed (no UNVERIFIED security fields)
- [ ] Human reviewer sign-off

## Result (fill on completion)
- **outcome:** `<paper_passed | rejected | frozen>` · **evidenced days:** `<n>` · **realized spread bps:** `<>`
- **spread_fully_explained:** `<true|false>` · **notes / lessons:** `<>`
