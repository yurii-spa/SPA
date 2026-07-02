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
- **reserve_transparency:** **STRENGTHENED (sourced 2026-07-02):** solvency is provable — **weekly proof-of-reserves** + institutional custody. Since Jan-2026: **Kraken** custody partner (weekly PoR) + **Anchorage Digital Bank** custodian (**monthly signed attestations + weekly PoR**). Independent attestors (Chaos Labs, Chainlink, Llama Risk, Harris & Trotter) verified overcollateralization live through the Oct-2025 crash. [L2]
- **attestations:** `[{firm: "Anchorage Digital Bank", cadence: "monthly signed + weekly PoR", since: "Jan 2026"}, {firm: "Kraken (custody)", cadence: "weekly PoR", since: "Jan 2026"}, {firm: "Chaos Labs/Chainlink/Llama Risk/Harris & Trotter", role: "independent overcollateralization attestors (Oct-2025 stress)"}]` — **verified 2026-07-02 [L2]**
- **redemption_mechanism:** `mint/redeem for whitelisted parties vs backing; sUSDe→USDe carries a ~7-day unstake cooldown (168h per the adapter); secondary DEX/CEX liquidity otherwise`

## Liquidity & market structure (never presented without a last-verified date)
- **liquidity_profile:** `Sizable but younger than USDC/USDT; sUSDe has a 7-day cooldown (exit friction) — depth requires data verification`
- **exchange_depth:** `TBD — requires data verification`
- **market_cap:** `~$5.5–5.9B` — **verified 2026-07-02** (DeFiLlama Q2-2026; contracted to ~$5.9B after the Oct-2025 deleveraging). Largest synthetic-dollar after Sky USDS. (The adapter's ~$1.7B literal is stale.) [L2]
- **circulating_supply:** `~$5.9B` (post Oct-2025 deleverage)
- **top_holder_concentration:** `TBD — requires data verification`

## Peg & control risk
- **depeg_history:** `[{date: "2025-10-10/11", event: "$19B market-wide deleveraging (tariff shock)", binance_low: "$0.65 (−35%)", true_impact: "DEX only −0.3% (Curve); the $0.65 was a BINANCE-oracle/Unified-Account ARTIFACT (internal orderbook oracle), NOT true value", solvency: "remained OVERCOLLATERALIZED ~$66M THROUGHOUT (attested live: Chaos Labs, Chainlink, Llama Risk, Harris & Trotter)", mechanism: "supply $9B→$6B redeemed near-instantly WITHOUT unwinding basis; short perps PROFITED as prices fell, padding reserves", outcome: "no exploit, no undercollateralization — design validated under duress; CoinDesk: 'USDe did not de-peg'. Note: $8.3B/24h outflows survived; synthetic rivals xUSD/deUSD collapsed outright"}]`  <!-- SOURCED 2026-07-02 — the key stress test -->
- **solvency_dd (sourced 2026-07-02, gates PT-sUSDe / CAND-PTSUSDE-001):** negative-funding history over 3yr = **17.5% of days negative, longest stretch 13 days** (vs 176 positive) — frequent but SHORT; reserve fund (~1.1% TVL) covers short bursts + acts as bidder-of-last-resort. **Oct-2025 stress passed overcollateralized.** Residual: thin 1.1% reserve; reflexivity (mcap $14.7B→$6.4B in 2mo); an EXTENDED (>reserve-coverage) negative-funding regime is the real tail — measurable + monitorable.
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
- [x] `depeg_history` SOURCED — Oct-2025 $19B crash: overcollateralized ~$66M throughout, Binance-$0.65 = oracle artifact, design validated (the key stress test)
- [x] `reserve_transparency` / attestations SOURCED — Anchorage (monthly attest + weekly PoR) + Kraken (weekly PoR), Jan-2026; market-cap ~$5.9B (2026-07-02)
- [x] `solvency_dd` for PT-sUSDe SOURCED — neg-funding 17.5% days/max 13d; reserve 1.1%; stress-passed; residual = extended-negative-funding (measurable)
- [ ] `risk_score` + `max_allocation_recommendation` cite dfb overlay / RiskPolicy caps + ADR-YL-008 spread test — pending
