# Stablecoin Cards

A **Stablecoin Card** is a single, comparable, auditable due-diligence record for one stablecoin SPA
can hold or route yield through (USDC, USDT, DAI, sUSDe, USDS, RWA-backed units). Every stablecoin a
Strategy Card touches is described in the same vocabulary: backing, reserve transparency, redemption,
liquidity depth, depeg history, freeze/blacklist risk, and how much of the book may safely sit in it.

Full spec: **`docs/13_stablecoin_card_system.md`**.

## Where cards live (research layer, NOT runtime)

This directory (`data/stablecoin_cards/`) is a **research-layer** location. Cards are **not** runtime
`data/*.json` state, are **not** read by the deterministic RiskPolicy, and are **not** on the
execution path. A card *describes* a stablecoin; it never *executes* against one. The card formalizes
due-diligence today implicit across the stablecoin-bearing adapters (`spa_core/adapters/`) and the
`spa_core/dfb/` risk overlay; it is the due-diligence layer for the stablecoin yield engine
(`docs/38`, Priority 2).

## Contents

| File | Purpose |
|---|---|
| `schema.stablecoin_card.json` | JSON Schema (draft 2020-12) — authoritative field/type/enum definition. Verified to parse as valid JSON. |
| `template.stablecoin_card.md` | Fill-in markdown template mirroring the schema, one line per field, unknown numbers as `TBD — requires data verification`. |
| `README.md` | This file. |

## Lifecycle

1. **Create** a card (JSON per schema and/or markdown from the template) when a strategy under review
   holds or routes through a stablecoin. `stablecoin_id` (`STC-XXXX`) is the stable key.
2. **Review** the load-bearing trust fields: `backing_type`, `reserve_transparency`, `depeg_history`,
   `blacklist_freeze_risk`, `emergency_exit_triggers` — an unknown there is a finding, not a blank.
3. **Gate** — if any stablecoin is involved in a Strategy Card, a reviewed Stablecoin Card is required
   before that strategy can promote to Enhanced / MaxYield (`docs/11 §5`).
4. **Re-review** per `monitoring_requirements`; bump `updated_at` on every material edit.

## Placeholder rule

- **Never invent market-cap / supply / depth.** Any unknown number is `TBD — requires data
  verification` until sourced with a source + last-verified date.
- Advisory `risk_score` and `max_allocation_recommendation` cite the `dfb` overlay / RiskPolicy caps
  (`docs/14`, `docs/06` A.1); they never replace the deterministic RiskPolicy or wire into execution.
