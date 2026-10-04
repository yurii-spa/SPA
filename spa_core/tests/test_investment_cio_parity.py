"""Parity test — ADR-554 finding #10: duplicated constants must never drift silently.

Before this fix, ``spa_core/investment_cio/policy.py`` carried its OWN literal copy of the
RiskPolicy T1/T2 concentration caps (``0.40``/``0.20``) right alongside ``exposure.py``'s own copy
of the same numbers. Two literals that happen to agree today are not "the same number" — nothing
stops one of them drifting the next time RiskPolicy changes via its own ADR.

This test reads the money-path's own RiskPolicy defaults (``spa_core/risk/policy.py``'s
``RiskConfig``) and the DeFi engine's ``reportable_after`` constant directly (test-only — the
investment_cio PACKAGE itself still never imports ``spa_core.risk``; the forward guard in
``test_investment_cio_guards.py`` only restricts ``spa_core/investment_cio/*.py``, not its tests),
and asserts the CIO's own copies equal them. A RiskPolicy change via its own ADR then reddens THIS
test instead of drifting silently out of step with the CIO.
"""
from __future__ import annotations

from spa_core.defi_engine.package_status import REPORTABLE_AFTER
from spa_core.investment_cio import contract, exposure, policy
from spa_core.risk.policy import RiskConfig


def test_cash_floor_matches_riskpolicy_min_cash_pct():
    assert contract.POLICY["cash_floor"] == RiskConfig().min_cash_pct


def test_maturity_developing_min_matches_defi_engine_reportable_after():
    assert contract.POLICY["maturity_developing_min"] == REPORTABLE_AFTER


def test_policy_protocol_caps_match_riskpolicy_concentration_limits():
    cfg = RiskConfig()
    assert policy.PROTOCOL_CAP_T1 == cfg.max_concentration_t1
    assert policy.PROTOCOL_CAP_T2 == cfg.max_concentration_t2


def test_exposure_reference_caps_match_riskpolicy_too():
    """exposure.py keeps its own read-only reference. Today that is
    ``RISK_POLICY_CAPS_REFERENCE`` (a dict); if a concurrent work-package renames it to named
    ``RISK_POLICY_CAP_T1`` / ``RISK_POLICY_CAP_T2`` constants, either shape is accepted here — the
    single copy ``policy.py`` derives from (see ``policy._protocol_caps_from_exposure``) must
    trace back to RiskPolicy's real numbers regardless of which shape wins."""
    cfg = RiskConfig()
    t1 = getattr(exposure, "RISK_POLICY_CAP_T1", None)
    t2 = getattr(exposure, "RISK_POLICY_CAP_T2", None)
    if t1 is None or t2 is None:
        ref = getattr(exposure, "RISK_POLICY_CAPS_REFERENCE", {}) or {}
        t1 = t1 if t1 is not None else ref.get("T1")
        t2 = t2 if t2 is not None else ref.get("T2")
    assert t1 == cfg.max_concentration_t1
    assert t2 == cfg.max_concentration_t2


def test_policy_caps_trace_to_exposures_own_copy_not_a_second_literal():
    """The regression finding #10 actually names: policy.py must DERIVE its caps from exposure.py,
    not carry a second independent literal that happens to match today."""
    assert (policy.PROTOCOL_CAP_T1, policy.PROTOCOL_CAP_T2) == policy._protocol_caps_from_exposure()
