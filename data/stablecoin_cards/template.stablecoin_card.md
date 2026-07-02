# Stablecoin Card — <SYMBOL>

> Fill-in template mirroring `schema.stablecoin_card.json`. One card per stablecoin.
> Research-layer artifact — NOT runtime data, never read by RiskPolicy or execution.
> **Never invent market-cap/supply/depth. Unknown numbers = `TBD — requires data verification`
> (with a last-verified date once sourced).**
> Cross-refs: docs/13 (this system), docs/12 (Protocol Cards), docs/38 (stablecoin yield engine),
> docs/14 (advisory Risk Scoring v2), docs/02 (existing stablecoin-bearing adapters + dfb overlay).

## Identity
- **stablecoin_id:** `STC-XXXX`  <!-- stable unique id, never reused -->
- **symbol:** `<USDC|sUSDe|USDS|...>`
- **issuer:** `<Circle|Ethena|Sky|...>`

## Backing & transparency (the due-diligence core)
- **backing_type:** `<fiat_backed|crypto_overcollateralized|rwa_backed|synthetic_delta_neutral|algorithmic|hybrid|unknown>`
- **reserve_transparency:** `<full_attestation|partial|opaque|unknown>`
- **attestations:** `[]`  <!-- [{firm, cadence, last_date}]; empty = none found, state so explicitly -->
- **redemption_mechanism:** `<direct issuer redemption | AMM only | queue | gated>`

## Liquidity & market structure (never presented without a last-verified date)
- **liquidity_profile:** `TBD — requires data verification`  <!-- on-chain + CEX depth summary -->
- **exchange_depth:** `TBD — requires data verification`  <!-- depth for exit-by-size -->
- **market_cap:** `TBD — requires data verification`  <!-- USD; cite source + date -->
- **circulating_supply:** `TBD — requires data verification`  <!-- units -->
- **top_holder_concentration:** `TBD — requires data verification`  <!-- run-risk proxy -->

## Peg & control risk
- **depeg_history:** `[]`  <!-- [{date, depth, duration, cause, recovery}]; empty = none known, state so -->
- **blacklist_freeze_risk:** `<can_freeze_and_blacklist|freeze_only|no_freeze|unknown>`
- **regulatory_risk:** `<legal/sanctions/securities surface>`
- **jurisdiction:** `<issuer jurisdiction>`

## Usage & dependencies
- **chains:** `[]`  <!-- native / bridged -->
- **main_use_cases:** `[]`  <!-- collateral, settlement, yield unit, LP pair -->
- **key_dependencies:** `[]`  <!-- oracle, bridge, perp funding leg (synthetics), RWA custodian -->

## Risk assessment (advisory; cites dfb overlay — never a hard gate)
- **risk_score:** `TBD`  <!-- 0–100, higher = riskier (docs/14); advisory only -->
- **max_allocation_recommendation:** `TBD — requires data verification`  <!-- % of book; never exceeds RiskPolicy caps -->
- **monitoring_requirements:** `[]`  <!-- peg, reserve attestation cadence, funding (synthetics), redemption queue -->
- **emergency_exit_triggers:** `[]`  <!-- depeg beyond threshold, reserve doubt, freeze/blacklist action, redemption halt, funding flip -->

## Provenance
- **notes:** `<reviewer notes>`
- **created_at:** `<ISO-8601 UTC>`
- **updated_at:** `<ISO-8601 UTC>`

---

### Review checklist (docs/13 §5)
- [ ] `backing_type`, `reserve_transparency`, `depeg_history`, `blacklist_freeze_risk`,
      `emergency_exit_triggers` filled substantively (unknown there is a finding, not a blank)
- [ ] `market_cap` / `circulating_supply` / liquidity fields sourced with a last-verified date, else `TBD`
- [ ] `risk_score` + `max_allocation_recommendation` cite the dfb overlay / RiskPolicy caps (advisory only)
