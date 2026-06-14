# ADR-027 — S13 Multi-Chain Yield Arbitrage Strategy

**Date:** 2026-06-12  
**Status:** Accepted  
**Authors:** SPA Agent  
**Extends:** ADR-025 (Base Chain Expansion), ADR-023 (Strategy Promotion Criteria)

---

## Context

ADR-025 added Base chain adapters (Aave Base, Morpho Blue Base, Extra Finance) to the SPA adapter registry. Post-integration monitoring reveals a persistent APY spread between Base and Ethereum mainnet:

- **Base chain protocols:** Aave Base, Morpho Blue Base, Extra Finance averaging **6–8% APY**
- **Ethereum mainnet (T1):** Aave V3, Compound V3, Morpho Steakhouse averaging **5–6% APY**
- **Current Tournament leader (2026-06-12):** S7 (Pendle YT) at 10.115% — T3-SPEC risk, advisory only

The spread creates a cross-chain yield arbitrage opportunity that no existing strategy exploits in a controlled, risk-bounded manner. S8 (Delta-Neutral sUSDe) and S9 (E-Mode Looping) address leverage/hedging strategies on Ethereum; S10 (Pendle YT) is speculative T3-SPEC. There is no T2 strategy that systematically routes capital between chains based on yield differential.

ADR-026 suspended Moonwell Finance (Base) due to oracle manipulation and uncleared bad debt — this protocol is excluded from the S13 allocation universe.

---

## Decision

Implement **S13 Multi-Chain Yield Arbitrage** as a new Tournament strategy with the following parameters:

| Parameter | Value |
|-----------|-------|
| Strategy ID | S13 |
| Tier | T2 |
| RISK_SCORE | 0.45 |
| Status | paper-only until go-live (2026-08-01) |

### Phase 1 — Pre-Go-Live (until 2026-08-01)

S13 operates in ETH-only fallback mode. Capital allocated entirely to Ethereum mainnet using fixed weights:

| Protocol | Weight |
|----------|--------|
| Aave V3 (Ethereum) | 40% |
| Compound V3 (Comet USDC) | 30% |
| Morpho Steakhouse | 30% |

Cross-chain routing is disabled in Phase 1. This builds a clean paper track record using familiar T1 protocols.

### Phase 2 — Post-Go-Live (after 2026-08-01)

Cross-chain arbitrage logic activates. Routing decision computed once per daily cycle:

**Arbitrage trigger condition:**

```
If Base_avg_APY > ETH_avg_APY + 1.5%:
    Base allocation = 30% (cap per ADR-025)
    ETH allocation  = 70%
Else:
    ETH allocation  = 100% (full fallback)
```

- **Base chain cap: 30%** — consistent with ADR-025 maximum 20% of total portfolio (at S13's tournament weight, 30% of S13 slice ≤ 20% of portfolio)
- **Gas kill-switch:** BaseGasMonitor (ADR-025) — if Base gas cost exceeds threshold, Base allocation collapses to 0% for the current cycle
- **Moonwell excluded:** ADAPTER_STATUS = "suspended" (ADR-026); not included in Base weights under any condition
- **Base allocation universe (Phase 2):** Aave Base, Morpho Blue Base, Extra Finance (T3 advisory cap applies)

### Allocation Rules Summary

| Condition | Base | ETH |
|-----------|------|-----|
| `Base_avg_APY > ETH_avg_APY + 1.5%` AND gas OK | 30% | 70% |
| `Base_avg_APY ≤ ETH_avg_APY + 1.5%` | 0% | 100% |
| Gas kill-switch triggered | 0% | 100% |
| Phase 1 (pre-go-live) | 0% | 100% |

---

## Promotion Criteria (ADR-023)

S13 may be promoted from paper to live allocation only when all of the following are satisfied:

1. **30 days** continuous paper trading without data gaps (gap_monitor)
2. **Sharpe ratio ≥ 0.8** (tournament_evaluator rolling 30d)
3. **Realized APY ≥ 7.5%** (paper period)
4. **USER_APPROVAL required** — manual Owner review before any live activation
5. Go-live conditions met (ADR-002: READY 7+ days + gap_monitor 30 days clean)

---

## Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Smart contract risk on Base | Medium | ADR-025 mitigations apply; Base cap 30%; excluded protocols suspended per ADR-026 |
| Gas costs Base > ETH for small operations | Low | Gas kill-switch (BaseGasMonitor) disables Base routing when uneconomical |
| Yield spread compression | Medium | Phase 1 ETH-only fallback is always available; spread threshold 1.5% filters noise |
| Bridge/settlement risk in paper mode | N/A | Paper trading — no actual cross-chain transfers; position values tracked by adapter APY |
| Oracle manipulation (per ADR-026) | Low | Moonwell excluded; remaining Base adapters use audited on-chain sources |

---

## Consequences

- **Tournament expanded to 14 strategies (S0–S13).** `strategy_registry.py` entry required for S13.
- **S13 paper track starts 2026-06-12.** The 30-day promotion clock begins from first cycle inclusion.
- **If S13 realizes APY > 8.5% in paper trading**, promotion review should be scheduled for September 2026 (subject to all criteria above).
- **Moonwell (SUSPENDED, ADR-026)** is not included in any S13 Base weights and must not be re-added without a new ADR lifting the suspension.
- **RiskPolicy v1.0 is unchanged.** S13 operates within existing caps: T2 total cap ≤ 50% (ADR-019), per-protocol cap ≤ 20%, TVL floor ≥ $5M per pool.
- **`approved=False` from RiskPolicy cannot be overridden by S13** under any circumstances.
- **Phase 2 cross-chain routing** requires BaseGasMonitor to be operational; if monitor is unavailable, strategy defaults to Phase 1 ETH-only weights.

---

## References

- ADR-002: Go-Live Transfer Rule
- ADR-019: T2 Total Cap raised to 50%
- ADR-023: Strategy Promotion Criteria
- ADR-025: Base Chain Expansion Plan
- ADR-026: Base Chain Protocols v2 — Moonwell Finance Suspension
- RiskPolicy v1.0: `spa_core/risk/policy.py`
- Tournament evaluator: `spa_core/strategies/tournament_evaluator.py`
- Strategy registry: `spa_core/strategies/strategy_registry.py`
