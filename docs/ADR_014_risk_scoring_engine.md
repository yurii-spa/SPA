# ADR-014 — Risk Scoring Engine (FEAT-RISK-001)

**Status:** Accepted
**Date:** 2026-05-27
**Sprint:** v3.14
**Author:** Dispatch orchestrator (autonomous run)
**Supersedes:** —
**Superseded by:** —

## Context

The Risk Layer roadmap defines a single structured grading function that
takes a protocol/pool and returns a letter grade in `{A, B, C, D}` plus
a numeric score in `[0, 1]`. This is the missing input for:

* **Allocation engine** (FEAT-ALLOC-002, next sprint) — grade `C` halves the
  default per-strategy cap and grade `D` clamps it to a 5 % absolute cap.
* **Architect agent's protocol whitelist refresh** — anything that drops
  to `D` for two consecutive runs is auto-removed from the whitelist.
* **Operator digest / Kanban risk panel** — surfaces the top-3 weakest
  subscores per protocol so the operator knows *why* a grade changed.

Before this ADR the risk read was implicit (the operator's mental model
+ a sparse `risk_alerts.json` file). Implicit scoring does not scale to
ten whitelisted protocols across three tiers.

## Decision

Ship a deterministic, stdlib-only, offline-tolerant engine that scores
each protocol on **15 documented subscores**, combines them with a
documented weight vector that sums to `1.0`, and maps the result to a
letter grade.

### 15 subscores

| #  | Key                          | Source                                       | Range  |
|----|------------------------------|----------------------------------------------|--------|
| 1  | `tvl_magnitude`              | DefiLlama `tvl` (log-banded $50M..$1B)       | [0, 1] |
| 2  | `tvl_trend`                  | DefiLlama `change_30d`                       | [0, 1] |
| 3  | `protocol_age`               | Bootstrap `launched_year`                    | [0, 1] |
| 4  | `hack_history`               | `data/incidents.json` (FEAT-RISK-002)        | [0, 1] |
| 5  | `audit_count`                | DefiLlama `audits`                           | [0, 1] |
| 6  | `audit_findings_severity`    | `data/audit_findings.json` (FEAT-INT-001)    | [0, 1] |
| 7  | `yield_source_type`          | Bootstrap classification                     | [0, 1] |
| 8  | `oracle_risk`                | Bootstrap (Chainlink / Pyth / custom / …)    | [0, 1] |
| 9  | `bridge_dependency`          | Bootstrap `bridge_dependent` flag            | [0, 1] |
| 10 | `timelock_duration`          | Bootstrap `timelock_seconds`                 | [0, 1] |
| 11 | `multisig_threshold`         | Bootstrap `multisig_m_of_n`                  | [0, 1] |
| 12 | `liquidity_depth`            | Bootstrap `liquidity_depth_usd`              | [0, 1] |
| 13 | `cross_protocol_deps`        | Bootstrap `cross_protocol_deps`              | [0, 1] |
| 14 | `regulatory_surface`         | Bootstrap `us_exposed` + chain               | [0, 1] |
| 15 | `chain_maturity`             | Bootstrap `chain` mapped to maturity bucket  | [0, 1] |

Every subscore returns a float in `[0, 1]` where **higher is safer**.

### Weights

All subscores are equally weighted at `1.0` *except* four risk-critical
parameters that receive a `1.5×` multiplier:

* `oracle_risk` — oracle compromise is the single most common DeFi loss
  vector;
* `hack_history` — past incidents are the best predictor of future ones;
* `audit_findings_severity` — open critical findings should outweigh raw
  audit count;
* `timelock_duration` — long timelocks are the operator's only window to
  respond to a malicious governance proposal.

The raw vector is then normalised so `sum(weights) == 1.0` exactly
(verified by a test). Concretely the normalised weights are:

```
oracle_risk:             ~0.088   audit_findings_severity: ~0.088
hack_history:            ~0.088   timelock_duration:       ~0.088
tvl_magnitude:           ~0.059   tvl_trend:               ~0.059
protocol_age:            ~0.059   audit_count:             ~0.059
yield_source_type:       ~0.059   bridge_dependency:       ~0.059
multisig_threshold:      ~0.059   liquidity_depth:         ~0.059
cross_protocol_deps:     ~0.059   regulatory_surface:      ~0.059
chain_maturity:          ~0.059
```

### Grade thresholds

| Grade | Score range | Allocation policy (downstream)        |
|-------|-------------|---------------------------------------|
| **A** | `>= 0.85`   | full strategy cap                     |
| **B** | `>= 0.70`   | full strategy cap                     |
| **C** | `>= 0.55`   | strategy cap × 0.50                   |
| **D** | `<  0.55`   | absolute 5 % cap                      |

Boundaries are inclusive on the high side (a score of exactly `0.85`
grades as `A`). This convention is asserted by the test suite.

## Output schema (`data/risk_scores.json`)

```json
{
  "generated_at":   "2026-05-27T20:53:00Z",
  "engine_version": "1.0",
  "weights":        { "tvl_magnitude": 0.058824, "...": 0.0 },
  "scores": [
    {
      "protocol":           "Aave V3",
      "slug":               "aave-v3",
      "grade":              "A",
      "score_numeric":      0.914,
      "subscores":          { "tvl_magnitude": 1.0, "...": 1.0 },
      "explanation":        "Aave V3 graded A (numeric 0.914). Lowest subscores: ...",
      "allocation_cap_pct": null,
      "fallback_used":      false,
      "generated_at":       "2026-05-27T20:53:00Z"
    }
  ],
  "summary_by_grade":  { "A": 2, "B": 8, "C": 0, "D": 0 },
  "fallback_used_any": true
}
```

## Integration plan

The engine is **additive**: it writes one new file and reads two
existing optional ones. Nothing else is modified by this sprint.

| Consumer                 | When                | Behaviour                            |
|--------------------------|---------------------|--------------------------------------|
| `engine.py` (allocation) | next sprint         | reads `risk_scores.json`, clamps cap |
| Architect agent          | next sprint         | auto-suspends protocols stuck at `D` |
| Kanban risk panel        | UI sprint           | renders grade chip + top-3 weak subs |
| Operator digest          | reports sprint      | adds a "Risk Movers" section         |

Run cadence: the engine is invoked from `python -m spa_core.risk.scoring_engine`
either ad-hoc by the operator or by a soon-to-be-scheduled CronAgent job
once per UTC day.

## Fallback behaviour

| Failure                                | Behaviour                                          |
|----------------------------------------|----------------------------------------------------|
| DefiLlama unreachable                  | merge `BOOTSTRAP_PROTOCOLS` into result; set flag  |
| `--offline` flag                       | skip network entirely; use bootstrap snapshot      |
| `data/incidents.json` missing/corrupt  | `hack_history` subscore → neutral `0.5` + flag     |
| `data/audit_findings.json` missing     | `audit_findings_severity` → neutral `0.5` + flag   |
| Unknown protocol slug requested        | neutral 0.5 record, `fallback_used=True`           |

The per-protocol `fallback_used` field and the top-level
`fallback_used_any` field make degraded runs observable.

No exception ever escapes `compute_score()` / `compute_all()`. The
allocation engine can therefore call the scoring engine on the hot path
without try/except guards.

## Alternatives considered

1. **Numeric score only (no letters)** — rejected. The operator needs a
   coarse, human-readable label for digests and for the architect
   agent's auto-suspend rule. A 0.78 vs 0.81 difference is not
   actionable; an `A` vs `B` is.

2. **MLP / boosted-tree risk model** — rejected for Phase 1. The whole
   point of the scoring engine is to make risk attributions *explainable*
   to the operator ("Curve dropped to B because of `cross_protocol_deps`
   and `tvl_trend`"). A neural model defeats that.

3. **5-tier grading (A/B/C/D/F)** — rejected. The de-facto industry
   standard published by Llama Risk, OpenZeppelin, and DeFiSafety is
   four tiers. Adopting the same vocabulary keeps the SPA digest
   comparable to those third-party scores.

4. **Per-strategy weight overrides** — deferred. Carrying ten strategies
   ×  fifteen weights would obscure the source of grade changes.
   Strategy-specific risk tilts can be applied as multiplicative
   overlays in the allocation engine instead.

## Rollback

The feature is fully additive:

* Delete `spa_core/risk/scoring_engine.py`.
* Delete `spa_core/tests/test_scoring_engine.py`.
* Delete `data/risk_scores.json` (no other module depends on it yet).
* Revert `KANBAN.json` and `SPA_sprint_log.md` v3.14 entries.

No DB migrations, no breaking changes, no live-trading impact.
