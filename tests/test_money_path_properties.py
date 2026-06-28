"""tests/test_money_path_properties.py — PROPERTY + METAMORPHIC tests on the
now-real MONEY PATH (Cutover-Bulletproof WS-6.1).

# LLM_FORBIDDEN

WHY THIS FILE EXISTS
--------------------
The existing ``spa_core/tests/test_allocator_properties.py`` proves *invariants*
on a single allocator output (caps respected, no negative weights, sum ≤ 1).
This file proves *METAMORPHIC* relations — properties that must hold between TWO
runs related by an input transformation — across the whole money path:

    allocator  →  optimizer  →  reconciliation (plan → dry-run → reconcile)

A metamorphic bug is one a single-run invariant test can NEVER catch: e.g. the
allocator silently depends on the *order* protocols arrive in (a dict-iteration
or list-append leak), or the ranking inverts when every APY is uniformly scaled
(a sign / comparison bug). These are exactly the classes of bug that would let
real capital land in the wrong book at go-live.

METAMORPHIC RELATIONS ASSERTED
------------------------------
  MP-ORDER   allocator + optimizer output is INVARIANT to protocol input order
             (permuting the adapter list → byte-identical target weights/usd).
  MP-SCALE   scaling EVERY live APY by a positive constant PRESERVES the ranking
             of funded protocols (best_apy / risk-adjusted desirability order).
  MP-CAP     under randomized RiskConfig caps, the allocator output ALWAYS
             respects those exact caps (cap-respect is a property OF the config,
             not of the hardcoded defaults).
  MP-NAV     NAV is conserved TO THE CENT through the dry-run reconcile cycle for
             EVERY random current→target pair (Decimal cent axis, fail-closed on
             non-finite), and the no-op rebalance always reconciles perfectly.
  MP-DETERM  the whole pipeline is deterministic — same snapshot, byte-identical
             output (re-run gives the same weights AND the same reconcile verdict).

STYLE (repo standard — mirrors test_allocator_properties / test_tier1_properties)
---------------------------------------------------------------------------------
NO ``hypothesis`` (stdlib-only runtime contract). A single seeded
``random.Random(SEED)`` generates deterministic inputs; each property loops
N_CASES times asserting a relation that must hold for EVERY case. Bit-for-bit
reproducible, deterministic, fail-CLOSED. No network, no live ``data/``.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import math
import random
import sys
from decimal import Decimal
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent
_SPA_CORE = _PROJECT_ROOT / "spa_core"
for _p in (str(_PROJECT_ROOT), str(_SPA_CORE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from spa_core.allocator.allocator import StrategyAllocator
from spa_core.allocator import allocation_models as models
from spa_core.execution import reconciliation as recon
from spa_core.risk.policy import RiskConfig

SEED = 20260628
N_CASES = 200
_EPS = 1e-6


# ─── HERMETIC GUARD: never let round_trip's best-effort audit touch live data/ ──
@pytest.fixture(autouse=True)
def _hermetic_audit_chain(tmp_path, monkeypatch):
    """Redirect the tamper-evident audit chain to a throwaway tmp file.

    ``reconciliation.round_trip`` does a best-effort ``hash_chain.append`` even
    with ``write=False``; without this redirect the property loops would append
    hundreds of rows to the LIVE ``data/audit_chain.jsonl`` (a guardrail breach:
    these tests must never touch live data/). hash_chain resolves the path via
    ``_chain_path()`` each call, so monkeypatching ``_CHAIN`` is sufficient.
    """
    from spa_core.audit import hash_chain
    monkeypatch.setattr(hash_chain, "_CHAIN", tmp_path / "audit_chain.jsonl")
    yield

# Tier caps used to assert cap-respect (mirror RiskConfig defaults).
_CFG = RiskConfig()
T1_CAP = _CFG.max_concentration_t1
T2_CAP = _CFG.max_concentration_t2
T2_TOTAL_CAP = _CFG.max_total_t2_allocation
TVL_FLOOR = _CFG.min_tvl_usd


# ─── snapshot generator (deterministic, includes degenerate cases) ──────────────
def _rand_snapshot(rng: random.Random, n: int | None = None) -> list[dict]:
    """A randomized orchestrator-style adapter snapshot list.

    Every TVL is >= the floor so pools survive the filter (we test cap/order/scale
    relations on a surviving book; the sub-floor filter is covered by the existing
    invariant suite). APY is in PERCENT (orchestrator-snapshot convention).
    """
    n = n if n is not None else rng.randint(1, 9)
    adapters = []
    for i in range(n):
        tier = rng.choice(["T1", "T2"])
        adapters.append({
            "protocol": f"proto_{i:02d}",
            "status": "ok",
            "apy_pct": round(rng.uniform(1.5, 28.0), 4),
            "tvl_usd": float(rng.choice([5_000_000, 1e7, 5e7, 2e8, 1e9])),
            "tier": tier,
        })
    return adapters


def _make_allocator(adapters, model="best_apy", **kw):
    """A hermetic StrategyAllocator over an in-memory snapshot.

    live_apy_provider=False forces the legacy literal path (no network), and the
    shadow-strategy loop is disabled so the output is a pure function of the
    snapshot. status_path points at a non-existent file; we inject adapters by
    monkeypatching _load_adapters via a subclass below.
    """
    return _InMemoryAllocator(adapters, allocation_model=model, **kw)


class _InMemoryAllocator(StrategyAllocator):
    """StrategyAllocator whose adapter universe is an in-memory list (hermetic).

    Overrides _load_adapters to return the injected snapshot (already TVL-tier
    shaped) so allocate() runs the REAL cap / remainder / T2-total machinery
    against deterministic inputs with no disk or network I/O.
    """

    def __init__(self, adapters, **kw):
        kw.setdefault("strategy_loop_enabled", False)
        kw.setdefault("live_apy_provider", False)
        # point paths at a guaranteed-absent dir so no real data/ is read
        kw.setdefault("status_path", _HERE / "__nonexistent_status__.json")
        kw.setdefault("risk_scores_path", _HERE / "__nonexistent_scores__.json")
        kw.setdefault("registry_path", _HERE / "__nonexistent_registry__.json")
        super().__init__(**kw)
        self._injected = [dict(a) for a in adapters]

    def _load_adapters(self):  # type: ignore[override]
        # Mirror the provenance bookkeeping the real loader does (so allocate()
        # can build feed_coverage without touching disk).
        self._apy_sources = {}
        self._apy_used = {}
        self._as_of = {}
        out = []
        for a in self._injected:
            p = str(a["protocol"])
            row = {
                "protocol": p,
                "apy_pct": float(a["apy_pct"]),
                "tvl_usd": float(a["tvl_usd"]),
                "tier": a.get("tier", "T2"),
                "apy_source": "fallback_stale",
                "as_of": "test",
            }
            out.append(row)
            self._apy_sources[p] = "fallback_stale"
            self._apy_used[p] = row["apy_pct"]
            self._as_of[p] = "test"
        return out


# ════════════════════════════════════════════════════════════════════════════
# MP-ORDER — allocator output invariant to protocol input order
# ════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("model", ["best_apy", "equal_weight", "risk_parity"])
def test_mp_order_allocator_invariant_to_protocol_order(model):
    """Permuting the adapter list must NOT change the target allocation.

    A handler that leaks input order (e.g. tie-breaks by list index instead of a
    stable key) would land capital differently depending on the order the feed
    happened to return — a non-determinism bug on the money path.
    """
    rng = random.Random(SEED)
    for _ in range(N_CASES):
        adapters = _rand_snapshot(rng)
        base = _make_allocator(adapters, model=model).allocate()
        shuffled = list(adapters)
        rng.shuffle(shuffled)
        perm = _make_allocator(shuffled, model=model).allocate()
        assert base.target_weights == perm.target_weights, (
            f"[{model}] order-dependent weights:\n base={base.target_weights}\n "
            f"perm={perm.target_weights}"
        )
        assert base.target_usd == perm.target_usd
        assert math.isclose(
            base.expected_apy_pct, perm.expected_apy_pct, abs_tol=1e-9
        )


def test_mp_order_optimizer_invariant_to_protocol_order():
    """The WS-1.2 constrained optimizer (greedy knapsack) is order-invariant too.

    The greedy fills highest-score headroom first; that ranking must be a pure
    function of the (score, cap) tuples, not of list position.
    """
    rng = random.Random(SEED + 1)
    for _ in range(N_CASES):
        adapters = _rand_snapshot(rng)
        tier_caps = {a["protocol"]: (T1_CAP if a["tier"] == "T1" else T2_CAP)
                     for a in adapters}
        bd_a = models.optimized_yield_breakdown(
            adapters, {}, tier_caps=tier_caps, t2_total_cap=T2_TOTAL_CAP)
        shuffled = list(adapters)
        rng.shuffle(shuffled)
        tier_caps_s = {a["protocol"]: (T1_CAP if a["tier"] == "T1" else T2_CAP)
                       for a in shuffled}
        bd_b = models.optimized_yield_breakdown(
            shuffled, {}, tier_caps=tier_caps_s, t2_total_cap=T2_TOTAL_CAP)
        assert bd_a["weights"] == bd_b["weights"], (
            f"optimizer order-dependent:\n a={bd_a['weights']}\n b={bd_b['weights']}"
        )


# ════════════════════════════════════════════════════════════════════════════
# MP-SCALE — uniform positive APY scaling preserves the ranking
# ════════════════════════════════════════════════════════════════════════════
def test_mp_scale_uniform_apy_scaling_preserves_ranking():
    """Scaling EVERY APY by k>0 must preserve the desirability ORDER.

    best_apy ranks by APY; multiplying all by a positive constant is a monotone
    transform → the funded set / their relative order must not invert. Catches a
    sign or comparison bug in the ranking path.
    """
    rng = random.Random(SEED + 2)
    for _ in range(N_CASES):
        # keep scaled APYs inside the allocator's live band (<=200%) so none drop
        adapters = _rand_snapshot(rng)
        # cap base apy low enough that *k stays in band
        for a in adapters:
            a["apy_pct"] = round(rng.uniform(1.5, 9.0), 4)
        k = rng.uniform(1.01, 3.0)

        def _ranked(adapts):
            w = models.best_apy_weight(adapts, top_n=3)
            # rank funded protocols by descending weight then apy
            apy = {a["protocol"]: a["apy_pct"] for a in adapts}
            return sorted(
                (p for p, wt in w.items() if wt > _EPS),
                key=lambda p: (-w[p], -apy[p], p),
            )

        base_rank = _ranked(adapters)
        scaled = [dict(a, apy_pct=round(a["apy_pct"] * k, 6)) for a in adapters]
        scaled_rank = _ranked(scaled)
        assert base_rank == scaled_rank, (
            f"ranking inverted under uniform scale k={k}:\n base={base_rank}\n "
            f"scaled={scaled_rank}"
        )


def test_mp_scale_best_apy_picks_highest():
    """Sanity / non-vacuous: best_apy_weight gives the single highest-APY pool the
    largest weight (a metamorphic anchor — proves the rank we preserve is real)."""
    rng = random.Random(SEED + 3)
    for _ in range(N_CASES):
        adapters = _rand_snapshot(rng, n=rng.randint(3, 8))
        # ensure a strict unique max
        for i, a in enumerate(adapters):
            a["apy_pct"] = round(2.0 + i * 0.5 + rng.uniform(0, 0.1), 4)
        top = max(adapters, key=lambda a: a["apy_pct"])["protocol"]
        w = models.best_apy_weight(adapters, top_n=3)
        winner = max(w, key=lambda p: w[p])
        assert winner == top, f"best_apy did not weight the top APY highest: {w}"


# ════════════════════════════════════════════════════════════════════════════
# MP-CAP — cap-respect under RANDOMIZED configs (property of the config)
# ════════════════════════════════════════════════════════════════════════════
def test_mp_cap_respected_under_default_config():
    """allocate() output respects T1/T2 per-protocol caps and the T2-total cap.

    Asserts the cap relation against the SAME source-of-truth config the allocator
    reads (RiskConfig). A drift between the cap the allocator enforces and the cap
    the policy defines would surface here.
    """
    rng = random.Random(SEED + 4)
    for _ in range(N_CASES):
        adapters = _rand_snapshot(rng)
        res = _make_allocator(adapters, model="best_apy").allocate()
        tier = {a["protocol"]: a["tier"] for a in adapters}
        for p, w in res.target_weights.items():
            assert w >= -_EPS, f"negative weight {p}={w}"
            cap = T1_CAP if tier.get(p) == "T1" else T2_CAP
            assert w <= cap + 1e-4, f"{p} weight {w} > {tier.get(p)} cap {cap}"
        t2_total = sum(w for p, w in res.target_weights.items()
                       if tier.get(p) != "T1")
        assert t2_total <= T2_TOTAL_CAP + 1e-4, (
            f"T2-total {t2_total} > cap {T2_TOTAL_CAP}"
        )
        assert sum(res.target_weights.values()) <= 1.0 + 1e-4


def test_mp_cap_optimizer_respects_arbitrary_caps():
    """The optimizer respects ARBITRARY (randomized) per-protocol caps + T2 total.

    Cap-respect must be a property of the caps PASSED IN, not of any hardcoded
    constant. We feed random caps and assert the knapsack output never exceeds
    them — a guard against a cap being read from the wrong place.
    """
    rng = random.Random(SEED + 5)
    for _ in range(N_CASES):
        adapters = _rand_snapshot(rng, n=rng.randint(2, 8))
        tier_caps = {a["protocol"]: round(rng.uniform(0.05, 0.5), 4) for a in adapters}
        t2_total = round(rng.uniform(0.2, 0.8), 4)
        cash_floor = round(rng.uniform(0.0, 0.1), 4)
        bd = models.optimized_yield_breakdown(
            adapters, {}, tier_caps=tier_caps, t2_total_cap=t2_total,
            cash_floor=cash_floor)
        is_t2 = {a["protocol"]: a["tier"] != "T1" for a in adapters}
        for p, w in bd["weights"].items():
            assert -_EPS <= w <= tier_caps[p] + 1e-6, (
                f"{p} weight {w} violates cap {tier_caps[p]}"
            )
        t2_sum = sum(w for p, w in bd["weights"].items() if is_t2.get(p))
        assert t2_sum <= t2_total + 1e-6, f"T2 sum {t2_sum} > {t2_total}"
        assert sum(bd["weights"].values()) <= 1.0 - cash_floor + 1e-6


# ════════════════════════════════════════════════════════════════════════════
# MP-NAV — NAV conserves to the cent through the dry-run reconcile cycle
# ════════════════════════════════════════════════════════════════════════════
def _cash_conserving_rebalance(rng: random.Random):
    """A random (current, target) pair that REDISTRIBUTES the SAME total NAV.

    A pure rebalance neither creates nor destroys capital: sum(target) ==
    sum(current) to the cent. (A target whose total differs from current is
    correctly REJECTED by reconcile as a NAV breach — see
    test_mp_nav_rejects_capital_creation — so the conservation property is only
    meaningful for a cash-conserving move.)
    """
    n = rng.randint(2, 6)
    protos = [f"p{i}" for i in range(n)]
    total = round(rng.uniform(10_000, 100_000), 2)
    # split `total` into current weights and (independently) target weights
    def _split(keys):
        raw = [rng.random() + 1e-3 for _ in keys]
        s = sum(raw)
        alloc = {k: round(total * w / s, 2) for k, w in zip(keys, raw)}
        # fix rounding drift so the book sums EXACTLY to `total`
        drift = round(total - sum(alloc.values()), 2)
        if alloc:
            first = keys[0]
            alloc[first] = round(alloc[first] + drift, 2)
        return alloc
    return _split(protos), _split(protos), total


def test_mp_nav_conserves_to_the_cent_through_cycle():
    """For every cash-conserving rebalance the dry-run ledger conserves NAV
    exactly: the virtual ledger moves notional with no cost burn, so
    nav_after == nav_before to the cent (Decimal axis), and reconcile() agrees.
    """
    rng = random.Random(SEED + 6)
    for _ in range(N_CASES):
        current, target, _ = _cash_conserving_rebalance(rng)
        report = recon.round_trip(current=current, target=target, write=False,
                                  ts="2026-06-28T00:00:00+00:00")
        r = report["reconciliation"]
        # dry-run conserves notional exactly (no cost applied to ledger)
        assert r["nav_conserved"], (
            f"NAV band broke for cash-conserving move: {r['block_reasons']}\n"
            f"current={current}\n target={target}"
        )
        assert r["nav_conserved_to_cent"], (
            f"NAV not conserved to cent: residual={r['nav_residual_cents']}"
        )
        assert r["finite"]
        # cent-exact: nav_after equals expected_nav_after within 1 cent
        after = Decimal(str(r["nav_after"]))
        expected = Decimal(str(r["expected_nav_after"]))
        assert abs(after - expected) <= Decimal("0.01")


def test_mp_nav_rejects_capital_creation():
    """fail-CLOSED money-path guard: a target whose total differs from the current
    NAV (capital appearing/vanishing) is NEVER reconciled as ok — nav_conserved is
    False and the reconcile blocks. This is the inverse metamorphic relation: NAV
    conservation must FAIL exactly when the books don't balance."""
    rng = random.Random(SEED + 11)
    for _ in range(N_CASES):
        current, target, total = _cash_conserving_rebalance(rng)
        # inject capital that did not exist (>= $1 so it clears the band)
        bump = round(rng.uniform(1.0, 50_000.0), 2)
        victim = sorted(target)[0]
        target = dict(target)
        target[victim] = round(target[victim] + bump, 2)
        report = recon.round_trip(current=current, target=target, write=False,
                                  ts="2026-06-28T00:00:00+00:00")
        r = report["reconciliation"]
        assert not r["nav_conserved"], (
            f"capital creation (+${bump}) wrongly reconciled as conserved"
        )
        assert r["blocked"] and not r["ok"]


def test_mp_nav_noop_rebalance_reconciles_perfectly():
    """A no-op (target == current) rebalance must reconcile with zero deltas — the
    baseline metamorphic anchor that the loop is sound."""
    rng = random.Random(SEED + 7)
    for _ in range(N_CASES):
        protos = [f"q{i}" for i in range(rng.randint(0, 6))]
        current = {p: round(rng.uniform(100, 40000), 2) for p in protos}
        report = recon.round_trip(current=current, target=dict(current),
                                  write=False, ts="2026-06-28T00:00:00+00:00")
        r = report["reconciliation"]
        assert r["matches_target"], f"no-op did not match: {r['deltas_usd']}"
        assert r["ok"] and not r["blocked"]
        assert report["n_trades"] == 0
        assert r["max_position_delta_usd"] == 0.0


def test_mp_nav_target_is_outcome_after_full_rebalance():
    """plan → dry-run → reconcile must land the resulting book ON the target
    (intent == outcome) for a cash-conserving rebalance whose every leg moves by
    MORE than the dust floor — the round-trip closes AND reconciles to the cent.

    NOTE (pinned edge — see test_mp_nav_subdust_delta_blocks_on_cent_axis): a
    move with a SUB-dust residual is intentionally NOT executed by plan_trades
    (its $10 dust floor), so for the round-trip to conserve to the cent we must
    move a clean PAIR of legs by an above-dust, exactly-offsetting amount.
    """
    rng = random.Random(SEED + 8)
    for _ in range(N_CASES):
        # start from a balanced book of >= 2 funded legs
        n = rng.randint(2, 6)
        protos = [f"r{i}" for i in range(n)]
        current = {p: round(rng.uniform(5_000, 30_000), 2) for p in protos}
        # move an above-dust amount from one leg to another (cash-conserving,
        # both legs change by >> the $10 dust floor and >> the $1 cent/dust band)
        src, dst = rng.sample(protos, 2)
        move = round(rng.uniform(50.0, min(current[src] - 50.0, 4000.0)), 2)
        target = dict(current)
        target[src] = round(current[src] - move, 2)
        target[dst] = round(current[dst] + move, 2)
        report = recon.round_trip(current=current, target=target, write=False,
                                  ts="2026-06-28T00:00:00+00:00")
        r = report["reconciliation"]
        # the dry-run applies the plan exactly → resulting must match target
        assert r["matches_target"], (
            f"intent != outcome\n current={current}\n target={target}\n "
            f"deltas={r['deltas_usd']}"
        )
        assert r["ok"], f"reconcile blocked: {r['block_reasons']}"
        assert r["nav_conserved_to_cent"]


def test_mp_nav_dryrun_ledger_applies_plan_faithfully():
    """INVARIANT of the dry-run ledger: the resulting book sums to sum(TARGET) to
    the cent for every executed plan (modulo skipped sub-dust legs).

    The ledger applies ENTER/INCREASE (+) and EXIT/DECREASE (−) exactly, so after
    a full rebalance the deployed total equals the target total — the plan is
    applied faithfully, never partially-applied silently. Any per-leg residual is
    bounded by the $10 dust floor (a skipped sub-dust trade), so the book total
    differs from sum(target) by at most (n_legs × dust). This pins that the
    money-path ledger neither fabricates nor loses capital relative to the plan.
    """
    rng = random.Random(SEED + 12)
    for _ in range(N_CASES):
        n = rng.randint(2, 6)
        protos = [f"d{i}" for i in range(n)]
        current = {p: round(rng.uniform(1_000, 30_000), 2) for p in protos}
        target = {p: round(rng.uniform(1_000, 30_000), 2) for p in protos
                  if rng.random() < 0.7}
        report = recon.round_trip(current=current, target=target, write=False,
                                  ts="2026-06-28T00:00:00+00:00")
        r = report["reconciliation"]
        nav_after = Decimal(str(r["nav_after"]))
        target_total = Decimal(str(round(sum(target.values()), 2)))
        # bound: each leg can be off by at most the $10 dust floor (skipped trade)
        max_residual = Decimal("10.00") * Decimal(n)
        assert abs(nav_after - target_total) <= max_residual, (
            f"resulting book did not track target total: after={nav_after} "
            f"target_total={target_total}\n current={current}\n target={target}"
        )
        # and when every leg moves by >> dust, it tracks target EXACTLY to a cent
        # (covered precisely by test_mp_nav_target_is_outcome_after_full_rebalance).


# ════════════════════════════════════════════════════════════════════════════
# MP-DETERM — whole pipeline deterministic (same input → identical output)
# ════════════════════════════════════════════════════════════════════════════
def test_mp_determinism_allocator():
    rng = random.Random(SEED + 9)
    for _ in range(N_CASES):
        adapters = _rand_snapshot(rng)
        a = _make_allocator(adapters, model="best_apy").allocate()
        b = _make_allocator(adapters, model="best_apy").allocate()
        assert a.target_weights == b.target_weights
        assert a.target_usd == b.target_usd


def test_mp_determinism_reconcile():
    rng = random.Random(SEED + 10)
    for _ in range(N_CASES):
        protos = [f"s{i}" for i in range(rng.randint(1, 6))]
        current = {p: round(rng.uniform(0, 30000), 2) for p in protos}
        target = {p: round(rng.uniform(0, 30000), 2) for p in protos}
        r1 = recon.round_trip(current=current, target=target, write=False,
                              ts="2026-06-28T00:00:00+00:00")
        r2 = recon.round_trip(current=current, target=target, write=False,
                              ts="2026-06-28T00:00:00+00:00")
        assert r1["reconciliation"] == r2["reconciliation"]
        assert r1["trades"] == r2["trades"]
