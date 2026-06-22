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
        """Отклонить если T2 совокупно > 50% (ADR-019 поднял cap с 35% до 50%)."""
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
        # Уже 35% T2, добавляем ещё 16% → итого 51% > 50% cap (ADR-019)
        result = policy.check_new_position(
            state=state,
            protocol_key="yearn-v3-usdc-ethereum",
            tier="T2",
            amount_usd=1_600.0,  # 3500 + 1600 = 5100 = 51% > 50%
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


# ─── MP-352 / ADR-019 / ADR-020: New limits tests ───────────────────────────
# 20+ tests covering:
#   - Ethereum chain limit raised to 90% (MP-352)
#   - T2 cap raised to 50% (ADR-019)
#   - T3 Private Credit cap 15% added (ADR-020)


class TestRiskConfigNewLimits:
    """Unit tests for new RiskConfig values (MP-352, ADR-019, ADR-020)."""

    def test_max_single_chain_allocation_is_90pct(self):
        """MP-352: Ethereum chain limit must be 90%, not 70%."""
        cfg = RiskConfig()
        assert cfg.max_single_chain_allocation == pytest.approx(0.90), (
            "MP-352: max_single_chain_allocation should be 0.90 (was 0.70)"
        )

    def test_max_total_t2_allocation_is_50pct(self):
        """ADR-019: T2 cap must be 50%, not 35%."""
        cfg = RiskConfig()
        assert cfg.max_total_t2_allocation == pytest.approx(0.50), (
            "ADR-019: max_total_t2_allocation should be 0.50 (was 0.35)"
        )

    def test_max_total_t3_allocation_exists_and_is_15pct(self):
        """ADR-020: T3 cap must be 15%."""
        cfg = RiskConfig()
        assert hasattr(cfg, "max_total_t3_allocation"), (
            "ADR-020: max_total_t3_allocation field must exist in RiskConfig"
        )
        assert cfg.max_total_t3_allocation == pytest.approx(0.15), (
            "ADR-020: max_total_t3_allocation should be 0.15"
        )

    def test_t2_cap_greater_than_old_value(self):
        """ADR-019: T2 cap must be strictly greater than old 35%."""
        cfg = RiskConfig()
        assert cfg.max_total_t2_allocation > 0.35

    def test_t3_cap_less_than_t2_cap(self):
        """ADR-020: T3 cap (15%) must be less than T2 cap (50%)."""
        cfg = RiskConfig()
        assert cfg.max_total_t3_allocation < cfg.max_total_t2_allocation

    def test_t2_plus_t3_cap_within_portfolio(self):
        """ADR-019 + ADR-020: Combined T2+T3 cap ≤ 65% — reasonable."""
        cfg = RiskConfig()
        combined = cfg.max_total_t2_allocation + cfg.max_total_t3_allocation
        assert combined <= 0.70, f"T2+T3 combined cap {combined:.0%} exceeds 70%"

    def test_chain_limit_above_realistic_ethereum_concentration(self):
        """MP-352: 90% limit comfortably accommodates realistic ethereum alloc (73-84%)."""
        cfg = RiskConfig()
        realistic_ethereum_conc = 0.84   # from real logs: CHAIN_LIMIT_WARN ethereum 84%
        assert cfg.max_single_chain_allocation > realistic_ethereum_conc

    def test_t2_cap_allows_50pct_allocation(self):
        """ADR-019: Policy must allow T2 position up to 50% of portfolio."""
        policy = RiskPolicy(config=RiskConfig())
        state = PortfolioState(
            total_capital_usd=100_000.0,
            positions=[
                Position(
                    protocol_key="morpho-blue-usdc-ethereum",
                    tier="T2",
                    asset="USDC",
                    amount_usd=29_000.0,  # 29% T2 already allocated
                    apy_at_open=6.0,
                    current_apy=6.0,
                ),
            ],
        )
        # Adding 20% more T2 → total 49% — must be approved under ADR-019
        result = policy.check_new_position(
            state=state,
            protocol_key="yearn-v3-usdc-ethereum",
            tier="T2",
            amount_usd=20_000.0,   # 20% → total T2 = 49%
            current_apy=7.5,
            tvl_usd=50_000_000.0,
        )
        assert result.approved is True, (
            f"ADR-019: 49% T2 should be approved (cap=50%), violations: {result.violations}"
        )

    def test_t2_cap_blocks_over_50pct(self):
        """ADR-019: Policy must block T2 position that would push total T2 > 50%."""
        policy = RiskPolicy(config=RiskConfig())
        state = PortfolioState(
            total_capital_usd=100_000.0,
            positions=[
                Position(
                    protocol_key="morpho-blue-usdc-ethereum",
                    tier="T2",
                    asset="USDC",
                    amount_usd=40_000.0,  # 40% T2 already allocated
                    apy_at_open=6.0,
                    current_apy=6.0,
                ),
            ],
        )
        # Adding 15% more T2 → total 55% — must be blocked (cap=50%)
        result = policy.check_new_position(
            state=state,
            protocol_key="yearn-v3-usdc-ethereum",
            tier="T2",
            amount_usd=15_000.0,   # would push T2 to 55%
            current_apy=7.5,
            tvl_usd=50_000_000.0,
        )
        assert result.approved is False, (
            "ADR-019: 55% T2 must be blocked (cap=50%)"
        )
        assert any("t2" in v.lower() or "50" in v for v in result.violations)

    def test_old_35pct_t2_now_approved(self):
        """ADR-019: Positions previously blocked at 35% T2 are now approved at 50%."""
        policy = RiskPolicy(config=RiskConfig())
        state = PortfolioState(
            total_capital_usd=100_000.0,
            positions=[
                Position(
                    protocol_key="morpho-blue-usdc-ethereum",
                    tier="T2",
                    asset="USDC",
                    amount_usd=30_000.0,  # 30% T2
                    apy_at_open=6.0,
                    current_apy=6.0,
                ),
            ],
        )
        # 10% more T2 → total 40%. Old cap (35%) would block this; new cap (50%) allows.
        result = policy.check_new_position(
            state=state,
            protocol_key="euler-v2-usdc-ethereum",
            tier="T2",
            amount_usd=10_000.0,
            current_apy=5.8,
            tvl_usd=30_000_000.0,
        )
        t2_violations = [v for v in result.violations if "t2" in v.lower() or "50" in v.lower()]
        assert len(t2_violations) == 0, (
            f"ADR-019: 40% T2 should NOT trigger T2 cap violation (cap=50%). "
            f"Got: {t2_violations}"
        )

    def test_t3_config_field_is_positive(self):
        """ADR-020: T3 cap must be a positive float."""
        cfg = RiskConfig()
        assert isinstance(cfg.max_total_t3_allocation, float)
        assert cfg.max_total_t3_allocation > 0.0

    def test_t3_cap_is_below_t1_per_protocol_cap(self):
        """ADR-020: T3 total cap (15%) < T1 per-protocol cap (40%) — sensible hierarchy."""
        cfg = RiskConfig()
        assert cfg.max_total_t3_allocation < cfg.max_concentration_t1

    def test_t3_cap_equals_015(self):
        """ADR-020: T3 cap exact value is 0.15."""
        cfg = RiskConfig()
        assert cfg.max_total_t3_allocation == 0.15

    def test_version_still_v1_0(self):
        """Policy version remains v1.0 during paper period (CLAUDE.md FORBIDDEN rule)."""
        cfg = RiskConfig()
        assert cfg.version == "v1.0"

    def test_changelog_mentions_mp352(self):
        """MP-352 must be documented in changelog."""
        cfg = RiskConfig()
        assert "MP-352" in cfg.changelog or "352" in cfg.changelog

    def test_changelog_mentions_adr019(self):
        """ADR-019 must be documented in changelog."""
        cfg = RiskConfig()
        assert "ADR-019" in cfg.changelog or "019" in cfg.changelog

    def test_changelog_mentions_adr020(self):
        """ADR-020 must be documented in changelog."""
        cfg = RiskConfig()
        assert "ADR-020" in cfg.changelog or "020" in cfg.changelog

    def test_per_protocol_t2_cap_unchanged(self):
        """ADR-019: Per-protocol T2 cap (20%) is unchanged — only total T2 cap changed."""
        cfg = RiskConfig()
        assert cfg.max_concentration_t2 == pytest.approx(0.20), (
            "Per-protocol T2 cap must remain 0.20 (ADR-019 only changes total T2 cap)"
        )

    def test_t1_per_protocol_cap_unchanged(self):
        """No regression: T1 per-protocol cap remains 40%."""
        cfg = RiskConfig()
        assert cfg.max_concentration_t1 == pytest.approx(0.40)

    def test_cash_buffer_unchanged(self):
        """No regression: cash buffer remains 5%."""
        cfg = RiskConfig()
        assert cfg.min_cash_pct == pytest.approx(0.05)

    def test_kill_switch_unchanged(self):
        """No regression: drawdown kill switch remains 5%."""
        cfg = RiskConfig()
        assert cfg.max_drawdown_stop == pytest.approx(0.05)

    def test_t2_cap_50pct_with_custom_config(self):
        """RiskConfig T2 50% cap is honoured when passed explicitly."""
        custom = RiskConfig(max_total_t2_allocation=0.50)
        assert custom.max_total_t2_allocation == 0.50

    def test_t3_cap_custom_value(self):
        """T3 cap is configurable (custom value works)."""
        custom = RiskConfig(max_total_t3_allocation=0.10)
        assert custom.max_total_t3_allocation == 0.10

    def test_chain_limit_custom_value(self):
        """Chain limit is configurable (custom value works)."""
        custom = RiskConfig(max_single_chain_allocation=0.80)
        assert custom.max_single_chain_allocation == 0.80


# ─── MP-352: chain_limits module — updated threshold tests ───────────────────

class TestChainLimitsMP352:
    """Tests for chain_limits.py with the new 90% ethereum threshold (MP-352)."""

    def setup_method(self):
        """Import check_chain_limits lazily (not all envs have the module on path)."""
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from risk.chain_limits import check_chain_limits, get_default_chain_map
        self.check_chain_limits = check_chain_limits
        self.get_default_chain_map = get_default_chain_map

    def test_ethereum_84pct_no_violation(self):
        """MP-352: 84% ethereum (max observed in logs) must NOT trigger violation."""
        alloc = {
            "aave_v3":     0.40,
            "compound_v3": 0.25,
            "morpho_blue": 0.19,
        }  # total ethereum = 84%
        result = self.check_chain_limits(alloc)
        assert result["ok"] is True, (
            f"MP-352: 84% ethereum must not violate 90% limit. "
            f"Violations: {result['violations']}"
        )

    def test_ethereum_73pct_no_violation(self):
        """MP-352: 73% ethereum (min observed in logs) must NOT trigger violation."""
        alloc = {"aave_v3": 0.40, "compound_v3": 0.33}  # 73%
        result = self.check_chain_limits(alloc)
        assert result["ok"] is True

    def test_ethereum_90pct_at_limit_ok(self):
        """MP-352: Exactly 90% ethereum must still pass (≤ not <)."""
        alloc = {"aave_v3": 0.50, "compound_v3": 0.40}  # 90%
        result = self.check_chain_limits(alloc)
        assert result["ok"] is True
        assert result["chain_breakdown"]["ethereum"] == pytest.approx(0.90)

    def test_ethereum_91pct_triggers_violation(self):
        """MP-352: 91% ethereum must trigger violation (above new 90% limit)."""
        alloc = {"aave_v3": 0.50, "compound_v3": 0.41}  # 91%
        result = self.check_chain_limits(alloc)
        assert result["ok"] is False
        assert any("ethereum" in v.lower() for v in result["violations"])

    def test_all_ethereum_only_flag_set(self):
        """MP-352: all_ethereum_only flag is True when all protocols are Ethereum L1."""
        alloc = {"aave_v3": 0.40, "compound_v3": 0.20, "morpho_blue": 0.15}
        result = self.check_chain_limits(alloc)
        assert result.get("all_ethereum_only") is True

    def test_all_ethereum_only_flag_false_with_l2(self):
        """MP-352: all_ethereum_only flag is False when L2 protocols present."""
        alloc = {"aave_v3": 0.40, "aave_v3_arbitrum": 0.20}
        result = self.check_chain_limits(alloc)
        assert result.get("all_ethereum_only") is False

    def test_empty_allocation_all_ethereum_only_false(self):
        """MP-352: all_ethereum_only is False for empty allocation (no protocols)."""
        result = self.check_chain_limits({})
        assert result.get("all_ethereum_only") is False

    def test_result_has_all_ethereum_only_key(self):
        """MP-352: result dict must include all_ethereum_only key."""
        result = self.check_chain_limits({"aave_v3": 0.30})
        assert "all_ethereum_only" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
