"""Parity guard between the two deterministic risk modules (prevents silent cap drift).

`spa_core/risk/policy.py` is the AUTHORITATIVE RiskPolicy v1.0 gate (stamps policy_compliant).
`spa_core/risk/policy_enforcer.py` is a SECONDARY check read by rules_watchdog + cycle_runner's
ALLOC-001/002. They MUST agree on the caps, or the same book is compliant under one and rejected
under the other — exactly the defect the rules_watchdog CRITICAL surfaced 2026-07-08:

    enforcer per_protocol_max_pct = 25%   vs  policy.max_single_protocol = 40%
    enforcer t1_min_pct           = 55%   vs  policy has NO T1 floor

These two are STALE risk_adjusted-era constants in the enforcer. Reconciling them is a RISK-LAYER
edit → OWNER SIGN-OFF required (see the decision surface). Until then these asserts xfail (documenting
the drift, keeping CI green); they flip to pass the moment the enforcer is reconciled to policy.py.
The T2 (50%) and T3 (15%) caps already agree and are asserted strictly (must never drift).
"""
from __future__ import annotations

import pytest

from spa_core.risk.policy import RiskConfig
from spa_core.risk import policy_enforcer as PE


_CFG = RiskConfig()
_RULES = PE.RULES


def test_t2_total_cap_parity():
    assert float(_RULES["t2_max_pct"]) == _CFG.max_total_t2_allocation * 100.0


def test_t3_total_cap_parity():
    assert float(_RULES["t3_max_pct"]) == getattr(_CFG, "max_total_t3_allocation", 0.15) * 100.0


def test_cash_floor_parity():
    assert float(_RULES["cash_min_pct"]) == _CFG.min_cash_pct * 100.0


@pytest.mark.xfail(reason="enforcer per_protocol 25% is stale vs policy 40% — pending owner sign-off", strict=True)
def test_per_protocol_cap_parity_PENDING_SIGNOFF():
    assert float(_RULES["per_protocol_max_pct"]) == _CFG.max_single_protocol * 100.0


@pytest.mark.xfail(reason="enforcer has a 55% T1 floor policy.py does not — pending owner sign-off", strict=True)
def test_no_t1_floor_beyond_policy_PENDING_SIGNOFF():
    # policy.py has NO T1 minimum; the enforcer's 55% floor is a stale extra constraint.
    assert float(_RULES.get("t1_min_pct", 0.0)) == 0.0
