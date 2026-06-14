# ADR-012 — Dynamic Kelly Sizing with Live APY Covariance

**Status:** Accepted — Phase 2 shipped in sprint v3.20.
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

---

## Phase 2 (sprint v3.20 — DONE)

### What was wired

* `spa_core/optimization/markowitz.py`
  * `PortfolioOptimizer.__init__` now accepts `live_covariance: bool | None = None`
    and `covariance_estimator: CovarianceEstimator | None = None`. When
    `live_covariance` is `None`, the constructor reads
    `SPA_LIVE_COVARIANCE` from the environment (default `0`, treated as
    OFF). When the flag is on and no estimator instance is passed, the
    optimizer lazy-imports and instantiates a default
    `CovarianceEstimator()` — this is a no-op when
    `data/apy_history.json` is missing.
  * `PortfolioOptimizer.estimate_covariance()` now branches: synthetic
    path is byte-identical to the v3.19 behaviour, live path calls
    `compute_covariance_matrix(window_days=90, protocols=..., tiers=...,
    synthetic_apys=...)` and projects the dict-of-dicts onto the
    canonical list-of-lists in declaration order.
  * Two new read-only attributes: `live_covariance: bool` and
    `covariance_source: "live" | "synthetic"`. The recommender attaches
    the latter to its top-level result for dashboard observability.
  * Private `_sigma` / `_corr` helpers are unchanged — they remain the
    synthetic source-of-truth and the same code the estimator falls
    back to when a protocol has fewer than `MIN_OBSERVATIONS` data
    points.

* `spa_core/optimization/recommender.py`
  * Reads `SPA_LIVE_COVARIANCE` once at the start of `recommend()`.
  * When live, instantiates a single shared `CovarianceEstimator`,
    pre-computes per-protocol volatility (with synthetic fallback when
    history is short), and uses `dynamic_kelly_fraction(...,
    volatility_pp=vol_map.get(key))` in the Step-1 Kelly pre-filter.
    Classical `kelly_fraction` path is preserved when the flag is off.
  * Same `estimator` and `live=True` flag are threaded into
    `PortfolioOptimizer(...)` so the recommender and optimizer share a
    single live view.
  * Top-level result dict now carries `"covariance_source": "live" |
    "synthetic"` so the dashboard / API can show which path produced
    the numbers.

* `spa_core/analytics/covariance_estimator.py`
  * Added a `__main__` CLI block that writes
    `data/covariance_summary.json` via `CovarianceEstimator().summary()`.
    Safe to invoke from cron / the export pipeline.

### Env flag mechanic

The single switch is `SPA_LIVE_COVARIANCE`. Truthy values: `1`, `true`,
`yes` (case-insensitive). Anything else — including unset, empty, `0`,
`false` — keeps the classical synthetic behaviour. The flag is read at
the boundaries (constructor / `recommend()` entry) so per-call overrides
are possible by passing `live_covariance=True` to
`PortfolioOptimizer(...)` directly.

### Safety property — "empty history = synthetic equivalent"

The estimator's fallback contract is unchanged from Phase 1:
`compute_volatility(key, synthetic_apy=apy)` returns
`apy * SYNTHETIC_APY_CV` (= `apy * 0.10`) when there are fewer than
`MIN_OBSERVATIONS=7` observations, and `compute_correlation` returns the
tier-based synthetic value (`0.6` same-tier, `0.2` cross-tier) when the
overlap is too short. These are exactly the values the old `_sigma /
_corr` helpers return.

Consequence: on the day of the cutover, with the env flag flipped but
`data/apy_history.json` still empty, **the covariance matrix and the
recommender output are provably numerically equivalent to the v3.19
code**. The new test `TestEmptyHistoryEqualsSynthetic` enforces this
guarantee per-matrix-cell to 1e-9 absolute tolerance.

### Rollback procedure

Single action: unset `SPA_LIVE_COVARIANCE` (or set it to `0`). No code
revert needed — the classical synthetic path is still present and
chosen by default. Restart the recommender process to clear cached env
reads in long-running daemons.

### Validation (this sprint)

* `spa_core/tests/test_phase2_integration.py` — 16 deterministic tests
  covering: env-unset byte-identity, empty-history numerical equivalence,
  populated-history measurable divergence, recommender end-to-end env
  wiring, and dynamic-Kelly call-site verification.
* Regression: `test_covariance_estimator` (44) + `test_dynamic_kelly`
  (39) + `test_optimization` (16) → 99/99 PASS. No existing behaviour
  changed.

### Phase 3 (post-go-live)

Remove the `SPA_LIVE_COVARIANCE` env flag entirely:
* `PortfolioOptimizer` constructor drops the kwarg; live covariance is
  the default and only path.
* `_sigma` / `_corr` are retained only as the in-process fallback for
  protocols with `<7` observations — same role they play today inside
  the estimator's fallback branch.
* `AllocationRecommender.recommend()` no longer branches on the flag;
  `dynamic_kelly_fraction` becomes the default everywhere.

Trigger: at least 14 days of populated `apy_history.json` for every
whitelisted protocol AND a clean diff in observed Kelly fractions vs
the synthetic baseline (< 20% drift per protocol). Targeted for the
sprint immediately following the 2026-07-15 go-live ADR.
