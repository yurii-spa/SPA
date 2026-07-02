# Strategy Card — Rates Desk · Fixed Carry (PT to maturity)

> Real card mapped from the existing `rates_desk_fixed_carry` sleeve
> (`spa_core/strategy_lab/rates_desk/`) — the first end-to-end demonstration of the ADR-YL-008
> unified mandate (judge **spread over the live floor**, every point risk-explained). Research-layer
> artifact — NOT runtime data, never read by RiskPolicy or execution. Numbers are sourced from
> `data/rates_desk/rates_desk_promotion.json`, `data/rates_desk/paper/status.json`, and
> `data/rates_desk/paper/realized_at_size_track.jsonl`; anything not in those is
> `requires verification`. Cross-refs: docs/11, docs/07, docs/37, docs/14, docs/34,
> docs/adr/ADR-YL-008, docs/RATES_DESK.md, docs/RATES_DESK_VALIDATION.md.

## Identity
- **strategy_id:** `SC-RDFC-001`  <!-- maps to sleeve id `rates_desk_fixed_carry` -->
- **name:** `Rates Desk — Fixed Carry (PT to maturity)`
- **version:** `1.0`
- **category:** `carry`
- **product_line:** `Enhanced`  <!-- TARGET bucket (docs/07 §2 maps rates_desk → Enhanced machinery). ⚠ HONESTY: backtest absolute net APY ~6.09% is BELOW the Enhanced 10–13% band; the mandate (ADR-YL-008) judges this card on SPREAD over the floor, not absolute APY. Not approved — see Validation. -->
- **asset_type:** `stablecoin`

## What it touches
- **assets_used:** `["Pendle PT (stablecoin/yield underlyings that survive the refusal gate)"]`
- **protocols_used:** `["Pendle (PT)", "lending venues (baseline rate)"]`  <!-- Protocol Cards (docs/12) not yet created — required before Enhanced promotion -->
- **chains_used:** `["Ethereum (+ chains where the survivor PT markets live)"]`  <!-- per-market — requires verification -->

## Yield source (the honesty core)
- **yield_source:** `Fixed-rate carry — buy Pendle PT below its fair implied yield and hold to maturity.`
- **yield_mechanism:** `PT fixed carry harvested only when (quoted_implied − fair_implied) > COST_BUFFER (0.5%/yr) AND tail_score < TAIL_REFUSE_THRESHOLD (0.45). Refusal-first: yield that is mostly tail-compensation is REFUSED, not booked.`
- **who_pays_the_yield:** `The PT-market counterparty selling future yield at a discount (YT/leveraged-yield buyers).`
- **why_yield_exists:** `A mispriced implied rate — the PT's quoted implied yield exceeds the engine's fair implied yield (kind-aware baseline − a tail-risk haircut up to MAX_TAIL_HAIRCUT_APY 12%). The surviving gap is real carry, by construction not explained by tail risk.`
- **why_yield_can_disappear:** `Rate compression toward maturity; Pendle liquidity thinning (exit-at-size); regime/incentive shift; or the gate reclassifying it as tail-comp (tail_score ≥ 0.45).`

## APY (never presented without an evidence level)
- **expected_apy_range:** `{ low: ~4.96%, high: ~6.09% } (BACKTEST net; the promotion sleeves span 4.96–6.09%)`
- **observed_apy_range:** `{ backtest_net: 6.0901% (walk-forward 100% consistency); live_paper_realized: 0.0119% (thin) }`  <!-- source: promotion.json net_apy_pct; paper/status.json net_apy_pct -->
- **base_apy:** `PT fixed carry (per-market — requires verification)`
- **incentive_apy:** `~0 / N/A (fixed carry is not incentive-driven)`
- **sustainable_apy_estimate:** `TBD — realized-at-size is INSUFFICIENT_DATA; not yet demonstrated`
- **apy_evidence_level:** `L3` (paper-tracked, THIN) — backtest is L1–L2; realized-at-size is NOT yet L4. <!-- docs/37 -->

## Spread over the floor (the mandate — ADR-YL-008: judged as spread over the live floor, not absolute APY)
- **floor_baseline_pct:** `{ value: 3.4, source: rwa_feed (live via _USE_LIVE_RWA_FLOOR; fail-closed committed-literal fallback), as_of: 2026-07-01, fallback_used: requires verification }`  <!-- NEVER hardcoded; promotion.json used rwa_floor_pct 3.4 -->
- **spread_over_floor_bps:** `BACKTEST ≈ 269 bps (net_apy 6.0901% − floor 3.4%). REALIZED-at-size = 0 bps (realized_at_size_track: floor_plus_bps_at_5M 0.0, verdict INSUFFICIENT_DATA, realized_days 0).`
- **spread_risk_explanation:** the accepted, measurable risks that constitute the backtest carry above the tail-comp threshold. **Per-risk bps split is NOT yet computed** (the fair-value engine yields a single `tail_score` → single haircut, not a per-risk decomposition) → each `bps` below is `requires attribution`:
  - `{ risk: "PT rate/duration risk (fixed rate held to maturity; MTM before maturity)", bps: "requires attribution", evidence: "feeds.build_surface RateSurface" }`
  - `{ risk: "Pendle protocol / smart-contract risk", bps: "requires attribution", evidence: "Pendle PT contracts (Protocol Card TBD)" }`
  - `{ risk: "Underlying collateral / peg risk (survivors only — toxic LRT underlyings refused)", bps: "requires attribution", evidence: "refusals_count 1070; RATES_DESK_VALIDATION Assertion 1 PASS" }`
  - `{ risk: "Exit-liquidity-at-size risk (thin PT liquidity → capacity-bounded)", bps: "requires attribution", evidence: "realized_at_size verdict INSUFFICIENT_DATA; n_books_deployable 0" }`
- **unexplained_spread_bps:** `Realized level: N/A (realized spread is 0 / INSUFFICIENT_DATA). Backtest level: the per-point risk→bps attribution of the ~269 bps is NOT yet decomposed → treat as requires-attribution, not as alpha.`
- **spread_fully_explained:** `false`  <!-- (1) realized-at-size spread = 0 (INSUFFICIENT_DATA, realized_days 0); (2) the backtest spread is not yet decomposed point-by-point into named accepted risks. Under ADR-YL-008 → cannot advance to Enhanced; held at paper_testing; the 1070 refusals are logged positive results. -->

## Advisory scores (0–100; docs/14 — ADVISORY ONLY, never a hard gate)
- **confidence_score:** `~40` (backtest strong: score 6/6, walk-forward 100%, deflated_sharpe 1.0; but realized-at-size INSUFFICIENT_DATA lowers confidence) — advisory
- **risk_score:** `TBD — requires a formal Risk Scoring v2 run (docs/14). Qualitatively moderate (PT duration + Pendle + exit-liquidity).`
- **liquidity_score:** `LOW — exit-at-size is the binding constraint (INSUFFICIENT_DATA at $5M). Requires exit-liquidity-by-size from dfb/risk_overlay.py.`
- **complexity_score:** `Moderate — PT mechanics + maturity roll management. Requires verification on 0–100 scale.`

## Capacity & capital
- **capacity_estimate:** `BACKTEST "max safe AUM $5,000,000"; REALIZED deployable = $0 (n_books_deployable 0, INSUFFICIENT_DATA). The backtest capacity is NOT yet realized.`
- **min_capital:** `TBD — requires verification`
- **max_capital:** `BACKTEST $5,000,000; REALIZED 0`
- **suitable_capital_tiers:** `["backtest ≤ ~$1–5M; realized none yet"]`  <!-- docs/34 — requires verification; the honest edge-at-scale finding: carry is venue-capped -->
- **lockup_period:** `to PT maturity (variable per market)`
- **withdrawal_time:** `Held to maturity, or early via Pendle AMM (liquidity-dependent) — exit-at-size is the constraint.`

## Risk dimensions (qualitative; feed the advisory scores)
- **smart_contract_risk:** `Pendle PT contracts (battle-tested but non-zero).`
- **stablecoin_risk:** `Depends on the PT underlying — survivors only (refusal gate rejects toxic underlyings). Stablecoin Cards (docs/13) required before Enhanced.`
- **counterparty_risk:** `PT market / AMM liquidity. No CEX leg (hedge_available = False → this is UNHEDGED fixed carry, not a basis trade).`
- **bridge_risk:** `N/A single-chain PT — verify per market.`
- **oracle_risk:** `Implied-rate / PT pricing dependency.`
- **liquidation_risk:** `None — FixedCarry uses no leverage (leverage lives in the separate LeveredCarry sleeve, research-only).`
- **regulatory_risk:** `Low–moderate (DeFi PT).`
- **operational_risk:** `Maturity roll management; daily rate-surface + refusal scan.`
- **concentration_risk:** `Per-market PT concentration; bounded by RiskPolicy caps (advisory here).`
- **correlation_risk:** `Rate-regime correlation; low BTC/ETH beta (stable mandate).`
- **market_regime_risk:** `Rate-compression / Pendle-liquidity regime sensitivity.`

## Dependencies, assumptions, conditions
- **key_dependencies:** `["Pendle PT market liquidity", "live RateSurface (feeds.build_surface)", "live RWA floor (rwa_feed)"]`
- **assumptions:** `["PT held to maturity realizes the fixed rate", "exit-at-size available if early exit is needed (currently unproven — INSUFFICIENT_DATA)"]`
- **entry_conditions:** `["(quoted_implied − fair_implied) > COST_BUFFER 0.5%", "tail_score < 0.45 (refusal-first)"]`
- **exit_conditions:** `["maturity", "fair-value convergence", "gate flips to REFUSE (tail_score ≥ 0.45)"]`
- **emergency_exit_conditions:** `["underlying depeg", "Pendle exploit", "PT liquidity collapse"]`
- **monitoring_requirements:** `["daily rate surface + refusal scan (com.spa.rates_desk_paper)", "realized_at_size_track", "proof-chain (entries + refusals)"]`
- **data_sources_required:** `["feeds.build_surface (Pendle/lending rate surface)", "rwa_feed (live floor)", "dfb exit-liquidity-by-size"]`

## Validation & approval (promotion ledger)
- **validation_status:** `paper_testing` (sleeve stage `PAPER_CANDIDATE`: backtest + walk-forward passed)
- **paper_test_status:** `running` — `com.spa.rates_desk_paper` live-paper track growing; realized-at-size verdict INSUFFICIENT_DATA
- **small_capital_test_status:** `not_started`
- **red_team_status:** `partial` — refusal-first gate + 1070 refusals + RATES_DESK_VALIDATION Assertion 1 (refusals fired) & Assertion 2 (survivor book beats floor risk-adjusted in backtest) PASS; **the ADR-YL-008 spread-attribution red-team (Q19) is NOT yet done** → not passed for Enhanced
- **approved_for_product_line:** `null`  <!-- NOT approved -->
- **final_recommendation:** `research-only` — hold at `paper_testing`. Backtest spread is real and refusal-validated, but the **realized-at-size spread is 0 (INSUFFICIENT_DATA)** and the spread is **not yet decomposed point-by-point into accepted risks**; under ADR-YL-008 it cannot advance to Enhanced.
- **max_allocation:** `0` (IS_ADVISORY = True — moves no live capital)
- **review_frequency:** `daily (paper) / weekly (IC)`

## Provenance
- **owner:** `owner / IC (human accountable)`
- **created_at:** `2026-07-02`
- **updated_at:** `2026-07-02`
- **status:** `paper_testing`

---

### Promotion gate checklist (docs/11 §5 — all required for Enhanced/MaxYield)
- [ ] **Spread fully explained (ADR-YL-008)** — **FALSE**: realized-at-size spread = 0 (INSUFFICIENT_DATA); backtest ~269 bps not yet decomposed point-by-point into named accepted risks.
- [x] Clear yield source (all 5 yield_* fields substantive, no TBD)
- [ ] APY evidence level ≥ L3 (Enhanced) — L3 is thin; realized-at-size is not yet L4; **not met** for a spread that clears the floor at size
- [ ] Protocol review — Pendle (+baseline venue) Protocol Cards (docs/12) not yet created
- [ ] Stablecoin review — underlying Stablecoin Cards (docs/13) not yet created
- [ ] Risk review — advisory Risk Scoring v2 (docs/14) not yet formally run
- [ ] Red-team review passed — refusal gate passed; ADR-YL-008 spread-attribution red-team pending
- [~] Capacity estimate — backtest max safe AUM $5M, but realized deployable $0 (partial)
- [ ] Liquidity review — exit-liquidity-at-size INSUFFICIENT_DATA (the binding gap)
- [ ] Paper testing passed — running, not passed (thin / realized-at-size INSUFFICIENT_DATA)
- [ ] Human approval — owner has not set approved_for_product_line

> **What this card demonstrates (ADR-YL-008 working):** a sleeve that is *backtest-GO* (PAPER_CANDIDATE,
> beats the floor, $5M backtest capacity, 100% walk-forward) is correctly **held at `paper_testing`,
> not promoted** — because the mandate judges the **realized spread over the live floor**, which is
> currently **0 / INSUFFICIENT_DATA**, and requires **every point of that spread to be attributed to a
> specific accepted risk**, which is **not yet decomposed**. The 1,070 refusals are the positive
> product. Absolute APY (~6%) is deliberately not the yardstick — spread is.
