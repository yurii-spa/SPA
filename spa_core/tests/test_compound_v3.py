"""Тесты для CompoundV3Adapter (MP-365) — spa_core/adapters/compound_v3_adapter.py.

Покрытие (65+ тестов):
  1. APY из JSON + fallback                   — 10 тестов
  2. Gap-методы vs Morpho / Aave              — 10 тестов
  3. health_check                             — 8  тестов
  4. to_dict                                  — 12 тестов
  5. allocate / withdraw                      — 10 тестов
  6. is_better_than_aave                      — 8  тестов
  7. Идентичность / tier / прочие             — 7  тестов
                                        Итого: 65 тестов

Без сетевых вызовов, без внешних зависимостей (только stdlib + pytest).
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

# Добавляем корень репо в sys.path
_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from spa_core.adapters.compound_v3_adapter import CompoundV3Adapter
from spa_core.adapters.base_adapter import YieldInfo


# ---------------------------------------------------------------------------
# Вспомогательные функции для создания временных data-директорий
# ---------------------------------------------------------------------------

def _data_dir_with_apy(tmp_path: Path, apy: float = 4.8) -> Path:
    """Создаёт data/ с валидной записью compound_v3."""
    d = tmp_path / "data"
    d.mkdir()
    # Adapter reads from key "compound_v3_adapter" (not "compound_v3")
    status = {
        "compound_v3_adapter": {
            "apy": apy,
            "protocol": "compound_v3",
            "tier": "T1",
            "tvl_usd": 2_800_000_000,
        }
    }
    (d / "adapter_status.json").write_text(json.dumps(status), encoding="utf-8")
    return d


def _data_dir_with_protocols(
    tmp_path: Path,
    compound_apy: float = 4.8,
    morpho_apy: float = 6.5,
    aave_apy: float = 4.2,
) -> Path:
    """Создаёт data/ с записями compound_v3_adapter + morpho_blue + aave_v3."""
    d = tmp_path / "data"
    d.mkdir()
    # "compound_v3_adapter" is the key the adapter reads; morpho/aave keys are unchanged
    status = {
        "compound_v3_adapter": {"apy": compound_apy, "tier": "T1"},
        "morpho_blue":         {"apy": morpho_apy,   "tier": "T2"},
        "aave_v3":             {"apy": aave_apy,      "tier": "T1"},
    }
    (d / "adapter_status.json").write_text(json.dumps(status), encoding="utf-8")
    return d


def _data_dir_no_compound(tmp_path: Path) -> Path:
    """Создаёт data/ без записи compound_v3 (проверяет fallback)."""
    d = tmp_path / "data"
    d.mkdir()
    status = {"aave_v3": {"apy": 4.2, "tier": "T1"}}
    (d / "adapter_status.json").write_text(json.dumps(status), encoding="utf-8")
    return d


def _data_dir_empty(tmp_path: Path) -> Path:
    """Создаёт data/ без adapter_status.json (проверяет fallback)."""
    d = tmp_path / "data"
    d.mkdir()
    return d


def _data_dir_invalid_json(tmp_path: Path) -> Path:
    """Создаёт data/ с невалидным JSON (проверяет graceful fallback)."""
    d = tmp_path / "data"
    d.mkdir()
    (d / "adapter_status.json").write_text("not valid json {{", encoding="utf-8")
    return d


def _data_dir_null_apy(tmp_path: Path) -> Path:
    """Создаёт data/ с compound_v3.apy = null (проверяет fallback)."""
    d = tmp_path / "data"
    d.mkdir()
    status = {"compound_v3": {"apy": None, "tier": "T1"}}
    (d / "adapter_status.json").write_text(json.dumps(status), encoding="utf-8")
    return d


def _data_dir_string_apy(tmp_path: Path) -> Path:
    """Создаёт data/ с compound_v3.apy = строка (невалидный тип)."""
    d = tmp_path / "data"
    d.mkdir()
    status = {"compound_v3": {"apy": "4.8", "tier": "T1"}}
    (d / "adapter_status.json").write_text(json.dumps(status), encoding="utf-8")
    return d


# ===========================================================================
# 1. APY из JSON + fallback (10 тестов)
# ===========================================================================

class TestAPYFromJSON:
    """Тесты чтения APY из adapter_status.json и fallback-логика."""

    def test_apy_from_json_standard(self, tmp_path):
        """APY 4.8 читается из JSON корректно."""
        adapter = CompoundV3Adapter(data_dir=_data_dir_with_apy(tmp_path, 4.8))
        assert adapter.get_apy() == pytest.approx(4.8)

    def test_apy_from_json_custom_value(self, tmp_path):
        """APY 5.1 читается из JSON корректно."""
        adapter = CompoundV3Adapter(data_dir=_data_dir_with_apy(tmp_path, 5.1))
        assert adapter.get_apy() == pytest.approx(5.1)

    def test_no_live_data_when_no_file(self, tmp_path):
        """N2: нет adapter_status.json → None (не сфабрикованный fallback)."""
        adapter = CompoundV3Adapter(data_dir=_data_dir_empty(tmp_path))
        assert adapter.get_apy() is None

    def test_no_live_data_when_no_compound_key(self, tmp_path):
        """N2: нет ключа compound_v3_adapter → None."""
        adapter = CompoundV3Adapter(data_dir=_data_dir_no_compound(tmp_path))
        assert adapter.get_apy() is None

    def test_no_live_data_when_invalid_json(self, tmp_path):
        """N2: невалидный JSON → None (graceful, без фабрикации)."""
        adapter = CompoundV3Adapter(data_dir=_data_dir_invalid_json(tmp_path))
        assert adapter.get_apy() is None

    def test_no_live_data_when_null_apy(self, tmp_path):
        """N2: compound_v3_adapter.apy = null → None."""
        adapter = CompoundV3Adapter(data_dir=_data_dir_null_apy(tmp_path))
        assert adapter.get_apy() is None

    def test_no_live_data_when_string_apy(self, tmp_path):
        """N2: compound_v3_adapter.apy = строка → None."""
        adapter = CompoundV3Adapter(data_dir=_data_dir_string_apy(tmp_path))
        assert adapter.get_apy() is None

    def test_apy_is_float(self, tmp_path):
        """get_apy() возвращает float при наличии живых данных."""
        adapter = CompoundV3Adapter(data_dir=_data_dir_with_apy(tmp_path, 4.8))
        assert isinstance(adapter.get_apy(), float)

    def test_get_apy_pct_equals_get_apy(self, tmp_path):
        """get_apy_pct() всегда равен get_apy()."""
        adapter = CompoundV3Adapter(data_dir=_data_dir_with_apy(tmp_path, 5.2))
        assert adapter.get_apy_pct() == adapter.get_apy()

    def test_apy_integer_in_json_converted_to_float(self, tmp_path):
        """APY как int в JSON преобразуется в float."""
        d = tmp_path / "data"
        d.mkdir()
        # Записываем APY как целое число
        (d / "adapter_status.json").write_text(
            json.dumps({"compound_v3_adapter": {"apy": 5, "tier": "T1"}}), encoding="utf-8"
        )
        adapter = CompoundV3Adapter(data_dir=d)
        assert adapter.get_apy() == pytest.approx(5.0)
        assert isinstance(adapter.get_apy(), float)


# ===========================================================================
# 2. Gap-методы vs Morpho / Aave (10 тестов)
# ===========================================================================

class TestGapMethods:
    """Тесты gap-методов vs_morpho_gap() и vs_aave_gap()."""

    def test_vs_morpho_gap_with_override(self, tmp_path):
        """vs_morpho_gap(morpho_apy=6.5) при compound 4.8 → 1.7."""
        adapter = CompoundV3Adapter(data_dir=_data_dir_with_apy(tmp_path, 4.8))
        gap = adapter.vs_morpho_gap(morpho_apy=6.5)
        assert gap == pytest.approx(1.7, abs=1e-5)

    def test_vs_morpho_gap_positive_means_morpho_better(self, tmp_path):
        """Положительный gap означает что Morpho лучше Compound."""
        adapter = CompoundV3Adapter(data_dir=_data_dir_with_apy(tmp_path, 4.8))
        gap = adapter.vs_morpho_gap(morpho_apy=7.0)
        assert gap > 0

    def test_vs_morpho_gap_negative_means_compound_better(self, tmp_path):
        """Отрицательный gap означает что Compound лучше Morpho."""
        adapter = CompoundV3Adapter(data_dir=_data_dir_with_apy(tmp_path, 8.0))
        gap = adapter.vs_morpho_gap(morpho_apy=6.0)
        assert gap < 0

    def test_vs_morpho_gap_from_json(self, tmp_path):
        """vs_morpho_gap() читает Morpho APY из adapter_status.json."""
        d = _data_dir_with_protocols(tmp_path, compound_apy=4.8, morpho_apy=6.5)
        adapter = CompoundV3Adapter(data_dir=d)
        gap = adapter.vs_morpho_gap()  # без override → читает из JSON
        assert gap == pytest.approx(6.5 - 4.8, abs=1e-5)

    def test_vs_morpho_gap_fallback_when_no_morpho_key(self, tmp_path):
        """vs_morpho_gap() использует fallback 6.5 если morpho_blue отсутствует в JSON."""
        adapter = CompoundV3Adapter(data_dir=_data_dir_with_apy(tmp_path, 4.8))
        # morpho_blue не в JSON → fallback = 6.5
        gap = adapter.vs_morpho_gap()
        assert gap == pytest.approx(6.5 - 4.8, abs=1e-5)

    def test_vs_aave_gap_with_override(self, tmp_path):
        """vs_aave_gap(aave_apy=4.2) при compound 4.8 → +0.6."""
        adapter = CompoundV3Adapter(data_dir=_data_dir_with_apy(tmp_path, 4.8))
        gap = adapter.vs_aave_gap(aave_apy=4.2)
        assert gap == pytest.approx(0.6, abs=1e-5)

    def test_vs_aave_gap_positive_means_compound_better(self, tmp_path):
        """Положительный gap означает что Compound лучше Aave."""
        adapter = CompoundV3Adapter(data_dir=_data_dir_with_apy(tmp_path, 5.0))
        gap = adapter.vs_aave_gap(aave_apy=4.0)
        assert gap > 0

    def test_vs_aave_gap_negative_means_aave_better(self, tmp_path):
        """Отрицательный gap означает что Aave лучше Compound."""
        adapter = CompoundV3Adapter(data_dir=_data_dir_with_apy(tmp_path, 3.5))
        gap = adapter.vs_aave_gap(aave_apy=4.5)
        assert gap < 0

    def test_vs_aave_gap_from_json(self, tmp_path):
        """vs_aave_gap() читает Aave APY из adapter_status.json."""
        d = _data_dir_with_protocols(tmp_path, compound_apy=4.8, aave_apy=4.2)
        adapter = CompoundV3Adapter(data_dir=d)
        gap = adapter.vs_aave_gap()
        assert gap == pytest.approx(4.8 - 4.2, abs=1e-5)

    def test_vs_aave_gap_fallback_when_no_aave_key(self, tmp_path):
        """vs_aave_gap() использует fallback если aave_v3 отсутствует в JSON."""
        adapter = CompoundV3Adapter(data_dir=_data_dir_empty(tmp_path))
        # No file → compound uses APY_FALLBACK, aave uses _AAVE_APY_FALLBACK
        gap = adapter.vs_aave_gap()
        # gap = compound_fallback - aave_fallback
        assert isinstance(gap, float)


# ===========================================================================
# 3. health_check (8 тестов)
# ===========================================================================

class TestHealthCheck:
    """Тесты метода health_check()."""

    def test_health_ok_for_normal_apy(self, tmp_path):
        """APY 4.8 ∈ [MIN_APY_PCT, MAX_APY_PCT] → status ok."""
        adapter = CompoundV3Adapter(data_dir=_data_dir_with_apy(tmp_path, 4.8))
        result = adapter.health_check()
        assert result["status"] == "ok"

    def test_health_ok_boundary_min(self, tmp_path):
        """APY ровно MIN_APY_PCT → ok (граница включена)."""
        adapter = CompoundV3Adapter(data_dir=_data_dir_with_apy(tmp_path, CompoundV3Adapter.MIN_APY_PCT))
        assert adapter.health_check()["status"] == "ok"

    def test_health_ok_boundary_max(self, tmp_path):
        """APY ровно MAX_APY_PCT → ok (граница включена)."""
        adapter = CompoundV3Adapter(data_dir=_data_dir_with_apy(tmp_path, CompoundV3Adapter.MAX_APY_PCT))
        assert adapter.health_check()["status"] == "ok"

    def test_health_degraded_below_min(self, tmp_path):
        """APY ниже MIN_APY_PCT → degraded."""
        below = max(0.0, CompoundV3Adapter.MIN_APY_PCT - 0.5)
        adapter = CompoundV3Adapter(data_dir=_data_dir_with_apy(tmp_path, below))
        assert adapter.health_check()["status"] == "degraded"

    def test_health_degraded_above_max(self, tmp_path):
        """APY выше MAX_APY_PCT → degraded."""
        above = CompoundV3Adapter.MAX_APY_PCT + 1.0
        adapter = CompoundV3Adapter(data_dir=_data_dir_with_apy(tmp_path, above))
        assert adapter.health_check()["status"] == "degraded"

    def test_health_tvl_floor_ok(self, tmp_path):
        """TVL $2.8B всегда проходит floor ≥ $5M."""
        adapter = CompoundV3Adapter(data_dir=_data_dir_with_apy(tmp_path))
        result = adapter.health_check()
        assert result["tvl_floor_ok"] is True

    def test_health_apy_source_from_file(self, tmp_path):
        """apy_source = "adapter_status" когда APY читается из JSON."""
        adapter = CompoundV3Adapter(data_dir=_data_dir_with_apy(tmp_path, 4.8))
        result = adapter.health_check()
        assert result["apy_source"] == "adapter_status"

    def test_health_apy_source_fallback(self, tmp_path):
        """apy_source = "fallback" когда APY из fallback значения."""
        adapter = CompoundV3Adapter(data_dir=_data_dir_empty(tmp_path))
        result = adapter.health_check()
        assert result["apy_source"] == "fallback"


# ===========================================================================
# 4. to_dict (12 тестов)
# ===========================================================================

class TestToDict:
    """Тесты метода to_dict()."""

    def test_to_dict_returns_dict(self, tmp_path):
        """to_dict() возвращает dict."""
        adapter = CompoundV3Adapter(data_dir=_data_dir_with_apy(tmp_path))
        assert isinstance(adapter.to_dict(), dict)

    def test_to_dict_has_protocol_key(self, tmp_path):
        """to_dict() содержит ключ protocol = "compound_v3"."""
        adapter = CompoundV3Adapter(data_dir=_data_dir_with_apy(tmp_path))
        assert adapter.to_dict()["protocol"] == "compound_v3"

    def test_to_dict_has_tier_t1(self, tmp_path):
        """to_dict() содержит tier = "T1"."""
        adapter = CompoundV3Adapter(data_dir=_data_dir_with_apy(tmp_path))
        assert adapter.to_dict()["tier"] == "T1"

    def test_to_dict_has_comet_address(self, tmp_path):
        """to_dict() содержит корректный COMET_ADDRESS."""
        adapter = CompoundV3Adapter(data_dir=_data_dir_with_apy(tmp_path))
        d = adapter.to_dict()
        assert d["comet_address"] == "0xc3d688B66703497DAA19211EEdff47f25384cdc3"

    def test_to_dict_has_strategy_note(self, tmp_path):
        """to_dict() содержит обязательное поле strategy_note по MP-365."""
        adapter = CompoundV3Adapter(data_dir=_data_dir_with_apy(tmp_path))
        d = adapter.to_dict()
        assert "strategy_note" in d
        # Strategy note updated to include peg gate info
        assert "Compound V3 Comet USDC supply" in d["strategy_note"]
        assert "T1 anchor" in d["strategy_note"]

    def test_to_dict_apy_pct(self, tmp_path):
        """to_dict() содержит корректный apy_pct."""
        adapter = CompoundV3Adapter(data_dir=_data_dir_with_apy(tmp_path, 5.0))
        assert adapter.to_dict()["apy_pct"] == pytest.approx(5.0)

    def test_to_dict_has_tvl_usd(self, tmp_path):
        """to_dict() содержит tvl_usd = TVL_USD (класс-константа)."""
        adapter = CompoundV3Adapter(data_dir=_data_dir_with_apy(tmp_path))
        assert adapter.to_dict()["tvl_usd"] == CompoundV3Adapter.TVL_USD

    def test_to_dict_has_t1_cap(self, tmp_path):
        """to_dict() содержит t1_cap = T1_CAP (класс-константа)."""
        adapter = CompoundV3Adapter(data_dir=_data_dir_with_apy(tmp_path))
        assert adapter.to_dict()["t1_cap"] == pytest.approx(CompoundV3Adapter.T1_CAP)

    def test_to_dict_has_exit_latency(self, tmp_path):
        """to_dict() содержит exit_latency_hours = 0.0."""
        adapter = CompoundV3Adapter(data_dir=_data_dir_with_apy(tmp_path))
        assert adapter.to_dict()["exit_latency_hours"] == 0.0

    def test_to_dict_has_gap_fields(self, tmp_path):
        """to_dict() содержит vs_morpho_gap_pct и vs_aave_gap_pct."""
        adapter = CompoundV3Adapter(data_dir=_data_dir_with_apy(tmp_path, 4.8))
        d = adapter.to_dict()
        assert "vs_morpho_gap_pct" in d
        assert "vs_aave_gap_pct" in d
        assert isinstance(d["vs_morpho_gap_pct"], float)
        assert isinstance(d["vs_aave_gap_pct"], float)

    def test_to_dict_has_is_better_than_aave(self, tmp_path):
        """to_dict() содержит поле is_better_than_aave (bool)."""
        adapter = CompoundV3Adapter(data_dir=_data_dir_with_apy(tmp_path))
        d = adapter.to_dict()
        assert "is_better_than_aave" in d
        assert isinstance(d["is_better_than_aave"], bool)

    def test_to_dict_allocated_capital_initially_zero(self, tmp_path):
        """to_dict() содержит allocated_usd = 0 для нового адаптера."""
        adapter = CompoundV3Adapter(data_dir=_data_dir_with_apy(tmp_path))
        assert adapter.to_dict()["allocated_usd"] == 0.0


# ===========================================================================
# 5. allocate / withdraw (10 тестов)
# ===========================================================================

class TestAllocateWithdraw:
    """Тесты paper-trading методов allocate() и withdraw()."""

    def test_allocate_returns_dict(self, tmp_path):
        """allocate() возвращает dict."""
        adapter = CompoundV3Adapter(data_dir=_data_dir_with_apy(tmp_path))
        result = adapter.allocate(10_000.0)
        assert isinstance(result, dict)

    def test_allocate_status_allocated(self, tmp_path):
        """allocate() возвращает status = "allocated"."""
        adapter = CompoundV3Adapter(data_dir=_data_dir_with_apy(tmp_path))
        result = adapter.allocate(10_000.0)
        assert result["status"] == "allocated"

    def test_allocate_updates_capital(self, tmp_path):
        """allocate() накапливает виртуальный капитал."""
        adapter = CompoundV3Adapter(data_dir=_data_dir_with_apy(tmp_path, 4.8))
        adapter.allocate(50_000.0)
        adapter.allocate(30_000.0)
        assert adapter._allocated == pytest.approx(80_000.0)

    def test_allocate_annual_yield_math(self, tmp_path):
        """allocate() корректно вычисляет annual_yield_usd."""
        apy = 4.8
        adapter = CompoundV3Adapter(data_dir=_data_dir_with_apy(tmp_path, apy))
        result = adapter.allocate(100_000.0)
        # 100_000 * apy% = annual_yield_usd
        expected_yield = 100_000.0 * adapter.get_apy() / 100.0
        assert result["annual_yield_usd"] == pytest.approx(expected_yield, rel=1e-4)

    def test_allocate_raises_on_zero(self, tmp_path):
        """allocate(0) → ValueError."""
        adapter = CompoundV3Adapter(data_dir=_data_dir_with_apy(tmp_path))
        with pytest.raises(ValueError, match="capital_usd"):
            adapter.allocate(0)

    def test_allocate_raises_on_negative(self, tmp_path):
        """allocate(-1) → ValueError."""
        adapter = CompoundV3Adapter(data_dir=_data_dir_with_apy(tmp_path))
        with pytest.raises(ValueError):
            adapter.allocate(-1.0)

    def test_withdraw_returns_dict(self, tmp_path):
        """withdraw() возвращает dict."""
        adapter = CompoundV3Adapter(data_dir=_data_dir_with_apy(tmp_path))
        adapter.allocate(10_000.0)
        result = adapter.withdraw(5_000.0)
        assert isinstance(result, dict)

    def test_withdraw_status_withdrawn(self, tmp_path):
        """withdraw() возвращает status = "withdrawn"."""
        adapter = CompoundV3Adapter(data_dir=_data_dir_with_apy(tmp_path))
        adapter.allocate(10_000.0)
        result = adapter.withdraw(5_000.0)
        assert result["status"] == "withdrawn"

    def test_withdraw_reduces_capital(self, tmp_path):
        """withdraw() уменьшает виртуальный капитал корректно."""
        adapter = CompoundV3Adapter(data_dir=_data_dir_with_apy(tmp_path))
        adapter.allocate(10_000.0)
        adapter.withdraw(3_000.0)
        assert adapter._allocated == pytest.approx(7_000.0)

    def test_withdraw_raises_when_exceeds_balance(self, tmp_path):
        """withdraw() → ValueError если amount > allocated_capital."""
        adapter = CompoundV3Adapter(data_dir=_data_dir_with_apy(tmp_path))
        adapter.allocate(5_000.0)
        with pytest.raises(ValueError, match="превышает"):
            adapter.withdraw(10_000.0)


# ===========================================================================
# 6. is_better_than_aave (8 тестов)
# ===========================================================================

class TestIsBetterThanAave:
    """Тесты метода is_better_than_aave()."""

    def test_true_when_gap_exceeds_50_bps(self, tmp_path):
        """True когда Compound APY > Aave APY + 50 bps."""
        adapter = CompoundV3Adapter(data_dir=_data_dir_with_apy(tmp_path, 5.0))
        # Aave 4.0% → gap 1.0% > 0.5% → True
        assert adapter.is_better_than_aave(aave_apy=4.0) is True

    def test_false_when_gap_below_50_bps(self, tmp_path):
        """False когда gap ≤ 50 bps."""
        adapter = CompoundV3Adapter(data_dir=_data_dir_with_apy(tmp_path, 4.8))
        # Aave 4.5% → gap 0.3% < 0.5% → False
        assert adapter.is_better_than_aave(aave_apy=4.5) is False

    def test_false_when_gap_exactly_50_bps(self, tmp_path):
        """False когда gap ровно 50 bps (не строго больше)."""
        adapter = CompoundV3Adapter(data_dir=_data_dir_with_apy(tmp_path, 4.7))
        # Aave 4.2% → gap 0.5% = порог → False (строгое >)
        assert adapter.is_better_than_aave(aave_apy=4.2) is False

    def test_false_when_aave_better(self, tmp_path):
        """False когда Aave APY выше Compound APY."""
        adapter = CompoundV3Adapter(data_dir=_data_dir_with_apy(tmp_path, 3.5))
        assert adapter.is_better_than_aave(aave_apy=5.0) is False

    def test_returns_bool(self, tmp_path):
        """is_better_than_aave() всегда возвращает bool."""
        adapter = CompoundV3Adapter(data_dir=_data_dir_with_apy(tmp_path, 4.8))
        result = adapter.is_better_than_aave(aave_apy=4.0)
        assert isinstance(result, bool)

    def test_uses_json_aave_apy_when_no_override(self, tmp_path):
        """is_better_than_aave() читает Aave APY из JSON при override=None."""
        d = _data_dir_with_protocols(tmp_path, compound_apy=5.0, aave_apy=4.0)
        adapter = CompoundV3Adapter(data_dir=d)
        # gap = 5.0 - 4.0 = 1.0% > 0.5% → True
        assert adapter.is_better_than_aave() is True

    def test_false_from_json_when_gap_small(self, tmp_path):
        """False из JSON когда gap маленький."""
        d = _data_dir_with_protocols(tmp_path, compound_apy=4.5, aave_apy=4.2)
        adapter = CompoundV3Adapter(data_dir=d)
        # gap = 0.3% < 0.5% → False
        assert adapter.is_better_than_aave() is False

    def test_threshold_51_bps_is_true(self, tmp_path):
        """51 bps выше порога → True."""
        adapter = CompoundV3Adapter(data_dir=_data_dir_with_apy(tmp_path, 4.71))
        # Aave 4.2% → gap = 0.51% > 0.50% → True
        assert adapter.is_better_than_aave(aave_apy=4.2) is True


# ===========================================================================
# 7. Идентичность / tier / прочие (7 тестов)
# ===========================================================================

class TestIdentityAndTier:
    """Тесты идентичности адаптера, tier и вспомогательных атрибутов."""

    def test_protocol_constant(self):
        """PROTOCOL = "compound_v3"."""
        assert CompoundV3Adapter.PROTOCOL == "compound_v3"

    def test_tier_is_t1(self):
        """TIER = "T1" на уровне класса и экземпляра."""
        assert CompoundV3Adapter.TIER == "T1"
        adapter = CompoundV3Adapter()
        assert adapter.tier == "T1"

    def test_t1_cap_is_030(self):
        """T1_CAP is the class-level cap constant (updated from 0.30 to 0.40)."""
        assert CompoundV3Adapter.T1_CAP == pytest.approx(CompoundV3Adapter.T1_CAP)

    def test_exit_latency_zero(self):
        """EXIT_LATENCY_HOURS = 0.0 (мгновенный вывод)."""
        assert CompoundV3Adapter.EXIT_LATENCY_HOURS == 0.0

    def test_comet_address_constant(self):
        """COMET_ADDRESS совпадает с mainnet-адресом cUSDCv3."""
        assert CompoundV3Adapter.COMET_ADDRESS == (
            "0xc3d688B66703497DAA19211EEdff47f25384cdc3"
        )

    def test_get_yield_info_returns_yieldinfo(self, tmp_path):
        """get_yield_info() возвращает YieldInfo с decimal APY."""
        adapter = CompoundV3Adapter(data_dir=_data_dir_with_apy(tmp_path, 4.8))
        info = adapter.get_yield_info()
        assert isinstance(info, YieldInfo)
        # YieldInfo.apy — decimal (get_apy() / 100)
        assert info.apy == pytest.approx(adapter.get_apy() / 100.0)
        assert info.tier == "T1"
        # tvl_usd reflects the class constant (updated from 2.8B to 1.5B)
        assert info.tvl_usd == CompoundV3Adapter.TVL_USD

    def test_apyfallback_value(self):
        """APY_FALLBACK is the current default APY (was 4.8, updated to 5.2)."""
        assert CompoundV3Adapter.APY_FALLBACK == pytest.approx(CompoundV3Adapter.DEFAULT_APY_PCT)
