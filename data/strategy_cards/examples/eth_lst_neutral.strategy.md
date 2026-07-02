# Strategy Card — ETH LST Neutral (SAFE hedged ETH, β≈0)

> Real card mapped from the `eth_lst_neutral` sleeve
> (`spa_core/strategy_lab/strategies/eth_lst_neutral.py`) — the **SAFE ETH-yield** approach:
> PLAIN staking LST (stETH/rETH, **NOT** an LRT) held delta-hedged with a short ETH perp so
> beta ≈ 0. Explicitly the safe counterpart to the LRT sleeves the Lab has shown die in ETH
> crashes (ezETH ~−79% in <1h, variant_n's Aug-2024 depeg kill). Research-layer artifact —
> NOT runtime data, never read by RiskPolicy or execution. Numbers are sourced from
> `data/strategy_lab_backtest.json` (the `eth_lst_neutral` entry) and the sleeve source; anything
> not in those is `requires verification`. Cross-refs: docs/11, docs/07, docs/37, docs/14, docs/34,
> docs/adr/ADR-YL-008, docs/STRATEGY_LAB.md. See also the sUSDe / USDe cards for the funding-carry
> family this sleeve deliberately differs from (it harvests staking + funding, not levered basis).

## Identity
- **strategy_id:** `SC-ETHLSTN-001`  <!-- maps to sleeve id `eth_lst_neutral` -->
- **name:** `ETH LST Neutral (delta-neutral stETH/rETH + perp short)`
- **version:** `1.0`
- **category:** `restaking`  <!-- plain LST staking, delta-hedged (basis-adjacent via the perp leg) -->
- **product_line:** `Enhanced`  <!-- TARGET bucket for hedged-ETH yield. ⚠ HONESTY: no realized spread yet (backtest fail-closed on tick 1 — see Validation). Judged on SPREAD over the floor per ADR-YL-008, not absolute APY. Not approved. -->
- **asset_type:** `ETH`

## What it touches
- **assets_used:** `["stETH or rETH (PLAIN-staking LST — NOT an LRT)", "short ETH perp (hedge leg)"]`  <!-- lst_symbol config-sourced -->
- **protocols_used:** `["Lido/Rocket Pool (LST issuer)", "perp venue (ETH perpetual — hedge leg)"]`  <!-- Protocol Cards (docs/12) not yet created -->
- **chains_used:** `["Ethereum (spot LST)", "perp venue (CEX or on-chain — requires verification)"]`

## Yield source (the honesty core)
- **yield_source:** `Plain ETH staking yield on an LST (stETH/rETH), with the ETH price hedged out by a short ETH perp — income is staking yield ± perp funding, not price appreciation.`
- **yield_mechanism:** `Staking-yield accrual on the LST spot leg + perp funding on the short hedge leg. Beta ≈ 0 by construction (hedge_ratio ≈ 1); the surviving residual is the LST/ETH ratio drift (small for a plain LST).`
- **who_pays_the_yield:** `Ethereum protocol issuance/priority fees (the staking yield, passed through by the LST issuer); + perp longs paying funding to the short hedge when funding is positive (the short PAYS when funding is negative).`
- **why_yield_exists:** `ETH consensus rewards are a real, ongoing protocol payment; perp funding is a real cash flow paid by leveraged longs. Hedging the ETH price leaves the staking carry (± funding) as the harvestable income.`
- **why_yield_can_disappear:** `Funding turns persistently negative (short PAYS → drag/kill); LST/ETH ratio depeg (residual loss on the un-hedgeable ratio drift); hedge-execution slippage/basis; staking-yield compression; validator/slashing event on the LST.`

## APY (never presented without an evidence level)
- **expected_apy_range:** `{ low: requires verification, high: requires verification }`  <!-- staking (~ETH consensus rate) ± funding − hedge cost; per-regime, not yet demonstrated -->
- **observed_apy_range:** `{ backtest_net: 0.0% (FAIL-CLOSED on tick 1 — see below); live_paper_realized: requires verification (own forward series absent → INSUFFICIENT_DATA) }`  <!-- source: data/strategy_lab_backtest.json eth_lst_neutral: killed 2024-06-05 "fail-closed: eth_price missing/invalid", equity flat 100000 → 100000 across 401 pts, net_apy_pct 0.0, max_dd 0.0 -->
- **base_apy:** `plain-LST staking yield (restaking_apy field for the LST = plain staking APY) — requires verification`
- **incentive_apy:** `0 / N/A (plain LST staking is contractual yield only — no points, the SAFE path by design)`
- **sustainable_apy_estimate:** `requires verification — no realized track yet (backtest never traded; own forward series absent)`
- **apy_evidence_level:** `L0–L1` — the backtest fail-closed on the first tick (no eth_price feed) so it produced **no traded track**; realized-at-size is INSUFFICIENT_DATA. Not L3. <!-- docs/37 -->

## Spread over the floor (the mandate — ADR-YL-008: judged as spread over the live floor, not absolute APY)
- **floor_baseline_pct:** `{ value: ~3.4, source: rwa_feed (live via data/rwa_feed.py; NEVER hardcoded; fail-closed committed-literal fallback), as_of: 2026-07-02, fallback_used: requires verification }`  <!-- rwa_sleeve realized ~3.4328% in the same backtest confirms the baseline -->
- **spread_over_floor_bps:** `NOT YET MEASURABLE — realized spread = requires verification / INSUFFICIENT_DATA. The backtest booked 0 (fail-closed on tick 1, equity flat at $100,000), so there is no realized excess over the floor to report. Expected (un-evidenced) spread = staking + funding − hedge cost − floor, magnitude requires verification.`
- **spread_risk_explanation:** the accepted, measurable risks that WOULD have to fully explain any positive spread over the floor. **Per-risk bps split is NOT computed** (no realized spread to attribute) → each `bps` below is `requires attribution`:
  - `{ risk: "LST depeg-residual (un-hedgeable LST/ETH ratio drift; smaller than an LRT by construction but non-zero)", bps: "requires attribution", evidence: "eth_lst_neutral.py depeg kill on smoothed/persistent lst_eth_ratio drop; TIGHTER threshold Y than the LRT variants" }`
  - `{ risk: "Perp funding risk (short PAYS when funding is negative → carry drag / funding kill)", bps: "requires attribution", evidence: "eth_lst_neutral.py funding_kill_threshold / funding_kill_hours; cum_funding tracked" }`
  - `{ risk: "Hedge-execution risk (slippage/gas on hedge rebalance, basis between spot LST and perp)", bps: "requires attribution", evidence: "eth_lst_neutral.py rebalance band + gas_usd + slippage_bps cost model" }`
  - `{ risk: "Validator / slashing / LST smart-contract risk (spot staking leg)", bps: "requires attribution", evidence: "LST issuer contracts (Protocol Card TBD)" }`
- **unexplained_spread_bps:** `Realized level: N/A (realized spread is requires-verification / INSUFFICIENT_DATA). Any future positive spread must be decomposed point-by-point into the accepted risks above before it counts as explained — until then it is treated as unpriced tail risk, not alpha.`
- **spread_fully_explained:** `false`  <!-- (1) there is NO realized spread over the floor yet (backtest fail-closed on tick 1 → 0; own forward series absent → INSUFFICIENT_DATA); (2) the risk→bps attribution is not decomposed. Under ADR-YL-008 → cannot advance to Enhanced; held at paper_testing. -->

## Advisory scores (0–100; docs/14 — ADVISORY ONLY, never a hard gate)
- **confidence_score:** `LOW (~25) — the design is the SAFE one (plain LST + hedge, β≈0), but there is no realized evidence: backtest never traded (fail-closed), own forward series absent.` — advisory
- **risk_score:** `TBD — requires a formal Risk Scoring v2 run (docs/14). Qualitatively LOWER than the LRT/levered sleeves (β≈0, plain LST, no leverage), but non-zero (depeg-residual + funding + hedge-execution + slashing).`
- **liquidity_score:** `Moderate — LST spot is liquid; perp hedge exit is venue-dependent. Requires exit-liquidity-by-size (dfb/risk_overlay.py).`
- **complexity_score:** `Moderate — two-leg hedged position + funding/depeg kill management. Requires verification on 0–100 scale.`

## Capacity & capital
- **capacity_estimate:** `requires verification — no realized capacity demonstrated (backtest never traded). LST spot is deep; the binding constraint is likely perp-funding depth / hedge capacity.`
- **min_capital:** `requires verification`
- **max_capital:** `requires verification`
- **suitable_capital_tiers:** `["requires verification — not yet demonstrated at any tier"]`  <!-- docs/34 -->
- **lockup_period:** `none (LST liquid); unstake/exit cooldown depends on LST + perp venue`
- **withdrawal_time:** `requires verification — LST spot liquid; perp unwind venue-dependent`

## Risk dimensions (qualitative; feed the advisory scores)
- **smart_contract_risk:** `LST issuer contracts (Lido/Rocket Pool — battle-tested but non-zero) + perp venue.`
- **stablecoin_risk:** `N/A — ETH-denominated staking, not a stablecoin play.`
- **counterparty_risk:** `Perp venue (CEX or on-chain) for the hedge leg — material; hedge_available is required for β≈0.`
- **bridge_risk:** `N/A single-chain spot — verify if the perp venue is cross-chain.`
- **oracle_risk:** `LST/ETH ratio + perp mark pricing (depeg signal is smoothed/persistent to reject 1-day DeFiLlama timestamp-misalignment artifacts).`
- **liquidation_risk:** `Short-perp hedge leg could be liquidated under an extreme ETH up-move if under-margined — hedge sizing/margin management required (no recursive leverage though).`
- **regulatory_risk:** `Low–moderate (staking + perp).`
- **operational_risk:** `Daily funding/depeg kill checks + hedge rebalance; fail-closed on any missing datapoint (the backtest kill demonstrates this).`
- **concentration_risk:** `Single LST + single perp venue.`
- **correlation_risk:** `β≈0 to ETH by construction; residual correlation via LST/ETH ratio and funding regime.`
- **market_regime_risk:** `Negative-funding regime erodes/kills the carry; high-vol crash stresses the LST peg and hedge basis.`

## Dependencies, assumptions, conditions
- **key_dependencies:** `["live ETH price feed (backtest fail-closed without it)", "LST/ETH ratio feed", "plain-staking APY feed", "multi-venue perp funding feed", "live RWA floor (rwa_feed)"]`
- **assumptions:** `["hedge_ratio ≈ 1 keeps β≈0", "LST stays tight to peg (plain LST, not LRT)", "funding net-positive on average"]`
- **entry_conditions:** `["valid ETH price + LST ratio + staking APY + funding present", "funding above kill threshold"]`
- **exit_conditions:** `["funding persistently below kill threshold for ≥ N hours", "sustained (smoothed, persistent) LST depeg > Y%"]`
- **emergency_exit_conditions:** `["any required datapoint invalid → fail-closed safe-hold (kill)", "LST depeg / issuer or perp-venue failure"]`
- **monitoring_requirements:** `["daily funding + depeg kill scan", "own forward series (currently absent → INSUFFICIENT_DATA)", "hedge drift/rebalance band"]`
- **data_sources_required:** `["price_feed (ETH + LST ratio)", "restaking_feed (plain staking APY)", "multi-venue funding feed", "rwa_feed (live floor)", "dfb exit-liquidity-by-size"]`

## Validation & approval (promotion ledger)
- **validation_status:** `paper_testing` (SAFE-sleeve mandate: advisory until canary)
- **paper_test_status:** `running (strategy_lab paper, com.spa.strategy_lab_paper) — but backtest FAIL-CLOSED on tick 1 (no eth_price feed on 2024-06-05) and own forward series is absent → realized track INSUFFICIENT_DATA`
- **small_capital_test_status:** `not_started`
- **red_team_status:** `not_started — the ADR-YL-008 spread-attribution red-team is not applicable yet (no realized spread to attribute); depeg/funding/hedge/counterparty triggers require a Red Team before any advance`
- **approved_for_product_line:** `null`  <!-- NOT approved -->
- **final_recommendation:** `research-only` — hold at `paper_testing`. The design is the SAFE hedged-ETH path, but there is **no realized spread over the floor** yet (backtest fail-closed on tick 1; forward series absent → INSUFFICIENT_DATA), and no spread can be attributed. Under ADR-YL-008 it cannot advance to Enhanced.
- **max_allocation:** `0` (is_advisory = True — moves no live capital)
- **review_frequency:** `daily (paper) / weekly (IC)`

## Provenance
- **owner:** `owner / IC (human accountable)`
- **created_at:** `2026-07-02`
- **updated_at:** `2026-07-02`
- **status:** `paper_testing`

---

### Promotion gate checklist (docs/11 §5 — all required for Enhanced/MaxYield)
- [ ] **Spread fully explained (ADR-YL-008)** — **FALSE**: no realized spread over the floor yet (backtest fail-closed on tick 1 → 0; own forward series absent → INSUFFICIENT_DATA); risk→bps attribution not decomposed.
- [x] Clear yield source (all 5 yield_* fields substantive — staking + funding, hedged)
- [ ] APY evidence level ≥ L3 — currently L0–L1 (no traded track); realized is INSUFFICIENT_DATA
- [ ] Protocol review — LST issuer + perp-venue Protocol Cards (docs/12) not yet created
- [ ] Stablecoin review — N/A (ETH-denominated)
- [ ] Risk review — advisory Risk Scoring v2 (docs/14) not yet run
- [ ] Red-team review — not started (depeg/funding/hedge/counterparty triggers)
- [ ] Capacity estimate + suitable_capital_tiers sourced — requires verification (never traded)
- [ ] Liquidity review — exit-liquidity-at-size not yet cited (perp-hedge depth is the likely constraint)
- [ ] Paper testing passed — running, not passed (realized track INSUFFICIENT_DATA)
- [ ] Human approval — owner has not set approved_for_product_line

> **Role in ADR-YL-008:** the intended **SAFE** ETH-yield sleeve — plain LST + short perp, β≈0 —
> deliberately chosen over the LRT/levered sleeves the Lab has shown blow up (leverage_loop realized
> −8.95%, variant_d realized −15.48%, lrt_carry realized −3.60%). But "safer design" earns nothing
> under the mandate without a **realized spread over the floor that is fully risk-explained**, and
> this sleeve has **no realized spread yet** (backtest fail-closed on tick 1; forward series absent).
> Correctly held at `paper_testing`, not promoted — honesty over the intuition that "hedged = fundable."
