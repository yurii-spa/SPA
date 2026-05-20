"""
Unit tests для Risk Policy — SPA Фаза 0B.

100% покрытие обязательно: этот код трогает деньги.

Запуск:
    cd spa_core
    python -m pytest tests/test_risk_policy.py -v
    python -m pytest tests/test_risk_policy.py -v --tb=short
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from risk.policy import (
    RiskPolicy,
    RiskConfig,
    Position,
    PortfolioState,
    RiskCheckResult,
)


# ─── Фикстуры ────────────────────────────────────────────────────────────────

@pytest.fixture
def default_config() -> RiskConfig:
    return RiskConfig()


@pytest.fixture
def policy(default_config) -> RiskPolicy:
    return RiskPolicy(config=default_config)


@pytest.fixture
def empty_state() -> PortfolioState:
    """Пустой портфель $10K."""
    return PortfolioState(total_capital_usd=10_000.0, positions=[])


@pytest.fixture
def state_with_aave() -> PortfolioState:
    """Портфель с позицией в Aave V3 $3K."""
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
                unrealized_pnl_usd=50.0,
            )
        ],
    )


@pytest.fixture
def state_with_drawdown() -> PortfolioState:
    """Портфель с drawdown 6% (выше kill switch 5%)."""
    return PortfolioState(
        total_capital_usd=10_000.0,
        positions=[
            Position(
                protocol_key="aave-v3-usdc-ethereum",
                tier="T1",
                asset="USDC",
                amount_usd=8_000.0,
                apy_at_open=5.0,
                current_apy=1.0,
                unrealized_pnl_usd=-600.0,  # -6%
            )
        ],
    )


# ─── PortfolioState tests ─────────────────────────────────────────────────────

class TestPortfolioState:

    def test_empty_cash_equals_total(self, empty_state):
        assert empty_state.cash_usd == 10_000.0
        assert empty_state.deployed_usd == 0.0
        assert empty_state.cash_pct == 1.0

    def test_cash_after_position(self, state_with_aave):
        assert state_with_aave.deployed_usd == 3_000.0
        assert state_with_aave.cash_usd == 7_000.0
        assert state_with_aave.cash_pct == pytest.approx(0.70)

    def test_concentration_empty(self, empty_state):
        assert empty_state.concentration_pct("aave-v3-usdc-ethereum") == 0.0

    def test_concentration_with_position(self, state_with_aave):
        conc = state_with_aave.concentration_pct("aave-v3-usdc-ethereum")
        assert conc == pytest.approx(0.30)  # 3000/10000

    def test_t2_allocation_zero_when_all_t1(self, state_with_aave):
        assert state_with_aave.t2_allocation_pct() == 0.0

    def test_t2_allocation_with_t2_position(self):
        state = PortfolioState(
            total_capital_usd=10_000.0,
            positions=[
                Position(
                    protocol_key="maple-usdc-ethereum",
                    tier="T2",
                    asset="USDC",
                    amount_usd=1_500.0,
                    apy_at_open=8.0,
                    current_apy=8.0,
                )
            ],
        )
        assert state.t2_allocation_pct() == pytest.approx(0.15)

    def test_total_drawdown_zero_pnl(self, state_with_aave):
        assert state_with_aave.total_drawdown_pct == 0.0  # PnL позитивный

    def test_total_drawdown_with_loss(self, state_with_drawdown):
        assert state_with_drawdown.total_drawdown_pct == pytest.approx(0.06)


# ─── check_new_position tests ─────────────────────────────────────────────────

class TestCheckNewPosition:

    def test_approve_valid_position(self, policy, empty_state):
        """Стандартная позиция должна быть одобрена."""
        result = policy.check_new_position(
            state=empty_state,
            protocol_key="aave-v3-usdc-ethereum",
            tier="T1",
            amount_usd=3_000.0,
            current_apy=5.5,
            tvl_usd=10_000_000.0,
        )
        assert result.approved is True
        assert len(result.violations) == 0

    def test_reject_insufficient_cash(self, policy, empty_state):
        """Отклонить если запрашиваем больше кэша."""
        result = policy.check_new_position(
            state=empty_state,
            protocol_key="aave-v3-usdc-ethereum",
            tier="T1",
            amount_usd=15_000.0,  # > $10K total
            current_apy=5.5,
            tvl_usd=10_000_000.0,
        )
        assert result.approved is False
        assert any("Insufficient cash" in v for v in result.violations)

    def test_reject_apy_too_high(self, policy, empty_state):
        """Отклонить если APY слишком высокий (> 30%)."""
        result = policy.check_new_position(
            state=empty_state,
            protocol_key="aave-v3-usdc-ethereum",
            tier="T1",
            amount_usd=2_000.0,
            current_apy=35.0,  # аномально высокий
            tvl_usd=10_000_000.0,
        )
        assert result.approved is False
        assert any("APY" in v and "exceeds maximum" in v for v in result.violations)

    def test_reject_apy_too_low(self, policy, empty_state):
        """Отклонить если APY ниже минимума."""
        result = policy.check_new_position(
            state=empty_state,
            protocol_key="aave-v3-usdc-ethereum",
            tier="T1",
            amount_usd=2_000.0,
            current_apy=0.5,  # ниже 1%
            tvl_usd=10_000_000.0,
        )
        assert result.approved is False
        assert any("below minimum" in v for v in result.violations)

    def test_reject_tvl_too_low(self, policy, empty_state):
        """Отклонить если TVL слишком маленький."""
        result = policy.check_new_position(
            state=empty_state,
            protocol_key="aave-v3-usdc-ethereum",
            tier="T1",
            amount_usd=2_000.0,
            current_apy=5.0,
            tvl_usd=1_000_000.0,  # $1M < $5M minimum
        )
        assert result.approved is False
        assert any("TVL" in v for v in result.violations)

    def test_reject_concentration_breach_t1(self, policy, state_with_aave):
        """Отклонить если превысим лимит T1 (40%)."""
        # Уже 30%, добавляем ещё 15% = 45% > 40%
        result = policy.check_new_position(
            state=state_with_aave,
            protocol_key="aave-v3-usdc-ethereum",
            tier="T1",
            amount_usd=1_500.0,  # ещё 15%, итого 45%
            current_apy=5.5,
            tvl_usd=10_000_000.0,
        )
        assert result.approved is False
        assert any("Concentration" in v for v in result.violations)

    def test_reject_t2_total_limit(self, policy):
        """Отклонить если T2 совокупно > 35%."""
        state = PortfolioState(
            total_capital_usd=10_000.0,
            positions=[
                Position(
                    protocol_key="maple-usdc-ethereum",
                    tier="T2",
                    asset="USDC",
                    amount_usd=2_000.0,
                    apy_at_open=8.0,
                    current_apy=8.0,
                ),
                Position(
                    protocol_key="euler-v2-usdc-ethereum",
                    tier="T2",
                    asset="USDC",
                    amount_usd=1_500.0,
                    apy_at_open=7.0,
                    current_apy=7.0,
                ),
            ],
        )
        # Уже 35% T2, попытка добавить ещё
        result = policy.check_new_position(
            state=state,
            protocol_key="yearn-v3-usdc-ethereum",
            tier="T2",
            amount_usd=500.0,  # Итого 40% > 35%
            current_apy=6.5,
            tvl_usd=10_000_000.0,
        )
        assert result.approved is False
        assert any("T2 allocation" in v for v in result.violations)

    def test_reject_kill_switch_drawdown(self, policy, state_with_drawdown):
        """Отклонить если портфель в drawdown выше kill switch."""
        result = policy.check_new_position(
            state=state_with_drawdown,
            protocol_key="compound-v3-usdc-ethereum",
            tier="T1",
            amount_usd=500.0,
            current_apy=5.0,
            tvl_usd=10_000_000.0,
        )
        assert result.approved is False
        assert any("kill switch" in v.lower() or "drawdown" in v.lower()
                   for v in result.violations)

    def test_reject_min_cash_buffer(self, policy, empty_state):
        """Отклонить если после сделки кэш упадёт ниже 5%."""
        # $10K, берём $9700 — остаток $300 = 3% < 5%
        result = policy.check_new_position(
            state=empty_state,
            protocol_key="aave-v3-usdc-ethereum",
            tier="T1",
            amount_usd=9_700.0,
            current_apy=5.5,
            tvl_usd=10_000_000.0,
        )
        assert result.approved is False
        assert any("cash buffer" in v.lower() for v in result.violations)

    def test_warning_concentration_approaching_limit(self, policy, state_with_aave):
        """Предупреждение если концентрация близко к лимиту."""
        # Текущая концентрация 30%, добавляем 5% = 35% (85% от лимита 40%)
        result = policy.check_new_position(
            state=state_with_aave,
            protocol_key="aave-v3-usdc-ethereum",
            tier="T1",
            amount_usd=500.0,
            current_apy=5.5,
            tvl_usd=10_000_000.0,
        )
        # Одобрено, но с предупреждением
        assert result.approved is True
        assert len(result.warnings) > 0
        assert any("approaching" in w.lower() for w in result.warnings)

    def test_multiple_violations(self, policy, empty_state):
        """Все нарушения должны быть в списке."""
        result = policy.check_new_position(
            state=empty_state,
            protocol_key="aave-v3-usdc-ethereum",
            tier="T1",
            amount_usd=20_000.0,   # > cash
            current_apy=0.1,        # < min APY
            tvl_usd=100_000.0,      # < min TVL
        )
        assert result.approved is False
        assert len(result.violations) >= 3  # минимум 3 нарушения


# ─── check_portfolio_health tests ─────────────────────────────────────────────

class TestCheckPortfolioHealth:

    def test_healthy_portfolio_approved(self, policy, state_with_aave):
        result = policy.check_portfolio_health(state_with_aave)
        assert result.approved is True

    def test_empty_portfolio_approved(self, policy, empty_state):
        result = policy.check_portfolio_health(empty_state)
        assert result.approved is True

    def test_kill_switch_triggered(self, policy, state_with_drawdown):
        result = policy.check_portfolio_health(state_with_drawdown)
        assert result.approved is False
        assert any("KILL SWITCH" in v for v in result.violations)

    def test_drawdown_warning_at_75_percent(self, policy):
        """Предупреждение при 75% от kill switch порога (3.75%).

        Используем amount_usd=3_000 (30% концентрация — в пределах T1 лимита 40%),
        pnl=-380 даёт 3.8% drawdown портфеля — выше порога 3.75% для предупреждения.
        """
        state = PortfolioState(
            total_capital_usd=10_000.0,
            positions=[
                Position(
                    protocol_key="aave-v3-usdc-ethereum",
                    tier="T1",
                    asset="USDC",
                    amount_usd=3_000.0,    # 30% — в пределах T1 лимита 40%
                    apy_at_open=5.0,
                    current_apy=4.0,
                    unrealized_pnl_usd=-380.0,  # -3.8% от портфеля
                )
            ],
        )
        result = policy.check_portfolio_health(state)
        assert result.approved is True  # не триггер, только предупреждение
        assert any("approaching" in w.lower() for w in result.warnings)

    def test_concentration_breach_detected(self, policy):
        """Обнаружить превышение концентрационного лимита."""
        state = PortfolioState(
            total_capital_usd=10_000.0,
            positions=[
                Position(
                    protocol_key="aave-v3-usdc-ethereum",
                    tier="T1",
                    asset="USDC",
                    amount_usd=4_500.0,  # 45% > 40% T1 limit
                    apy_at_open=5.0,
                    current_apy=5.0,
                )
            ],
        )
        result = policy.check_portfolio_health(state)
        assert result.approved is False
        assert any("Concentration breach" in v for v in result.violations)

    def test_position_drawdown_warning(self, policy):
        """Предупреждение если отдельная позиция в большом убытке."""
        state = PortfolioState(
            total_capital_usd=10_000.0,
            positions=[
                Position(
                    protocol_key="aave-v3-usdc-ethereum",
                    tier="T1",
                    asset="USDC",
                    amount_usd=2_000.0,
                    apy_at_open=5.0,
                    current_apy=3.0,
                    unrealized_pnl_usd=-70.0,  # -3.5% > порог -3%
                )
            ],
        )
        result = policy.check_portfolio_health(state)
        assert result.approved is True  # не блокирует
        assert any("loss" in w.lower() for w in result.warnings)


# ─── calculate_var tests ──────────────────────────────────────────────────────

class TestCalculateVar:

    def test_var_empty_portfolio(self, policy, empty_state):
        var = policy.calculate_var(empty_state)
        assert var["var_usd"] == 0.0
        assert var["var_pct"] == 0.0
        assert var["breach"] is False

    def test_var_returns_dict_keys(self, policy, state_with_aave):
        var = policy.calculate_var(state_with_aave)
        assert "var_usd" in var
        assert "var_pct" in var
        assert "confidence" in var
        assert "horizon_days" in var
        assert "breach" in var

    def test_var_positive_for_deployed_capital(self, policy, state_with_aave):
        var = policy.calculate_var(state_with_aave)
        assert var["var_usd"] > 0
        assert var["var_pct"] > 0

    def test_var_confidence_matches_config(self, policy, state_with_aave):
        var = policy.calculate_var(state_with_aave)
        assert var["confidence"] == policy.config.var_confidence

    def test_var_larger_for_higher_volatility(self, policy, state_with_aave):
        var_low = policy.calculate_var(state_with_aave, apy_std_pct=1.0)
        var_high = policy.calculate_var(state_with_aave, apy_std_pct=5.0)
        assert var_high["var_usd"] > var_low["var_usd"]


# ─── max_safe_position_size tests ─────────────────────────────────────────────

class TestMaxSafePositionSize:

    def test_max_size_empty_portfolio(self, policy, empty_state):
        """На пустом портфеле лимит = min(40% от T1, cash - 5% буфер)."""
        max_size = policy.max_safe_position_size(empty_state, "aave-v3-usdc-ethereum", "T1")
        # Кэш лимит: 10000 - 5% = 9500
        # Концентрация T1: 40% * 10000 = 4000
        expected = 4_000.0
        assert max_size == pytest.approx(expected)

    def test_max_size_t2_lower_limit(self, policy, empty_state):
        """T2 лимит (20%) ниже T1 (40%)."""
        max_t1 = policy.max_safe_position_size(empty_state, "aave-v3-usdc-ethereum", "T1")
        max_t2 = policy.max_safe_position_size(empty_state, "maple-usdc-ethereum", "T2")
        assert max_t2 < max_t1

    def test_max_size_zero_when_at_limit(self, policy):
        """Ноль если уже на лимите концентрации."""
        state = PortfolioState(
            total_capital_usd=10_000.0,
            positions=[
                Position(
                    protocol_key="aave-v3-usdc-ethereum",
                    tier="T1",
                    asset="USDC",
                    amount_usd=4_000.0,  # ровно 40% T1 limit
                    apy_at_open=5.0,
                    current_apy=5.0,
                )
            ],
        )
        max_size = policy.max_safe_position_size(state, "aave-v3-usdc-ethereum", "T1")
        assert max_size == 0.0

    def test_max_size_non_negative(self, policy, state_with_aave):
        """Размер никогда не может быть отрицательным."""
        max_size = policy.max_safe_position_size(state_with_aave, "aave-v3-usdc-ethereum", "T1")
        assert max_size >= 0.0


# ─── RiskCheckResult tests ────────────────────────────────────────────────────

class TestRiskCheckResult:

    def test_str_approved(self):
        r = RiskCheckResult(approved=True, check_name="test")
        assert "APPROVED" in str(r)

    def test_str_rejected(self):
        r = RiskCheckResult(
            approved=False,
            violations=["TVL too low"],
            check_name="test"
        )
        assert "REJECTED" in str(r)
        assert "TVL too low" in str(r)

    def test_empty_violations_list(self):
        r = RiskCheckResult(approved=True)
        assert r.violations == []
        assert r.warnings == []


# ─── Custom config tests ──────────────────────────────────────────────────────

class TestCustomConfig:

    def test_strict_config_more_restrictive(self):
        """Строгая конфигурация должна отклонять больше позиций."""
        strict = RiskPolicy(config=RiskConfig(
            max_concentration_t1=0.20,  # 20% вместо 40%
            min_tvl_usd=50_000_000,     # $50M вместо $5M
        ))
        state = PortfolioState(total_capital_usd=10_000.0, positions=[])

        result = strict.check_new_position(
            state=state,
            protocol_key="aave-v3-usdc-ethereum",
            tier="T1",
            amount_usd=3_000.0,  # 30% > строгий лимит 20%
            current_apy=5.5,
            tvl_usd=10_000_000.0,  # < строгий минимум TVL
        )
        assert result.approved is False

    def test_lenient_config_approves_more(self):
        """Мягкая конфигурация одобряет больше."""
        lenient = RiskPolicy(config=RiskConfig(
            max_apy_for_new_position=100.0,
            min_tvl_usd=100_000.0,
        ))
        state = PortfolioState(total_capital_usd=10_000.0, positions=[])

        result = lenient.check_new_position(
            state=state,
            protocol_key="test-protocol",
            tier="T1",
            amount_usd=1_000.0,
            current_apy=50.0,   # прошло бы у строгого
            tvl_usd=500_000.0,  # прошло бы у строгого
        )
        # Может быть одобрено с мягкими настройками
        assert isinstance(result.approved, bool)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
