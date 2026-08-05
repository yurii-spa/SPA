"""
Пробные тесты линии A1 время-рядов: модули потока 3, оживлённые фидом
реальных APY-рядов (spa_core.analytics._apy_series).

Проверяется контракт module-level analyze(context):
* реальный ряд → скор 0-100, зависящий от протокола/формы ряда
  (полярность: падающая доходность → риск выше растущей);
* недобор истории → None (fail-closed, не фабрикация);
* неизвестный протокол → None;
* агрегатор (signal_aggregator._ModuleAdapter) видит entrypoint и
  коэрсит результат в ok-score.

Все данные — синтетические в tmp_path (data_dir протаскивается через
context["data_dir"]); ничего не читается из живого data/ и ничего в него
не пишется.
"""
import importlib
import json

import pytest

from spa_core.analytics import _apy_series as apy_series
from spa_core.analytics import _module_registry as registry
from spa_core.analytics.signal_aggregator import _ModuleAdapter

try:
    from spa_core.analytics._protocol_blindness import PROTOCOL_BLIND_MODULES
except Exception:  # pragma: no cover
    PROTOCOL_BLIND_MODULES = frozenset()


REVIVED_16 = [
    "apy_forecaster", "apy_momentum", "defi_borrow_rate_forecaster",
    "cross_chain_yield_comparator", "defi_risk_adjusted_yield_comparator",
    "protocol_defi_cross_chain_yield_normalizer",
    "protocol_defi_cross_protocol_yield_arbitrage_scanner",
    "protocol_defi_depeg_contagion_modeler",
    "defi_protocol_real_yield_sustainability_rater",
    "defi_yield_sustainability_rater",
    "protocol_defi_yield_source_sustainability_ranker",
    "chain_concentration", "liquidity_scorer",
    "protocol_liquidity_depth_stress_tester", "risk_budget",
    "defi_vault_strategy_risk_decomposer",
]
NOT_REVIVED_2 = ["defi_liquid_staking_rate_comparator",
                 "defi_nft_collateral_valuation_model"]
BONUS_5 = ["apy_anomaly_detector", "apy_tracker", "yield_forecast_engine",
           "protocol_defi_yield_seasonality_analyzer",
           "yield_compressor_score"]


@pytest.fixture(autouse=True)
def _fresh_cache():
    apy_series.clear_cache()
    yield
    apy_series.clear_cache()


@pytest.fixture()
def series_dir(tmp_path):
    """Синтетический data_dir: aave_v3 РАСТЁТ, morpho_blue ПАДАЕТ (40 дней),
    yearn_v3 — 2 точки (недобор для любого min_days≥3)."""
    hist = tmp_path / "historical_apy"
    hist.mkdir()

    def rows(start, step, n=40):
        return [{"date": "2026-06-%02d" % (d + 1) if d < 30
                 else "2026-07-%02d" % (d - 29),
                 "apy": round(start + step * d, 4)} for d in range(n)]

    (hist / "aave_v3_usdc.json").write_text(
        json.dumps(rows(2.0, +0.05)), encoding="utf-8")
    (hist / "morpho_blue_usdc.json").write_text(
        json.dumps(rows(4.0, -0.05)), encoding="utf-8")
    (hist / "yearn_v3_usdc.json").write_text(json.dumps([
        {"date": "2026-07-09", "apy": 3.0},
        {"date": "2026-07-10", "apy": 3.1},
    ]), encoding="utf-8")
    return tmp_path


def _ctx(protocol, data_dir):
    return {"protocol": protocol, "data_dir": str(data_dir), "source": "test"}


def _analyze(module_name, protocol, data_dir):
    mod = importlib.import_module("spa_core.analytics." + module_name)
    return mod.analyze(_ctx(protocol, data_dir))


# ─── Полярность и протокол-зависимость на синтетических рядах ────────────────

@pytest.mark.parametrize("module_name", [
    "apy_forecaster", "apy_momentum", "yield_forecast_engine", "apy_tracker",
])
def test_falling_apy_riskier_than_rising(module_name, series_dir):
    rising = _analyze(module_name, "aave_v3", series_dir)
    falling = _analyze(module_name, "morpho_blue", series_dir)
    assert rising is not None and falling is not None
    assert 0.0 <= rising["risk_score"] <= 100.0
    assert 0.0 <= falling["risk_score"] <= 100.0
    assert falling["risk_score"] > rising["risk_score"], (
        "падающий ряд обязан быть рискованнее растущего "
        f"({module_name}: falling={falling['risk_score']} "
        f"rising={rising['risk_score']})")


@pytest.mark.parametrize("module_name",
                         REVIVED_16 + BONUS_5)
def test_nonexistent_protocol_returns_none(module_name, series_dir):
    assert _analyze(module_name, "__nonexistent__", series_dir) is None


@pytest.mark.parametrize("module_name", [
    "apy_forecaster", "apy_momentum", "apy_anomaly_detector",
    "defi_protocol_real_yield_sustainability_rater",
])
def test_insufficient_history_returns_none(module_name, series_dir):
    """yearn_v3 в фикстуре имеет 2 точки — меньше любого min_days модулей."""
    assert _analyze(module_name, "yearn_v3", series_dir) is None


def test_anomaly_detector_flags_spike(series_dir):
    """Спокойный ряд + скачок последней точки → риск выше, чем без скачка.

    Ряд слегка колеблется (±0.05): у строго константного ряда σ=0 и
    z-score движка не определён — это законный NORMAL, а не контроль.
    """
    hist = series_dir / "historical_apy"
    flat = [{"date": "2026-06-%02d" % (d + 1),
             "apy": 3.0 + (0.05 if d % 2 else -0.05)}
            for d in range(1, 30)]
    (hist / "compound_v3_usdc.json").write_text(
        json.dumps(flat + [{"date": "2026-07-01", "apy": 3.01}]),
        encoding="utf-8")
    apy_series.clear_cache()
    normal = _analyze("apy_anomaly_detector", "compound_v3", series_dir)
    (hist / "compound_v3_usdc.json").write_text(
        json.dumps(flat + [{"date": "2026-07-01", "apy": 9.0}]),
        encoding="utf-8")
    apy_series.clear_cache()
    spiked = _analyze("apy_anomaly_detector", "compound_v3", series_dir)
    assert normal is not None and spiked is not None
    assert normal["label"] == "NORMAL"
    assert spiked["risk_score"] > normal["risk_score"]
    assert spiked["risk_score"] >= 50.0


def test_not_revived_modules_return_none_always(series_dir):
    for name in NOT_REVIVED_2:
        assert _analyze(name, "aave_v3", series_dir) is None


# ─── Реестр и агрегатор ──────────────────────────────────────────────────────

def test_revived_modules_registered_tier_b_with_module_entrypoint():
    tier_b = {m["module"]: m for m in registry.get_tier_modules("B")}
    for name in REVIVED_16 + BONUS_5:
        assert name in tier_b, f"{name} должен быть в Tier-B реестре"
        assert tier_b[name]["class"] is None, (
            f"{name}: entrypoint — module-level analyze(context), "
            "class обязан быть None")
        assert name not in PROTOCOL_BLIND_MODULES, (
            f"{name} размечен protocol-blind — агрегатор его не исполнит")
    for name in NOT_REVIVED_2:
        assert name not in tier_b, (
            f"{name} нечем честно кормить — в реестр не возвращается")


def test_aggregator_adapter_sees_analyze_and_coerces_ok(series_dir):
    adapter = _ModuleAdapter({"module": "apy_forecaster", "class": None,
                              "tier": "B", "category": "yield_quality",
                              "weight": 0.45})
    score, status, detail = adapter.run("aave_v3",
                                        {"data_dir": str(series_dir)})
    assert status == "ok", detail
    assert score is not None and 0.0 <= score <= 100.0
    # недобор истории → None → громкий dormant, не тихий OK
    score2, status2, _ = adapter.run("yearn_v3",
                                     {"data_dir": str(series_dir)})
    assert score2 is None and status2 == "dormant"


def test_context_path_writes_nothing(series_dir):
    """Контекст-путь модулей не должен писать НИ ОДНОГО файла в data_dir."""
    before = {p.name for p in series_dir.rglob("*") if p.is_file()}
    for name in REVIVED_16 + BONUS_5 + NOT_REVIVED_2:
        _analyze(name, "aave_v3", series_dir)
        _analyze(name, "morpho_blue", series_dir)
    after = {p.name for p in series_dir.rglob("*") if p.is_file()}
    assert after == before, f"context-путь создал файлы: {after - before}"
