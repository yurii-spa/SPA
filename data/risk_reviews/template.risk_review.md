# Risk Review — <STRATEGY NAME>

> Fill-in advisory risk review (§38 reporting set, Risk Scoring v2). Research-layer artifact —
> **advisory only; never an execution gate (ADR-YL-004).** The deterministic RiskPolicy
> (`spa_core/risk/policy.py`, v1.0) remains the sole hard gate. **Never invent APY/TVL. Unknown =
> `TBD — requires verification`.** Cross-refs: `docs/14_risk_scoring_v2.md`,
> `docs/11_strategy_card_system.md` (§3.7), `docs/06_spa_core_invariants.md`.

- **review_id:** `RV-XXXX`  ·  **strategy_id:** `SC-XXXX`
- **reviewer:** `<name>`  ·  **date:** `<ISO-8601 UTC>`  ·  **status:** `<draft|final>`

## 1. Advisory scores (0–100; higher risk_score = riskier)
| Score | Value | Band (green/yellow/red) | Notes |
|---|---|---|---|
| risk_score | `TBD` | | |
| liquidity_score | `TBD` | | |
| complexity_score | `TBD` | | |
| confidence_score | `TBD` | | |

## 2. Triggers fired
- [ ] hard-reject sub-score  <!-- blocks promotion decision; never touches execution -->
- [ ] human-review required
- [ ] red-team required (leverage/credit/counterparty/bridge/opaque/new-stablecoin/lockup/options/basis)

## 3. Risk dimensions (qualitative)
| Dimension | Assessment | Severity (L/M/H) |
|---|---|---|
| smart_contract_risk | | |
| stablecoin_risk (depeg/redemption/reserve) | | |
| counterparty_risk (CEX/issuer/MM) | | |
| bridge_risk | | |
| oracle_risk | | |
| liquidation_risk | | |
| regulatory_risk | | |
| operational_risk | | |
| concentration_risk | | |
| correlation_risk (to BTC/ETH/rates/book) | | |
| market_regime_risk | | |

## 4. Key dependencies & assumptions
- **key_dependencies:** `[]`  <!-- a peg, a CEX leg, an oracle, an incentive program -->
- **assumptions:** `[]`  <!-- the most fragile assumption goes first -->

## 5. Liquidity / exit review
- withdrawal_time / lockup: `<...>`
- exit-liquidity-by-size: `<cite dfb/risk_overlay.py; do not synthesize>`

## 6. Interaction with deterministic RiskPolicy
- RiskPolicy caps that bind (TVL ≥ $5M, per-protocol 40% T1 / 20% T2, T2 ≤ 50%, APY 1–30%, cash ≥ 5%): `<...>`
- Two-tier kill-switch relevance (SOFT −5% / HARD −10%): `<...>`
> This review does not modify or override RiskPolicy; it is advisory input to a human decision.

## 7. Recommendation (advisory)
- **verdict:** `<green | yellow (human-review) | red (hard-reject advisory)>`
- **conditions for advancing:** `<...>`
- **review_frequency:** `<weekly|monthly>`
