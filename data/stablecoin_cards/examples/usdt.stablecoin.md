# Stablecoin Card — USDT

> Real card for Tether USD. Research-layer artifact — NOT runtime data. **No market-cap/supply/depth
> invented**; unsourced = `requires data verification`. Cross-refs: docs/13, docs/12, docs/38, docs/14.

## Identity
- **stablecoin_id:** `STC-USDT-001`
- **symbol:** `USDT`
- **issuer:** `Tether`

## Backing & transparency (the due-diligence core)
- **backing_type:** `fiat_backed + mixed` — **sourced (verified 2026-07-02):** ~80% US Treasury bills + overnight repo + cash, **PLUS ~$8B gold and ~$7B BTC** + secured loans/other (Q1-2026). The **gold + BTC (~$15B non-fiat) is a real risk-relevant nuance** — USDT is NOT purely cash/T-bill backed. Q1-2026 BDO report: reserves **$191.77B** vs liabilities **$183.54B** → **~$8.23B excess**.
- **reserve_transparency:** **QUARTERLY attestation (sourced 2026-07-02)** — BDO ISAE 3000 (Revised) assurance report, point-in-time, **NOT a full GAAS audit**. Weaker cadence than USDC's monthly (quarterly vs monthly) + the mixed gold/BTC reserve.
- **attestations:** `[{firm: "BDO (BDO Italia)", cadence: "quarterly", type: "ISAE 3000 (Revised) assurance (point-in-time, not full audit)", last_seen: "Q1 2026 (as-of Mar 31 2026)"}]` — **verified 2026-07-02 [L2]**
- **redemption_mechanism:** `direct issuer redemption for large KYC'd accounts (minimums); deep secondary CEX/on-chain liquidity for others`

## Liquidity & market structure (never presented without a last-verified date)
- **liquidity_profile:** `The most-traded stablecoin globally (deepest CEX liquidity) — exact depth requires data verification`
- **exchange_depth:** `TBD — requires data verification`
- **market_cap:** `~$188B` — **verified 2026-07-02** (CoinMarketCap, June 2026; the LARGEST stablecoin, ~58% of total stablecoin supply, >2× USDC). [L2]
- **circulating_supply:** `~$189B` (Q1 2026)
- **top_holder_concentration:** `TBD — requires data verification`

## Peg & control risk
- **depeg_history:** `[{date: "multiple minor (e.g. 2022 briefly ~$0.95 intraday on some venues)", depth: "requires verification", duration: "brief", cause: "market stress / confidence episodes", recovery: "repegged"}]`  <!-- verify exact events/figures -->
- **blacklist_freeze_risk:** `can_freeze_and_blacklist` — Tether freezes addresses (has done so for law enforcement)
- **regulatory_risk:** `Moderate–elevated — offshore issuer, historically more regulatory scrutiny than Circle/USDC; verify current status`
- **jurisdiction:** `Offshore (Tether — British Virgin Islands / Hong Kong; verify)`

## Usage & dependencies
- **chains:** `["Ethereum", "Tron", "+ many (native + bridged) — verify which the desk uses"]`
- **main_use_cases:** `["settlement", "CEX quote asset", "collateral", "lending unit", "LP pair"]`
- **key_dependencies:** `["Tether solvency + reserve quality", "banking/custody partners", "regulatory regime"]`

## Risk assessment (advisory; cites dfb overlay — never a hard gate)
- **risk_score:** `TBD — requires Risk Scoring v2 run (docs/14). Qualitatively LOW-MODERATE: unmatched liquidity, but weaker reserve transparency + offshore/regulatory surface vs USDC → a higher stablecoin_risk than USDC.`
- **max_allocation_recommendation:** `Advisory — bounded by RiskPolicy caps; transparency gap argues for a sub-cap vs USDC. Exact % requires verification.`
- **monitoring_requirements:** `["peg", "attestation cadence/quality", "regulatory news", "freeze actions", "reserve-composition disclosures"]`
- **emergency_exit_triggers:** `["peg deviation beyond threshold", "reserve/transparency doubt", "regulatory action", "freeze on desk addresses", "redemption friction"]`

## Provenance
- **notes:** `USDT is the deepest-liquidity stablecoin but with weaker reserve transparency + offshore/regulatory surface than USDC — a real, accepted risk differential, not a disqualifier. Backing_type + freeze capability stated (publicly certain); market-cap/supply/depth/attestation specifics = requires verification, not invented.`
- **created_at:** `2026-07-02`
- **updated_at:** `2026-07-02`

---

### Review checklist (docs/13 §5)
- [x] `backing_type`, `blacklist_freeze_risk`, `emergency_exit_triggers` filled; `depeg_history` documented (verify figures)
- [x] `reserve_transparency` attestation firm/cadence SOURCED — **BDO Italia, quarterly ISAE 3000, last Q1-2026 (verified 2026-07-02); weaker cadence + gold/BTC reserve vs USDC**
- [ ] `market_cap` / `circulating_supply` / liquidity sourced with a date — pending
- [ ] `risk_score` + `max_allocation_recommendation` cite dfb overlay / RiskPolicy caps — pending
