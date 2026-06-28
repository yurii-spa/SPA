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

The RiskPolicy stage is wired to the REAL deterministic
spa_core.risk.policy.RiskPolicy (correct signature, honours ``.approved``) and
FAILS CLOSED whenever the policy cannot be evaluated — see
TestRiskPolicyRealEvaluation. (This replaced a former fail-OPEN gap where a v2
signature mismatch raised TypeError that was swallowed, so the live policy was
never consulted.)

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
def _reset_module_state(tmp_path):
    """Reset module-level rate-limit state + point the PERSISTED kill-switch at a
    throwaway dir before AND after each test.

    WS-B2: the manual kill is now PERSISTED to ``data/kill_switch_active.json``
    via the governance lifecycle. We redirect that state to a per-test tmp dir
    (``set_data_dir_override``) so tests NEVER touch live ``data/`` and stay
    isolated; the deprecated process-local flag is also cleared for legacy pokes.
    """
    sc._tx_timestamps.clear()
    sc._kill_switch_active = False
    sc.set_data_dir_override(tmp_path)
    yield
    sc._tx_timestamps.clear()
    sc._kill_switch_active = False
    sc.set_data_dir_override(None)


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
        # 6% drawdown → governance SOFT tier → blocks a NEW/increasing (default
        # "supply") exposure (converged onto governance, WS-B1).
        r = safety.check_not_in_kill_switch({"total_drawdown_pct": 0.06})
        assert r.passed is False
        assert r.is_hard_block is True

    def test_block_at_exact_threshold(self, safety):
        # Exactly 5% → governance SOFT boundary (inclusive >=) → blocks supply.
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
        # Whitelisted + positive amount + compliant live inputs → the REAL
        # RiskPolicy is consulted and approves → pass (blocking=True result).
        # We supply current_apy/tvl_usd explicitly so the check is deterministic
        # (no network) and the policy floors (TVL ≥ $5M, 1% ≤ APY ≤ 30%) hold.
        r = safety.check_risk_policy(
            "aave-v3", "supply", 1000.0, healthy_portfolio,
            current_apy=5.0, tvl_usd=200_000_000.0,
        )
        assert r.passed is True
        assert r.blocking is True
        assert r.is_hard_block is False
        # Confirm the REAL policy (not a whitelist-only fallback) was consulted.
        assert "v1.0 PASS" in r.details

    def test_explicit_policy_rejection_blocks(self, safety, healthy_portfolio, monkeypatch):
        """If the live RiskPolicy raises for any reason, the stage must FAIL CLOSED
        (BLOCK). We simulate this by injecting a policy whose check_new_position
        raises — any exception in the policy call → block, never fall through."""

        class _RejectingPolicy:
            def check_new_position(self, *a, **k):
                raise RuntimeError("RiskPolicy v1.0: TVL below minimum — rejected")

        import spa_core.risk.policy as real_policy_mod
        monkeypatch.setattr(real_policy_mod, "RiskPolicy", _RejectingPolicy)

        r = safety.check_risk_policy(
            "aave-v3", "supply", 1000.0, healthy_portfolio,
            current_apy=5.0, tvl_usd=200_000_000.0,
        )
        assert r.passed is False
        assert r.is_hard_block is True
        assert "fail-closed" in r.details.lower()


# ═══════════════════════════════════════════════════════════════════════════
# RiskPolicy stage is wired to the REAL deterministic policy (fail-CLOSED)
# ═══════════════════════════════════════════════════════════════════════════


class TestRiskPolicyRealEvaluation:
    """The (formerly fail-OPEN) RiskPolicy stage now calls the REAL
    spa_core.risk.policy.RiskPolicy.check_new_position with the correct
    signature and honours its ``.approved`` verdict.

    Previously check_risk_policy called the policy with a v2 signature
    (protocol=/action=/portfolio=) that raised TypeError, which was swallowed
    (`except TypeError: pass`) → it fell through to passed=True. The real,
    deterministic RiskPolicy (TVL floor, concentration caps, APY bounds, cash
    buffer, drawdown) was NEVER consulted — a position the live policy would
    reject still PASSED. This was a fail-OPEN go-live blocker.

    These tests pin the corrected, fail-CLOSED behaviour.
    """

    _PORTFOLIO = {
        "total_drawdown_pct": 0.0,
        "cash_usd": 50_000.0,
        "total_capital_usd": 100_000.0,
    }

    def test_high_apy_low_tvl_position_is_blocked(self, safety):
        # APY 99% > 30% ceiling AND TVL $1 < $5M floor → the REAL RiskPolicy
        # rejects → the gate must BLOCK (was a silent pass before the fix).
        r = safety.check_risk_policy(
            "aave-v3", "supply", 1000.0, self._PORTFOLIO,
            current_apy=99.0, tvl_usd=1.0,
        )
        assert r.passed is False
        assert r.is_hard_block is True
        # Real policy violations surface in the detail (not a whitelist fallback).
        assert "rejected" in r.details.lower()
        assert ("tvl" in r.details.lower() or "apy" in r.details.lower())

    def test_over_concentration_position_is_blocked(self, safety):
        # A position larger than the T1 40% concentration cap (and that would
        # bust the cash buffer) → the REAL RiskPolicy rejects → gate BLOCKS.
        portfolio = {
            "total_drawdown_pct": 0.0,
            "cash_usd": 100_000.0,
            "total_capital_usd": 100_000.0,
        }
        r = safety.check_risk_policy(
            "aave-v3", "supply", 60_000.0, portfolio,   # 60% > 40% T1 cap
            current_apy=5.0, tvl_usd=200_000_000.0,
        )
        assert r.passed is False
        assert r.is_hard_block is True
        assert "rejected" in r.details.lower()

    def test_compliant_position_passes_via_real_policy(self, safety):
        # A fully policy-compliant position → REAL RiskPolicy approves → pass.
        r = safety.check_risk_policy(
            "aave-v3", "supply", 1000.0, self._PORTFOLIO,
            current_apy=5.0, tvl_usd=200_000_000.0,
        )
        assert r.passed is True
        assert r.is_hard_block is False
        assert "v1.0 PASS" in r.details   # proves the real policy ran

    def test_missing_live_inputs_fail_closed(self, safety, monkeypatch):
        # If APY/TVL are not supplied AND the live feed cannot provide them,
        # the policy cannot be evaluated → the gate must FAIL CLOSED (block),
        # never fall through to a pass.
        import spa_core.execution.safety_checks as scmod
        monkeypatch.setattr(scmod, "_fetch_protocol_metrics", lambda _pk: (None, None))
        r = safety.check_risk_policy("aave-v3", "supply", 1000.0, self._PORTFOLIO)
        assert r.passed is False
        assert r.is_hard_block is True
        assert "fail-closed" in r.details.lower()

    def test_policy_error_fail_closed(self, safety, monkeypatch):
        # Any exception raised while evaluating the policy → FAIL CLOSED.
        class _BoomPolicy:
            def check_new_position(self, *a, **k):
                raise ValueError("boom")

        import spa_core.risk.policy as real_policy_mod
        monkeypatch.setattr(real_policy_mod, "RiskPolicy", _BoomPolicy)
        r = safety.check_risk_policy(
            "aave-v3", "supply", 1000.0, self._PORTFOLIO,
            current_apy=5.0, tvl_usd=200_000_000.0,
        )
        assert r.passed is False
        assert r.is_hard_block is True
        assert "fail-closed" in r.details.lower()


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
            current_apy=5.0, tvl_usd=200_000_000.0,
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
            current_apy=5.0, tvl_usd=200_000_000.0,
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
            current_apy=5.0, tvl_usd=200_000_000.0,
        )
        gas = next(c for c in pipeline.checks if c.check_name == "Gas Reasonableness")
        assert gas.blocking is False  # documented: gas skip is non-blocking
        # With a good sim and no other failures the pipeline proceeds.
        assert pipeline.blocked is False


# ═══════════════════════════════════════════════════════════════════════════
# Result helpers
# ═══════════════════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════════════════
# WS-B1/B2 — Execution kill-switch CONVERGED onto governance (ADR-049)
# ═══════════════════════════════════════════════════════════════════════════


class TestKillSwitchGovernanceConvergence:
    """Red-team + property tests for the convergence onto the ONE governance
    source of truth (WS-B1 two-tier, WS-B2 persistence).

    Proves:
      * the execution two-tier verdict == governance ``drawdown_tier`` on the
        same equity (no divergence) at every band + both boundaries (5/10%);
      * SOFT blocks NEW/increase only (supply blocked, withdraw allowed);
        HARD blocks ALL (both supply and withdraw);
      * NO flat-5% hard-block remains (5–10% does NOT all-cash a withdraw);
      * the kill is PERSISTED — survives a simulated process restart; absence=OFF.
    """

    import pytest as _pytest  # local alias for parametrize

    def _portfolio(self, frac):
        return {"total_drawdown_pct": frac, "cash_usd": 0.0, "total_capital_usd": 100_000.0}

    # ── B1: two-tier verdict matches governance, no divergence ───────────────

    @_pytest.mark.parametrize(
        "frac, exp_tier",
        [
            (0.0, "TIER_NONE"),
            (0.0499, "TIER_NONE"),
            (0.05, "TIER_SOFT_DERISK"),   # inclusive lower boundary
            (0.075, "TIER_SOFT_DERISK"),
            (0.0999, "TIER_SOFT_DERISK"),
            (0.10, "TIER_HARD_KILL"),     # inclusive boundary — exactly 10% kills
            (0.15, "TIER_HARD_KILL"),
        ],
    )
    def test_execution_tier_matches_governance(self, safety, frac, exp_tier):
        from spa_core.governance import kill_switch as gov
        # Governance classifies a PERCENTAGE; execution stores a fraction.
        gov_tier, _ = gov.classify_drawdown_pct(frac * 100.0)
        assert gov_tier == getattr(gov, exp_tier)

        # Execution SUPPLY (increasing exposure) verdict must agree with the tier:
        r_sup = safety.check_not_in_kill_switch(self._portfolio(frac), action="supply")
        if gov_tier == gov.TIER_NONE:
            assert r_sup.passed is True
        else:  # SOFT or HARD both block an increase
            assert r_sup.is_hard_block is True

    def test_soft_blocks_increase_allows_reduce_no_flat_5pct(self, safety):
        # 7% drawdown = SOFT. RED-TEAM: the OLD flat-5% hard-block would block a
        # withdraw too. The converged gate must ALLOW a reduction under SOFT.
        p = self._portfolio(0.07)
        assert safety.check_not_in_kill_switch(p, action="supply").is_hard_block is True
        r_wd = safety.check_not_in_kill_switch(p, action="withdraw")
        assert r_wd.passed is True
        assert r_wd.is_hard_block is False
        assert "soft de-risk" in r_wd.details.lower()

    def test_hard_blocks_all_including_withdraw(self, safety):
        # 12% drawdown = HARD → ALL blocked, even a reducing withdraw (all-cash).
        p = self._portfolio(0.12)
        assert safety.check_not_in_kill_switch(p, action="supply").is_hard_block is True
        assert safety.check_not_in_kill_switch(p, action="withdraw").is_hard_block is True

    def test_max_drawdown_stop_arg_is_ignored_governance_owns_threshold(self, safety):
        # Passing a different max_drawdown_stop must NOT change the verdict — the
        # owner-set governance constants own the threshold now (no private value).
        p = self._portfolio(0.07)  # SOFT under governance
        r = safety.check_not_in_kill_switch(p, max_drawdown_stop=0.50, action="supply")
        assert r.is_hard_block is True  # still SOFT-blocked despite a 50% arg

    # ── B2: persistence across a simulated process restart ───────────────────

    def test_manual_kill_persists_across_restart(self, safety, tmp_path, healthy_portfolio):
        # Activate (writes data/kill_switch_active.json under the tmp override),
        # then SIMULATE a restart by clearing the deprecated in-process flag.
        PreExecutionSafety.activate_kill_switch("persist test")
        sc._kill_switch_active = False  # crash/restart wipes the in-memory flag
        # A "new process" reads the persisted file → still ACTIVE.
        assert PreExecutionSafety.is_kill_switch_active() is True
        r = safety.check_not_in_kill_switch(healthy_portfolio)
        assert r.is_hard_block is True
        assert "persisted" in r.details.lower()
        # File actually exists on disk (proof of persistence).
        assert (tmp_path / "kill_switch_active.json").exists()

    def test_absence_is_off(self, safety, tmp_path, healthy_portfolio):
        # No kill_switch_active.json in the tmp dir → OFF (file-absent contract).
        assert not (tmp_path / "kill_switch_active.json").exists()
        assert PreExecutionSafety.is_kill_switch_active() is False
        r = safety.check_not_in_kill_switch(healthy_portfolio)
        assert r.passed is True

    def test_deactivate_clears_persisted_state(self, safety, tmp_path, healthy_portfolio):
        PreExecutionSafety.activate_kill_switch("trip")
        assert (tmp_path / "kill_switch_active.json").exists()
        PreExecutionSafety.deactivate_kill_switch("owner cleared")
        assert not (tmp_path / "kill_switch_active.json").exists()
        assert PreExecutionSafety.is_kill_switch_active() is False
        assert safety.check_not_in_kill_switch(healthy_portfolio).passed is True

    def test_explicit_active_false_file_is_off(self, safety, tmp_path, healthy_portfolio):
        # Governance contract: a file with active=False == explicitly OFF.
        import json
        (tmp_path / "kill_switch_active.json").write_text(
            json.dumps({"active": False, "reason": "deactivated"}), encoding="utf-8"
        )
        assert PreExecutionSafety.is_kill_switch_active() is False
        assert safety.check_not_in_kill_switch(healthy_portfolio).passed is True


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
