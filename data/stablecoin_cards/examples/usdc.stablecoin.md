# Stablecoin Card — USDC

> Real card for USD Coin (Circle) — the desk's primary settlement + lending unit. Research-layer
> artifact — NOT runtime data, never read by RiskPolicy or execution. **No market-cap/supply/depth is
> invented**; anything not publicly-certain or sourced is `requires data verification`. Cross-refs:
> docs/13, docs/12, docs/38, docs/14, docs/02.

## Identity
- **stablecoin_id:** `STC-USDC-001`
- **symbol:** `USDC`
- **issuer:** `Circle`

## Backing & transparency (the due-diligence core)
- **backing_type:** `fiat_backed` — **sourced (verified 2026-07-02):** ~80%+ held in the **BlackRock-managed Circle Reserve Fund (USDXX, a registered 2a-7 government money-market fund, custodied at BNY Mellon)**; remainder cash at GSIB banks.
- **reserve_transparency:** **FULL monthly attestation (sourced 2026-07-02)** — AICPA agreed-upon-procedures (point-in-time reserve assertion, NOT a full GAAS audit). Published on Circle's transparency page.
- **attestations:** `[{firm: "Deloitte & Touche LLP", cadence: "monthly", type: "AICPA agreed-upon-procedures (point-in-time)", last_seen: "March 2026 (as-of Mar 11 + Mar 31 2026)"}]` — **verified 2026-07-02 [L2]**
- **redemption_mechanism:** `direct issuer redemption (1:1 for eligible/KYC'd institutional accounts) + deep secondary AMM/CEX liquidity for everyone else`

## Liquidity & market structure (never presented without a last-verified date)
- **liquidity_profile:** `Very deep on-chain + CEX (one of the two most-liquid stablecoins) — exact depth requires data verification`
- **exchange_depth:** `TBD — requires data verification (source depth-for-exit-by-size)`
- **market_cap:** `~$73.5–77B` — **verified 2026-07-02** (Circle transparency / DeFiLlama; 2nd-largest stablecoin). [L2]
- **circulating_supply:** `~$73.5B across 30+ chains` (2026)
- **top_holder_concentration:** `TBD — requires data verification`

## Peg & control risk
- **depeg_history:** `[{date: "2023-03 (SVB)", depth: "~$0.88 low (verify exact)", duration: "~days", cause: "USDC reserves partly held at Silicon Valley Bank during its failure", recovery: "full repeg after USG backstop of SVB deposits"}]`  <!-- well-documented event; exact figures requires verification -->
- **blacklist_freeze_risk:** `can_freeze_and_blacklist` — Circle can freeze specific addresses (centralized control; a real, accepted risk)
- **regulatory_risk:** `Moderate — regulated US issuer; sanctions/OFAC compliance means addresses can be frozen; generally viewed as the more compliance-aligned major stablecoin (verify current status)`
- **jurisdiction:** `United States (Circle)`

## Usage & dependencies
- **chains:** `["Ethereum (native)", "Arbitrum", "Optimism", "Base", "Polygon", "+ others (native + bridged — verify which the desk uses)"]`
- **main_use_cases:** `["settlement", "collateral", "lending unit (Aave/Compound/Morpho)", "LP pair", "PT underlying (Pendle fixed carry)"]`
- **key_dependencies:** `["Circle solvency + banking partners", "reserve custody (banks + US Treasuries)", "OFAC/regulatory regime", "bridge integrity for non-native chains"]`

## Risk assessment (advisory; cites dfb overlay — never a hard gate)
- **risk_score:** `TBD — requires a Risk Scoring v2 run (docs/14). Qualitatively LOW among stablecoins (deep liquidity, regulated fiat backing), with the accepted centralization/freeze + banking-exposure risks the SVB event demonstrated.`
- **max_allocation_recommendation:** `Advisory — USDC is the desk's lowest-risk stablecoin unit; still bounded by RiskPolicy caps. Exact % requires verification.`
- **monitoring_requirements:** `["peg (alert on deviation)", "reserve attestation cadence", "banking-partner / regulatory news", "freeze/blacklist actions"]`
- **emergency_exit_triggers:** `["peg deviation beyond threshold", "reserve doubt / attestation miss", "banking-partner failure (SVB-type)", "freeze/blacklist action on desk addresses", "redemption halt"]`

## Provenance
- **notes:** `USDC is the primary settlement/lending unit and a Pendle-PT underlying (feeds SC-RDFC-001). Backing_type + freeze capability + the 2023 SVB depeg are publicly certain and stated; specific figures (market cap, supply, depth, attestation firm/cadence) are requires-verification, not invented. Fail-closed: an unverified attestation cadence is a finding, not a blank.`
- **created_at:** `2026-07-02`
- **updated_at:** `2026-07-02`

---

### Review checklist (docs/13 §5)
- [x] `backing_type`, `blacklist_freeze_risk`, `depeg_history`, `emergency_exit_triggers` filled substantively (SVB depeg + freeze capability documented)
- [x] `reserve_transparency` attestation firm/cadence SOURCED — **Deloitte & Touche LLP, monthly AICPA AUP, last March 2026 (verified 2026-07-02)**
- [ ] `market_cap` / `circulating_supply` / liquidity fields sourced with a last-verified date — **pending**
- [ ] `risk_score` + `max_allocation_recommendation` cite the dfb overlay / RiskPolicy caps — pending
