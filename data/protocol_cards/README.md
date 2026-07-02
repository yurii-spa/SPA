# Protocol Cards

A **Protocol Card** is a single, comparable, auditable due-diligence record for one protocol SPA can
depend on (a lending market, a vault, an LP venue, an RWA issuer surface). Every protocol a Strategy
Card touches is described in the same vocabulary: size, admin keys, oracle/bridge dependencies,
exploit history, yield sustainability, and how much of the book may safely sit on it.

Full spec: **`docs/12_protocol_card_system.md`**.

## Where cards live (research layer, NOT runtime)

This directory (`data/protocol_cards/`) is a **research-layer** location. Cards are **not** runtime
`data/*.json` state, are **not** read by the deterministic RiskPolicy, and are **not** on the
execution path. A card *describes* a protocol; it never *executes* against one. The card formalizes
due-diligence today implicit across the 35 read-only adapters (`spa_core/adapters/` `ADAPTER_REGISTRY`)
and the `spa_core/dfb/` risk overlay.

## Contents

| File | Purpose |
|---|---|
| `schema.protocol_card.json` | JSON Schema (draft 2020-12) — authoritative field/type/enum definition. Verified to parse as valid JSON. |
| `template.protocol_card.md` | Fill-in markdown template mirroring the schema, one line per field, unknown numbers as `TBD — requires data verification`. |
| `README.md` | This file. |

## Lifecycle

1. **Create** a card (JSON per schema and/or markdown from the template) when a strategy under review
   depends on a protocol. `protocol_id` (`PC-XXXX`) is the stable key; map it to the adapter key where
   one exists.
2. **Review** the load-bearing trust fields: `admin_keys`, `upgradeability`, `oracle_dependencies`,
   `exploit_history`, `emergency_triggers` — an unknown there is a finding, not a blank.
3. **Gate** — every protocol in a Strategy Card's `protocols_used` must have a reviewed Protocol Card
   before that strategy can promote to Enhanced / MaxYield (`docs/11 §5`).
4. **Re-review** at `monitoring_frequency`; bump `updated_at` on every material edit.

## Placeholder rule

- **Never invent TVL / revenue / user-activity.** Any unknown number is `TBD — requires data
  verification` until sourced with a source + last-verified date.
- Advisory `risk_score` and `max_allocation_recommendation` cite the `dfb` overlay / RiskPolicy caps
  (`docs/14`, `docs/06` A.1); they never replace the deterministic RiskPolicy or wire into execution.
