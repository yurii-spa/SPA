# Stablecoin Card — USDS (Sky)

> Real card for USDS (Sky, the MakerDAO successor) / sUSDS. Research-layer artifact — NOT runtime data.
> **No specifics invented**; unsourced = `requires data verification`. NOTE the runtime constraint:
> the desk holds `sky_susds` at **0% APY until an on-chain GSM Pause Delay ≥ 48h is confirmed**
> (CLAUDE.md FORBIDDEN #8) — this card must not imply yield before that. Cross-refs: docs/13, docs/12,
> docs/38, docs/14.

## Identity
- **stablecoin_id:** `STC-USDS-001`
- **symbol:** `USDS` (yield wrapper: `sUSDS`)
- **issuer:** `Sky (formerly MakerDAO) — decentralized protocol`

## Backing & transparency (the due-diligence core)
- **backing_type:** `hybrid` — same lineage as DAI (crypto-overcollateralized + RWA + stablecoin/PSM backing); USDS is the Sky-rebrand upgrade of DAI. `requires verification` of current composition.
- **reserve_transparency:** `on-chain collateral transparent; RWA legs partial` — `requires verification`
- **attestations:** `[]`  <!-- verify Sky reporting -->
- **redemption_mechanism:** `Sky PSM + vault redemption; DAI↔USDS converter; DEX liquidity`

## Liquidity & market structure (never presented without a last-verified date)
- **liquidity_profile:** `Growing (inherits DAI liquidity via converter) — depth requires data verification`
- **exchange_depth:** `TBD — requires data verification`
- **market_cap:** `TBD — requires data verification`
- **circulating_supply:** `TBD — requires data verification`
- **top_holder_concentration:** `TBD — requires data verification`

## Peg & control risk
- **depeg_history:** `[]`  <!-- USDS is new (2024 rebrand); inherits DAI's risk lineage (incl. the USDC/PSM correlation). Absence = NOT YET SOURCED. -->
- **blacklist_freeze_risk:** `requires verification` — DAI-lineage suggests no token-level freeze, but USDS added features/backing must be verified (indirect USDC/PSM exposure likely persists)
- **regulatory_risk:** `Inherits USDC/RWA-backing exposure (like DAI); decentralized issuer reduces direct issuer risk`
- **jurisdiction:** `Decentralized protocol (Sky); RWA legs multi-jurisdiction`

## Usage & dependencies
- **chains:** `["Ethereum (native)", "+ verify"]`
- **main_use_cases:** `["settlement", "collateral", "sUSDS yield wrapper (Sky Savings Rate)", "LP pair"]`
- **key_dependencies:** `["Sky protocol governance + parameters", "USDC/PSM + RWA backing (USDC-correlation like DAI)", "collateral health", "the GSM Pause Delay safety mechanism (see below)"]`

## Risk assessment (advisory; cites dfb overlay — never a hard gate)
- **risk_score:** `TBD — requires Risk Scoring v2 run (docs/14). Qualitatively LOW-MODERATE (DAI-lineage), plus a specific governance-safety caveat below.`
- **max_allocation_recommendation:** `Advisory — bounded by RiskPolicy caps; correlate with USDC/DAI when sizing.`
- **monitoring_requirements:** `["peg", "GSM Pause Delay status (on-chain ≥48h?)", "USDC/PSM backing share", "Sky governance parameter changes", "RWA-leg disclosures"]`
- **emergency_exit_triggers:** `["peg deviation", "GSM Pause Delay removed/weakened", "USDC depeg (correlated)", "governance risk-parameter shock", "RWA-leg impairment"]`

## Provenance
- **notes:** `RUNTIME CONSTRAINT (CLAUDE.md FORBIDDEN #8): sky_susds is held at 0% APY until an on-chain GSM Pause Delay ≥ 48h is confirmed — the pause-delay is the depositor-protection window against a malicious governance action. This card must not present a sUSDS yield as available until that condition is verified on-chain. USDS inherits DAI's USDC/RWA-backing correlation. New asset (2024) — most specifics requires verification.`
- **created_at:** `2026-07-02`
- **updated_at:** `2026-07-02`

---

### Review checklist (docs/13 §5)
- [x] `backing_type` (DAI-lineage hybrid), `key_dependencies` (GSM pause delay + USDC/PSM), `emergency_exit_triggers` filled
- [ ] **GSM Pause Delay ≥ 48h on-chain confirmed** — governance-safety gate (FORBIDDEN #8) — **pending verification**
- [ ] `reserve_transparency` / backing share / market-cap / depth sourced with a date — pending
- [ ] `risk_score` + `max_allocation_recommendation` cite dfb overlay / RiskPolicy caps + USDC-correlation — pending
