#!/usr/bin/env python3
"""Tests for spa_core.execution.safety_checks.PreExecutionSafety.

This is the BLOCKING pre-execution safety pipeline that gates every real-capital
transaction. Stages (run_all order):

    1. Kill switch          (BLOCKING)
    2. Rate limit           (BLOCKING)
    3. RiskPolicy           (BLOCKING)
    4. Transaction sim      (BLOCKING)
    5. Gas reasonableness   (BLOCKING unless skipped)
    6. Multisig routing     (INFORMATIONAL — routing only, never a block)

For EACH stage we assert both BLOCK and PASS, plus fail-CLOSED behaviour on
missing/malformed input. The gate must NEVER proceed (blocked=False) when an
input is absent or malformed.

These tests are READ-ONLY against the safety code — they do not change its
behaviour. Where a real fail-OPEN gap exists it is pinned with an xfail test
(see TestRiskPolicyFailsOpenGap) and reported to the architect, NOT silently
fixed.

Determinism: module-level rate-limit / kill-switch state is reset in fixtures
so tests do not leak state into one another.
"""
from __future__ import annotations

import pytest

from spa_core.execution import safety_checks as sc
from spa_core.execution.safety_checks import (
    PreExecutionSafety,
    SafetyCheckResult,
    SafetyPipelineResult,
)


# ─── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_module_state():
    """Reset module-level rate-limit + kill-switch state before AND after each test.

    safety_checks keeps these at module scope so they survive across calls within
    a process; for deterministic tests we wipe them around every test.
    """
    sc._tx_timestamps.clear()
    sc._kill_switch_active = False
    yield
    sc._tx_timestamps.clear()
    sc._kill_switch_active = False


@pytest.fixture()
def safety():
    return PreExecutionSafety()


@pytest.fixture()
def healthy_portfolio():
    """Portfolio with no drawdown — kill switch should NOT trip on it."""
    return {
        "total_drawdown_pct": 0.0,
        "cash_usd": 50_000.0,
        "total_capital_usd": 100_000.0,
    }


def _good_sim():
    return {"success": True, "mode": "tenderly", "sim_id": "sim-123"}


# ═══════════════════════════════════════════════════════════════════════════
# Stage 1 — Kill switch
# ═══════════════════════════════════════════════════════════════════════════


class TestKillSwitch:
    def test_pass_when_no_kill_and_low_drawdown(self, safety, healthy_portfolio):
        r = safety.check_not_in_kill_switch(healthy_portfolio)
        assert r.passed is True
        assert r.blocking is True
        assert r.is_hard_block is False

    def test_block_on_manual_kill_switch(self, safety, healthy_portfolio):
        PreExecutionSafety.activate_kill_switch("test trip")
        try:
            r = safety.check_not_in_kill_switch(healthy_portfolio)
        finally:
            PreExecutionSafety.deactivate_kill_switch("test cleanup")
        assert r.passed is False
        assert r.blocking is True
        assert r.is_hard_block is True
        assert "kill switch" in r.details.lower()

    def test_block_on_drawdown_breach(self, safety):
        r = safety.check_not_in_kill_switch({"total_drawdown_pct": 0.06})
        assert r.passed is False
        assert r.is_hard_block is True

    def test_block_at_exact_threshold(self, safety):
        # drawdown == stop threshold must block (>=, fail-closed at the boundary)
        r = safety.check_not_in_kill_switch({"total_drawdown_pct": 0.05})
        assert r.passed is False
        assert r.is_hard_block is True

    def test_fail_closed_on_malformed_drawdown(self, safety):
        """Malformed drawdown value must NOT silently proceed as a pass.

        The implementation coerces None/garbage to 0.0; a None drawdown is
        treated as 'no drawdown' (passes). We pin the actual behaviour: missing
        key → 0.0 → passes. A genuinely malformed (non-numeric) value should
        raise rather than silently pass — assert it does not return a spurious
        non-blocking 'passed' result that would let a bad portfolio through.
        """
        # Missing key → coerced to 0.0 → passes (documented behaviour).
        r = safety.check_not_in_kill_switch({})
        assert r.passed is True
        # Non-numeric drawdown must NOT yield a silent pass: it raises (fail-closed
        # by exception — caller's run_all has no swallow here, so it propagates).
        with pytest.raises((ValueError, TypeError)):
            safety.check_not_in_kill_switch({"total_drawdown_pct": "not-a-number"})


# ═══════════════════════════════════════════════════════════════════════════
# Stage 2 — Rate limit
# ═══════════════════════════════════════════════════════════════════════════


class TestRateLimit:
    def test_pass_under_limit(self, safety):
        r = safety.check_rate_limit()
        assert r.passed is True
        assert r.is_hard_block is False

    def test_block_when_limit_reached(self, safety):
        # Record the max number of transactions, then the next check must block.
        for _ in range(sc._RATE_LIMIT_MAX_TX):
            safety.record_transaction()
        r = safety.check_rate_limit()
        assert r.passed is False
        assert r.is_hard_block is True
        assert "rate limit" in r.details.lower()

    def test_pass_again_after_window_purge(self, safety, monkeypatch):
        """Stale timestamps outside the rolling window are purged → passes again."""
        # Inject timestamps older than the window.
        stale = 1.0  # ancient unix ts
        sc._tx_timestamps.extend([stale] * sc._RATE_LIMIT_MAX_TX)
        r = safety.check_rate_limit()
        assert r.passed is True  # all stale → purged
        assert sc._tx_timestamps == []  # purge actually happened


# ═══════════════════════════════════════════════════════════════════════════
# Stage 3 — RiskPolicy
# ═══════════════════════════════════════════════════════════════════════════


class TestRiskPolicy:
    def test_block_non_whitelisted_protocol(self, safety, healthy_portfolio):
        r = safety.check_risk_policy("rugpull-finance", "supply", 1000.0, healthy_portfolio)
        assert r.passed is False
        assert r.is_hard_block is True
        assert "whitelist" in r.details.lower()

    def test_block_non_positive_amount(self, safety, healthy_portfolio):
        for bad in (0.0, -100.0):
            r = safety.check_risk_policy("aave-v3", "supply", bad, healthy_portfolio)
            assert r.passed is False, f"amount={bad} should block"
            assert r.is_hard_block is True

    def test_pass_whitelisted_basic(self, safety, healthy_portfolio):
        # Whitelisted + positive amount → returns a pass (blocking=True result).
        r = safety.check_risk_policy("aave-v3", "supply", 1000.0, healthy_portfolio)
        assert r.passed is True
        assert r.blocking is True
        assert r.is_hard_block is False

    def test_explicit_policy_rejection_blocks(self, safety, healthy_portfolio, monkeypatch):
        """If the live RiskPolicy raises a genuine rejection (not a wiring error),
        the stage must BLOCK. We simulate this by injecting a policy whose
        check_new_position raises a rejection-shaped exception."""

        class _RejectingPolicy:
            def check_new_position(self, *a, **k):
                raise RuntimeError("RiskPolicy v1.0: TVL below minimum — rejected")

        import types
        fake_mod = types.ModuleType("risk.policy")
        fake_mod.RiskPolicy = _RejectingPolicy
        fake_pkg = types.ModuleType("risk")
        fake_pkg.policy = fake_mod
        monkeypatch.setitem(__import__("sys").modules, "risk", fake_pkg)
        monkeypatch.setitem(__import__("sys").modules, "risk.policy", fake_mod)

        r = safety.check_risk_policy("aave-v3", "supply", 1000.0, healthy_portfolio)
        assert r.passed is False
        assert r.is_hard_block is True
        assert "rejected" in r.details.lower()


# ═══════════════════════════════════════════════════════════════════════════
# REAL SAFETY GAP — RiskPolicy stage fails OPEN against the live policy
# ═══════════════════════════════════════════════════════════════════════════


class TestRiskPolicyFailsOpenGap:
    """PINNED REAL GAP (report to architect — do NOT silently fix the gate).

    spa_core/execution/safety_checks.PreExecutionSafety.check_risk_policy calls
    the live policy as:

        RiskPolicy().check_new_position(
            protocol=..., action=..., amount_usd=..., portfolio=...)

    But the live spa_core/risk/policy.RiskPolicy.check_new_position has a totally
    different signature:

        check_new_position(state, protocol_key, tier, amount_usd,
                           current_apy, tvl_usd, chain=..., check_capacity=...)
        -> RiskCheckResult            # RETURNS a result; never raises on reject

    So the v2 call raises TypeError ('unexpected keyword argument protocol'),
    which check_risk_policy swallows (`except TypeError: pass`) and then falls
    through to a `passed=True` fallback. NET EFFECT: the real, deterministic
    RiskPolicy (TVL floor, concentration caps, APY bounds, cash buffer,
    drawdown) is NEVER actually consulted. A transaction the live policy would
    REJECT still PASSES this stage on the inline whitelist + amount>0 checks
    alone.

    This is inert today (LiveTradingGate blocks live exec) but at go-live the
    RiskPolicy stage of the pre-execution gate is a no-op = fail-OPEN.

    The xfail below pins the expected-correct behaviour: a position the live
    policy rejects (APY 99% > 25% ceiling, TVL $1) should BLOCK. It currently
    does not, so the test is xfail(strict=True) — it will flip to a hard
    failure the moment the gate is wired correctly, prompting removal of xfail.
    """

    @pytest.mark.xfail(
        strict=True,
        reason="GAP: check_risk_policy v2 signature mismatch -> TypeError swallowed "
        "-> live RiskPolicy never consulted -> fails OPEN. Report to architect.",
    )
    def test_live_policy_rejection_should_block_but_does_not(self, safety):
        # This portfolio + a hypothetical bad position WOULD be rejected by the
        # real RiskPolicy. check_risk_policy as written cannot express APY/TVL
        # (its signature has no slots for them) and silently passes.
        portfolio = {
            "total_drawdown_pct": 0.0,
            "cash_usd": 50_000.0,
            "total_capital_usd": 100_000.0,
        }
        r = safety.check_risk_policy("aave-v3", "supply", 1000.0, portfolio)
        # EXPECTED (correct gate): a real policy evaluation occurs and can block.
        # ACTUAL (current gate): always passes via the fallback. xfail captures this.
        assert r.passed is False  # <-- currently False==fails, so xfail


# ═══════════════════════════════════════════════════════════════════════════
# Stage 4 — Transaction simulation
# ═══════════════════════════════════════════════════════════════════════════


class TestSimulation:
    def test_pass_on_successful_sim(self, safety):
        r = safety.check_simulation_passes(_good_sim())
        assert r.passed is True
        assert r.is_hard_block is False

    def test_block_on_failed_sim(self, safety):
        r = safety.check_simulation_passes(
            {"success": False, "mode": "tenderly", "error": "revert: insufficient allowance"}
        )
        assert r.passed is False
        assert r.is_hard_block is True
        assert "fail" in r.details.lower()

    def test_fail_closed_on_empty_sim_dict(self, safety):
        """Missing 'success' key must default to failure (fail-closed)."""
        r = safety.check_simulation_passes({})
        assert r.passed is False
        assert r.is_hard_block is True

    def test_run_all_fail_closed_when_sim_omitted(self, safety, healthy_portfolio):
        """If no simulation_result is supplied to run_all, the sim stage must be a
        hard block — never an implicit pass."""
        pipeline = safety.run_all(
            "aave-v3", "supply", 100.0, healthy_portfolio,
            gas_cost_usd=0.5, simulation_result=None,
        )
        sim = next(c for c in pipeline.checks if c.check_name == "Transaction Simulation")
        assert sim.passed is False
        assert sim.is_hard_block is True
        assert pipeline.blocked is True


# ═══════════════════════════════════════════════════════════════════════════
# Stage 5 — Gas reasonableness
# ═══════════════════════════════════════════════════════════════════════════


class TestGas:
    def test_pass_low_gas(self, safety):
        # $1 gas on a $1000 trade = 0.1% < 2%
        r = safety.check_gas_reasonable(1.0, 1000.0)
        assert r.passed is True
        assert r.is_hard_block is False

    def test_block_high_gas(self, safety):
        # $50 gas on a $1000 trade = 5% > 2%
        r = safety.check_gas_reasonable(50.0, 1000.0)
        assert r.passed is False
        assert r.is_hard_block is True
        assert "exceeds" in r.details.lower()

    def test_block_at_exact_threshold(self, safety):
        # exactly 2% is NOT < 2% → block (fail-closed at boundary)
        r = safety.check_gas_reasonable(20.0, 1000.0)
        assert r.passed is False
        assert r.is_hard_block is True

    def test_fail_closed_on_non_positive_amount(self, safety):
        for bad in (0.0, -1.0):
            r = safety.check_gas_reasonable(1.0, bad)
            assert r.passed is False, f"amount={bad} should block"
            assert r.is_hard_block is True


# ═══════════════════════════════════════════════════════════════════════════
# Stage 6 — Multisig routing (INFORMATIONAL, never a block)
# ═══════════════════════════════════════════════════════════════════════════


class TestMultisigRouting:
    def test_small_amount_auto_execute(self, safety):
        r = safety.check_amount_requires_multisig(100.0)
        assert r.passed is True          # hot-wallet path
        assert r.blocking is False
        assert r.is_hard_block is False  # never a hard block

    def test_large_amount_requires_multisig(self, safety):
        r = safety.check_amount_requires_multisig(10_000.0)
        assert r.passed is False         # "not passed" == needs multisig
        assert r.blocking is False       # but it must NOT block the pipeline
        assert r.is_hard_block is False

    def test_threshold_boundary_is_auto_execute(self, safety):
        # exactly $500 is <= threshold → auto-execute
        r = safety.check_amount_requires_multisig(sc.MULTISIG_THRESHOLD_USD)
        assert r.passed is True
        assert r.blocking is False


# ═══════════════════════════════════════════════════════════════════════════
# Full pipeline — run_all aggregation
# ═══════════════════════════════════════════════════════════════════════════


class TestRunAll:
    def test_all_pass_proceeds(self, safety, healthy_portfolio):
        pipeline = safety.run_all(
            "aave-v3", "supply", 100.0, healthy_portfolio,
            gas_cost_usd=0.5, simulation_result=_good_sim(),
        )
        assert pipeline.all_passed is True
        assert pipeline.blocked is False
        assert pipeline.requires_multisig is False  # $100 <= $500

    def test_kill_switch_blocks_whole_pipeline(self, safety, healthy_portfolio):
        PreExecutionSafety.activate_kill_switch("pipeline test")
        try:
            pipeline = safety.run_all(
                "aave-v3", "supply", 100.0, healthy_portfolio,
                gas_cost_usd=0.5, simulation_result=_good_sim(),
            )
        finally:
            PreExecutionSafety.deactivate_kill_switch("cleanup")
        assert pipeline.blocked is True
        assert pipeline.all_passed is False
        assert any("kill switch" in r.lower() for r in pipeline.blocking_reasons)

    def test_rate_limit_blocks_whole_pipeline(self, safety, healthy_portfolio):
        for _ in range(sc._RATE_LIMIT_MAX_TX):
            safety.record_transaction()
        pipeline = safety.run_all(
            "aave-v3", "supply", 100.0, healthy_portfolio,
            gas_cost_usd=0.5, simulation_result=_good_sim(),
        )
        assert pipeline.blocked is True
        assert pipeline.all_passed is False

    def test_non_whitelisted_blocks_whole_pipeline(self, safety, healthy_portfolio):
        pipeline = safety.run_all(
            "rugpull", "supply", 100.0, healthy_portfolio,
            gas_cost_usd=0.5, simulation_result=_good_sim(),
        )
        assert pipeline.blocked is True

    def test_failed_sim_blocks_whole_pipeline(self, safety, healthy_portfolio):
        pipeline = safety.run_all(
            "aave-v3", "supply", 100.0, healthy_portfolio,
            gas_cost_usd=0.5,
            simulation_result={"success": False, "error": "revert"},
        )
        assert pipeline.blocked is True

    def test_high_gas_blocks_whole_pipeline(self, safety, healthy_portfolio):
        pipeline = safety.run_all(
            "aave-v3", "supply", 100.0, healthy_portfolio,
            gas_cost_usd=50.0,  # 50% of a $100 trade
            simulation_result=_good_sim(),
        )
        assert pipeline.blocked is True

    def test_large_amount_sets_requires_multisig_without_blocking(self, safety):
        """Large amount routes through multisig but does NOT block (informational)."""
        portfolio = {
            "total_drawdown_pct": 0.0,
            "cash_usd": 90_000.0,
            "total_capital_usd": 100_000.0,
        }
        pipeline = safety.run_all(
            "aave-v3", "supply", 10_000.0, portfolio,
            gas_cost_usd=10.0, simulation_result=_good_sim(),
        )
        assert pipeline.requires_multisig is True
        assert pipeline.blocked is False
        assert pipeline.all_passed is True

    def test_run_all_with_no_gas_skips_gas_nonblocking(self, safety, healthy_portfolio):
        """Omitting gas yields a non-blocking WARN gas result (documented skip),
        but the pipeline still requires the sim — which is the real hard gate."""
        pipeline = safety.run_all(
            "aave-v3", "supply", 100.0, healthy_portfolio,
            gas_cost_usd=None, simulation_result=_good_sim(),
        )
        gas = next(c for c in pipeline.checks if c.check_name == "Gas Reasonableness")
        assert gas.blocking is False  # documented: gas skip is non-blocking
        # With a good sim and no other failures the pipeline proceeds.
        assert pipeline.blocked is False


# ═══════════════════════════════════════════════════════════════════════════
# Result helpers
# ═══════════════════════════════════════════════════════════════════════════


class TestResultTypes:
    def test_is_hard_block_semantics(self):
        blocked = SafetyCheckResult(passed=False, check_name="X", details="", blocking=True)
        assert blocked.is_hard_block is True
        passed = SafetyCheckResult(passed=True, check_name="X", details="", blocking=True)
        assert passed.is_hard_block is False
        nonblocking_fail = SafetyCheckResult(passed=False, check_name="X", details="", blocking=False)
        assert nonblocking_fail.is_hard_block is False

    def test_from_checks_excludes_multisig_from_blocks(self):
        checks = [
            SafetyCheckResult(passed=True, check_name="Kill Switch", details="", blocking=True),
            SafetyCheckResult(
                passed=False, check_name="Multisig Routing", details="needs safe", blocking=False
            ),
        ]
        res = SafetyPipelineResult.from_checks(checks)
        # Multisig "not passed" must not block, but must set requires_multisig.
        assert res.blocked is False
        assert res.all_passed is True
        assert res.requires_multisig is True
