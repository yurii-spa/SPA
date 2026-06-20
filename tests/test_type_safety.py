"""Runtime type-contract tests (MP-1233).

These tests pin the *runtime* types of the values that flow across SPA's core
public API — the allocator, the deterministic RiskPolicy and the paper-trading
cycle runner — plus the shared aliases in ``spa_core.utils.type_utils``.

They complement the static mypy gate in ci-lite.yml: mypy proves the
annotations are internally consistent; these assertions prove the *real*
objects returned at runtime actually match the documented shapes (e.g. a
``CycleResult.current_equity`` really is a ``float``, ``RiskCheckResult.approved``
really is a ``bool``). Pure stdlib, fully deterministic — orchestrator and
allocator are injected in-process fakes, so there is no network or disk
dependency beyond pytest's ``tmp_path``.
"""
from __future__ import annotations

import typing
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from spa_core.utils import type_utils as tu
from spa_core.risk.policy import (
    PortfolioState,
    Position,
    RiskCheckResult,
    RiskConfig,
    RiskPolicy,
)
from spa_core.allocator.allocator import AllocationResult
from spa_core.paper_trading import cycle_runner as cr


# ─── Fixtures: deterministic, network-free cycle wiring ──────────────────────


def _adapter(protocol, tier="T1", apy=4.0, tvl=2e8, status="ok"):
    return {
        "protocol": protocol,
        "tier": tier,
        "apy_pct": apy,
        "tvl_usd": tvl,
        "status": status,
    }


_ADAPTERS = [
    _adapter("aave_v3", tier="T1", apy=4.0, tvl=2e8),
    _adapter("morpho_blue", tier="T2", apy=5.0, tvl=1e7),
]
_TARGET = {"aave_v3": 40000.0, "morpho_blue": 18000.0}


class _FakeAllocator:
    def allocate(self):
        return SimpleNamespace(
            target_usd=dict(_TARGET),
            expected_apy_pct=3.0,
            model_used="risk_adjusted",
            strategy_loop_active=False,
        )


def _orch_fn(adapters, status="ok"):
    def _fn(data_dir):
        return SimpleNamespace(adapters=adapters, status=status)

    return _fn


@pytest.fixture
def cycle_result(tmp_path):
    """Run one fully-injected, deterministic paper-trading cycle."""
    return cr.run_cycle(
        data_dir=tmp_path,
        now=datetime(2026, 6, 10, 8, 0, tzinfo=timezone.utc),
        orchestrator_fn=_orch_fn(_ADAPTERS),
        allocator=_FakeAllocator(),
        risk_scorer_fn=lambda d: None,
        track_persister_fn=lambda d: None,
        write=True,
    )


@pytest.fixture
def portfolio_state():
    return PortfolioState(
        total_capital_usd=100_000.0,
        positions=[
            Position(
                protocol_key="aave_v3",
                tier="T1",
                asset="USDC",
                amount_usd=40_000.0,
                apy_at_open=4.0,
                current_apy=4.0,
            )
        ],
    )


# ─── 1–7: type_utils aliases ─────────────────────────────────────────────────


def test_apyfloat_is_float():
    assert tu.APYFloat is float


def test_usdfloat_is_float():
    assert tu.USDFloat is float


def test_weightfloat_is_float():
    assert tu.WeightFloat is float


def test_adaptername_is_str():
    assert tu.AdapterName is str


def test_strategyname_is_str():
    assert tu.StrategyName is str


def test_protocoltier_literal_values():
    assert typing.get_args(tu.ProtocolTier) == ("T1", "T2", "T3")


def test_type_utils_all_exports_resolve():
    for name in tu.__all__:
        assert hasattr(tu, name), f"__all__ names missing attr: {name}"


# ─── 8–13: RiskPolicy return contracts ───────────────────────────────────────


def test_riskpolicy_default_config_type():
    assert isinstance(RiskPolicy().config, RiskConfig)


def test_check_new_position_returns_riskcheckresult():
    res = RiskPolicy().check_new_position(
        state=PortfolioState(total_capital_usd=100_000.0),
        protocol_key="aave_v3",
        tier="T1",
        amount_usd=10_000.0,
        current_apy=4.0,
        tvl_usd=2e8,
    )
    assert isinstance(res, RiskCheckResult)
    assert isinstance(res.approved, bool)
    assert isinstance(res.violations, list)
    assert isinstance(res.warnings, list)


def test_check_portfolio_health_returns_riskcheckresult(portfolio_state):
    res = RiskPolicy().check_portfolio_health(portfolio_state)
    assert isinstance(res, RiskCheckResult)
    assert isinstance(res.approved, bool)


def test_calculate_var_returns_dict(portfolio_state):
    assert isinstance(RiskPolicy().calculate_var(portfolio_state), dict)


def test_max_safe_position_size_returns_float(portfolio_state):
    size = RiskPolicy().max_safe_position_size(portfolio_state, "compound_v3", "T1")
    assert isinstance(size, float)


def test_check_stablecoin_depeg_returns_riskcheckresult():
    res = RiskPolicy().check_stablecoin_depeg({"USDC": 1.0, "DAI": 0.999})
    assert isinstance(res, RiskCheckResult)
    assert isinstance(res.approved, bool)


# ─── 14–15: PortfolioState derived properties ────────────────────────────────


def test_portfolio_state_deployed_usd_is_float(portfolio_state):
    assert isinstance(portfolio_state.deployed_usd, float)
    assert portfolio_state.deployed_usd == 40_000.0


def test_portfolio_state_cash_pct_is_float(portfolio_state):
    assert isinstance(portfolio_state.cash_pct, float)
    assert 0.0 <= portfolio_state.cash_pct <= 1.0


# ─── 16: AllocationResult shape ──────────────────────────────────────────────


def test_allocation_result_to_dict_types():
    ar = AllocationResult(
        target_weights={"aave_v3": 0.4},
        target_usd={"aave_v3": 40_000.0},
        expected_apy_pct=4.0,
        model_used="risk_adjusted",
        timestamp="2026-06-10T08:00:00+00:00",
    )
    d = ar.to_dict()
    assert isinstance(d, dict)
    assert isinstance(d["target_usd"], dict)
    assert isinstance(d["expected_apy_pct"], float)


# ─── 17–22: CycleResult runtime contract ─────────────────────────────────────


def test_run_cycle_returns_cycleresult(cycle_result):
    assert isinstance(cycle_result, cr.CycleResult)


def test_cycle_result_current_equity_is_float(cycle_result):
    assert isinstance(cycle_result.current_equity, float)


def test_cycle_result_traded_is_bool(cycle_result):
    assert isinstance(cycle_result.traded, bool)


def test_cycle_result_status_is_str(cycle_result):
    assert isinstance(cycle_result.status, str)


def test_cycle_result_positions_and_notes_containers(cycle_result):
    assert isinstance(cycle_result.positions, dict)
    assert isinstance(cycle_result.notes, list)


def test_cycle_result_to_dict_is_serialisable(cycle_result):
    import json

    d = cycle_result.to_dict()
    assert isinstance(d, dict)
    # round-trips through JSON → every value is a JSON-native type
    assert isinstance(json.loads(json.dumps(d)), dict)


def test_cycle_result_policy_approved_is_bool(cycle_result):
    assert isinstance(cycle_result.policy_approved, bool)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
