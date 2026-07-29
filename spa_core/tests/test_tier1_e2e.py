"""
spa_core/tests/test_tier1_e2e.py — END-TO-END Tier-1 pipeline integration test.

Runs the Tier-1 analytical pipeline in sequence against the REAL current data
(read-only; write=False everywhere) and asserts the chain is coherent across the
~15 pipeline modules. The goal is to catch INTEGRATION DRIFT — when one module's
output shape or contract changes in a way that silently breaks a downstream
consumer — which per-module unit tests miss.

Cross-module invariants enforced here:
  • gate.eligible_for_paper  == validated set OF THE VERDICT THE GATE READ  (gate consistency)
  • packages offered strategies ⊆ gate.eligible_for_paper    (packages ⊆ eligible)
  • correlation.packages keys present (conservative/balanced/aggressive)
  • status.health ∈ {OK, ATTENTION}; ATTENTION ⇒ problems non-empty; OK ⇒ nothing unchecked
  • monte_carlo / var / attribution / benchmark build_report structurally valid
    over the validated set
  • run_manifest.build_manifest has a manifest_hash and is DETERMINISTIC
    (two calls equal)

Pure stdlib + pytest. Deterministic. Read-only (write=False). LLM-forbidden.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json

import pytest

from spa_core.backtesting.tier1 import evaluator
from spa_core.backtesting.tier1 import gate as gate_mod
from spa_core.backtesting.tier1 import packages as packages_mod
from spa_core.backtesting.tier1 import correlation as correlation_mod
from spa_core.backtesting.tier1 import status as status_mod
from spa_core.backtesting.tier1 import monte_carlo as mc_mod
from spa_core.backtesting.tier1 import var as var_mod
from spa_core.backtesting.tier1 import attribution as attribution_mod
from spa_core.backtesting.tier1 import benchmark as benchmark_mod
from spa_core.backtesting.tier1 import run_manifest as manifest_mod


# ---------------------------------------------------------------------------
# Session-scoped fixtures: run each stage ONCE against real data, write=False.
#
# TWO DIFFERENT VERDICTS — do not mix them up (this was the file's core defect):
#   `verdict`          — a FRESH evaluator.evaluate(write=False) recompute. Use it
#                        only to assert the evaluator's own output is self-consistent.
#   `verdict_snapshot` — data/tier1_verdict.json, the file EVERY downstream module
#                        (gate, packages, correlation, monte_carlo, var, attribution,
#                        benchmark, status) actually reads. Use it for every
#                        cross-module count/set assertion.
# Deriving cross-module expectations from the recompute compared an input the
# pipeline never used: the assertions were green only while snapshot ≡ recompute and
# went red — for a reason unrelated to integration — the moment the strategy registry
# moved after the snapshot was taken. Snapshot STALENESS is a real, separate question
# (no Tier-1 module publishes the age of its verdict input); it is recorded as a
# signal for the owner rather than asserted away here.
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def verdict():
    return evaluator.evaluate(write=False)


@pytest.fixture(scope="module")
def verdict_snapshot():
    """The on-disk verdict the downstream modules read ({} when the pipeline never ran)."""
    if not gate_mod._VERDICT.exists():
        return {}
    return json.loads(gate_mod._VERDICT.read_text())


def _validated_ids(verdict_obj: dict) -> set:
    return {r["id"] for r in verdict_obj.get("leaderboard_tier1", []) if r.get("validated")}


@pytest.fixture(scope="module")
def gate():
    return gate_mod.build_gate(write=False)


@pytest.fixture(scope="module")
def packages():
    return packages_mod.build(write=False)


@pytest.fixture(scope="module")
def correlation():
    return correlation_mod.analyze(write=False)


@pytest.fixture(scope="module")
def status():
    return status_mod.build(write=False, alert=False)


# ---------------------------------------------------------------------------
# 1. evaluator → verdict with regime + tier-1 leaderboard
# ---------------------------------------------------------------------------
def test_evaluator_verdict_shape(verdict):
    assert isinstance(verdict, dict)
    assert verdict["regime"] in ("NORMAL", "LOW_VOL_YIELD", "DEGENERATE_MOCK")
    assert isinstance(verdict["leaderboard_tier1"], list)
    assert verdict["llm_forbidden"] is True
    # every row carries the fields the downstream modules consume
    for row in verdict["leaderboard_tier1"]:
        assert "id" in row
        assert "validated" in row
        assert "net_apy_pct" in row
        assert "package" in row
        assert "tier1_grade" in row
    # validated_count is consistent with the leaderboard
    n_validated = sum(1 for r in verdict["leaderboard_tier1"] if r["validated"])
    assert verdict["validated_count"] == n_validated


# ---------------------------------------------------------------------------
# 2. gate.eligible set == validated set of the verdict the gate ACTUALLY READ
#
# `build_gate` recomputes nothing: it loads the verdict SNAPSHOT the pipeline last
# wrote (gate_mod._VERDICT). Deriving the expectation from a fresh
# evaluate(write=False) compared TWO DIFFERENT INPUTS and so failed whenever the
# strategy registry moved after the snapshot was taken — saying nothing about the
# gate's own consistency while hiding it. Same correction as
# test_tier1_backtest::test_gate_eligible_subset_of_validated (cycle #34); the
# property is unchanged, only the input is now the right one (invariant #16).
# Snapshot STALENESS is a real and separate question — the gate publishes no age
# for its input — recorded as a signal for the owner, not asserted away here.
# ---------------------------------------------------------------------------
@pytest.mark.skipif(
    not gate_mod._VERDICT.exists(),
    reason=(f"the gate reads its verdict from {gate_mod._VERDICT} (a git-ignored artifact the "
            "live Tier-1 pipeline maintains); with no verdict there is no partition to check"),
)
def test_gate_eligible_equals_validated(gate, verdict_snapshot):
    board = verdict_snapshot.get("leaderboard_tier1", [])
    eligible = set(gate["eligible_for_paper"])
    validated_ids = _validated_ids(verdict_snapshot)
    assert eligible == validated_ids, (
        f"gate eligible {eligible} != validated {validated_ids} of the verdict snapshot the "
        "gate read — integration drift between gate.py and evaluator.py"
    )
    assert gate["eligible_count"] == len(eligible)
    # every blocked strategy has a non-empty reason string
    for sid, reason in gate["blocked"].items():
        assert isinstance(reason, str) and reason
    # eligible ∪ blocked partition the board exactly — nothing silently dropped
    blocked = set(gate["blocked"].keys())
    assert eligible.isdisjoint(blocked)
    assert eligible | blocked == {r["id"] for r in board}
    assert gate["eligible_count"] + gate["blocked_count"] == len(board)


# ---------------------------------------------------------------------------
# 3. packages ⊆ gate eligible set
#
# Every strategy offered in any package must be eligible (validated). Packages
# is built from validated ∩ diversified-core, so it can only ever be a subset.
# ---------------------------------------------------------------------------
def test_packages_subset_of_eligible(packages, gate):
    eligible = set(gate["eligible_for_paper"])
    offered_ids = set()
    for key, pkg in packages["packages"].items():
        for member in pkg["strategies"]:
            offered_ids.add(member["id"])
    assert offered_ids <= eligible, (
        f"packages offer strategies {offered_ids - eligible} not in the gate's "
        f"eligible set {eligible} — packages.py is offering a non-validated strategy"
    )
    # all three product tiers are present
    assert set(packages["packages"].keys()) == {"conservative", "balanced", "aggressive"}
    # n_offered matches the strategy list length
    for key, pkg in packages["packages"].items():
        assert pkg["n_offered"] == len(pkg["strategies"])
        assert pkg["status"] in ("available", "no_validated_strategies_yet")
        if pkg["strategies"]:
            assert pkg["status"] == "available"


# ---------------------------------------------------------------------------
# 4. correlation.analyze → package keys present
# ---------------------------------------------------------------------------
def test_correlation_package_keys(correlation):
    assert isinstance(correlation, dict)
    pkgs = correlation["packages"]
    assert set(pkgs.keys()) == {"conservative", "balanced", "aggressive"}
    # each package entry reports a member count
    for key, info in pkgs.items():
        assert "n" in info
        # diversified_subset (if present) is a subset of members (if present)
        if "members" in info and "diversified_subset" in info:
            assert set(info["diversified_subset"]) <= set(info["members"])


# ---------------------------------------------------------------------------
# 5. status.build → health in {OK, ATTENTION}; ATTENTION ⇒ problems non-empty;
#    OK ⇒ both detectors actually ran (`unchecked` empty).
#
# The previous marker skipped this on GITHUB_ACTIONS with "runs locally" — it did
# not run locally either: on a clean checkout it FAILED, because the three-tier
# assertion below needs the git-ignored tier1_packages.json that only the live
# pipeline writes. Gated on that artifact instead (invariant #16 — the property is
# not weakened, the precondition is now stated truthfully; with the artifact
# present the test executes and asserts strictly more than before).
#
# The unchecked/health part is asserted UNCONDITIONALLY in the hermetic
# test_tier1_status_honesty.py, which injects its own data dir.
# ---------------------------------------------------------------------------
_PACKAGES_ARTIFACT = status_mod._DATA / "tier1_packages.json"


@pytest.mark.skipif(
    not _PACKAGES_ARTIFACT.exists(),
    reason=(f"the rollup summarises {_PACKAGES_ARTIFACT} (a git-ignored artifact the live Tier-1 "
            "pipeline writes); with no packages file there are no tiers to roll up"),
)
def test_status_health_invariant(status):
    assert status["health"] in ("OK", "ATTENTION")
    if status["health"] == "ATTENTION":
        assert status["problems"], "health=ATTENTION but problems list is empty"
    else:
        assert status["problems"] == []
        # refusal-first: OK may never mean "no detector fired" (invariant #2)
        assert status["unchecked"] == [], (
            f"health=OK while {status['unchecked']} was never measured")
    # anything unchecked must be visible in problems — the alert reads problems only
    for reason in status["unchecked"]:
        assert reason in status["problems"]
    # packages summary carries the three tiers
    assert set(status["packages"].keys()) == {"conservative", "balanced", "aggressive"}


# ---------------------------------------------------------------------------
# 6. monte_carlo / var / attribution / benchmark build_report (write=False) —
#    structurally valid over the validated set.
#
# All four read the VERDICT SNAPSHOT (each module has its own `_VERDICT` pointing at
# data/tier1_verdict.json), so the expected counts come from `verdict_snapshot`, not
# from a fresh recompute.
# ---------------------------------------------------------------------------
def test_monte_carlo_report(verdict_snapshot):
    rep = mc_mod.build_report(write=False, n_paths=200)  # fewer paths → fast, still deterministic
    n_validated = len(_validated_ids(verdict_snapshot))
    assert rep["validated_count"] == n_validated
    assert rep["seed"] == 42
    assert len(rep["strategies"]) == n_validated
    for row in rep["strategies"]:
        mc = row["mc"]
        assert mc["status"] in ("ok", "insufficient_data", "insufficient_history")
        if mc["status"] == "ok":
            # percentile ordering p5 <= p50 <= p95 for both apy and drawdown
            assert mc["apy_p5"] <= mc["apy_p50"] <= mc["apy_p95"]
            assert mc["maxdd_p5"] <= mc["maxdd_p50"] <= mc["maxdd_p95"]
            assert mc["maxdd_p5"] >= 0.0


def test_var_report(verdict_snapshot):
    rep = var_mod.build_report(write=False)
    n_validated = len(_validated_ids(verdict_snapshot))
    assert rep["validated_count"] == n_validated
    assert len(rep["strategies"]) == n_validated
    for row in rep["strategies"]:
        risk = row["risk"]
        # principal VaR @99% >= @95% (higher confidence = worse/larger loss)
        assert risk["principal_var_99"] >= risk["principal_var_95"]
        # yield VaR is a non-negative loss
        assert risk["yield_var_95"] >= 0.0
        assert risk["yield_var_99"] >= 0.0
        # combined (binding) risk == principal VaR @99%
        assert risk["combined_annual_risk_pct"] == risk["principal_var_99"]


def test_attribution_report(verdict_snapshot):
    rep = attribution_mod.build_report(write=False)
    n_validated = len(_validated_ids(verdict_snapshot))
    assert rep["n_validated"] == n_validated
    assert len(rep["strategies"]) == n_validated
    for sid, row in rep["strategies"].items():
        attr = row["attribution"]
        assert attr["status"] in ("ok", "insufficient_data")
        if attr["status"] == "ok":
            # shares of contribution sum to ~100% (renormalised over covered)
            shares = [bp["share_pct"] for bp in attr["by_protocol"]]
            if shares:
                assert abs(sum(shares) - 100.0) < 1.0


def test_benchmark_report():
    # no verdict fixture: this one asserts only the report's internal consistency
    rep = benchmark_mod.build_report(write=False)
    assert isinstance(rep["results"], list)
    assert rep["n_strategies"] == len(rep["results"])
    for row in rep["results"]:
        assert row["status"] in (
            "ok", "insufficient_data", "insufficient_history", "no_aave_benchmark")
        if row["status"] == "ok":
            # excess vs rf is strategy_apy - risk-free, must be internally consistent
            assert abs((row["strategy_apy"] - row["rf_apy"])
                       - row["excess_vs_rf_pct"]) < 1e-3
            assert 0.0 <= row["pct_days_outperform"] <= 100.0


# ---------------------------------------------------------------------------
# 7. run_manifest.build_manifest → manifest_hash present + deterministic
# ---------------------------------------------------------------------------
def test_run_manifest_deterministic():
    m1 = manifest_mod.build_manifest(write=False)
    m2 = manifest_mod.build_manifest(write=False)
    assert m1["manifest_hash"]
    assert isinstance(m1["manifest_hash"], str) and len(m1["manifest_hash"]) == 64
    # deterministic: two consecutive calls produce the same content hash
    assert m1["manifest_hash"] == m2["manifest_hash"], (
        "run_manifest is not deterministic — same code+inputs gave different hashes"
    )
    assert m1["module_count"] >= 15  # the tier1 module set
    assert "evaluator.py" in m1["module_hashes"]
    # verify_reproducible against itself is True (nothing changed between calls)
    vr = manifest_mod.verify_reproducible(m1)
    assert vr["reproducible"] is True
    assert vr["changed_modules"] == []
    assert vr["changed_inputs"] == []


# ---------------------------------------------------------------------------
# 8. WHOLE-CHAIN smoke: run every stage in order without exception and assert
#    the top-level cross-module invariants (eligible ⊆ validated, packages ⊆ eligible).
# ---------------------------------------------------------------------------
def test_full_pipeline_chain_runs(verdict_snapshot):
    v = evaluator.evaluate(write=False)
    g = gate_mod.build_gate(write=False)
    p = packages_mod.build(write=False)
    c = correlation_mod.analyze(write=False)
    s = status_mod.build(write=False, alert=False)
    mc = mc_mod.build_report(write=False, n_paths=100)
    var_rep = var_mod.build_report(write=False)
    attr = attribution_mod.build_report(write=False)
    bench = benchmark_mod.build_report(write=False)
    man = manifest_mod.build_manifest(write=False)

    # eligible/offered come from the SNAPSHOT-reading modules, so the validated set must
    # come from the snapshot too — `v` above only proves the evaluator still runs.
    validated_ids = _validated_ids(verdict_snapshot)
    eligible = set(g["eligible_for_paper"])
    offered = {m["id"] for pkg in p["packages"].values() for m in pkg["strategies"]}

    # the two headline integration invariants
    assert eligible <= validated_ids       # eligible ⊆ validated
    assert offered <= eligible             # packages ⊆ eligible
    assert isinstance(v["leaderboard_tier1"], list)   # the recompute itself still produces a board

    # nothing returned a degenerate/empty structure
    assert set(c["packages"].keys()) == {"conservative", "balanced", "aggressive"}
    assert s["health"] in ("OK", "ATTENTION")
    assert (s["health"] == "ATTENTION") == bool(s["problems"])
    assert mc["seed"] == 42
    assert var_rep["model"] == "tier1_var"
    assert attr["model"] == "tier1_attribution"
    assert bench["model"] == "tier1_parallel"
    assert man["manifest_hash"]
