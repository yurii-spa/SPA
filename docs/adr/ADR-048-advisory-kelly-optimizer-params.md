# ADR-048: Kelly Optimizer Parameters — Advisory Only

| Field            | Value                                            |
|------------------|--------------------------------------------------|
| **Date**         | 2026-06-21                                       |
| **Status**       | PENDING — Owner to review and decide             |
| **Author**       | Claude (SPA agent)                               |
| **Approved by**  | _pending_ (Yurii)                                |
| **Policy ver.**  | v1.0 (no change applied — advisory record only)  |
| **ADR number**   | ADR-048                                           |

> **Numbering note:** the originating request referenced "ADR-036", but
> `ADR-036-baseanalytics-migration.md` already exists for an unrelated decision.
> To avoid colliding with / overwriting that ADR, this record uses the next free
> number, **ADR-048** (latest prior was ADR-047).

---

## Context

The parameter optimizer (Kelly / grid search, `spa_core/allocator/parameter_optimizer.py`)
produced `data/optimized_params.json` on 2026-06-20. The top-scoring combination is:

| Parameter             | Optimizer value |
|-----------------------|-----------------|
| `t1_cap`              | **0.30**        |
| `t2_cap`              | **0.25**        |
| `cash_buffer`         | **0.03**        |
| `rebalance_threshold` | **0.05**        |

with **expected APY 8.65%** (paper Sharpe and risk-adjusted APY also reported).

The current live risk policy (`spa_core/risk/policy.py`, RiskConfig v1.0) is:

| Parameter                  | Current value |
|----------------------------|---------------|
| `max_concentration_t1`     | 0.40          |
| `max_concentration_t2`     | **0.20**      |
| `min_cash_pct`             | **0.05**      |

The optimizer's `t2_cap=0.25` **exceeds** the live per-protocol T2 cap (0.20), and
its `cash_buffer=0.03` is **below** the live minimum cash buffer (0.05). Both move
the policy in a *less conservative* direction, i.e. they would **loosen** risk
limits. `t1_cap=0.30` is *more* restrictive than the live 0.40 (safe direction).

A decision was needed on whether to apply these parameters automatically.

---

## Decision

**Record the optimizer output as ADVISORY only. Do NOT change `RiskConfig`
automatically.**

A new read-only module, `spa_core/allocator/advisory_config.py`
(`AdvisoryConfig.get_comparison()`), surfaces the optimizer recommendation next to
the live policy for dashboards and review. It does not modify `RiskConfig`, the
allocator, or execution, uses no LLM, and depends only on stdlib.

### Changes to RiskConfig

**None.** No parameter is changed by this ADR.

| Parameter | Old value | New value | Rationale |
|-----------|-----------|-----------|-----------|
| _(none)_  | —         | —         | Advisory record only; any actual change needs its own approved ADR + paper test. |

---

## Rationale

Any risk-parameter change requires human review per **RULES.md** and the
governance block in `spa_core/risk/policy.py` (ADR → Owner approval → snapshot →
≥2-week paper test → merge). The optimizer recommendation *loosens* two limits
(T2 per-protocol cap up 0.20→0.25; cash buffer down 0.05→0.03), so it is **not**
within the existing risk envelope and cannot be auto-applied.

`AdvisoryConfig.safe_to_apply` evaluates to **False** for exactly this reason
(T2 cap raised; cash buffer lowered).

### Alternatives Considered

- **Auto-apply optimizer params to RiskConfig** — rejected: violates governance
  (no ADR/owner approval/paper test), and loosens risk limits unreviewed.
- **Ignore the optimizer output** — rejected: the ~0.5% APY signal is worth
  recording and reviewing; advisory surfacing keeps it visible without risk.

---

## Consequences

### Positive
- Optimizer signal is captured and visible (dashboard/tests) with zero risk
  change.
- Clear, auditable record of *why* the change was not auto-applied.

### Negative / Risks
- Estimated **~0.5% APY** improvement (8.65% optimal vs ~8.15% at current caps)
  is left on the table until/unless a follow-up ADR approves the change.

### Neutral
- `t1_cap=0.30` would tighten T1 concentration (safe direction) but is bundled
  with the loosening changes, so the bundle as a whole needs review.

---

## Estimated Improvement

**~0.5% APY** — optimizer expected APY **8.65%** vs **~8.15%** for the current
caps (`t1_cap=0.40, t2_cap=0.20, cash_buffer=0.05`) from the optimizer's own
`all_results` grid.

---

## Decision Required (Owner)

Yurii to review and choose one of:

1. **Approve a follow-up ADR** raising `max_concentration_t2` 0.20→0.25 and/or
   lowering `min_cash_pct` 0.05→0.03, with snapshot + ≥2-week paper test.
2. **Approve only the safe subset** (`t1_cap` 0.40→0.30) if desired.
3. **Reject** — keep RiskConfig v1.0 as-is; advisory record remains for history.

**Status: PENDING.**

---

## References

- Optimizer output: [`data/optimized_params.json`](../../data/optimized_params.json)
- Advisory module: [`spa_core/allocator/advisory_config.py`](../../spa_core/allocator/advisory_config.py)
- Policy file: [`spa_core/risk/policy.py`](../../spa_core/risk/policy.py)
- [ADR-019](./ADR-019-t2-cap-increase.md): prior T2 cap change (35%→50% total)
- [ADR-045](./ADR-045-kelly-criterion-allocation.md): Kelly sizing (advisory tilt)
- Governance: `RULES.md`
