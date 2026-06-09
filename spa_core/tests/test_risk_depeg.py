"""
Tests for FEAT-006 Phase 3 — Depeg → Risk Policy Kill-Switch wiring.

Verifies:
  1) check_portfolio_health() backwards compat when stablecoin_prices is None.
  2) check_portfolio_health() routes CRITICAL depegs → violations and
     WARN depegs → warnings while leaving the existing drawdown/concentration
     checks untouched.
  3) RiskPolicy.check_stablecoin_depeg() standalone helper.

All tests are deterministic — pure Python, no I/O, no network, no sleep.

Run:
    cd spa_core
    python -m pytest tests/test_risk_depeg.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure spa_core package root is importable (mirrors other tests in this dir).
sys.path.insert(0, str(Path(__file__).parent.parent))

from risk.policy import (
    Position,
    PortfolioState,
    RiskCheckResult,
    RiskConfig,
    RiskPolicy,
)


# ─── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def policy() -> RiskPolicy:
    return RiskPolicy(config=RiskConfig())


@pytest.fixture
def healthy_state() -> PortfolioState:
    """$10K portfolio with one healthy T1 position (no drawdown)."""
    return PortfolioState(
        total_capital_usd=10_000.0,
        positions=[
            Position(
                protocol_key="aave-v3-usdc-ethereum",
                tier="T1",
                asset="USDC",
                amount_usd=3_000.0,
                apy_at_open=5.0,
                current_apy=5.2,
                unrealized_pnl_usd=0.0,
            )
        ],
    )


@pytest.fixture
def pegged_prices() -> dict[str, float]:
    """All stablecoins on-peg ($1.00 exactly)."""
    return {"USDC": 1.0, "USDT": 1.0, "DAI": 1.0, "USDS": 1.0}


# ─── check_portfolio_health: depeg wiring ─────────────────────────────────────


def test_no_prices_passed_skips_depeg(policy, healthy_state):
    """
    Backwards compat: omitting stablecoin_prices (or passing None) must
    leave check_portfolio_health behaving byte-for-byte as before — no
    depeg violations or warnings injected.
    """
    # Both forms must behave identically (default value + explicit None).
    res_default = policy.check_portfolio_health(healthy_state)
    res_none = policy.check_portfolio_health(healthy_state, stablecoin_prices=None)

    for res in (res_default, res_none):
        assert isinstance(res, RiskCheckResult)
        assert res.check_name == "portfolio_health"
        # No depeg-injected text in either bucket.
        joined = " ".join(res.violations + res.warnings)
        assert "DEPEG" not in joined
    # Healthy portfolio → still approved.
    assert res_default.approved is True
    assert res_none.approved is True


def test_all_pegged_prices_no_violations(policy, healthy_state, pegged_prices):
    """All stablecoins at $1.00 → no depeg violations or warnings, approved."""
    res = policy.check_portfolio_health(healthy_state, stablecoin_prices=pegged_prices)
    assert res.approved is True
    assert not any("DEPEG" in v for v in res.violations)
    assert not any("DEPEG" in w for w in res.warnings)


def test_warn_depeg_in_check_portfolio_health(policy, healthy_state):
    """
    USDT at $0.97 (-3% dev) under the 2% default threshold sits in the
    WARN band (2% ≤ |dev| < 4%): warnings get a DEPEG WARN entry but the
    portfolio is still approved (drawdown is zero).
    """
    prices = {"USDC": 1.0, "USDT": 0.97, "DAI": 1.0, "USDS": 1.0}
    res = policy.check_portfolio_health(healthy_state, stablecoin_prices=prices)

    depeg_warns = [w for w in res.warnings if "DEPEG WARN" in w]
    depeg_viols = [v for v in res.violations if "DEPEG" in v]

    assert len(depeg_warns) == 1
    assert "USDT" in depeg_warns[0]
    assert len(depeg_viols) == 0
    assert res.approved is True  # WARN does not block


def test_critical_depeg_blocks_portfolio(policy, healthy_state):
    """DAI at $0.95 (-5% dev) ≥ 2×threshold → CRITICAL → violations + reject."""
    prices = {"USDC": 1.0, "USDT": 1.0, "DAI": 0.95, "USDS": 1.0}
    res = policy.check_portfolio_health(healthy_state, stablecoin_prices=prices)

    depeg_viols = [v for v in res.violations if "DEPEG KILL SWITCH" in v]
    assert len(depeg_viols) == 1
    assert "DAI" in depeg_viols[0]
    assert res.approved is False


def test_critical_depeg_independent_of_drawdown(policy):
    """
    Empty / no-PnL portfolio (drawdown 0%) — CRITICAL depeg must still
    block. The depeg check is independent of the drawdown branch.
    """
    state = PortfolioState(total_capital_usd=10_000.0, positions=[])
    prices = {"USDC": 1.0, "USDT": 1.0, "DAI": 0.93, "USDS": 1.0}  # -7% → CRITICAL

    res = policy.check_portfolio_health(state, stablecoin_prices=prices)

    # No drawdown KILL SWITCH violation.
    assert not any("KILL SWITCH TRIGGERED" in v for v in res.violations)
    # But the depeg one is there and blocks the portfolio.
    assert any("DEPEG KILL SWITCH" in v and "DAI" in v for v in res.violations)
    assert res.approved is False


# ─── check_stablecoin_depeg: standalone helper ────────────────────────────────


def test_check_stablecoin_depeg_standalone_pass(policy, pegged_prices):
    """All prices at $1.00 → approved, empty violations & warnings."""
    res = policy.check_stablecoin_depeg(pegged_prices)
    assert isinstance(res, RiskCheckResult)
    assert res.check_name == "stablecoin_depeg"
    assert res.approved is True
    assert res.violations == []
    assert res.warnings == []


def test_check_stablecoin_depeg_warn_tier(policy):
    """
    One coin at $0.975 (-2.5%) with threshold=0.02 → WARN tier
    (2% ≤ |dev| < 4%): warnings == 1, violations == 0, approved.
    """
    prices = {"USDC": 0.975}
    res = policy.check_stablecoin_depeg(prices, threshold=0.02)

    assert len(res.warnings) == 1
    assert len(res.violations) == 0
    assert "DEPEG WARN" in res.warnings[0]
    assert "USDC" in res.warnings[0]
    assert res.approved is True


def test_check_stablecoin_depeg_critical_tier(policy):
    """
    One coin at $0.95 (-5%) with threshold=0.02 → CRITICAL tier
    (|dev| ≥ 4%): violations == 1, approved=False.
    """
    prices = {"DAI": 0.95}
    res = policy.check_stablecoin_depeg(prices, threshold=0.02)

    assert len(res.violations) == 1
    assert "DEPEG KILL SWITCH" in res.violations[0]
    assert "DAI" in res.violations[0]
    assert res.approved is False


def test_custom_threshold_passed_through(policy):
    """
    Lowering threshold to 0.01 makes the check more sensitive.

    Price $0.985 (|dev|=1.5%):
      - default threshold 0.02 → below band → NO event.
      - threshold 0.01 → 0.01 ≤ |dev| < 0.02 → WARN event.

    Price $0.97 (|dev|=3%):
      - threshold 0.01 → |dev| ≥ 2×0.01=0.02 → CRITICAL event (more sensitive
        than default 0.02, which would only flag WARN).
    """
    # 1) Below the default band but inside the tightened WARN band.
    res_default = policy.check_stablecoin_depeg({"USDC": 0.985})
    assert res_default.approved is True
    assert res_default.violations == []
    assert res_default.warnings == []

    res_warn = policy.check_stablecoin_depeg({"USDC": 0.985}, threshold=0.01)
    assert res_warn.approved is True
    assert len(res_warn.warnings) == 1
    assert "DEPEG WARN" in res_warn.warnings[0]
    assert "USDC" in res_warn.warnings[0]
    assert res_warn.violations == []

    # 2) Same price, tighter threshold escalates from WARN (default) to
    #    CRITICAL — proves the threshold value is plumbed into detect_depeg.
    res_default_warn = policy.check_stablecoin_depeg({"DAI": 0.97})
    assert res_default_warn.approved is True
    assert any("DEPEG WARN" in w for w in res_default_warn.warnings)

    res_strict_critical = policy.check_stablecoin_depeg({"DAI": 0.97}, threshold=0.01)
    assert res_strict_critical.approved is False
    assert len(res_strict_critical.violations) == 1
    assert "DEPEG KILL SWITCH" in res_strict_critical.violations[0]
    assert "DAI" in res_strict_critical.violations[0]
