# Stablecoin Card — USDe (Ethena)

> Real card for Ethena USDe / sUSDe — mapped from `spa_core/adapters/ethena*.py` (sUSDe adapter, T2,
> synthetic delta-neutral, 7-day cooldown, FALLBACK_TVL ~$1.7B). Research-layer artifact — NOT runtime
> data. **No specifics invented**; unsourced = `requires data verification`. USDe is a
> **risk-compensation** yield asset — the desk treats it advisory/T2 and its yield must clear the
> ADR-YL-008 spread-attribution test. Cross-refs: docs/13, docs/12, docs/38, docs/14, docs/33.

## Identity
- **stablecoin_id:** `STC-USDE-001`
- **symbol:** `USDe` (yield-bearing wrapper: `sUSDe`)
- **issuer:** `Ethena`

## Backing & transparency (the due-diligence core)
- **backing_type:** `synthetic_delta_neutral` — spot crypto collateral (BTC/ETH/LST + stables) HEDGED with short perpetual futures; NOT fiat-backed. The peg relies on the hedge holding.
- **reserve_transparency:** `partial` — Ethena publishes reserve/position dashboards; custody + exchange positions rely on off-chain reporting. `requires verification`.
- **attestations:** `[{firm: "requires verification", cadence: "requires verification", last_date: "requires verification"}]`
- **redemption_mechanism:** `mint/redeem for whitelisted parties vs backing; sUSDe→USDe carries a ~7-day unstake cooldown (168h per the adapter); secondary DEX/CEX liquidity otherwise`

## Liquidity & market structure (never presented without a last-verified date)
- **liquidity_profile:** `Sizable but younger than USDC/USDT; sUSDe has a 7-day cooldown (exit friction) — depth requires data verification`
- **exchange_depth:** `TBD — requires data verification`
- **market_cap:** `~$5.5–5.9B` — **verified 2026-07-02** (DeFiLlama Q2-2026; contracted to ~$5.9B after the Oct-2025 deleveraging). Largest synthetic-dollar after Sky USDS. (The adapter's ~$1.7B literal is stale.) [L2]
- **circulating_supply:** `~$5.9B` (post Oct-2025 deleverage)
- **top_holder_concentration:** `TBD — requires data verification`

## Peg & control risk
- **depeg_history:** `[]`  <!-- USDe is relatively young; verify any stress episodes. Absence here = NOT YET SOURCED, not "none". -->
- **blacklist_freeze_risk:** `requires verification (issuer-controlled mint/redeem; token-level freeze unclear)`
- **regulatory_risk:** `ELEVATED (sourced 2026-07-02): Germany's BaFin barred USDe under MiCA in 2026 — a novel synthetic-dollar structure with active regulatory friction. Reserve Fund ~$61M vs ~$5.6B supply (~1.1%) — small buffer, "not a guarantee." sUSDe yield ~9.4% (7d) / ~11.8% (90d) = clearly risk-comp, not a floor.`
- **jurisdiction:** `Ethena (requires verification)`

## Usage & dependencies
- **chains:** `["Ethereum", "+ verify"]`
- **main_use_cases:** `["yield unit (sUSDe)", "collateral (with care)", "LP pair"]`
- **key_dependencies:** `["PERP FUNDING RATE (yield source AND tail risk — funding can go negative)", "CEX/custody counterparties holding the hedge (counterparty risk)", "collateral (BTC/ETH/LST) integrity", "the hedge executing during stress"]`

## Risk assessment (advisory; cites dfb overlay — never a hard gate)
- **risk_score:** `TBD — requires Risk Scoring v2 run (docs/14). Qualitatively HIGH among stablecoins: synthetic peg + funding dependency + CEX/custody counterparty + young track record. This is a RISK-COMP asset (docs/33 Class C), not a floor-like unit.`
- **max_allocation_recommendation:** `Advisory — SMALL, strict sub-cap; T2/T3 treatment. Its yield must pass the ADR-YL-008 spread-attribution (funding-carry + counterparty + peg risk must explain the spread) or be REFUSED. Exact % requires verification.`
- **monitoring_requirements:** `["perp funding (flip = yield collapse / hedge cost)", "peg", "CEX/custody counterparty health", "collateral composition", "cooldown/redemption queue", "reserve dashboard"]`
- **emergency_exit_triggers:** `["sustained negative funding", "CEX/custody counterparty event", "peg deviation", "collateral impairment", "redemption/cooldown gating during stress"]`

## Provenance
- **notes:** `USDe/sUSDe is a synthetic delta-neutral dollar — its yield is funding-rate carry + staking, which is RISK-COMPENSATION, not a floor. Under ADR-YL-008 its spread over the floor must be fully explained by the accepted funding/counterparty/peg risks or refused (cf. the aggressive_lab + rates_desk treatment). 7-day cooldown = real exit friction. ~$1.7B is an adapter fallback literal — re-verify live.`
- **created_at:** `2026-07-02`
- **updated_at:** `2026-07-02`

---

### Review checklist (docs/13 §5)
- [x] `backing_type` (synthetic delta-neutral), `key_dependencies` (funding + counterparty), `emergency_exit_triggers` filled
- [ ] `depeg_history` / stress episodes sourced — **pending (young asset; absence = not-yet-sourced)**
- [ ] `reserve_transparency` / attestations / market-cap / depth sourced with a date — pending
- [ ] `risk_score` + `max_allocation_recommendation` cite dfb overlay / RiskPolicy caps + ADR-YL-008 spread test — pending
