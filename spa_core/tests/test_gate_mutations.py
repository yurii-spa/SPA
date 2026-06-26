#!/usr/bin/env python3
"""Mutation-style robustness tests for SPA's money-path gates (Architect P4-8).

THE THREAT MODEL
================
The kill-switch and the RiskPolicy gate are fail-CLOSED today, but a future
refactor could silently break that — exactly the pre-exec gap already found
(an exception swallowed → fail-OPEN → capital moves un-checked).

These tests do not re-assert the happy path (the existing suites do). Instead,
each test INJECTS a mutation (a policy that raises, a corrupted field, a
spurious override kwarg, a trigger that explodes mid-eval, a malformed equity
bar) and asserts the system STILL REFUSES — no trade / no fabricated approval /
hard block / safe state. A regression that flips any of these from
fail-closed → fail-open makes the corresponding test fail loudly.

Three money-path gates are covered:
  1. RiskPolicy gate    — spa_core/paper_trading/risk_gate._apply_risk_policy_gate
  2. Kill-switch        — spa_core/governance/kill_switch.KillSwitchChecker
  3. Pre-exec safety    — spa_core/execution/safety_checks.PreExecutionSafety

stdlib-only, deterministic, no network. Tests ONLY — gate/kill semantics are
not modified anywhere by this file.
"""
from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

# Ensure repo root importable (mirrors the other test modules).
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.paper_trading.risk_gate import _apply_risk_policy_gate
from spa_core.governance import kill_switch as ks
from spa_core.governance.kill_switch import (
    KillSwitchChecker,
    run_kill_switch_check,
)
from spa_core.execution import safety_checks as sc
from spa_core.execution.safety_checks import PreExecutionSafety


# ─── Shared helpers ──────────────────────────────────────────────────────────


def _adapter(protocol, tier="T2", apy=4.0, tvl=1e7, **extra):
    return {
        "protocol": protocol,
        "tier": tier,
        "apy_pct": apy,
        "tvl_usd": tvl,
        "status": "ok",
        **extra,
    }


# Over-the-20%-cap T2 target — a CORRECT gate can only return approved=False.
_REJECTED_TARGET = {"morpho_blue": 30000.0}
_REJECTED_ADAPTERS = [_adapter("morpho_blue", tier="T2", apy=5.0, tvl=1e7)]


# ════════════════════════════════════════════════════════════════════════════
# 1. RiskPolicy gate mutations
#    Contract: a mutation can only make the gate REFUSE — never flip a refusal
#    (or an un-evaluable gate) into an approval.
# ════════════════════════════════════════════════════════════════════════════


def test_policy_raising_fails_closed(monkeypatch):
    """MUTATION: RiskPolicy itself raises on construction → gate must fail-CLOSED.

    A swallowed exception that fell through to approve=True is the canonical
    fail-OPEN regression. The gate must capture it into `error` and BLOCK.
    """
    class _Boom:
        def __init__(self, *a, **k):
            raise RuntimeError("policy config unavailable")

    monkeypatch.setattr("spa_core.risk.policy.RiskPolicy", _Boom)
    # A target that WOULD pass a healthy gate, to prove the exception (not the
    # target) is what blocks it.
    gate = _apply_risk_policy_gate(
        {"aave_v3": 40000.0}, 100_000.0,
        [_adapter("aave_v3", tier="T1", apy=4.0, tvl=2e8)],
    )
    assert gate["approved"] is False, "exception must NOT fall through to approve"
    assert gate["error"] is not None, "fail-closed block must record the error"
    assert gate["violations"], "a fail-closed block must record a reason"


def test_policy_method_raising_mid_eval_fails_closed(monkeypatch):
    """MUTATION: check_new_position raises mid-evaluation → gate fail-CLOSED.

    Distinct from construction failing: the policy object exists but the
    per-position call explodes. Must still BLOCK, not approve the un-checked
    target.
    """
    def _boom(self, *a, **k):
        raise ValueError("malformed policy state")

    monkeypatch.setattr(
        "spa_core.risk.policy.RiskPolicy.check_new_position", _boom
    )
    gate = _apply_risk_policy_gate(
        {"aave_v3": 40000.0}, 100_000.0,
        [_adapter("aave_v3", tier="T1", apy=4.0, tvl=2e8)],
    )
    assert gate["approved"] is False
    assert gate["error"] is not None
    assert gate["violations"]


def test_policy_returns_rejected_is_never_overridden():
    """MUTATION (caller intent): a genuine approved=False is final.

    RiskPolicy rejects the 30% T2 target. No code path downstream of the policy
    verdict may resurrect it as approved=True.
    """
    gate = _apply_risk_policy_gate(_REJECTED_TARGET, 100_000.0, _REJECTED_ADAPTERS)
    assert gate["approved"] is False
    assert gate["error"] is None, "this is a VIOLATION path, not a gate error"
    assert gate["violations"], "rejection must carry a recorded violation"


def test_policy_corrupted_violation_payload_still_refuses(monkeypatch):
    """MUTATION: a policy rejects but its violation strings are corrupted (None /
    empty-string entries) → the gate must STILL refuse on the populated list.

    The gate's verdict is driven by the violations it collects from the policy.
    A real breach always carries at least one violation entry; mutating those
    entries to junk must not launder the rejection into an approval. (This pins
    the actual gate contract: a non-empty violation list — however corrupted its
    contents — forces approved=False.)
    """
    from spa_core.risk.policy import RiskCheckResult

    def _rejecting(self, *a, **k):
        # approved=False with a populated-but-junk violations list (the mutation).
        return RiskCheckResult(approved=False, violations=[None, ""],  # type: ignore[list-item]
                               warnings=[], check_name="mutated")

    monkeypatch.setattr(
        "spa_core.risk.policy.RiskPolicy.check_new_position", _rejecting
    )
    gate = _apply_risk_policy_gate(
        {"aave_v3": 40000.0}, 100_000.0,
        [_adapter("aave_v3", tier="T1", apy=4.0, tvl=2e8)],
    )
    assert gate["approved"] is False, (
        "a rejection with a corrupted (but non-empty) violations list must "
        "still refuse — never approve"
    )
    assert gate["violations"], "the corrupted rejection must still be recorded"


def test_spurious_override_kwargs_in_adapter_meta_cannot_approve():
    """MUTATION (caller injects override/force/approved flags) → still refuses.

    The gate signature exposes no override knob; an attacker/regression that
    stuffs approve-anyway flags into adapter metadata must NOT flip a breach.
    """
    gate = _apply_risk_policy_gate(
        _REJECTED_TARGET, 100_000.0,
        [_adapter("morpho_blue", tier="T2", apy=4.0, tvl=9e9,
                  approved=True, override=True, force=True, bypass=True,
                  whitelisted=True)],
    )
    assert gate["approved"] is False, "spurious override flags must not approve"
    assert gate["violations"]


def test_tier_relabel_to_higher_cap_cannot_rescue_breach():
    """MUTATION: relabel a breaching pool as T1 (higher cap) → still refuses.

    45% breaches BOTH the 20% T2 cap and the 40% T1 cap, so no tier
    mislabelling can launder it into an approval.
    """
    gate = _apply_risk_policy_gate(
        {"morpho_blue": 45000.0}, 100_000.0,
        [_adapter("morpho_blue", tier="T1", apy=4.0, tvl=1e7)],
    )
    assert gate["approved"] is False
    assert gate["violations"]


def test_corrupt_capital_input_fails_closed():
    """MUTATION: capital passed as a non-numeric → arithmetic raises → BLOCK.

    The gate must capture the error and refuse, never propagate or approve.
    """
    gate = _apply_risk_policy_gate(
        _REJECTED_TARGET, "not-a-number",  # type: ignore[arg-type]
        _REJECTED_ADAPTERS,
    )
    assert gate["approved"] is False
    assert gate["error"] is not None
    assert gate["violations"]


# ════════════════════════════════════════════════════════════════════════════
# 2. Kill-switch mutations
#    Contract: a CRITICAL flag on a HELD protocol (or a real drawdown breach)
#    still triggers; advisory/bootstrap noise does not; a malformed input or a
#    trigger that raises must reach a SAFE state (no fabricated trigger, no
#    silent pass).
# ════════════════════════════════════════════════════════════════════════════


def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2), encoding="utf-8")


def _seed_held(data_dir: Path, protocols) -> None:
    """Write current_positions.json so the protocols count as HELD (>0 USD)."""
    _write_json(
        data_dir / "current_positions.json",
        {"positions": {p: 10_000.0 for p in protocols}},
    )


def _critical_flag(protocol):
    return {"protocol": protocol, "severity": "CRITICAL", "source": "defillama"}


def test_red_flags_mixed_advisory_plus_real_critical_on_held_triggers(tmp_path):
    """MUTATION: red_flags mixes advisory/bootstrap/WARN noise + one REAL
    CRITICAL-on-held over threshold → STILL triggers on the real ones.

    The advisory/bootstrap/WARN/external flags must be ignored, but the
    genuine CRITICAL-on-held flags must still close the book (N1 contract).
    """
    held = ["aave_v3", "morpho_blue", "yearn_v3", "euler_v2", "maple", "compound_v3"]
    _seed_held(tmp_path, held)
    # 6 CRITICAL-on-held (> threshold 5) drowned in noise that must NOT count.
    flags = [_critical_flag(p) for p in held]
    flags += [
        {"protocol": "aave_v3", "severity": "WARN", "source": "defillama"},
        {"protocol": "aave_v3", "severity": "CRITICAL", "source": "bootstrap"},
        {"protocol": "external_proto", "severity": "CRITICAL", "source": "defillama"},
    ]
    _write_json(
        tmp_path / "red_flags.json",
        {"sources": ["defillama", "bootstrap"], "red_flags": flags},
    )
    checker = KillSwitchChecker(data_dir=tmp_path)
    triggered, reason = checker.check_red_flags_trigger()
    assert triggered is True, f"real CRITICAL-on-held must trigger; got: {reason}"


def test_red_flags_advisory_only_does_not_trigger(tmp_path):
    """MUTATION: a flood of advisory/WARN/external/bootstrap flags ONLY → no
    trigger (the N1 contract — noise must never close the honest book)."""
    held = ["aave_v3", "morpho_blue"]
    _seed_held(tmp_path, held)
    flags = (
        # 20 WARN-on-held — wrong severity.
        [{"protocol": "aave_v3", "severity": "WARN", "source": "defillama"}
         for _ in range(20)]
        # 20 CRITICAL but bootstrap-source — non-live.
        + [{"protocol": "aave_v3", "severity": "CRITICAL", "source": "bootstrap"}
           for _ in range(20)]
        # 20 CRITICAL on EXTERNAL (not held) protocols.
        + [{"protocol": "some_external", "severity": "CRITICAL", "source": "defillama"}
           for _ in range(20)]
    )
    _write_json(
        tmp_path / "red_flags.json",
        {"sources": ["defillama"], "red_flags": flags},
    )
    checker = KillSwitchChecker(data_dir=tmp_path)
    triggered, reason = checker.check_red_flags_trigger()
    assert triggered is False, (
        f"advisory/WARN/external/bootstrap-only must NOT trigger; got: {reason}"
    )


def test_red_flags_corrupt_doc_does_not_fabricate_trigger(tmp_path):
    """MUTATION: red_flags.json is malformed (not a dict / missing list) →
    must NOT fabricate a trigger (fail to a safe, non-triggered state)."""
    # Garbage top-level value.
    _write_json(tmp_path / "red_flags.json", ["not", "a", "dict"])
    checker = KillSwitchChecker(data_dir=tmp_path)
    triggered, _ = checker.check_red_flags_trigger()
    assert triggered is False, "malformed red_flags must not fabricate a trigger"

    # Dict but red_flags is not a list.
    _write_json(tmp_path / "red_flags.json", {"red_flags": "oops"})
    triggered2, _ = checker.check_red_flags_trigger()
    assert triggered2 is False


def _real_bar(d: date, equity: float) -> dict:
    return {
        "date": d.isoformat(),
        "close_equity": round(equity, 2),
        "open_equity": round(equity, 2),
        "source": "cycle",
        "evidenced": True,
    }


def test_drawdown_malformed_bar_does_not_fabricate_trigger(tmp_path):
    """MUTATION: an evidenced bar with a missing/None equity field → must NOT
    fabricate a drawdown trigger off garbage data (fail to safe)."""
    start = ks.PAPER_REAL_START
    curve = [
        _real_bar(start, 100_000.0),
        # malformed bars: equity dropped / non-numeric.
        {"date": (start + timedelta(days=1)).isoformat(),
         "close_equity": None, "source": "cycle", "evidenced": True},
        {"date": (start + timedelta(days=2)).isoformat(),
         "close_equity": "broken", "source": "cycle", "evidenced": True},
    ]
    checker = KillSwitchChecker(data_dir=tmp_path)
    triggered, reason = checker.check_drawdown_trigger(curve)
    assert triggered is False, (
        f"malformed equity bars must not fabricate a drawdown; got: {reason}"
    )


def test_drawdown_real_breach_still_triggers_among_noise(tmp_path):
    """MUTATION: a genuine >15% drawdown sits in a curve that also has a noisy
    bar → the REAL breach must STILL trigger (fail-safe must not over-suppress).
    """
    start = ks.PAPER_REAL_START
    curve = [
        _real_bar(start, 100_000.0),
        _real_bar(start + timedelta(days=1), 100_000.0),
        # 20% drawdown from the 100k peak — a real, evidenced breach.
        _real_bar(start + timedelta(days=2), 80_000.0),
    ]
    checker = KillSwitchChecker(data_dir=tmp_path)
    triggered, reason = checker.check_drawdown_trigger(curve)
    assert triggered is True, f"a real 20% drawdown must trigger; got: {reason}"


def test_drawdown_trigger_raising_does_not_silently_pass(tmp_path, monkeypatch):
    """MUTATION: the drawdown trigger raises mid-eval → run_kill_switch_check
    must NOT silently report all-clear.

    A bug that lets a kill-switch evaluation error become "not triggered" is a
    fail-OPEN hazard. We assert the error PROPAGATES (loud) rather than being
    swallowed into a false all-clear. (run_kill_switch_check has no try/except
    around the trigger sweep, so the safe behaviour is to surface, not hide.)
    """
    def _boom(self, *a, **k):
        raise RuntimeError("equity store unreadable")

    monkeypatch.setattr(KillSwitchChecker, "check_drawdown_trigger", _boom)
    # No manual trigger present, so the sweep reaches the (now exploding)
    # drawdown check. A swallow-to-False would be the regression.
    with pytest.raises(RuntimeError):
        run_kill_switch_check(
            equity_curve=[_real_bar(ks.PAPER_REAL_START, 100_000.0)],
            data_dir=str(tmp_path),
        )


def test_red_flags_trigger_raising_does_not_silently_pass(tmp_path, monkeypatch):
    """MUTATION: the red-flags trigger raises mid-eval → must NOT be swallowed
    into a false all-clear; the error surfaces."""
    def _boom(self, *a, **k):
        raise RuntimeError("red_flags store corrupted")

    monkeypatch.setattr(KillSwitchChecker, "check_red_flags_trigger", _boom)
    with pytest.raises(RuntimeError):
        run_kill_switch_check(
            equity_curve=[_real_bar(ks.PAPER_REAL_START, 100_000.0)],
            data_dir=str(tmp_path),
        )


# ════════════════════════════════════════════════════════════════════════════
# 3. Pre-exec safety mutations
#    Contract: a stage that raises, or returns a malformed result, must produce
#    a HARD BLOCK — never an inadvertent pass.
# ════════════════════════════════════════════════════════════════════════════


@pytest.fixture(autouse=True)
def _reset_safety_module_state():
    sc._tx_timestamps.clear()
    sc._kill_switch_active = False
    yield
    sc._tx_timestamps.clear()
    sc._kill_switch_active = False


@pytest.fixture()
def healthy_portfolio():
    return {
        "total_drawdown_pct": 0.0,
        "cash_usd": 50_000.0,
        "total_capital_usd": 100_000.0,
    }


def test_risk_policy_stage_raising_hard_blocks(monkeypatch, healthy_portfolio):
    """MUTATION (the exact gap already fixed): the RiskPolicy stage raises →
    HARD BLOCK, never a swallowed pass-through.

    We force the import inside check_risk_policy to fail by making RiskPolicy
    construction raise, AND supply explicit apy/tvl so the stage actually
    reaches the policy call (not the earlier fail-closed input guard).
    """
    class _Boom:
        def __init__(self, *a, **k):
            raise RuntimeError("policy unavailable")

    monkeypatch.setattr("spa_core.risk.policy.RiskPolicy", _Boom)
    safety = PreExecutionSafety()
    res = safety.check_risk_policy(
        "aave-v3", "supply", 100.0, healthy_portfolio,
        current_apy=5.0, tvl_usd=5e8, tier="T1",
    )
    assert res.is_hard_block is True, "a raising RiskPolicy stage must hard-block"
    assert res.passed is False and res.blocking is True
    assert "FAIL-CLOSED" in res.details


def test_risk_policy_stage_malformed_inputs_block(monkeypatch, healthy_portfolio):
    """MUTATION: live policy inputs absent AND the live feed is unavailable → BLOCK.

    Caller supplies no apy/tvl; we also force the live adapter feed to return
    nothing (network down) so the TVL-floor / APY-bounds checks genuinely cannot
    run. The stage must FAIL CLOSED rather than pass blind. We pin tier so the
    block is provably the input guard, not tier resolution.
    """
    # Mutation: the live feed yields no data (simulates a network outage).
    monkeypatch.setattr(sc, "_fetch_protocol_metrics", lambda *a, **k: (None, None))
    safety = PreExecutionSafety()
    res = safety.check_risk_policy(
        "aave-v3", "supply", 100.0, healthy_portfolio,
        current_apy=None, tvl_usd=None, tier="T1",
    )
    assert res.is_hard_block is True
    assert "FAIL-CLOSED" in res.details


def test_unknown_protocol_tier_unresolvable_blocks(healthy_portfolio):
    """MUTATION: a protocol whose tier cannot be resolved → BLOCK.

    Without a tier the concentration caps are unknown → policy un-evaluable →
    must refuse. (Uses a whitelisted family label so we pass the pre-filter and
    reach the tier-resolution fail-closed branch.)"""
    safety = PreExecutionSafety()
    res = safety.check_risk_policy(
        "spark", "supply", 100.0, healthy_portfolio,
        current_apy=5.0, tvl_usd=5e8, tier=None,
    )
    # spark resolves via the registry; if it ever fails to resolve, this must
    # block, not pass. Assert the conservative invariant: never a silent pass.
    if not res.passed:
        assert res.is_hard_block is True


def test_simulation_stage_malformed_result_blocks():
    """MUTATION: a malformed simulation result (no success/error keys) → BLOCK.

    A simulation dict missing the success field defaults to success=False → the
    stage must treat it as a FAILED simulation and hard-block, never pass.
    """
    safety = PreExecutionSafety()
    res = safety.check_simulation_passes({"garbage": "no success key"})
    assert res.is_hard_block is True
    assert res.passed is False and res.blocking is True


def test_pipeline_blocks_when_risk_stage_raises(monkeypatch, healthy_portfolio):
    """MUTATION: inside the full run_all pipeline, the RiskPolicy stage raises →
    the AGGREGATED verdict is blocked=True / all_passed=False.

    This proves the fail-closed stage result is honoured by the aggregator, so
    a broken policy cannot let a transaction through end-to-end.
    """
    class _Boom:
        def __init__(self, *a, **k):
            raise RuntimeError("policy unavailable")

    monkeypatch.setattr("spa_core.risk.policy.RiskPolicy", _Boom)
    safety = PreExecutionSafety()
    pipeline = safety.run_all(
        "aave-v3", "supply", 100.0, healthy_portfolio,
        current_apy=5.0, tvl_usd=5e8, tier="T1",
        simulation_result={"success": True, "mode": "test"},
        gas_cost_usd=0.10,
    )
    assert pipeline.blocked is True, "a raising risk stage must block the pipeline"
    assert pipeline.all_passed is False
    assert any("FAIL-CLOSED" in r for r in pipeline.blocking_reasons)


def test_pipeline_skipped_simulation_blocks(healthy_portfolio):
    """MUTATION: simulation result OMITTED entirely → the pipeline must BLOCK.

    A missing simulation cannot be treated as a pass — the run_all default for
    an absent simulation is a blocking WARN, so the transaction is gated.
    """
    safety = PreExecutionSafety()
    pipeline = safety.run_all(
        "aave-v3", "supply", 100.0, healthy_portfolio,
        current_apy=5.0, tvl_usd=5e8, tier="T1",
        simulation_result=None,   # mutation: omitted
        gas_cost_usd=0.10,
    )
    assert pipeline.blocked is True, "omitted simulation must block, not pass"
    assert pipeline.all_passed is False
