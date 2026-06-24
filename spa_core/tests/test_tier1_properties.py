"""
spa_core/tests/test_tier1_properties.py — PROPERTY-BASED tests for Tier-1 maths.

No external 'hypothesis' dependency (stdlib-only contract). Instead we generate
DETERMINISTIC random inputs with a single seeded random.Random(42) and loop ~100
cases per property, asserting an invariant that must hold for EVERY case. A seeded
PRNG keeps the suite bit-for-bit reproducible while still exercising a broad,
property-style input space.

Properties:
  • deflated_sharpe.probabilistic_sharpe_ratio ∈ [0, 1]                       (range)
  • deflated_sharpe: higher per-period SR ⇒ higher PSR                        (monotonic)
  • cost_model.net_of_cost_apy: net <= gross; more rebalances ⇒ more cost     (frictions)
  • tail_risk.strategy_tail_risk: 0 <= tail_risk_pct <= max tier loss         (bounds)
  • oos blended yield: weighted avg ∈ [min protocol apy, max protocol apy]    (convexity)
  • stress.stress_strategy: worst_case_pct <= base_net_apy_pct               (downside)
  • nav_proof: computed_nav == sum(positions) + cash + accrued (exact)        (reconcile)

Pure stdlib + pytest. Deterministic (seed 42). LLM-forbidden.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import random

import pytest

from spa_core.backtesting.tier1 import deflated_sharpe as ds
from spa_core.backtesting.tier1 import cost_model
from spa_core.backtesting.tier1 import tail_risk
from spa_core.backtesting.tier1 import oos as oos_mod
from spa_core.backtesting.tier1 import stress
from spa_core.backtesting.tier1 import nav_proof

N_CASES = 100
SEED = 42

# All protocols the tier map knows about, plus 'cash' and an unregistered name
# (which the model maps to the conservative T2 default → 1.5%).
_KNOWN_PROTOCOLS = list(tail_risk.PROTOCOL_TIER.keys())
_ALLOC_KEYS = _KNOWN_PROTOCOLS + ["cash", "some_unregistered_protocol"]
_MAX_TIER_LOSS = max(tail_risk.TIER_EXPECTED_LOSS_PCT.values())  # 5.0 (T3)


def _rng() -> random.Random:
    return random.Random(SEED)


def _random_allocation(rng: random.Random) -> dict:
    """A random allocation over a random subset of known protocols (weights > 0)."""
    k = rng.randint(1, 5)
    chosen = rng.sample(_ALLOC_KEYS, k)
    return {p: round(rng.uniform(0.01, 1.0), 4) for p in chosen}


# ---------------------------------------------------------------------------
# 1. PSR ∈ [0, 1] for random (sr, n, skew, kurt)
# ---------------------------------------------------------------------------
def test_psr_in_unit_interval():
    rng = _rng()
    for _ in range(N_CASES):
        sr = rng.uniform(-1.0, 1.0)        # per-period Sharpe
        n = rng.randint(2, 1000)
        skew = rng.uniform(-2.0, 2.0)
        kurt = rng.uniform(1.5, 10.0)
        psr = ds.probabilistic_sharpe_ratio(sr, n, skew=skew, kurt=kurt)
        assert 0.0 <= psr <= 1.0, (
            f"PSR out of [0,1]: {psr} for sr={sr} n={n} skew={skew} kurt={kurt}")


# ---------------------------------------------------------------------------
# 2. Monotonicity: higher per-period SR ⇒ higher (or equal) PSR.
#    Hold n, skew=0, kurt=3 (Normal) fixed within each pair so the only thing
#    that changes is the Sharpe; PSR is then strictly increasing in SR.
# ---------------------------------------------------------------------------
def test_psr_monotonic_in_sharpe():
    rng = _rng()
    for _ in range(N_CASES):
        n = rng.randint(5, 2000)
        a = rng.uniform(-1.0, 1.0)
        b = rng.uniform(-1.0, 1.0)
        lo, hi = (a, b) if a < b else (b, a)
        if hi - lo < 1e-6:
            continue  # essentially equal SR — skip degenerate pair
        psr_lo = ds.probabilistic_sharpe_ratio(lo, n, skew=0.0, kurt=3.0)
        psr_hi = ds.probabilistic_sharpe_ratio(hi, n, skew=0.0, kurt=3.0)
        assert psr_hi >= psr_lo - 1e-12, (
            f"PSR not monotonic: sr {lo}->{hi} gave PSR {psr_lo}->{psr_hi} (n={n})")


# ---------------------------------------------------------------------------
# 3. net_of_cost_apy: net <= gross always; more rebalances ⇒ more cost.
# ---------------------------------------------------------------------------
def test_net_le_gross():
    rng = _rng()
    for _ in range(N_CASES):
        gross = rng.uniform(-5.0, 30.0)
        capital = rng.uniform(1_000.0, 1_000_000.0)
        n_pos = rng.randint(1, 12)
        rebal = rng.randint(1, 365)
        turnover = rng.uniform(0.0, 5.0)
        chain = rng.choice(["ethereum", "arbitrum", "base", "polygon", "blended"])
        multichain = rng.random() < 0.5
        r = cost_model.net_of_cost_apy(
            gross, capital, n_positions=n_pos, rebalances_per_year=rebal,
            annual_turnover=turnover, chain=chain, multichain=multichain)
        # cost is a non-negative drag → net <= gross (within rounding noise)
        assert r["net_apy_pct"] <= r["gross_apy_pct"] + 1e-6
        assert r["total_cost_pct"] >= -1e-9


def test_more_rebalances_more_cost():
    rng = _rng()
    for _ in range(N_CASES):
        gross = rng.uniform(0.0, 30.0)
        capital = rng.uniform(1_000.0, 1_000_000.0)
        n_pos = rng.randint(1, 12)
        turnover = rng.uniform(0.1, 5.0)
        chain = rng.choice(["ethereum", "arbitrum", "base", "polygon", "blended"])
        multichain = rng.random() < 0.5
        few = rng.randint(1, 50)
        more = few + rng.randint(1, 50)
        cost_few = cost_model.net_of_cost_apy(
            gross, capital, n_positions=n_pos, rebalances_per_year=few,
            annual_turnover=turnover, chain=chain, multichain=multichain)["total_cost_pct"]
        cost_more = cost_model.net_of_cost_apy(
            gross, capital, n_positions=n_pos, rebalances_per_year=more,
            annual_turnover=turnover, chain=chain, multichain=multichain)["total_cost_pct"]
        # gas (and bridge if multichain) scale with rebalances → strictly more cost
        assert cost_more > cost_few - 1e-9, (
            f"more rebalances ({few}->{more}) did not increase cost "
            f"({cost_few}->{cost_more})")


# ---------------------------------------------------------------------------
# 4. tail_risk: 0 <= tail_risk_pct <= max tier expected-loss.
# ---------------------------------------------------------------------------
def test_tail_risk_bounds():
    rng = _rng()
    for _ in range(N_CASES):
        alloc = _random_allocation(rng)
        tr = tail_risk.strategy_tail_risk(alloc)
        trp = tr["tail_risk_pct"]
        assert trp >= 0.0, f"tail_risk_pct negative: {trp} for {alloc}"
        assert trp <= _MAX_TIER_LOSS + 1e-9, (
            f"tail_risk_pct {trp} exceeds max tier loss {_MAX_TIER_LOSS} for {alloc}")
        # tier_mix weights sum to ~1 (renormalised over non-zero weights).
        # The module rounds each tier weight to 4 dp, so accumulated rounding
        # can drift by up to ~(#tiers * 5e-5); tolerate that granularity.
        assert abs(sum(tr["tier_mix"].values()) - 1.0) < 1e-3


# ---------------------------------------------------------------------------
# 5. oos blended weighted-average APY ∈ [min protocol apy, max protocol apy].
#    Build a synthetic series_map (constant APY per protocol over a shared axis)
#    so the blended weighted average must fall between the per-protocol extremes.
# ---------------------------------------------------------------------------
def _synthetic_series(protocols, apys, n_days):
    """{protocol: {date: apy}} — each protocol has a CONSTANT apy over n_days."""
    axis = [f"2026-01-{d:02d}" if d <= 31 else f"2026-02-{d - 31:02d}"
            for d in range(1, n_days + 1)]
    return {p: {d: a for d in axis} for p, a in zip(protocols, apys)}


def test_oos_blended_within_protocol_range():
    rng = _rng()
    pool = [p for p in _KNOWN_PROTOCOLS]
    for _ in range(N_CASES):
        k = rng.randint(2, 4)
        protocols = rng.sample(pool, k)
        apys = [rng.uniform(0.005, 0.20) for _ in protocols]      # 0.5%..20% decimal
        weights = {p: round(rng.uniform(0.05, 1.0), 4) for p in protocols}
        n_days = 2 * oos_mod.MIN_WINDOW_DAYS + rng.randint(0, 20)  # enough history
        series = _synthetic_series(protocols, apys, n_days)
        res = oos_mod.oos_check(weights, series)
        assert res["status"] == "ok", f"unexpected status {res} for {weights}"
        lo = min(apys) * 100.0   # decimal → percent (oos reports percent)
        hi = max(apys) * 100.0
        for key in ("in_sample_apy_pct", "out_of_sample_apy_pct"):
            v = res[key]
            assert lo - 1e-6 <= v <= hi + 1e-6, (
                f"{key}={v} outside protocol APY range [{lo}, {hi}] for weights={weights}")


# ---------------------------------------------------------------------------
# 6. stress: worst_case_pct <= base_net_apy_pct.
#    depeg and exploit subtract a non-negative loss from net → both <= net,
#    so worst_case = min(scenarios) <= net for ANY sign of net.
# ---------------------------------------------------------------------------
def test_stress_worst_le_base():
    rng = _rng()
    for _ in range(N_CASES):
        net = rng.uniform(-10.0, 25.0)
        alloc = _random_allocation(rng)
        st = stress.stress_strategy(net, alloc)
        # use the rounded base the module reports (it rounds to 3 dp)
        base = st["base_net_apy_pct"]
        assert st["worst_case_pct"] <= base + 1e-6, (
            f"worst_case {st['worst_case_pct']} > base {base} for net={net} alloc={alloc} "
            f"scenarios={st['scenarios']}")
        # worst_scenario names one of the computed scenarios
        assert st["worst_scenario"] in ("rate_collapse", "stable_depeg", "t2_exploit")


# ---------------------------------------------------------------------------
# 7. nav reconcile: computed_nav == sum(positions) + cash + accrued (exact).
#    Replicate the module's own per-component rounding (it rounds each component
#    to 8 dp then sums and rounds to 8 dp). Monkeypatch the loaders per case.
# ---------------------------------------------------------------------------
def test_nav_reconcile_exact(monkeypatch):
    rng = _rng()
    for _ in range(N_CASES):
        n_pos = rng.randint(0, 6)
        positions = {f"proto_{i}": round(rng.uniform(0.0, 100_000.0), 8)
                     for i in range(n_pos)}
        cash = round(rng.uniform(0.0, 50_000.0), 8)
        accrued = round(rng.uniform(-1_000.0, 5_000.0), 8)

        monkeypatch.setattr(nav_proof, "_load_positions", lambda positions=positions: dict(positions))
        monkeypatch.setattr(nav_proof, "_load_cash", lambda cash=cash: cash)
        monkeypatch.setattr(nav_proof, "_load_accrued_yield", lambda accrued=accrued: accrued)
        monkeypatch.setattr(nav_proof, "_load_reported_equity", lambda: None)

        nav = nav_proof.compute_nav()
        # the module rounds deployed/cash/accrued each to 8dp, then sums, then rounds to 8dp
        expected = round(
            round(sum(positions.values()), 8) + round(cash, 8) + round(accrued, 8), 8)
        assert nav["computed_nav_usd"] == expected, (
            f"NAV {nav['computed_nav_usd']} != expected {expected} "
            f"(positions={positions} cash={cash} accrued={accrued})")
        assert nav["deployed_usd"] == round(sum(positions.values()), 8)

        # And the published proof verifies against itself (anyone-can-verify property).
        proof = nav_proof.build_proof(write=False)
        assert nav_proof.verify_proof(proof) is True
