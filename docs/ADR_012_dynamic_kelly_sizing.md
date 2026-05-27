# ADR-012 — Dynamic Kelly Sizing with Live APY Covariance

**Status:** Accepted — Phase 1 (scaffold) shipped in sprint v3.12.
**Date:** 2026-05-27
**Related:** FEAT-007, ADR-001 (initial risk policy), ADR-008 (execution router), ADR-011 (engine live cutover)

---

## Context

The original Kelly sizing in `spa_core/optimization/kelly.py` (and the
correlation matrix in `optimization/markowitz.py`) hardcodes the
per-protocol volatility as `σ_i = apy_i * 0.10` (a flat 10% coefficient
of variation) and the cross-protocol correlation as a tier-based
constant (0.6 same-tier, 0.2 cross-tier). These were defensible
placeholders in v0.13 when no APY history existed, but by sprint v3.11
the `data/apy_history.json` store maintained by `analytics.apy_tracker`
holds 90 days of per-cycle observations across every whitelisted pool.

FEAT-007 ("Advanced Kelly Sizing with Live Data") calls for replacing
the synthetic covariance matrix with a rolling 90-day live estimate, and
adjusting the Kelly fraction per cycle based on the real volatility
distribution.

## Decision

Implement FEAT-007 as a **three-phase rollout** mirroring the
FEAT-004/005/006 phased pattern:

- **Phase 1 (this ADR, sprint v3.12 — DONE):** Pure-Python
  `analytics/covariance_estimator.CovarianceEstimator` + an OPT-IN
  `optimization/dynamic_kelly.py` module exposing `dynamic_kelly_fraction
  / dynamic_half_kelly / dynamic_position_size`. Both delegate to the
  classical kelly path when `volatility_pp` is None or non-positive, so
  every existing call-site behaves byte-identically. No production
  wiring.

- **Phase 2 (next sprint):** Wire `CovarianceEstimator` into
  `optimization/markowitz.PortfolioOptimizer` and
  `optimization/recommender.AllocationRecommender` behind a
  `SPA_LIVE_COVARIANCE=1` env flag. Default OFF so paper-trading day-N
  numbers stay stable. Daily JSON export at `data/covariance_summary.json`
  for dashboard inspection.

- **Phase 3 (post-go-live):** Remove the env flag; live covariance
  becomes the default. The synthetic CV proxy is retained ONLY as a
  cold-start fallback when a protocol has fewer than 7 observations.

## Mathematical model

### Variance Kelly

For continuous returns with mean μ and variance σ²:

```
f* = (μ - r_f) / σ²
```

Both inputs are expressed as fractions in the implementation (apy / 100,
σ / 100) so the result is dimensionless. The risk-free rate `r_f` is the
same `_RISK_FREE_RATE_PCT = 5.0` used by `markowitz.py` and `engine.py`,
so the three subsystems share a single hurdle.

### Cold-start blend

When `CovarianceEstimator.compute_volatility()` returns 0 (fewer than
`MIN_OBSERVATIONS=7` data points in the window), `dynamic_kelly_fraction`
delegates straight through to `kelly.kelly_fraction`. This means the
cold-start case is *provably identical* to the existing behaviour — a
critical safety property for the go-live cutover.

### Covariance matrix

`Cov[i][j] = σ_i * σ_j * ρ_ij`

* `σ_i` is the sample standard deviation (Bessel's correction) of the
  protocol's APY series in the rolling window.
* `ρ_ij` is the Pearson correlation on the time-aligned intersection of
  timestamps. When fewer than `MIN_OBSERVATIONS` overlapping points
  exist, the tier-based synthetic value is returned.

The diagonal is `σ²` (the variance), matching how Markowitz reads it.

## Alternatives considered

1. **Exponential weighting (EWMA).** Would react faster to a regime
   change at the cost of higher noise. Rejected for Phase 1 because the
   linear 90-day window matches `apy_tracker.MAX_HISTORY_DAYS` exactly,
   simplifying the mental model. Re-evaluate after Phase 2 ships.

2. **Ledoit-Wolf shrinkage.** Industry standard for ill-conditioned
   covariance matrices, but requires numpy. Rejected because the
   SPA stdlib-only constraint precludes a numpy dep for a single
   estimator, and our n=7 protocols × 90 days regime doesn't actually
   suffer the rank-deficient pathologies shrinkage solves.

3. **Risk-parity weighting instead of Kelly.** Different objective —
   minimises marginal risk contribution rather than maximising
   log-growth. Out of scope for FEAT-007; could be a future feature.

## Rollback

Phase 1 is purely additive — no existing module imports from
`analytics/covariance_estimator.py` or `optimization/dynamic_kelly.py`.
Reverting is a single `git rm` of those two files plus their tests.

Phase 2 will gate the new path behind `SPA_LIVE_COVARIANCE=1`, so
rollback there is a single env var flip.

## Validation

* `spa_core/tests/test_covariance_estimator.py` — 31 deterministic tests
  (ISO parsing, stdev/Pearson helpers, protocol listing, volatility +
  correlation estimators, matrix symmetry, JSON summary shape). All PASS.
* `spa_core/tests/test_dynamic_kelly.py` — 21 deterministic tests
  (fallback parity with classical kelly across 5 input regimes,
  variance-Kelly known-value checks, half-kelly invariant, cap
  enforcement). All PASS.
* Regression: `test_optimization.py + test_apy_tracker.py +
  test_analytics.py` → 80/80 PASS. No existing behaviour changed.

## Operational notes

`CovarianceEstimator(history_file="data/apy_history.json")` is read-only
and safe to instantiate per-cycle. The full whitelist (~15 pools × 90
days) computes in <5 ms on a 2020 MacBook Air. No DB connection
required; no network calls.

`summary(window_days=90)` returns a JSON-ready dict suitable for direct
write to `data/covariance_summary.json` — that file is the planned
Phase 2 dashboard input.
