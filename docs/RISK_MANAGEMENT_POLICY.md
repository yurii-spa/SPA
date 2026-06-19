# SPA Risk Management Policy

**Version:** v1.0  
**Effective:** 2026-05-20  
**Owner:** SPA Engineering Team  
**ADR reference:** ADR-001, ADR-019, ADR-020, ADR-021  

---

## 1. Overview

This document defines the deterministic risk constraints governing all capital allocation
decisions in the Smart Passive Aggregator (SPA) system. The policy is enforced by
`spa_core/risk/policy.py` and applied as a hard gate in every daily cycle. No trade
may be executed if `RiskPolicy.approve()` returns `False`.

**LLM_FORBIDDEN:** Risk, execution, and monitoring components must never invoke
language-model calls (prompt-injection in capital pathways is a critical attack vector).

---

## 2. Capital Limits

| Parameter | Value | Notes |
|-----------|-------|-------|
| Total virtual capital | $100,000 USDC | Paper trading phase |
| Min cash buffer | ≥ 5% | ~$5,000 always undeployed |
| Per-protocol cap (T1) | 40% | $40,000 max per T1 protocol |
| Per-protocol cap (T2) | 20% | $20,000 max per T2 protocol |
| T2 total cap | ≤ 50% | $50,000 max in T2 aggregate (ADR-019) |
| T3 advisory cap | 0% auto | T3-SPEC: advisory only, no auto-positions |

---

## 3. Protocol Tiers

| Tier | Description | Examples |
|------|-------------|---------|
| T1 | Battle-tested, high TVL (≥$1B), audited | Aave V3, Compound V3, Morpho Steakhouse |
| T2 | Established, TVL $50M–$1B, audited | Morpho Blue, Yearn V3, Euler V2, Maple |
| T3-SPEC | Speculative / research only | Pendle YT (ADR-021), Delta-Neutral strategies |

### TVL Floor

Minimum TVL per pool: **≥ $5,000,000 USD**. Any pool below this floor is
rejected by `RiskPolicy` regardless of APY.

---

## 4. APY Guardrails

New positions may only be opened when:

- **APY floor:** ≥ 1.0% annualised
- **APY ceiling:** ≤ 30.0% annualised

APY values exceeding 30% are flagged as potentially unsustainable and blocked
from automatic allocation. Strategies like Delta-Neutral sUSDe (S8) and Pendle YT (S10)
are assessed in paper-trading only (advisory mode) pending go-live approval.

---

## 5. Kill Switch

A portfolio-level drawdown of **≥ 5%** from peak equity triggers an emergency
kill switch:

1. All open positions are closed (or flagged for closure in paper mode)
2. `risk_policy_blocks.json` records the event
3. Cycle runner exits without executing rebalance
4. Manual review required before resuming

The kill switch is implemented in `spa_core/safety/safeguard.py` and
`spa_core/safety/live_trading_gate.py`.

---

## 6. Sky/sUSDS Special Rule

Sky protocol (sUSDS) receives **0% allocation** until:

- On-chain GSM Pause Delay is confirmed ≥ 48 hours
- `spa_core/data_pipeline/sky_monitor.py` returns `gsm_pause_delay_ok: True`

See ADR-001 for rationale.

---

## 7. RiskPolicy Version Control

The current policy version is **v1.0** (effective 2026-05-20). Any change to
risk parameters during the paper-trading period requires:

1. A new ADR document in `docs/adr/`
2. A versioned snapshot in `spa_core/risk/versions/`
3. GoLiveChecker re-validation
4. Manual owner sign-off

The version string `"v1.0"` must not be changed without completing the above steps.

---

## 8. Audit Trail

- Policy blocks are logged in `data/risk_policy_blocks.json` (ring-buffer, 100 entries)
- Every cycle records the gate decision in `data/paper_trading_status.json`
- The GoLiveChecker criterion `risk_policy_snapshot` verifies the snapshot is current

---

## 9. Forbidden Operations

The following operations are **permanently prohibited** regardless of strategy signals:

1. Importing `spa_core/execution/` from read-only or paper-trading code
2. Using external Python dependencies in runtime risk code (stdlib only)
3. Overriding `approved=False` from `RiskPolicy`
4. Writing to `data/adapter_status.json` from read-only code
5. Direct `open(..., "w")` on state files (must use `tmp + os.replace`)

---

*Document maintained by SPA Engineering. Last updated: 2026-06-19 (MP-1417)*
