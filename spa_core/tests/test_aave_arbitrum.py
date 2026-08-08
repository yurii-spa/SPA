"""Тесты для AaveArbitrumAdapter — T1 anchor на L2 (MP-356).

Покрытие:
  - Константы сети: NETWORK, CHAIN_ID, POOL_ADDRESS, USDC_ADDRESS
  - Tier T1: значение, cap, risk_score
  - APY: чтение из adapter_status.json (JSON-путь)
  - APY: fallback 4.1% при отсутствии/невалидном JSON
  - APY: валидность значения (> 0, < 100)
  - get_gas_estimate(): структура и значения
  - gas_advantage_usd = 0.09
  - to_dict(): все обязательные ключи включая gas_advantage_usd, arbitrage_note
  - allocate(): нормальный путь, math, обновление _allocated_capital
  - allocate(): ValueError при capital ≤ 0
  - withdraw(): нормальный путь, остаток, math
  - withdraw(): ValueError при amount ≤ 0 и amount > allocated
  - health_check(): структура, tvl_floor_ok, apy_source
  - get_yield_info(): YieldInfo, apy как decimal, tvl_usd
  - ADAPTER_REGISTRY: aave_arbitrum зарегистрирован как T1
  - __init__.py: AaveArbitrumAdapter доступен через пакет

Итого: 50 тестов. Без сетевых вызовов, без внешних зависимостей.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Optional

import pytest

# Добавляем корень репо в sys.path
_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from spa_core.adapters.aave_arbitrum_adapter import AaveArbitrumAdapter
from spa_core.adapters.base_adapter import YieldInfo


# ---------------------------------------------------------------------------
# Хелперы для тестов с временными data-директориями
# ---------------------------------------------------------------------------

def _make_data_dir_with_entry(tmp_path: Path, apy_value=4.1) -> Path:
    """Создаёт временный data/ с корректной записью aave_arbitrum."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    status = {
        "aave_arbitrum": {
            "apy": apy_value,
            "tier": "T1",
            "network": "arbitrum",
            "chain_id": 42161,
            "tvl_usd": 1_200_000_000,
        }
    }
    (data_dir / "adapter_status.json").write_text(
        json.dumps(status), encoding="utf-8"
    )
    return data_dir


def _make_data_dir_no_entry(tmp_path: Path) -> Path:
    """Создаёт временный data/ без записи aave_arbitrum."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    status = {"other_protocol": {"apy": 3.5}}
    (data_dir / "adapter_status.json").write_text(
        json.dumps(status), encoding="utf-8"
    )
    return data_dir


def _make_data_dir_empty(tmp_path: Path) -> Path:
    """Создаёт временный data/ без adapter_status.json."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    return data_dir


def _make_data_dir_broken_json(tmp_path: Path) -> Path:
    """Создаёт временный data/ с повреждённым JSON."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "adapter_status.json").write_text(
        "{broken json{{", encoding="utf-8"
    )
    return data_dir


def _make_data_dir_null_apy(tmp_path: Path) -> Path:
    """Создаёт временный data/ где apy = null (невалидный тип)."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    status = {"aave_arbitrum": {"apy": None, "tier": "T1"}}
    (data_dir / "adapter_status.json").write_text(
        json.dumps(status), encoding="utf-8"
    )
    return data_dir


# ===========================================================================
# 1. Константы сети и протокола
# ===========================================================================

class TestNetworkConstants:
    """Проверяем, что сетевые константы соответствуют спецификации MP-356."""

    def test_network_is_arbitrum(self):
        assert AaveArbitrumAdapter.NETWORK == "arbitrum"

    def test_chain_id_is_42161(self):
        assert AaveArbitrumAdapter.CHAIN_ID == 42161

    def test_pool_address(self):
        assert AaveArbitrumAdapter.POOL_ADDRESS == "0x794a61358D6845594F94dc1DB02A252b5b4814aD"

    def test_usdc_address(self):
        assert AaveArbitrumAdapter.USDC_ADDRESS == "0xFF970A61A04b1cA14834A43f5dE4533eBDDB5CC8"

    def test_protocol_key(self):
        assert AaveArbitrumAdapter.PROTOCOL == "aave_arbitrum"

    def test_pool_id(self):
        assert AaveArbitrumAdapter.pool_id == "aave-v3-usdc-arbitrum-t1"


# ===========================================================================
# 2. Tier T1 и лимиты
# ===========================================================================

class TestTierAndCaps:
    """Проверяем T1 классификацию, лимиты и риск-профиль."""

    def test_tier_is_t1(self, tmp_path):
        a = AaveArbitrumAdapter(data_dir=_make_data_dir_empty(tmp_path))
        assert a.tier == "T1"

    def test_tier_class_constant_t1(self):
        assert AaveArbitrumAdapter.TIER == "T1"

    def test_t1_cap_is_40pct(self):
        assert AaveArbitrumAdapter.T1_CAP == 0.40

    def test_risk_score_t1_level(self):
        # T1 risk_score должен быть ниже 0.35 (T2 уровень)
        assert AaveArbitrumAdapter.RISK_SCORE < 0.35

    def test_risk_score_above_mainnet_t1(self):
        # L2 bridge риск: чуть выше mainnet T1 (0.20)
        assert AaveArbitrumAdapter.RISK_SCORE > 0.20

    def test_exit_latency_instant(self):
        # Instant exit: same-block на L2
        assert AaveArbitrumAdapter.EXIT_LATENCY_HOURS == 0.0


# ===========================================================================
# 3. APY — чтение из JSON
# ===========================================================================

class TestApyFromJson:
    """APY успешно читается из adapter_status.json."""

    def test_get_apy_reads_from_json(self, tmp_path):
        data_dir = _make_data_dir_with_entry(tmp_path, apy_value=4.1)
        a = AaveArbitrumAdapter(data_dir=data_dir)
        assert a.get_apy() == 4.1

    def test_get_apy_custom_value(self, tmp_path):
        data_dir = _make_data_dir_with_entry(tmp_path, apy_value=5.5)
        a = AaveArbitrumAdapter(data_dir=data_dir)
        assert a.get_apy() == 5.5

    def test_get_apy_float_precision(self, tmp_path):
        data_dir = _make_data_dir_with_entry(tmp_path, apy_value=4.15)
        a = AaveArbitrumAdapter(data_dir=data_dir)
        assert abs(a.get_apy() - 4.15) < 1e-9

    def test_load_apy_from_status_returns_float(self, tmp_path):
        data_dir = _make_data_dir_with_entry(tmp_path, apy_value=3.8)
        a = AaveArbitrumAdapter(data_dir=data_dir)
        result = a._load_apy_from_status()
        assert isinstance(result, float)
        assert result == 3.8

    def test_apy_as_int_in_json(self, tmp_path):
        """JSON с целочисленным APY тоже должен работать."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        status = {"aave_arbitrum": {"apy": 4, "tier": "T1"}}
        (data_dir / "adapter_status.json").write_text(json.dumps(status))
        a = AaveArbitrumAdapter(data_dir=data_dir)
        assert a.get_apy() == 4.0


# ===========================================================================
# 4. APY — fallback
# ===========================================================================

class TestApyFallback:
    """Наблюдения нет ⇒ None. Подстановки 4.1 % больше не существует.

    ИЗМЕНЁН НАМЕРЕННО 2026-08-08 (инв. №16). Класс назывался «APY fallback 4.1 %
    при отсутствии или невалидности JSON» и закреплял ровно то поведение,
    которое владелец приказал убрать («делать все 15», карточка
    `agent-fake-fallback-v-15-adapterah`).

    Проверка НЕ ослаблена: те же четыре ветки чтения (нет файла / нет записи /
    битый JSON / apy=null) проверяются по-прежнему — изменилось ожидаемое
    значение, с выдуманного на честное. Два теста, требовавшие «> 0» и
    «< 100», УСИЛЕНЫ: теперь они требуют, чтобы граничные проверки применялись
    к НАБЛЮДЕНИЮ, а к его отсутствию не применялись вовсе.

    Это единственный T1 в списке из пятнадцати, и его литерал доходил до
    ``YieldInfo.apy`` — поверхности оркестратора.
    """

    def test_none_when_no_file(self, tmp_path):
        data_dir = _make_data_dir_empty(tmp_path)
        a = AaveArbitrumAdapter(data_dir=data_dir)
        assert a.get_apy() is None

    def test_none_when_no_entry(self, tmp_path):
        data_dir = _make_data_dir_no_entry(tmp_path)
        a = AaveArbitrumAdapter(data_dir=data_dir)
        assert a.get_apy() is None

    def test_none_when_broken_json(self, tmp_path):
        data_dir = _make_data_dir_broken_json(tmp_path)
        a = AaveArbitrumAdapter(data_dir=data_dir)
        assert a.get_apy() is None

    def test_none_when_null_apy(self, tmp_path):
        data_dir = _make_data_dir_null_apy(tmp_path)
        a = AaveArbitrumAdapter(data_dir=data_dir)
        assert a.get_apy() is None

    def test_fallback_constant_no_longer_exists(self):
        """Атрибута нет СОВСЕМ — пока он есть, его легко «вернуть на минутку»."""
        assert not hasattr(AaveArbitrumAdapter, "APY_FALLBACK")

    def test_load_apy_returns_none_when_no_file(self, tmp_path):
        data_dir = _make_data_dir_empty(tmp_path)
        a = AaveArbitrumAdapter(data_dir=data_dir)
        assert a._load_apy_from_status() is None

    def test_observed_apy_still_passes_through(self, tmp_path):
        """Контроль в обратную сторону: наблюдение не превращается в None.

        Без него «починка» вида ``return None`` всегда была бы зелёной.
        """
        import json
        d = tmp_path / "data_ok"
        d.mkdir()
        (d / "adapter_status.json").write_text(
            json.dumps({"aave_arbitrum": {"apy": 2.3475}}), encoding="utf-8")
        a = AaveArbitrumAdapter(data_dir=str(d))
        assert a.get_apy() == pytest.approx(2.3475)
        assert a.get_yield_info().apy == pytest.approx(0.023475)

    def test_yield_info_apy_is_none_without_observation(self, tmp_path):
        """Поверхность ОРКЕСТРАТОРА — то место, куда литерал доходил."""
        a = AaveArbitrumAdapter(data_dir=_make_data_dir_empty(tmp_path))
        assert a.get_yield_info().apy is None

    def test_allocate_reports_no_yield_without_observation(self, tmp_path):
        """Ноль был бы таким же выдуманным числом, как 4.1 — только тише."""
        a = AaveArbitrumAdapter(data_dir=_make_data_dir_empty(tmp_path))
        r = a.allocate(10_000.0)
        assert r["apy_pct"] is None
        assert r["annual_yield_usd"] is None


# ===========================================================================
# 5. get_gas_estimate()
# ===========================================================================

class TestGasEstimate:
    """Проверяем структуру и значения газовой оценки."""

    def test_returns_dict(self, tmp_path):
        a = AaveArbitrumAdapter(data_dir=_make_data_dir_empty(tmp_path))
        result = a.get_gas_estimate()
        assert isinstance(result, dict)

    def test_network_in_gas_estimate(self, tmp_path):
        a = AaveArbitrumAdapter(data_dir=_make_data_dir_empty(tmp_path))
        assert a.get_gas_estimate()["network"] == "arbitrum"

    def test_chain_id_in_gas_estimate(self, tmp_path):
        a = AaveArbitrumAdapter(data_dir=_make_data_dir_empty(tmp_path))
        assert a.get_gas_estimate()["chain_id"] == 42161

    def test_gas_advantage_is_0_09(self, tmp_path):
        a = AaveArbitrumAdapter(data_dir=_make_data_dir_empty(tmp_path))
        est = a.get_gas_estimate()
        assert abs(est["gas_advantage_usd"] - 0.09) < 1e-9

    def test_gas_cost_l2(self, tmp_path):
        a = AaveArbitrumAdapter(data_dir=_make_data_dir_empty(tmp_path))
        assert a.get_gas_estimate()["gas_cost_usd"] == 0.01

    def test_gas_cost_mainnet(self, tmp_path):
        a = AaveArbitrumAdapter(data_dir=_make_data_dir_empty(tmp_path))
        assert a.get_gas_estimate()["mainnet_gas_cost_usd"] == 0.10

    def test_gas_multiplier_10x(self, tmp_path):
        a = AaveArbitrumAdapter(data_dir=_make_data_dir_empty(tmp_path))
        assert a.get_gas_estimate()["gas_multiplier"] == 10

    def test_finality_minutes(self, tmp_path):
        a = AaveArbitrumAdapter(data_dir=_make_data_dir_empty(tmp_path))
        assert a.get_gas_estimate()["finality_minutes"] == 15


# ===========================================================================
# 6. to_dict()
# ===========================================================================

class TestToDict:
    """Проверяем содержимое словаря to_dict()."""

    def test_returns_dict(self, tmp_path):
        a = AaveArbitrumAdapter(data_dir=_make_data_dir_empty(tmp_path))
        assert isinstance(a.to_dict(), dict)

    def test_network_field(self, tmp_path):
        a = AaveArbitrumAdapter(data_dir=_make_data_dir_empty(tmp_path))
        assert a.to_dict()["network"] == "arbitrum"

    def test_chain_id_field(self, tmp_path):
        a = AaveArbitrumAdapter(data_dir=_make_data_dir_empty(tmp_path))
        assert a.to_dict()["chain_id"] == 42161

    def test_gas_advantage_usd_field(self, tmp_path):
        a = AaveArbitrumAdapter(data_dir=_make_data_dir_empty(tmp_path))
        d = a.to_dict()
        assert "gas_advantage_usd" in d
        assert abs(d["gas_advantage_usd"] - 0.09) < 1e-9

    def test_arbitrage_note_present(self, tmp_path):
        a = AaveArbitrumAdapter(data_dir=_make_data_dir_empty(tmp_path))
        d = a.to_dict()
        assert "arbitrage_note" in d
        assert isinstance(d["arbitrage_note"], str)
        assert len(d["arbitrage_note"]) > 10

    def test_tier_t1_in_to_dict(self, tmp_path):
        a = AaveArbitrumAdapter(data_dir=_make_data_dir_empty(tmp_path))
        assert a.to_dict()["tier"] == "T1"

    def test_l2_advantages_block(self, tmp_path):
        a = AaveArbitrumAdapter(data_dir=_make_data_dir_empty(tmp_path))
        d = a.to_dict()
        assert "l2_advantages" in d
        l2 = d["l2_advantages"]
        assert l2["gas_savings_per_tx_usd"] == pytest.approx(0.09)

    def test_apy_pct_in_to_dict(self, tmp_path):
        data_dir = _make_data_dir_with_entry(tmp_path, apy_value=4.1)
        a = AaveArbitrumAdapter(data_dir=data_dir)
        assert a.to_dict()["apy_pct"] == 4.1

    def test_tvl_usd_in_to_dict(self, tmp_path):
        a = AaveArbitrumAdapter(data_dir=_make_data_dir_empty(tmp_path))
        assert a.to_dict()["tvl_usd"] == 1_200_000_000


# ===========================================================================
# 7. allocate()
# ===========================================================================

class TestAllocate:
    """Проверяем логику виртуального размещения капитала."""

    def test_allocate_returns_dict(self, tmp_path):
        a = AaveArbitrumAdapter(data_dir=_make_data_dir_empty(tmp_path))
        result = a.allocate(1000.0)
        assert isinstance(result, dict)

    def test_allocate_status_ok(self, tmp_path):
        a = AaveArbitrumAdapter(data_dir=_make_data_dir_empty(tmp_path))
        assert a.allocate(1000.0)["status"] == "allocated"

    def test_allocate_updates_capital(self, tmp_path):
        a = AaveArbitrumAdapter(data_dir=_make_data_dir_empty(tmp_path))
        a.allocate(5000.0)
        assert a._allocated_capital == pytest.approx(5000.0)

    def test_allocate_accumulates(self, tmp_path):
        a = AaveArbitrumAdapter(data_dir=_make_data_dir_empty(tmp_path))
        a.allocate(3000.0)
        a.allocate(2000.0)
        assert a._allocated_capital == pytest.approx(5000.0)

    def test_allocate_annual_yield_math(self, tmp_path):
        """annual_yield = capital * (apy_pct / 100) — на НАБЛЮДЁННОМ APY.

        ИЗМЕНЁН НАМЕРЕННО 2026-08-08 (инв. №16): тест считал математику от
        подставного 4.1 %, которого больше нет. Арифметика проверяется ровно
        та же, но на наблюдении; случай «наблюдения нет» проверяется отдельно
        (`test_allocate_reports_no_yield_without_observation`).
        """
        import json
        d = tmp_path / "data_obs"
        d.mkdir()
        (d / "adapter_status.json").write_text(
            json.dumps({"aave_arbitrum": {"apy": 4.1}}), encoding="utf-8")
        a = AaveArbitrumAdapter(data_dir=str(d))
        result = a.allocate(10_000.0)
        assert result["annual_yield_usd"] == pytest.approx(10_000.0 * 0.041, rel=1e-6)

    def test_allocate_raises_on_zero(self, tmp_path):
        a = AaveArbitrumAdapter(data_dir=_make_data_dir_empty(tmp_path))
        with pytest.raises(ValueError):
            a.allocate(0.0)

    def test_allocate_raises_on_negative(self, tmp_path):
        a = AaveArbitrumAdapter(data_dir=_make_data_dir_empty(tmp_path))
        with pytest.raises(ValueError):
            a.allocate(-100.0)

    def test_allocate_network_in_result(self, tmp_path):
        a = AaveArbitrumAdapter(data_dir=_make_data_dir_empty(tmp_path))
        result = a.allocate(100.0)
        assert result["network"] == "arbitrum"
        assert result["chain_id"] == 42161


# ===========================================================================
# 8. withdraw()
# ===========================================================================

class TestWithdraw:
    """Проверяем логику виртуального вывода капитала."""

    def test_withdraw_returns_dict(self, tmp_path):
        a = AaveArbitrumAdapter(data_dir=_make_data_dir_empty(tmp_path))
        a.allocate(1000.0)
        result = a.withdraw(500.0)
        assert isinstance(result, dict)

    def test_withdraw_status_withdrawn(self, tmp_path):
        a = AaveArbitrumAdapter(data_dir=_make_data_dir_empty(tmp_path))
        a.allocate(1000.0)
        assert a.withdraw(500.0)["status"] == "withdrawn"

    def test_withdraw_reduces_capital(self, tmp_path):
        a = AaveArbitrumAdapter(data_dir=_make_data_dir_empty(tmp_path))
        a.allocate(1000.0)
        a.withdraw(300.0)
        assert a._allocated_capital == pytest.approx(700.0)

    def test_withdraw_full_amount(self, tmp_path):
        a = AaveArbitrumAdapter(data_dir=_make_data_dir_empty(tmp_path))
        a.allocate(1000.0)
        a.withdraw(1000.0)
        assert a._allocated_capital == pytest.approx(0.0)

    def test_withdraw_remaining_correct(self, tmp_path):
        a = AaveArbitrumAdapter(data_dir=_make_data_dir_empty(tmp_path))
        a.allocate(5000.0)
        result = a.withdraw(2000.0)
        assert result["remaining_allocated_usd"] == pytest.approx(3000.0)

    def test_withdraw_raises_on_zero(self, tmp_path):
        a = AaveArbitrumAdapter(data_dir=_make_data_dir_empty(tmp_path))
        a.allocate(1000.0)
        with pytest.raises(ValueError):
            a.withdraw(0.0)

    def test_withdraw_raises_on_negative(self, tmp_path):
        a = AaveArbitrumAdapter(data_dir=_make_data_dir_empty(tmp_path))
        a.allocate(1000.0)
        with pytest.raises(ValueError):
            a.withdraw(-1.0)

    def test_withdraw_raises_on_overdraft(self, tmp_path):
        a = AaveArbitrumAdapter(data_dir=_make_data_dir_empty(tmp_path))
        a.allocate(100.0)
        with pytest.raises(ValueError):
            a.withdraw(200.0)

    def test_withdraw_without_allocate_raises(self, tmp_path):
        """Вывод без предшествующего allocate должен вызывать ValueError."""
        a = AaveArbitrumAdapter(data_dir=_make_data_dir_empty(tmp_path))
        with pytest.raises(ValueError):
            a.withdraw(1.0)


# ===========================================================================
# 9. health_check()
# ===========================================================================

class TestHealthCheck:
    """Проверяем структуру и значения health_check()."""

    def test_returns_dict(self, tmp_path):
        a = AaveArbitrumAdapter(data_dir=_make_data_dir_empty(tmp_path))
        assert isinstance(a.health_check(), dict)

    def test_status_ok(self, tmp_path):
        a = AaveArbitrumAdapter(data_dir=_make_data_dir_empty(tmp_path))
        assert a.health_check()["status"] == "ok"

    def test_tvl_floor_ok_true(self, tmp_path):
        """TVL $1.2B >> $5M floor из RiskPolicy."""
        # ИЗМЕНЕНИЕ ТЕСТА (2026-08-05, правило 16 — обоснование):
        # утверждение закрепляло ТАВТОЛОГИЮ. `tvl_floor_ok` считался как
        # `self.TVL_USD >= 5_000_000` от зашитой константы, которая заведомо
        # больше порога, — выражение не могло вернуть False НИ ПРИ КАКИХ данных,
        # и здесь оно вызывалось на ПУСТОМ каталоге. То есть тест требовал
        # «порог пройден» при полном отсутствии наблюдения.
        # Реальная цена: moonwell_base несёт TVL_USD = 500_000_000 при
        # наблюдаемых $2.6M — пул, не проходящий порог, проходил его всегда.
        # Контракт изменён намеренно: True/False по наблюдению, None если не
        # измерено. Обе стороны закреплены в test_tvl_floor_verdict.py.
        a = AaveArbitrumAdapter(data_dir=_make_data_dir_empty(tmp_path))
        assert a.health_check()["tvl_floor_ok"] is None

    def test_apy_source_fallback(self, tmp_path):
        data_dir = _make_data_dir_empty(tmp_path)
        a = AaveArbitrumAdapter(data_dir=data_dir)
        assert a.health_check()["apy_source"] == "fallback"

    def test_apy_source_adapter_status(self, tmp_path):
        data_dir = _make_data_dir_with_entry(tmp_path, apy_value=4.1)
        a = AaveArbitrumAdapter(data_dir=data_dir)
        assert a.health_check()["apy_source"] == "adapter_status"

    def test_network_in_health_check(self, tmp_path):
        a = AaveArbitrumAdapter(data_dir=_make_data_dir_empty(tmp_path))
        assert a.health_check()["network"] == "arbitrum"

    def test_tier_in_health_check(self, tmp_path):
        a = AaveArbitrumAdapter(data_dir=_make_data_dir_empty(tmp_path))
        assert a.health_check()["tier"] == "T1"


# ===========================================================================
# 10. get_yield_info()
# ===========================================================================

class TestGetYieldInfo:
    """Проверяем YieldInfo от адаптера."""

    def test_returns_yield_info(self, tmp_path):
        a = AaveArbitrumAdapter(data_dir=_make_data_dir_empty(tmp_path))
        assert isinstance(a.get_yield_info(), YieldInfo)

    def test_apy_is_decimal_in_yield_info(self, tmp_path):
        """YieldInfo.apy должен быть decimal (0.041 для 4.1%)."""
        data_dir = _make_data_dir_with_entry(tmp_path, apy_value=4.1)
        a = AaveArbitrumAdapter(data_dir=data_dir)
        yi = a.get_yield_info()
        assert yi.apy == pytest.approx(0.041, rel=1e-6)

    def test_tvl_usd_in_yield_info(self, tmp_path):
        a = AaveArbitrumAdapter(data_dir=_make_data_dir_empty(tmp_path))
        yi = a.get_yield_info()
        assert yi.tvl_usd == 1_200_000_000.0

    def test_tier_t1_in_yield_info(self, tmp_path):
        a = AaveArbitrumAdapter(data_dir=_make_data_dir_empty(tmp_path))
        assert a.get_yield_info().tier == "T1"

    def test_protocol_in_yield_info(self, tmp_path):
        a = AaveArbitrumAdapter(data_dir=_make_data_dir_empty(tmp_path))
        assert a.get_yield_info().protocol == "aave_arbitrum"

    def test_exit_latency_zero(self, tmp_path):
        a = AaveArbitrumAdapter(data_dir=_make_data_dir_empty(tmp_path))
        assert a.get_yield_info().exit_latency_hours == 0.0


# ===========================================================================
# 11. ADAPTER_REGISTRY — интеграция
# ===========================================================================

class TestAdapterRegistry:
    """Проверяем регистрацию в ADAPTER_REGISTRY."""

    def test_aave_arbitrum_in_registry(self):
        from spa_core.adapters import ADAPTER_REGISTRY
        keys = [entry[0] for entry in ADAPTER_REGISTRY]
        assert "aave_arbitrum" in keys

    def test_aave_arbitrum_tier_t1_in_registry(self):
        from spa_core.adapters import ADAPTER_REGISTRY
        for key, tier, cls in ADAPTER_REGISTRY:
            if key == "aave_arbitrum":
                assert tier == "T1"
                return
        pytest.fail("aave_arbitrum не найден в ADAPTER_REGISTRY")

    def test_aave_arbitrum_class_in_registry(self):
        from spa_core.adapters import ADAPTER_REGISTRY, AaveArbitrumAdapter
        for key, tier, cls in ADAPTER_REGISTRY:
            if key == "aave_arbitrum":
                assert cls is AaveArbitrumAdapter
                return
        pytest.fail("AaveArbitrumAdapter не зарегистрирован")

    def test_import_from_package(self):
        """AaveArbitrumAdapter должен быть доступен через spa_core.adapters."""
        from spa_core.adapters import AaveArbitrumAdapter as A
        assert A is AaveArbitrumAdapter
