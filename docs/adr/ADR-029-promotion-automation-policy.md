# ADR-029: Strategy Promotion Automation Policy

**Status:** Accepted
**Date:** 2026-06-12
**Deciders:** Owner
**Related:** ADR-023 (Strategy Promotion Policy), ADR-002 (Go-live transfer rule), ADR-021 (Pendle YT T3-SPEC)

---

## Context

ADR-023 defines the gate criteria for promoting a strategy from paper trading to live
allocation: ≥ 14 days paper (≥ 30 days for T3), Sharpe ≥ 0.80, APY ≥ 7% net,
Calmar ≥ 1.0, adapter health PASS, chain concentration within bounds. The final step
in that flow is `USER_APPROVAL` — an explicit Owner confirmation in Telegram before
`PromotionEngine` shifts any capital.

In the early paper-trading phase (through 2026-06-12) this gate worked well because
promotions were infrequent and the Owner was actively monitoring daily outputs. As the
Tournament scales to S0–S10+ strategies and the system approaches go-live (ADR-002,
target 2026-08-01), the `USER_APPROVAL` step is becoming a bottleneck:

- The Owner may be offline for 12–48 h during travel, weekends, or off-hours.
- A promotion opportunity for a strategy already well above threshold can be missed
  by a multi-day delay, costing realized yield on the virtual portfolio.
- Conversely, not all promotions carry equal risk: a T1 strategy at Sharpe 1.2 with
  zero halts is structurally different from a T3-SPEC strategy at Sharpe 0.81 that
  triggered one risk gate in the observation window.

This ADR introduces a three-tier automation framework that preserves `USER_APPROVAL`
where it matters (high-risk edge cases) while allowing unattended promotion for
strategies that have demonstrably exceeded all safety thresholds.

**Scope:** This ADR governs only paper → advisory-live promotion decisions within
`PromotionEngine`. It does not affect `RiskPolicy` gate logic (which remains
deterministic and LLM-forbidden), allocation caps, or the go-live transfer rule
(ADR-002). `approved=False` from `RiskPolicy` cannot be overridden by any tier of
this policy.

---

## Decision

### Tier A — Automatic Promotion (immediate)

All of the following conditions must be satisfied simultaneously:

| Criterion | Threshold | Rationale |
|---|---|---|
| Paper trading days | ≥ 30 calendar days | Full month of evidence, stricter than ADR-023 |
| Sharpe ratio (30d rolling) | ≥ 1.0 | 25% above ADR-023 minimum; compensates for absent human review |
| Realized APY vs target | ≥ target × 110% | Demonstrably outperforming, not just qualifying |
| Maximum drawdown (period) | < 5% at all times | Kill-switch alignment; zero headroom to limit |
| Risk Gate HALTs (period) | 0 | Any halt signals unresolved structural risk |
| Strategy tier | T1 or T2 only | T3-SPEC strategies are excluded regardless of metrics |

When all Tier A conditions pass, `PromotionEngine` promotes the strategy immediately
without waiting for Owner input. A Telegram notification is sent:

```
⚡ AUTO-PROMOTED: {strategy_id} → Production
Sharpe: {sharpe:.2f} | APY: {apy:.1f}% | DD: {dd:.1f}% | Days: {days}
Tier A (all thresholds exceeded, zero halts, no T3-SPEC)
Reply REVERT within 24h to roll back.
```

A 24-hour REVERT window is provided: if the Owner replies `REVERT {strategy_id}`,
`PromotionEngine` demotes the strategy and logs an ADR note. This is the only
post-hoc override mechanism in Tier A.

### Tier B — Automatic Promotion with 48-Hour Hold

Applies when all Tier B conditions pass but Tier A conditions are **not** met:

| Criterion | Threshold | Notes |
|---|---|---|
| Paper trading days | ≥ 30 calendar days | Same as Tier A |
| Sharpe ratio (30d rolling) | ≥ 0.8 | ADR-023 minimum |
| Realized APY vs target | ≥ target × 90% | Slightly below plan — still viable |
| Maximum drawdown (period) | < 8% | Wider than Tier A; still below kill switch |
| Risk Gate HALTs (period) | 0 | No halts allowed even in Tier B |
| Strategy tier | T1 or T2 only | T3-SPEC excluded |

When Tier B conditions pass, `PromotionEngine` sends a Telegram notification and
starts a 48-hour countdown:

```
🕐 PENDING AUTO-PROMOTE: {strategy_id} in 48h
Sharpe: {sharpe:.2f} | APY: {apy:.1f}% | DD: {dd:.1f}%
Tier B (metrics above ADR-023 floor; below Tier A threshold)
Reply CANCEL to stop. Silence = proceed.
```

If no `CANCEL {strategy_id}` reply is received within 48 hours, the strategy is
promoted automatically. If `CANCEL` is received, the strategy enters Tier C manual
review. Pending Tier B promotions are persisted in `data/promotion_pending.json`
to survive daemon restarts.

### Tier C — Manual Review Required

Tier C applies when **any** of the following is true:

| Trigger | Reason |
|---|---|
| Strategy is T3-SPEC (ADR-021) | High speculative risk; Owner must sign off |
| Realized APY < target × 90% | Below acceptable floor; strategy underperforming plan |
| Drawdown ≥ 8% at any point in period | Structural risk signal not acceptable for auto-promote |
| Sharpe < 0.8 | Below ADR-023 minimum; ineligible for any automation |
| Any Risk Gate HALT in observation period | RiskPolicy already flagged a violation |
| `capital_at_risk` projection > $50,000 | Large-position strategies require human judgment |
| Owner sends `CANCEL` to a Tier B pending | Explicit opt-out re-routes to manual flow |

Telegram notification:

```
🔴 MANUAL REVIEW REQUIRED: {strategy_id}
Reason: {reason}
Sharpe: {sharpe:.2f} | APY: {apy:.1f}% | DD: {dd:.1f}%
Reply APPROVE {strategy_id} or REJECT {strategy_id}
```

No automated promotion occurs. The strategy remains in paper trading until explicit
Owner approval (`APPROVE`) or rejection (`REJECT`). This is the current ADR-023
flow, unchanged.

### Tier Routing Logic

```
evaluate_for_auto_promote(strategy):
    if strategy.tier == "T3-SPEC":              → Tier C (T3-SPEC mandatory)
    if any halt in observation window:          → Tier C (halt flag)
    if sharpe < 0.8:                            → Tier C (below ADR-023 floor)
    if apy < target × 0.90:                     → Tier C (underperforming)
    if drawdown ≥ 8%:                           → Tier C (drawdown signal)
    if capital_at_risk > 50_000:                → Tier C (size gate)
    # Passed all Tier C exclusions
    if sharpe ≥ 1.0 and apy ≥ target × 1.10 and drawdown < 5%:
                                                → Tier A (immediate)
    else:                                       → Tier B (48h hold)
```

### Phased Activation

| Phase | Date | State |
|---|---|---|
| **Phase 1** | Now — 2026-07-11 | All promotions via USER_APPROVAL (ADR-023). `auto_promote_enabled: false`. Tier A/B logic computed but suppressed; output logged to `data/promotion_report.json` as advisory. |
| **Phase 2** | 2026-07-12 (after 30 days paper) | `auto_promote_enabled: true`. Tier A and Tier B active. Tier C unchanged (manual). |
| **Phase 3** | 2026-08-01 (go-live) | Tier C blockers for T3-SPEC propagate to GoLiveChecker as a hard gate. A strategy in Tier C cannot be deployed live without Owner sign-off regardless of other go-live criteria. |

The `auto_promote_enable_date` field in `data/promotion_policy.json` controls Phase 2
activation. Changing it requires an Owner decision and a new ADR note.

---

## Rationale

### Why not automate T3-SPEC strategies?

ADR-021 classifies Pendle YT strategies (S10 and equivalents) as advisory-only with
no automatic position opening. That restriction is structural, not metric-dependent.
Even a T3-SPEC strategy at Sharpe 2.0 carries protocol risk (yield token illiquidity,
AMM slippage, maturity cliff) that quantitative metrics do not fully capture. The
Owner remains the final authority on T3-SPEC promotion.

### Why 48 hours for Tier B (not 24)?

48 hours covers a full weekend day plus a business day buffer — enough for an Owner
travelling across time zones to review the notification. 24 hours was considered but
rejected: a Friday evening notification would effectively force same-day review or
auto-promote before Monday, which is not acceptable behaviour.

### Why the REVERT window in Tier A?

Tier A auto-promotion is immediate and notification-only, which means the Owner has
no pre-approval step. A 24-hour REVERT window provides a safety net without defeating
the purpose of unattended automation. REVERT is implemented as an allocation rollback
(not a kill), so the strategy returns to paper trading rather than being terminated.

### Alternatives Considered

- **Full automation (no Tier C):** Rejected. T3-SPEC strategies and large positions
  require human context (market regime, protocol news, custody readiness) that the
  deterministic engine cannot assess.
- **Keep pure USER_APPROVAL (no automation):** Rejected. As the portfolio scales,
  the Owner cannot be the synchronous bottleneck for every routine promotion.
- **Tier A only (no Tier B):** Rejected. A Sharpe 0.85 strategy that is otherwise
  clean should not require manual approval, but the 48-hour hold provides proportional
  caution for strategies that haven't cleared the stricter Tier A bar.

---

## Consequences

### Positive

- Eliminates Owner availability as a bottleneck for routine, high-confidence promotions.
- Tier B 48-hour hold provides a proportional safety net between full automation (Tier A)
  and full manual review (Tier C).
- Phased activation (Phase 1 advisory → Phase 2 live) allows the tier routing logic to
  be observed and validated before it has any effect.
- T3-SPEC strategies remain under unconditional human oversight (consistent with ADR-021).

### Negative / Risks

- Tier A promotes without explicit Owner sign-off. If the strategy encounters a regime
  shift immediately after promotion, the Owner may not be aware until the Telegram fires.
  Mitigated by the 24-hour REVERT window and the existing kill-switch (drawdown ≥ 5%
  triggers `approved: false` in RiskPolicy gate).
- Tier B 48-hour silence-as-consent requires the Owner to trust that the Telegram
  notification was received and read. If Telegram delivery fails, the auto-promotion
  proceeds. Mitigated by requiring Telegram delivery confirmation before starting the
  48-hour countdown.
- Adding `promotion_pending.json` introduces a new persistent state file that must
  survive daemon restarts and be included in the DR procedure (DR_PROCEDURE_v2.md).

### Neutral

- Phase 1 produces advisory-only tier classification in `data/promotion_report.json`.
  This is zero-risk and provides real data to validate the routing logic before
  Phase 2 activation.

---

## Implementation Plan

| Phase | Date | Deliverable |
|---|---|---|
| **Phase 1** | 2026-06-12 | `data/promotion_policy.json` (this ADR); tier routing logic added to `promotion_engine.py` as advisory-only; output in `promotion_report.json` |
| **Phase 2** | 2026-07-12 | Flip `auto_promote_enabled: true` in `promotion_policy.json`; Tier A/B Telegram notifications live |
| **Phase 3** | 2026-08-01 | GoLiveChecker criterion: Tier C strategies block go-live unless Owner has issued `APPROVE` |

Progress tracked in `KANBAN.json` under the MP task for this ADR.

---

## References

- [ADR-023: Strategy Promotion Policy](../ADR-023-strategy-promotion-policy.md)
- [ADR-002: Go-live Transfer Rule](./ADR-002-golive-transfer-rule.md)
- [ADR-021: Pendle YT T3-SPEC](./ADR-021-pendle-yt-t3-classification.md)
- [`spa_core/paper_trading/promotion_engine.py`](../../spa_core/paper_trading/promotion_engine.py)
- [`data/promotion_policy.json`](../../data/promotion_policy.json)
- [`data/promotion_pending.json`](../../data/promotion_pending.json) *(created in Phase 2)*

---

*Document owner: Owner. Next review: 2026-07-12 (Phase 2 activation) or upon any
promotion incident. Changes to tier thresholds require a new ADR.*
