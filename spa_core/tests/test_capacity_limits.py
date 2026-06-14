"""
Unit tests для spa_core/risk/capacity_limits.py (MP-209).

Минимум 30 тестов, охватывающих:
  - check_capacity(): ok, violation, граничные значения, no-TVL
  - check_all_capacities(): все ok, одно нарушение, несколько, missing TVL
  - apply_capacity_caps(): обрезание, unknown TVL pass-through, без изменений
  - build_tvl_map(): реальная структура, пустой input, нулевой TVL, только alias tvl
  - effective_max_pct(): T1 high-TVL исключение, T2, пограничный TVL
  - Регрессия: check_new_position / check_portfolio_health из policy.py не ломаются

Запуск:
    python3 -m pytest spa_core/tests/test_capacity_limits.py -v
    python3 -m pytest spa_core/tests/test_capacity_limits.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

# Добавляем корень проекта в sys.path для импорта модулей
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest

from spa_core.risk.capacity_limits import (
    MAX_CAPACITY_PCT,
    T1_HIGH_TVL_CAPACITY_PCT,
    T1_HIGH_TVL_THRESHOLD_USD,
    apply_capacity_caps,
    build_tvl_map,
    check_all_capacities,
    check_capacity,
    effective_max_pct,
)


# ─── Фикстуры ────────────────────────────────────────────────────────────────

@pytest.fixture
def small_pool_tvl() -> float:
    """$5M TVL — минимальный по RiskPolicy."""
    return 5_000_000.0


@pytest.fixture
def large_pool_tvl() -> float:
    """$200M TVL — типичный Aave."""
    return 200_000_000.0


@pytest.fixture
def huge_pool_tvl() -> float:
    """$2B TVL — крупный T1 с high-TVL исключением."""
    return 2_000_000_000.0


@pytest.fixture
def sample_adapter_status() -> dict:
    """Реальная структура adapter_orchestrator_status.json."""
    return {
        "generated_at": "2026-06-11T06:00:05.334976+00:00",
        "adapters": [
            {
                "protocol": "aave_v3",
                "tier": "T1",
                "apy_pct": 3.19,
                "tvl_usd": 189_455_356.0,
                "status": "ok",
            },
            {
                "protocol": "compound_v3",
                "tier": "T1",
                "apy_pct": 3.18,
                "tvl_usd": 48_426_912.0,
                "status": "ok",
            },
            {
                "protocol": "morpho_blue",
                "tier": "T2",
                "apy_pct": None,
                "tvl_usd": None,  # нет TVL — timeout
                "status": "timeout",
            },
            {
                "protocol": "yearn_v3",
                "tier": "T2",
                "apy_pct": 3.23,
                "tvl_usd": 26_689_422.0,
                "status": "ok",
            },
            {
                "protocol": "euler_v2",
                "tier": "T2",
                "apy_pct": 2.82,
                "tvl_usd": 15_730_776.0,
                "status": "ok",
            },
            {
                "protocol": "maple",
                "tier": "T2",
                "apy_pct": 4.72,
                "tvl_usd": 3_115_803_969.0,
                "status": "ok",
            },
        ],
    }


# ─── check_capacity(): ok cases ─────────────────────────────────────────────

class TestCheckCapacityOk:

    def test_well_below_limit(self, small_pool_tvl):
        """$1K в $5M пуле = 0.02% — хорошо ниже 1%."""
        r = check_capacity("proto_a", 1_000.0, small_pool_tvl)
        assert r["ok"] is True
        assert r["message"] == "ok"
        assert r["excess_usd"] == 0.0

    def test_exactly_at_limit(self, small_pool_tvl):
        """$50K в $5M пуле = ровно 1% — ok (граница включается)."""
        limit = small_pool_tvl * MAX_CAPACITY_PCT  # $50K
        r = check_capacity("proto_a", limit, small_pool_tvl)
        assert r["ok"] is True
        assert r["excess_usd"] == 0.0

    def test_just_below_limit(self, small_pool_tvl):
        """$49_999 в $5M = 0.99998% — ok."""
        r = check_capacity("proto_a", 49_999.0, small_pool_tvl)
        assert r["ok"] is True

    def test_large_pool_reasonable_position(self, large_pool_tvl):
        """$40K в $200M пуле = 0.02% — ok."""
        r = check_capacity("aave_v3", 40_000.0, large_pool_tvl)
        assert r["ok"] is True
        assert r["capacity_pct"] == pytest.approx(40_000.0 / 200_000_000.0)

    def test_protocol_id_preserved(self):
        """protocol_id должен возвращаться в ответе."""
        r = check_capacity("my_protocol_xyz", 1_000.0, 1_000_000.0)
        assert r["protocol_id"] == "my_protocol_xyz"

    def test_custom_max_pct(self):
        """Кастомный max_pct=0.05 (5%)."""
        r = check_capacity("proto", 4_000.0, 100_000.0, max_pct=0.05)
        assert r["ok"] is True  # 4% < 5%
        assert r["max_pct"] == 0.05
        assert r["max_deployable_usd"] == pytest.approx(5_000.0)


# ─── check_capacity(): violation cases ──────────────────────────────────────

class TestCheckCapacityViolation:

    def test_just_over_limit(self, small_pool_tvl):
        """$50_001 в $5M пуле = 1.000020% — violation."""
        r = check_capacity("proto_a", 50_001.0, small_pool_tvl)
        assert r["ok"] is False
        assert "exceeds_capacity_limit" in r["message"]
        assert r["excess_usd"] > 0

    def test_gross_violation(self, small_pool_tvl):
        """$1M в $5M пуле = 20% — явное нарушение."""
        r = check_capacity("proto_a", 1_000_000.0, small_pool_tvl)
        assert r["ok"] is False
        assert r["capacity_pct"] == pytest.approx(0.20)
        assert r["excess_usd"] == pytest.approx(950_000.0)  # 1M - 50K

    def test_message_contains_percentages(self, small_pool_tvl):
        """Message должен содержать фактический и максимальный %."""
        r = check_capacity("proto_a", 100_000.0, small_pool_tvl)  # 2%
        assert "2.00%" in r["message"]
        assert "1.00%" in r["message"]

    def test_excess_usd_correct(self):
        """excess_usd = proposed - max_deployable."""
        # $30K в $100K пуле при лимите 10% → max=$10K, excess=$20K
        r = check_capacity("p", 30_000.0, 100_000.0, max_pct=0.10)
        assert r["ok"] is False
        assert r["excess_usd"] == pytest.approx(20_000.0)


# ─── check_capacity(): no TVL ────────────────────────────────────────────────

class TestCheckCapacityNoTvl:

    def test_zero_tvl_passthrough(self):
        """TVL=0 → ok=True (fail-safe, не блокируем)."""
        r = check_capacity("proto_a", 50_000.0, 0.0)
        assert r["ok"] is True
        assert "no_tvl_data" in r["message"]

    def test_none_tvl_passthrough(self):
        """TVL=None → ok=True (fail-safe)."""
        r = check_capacity("proto_a", 50_000.0, None)
        assert r["ok"] is True
        assert "no_tvl_data" in r["message"]

    def test_negative_tvl_passthrough(self):
        """Отрицательный TVL → ok=True (fail-safe)."""
        r = check_capacity("proto_a", 50_000.0, -1_000.0)
        assert r["ok"] is True

    def test_max_deployable_zero_when_no_tvl(self):
        """max_deployable_usd=0 когда TVL недоступен."""
        r = check_capacity("proto_a", 10_000.0, 0.0)
        assert r["max_deployable_usd"] == 0.0


# ─── check_all_capacities() ─────────────────────────────────────────────────

class TestCheckAllCapacities:

    def test_all_ok(self):
        """Все позиции в лимите → ok=True, violations=[]."""
        allocation = {"aave_v3": 1_000.0, "compound_v3": 500.0}
        tvl_map = {"aave_v3": 100_000_000.0, "compound_v3": 50_000_000.0}
        r = check_all_capacities(allocation, tvl_map)
        assert r["ok"] is True
        assert r["violations"] == []
        assert r["warnings"] == []

    def test_single_violation(self):
        """Одно нарушение → ok=False, одна violations."""
        allocation = {"aave_v3": 10_000.0, "compound_v3": 500.0}
        tvl_map = {"aave_v3": 100_000.0, "compound_v3": 50_000_000.0}
        # aave_v3: $10K / $100K = 10% > 1% → violation
        r = check_all_capacities(allocation, tvl_map)
        assert r["ok"] is False
        assert len(r["violations"]) == 1
        assert "aave_v3" in r["violations"][0]

    def test_multiple_violations(self):
        """Несколько нарушений."""
        allocation = {"proto_a": 5_000.0, "proto_b": 3_000.0}
        tvl_map = {"proto_a": 100_000.0, "proto_b": 100_000.0}
        # proto_a: 5%, proto_b: 3% — оба > 1%
        r = check_all_capacities(allocation, tvl_map)
        assert r["ok"] is False
        assert len(r["violations"]) == 2

    def test_missing_tvl_warning(self):
        """Протокол без TVL → warnings, не violations."""
        allocation = {"aave_v3": 1_000.0, "unknown_proto": 500.0}
        tvl_map = {"aave_v3": 100_000_000.0}  # unknown_proto нет
        r = check_all_capacities(allocation, tvl_map)
        assert r["ok"] is True  # только warning, не нарушение
        assert len(r["warnings"]) == 1
        assert "unknown_proto" in r["warnings"][0]

    def test_zero_allocation_skipped(self):
        """Нулевые позиции пропускаются."""
        allocation = {"proto_a": 0.0, "proto_b": 100.0}
        tvl_map = {"proto_a": 1_000.0, "proto_b": 100_000_000.0}
        r = check_all_capacities(allocation, tvl_map)
        assert r["ok"] is True
        assert "proto_a" not in r["results"]  # пропущен (0 allocation)

    def test_results_contains_all_checked_protocols(self):
        """results должен содержать все проверенные протоколы."""
        allocation = {"a": 1_000.0, "b": 500.0}
        tvl_map = {"a": 10_000_000.0, "b": 10_000_000.0}
        r = check_all_capacities(allocation, tvl_map)
        assert "a" in r["results"]
        assert "b" in r["results"]

    def test_custom_max_pct(self):
        """Кастомный лимит 5%."""
        allocation = {"proto": 4_000.0}
        tvl_map = {"proto": 100_000.0}  # 4% < 5% → ok
        r = check_all_capacities(allocation, tvl_map, max_pct=0.05)
        assert r["ok"] is True

    def test_empty_allocation(self):
        """Пустая аллокация → ok=True."""
        r = check_all_capacities({}, {"proto": 1_000_000.0})
        assert r["ok"] is True
        assert r["violations"] == []

    def test_empty_tvl_map(self):
        """Пустой tvl_map → все в warnings (нет TVL данных), ok=True."""
        allocation = {"proto_a": 1_000.0}
        r = check_all_capacities(allocation, {})
        assert r["ok"] is True
        assert len(r["warnings"]) == 1


# ─── apply_capacity_caps() ───────────────────────────────────────────────────

class TestApplyCapacityCaps:

    def test_no_cap_needed(self):
        """Позиции в лимите → возвращает без изменений."""
        allocation = {"aave_v3": 1_000.0}
        tvl_map = {"aave_v3": 100_000_000.0}
        result = apply_capacity_caps(allocation, tvl_map)
        assert result["aave_v3"] == pytest.approx(1_000.0)

    def test_caps_correctly(self):
        """Позиция выше лимита → обрезается до max_deployable."""
        allocation = {"proto_a": 100_000.0}
        tvl_map = {"proto_a": 5_000_000.0}  # max = $50K (1%)
        result = apply_capacity_caps(allocation, tvl_map)
        assert result["proto_a"] == pytest.approx(50_000.0)

    def test_unknown_tvl_passthrough(self):
        """Нет TVL для протокола → pass-through (fail-safe)."""
        allocation = {"known": 1_000.0, "unknown": 50_000.0}
        tvl_map = {"known": 100_000_000.0}
        result = apply_capacity_caps(allocation, tvl_map)
        assert result["unknown"] == pytest.approx(50_000.0)  # без изменений

    def test_zero_tvl_passthrough(self):
        """TVL=0 → pass-through."""
        allocation = {"proto": 50_000.0}
        tvl_map = {"proto": 0.0}
        result = apply_capacity_caps(allocation, tvl_map)
        assert result["proto"] == pytest.approx(50_000.0)

    def test_all_within_limits_unchanged(self):
        """Все в лимите → исходный dict без изменений по значениям."""
        allocation = {"a": 100.0, "b": 200.0, "c": 300.0}
        tvl_map = {"a": 10_000_000.0, "b": 20_000_000.0, "c": 30_000_000.0}
        result = apply_capacity_caps(allocation, tvl_map)
        assert result == pytest.approx(allocation)

    def test_multiple_protocols_partial_cap(self):
        """Несколько протоколов — только нарушители обрезаются."""
        allocation = {
            "safe_proto": 1_000.0,    # ok (tiny vs TVL)
            "over_proto": 200_000.0,   # 2% of $5M → обрезается до $50K
        }
        tvl_map = {
            "safe_proto": 100_000_000.0,
            "over_proto": 5_000_000.0,
        }
        result = apply_capacity_caps(allocation, tvl_map)
        assert result["safe_proto"] == pytest.approx(1_000.0)
        assert result["over_proto"] == pytest.approx(50_000.0)

    def test_custom_max_pct(self):
        """Кастомный max_pct=0.05 (5%)."""
        allocation = {"proto": 4_000.0}
        tvl_map = {"proto": 100_000.0}  # max = $5K при 5%
        result = apply_capacity_caps(allocation, tvl_map, max_pct=0.05)
        assert result["proto"] == pytest.approx(4_000.0)  # 4% < 5%, не обрезается

    def test_returns_new_dict(self):
        """apply_capacity_caps возвращает новый dict, не модифицирует исходный."""
        allocation = {"proto": 999_999.0}
        tvl_map = {"proto": 5_000_000.0}
        result = apply_capacity_caps(allocation, tvl_map)
        assert result is not allocation
        assert allocation["proto"] == 999_999.0  # исходный не изменился

    def test_none_value_passthrough(self):
        """None значение в allocation → pass-through."""
        allocation = {"proto": None}
        tvl_map = {"proto": 5_000_000.0}
        result = apply_capacity_caps(allocation, tvl_map)
        assert result["proto"] is None


# ─── build_tvl_map() ─────────────────────────────────────────────────────────

class TestBuildTvlMap:

    def test_extracts_from_real_structure(self, sample_adapter_status):
        """Из реальной adapter_orchestrator_status структуры извлекает TVL."""
        tvl_map = build_tvl_map(sample_adapter_status)
        assert "aave_v3" in tvl_map
        assert tvl_map["aave_v3"] == pytest.approx(189_455_356.0)
        assert "compound_v3" in tvl_map
        assert "yearn_v3" in tvl_map
        assert "euler_v2" in tvl_map
        assert "maple" in tvl_map

    def test_excludes_zero_tvl(self, sample_adapter_status):
        """Протоколы с TVL=None (timeout) не включаются."""
        tvl_map = build_tvl_map(sample_adapter_status)
        assert "morpho_blue" not in tvl_map  # tvl_usd=None → исключён

    def test_empty_input(self):
        """Пустой dict → пустой map."""
        assert build_tvl_map({}) == {}

    def test_none_input(self):
        """None input → пустой map."""
        assert build_tvl_map(None) == {}

    def test_wrong_type_input(self):
        """Не dict → пустой map (без исключения)."""
        assert build_tvl_map("not a dict") == {}
        assert build_tvl_map(42) == {}

    def test_missing_adapters_key(self):
        """Нет ключа adapters → пустой map."""
        assert build_tvl_map({"other_key": []}) == {}

    def test_tvl_alias_field(self):
        """Поддерживает поле 'tvl' как алиас 'tvl_usd'."""
        status = {
            "adapters": [
                {"protocol": "proto_a", "tvl": 10_000_000.0},
            ]
        }
        tvl_map = build_tvl_map(status)
        assert "proto_a" in tvl_map
        assert tvl_map["proto_a"] == pytest.approx(10_000_000.0)

    def test_zero_tvl_excluded(self):
        """TVL=0 → не включается в map."""
        status = {
            "adapters": [
                {"protocol": "zero_tvl_proto", "tvl_usd": 0.0},
                {"protocol": "good_proto", "tvl_usd": 5_000_000.0},
            ]
        }
        tvl_map = build_tvl_map(status)
        assert "zero_tvl_proto" not in tvl_map
        assert "good_proto" in tvl_map


# ─── effective_max_pct() ─────────────────────────────────────────────────────

class TestEffectiveMaxPct:

    def test_t2_always_base_limit(self):
        """T2 всегда использует базовый лимит, даже при огромном TVL."""
        pct = effective_max_pct("yearn_v3", "T2", 5_000_000_000.0)
        assert pct == pytest.approx(MAX_CAPACITY_PCT)

    def test_t1_small_tvl_base_limit(self):
        """T1 с TVL < $1B → базовый лимит."""
        pct = effective_max_pct("aave_v3", "T1", 500_000_000.0)
        assert pct == pytest.approx(MAX_CAPACITY_PCT)

    def test_t1_high_tvl_extended_limit(self, huge_pool_tvl):
        """T1 с TVL ≥ $1B → расширенный лимит 3%."""
        pct = effective_max_pct("aave_v3", "T1", huge_pool_tvl)
        assert pct == pytest.approx(T1_HIGH_TVL_CAPACITY_PCT)

    def test_t1_exactly_at_threshold(self):
        """T1 с TVL ровно $1B → расширенный лимит."""
        pct = effective_max_pct("aave_v3", "T1", T1_HIGH_TVL_THRESHOLD_USD)
        assert pct == pytest.approx(T1_HIGH_TVL_CAPACITY_PCT)

    def test_t1_just_below_threshold(self):
        """T1 с TVL чуть ниже $1B → базовый лимит."""
        pct = effective_max_pct("aave_v3", "T1", T1_HIGH_TVL_THRESHOLD_USD - 1)
        assert pct == pytest.approx(MAX_CAPACITY_PCT)


# ─── Регрессия: policy.py не ломается ────────────────────────────────────────

class TestPolicyRegression:
    """Убеждаемся, что добавление capacity_check не ломает существующий код."""

    def test_risk_check_result_has_capacity_check(self):
        """RiskCheckResult имеет поле capacity_check."""
        from spa_core.risk.policy import RiskCheckResult
        r = RiskCheckResult(approved=True)
        assert hasattr(r, "capacity_check")
        assert isinstance(r.capacity_check, dict)

    def test_check_new_position_default_check_capacity_true(self):
        """check_new_position по умолчанию проверяет capacity (warn-only)."""
        from spa_core.risk.policy import PortfolioState, RiskPolicy

        policy = RiskPolicy()
        state = PortfolioState(total_capital_usd=100_000.0)
        # $40K в пуле с TVL $5M = 0.8% < 1% — ok, нет предупреждения
        result = policy.check_new_position(
            state,
            protocol_key="aave_v3",
            tier="T1",
            amount_usd=40_000.0,
            current_apy=3.5,
            tvl_usd=5_000_000.0,
        )
        # Не должно быть capacity warnings при 0.8%
        cap_warns = [w for w in result.warnings if "CAPACITY_WARN" in w]
        assert cap_warns == []

    def test_check_new_position_capacity_warning_on_violation(self):
        """check_new_position выдаёт CAPACITY_WARN при нарушении (не rejection).

        TVL должен быть ≥ $5M (TVL floor), иначе позиция блокируется по TVL floor
        раньше, чем capacity warn может сработать как предупреждение.
        $200K в пуле $10M TVL = 2% > 1% → capacity warn, но approved (warn-only ADR-009).
        """
        from spa_core.risk.policy import PortfolioState, RiskPolicy

        policy = RiskPolicy()
        # 1M капитал — достаточно кэша
        state = PortfolioState(total_capital_usd=1_000_000.0)
        # $200K в пуле $10M TVL = 2% > 1% (TVL floor: $10M ≥ $5M → passes)
        result = policy.check_new_position(
            state,
            protocol_key="mid_pool",
            tier="T1",
            amount_usd=200_000.0,
            current_apy=5.0,
            tvl_usd=10_000_000.0,
        )
        cap_warns = [w for w in result.warnings if "CAPACITY_WARN" in w]
        assert len(cap_warns) == 1, f"Expected 1 CAPACITY_WARN, got: {cap_warns}"
        assert result.approved is True, "Capacity warn-only — should not block"

    def test_check_new_position_capacity_false_skips_check(self):
        """check_capacity=False → capacity_check пустой."""
        from spa_core.risk.policy import PortfolioState, RiskPolicy

        policy = RiskPolicy()
        state = PortfolioState(total_capital_usd=100_000.0)
        result = policy.check_new_position(
            state,
            protocol_key="aave_v3",
            tier="T1",
            amount_usd=1_000.0,
            current_apy=3.5,
            tvl_usd=100_000_000.0,
            check_capacity=False,
        )
        assert result.capacity_check == {}

    def test_check_portfolio_health_default_no_crash(self):
        """check_portfolio_health без tvl_map → не падает, пропускает capacity."""
        from spa_core.risk.policy import PortfolioState, Position, RiskPolicy

        policy = RiskPolicy()
        state = PortfolioState(
            total_capital_usd=100_000.0,
            positions=[
                Position(
                    protocol_key="aave_v3",
                    tier="T1",
                    asset="USDC",
                    amount_usd=40_000.0,
                    apy_at_open=3.5,
                    current_apy=3.5,
                )
            ],
        )
        result = policy.check_portfolio_health(state)
        assert result.approved  # нет нарушений
        assert result.capacity_check == {}  # tvl_map не передан → пустой

    def test_check_portfolio_health_with_tvl_map(self):
        """check_portfolio_health с tvl_map → capacity_check заполнен."""
        from spa_core.risk.policy import PortfolioState, Position, RiskPolicy

        policy = RiskPolicy()
        state = PortfolioState(
            total_capital_usd=100_000.0,
            positions=[
                Position(
                    protocol_key="aave_v3",
                    tier="T1",
                    asset="USDC",
                    amount_usd=1_000.0,  # $1K из $189M TVL — безопасно
                    apy_at_open=3.5,
                    current_apy=3.5,
                )
            ],
        )
        tvl_map = {"aave_v3": 189_455_356.0}
        result = policy.check_portfolio_health(state, tvl_map=tvl_map)
        assert result.capacity_check != {}
        assert result.capacity_check["ok"] is True

    def test_check_portfolio_health_capacity_violation_is_warning_not_rejection(self):
        """Capacity violation → warning (not violation), approved остаётся True."""
        from spa_core.risk.policy import PortfolioState, Position, RiskPolicy

        policy = RiskPolicy()
        state = PortfolioState(
            total_capital_usd=100_000.0,
            positions=[
                Position(
                    protocol_key="tiny_pool",
                    tier="T2",
                    asset="USDC",
                    amount_usd=50_000.0,  # 50% TVL — нарушение capacity
                    apy_at_open=3.0,
                    current_apy=3.0,
                )
            ],
        )
        tvl_map = {"tiny_pool": 100_000.0}  # $100K TVL → max $1K
        result = policy.check_portfolio_health(state, tvl_map=tvl_map)
        # Capacity нарушение идёт в warnings, не violations (warn-only ADR-009)
        cap_warnings = [w for w in result.warnings if "CAPACITY_WARN" in w]
        assert len(cap_warnings) >= 1
        # Портфель одобрен (capacity не блокирует)
        # (approved зависит от других проверок — drawdown, concentration — которые ok)
        cap_violations = [v for v in result.violations if "CAPACITY" in v]
        assert cap_violations == []
