# Strategy Cards

A **Strategy Card** is a single, comparable, auditable record for one yield strategy. Every candidate
strategy — before it can touch any product line — is described in the same vocabulary: where the yield
comes from, who pays it, why it can disappear, what can go wrong, what evidence supports the APY, how
it scores on the advisory Risk Scoring v2, and what it is approved for.

Full spec: **`docs/11_strategy_card_system.md`**.

## Where cards live (research layer, NOT runtime)

This directory (`data/strategy_cards/`) is a **research-layer** location. Cards are **not** runtime
`data/*.json` state, are **not** read by the deterministic RiskPolicy, and are **not** on the
execution path. A card *describes* a strategy; it never *executes* one.

## Contents

| File | Purpose |
|---|---|
| `schema.strategy_card.json` | JSON Schema (draft 2020-12) — the authoritative field/type/enum definition. Verified to parse as valid JSON. |
| `template.strategy_card.md` | Fill-in markdown template mirroring the schema, with every field, a one-line hint, and unknown numbers as `TBD — requires verification`. |
| `README.md` | This file. |
| `examples/` | Worked example cards. **Empty at scaffolding time — populated in Priority 2.** |

## Lifecycle (docs/07)

```
idea → research → rejected
              ↘ paper_testing → paper_passed → small_capital_testing → small_capital_passed
                    → approved_for_{preserve,core,enhanced,max_yield} → frozen | retired
```

A card cannot reach **Enhanced / MaxYield** without all promotion gates satisfied: clear yield source,
APY evidence level (docs/37), protocol review, stablecoin review (if applicable), risk review
(advisory Risk Scoring v2, docs/14), red-team review, capacity estimate, liquidity review, paper
testing, and **human approval**. See `docs/11 §5`. No card self-promotes.

## Honesty rules

- **Never invent APY / TVL / capacity.** Any unknown number is `TBD — requires verification` until
  sourced with an evidence level and a last-verified date.
- Advisory scores (`risk_score`, `liquidity_score`, `complexity_score`, `confidence_score`) are
  **advisory only** — they never replace the deterministic RiskPolicy and are never wired to
  execution (Risk Scoring v2, docs/14; ADR-YL-004).
- Cards reuse the existing research/risk modules (`spa_core/strategy_lab/*`, `spa_core/dfb/risk_overlay.py`,
  `spa_core/risk/scoring_engine.py`, `spa_core/tournament/*`, `spa_core/redteam/`) rather than
  re-deriving their numbers.
