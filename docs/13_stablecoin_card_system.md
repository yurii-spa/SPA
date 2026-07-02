# 13 — Stablecoin Card System (§20)

**Status:** research-layer documentation. No runtime code, RiskPolicy, dashboard, deploy, or
existing files are modified by this document. **Tone:** institutional, evidence-first. **Market-cap /
supply / depth numbers in any card are placeholders marked "TBD — requires data verification" until
sourced with a last-verified date.**

Cross-references: `docs/12_protocol_card_system.md` (sibling due-diligence for protocols),
`docs/11_strategy_card_system.md` (Strategy Cards reference these via `stablecoin_risk`),
`docs/38_stablecoin_yield_engine.md` (stablecoin yield engine — Priority 2; these cards are its
due-diligence layer), `docs/14_risk_scoring_v2.md` (advisory scorecard), `docs/06_spa_core_invariants.md`
(hard invariants preserved), `data/stablecoin_cards/` (schema + template + README).

> Note: `docs/38` is a Priority-2 document. Where it does not yet exist, this document is
> forward-referencing it; the cross-reference is intentional and does not depend on 38 being present.

---

## 1. Purpose

A **Stablecoin Card** is a single, comparable, auditable due-diligence record for one stablecoin SPA
can hold or route yield through (USDC, USDT, DAI, sUSDe, USDS, and RWA-backed units). It exists so
that every stablecoin a Strategy Card touches is described in the *same* vocabulary: what backs it,
how transparent the reserves are, how it redeems, how deep its liquidity is, whether it can be frozen
or blacklisted, its depeg history, and how much of the book may safely sit in it.

Stablecoin risk is the quietest and most correlated risk the desk carries — a depeg or freeze hits
every position that touches the unit at once. The Stablecoin Card makes that due-diligence explicit,
comparable, and promotion-gating, so it is:

- **Comparable** — every stablecoin answers the same fields, so a fiat-backed unit (USDC) and a
  synthetic/yield-bearing unit (sUSDe) can be laid side by side.
- **Auditable** — a future reviewer (or external IC) can reconstruct *why* a stablecoin was trusted,
  capped, or refused, from the card alone.
- **Promotion-gating** — if any stablecoin is involved in a Strategy Card, a reviewed Stablecoin Card
  is required before that strategy can promote to Enhanced / MaxYield (`docs/11 §5`).

A Stablecoin Card is a **research-layer artifact**. Cards live under `data/stablecoin_cards/`
(research data), never in runtime `data/*.json`. A card **describes** a stablecoin; it never
**executes** against one and is never read by the deterministic RiskPolicy or the execution path.

---

## 2. Relationship to what already exists (do not duplicate)

Stablecoin due-diligence is today **implicit** in the adapters (`spa_core/adapters/` — e.g. Ethena
sUSDe, Sky sUSDS, Ondo USDY units feed through them) and the `spa_core/dfb/` risk overlay. The card
system **formalizes and unifies** that:

| Existing surface | What the card reuses / references |
|---|---|
| `spa_core/adapters/` (stablecoin-bearing adapters + DeFiLlama feed) | `market_cap`, `circulating_supply`, `chains` inputs — cited with a last-verified date, never hardcoded |
| `spa_core/dfb/` risk overlay | `depeg_history`, `liquidity_profile`, advisory `risk_score` inputs — the card **cites** the overlay, never re-derives it |
| `docs/38` stablecoin yield engine (Priority 2) | the engine consumes these cards as its due-diligence layer |
| `spa_core/redteam/` | `depeg_history`, `blacklist_freeze_risk`, `emergency_exit_triggers` inputs |

**Rule:** the card is a *presentation and record* layer. Where a value can be produced by an existing
module (a market cap, an overlay depeg signal), the card **cites** it with a source + last-verified
date and does not invent a parallel number.

---

## 3. Full field list

Fields are grouped for readability; the authoritative machine schema is
`data/stablecoin_cards/schema.stablecoin_card.json` and the fill-in template is
`data/stablecoin_cards/template.stablecoin_card.md`. All numeric market-cap / supply / depth fields
are placeholders (`TBD — requires data verification`) until sourced with a last-verified date.

### 3.1 Identity

| Field | Type | Meaning |
|---|---|---|
| `stablecoin_id` | string | Stable unique id (e.g. `STC-0001`). Never reused. |
| `symbol` | string | Ticker (e.g. `USDC`, `sUSDe`, `USDS`). |
| `issuer` | string | Issuing entity / protocol (e.g. `Circle`, `Ethena`, `Sky`). |

### 3.2 Backing & transparency (the due-diligence core)

| Field | Type | Meaning |
|---|---|---|
| `backing_type` | enum | `fiat_backed` \| `crypto_overcollateralized` \| `rwa_backed` \| `synthetic_delta_neutral` \| `algorithmic` \| `hybrid` \| `unknown`. |
| `reserve_transparency` | enum | `full_attestation` \| `partial` \| `opaque` \| `unknown`. How visible the reserves are. |
| `attestations` | array | Attestation / audit records: firm, cadence, last date. Empty = none found (state so explicitly). |
| `redemption_mechanism` | string | How a holder redeems to the underlying (direct issuer redemption, AMM only, queue, gated). |

### 3.3 Liquidity & market structure (never presented without a last-verified date)

| Field | Type | Meaning |
|---|---|---|
| `liquidity_profile` | string | On-chain + CEX liquidity depth summary. **TBD — requires data verification.** |
| `exchange_depth` | string | Depth on major venues / DEX pools (for exit-by-size). TBD until sourced. |
| `market_cap` | number\|null | Market cap (USD). TBD until sourced; cite source + date. |
| `circulating_supply` | number\|null | Circulating supply (units). TBD until sourced. |
| `top_holder_concentration` | string | Concentration of supply in top holders (a run-risk proxy). TBD until sourced. |

### 3.4 Peg & control risk

| Field | Type | Meaning |
|---|---|---|
| `depeg_history` | array | Past depeg events: date, depth, duration, cause, recovery. Empty = none known (state so). |
| `blacklist_freeze_risk` | enum | `can_freeze_and_blacklist` \| `freeze_only` \| `no_freeze` \| `unknown`. Whether the issuer can freeze/blacklist holdings. |
| `regulatory_risk` | string | Legal / sanctions / securities surface for this unit. |
| `jurisdiction` | string | Issuer jurisdiction (regulatory exposure). |

### 3.5 Usage & dependencies

| Field | Type | Meaning |
|---|---|---|
| `chains` | array | Chains the stablecoin is native / bridged on. |
| `main_use_cases` | array | Primary use cases (collateral, settlement, yield unit, LP pair). |
| `key_dependencies` | array | External things that must hold (an oracle, a bridge, a perp funding leg for synthetics, an RWA custodian). |

### 3.6 Risk assessment (advisory; feeds Strategy Cards)

| Field | Type | Meaning |
|---|---|---|
| `risk_score` | 0–100 | Advisory overall stablecoin risk (higher = riskier per `docs/14`). **Advisory only** — cites `dfb` overlay, never a hard gate. |
| `max_allocation_recommendation` | number\|null | Advisory ceiling (% of book) in this unit. **Never exceeds / overrides RiskPolicy caps** (`docs/06` A.1). TBD until sourced. |
| `monitoring_requirements` | array | What must be monitored (peg, reserves attestation cadence, funding for synthetics, redemption queue). |
| `emergency_exit_triggers` | array | Conditions that force exiting the unit (depeg beyond threshold, reserve doubt, freeze/blacklist action, redemption halt, funding flip for synthetics). |

### 3.7 Provenance

| Field | Type | Meaning |
|---|---|---|
| `notes` | string | Free-text reviewer notes. |
| `created_at` | ISO-8601 | Creation timestamp (UTC). |
| `updated_at` | ISO-8601 | Last update timestamp (UTC). |

---

## 4. Where cards live

- Directory: `data/stablecoin_cards/` (research layer, **not** runtime `data/*.json`).
- Schema: `data/stablecoin_cards/schema.stablecoin_card.json` (JSON Schema draft 2020-12).
- Template: `data/stablecoin_cards/template.stablecoin_card.md`.
- README: `data/stablecoin_cards/README.md`.
- One card per stablecoin, as a JSON file conforming to the schema and/or a markdown card from the
  template. `stablecoin_id` is the stable key.

---

## 5. Review discipline

- If any stablecoin is involved in a Strategy Card, a reviewed Stablecoin Card is required before
  that strategy can promote to Enhanced / MaxYield (`docs/11 §5`, promotion gate "Stablecoin review").
- `backing_type`, `reserve_transparency`, `depeg_history`, `blacklist_freeze_risk`, and
  `emergency_exit_triggers` are the load-bearing trust fields — an empty/unknown value there is a
  finding, not a blank.
- `risk_score` and `max_allocation_recommendation` are **advisory** and cite the `dfb` overlay /
  RiskPolicy caps; they never replace the deterministic RiskPolicy or wire into execution.

---

## 6. Invariants this document preserves

- The deterministic RiskPolicy remains the sole hard execution gate; card scores and allocation
  recommendations are advisory records (`docs/06` A.1–A.4, invariants 14 & 17).
- No LLM is placed in the risk/execution/monitoring/kill path by the card system.
- No market-cap / supply / depth number is presented as verified without a last-verified date and
  source; unknowns are `TBD — requires data verification`.
- Cards reuse the existing adapter + `dfb` overlay + red-team modules rather than duplicating their
  math.
