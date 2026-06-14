# ADR-001: Initial Risk Policy v1.0 — Stable Lending Core

| Field            | Value                                    |
|------------------|------------------------------------------|
| **Date**         | 2026-05-20                               |
| **Status**       | Approved                                 |
| **Author**       | Yurii (Owner)                            |
| **Approved by**  | Yurii (Owner) on 2026-05-20              |
| **Policy ver.**  | v1.0                                     |
| **ADR number**   | ADR-001                                  |

---

## Context

SPA (Smart Passive Aggregator) launched paper trading on 2026-05-20 with a $100,000 virtual portfolio
targeting stablecoin yield via T1 (Aave, Compound, Morpho) and T2 (Yearn, Maple, Euler) lending protocols.

Before any agent could open a position, a deterministic risk policy was required to enforce capital
preservation constraints. This ADR documents the design rationale for every parameter in `RiskConfig v1.0`.

The policy had to satisfy three constraints:
1. Be conservative enough for a first-ever live deployment of an automated strategy.
2. Allow meaningful yield capture across 4–7 protocols simultaneously.
3. Be fully deterministic — no LLM override possible.

---

## Decision

Adopt `RiskConfig v1.0` as defined in `spa_core/risk/policy.py` with the following parameters:

| Parameter                      | Value  | Category              |
|-------------------------------|--------|-----------------------|
| `max_concentration_t1`        | 40%    | Concentration limit   |
| `max_concentration_t2`        | 20%    | Concentration limit   |
| `max_single_protocol`         | 40%    | Hard cap              |
| `max_total_t2_allocation`     | 35%    | Category limit        |
| `max_apy_for_new_position`    | 30%    | Circuit breaker       |
| `min_apy_for_new_position`    | 1%     | Circuit breaker       |
| `min_tvl_usd`                 | $5M    | Liquidity gate        |
| `max_drawdown_stop`           | 5%     | Kill switch           |
| `max_single_position_drawdown`| 3%     | Position stop         |
| `var_confidence`              | 95%    | VaR parameter         |
| `var_horizon_days`            | 7      | VaR parameter         |
| `max_var_pct`                 | 5%     | VaR limit             |
| `min_cash_pct`                | 5%     | Cash buffer           |

---

## Rationale

### T1 concentration limit: 40%

Aave v3, Compound v3, and Morpho are battle-tested protocols with multi-billion TVL and long audit
histories. A 40% single-protocol cap allows meaningful position sizing (e.g., $40K in Aave on a $100K
portfolio) while ensuring no single protocol failure wipes out the portfolio. The 40% cap is consistent
with institutional DeFi risk frameworks that treat T1 lending as near-equivalent to money-market instruments.

### T2 concentration limit: 20%

T2 protocols (Yearn v3 vaults, Maple Finance, Euler v2) carry additional smart contract risk from
strategy complexity (Yearn), credit risk from institutional borrowers (Maple), and protocol novelty
(Euler post-exploit recovery). A 20% cap per protocol limits blast radius from any single T2 failure
to ≤ 20% of portfolio. Combined with the 35% aggregate T2 cap, worst-case T2 total loss is bounded.

### T2 aggregate limit: 35%

This ensures at least 65% of deployed capital sits in T1 protocols at all times, maintaining a
conservative overall risk posture. The 35% figure leaves room to capture T2 yield uplift (typically
+1–4% APY over T1) while keeping the portfolio anchored in safer assets.

### 5% drawdown kill switch

A 5% portfolio drawdown in stablecoin lending is anomalous — it would indicate either: (a) a smart
contract exploit, (b) severe slippage/liquidation event, or (c) data error. The 5% trigger is set
low enough to catch these scenarios early while being above normal mark-to-market noise. At $100K
paper capital, this is a $5,000 loss threshold — significant enough to trigger immediate review.

This matches the conservative posture recommended in the SPA Risk Policy v0.3 doc
(`SPA/01_Docs/Risk_Policy_v0.3.md`).

### APY range: 1%–30%

**Minimum 1% APY:** Below 1%, the yield does not justify gas cost, smart contract risk, or opportunity
cost vs. a T-bill. Any protocol showing <1% APY either has a data quality issue or has structurally
broken incentives — neither is worth entering.

**Maximum 30% APY:** Stablecoin yields above 30% are structurally unsustainable and almost always
indicate: (a) temporary liquidity mining that will disappear, (b) inflated rewards with hidden token
risk, or (c) elevated credit risk. The 30% cap prevents the strategy from chasing unsustainable
yields that would invert when the incentive program ends. This is validated by historical data —
Aave/Compound yields have remained 2–12% across market cycles.

### $5M minimum TVL

TVL under $5M creates meaningful slippage risk even for a $100K portfolio ($5K position = 0.1% of
$5M TVL — manageable, but pools smaller than this create withdrawal risk). The $5M floor also
serves as a basic liquidity health check: protocols that cannot attract $5M in liquidity are either
new (untested) or losing trust. All 7 whitelisted protocols have TVL far above this threshold
(Aave: $138M+, Compound: $40M+, Morpho: $100M+).

### 5% cash buffer

The cash buffer serves three functions:
1. **Rebalancing capacity:** Always have funds available to capture opportunities without forced sells.
2. **Gas/slippage reserve:** Paper trading simulates this; live trading needs a float for transactions.
3. **Circuit breaker runway:** If the kill switch triggers, immediate position unwinding is possible
   without needing to close positions to raise cash.

5% on a $100K portfolio = $5,000 always liquid. This is consistent with institutional practice of
maintaining a 3–10% cash buffer in actively managed yield strategies.

---

## Consequences

### Positive
- Conservative parameters protect the paper portfolio during the validation phase.
- Deterministic enforcement means no agent can rationalize a policy override.
- Clear numeric limits make monitoring and alerting straightforward.
- The version + changelog system enables clean rollbacks if parameters prove too restrictive.

### Negative / Risks
- The 40% T1 / 20% T2 caps may leave capital idle if only a few protocols pass all screens.
- The 30% APY ceiling may cause the strategy to miss genuinely high-yield windows.
- The 5% kill switch may trigger on temporary mark-to-market dips before recovering.

### Neutral
- 8-week paper testing period (2026-05-20 → 2026-07-15) delays live deployment — intentional.
- The 1% minimum APY floor will rarely bind in the current environment (all target protocols yield ≥ 3%).

---

## Paper Test Plan

| Item               | Value                                             |
|--------------------|---------------------------------------------------|
| Start date         | 2026-05-20                                        |
| Minimum duration   | 8 weeks (56 days)                                 |
| Go-live target     | 2026-07-15                                        |
| Capital            | $100,000 virtual (paper)                          |
| Success criteria   | Sharpe > 0.5, max DD < 3%, no policy violations, positive total return |
| Monitoring         | Daily: APY changes, concentration drift, cash buffer; Weekly: PnL summary |

**Paper Test Status:** ACTIVE (started 2026-05-20, running)

---

## Paper Test Results

_To be filled in after the paper test period ends (~2026-07-15)._

| Metric            | Result | Pass? |
|-------------------|--------|-------|
| Sharpe ratio      | TBD    | TBD   |
| Max drawdown      | TBD    | TBD   |
| Total return      | TBD    | TBD   |
| Policy violations | TBD    | TBD   |
| Avg APY captured  | TBD    | TBD   |

---

## Rollback Plan

If v1.0 parameters prove incorrect and need to be reverted or replaced:

1. Create a new ADR (ADR-002+) documenting the failure mode and proposed fix.
2. Snapshot v1.0 already exists at: `spa_core/risk/versions/v1_0_passive.py`
3. Load `V1_0_PASSIVE_CONFIG` from that file to verify the original values.
4. Apply the corrected values to `spa_core/risk/policy.py` with a new version number (e.g., v1.1).
5. Owner (Yurii) sign-off → merge.

If rolling back to a pre-v1.0 state (before any policy existed): the strategy must be paused manually.

---

## References

- Risk Policy doc: [`SPA/01_Docs/Risk_Policy_v0.3.md`](../../SPA/01_Docs/Risk_Policy_v0.3.md)
- Paper Trading Plan: [`SPA/01_Docs/Paper_Trading_and_Simulation_Plan_v0.3.md`](../../SPA/01_Docs/Paper_Trading_and_Simulation_Plan_v0.3.md)
- Strategy Passport: [`SPA/01_Docs/Strategy_Passport_Stable_Lending_Core_v0.3.md`](../../SPA/01_Docs/Strategy_Passport_Stable_Lending_Core_v0.3.md)
- Protocol whitelist: [`SPA/06_ADR/ADR-2026-006-extended_whitelist_v0.4.md`](../../SPA/06_ADR/ADR-2026-006-extended_whitelist_v0.4.md)
- Policy implementation: [`spa_core/risk/policy.py`](../../spa_core/risk/policy.py)
- Frozen snapshot: [`spa_core/risk/versions/v1_0_passive.py`](../../spa_core/risk/versions/v1_0_passive.py)
- ADR template: [`docs/adr/ADR_TEMPLATE.md`](./ADR_TEMPLATE.md)
