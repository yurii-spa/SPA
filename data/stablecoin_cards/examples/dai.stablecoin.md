# Stablecoin Card — DAI

> Real card for DAI (Sky / MakerDAO). Research-layer artifact — NOT runtime data. **No specifics
> invented**; unsourced = `requires data verification`. Cross-refs: docs/13, docs/12, docs/38, docs/14.

## Identity
- **stablecoin_id:** `STC-DAI-001`
- **symbol:** `DAI`
- **issuer:** `Sky (formerly MakerDAO) — decentralized protocol`

## Backing & transparency (the due-diligence core)
- **backing_type:** `hybrid` — crypto-overcollateralized (ETH/LST + other vaults) PLUS significant RWA + stablecoin (USDC/USDS-PSM) backing. The USDC/RWA share is the key non-obvious dependency.
- **reserve_transparency:** `on-chain collateral is transparent; RWA legs are partial` — `requires verification` of current composition
- **attestations:** `[]`  <!-- on-chain collateral verifiable; RWA legs rely on off-chain reporting — verify -->
- **redemption_mechanism:** `PSM (Peg Stability Module) 1:1 vs USDC + vault CDP redemption; DEX liquidity`

## Liquidity & market structure (never presented without a last-verified date)
- **liquidity_profile:** `Deep on-chain (Curve/DEX) — exact depth requires data verification`
- **exchange_depth:** `TBD — requires data verification`
- **market_cap:** `~$4.7B` — **verified 2026-07-02** (DeFiLlama; the original crypto-collateralized stablecoin, now alongside Sky's newer USDS ~$8.7B which is the strategic successor). [L2]
- **circulating_supply:** `~$4.7B` (2026)
- **top_holder_concentration:** `TBD — requires data verification`

## Peg & control risk
- **depeg_history:** `[{date: "2020-03 (Black Thursday)", depth: "vault liquidation stress (verify)", cause: "ETH crash + gas spike broke liquidations", recovery: "protocol changes"}, {date: "2023-03 (USDC/SVB)", depth: "DAI de-pegged WITH USDC due to PSM exposure (verify)", cause: "USDC backing via PSM", recovery: "with USDC"}]`
- **blacklist_freeze_risk:** `no_freeze at the DAI-token level (DAI itself is not freezable), BUT indirectly exposed to USDC freeze via PSM backing` — key nuance
- **regulatory_risk:** `Lower direct issuer risk (decentralized), but INHERITS USDC/RWA regulatory exposure through its backing`
- **jurisdiction:** `Decentralized protocol (Sky) — backing legs touch multiple jurisdictions (RWA)`

## Usage & dependencies
- **chains:** `["Ethereum (native)", "+ bridged — verify"]`
- **main_use_cases:** `["collateral", "settlement", "lending unit", "LP pair", "sDAI yield wrapper"]`
- **key_dependencies:** `["USDC (PSM backing — DAI's peg partly rides USDC's peg)", "RWA custodians/counterparties", "collateral (ETH/LST) health", "oracle feeds for liquidations"]`

## Risk assessment (advisory; cites dfb overlay — never a hard gate)
- **risk_score:** `TBD — requires Risk Scoring v2 run (docs/14). Qualitatively LOW-MODERATE: no token-level freeze, but the USDC/RWA-backing dependency means DAI is NOT decoupled from USDC's tail (2023 proved this).`
- **max_allocation_recommendation:** `Advisory — bounded by RiskPolicy caps; note the USDC-correlation when sizing alongside USDC.`
- **monitoring_requirements:** `["peg", "PSM/USDC backing share", "RWA-leg disclosures", "collateral health", "governance (Sky) parameter changes"]`
- **emergency_exit_triggers:** `["peg deviation", "USDC depeg (correlated)", "RWA-leg impairment", "collateral crash / liquidation stress", "governance risk-parameter shock"]`

## Provenance
- **notes:** `DAI's decentralization reduces token-level freeze risk but its PSM/USDC + RWA backing means it CORRELATES with USDC's tail (demonstrated 2023-03). Treat DAI+USDC as partially correlated for concentration. Backing composition + RWA legs = requires verification. sDAI is the yield wrapper (separate).`
- **created_at:** `2026-07-02`
- **updated_at:** `2026-07-02`

---

### Review checklist (docs/13 §5)
- [x] `backing_type`, `blacklist_freeze_risk` (with USDC-PSM nuance), `depeg_history`, `emergency_exit_triggers` filled
- [ ] `reserve_transparency` — current USDC/RWA backing share sourced with a date — **pending (load-bearing)**
- [ ] `market_cap` / `circulating_supply` / liquidity sourced with a date — pending
- [ ] `risk_score` + `max_allocation_recommendation` cite dfb overlay / RiskPolicy caps + USDC-correlation — pending
