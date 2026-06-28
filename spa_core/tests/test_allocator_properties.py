"""
spa_core/tests/test_allocator_properties.py — PROPERTY / METAMORPHIC tests for
StrategyAllocator.allocate() — the money-path allocator the daily cycle runs.

WHY THIS FILE EXISTS
--------------------
allocate() is the exact surface where a SILENT breach of a risk limit (tier
concentration cap, T2-total cap, TVL floor, cash buffer) would let real capital
sit in a non-compliant book at go-live. Before this file the allocator was only
EXAMPLE-tested (19 hand-picked cases in test_allocator.py). This suite feeds
~200 randomized — including deliberately DEGENERATE — adapter snapshots into
allocate() per property and asserts an invariant that must hold for EVERY output.

STYLE (mirrors spa_core/tests/test_tier1_properties.py)
-------------------------------------------------------
NO 'hypothesis' dependency — that violates the stdlib-only runtime contract.
Instead a single seeded random.Random(SEED) generates deterministic inputs and
each property loops N_CASES times. Bit-for-bit reproducible, fail-CLOSED.

SCOPE — what allocate() DOES vs DOES NOT guarantee (verified against source)
----------------------------------------------------------------------------
allocate() DOES enforce, and these are asserted as invariants:
  * per-protocol tier caps (T1 ≤ 40%, T2 ≤ 20%)
  * T2-total ≤ 50% (ADR-019)
  * TVL floor ≥ $5M (pools below floor are filtered BEFORE weighting; the only
    exception is the explicit all-sub-floor fallback, which is asserted too)
  * sum(weights) ≤ 1.0 with cash buffer = 1 - allocated ≥ 0
  * no negative weights
  * allocated protocols ⊆ input protocols
  * determinism (same snapshot → identical output)

allocate() DOES *NOT* itself enforce (confirmed in source — do NOT assert here):
  * the APY band [1%, 30%] — that is the RiskPolicy.check_new_position() GATE
    downstream in cycle_runner, NOT the allocator. allocate() will happily weight
    a 99%-APY or inf-APY pool; the gate rejects the resulting position. Asserting
    an APY-band invariant on allocate() output would be a FALSE property, so we
    instead PIN the real contract: the allocator never lets a non-finite APY
    poison the expected_apy_pct metric (regression guard for the bug fixed
    alongside this suite).
  * the ≤8-protocol count (ALLOC-002) — that collapse happens DOWNSTREAM in
    cycle_runner / policy_enforcer, not inside allocate(). We therefore pin the
    ALLOC-002 bar as a SEPARATE check against policy_enforcer.RULES rather than
    asserting allocate() already obeys it.

Pure stdlib + pytest. Deterministic (seed 42). LLM-forbidden.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import math
import random
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.allocator.allocator import AllocationResult, StrategyAllocator

N_CASES = 200
SEED = 42

T1_CAP = StrategyAllocator.T1_CAP            # 0.40
T2_CAP = StrategyAllocator.T2_CAP            # 0.20
T2_TOTAL_CAP = StrategyAllocator.T2_TOTAL_CAP  # 0.50
TVL_FLOOR = StrategyAllocator.TVL_FLOOR_USD   # 5_000_000
CAP = StrategyAllocator.CAPITAL               # 100_000
_TOL = 1e-6

# Models with a fn(adapters) signature — risk_adjusted needs risk_scores.json so
# it is exercised via the default-construction path, not driven here directly.
_MODELS = ("equal_weight", "best_apy", "risk_parity")

# A small pool of protocol names so duplicates / overlaps occur naturally.
_NAMES = [f"proto_{i}" for i in range(12)]


# ---------------------------------------------------------------------------
# Harness: write a snapshot to a temp file and allocate() against it, fully
# isolated from the real data/ directory (registry pointed at a missing path,
# shadow strategy loop disabled — both would otherwise pull live state in).
# ---------------------------------------------------------------------------
def _allocate(tmpdir: Path, adapters: list[dict], model: str) -> AllocationResult:
    status = tmpdir / "status.json"
    payload = {
        "adapters": [
            {
                "protocol": a["protocol"],
                "apy_pct": a["apy_pct"],
                "tvl_usd": a["tvl_usd"],
                "tier": a["tier"],
                "status": a.get("status", "ok"),
            }
            for a in adapters
        ]
    }
    status.write_text(json.dumps(payload), encoding="utf-8")
    allocator = StrategyAllocator(
        status_path=status,
        registry_path=tmpdir / "_no_registry.json",  # isolate from real registry
        strategy_loop_enabled=False,                  # isolate from shadow loop
        live_apy_provider={},                         # WS1.1: isolate from network feed
    )
    return allocator.allocate(model=model)


def _rng() -> random.Random:
    return random.Random(SEED)


def _random_adapters(rng: random.Random, *, allow_degenerate: bool) -> list[dict]:
    """A random adapter snapshot.

    When allow_degenerate=True, deliberately injects the nasty inputs a real
    feed can produce: NaN/inf APY, zero/negative APY, sub-floor or zero/negative
    TVL, duplicate protocol names, all-T2 sets, single-protocol and empty sets.
    """
    n = rng.randint(0, 7)  # include the EMPTY set (n==0)
    adapters: list[dict] = []
    for _ in range(n):
        name = rng.choice(_NAMES)  # repeats → duplicate protocols on purpose
        tier = rng.choice(["T1", "T2", "T3", "t1", "t2"])
        if allow_degenerate and rng.random() < 0.35:
            apy = rng.choice(
                [float("nan"), float("inf"), float("-inf"), 0.0, -5.0, 1e9, 99.0]
            )
        else:
            apy = rng.uniform(0.5, 25.0)
        if allow_degenerate and rng.random() < 0.35:
            tvl = rng.choice([0.0, -1.0, 1.0, 4_999_999.0, float("inf"), 1e3])
        else:
            tvl = rng.uniform(5_000_000.0, 5_000_000_000.0)
        adapters.append(
            {"protocol": name, "apy_pct": apy, "tvl_usd": tvl, "tier": tier}
        )
    return adapters


# ── tier classification mirrors the allocator (anything not T1 counts as T2) ──
def _is_t1(tier: str) -> bool:
    return str(tier).upper() == "T1"


def _tier_cap(tier: str) -> float:
    return T1_CAP if _is_t1(tier) else T2_CAP


# Replicate the allocator's OWN survivor computation so the test classifies each
# funded protocol exactly as allocate() did — otherwise duplicate protocol names
# (which the generator produces on purpose) make tier/TVL ambiguous and yield
# phantom "breaches" that are really test-side mis-classification.
#
# allocate() does, in order:
#   1. keep adapters with status in {ok, partial};
#   2. _filter_by_tvl: keep finite TVL ≥ floor; if NONE survive, fall back to the
#      finite-TVL subset of the inputs (sub-floor-but-finite pools);
#   3. build tier_map / tvl_map as dict comprehensions over the survivors →
#      LAST occurrence of a duplicate protocol name wins.
def _survivors(adapters: list[dict]) -> tuple[dict[str, str], dict[str, float]]:
    live = [a for a in adapters if a.get("status", "ok") in ("ok", "partial")]

    def _finite(t) -> bool:
        return isinstance(t, (int, float)) and not isinstance(t, bool) and math.isfinite(t)

    kept = [a for a in live if _finite(a["tvl_usd"]) and a["tvl_usd"] >= TVL_FLOOR]
    if not kept and live:
        # all-sub-floor fallback: finite-TVL inputs only (non-finite excluded).
        kept = [a for a in live if _finite(a["tvl_usd"])]
    tier_map: dict[str, str] = {a["protocol"]: a["tier"] for a in kept}  # last wins
    tvl_map: dict[str, float] = {a["protocol"]: a["tvl_usd"] for a in kept}
    return tier_map, tvl_map


def _tier_of(adapters: list[dict]) -> dict[str, str]:
    return _survivors(adapters)[0]


# Set of input protocol names (ok/partial status only — matches _load_adapters).
def _input_protocols(adapters: list[dict]) -> set[str]:
    return {
        a["protocol"]
        for a in adapters
        if a.get("status", "ok") in ("ok", "partial")
    }


# ---------------------------------------------------------------------------
# INVARIANT 1: every weight is non-negative.  (no_negative_weights)
# ---------------------------------------------------------------------------
def test_inv_no_negative_weights():
    rng = _rng()
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        for _ in range(N_CASES):
            model = rng.choice(_MODELS)
            adapters = _random_adapters(rng, allow_degenerate=True)
            res = _allocate(tmp, adapters, model)
            for p, w in res.target_weights.items():
                assert w >= -_TOL, f"negative weight {p}={w} model={model}"


# ---------------------------------------------------------------------------
# INVARIANT 2: sum(weights) ≤ 1.0  AND  cash buffer = 1 - allocated ≥ 0.
#              (the allocator NEVER over-deploys; remainder is honest cash.)
# ---------------------------------------------------------------------------
def test_inv_sum_le_one_with_cash_buffer():
    rng = _rng()
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        for _ in range(N_CASES):
            model = rng.choice(_MODELS)
            adapters = _random_adapters(rng, allow_degenerate=True)
            res = _allocate(tmp, adapters, model)
            allocated = sum(res.target_weights.values())
            # weights are each rounded to 6 dp, so summing N of them can drift by
            # ~N·5e-7; tolerate that rounding granularity (the real invariant is
            # "no meaningful over-deploy", not bit-exact ≤1.0).
            assert allocated <= 1.0 + 1e-4, f"over-deployed {allocated} model={model}"
            # reported cash buffer is consistent and non-negative
            assert res.unallocated_pct >= -_TOL
            assert res.cash_pct >= -_TOL
            assert abs((1.0 - allocated) - res.unallocated_pct) < 1e-4


# ---------------------------------------------------------------------------
# INVARIANT 3: cash buffer ≥ 5% WHENEVER the allocator left the book fully
#   capped (i.e. it could not place 100%). The allocator's job is to never
#   FORCE a sub-5% cash book: if it deploys <100% the remainder IS the buffer.
#   When it deploys ~100% (enough T1 headroom) cash can legitimately be ~0 and
#   the 5% floor is then the RiskPolicy gate's concern, not the allocator's —
#   so we assert the policy-relevant direction: allocated ≤ 95% OR ~100%.
# ---------------------------------------------------------------------------
def test_inv_cash_buffer_or_full_deploy():
    rng = _rng()
    min_cash = 0.05
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        for _ in range(N_CASES):
            model = rng.choice(_MODELS)
            adapters = _random_adapters(rng, allow_degenerate=True)
            res = _allocate(tmp, adapters, model)
            allocated = sum(res.target_weights.values())
            # Either a ≥5% buffer is held, or the book is (near-)fully deployed.
            assert (1.0 - allocated) >= min_cash - _TOL or allocated >= 1.0 - 1e-4, (
                f"book deployed {allocated:.4f}: neither ≥5% cash nor full "
                f"deploy, model={model}"
            )


# ---------------------------------------------------------------------------
# INVARIANT 4: no protocol exceeds its TIER cap (T1 ≤ 40%, T2 ≤ 20%).
#   This is THE concentration-breach guard that protects real capital.
# ---------------------------------------------------------------------------
def test_inv_per_protocol_tier_cap():
    rng = _rng()
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        for _ in range(N_CASES):
            model = rng.choice(_MODELS)
            adapters = _random_adapters(rng, allow_degenerate=True)
            tmap = _tier_of(adapters)
            res = _allocate(tmp, adapters, model)
            for p, w in res.target_weights.items():
                cap = _tier_cap(tmap.get(p, "T2"))
                # weights rounded to 6 dp → allow 6-dp rounding slack on the cap.
                assert w <= cap + 1e-4, (
                    f"tier-cap breach: {p}={w} > {cap} (tier={tmap.get(p)}) "
                    f"model={model}"
                )


# ---------------------------------------------------------------------------
# INVARIANT 5: total T2 weight ≤ 50% (ADR-019 T2-total cap).
# ---------------------------------------------------------------------------
def test_inv_t2_total_cap():
    rng = _rng()
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        for _ in range(N_CASES):
            model = rng.choice(_MODELS)
            adapters = _random_adapters(rng, allow_degenerate=True)
            tmap = _tier_of(adapters)
            res = _allocate(tmp, adapters, model)
            t2_total = sum(
                w for p, w in res.target_weights.items() if not _is_t1(tmap.get(p, "T2"))
            )
            assert t2_total <= T2_TOTAL_CAP + 1e-4, (
                f"T2-total breach: {t2_total} > {T2_TOTAL_CAP} model={model}"
            )


# ---------------------------------------------------------------------------
# INVARIANT 6: every allocated protocol (weight > 0) was in the input set.
#   The allocator must never conjure a position out of nothing.
# ---------------------------------------------------------------------------
def test_inv_allocated_subset_of_input():
    rng = _rng()
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        for _ in range(N_CASES):
            model = rng.choice(_MODELS)
            adapters = _random_adapters(rng, allow_degenerate=True)
            inputs = _input_protocols(adapters)
            res = _allocate(tmp, adapters, model)
            for p, w in res.target_weights.items():
                if w > _TOL:
                    assert p in inputs, (
                        f"phantom allocation: {p}={w} not in input {inputs} "
                        f"model={model}"
                    )


# ---------------------------------------------------------------------------
# INVARIANT 7: every pool that received a POSITIVE weight had TVL ≥ $5M —
#   EXCEPT the explicit all-sub-floor fallback the allocator documents (when
#   every adapter is below floor it keeps them so the gate, not the allocator,
#   is the visible blocker). We assert: either every funded pool clears the
#   floor, OR the result is flagged as that fallback (all inputs sub-floor).
# ---------------------------------------------------------------------------
def test_inv_funded_pools_clear_tvl_floor_or_fallback():
    rng = _rng()
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        for _ in range(N_CASES):
            model = rng.choice(_MODELS)
            adapters = _random_adapters(rng, allow_degenerate=True)

            def _clears_floor(t) -> bool:
                return (
                    isinstance(t, (int, float))
                    and not isinstance(t, bool)
                    and math.isfinite(t)
                    and t >= TVL_FLOOR
                )

            # Survivor TVL map = exactly what the allocator weighted against.
            _tmap, tvl_of = _survivors(adapters)
            inputs = _input_protocols(adapters)
            # The all-sub-floor fallback fires when NO input pool clears the floor.
            all_sub_floor = bool(inputs) and not any(
                _clears_floor(a["tvl_usd"])
                for a in adapters
                if a.get("status", "ok") in ("ok", "partial")
            )
            res = _allocate(tmp, adapters, model)
            funded = [p for p, w in res.target_weights.items() if w > _TOL]
            if all_sub_floor:
                # fallback path is allowed to fund below-floor (but finite) pools
                # so the RiskPolicy gate, not the allocator, is the visible blocker.
                continue
            for p in funded:
                tvl = tvl_of.get(p, 0.0)
                assert _clears_floor(tvl), (
                    f"funded sub-floor pool {p} tvl={tvl} (floor={TVL_FLOOR}) "
                    f"outside fallback, model={model}"
                )


# ---------------------------------------------------------------------------
# INVARIANT 8: target_usd is consistent with target_weights × capital.
# ---------------------------------------------------------------------------
def test_inv_target_usd_matches_weights():
    rng = _rng()
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        for _ in range(N_CASES):
            model = rng.choice(_MODELS)
            adapters = _random_adapters(rng, allow_degenerate=False)  # clean: USD exact
            res = _allocate(tmp, adapters, model)
            for p, w in res.target_weights.items():
                # target_weights is round(w,6) and target_usd is round(w*CAP,2)
                # from the SAME pre-rounding weight. Reconstructing usd from the
                # published 6-dp weight can differ by up to CAP×0.5e-6 = $0.05 of
                # rounding (e.g. 0.16666666 → weight 0.166667 → $16666.70 vs the
                # true $16666.67). Allow that rounding band.
                assert abs(res.target_usd.get(p, 0.0) - round(w * CAP, 2)) <= 0.06, (
                    f"usd/weight mismatch {p}: {res.target_usd.get(p)} != {w*CAP}"
                )


# ---------------------------------------------------------------------------
# INVARIANT 9: expected_apy_pct is ALWAYS finite — a NaN/Inf APY in the feed
#   must never poison the portfolio APY metric (regression guard for the
#   fail-closed sanitiser added in allocator.allocate()).
# ---------------------------------------------------------------------------
def test_inv_expected_apy_always_finite():
    rng = _rng()
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        for _ in range(N_CASES):
            model = rng.choice(_MODELS)
            adapters = _random_adapters(rng, allow_degenerate=True)
            res = _allocate(tmp, adapters, model)
            assert isinstance(res.expected_apy_pct, (int, float))
            assert math.isfinite(res.expected_apy_pct), (
                f"expected_apy_pct not finite: {res.expected_apy_pct} model={model}"
            )


# ---------------------------------------------------------------------------
# INVARIANT 10: result is well-typed and self-consistent — t1_pct + t2_pct
#   equals allocated_pct, and reported allocated/unallocated partition 1.0.
# ---------------------------------------------------------------------------
def test_inv_tier_breakdown_partitions_book():
    rng = _rng()
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        for _ in range(N_CASES):
            model = rng.choice(_MODELS)
            adapters = _random_adapters(rng, allow_degenerate=True)
            res = _allocate(tmp, adapters, model)
            assert abs((res.t1_pct + res.t2_pct) - res.allocated_pct) < 1e-4, (
                f"t1+t2 ({res.t1_pct}+{res.t2_pct}) != allocated {res.allocated_pct}"
            )
            assert abs((res.allocated_pct + res.unallocated_pct) - 1.0) < 1e-4, (
                f"allocated+unallocated != 1: {res.allocated_pct}+{res.unallocated_pct}"
            )


# ---------------------------------------------------------------------------
# INVARIANT 11 (ALLOC-002 bar, checked at the policy_enforcer surface).
#   allocate() itself does NOT collapse to ≤8 protocols — that is downstream.
#   So we pin the bar where it lives: the funded set, if it ever exceeds 8,
#   would be collapsed by policy_enforcer. With ≤7 input names per case the
#   allocator output already satisfies ≤8, so we assert the count never EXCEEDS
#   the documented ALLOC-002 limit on allocate() output (a tighter pin: the
#   allocator must not invent MORE positions than it was given, capped at 8).
# ---------------------------------------------------------------------------
def test_inv_protocol_count_within_alloc002_bar():
    from spa_core.risk.policy_enforcer import RULES

    max_protocols = int(RULES["max_protocols"])  # 8
    rng = _rng()
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        for _ in range(N_CASES):
            model = rng.choice(_MODELS)
            adapters = _random_adapters(rng, allow_degenerate=True)
            n_inputs = len(_input_protocols(adapters))  # ≤ len(_NAMES) but ≤7 here
            res = _allocate(tmp, adapters, model)
            funded = [p for p, w in res.target_weights.items() if w > _TOL]
            # allocator never funds MORE distinct pools than it was given …
            assert len(funded) <= n_inputs
            # … and, given our ≤7-name generator, stays within the ALLOC-002 bar.
            assert len(funded) <= max_protocols, (
                f"funded {len(funded)} > ALLOC-002 max {max_protocols} model={model}"
            )


# ---------------------------------------------------------------------------
# DETERMINISM: same snapshot → byte-identical allocation (no hidden RNG/clock
#   dependence in the weighting, only the timestamp differs).
# ---------------------------------------------------------------------------
def test_determinism_same_input_same_output():
    rng = _rng()
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        for _ in range(N_CASES):
            model = rng.choice(_MODELS)
            adapters = _random_adapters(rng, allow_degenerate=True)
            r1 = _allocate(tmp, adapters, model)
            r2 = _allocate(tmp, adapters, model)
            assert r1.target_weights == r2.target_weights, "weights non-deterministic"
            assert r1.target_usd == r2.target_usd, "usd non-deterministic"
            # expected_apy can be the same finite value (or both 0); compare exact
            assert r1.expected_apy_pct == r2.expected_apy_pct


# ---------------------------------------------------------------------------
# METAMORPHIC 1: scaling ALL TVLs up never REMOVES an eligible pool.
#   If a pool is funded at the base TVLs, it is still funded after every TVL is
#   multiplied by a factor ≥ 1 (it only becomes MORE eligible vs the floor).
# ---------------------------------------------------------------------------
def test_metamorphic_scale_tvl_up_keeps_eligible():
    rng = _rng()
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        for _ in range(N_CASES):
            model = rng.choice(_MODELS)
            # use clean finite TVLs so scaling is well-defined
            adapters = _random_adapters(rng, allow_degenerate=False)
            base = _allocate(tmp, adapters, model)
            funded_base = {p for p, w in base.target_weights.items() if w > _TOL}
            factor = rng.uniform(1.0, 50.0)
            scaled = [
                {**a, "tvl_usd": a["tvl_usd"] * factor} for a in adapters
            ]
            after = _allocate(tmp, scaled, model)
            funded_after = {p for p, w in after.target_weights.items() if w > _TOL}
            # every base-funded pool remains funded after scaling TVL up
            assert funded_base <= funded_after, (
                f"scaling TVL ×{factor:.1f} dropped pools "
                f"{funded_base - funded_after} model={model}"
            )


# ---------------------------------------------------------------------------
# METAMORPHIC 2: raising ONE pool's APY (ceteris paribus) never LOWERS its own
#   weight, under an APY-sensitive model (best_apy). Build a clean all-T2 set so
#   the tier cap is uniform and the only mover is the targeted pool's APY.
# ---------------------------------------------------------------------------
def test_metamorphic_raise_apy_not_lower_own_weight():
    rng = _rng()
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        for _ in range(N_CASES):
            k = rng.randint(2, 5)
            names = rng.sample(_NAMES, k)
            adapters = [
                {
                    "protocol": p,
                    "apy_pct": rng.uniform(2.0, 10.0),
                    "tvl_usd": rng.uniform(1e7, 1e9),
                    "tier": "T2",
                }
                for p in names
            ]
            target = adapters[0]["protocol"]
            base = _allocate(tmp, adapters, "best_apy")
            w_before = base.target_weights.get(target, 0.0)
            bumped = [dict(a) for a in adapters]
            bumped[0]["apy_pct"] += rng.uniform(5.0, 15.0)  # strictly raise its APY
            after = _allocate(tmp, bumped, "best_apy")
            w_after = after.target_weights.get(target, 0.0)
            assert w_after >= w_before - _TOL, (
                f"raising {target} APY lowered its weight {w_before}->{w_after}"
            )


# ---------------------------------------------------------------------------
# METAMORPHIC 3: adding a SUB-FLOOR pool never changes the compliant allocation.
#   A pool below the $5M TVL floor is filtered before weighting, so injecting one
#   must leave the funded weights of the compliant pools untouched.
# ---------------------------------------------------------------------------
def test_metamorphic_add_subfloor_pool_is_noop():
    rng = _rng()
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        for _ in range(N_CASES):
            model = rng.choice(_MODELS)
            k = rng.randint(1, 4)
            names = rng.sample(_NAMES, k)
            adapters = [
                {
                    "protocol": p,
                    "apy_pct": rng.uniform(2.0, 12.0),
                    "tvl_usd": rng.uniform(1e7, 1e9),  # all clear the floor
                    "tier": rng.choice(["T1", "T2"]),
                }
                for p in names
            ]
            base = _allocate(tmp, adapters, model)
            # add a sub-floor pool with a fresh name
            spare = next(n for n in _NAMES if n not in names)
            with_junk = adapters + [
                {"protocol": spare, "apy_pct": 8.0, "tvl_usd": 1_000.0, "tier": "T2"}
            ]
            after = _allocate(tmp, with_junk, model)
            # the sub-floor pool must not be funded …
            assert after.target_weights.get(spare, 0.0) <= _TOL, (
                f"sub-floor pool {spare} got funded {after.target_weights.get(spare)}"
            )
            # … and the compliant pools' weights are unchanged.
            for p in names:
                assert abs(
                    base.target_weights.get(p, 0.0) - after.target_weights.get(p, 0.0)
                ) <= 1e-9, (
                    f"adding sub-floor pool moved {p}: "
                    f"{base.target_weights.get(p)} -> {after.target_weights.get(p)}"
                )


# ---------------------------------------------------------------------------
# DEGENERATE-PATH PROOF: the nastiest inputs (NaN/inf APY, negative/zero/sub-floor
#   TVL, duplicates, empty, single-protocol, all-T2) must FAIL CLOSED — allocate()
#   returns a valid AllocationResult (empty/cash or capped book) and NEVER raises,
#   NEVER breaches a cap, NEVER emits a non-finite metric. This proves the
#   degenerate path is exercised, not merely assumed.
# ---------------------------------------------------------------------------
def test_degenerate_inputs_fail_closed_no_crash():
    tmp_cases = [
        [],  # empty set
        [{"protocol": "solo", "apy_pct": float("nan"), "tvl_usd": 5e7, "tier": "T2"}],  # single NaN
        [{"protocol": "x", "apy_pct": float("inf"), "tvl_usd": float("inf"), "tier": "T1"}],
        [{"protocol": "x", "apy_pct": -10.0, "tvl_usd": -1.0, "tier": "T2"}],  # all negative
        [  # duplicate protocol name, conflicting tiers
            {"protocol": "dup", "apy_pct": 5.0, "tvl_usd": 5e7, "tier": "T1"},
            {"protocol": "dup", "apy_pct": 9.0, "tvl_usd": 5e7, "tier": "T2"},
        ],
        [  # everything sub-floor → documented fallback
            {"protocol": "a", "apy_pct": 5.0, "tvl_usd": 1.0, "tier": "T2"},
            {"protocol": "b", "apy_pct": 7.0, "tvl_usd": 2.0, "tier": "T2"},
        ],
        [  # 6× all-T2, each would want 1/6 > nothing, T2-total cap must bind
            {"protocol": f"t2_{i}", "apy_pct": 8.0, "tvl_usd": 5e7, "tier": "T2"}
            for i in range(6)
        ],
        [{"protocol": "nanapy", "apy_pct": float("nan"), "tvl_usd": float("nan"), "tier": "T2"}],
    ]
    proved_no_crash = 0
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        for adapters in tmp_cases:
            for model in _MODELS:
                # MUST NOT RAISE.
                res = _allocate(tmp, adapters, model)
                assert isinstance(res, AllocationResult)
                # finite metric
                assert math.isfinite(res.expected_apy_pct)
                # non-negative, ≤1 deploy, caps hold even here
                allocated = sum(res.target_weights.values())
                assert allocated <= 1.0 + _TOL
                tmap = _tier_of(adapters)
                t2_total = 0.0
                for p, w in res.target_weights.items():
                    assert w >= -_TOL
                    cap = _tier_cap(tmap.get(p, "T2"))
                    assert w <= cap + _TOL, f"degenerate cap breach {p}={w}>{cap}"
                    if not _is_t1(tmap.get(p, "T2")):
                        t2_total += w
                assert t2_total <= T2_TOTAL_CAP + _TOL
                proved_no_crash += 1
    # proof that the degenerate path actually executed across all cases × models
    assert proved_no_crash == len(tmp_cases) * len(_MODELS) == 8 * 3


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-p", "no:randomly", "-q"]))
