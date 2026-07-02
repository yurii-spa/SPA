# Strategy Card — sUSDe Delta-Neutral (funding carry, RISK-COMP)

> Real card mapped from `susde_dn` in `spa_core/strategy_lab/aggressive_lab/`
> (`data/aggressive_lab/scorecard.json`: risk_class **C = risk-compensation (yield paid for a tail)**,
> risk_shape `funding_flip`, headline **11.0%**, backtest realized **4.2175%**). Long sUSDe + short
> ETH perp — the yield is funding carry, paid for bearing the funding-flip / Ethena-unwind tail.
> This card is an ADR-YL-008 **risk-compensation demonstration**: the realized return is positive and
> beats the floor, but as a class-C sleeve the spread must be **fully attributed to accepted measurable
> risk or refused** — and the residual funding/counterparty/peg tail is NOT fully explained → held
> advisory / risk-comp-flagged, not promoted. Numbers from the aggressive-lab scorecard (advisory,
> OUTSIDE RiskPolicy, separate from the go-live track); anything else `requires verification`.
> Cross-refs: docs/11, docs/07, docs/adr/ADR-YL-008, docs/14, docs/34, docs/37. **Cross-ref the USDe
> stablecoin card (`susde_yield.strategy.md`, SC-EX-003) — same Ethena/USDe substrate and funding
> mechanism.**

## Identity
- **strategy_id:** `SC-SUSDEDN-001`  <!-- maps to aggressive_lab strategy `susde_dn` -->
- **name:** `sUSDe Delta-Neutral (long sUSDe + short ETH perp)`
- **version:** `1.0`
- **category:** `basis`
- **product_line:** `MaxYield` (TARGET, as a nominal ~11% funding-carry sleeve) — **risk-comp flagged, not approved**
- **asset_type:** `stablecoin`

## What it touches
- **assets_used:** `["USDe", "sUSDe (staked)", "short ETH perp (delta hedge)"]`
- **protocols_used:** `["Ethena (sUSDe)", "perp venue (ETH perpetual)"]`  <!-- Protocol/Stablecoin Cards (docs/12, docs/13) required before any advance -->
- **chains_used:** `["Ethereum (sUSDe)", "perp venue (CEX or on-chain — requires verification)"]`

## Yield source (the honesty core)
- **yield_source:** `Funding carry — hold sUSDe (Ethena's own delta-neutral basis + staking) with an additional short ETH perp for delta-neutrality; income is funding/basis carry.`
- **yield_mechanism:** `Positive perp funding paid by leveraged longs, harvested by the short leg (plus sUSDe's underlying basis/staking). Delta-neutral to ETH; the return is the carry, not price.`
- **who_pays_the_yield:** `Perp longs paying funding to shorts in leveraged/bullish regimes (via sUSDe's hedge and the added short leg).`
- **why_yield_exists:** `Persistent positive perp funding in leveraged regimes — a real cash flow, but one paid precisely BECAUSE someone bears the funding-flip / unwind tail.`
- **why_yield_can_disappear:** `Funding flips negative (short PAYS → the carry inverts); USDe/sUSDe peg stress; Ethena / CEX-custody counterparty event; hedge slippage. The 2025-10 USDe leverage unwind is the named stress window.`

## APY (never presented without an evidence level)
- **expected_apy_range:** `headline ~11.0% (the LURE — scorecard headline_apy_pct)`
- **observed_apy_range:** `realized **4.2175%** (aggressive-lab backtest 2024-07-01→2026-05-31, 700 pts, class C); forward LOCKED_VOL 11.6257% (thin, vol 0.0001 → INSUFFICIENT_DATA, not trustworthy)`  <!-- source: scorecard.json susde_dn.backtest.realized_apy_pct 4.2175; forward.realized_apy_pct 11.6257 status LOCKED_VOL -->
- **base_apy:** `funding carry (regime-dependent) — requires verification`
- **incentive_apy:** `variable (Ethena incentives, if any) — requires verification`
- **sustainable_apy_estimate:** `<< headline: realized backtest 4.22% (not 11%); regime-dependent, can invert in a funding-flip`
- **apy_evidence_level:** `L3` (aggressive-lab backtest, trustworthy) for the 4.22% realized; the 11% headline and 11.63% forward are NOT verified (forward is LOCKED_VOL / INSUFFICIENT_DATA) <!-- docs/37 -->

## Spread over the floor (the mandate — ADR-YL-008: judged as spread over the live floor, not absolute APY)
- **floor_baseline_pct:** `{ value: ~3.4, source: rwa_feed (live via data/rwa_feed.py; NEVER hardcoded; fail-closed committed-literal fallback), as_of: 2026-07-02, fallback_used: requires verification }`  <!-- rwa_sleeve realized ~3.4328% confirms the baseline -->
- **spread_over_floor_bps:** `NOMINAL (headline) ~760 bps (11.0% − 3.4%). REALIZED (backtest) ~82 bps (4.2175% − 3.4%) — positive but far below the headline. Realized spread is small AND the tail is real (worst stress drawdown ~10.55% in the 2025-10 USDe-unwind shape-shock; max_dd 8.4785%).`
- **spread_risk_explanation:** the accepted, measurable risks the ~82 bps realized spread pays for. **Per-risk bps split is NOT computed** (scorecard yields one realized number + a tail, not a per-risk decomposition) → each `bps` below is `requires attribution`:
  - `{ risk: "Funding-flip risk (short PAYS when funding goes negative → the carry inverts)", bps: "requires attribution", evidence: "scorecard risk_shape funding_flip; 2025-10 USDe-unwind window worst_dd 4.1962% in-sample, recovered:false" }`
  - `{ risk: "CEX / custody counterparty risk (hedge-collateral custody + perp-venue solvency)", bps: "requires attribution", evidence: "Ethena delta-neutral relies on CEX custody; Protocol Card TBD" }`
  - `{ risk: "sUSDe / USDe peg risk (synthetic dollar, not fiat-reserve backed)", bps: "requires attribution", evidence: "USDe depeg surface — cross-ref SC-EX-003 susde_yield card; Stablecoin Card TBD" }`
  - `{ risk: "Hedge-execution / basis risk (slippage, sUSDe-vs-perp basis)", bps: "requires attribution", evidence: "delta-neutral rebalance under stress" }`
- **unexplained_spread_bps:** `requires attribution — the realized ~82 bps is NOT yet decomposed point-by-point into the named risks above; and the tail it pays for (~10.55% stress drawdown, NOT_RECOVERED in the 2025-10 window) is severe relative to the thin realized spread. The residual funding/counterparty/peg tail is treated as UNPRICED tail risk, not alpha.`
- **spread_fully_explained:** `false`  <!-- realized return is positive and beats the floor by ~82 bps, BUT (1) the spread is not decomposed point-by-point into accepted risks, and (2) the class-C tail (funding-flip / Ethena-unwind, ~10.55% stress dd, NOT_RECOVERED) is large vs the thin spread → the residual is unpriced tail. Under ADR-YL-008 a class-C sleeve whose spread is not fully risk-explained is held/advisory (risk-comp flag), not promoted. -->

## Advisory scores (0–100; docs/14 — ADVISORY ONLY, never a hard gate)
- **confidence_score:** `LOW–MODERATE (~35) — realized 4.22% is trustworthy (700-pt backtest, Sharpe 1.06), but the headline/forward are not, and the tail is real.` — advisory
- **risk_score:** `HIGH (class C; funding-flip tail; worst stress dd ~10.55%) — requires Risk Scoring v2 run`
- **liquidity_score:** `Moderate, degrades under stress (unstake cooldown + hedge unwind at the worst time). Requires exit-liquidity-by-size (dfb/risk_overlay.py).`
- **complexity_score:** `High — two-leg delta-neutral (sUSDe + short perp) + funding/peg/custody monitoring.`

## Capacity & capital
- **capacity_estimate:** `requires verification — bounded by perp-funding depth + sUSDe capacity; not demonstrated at size`
- **min_capital:** `requires verification`
- **max_capital:** `requires verification`
- **suitable_capital_tiers:** `["isolated high-risk sleeve only — requires verification (docs/34)"]`
- **lockup_period:** `sUSDe unstake cooldown (variable)`
- **withdrawal_time:** `cooldown + hedge unwind + secondary-market exit`

## Risk dimensions (qualitative; feed the advisory scores)
- **smart_contract_risk:** `Ethena minting/staking contracts + perp venue.`
- **stablecoin_risk:** `USDe depeg — synthetic dollar, not fiat-reserve backed (THE peg risk; cross-ref SC-EX-003).`
- **counterparty_risk:** `CEX custody of hedge collateral + perp-venue solvency — material (class-C driver).`
- **bridge_risk:** `Low (mainnet) / per perp venue.`
- **oracle_risk:** `Collateral + perp mark pricing.`
- **liquidation_risk:** `Short-perp hedge leg liquidation under an extreme ETH up-move if under-margined.`
- **regulatory_risk:** `Synthetic-dollar regulatory surface.`
- **operational_risk:** `Delta-neutral rebalancing + funding/peg/custody monitoring.`
- **concentration_risk:** `Single-protocol (Ethena), single mechanism (funding carry).`
- **correlation_risk:** `Funding correlates with the ETH/BTC leverage regime; delta-neutral to ETH price otherwise.`
- **market_regime_risk:** `HIGH — negative-funding regimes erode or invert the carry (the funding-flip tail).`

## Dependencies, assumptions, conditions
- **key_dependencies:** `["positive perp funding", "CEX custody solvency", "USDe/sUSDe peg", "hedge integrity", "live RWA floor (rwa_feed)"]`
- **assumptions:** `["funding net-positive on average", "hedge holds through stress", "peg holds — falsifiable in a USDe unwind"]`
- **entry_conditions:** `["funding-regime check passes", "refused if funding negative / depeg risk elevated"]`
- **exit_conditions:** `["funding persistently negative", "peg/custody stress", "better risk-adjusted allocation"]`
- **emergency_exit_conditions:** `["USDe depeg", "CEX/counterparty failure", "hedge breakdown", "Ethena-unwind event"]`
- **monitoring_requirements:** `["multi-venue perp funding", "USDe/sUSDe peg", "collateral/custody status", "unstake queue", "tail overlay (aggressive_lab)"]`
- **data_sources_required:** `["multi-venue funding feed", "peg oracle", "aggressive_lab scorecard (advisory)", "rwa_feed (live floor)"]`

## Validation & approval (promotion ledger)
- **validation_status:** `research / risk-comp` (aggressive_lab verdict `RISK_COMPENSATION` — advisory, outside RiskPolicy, separate from go-live track)
- **paper_test_status:** `partial — aggressive-lab backtest trustworthy (realized 4.22%, Sharpe 1.06, 700 pts); forward LOCKED_VOL / INSUFFICIENT_DATA (thin)`
- **small_capital_test_status:** `not_started`
- **red_team_status:** `not_started (MANDATORY — basis/counterparty/new-stablecoin + ADR-YL-008 spread-attribution triggers)`
- **approved_for_product_line:** `null`  <!-- NOT approved — risk-comp flagged -->
- **final_recommendation:** `research-only / risk-comp` — hold advisory in the aggressive lab. Realized return is positive and beats the floor (~82 bps), but as a **class-C** sleeve the spread is **not fully risk-explained** (undecomposed + a severe funding-flip/Ethena-unwind tail, ~10.55% stress dd NOT_RECOVERED). Under ADR-YL-008 → NOT promotable until the spread is fully attributed or it is refused.
- **max_allocation:** `0` (is_advisory = True; aggressive lab is outside RiskPolicy, moves no live capital)
- **review_frequency:** `weekly`

## Provenance
- **owner:** `owner / IC (human accountable)`
- **created_at:** `2026-07-02`
- **updated_at:** `2026-07-02`
- **status:** `research`  <!-- honest: NOT approved; risk-comp flagged -->

---

### Promotion gate checklist (docs/11 §5 — MaxYield requires all + ≥ L4)
- [ ] **Spread fully explained (ADR-YL-008)** — **FALSE**: realized ~82 bps spread not decomposed point-by-point; class-C funding-flip/peg/counterparty tail (~10.55% stress dd, NOT_RECOVERED) is unpriced → risk-comp, not alpha.
- [x] Clear yield source (all 5 yield_* fields substantive — funding carry, hedged)
- [ ] APY evidence level ≥ L4 — realized is L3 (4.22%, trustworthy); headline 11% / forward 11.63% NOT verified (LOCKED_VOL)
- [ ] Protocol review — Ethena + perp-venue Protocol Cards (docs/12) not created
- [ ] Stablecoin review — USDe Stablecoin Card (docs/13) not created (cross-ref SC-EX-003)
- [ ] Risk review — advisory Risk Scoring v2 (docs/14) not run (qualitatively HIGH)
- [ ] Red-team review — NOT started (MANDATORY: basis/counterparty/new-stablecoin + spread-attribution)
- [ ] Capacity estimate sourced — requires verification
- [ ] Liquidity review — exit-liquidity-at-size not cited
- [ ] Paper testing passed — backtest trustworthy but forward INSUFFICIENT_DATA
- [ ] Human approval — NOT set (approved_for_product_line = null)

> **Role in ADR-YL-008:** the canonical **positive-but-not-fundable / risk-compensation** example. A
> class-C funding-carry sleeve with a REAL, trustworthy positive realized return (4.22%, beats the
> ~3.4% floor by ~82 bps) is still **NOT promoted** — because under the mandate a positive spread is
> not enough: every point must be attributed to a specific accepted measurable risk, and here the thin
> spread pays for a severe funding-flip / Ethena-unwind tail (~10.55% stress drawdown, NOT_RECOVERED)
> that is not decomposed and not priced. Beating the floor is necessary, not sufficient; the residual
> tail keeps it advisory / risk-comp-flagged.
