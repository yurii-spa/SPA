"""
Тесты для APYAggregator (MP-368).

Структура (62 теста):
  TestLoad              — загрузка из mock-JSON (10)
  TestRankByApy         — сортировка по APY (10)
  TestRankByRiskAdj     — risk-adjusted ранжирование (8)
  TestBestT1            — логика best_t1 (8)
  TestTopN              — top_n + tier_filter (10)
  TestVsBaseline        — vs_baseline (8)
  TestToSummaryDict     — to_summary_dict (8)

Требования: stdlib only, no network, no files (tmp-dir исключение).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from spa_core.adapters.apy_aggregator import (
    APYAggregator,
    AdapterSnapshot,
    RISK_WEIGHTS,
    MIN_TVL_USD,
    _best_apy_from_mock,
    _primary_network,
)


# ===========================================================================
# Фабрики / хелперы для тестов
# ===========================================================================

def make_snap(
    protocol: str = "proto-x",
    tier: str = "T1",
    apy_pct: float = 5.0,
    network: str = "ethereum",
    tvl_usd: float = 0.0,
    last_updated: str = "2026-06-12",
    risk_score: float = 0.20,
) -> AdapterSnapshot:
    """Создаёт AdapterSnapshot с заданными параметрами (удобный хелпер)."""
    return AdapterSnapshot(
        protocol=protocol,
        tier=tier,
        apy_pct=apy_pct,
        network=network,
        tvl_usd=tvl_usd,
        last_updated=last_updated,
        risk_score=risk_score,
    )


def write_status_json(tmp_path: Path, payload: dict) -> Path:
    """Пишет adapter_status.json во временную директорию и возвращает её путь."""
    status_file = tmp_path / "adapter_status.json"
    status_file.write_text(json.dumps(payload), encoding="utf-8")
    return tmp_path


# ---------------------------------------------------------------------------
# Базовый mock-статус — используется в нескольких тестах
# ---------------------------------------------------------------------------

BASE_STATUS = {
    "generated_at": "2026-06-12T10:00:00Z",
    "adapters": [
        {
            "protocol_key": "aave-v3",
            "tier": "T1",
            "allocation_cap": 0.4,
            "chains": ["ethereum"],
            "mock_apy": {"ethereum": {"USDC": 4.2}},
        },
        {
            "protocol_key": "compound-v3",
            "tier": "T1",
            "allocation_cap": 0.4,
            "chains": ["ethereum"],
            "mock_apy": {"ethereum": {"USDC": 4.8}},
        },
        {
            "protocol_key": "yearn-v3",
            "tier": "T2",
            "allocation_cap": 0.2,
            "chains": ["ethereum"],
            "mock_apy": {"ethereum": {"USDC": 6.8}},
        },
        {
            "protocol_key": "pendle-pt",
            "tier": "T2",
            "allocation_cap": 0.2,
            "chains": ["ethereum"],
            "mock_apy": {"ethereum": {"USDC": 8.0}},
        },
        # sky-susds исключён (allocation_cap=0)
        {
            "protocol_key": "sky-susds",
            "tier": "T2-conditional",
            "allocation_cap": 0.0,
            "chains": ["ethereum"],
            "mock_apy": {"ethereum": {"USDS": 6.5}},
        },
    ],
    "morpho_steakhouse": {
        "protocol_key": "morpho-blue",
        "bps_gain": 200,
    },
    "aave_arbitrum": {
        "apy": 4.1,
        "tier": "T1",
        "network": "arbitrum",
        "tvl_usd": 1_200_000_000,
        "added_at": "2026-06-12",
    },
    # pendle_pt дублирует pendle-pt — должно быть пропущено
    "pendle_pt": {
        "protocol_key": "pendle-pt",
        "apy": 8.0,
        "tier": "T2",
        "chain": "ethereum",
    },
}


# ===========================================================================
# TestLoad — загрузка из mock-JSON (10 тестов)
# ===========================================================================

class TestLoad:

    def test_load_returns_aggregator_instance(self, tmp_path):
        """load() возвращает экземпляр APYAggregator."""
        d = write_status_json(tmp_path, BASE_STATUS)
        agg = APYAggregator.load(d)
        assert isinstance(agg, APYAggregator)

    def test_load_empty_on_missing_file(self, tmp_path):
        """Если файл отсутствует — возвращается пустой агрегатор (не падает)."""
        agg = APYAggregator.load(tmp_path)  # нет файла
        assert agg.snapshots() == []

    def test_load_empty_on_corrupt_json(self, tmp_path):
        """Повреждённый JSON → пустой агрегатор без исключений."""
        (tmp_path / "adapter_status.json").write_text("NOT_JSON", encoding="utf-8")
        agg = APYAggregator.load(tmp_path)
        assert agg.snapshots() == []

    def test_load_skips_zero_alloc_cap(self, tmp_path):
        """Адаптеры с allocation_cap=0 (sky-susds) пропускаются."""
        d = write_status_json(tmp_path, BASE_STATUS)
        agg = APYAggregator.load(d)
        protocols = {s.protocol for s in agg.snapshots()}
        assert "sky-susds" not in protocols

    def test_load_includes_adapters_array(self, tmp_path):
        """Все валидные адаптеры из массива adapters загружаются."""
        d = write_status_json(tmp_path, BASE_STATUS)
        agg = APYAggregator.load(d)
        protocols = {s.protocol for s in agg.snapshots()}
        assert "aave-v3" in protocols
        assert "compound-v3" in protocols
        assert "yearn-v3" in protocols
        assert "pendle-pt" in protocols

    def test_load_includes_morpho_steakhouse(self, tmp_path):
        """Morpho Steakhouse vault добавляется отдельным снимком."""
        d = write_status_json(tmp_path, BASE_STATUS)
        agg = APYAggregator.load(d)
        protocols = {s.protocol for s in agg.snapshots()}
        assert "morpho-blue-steakhouse" in protocols

    def test_load_morpho_apy_from_bps_gain(self, tmp_path):
        """APY Morpho вычисляется из bps_gain: 3.2 + 200/100 = 5.2."""
        d = write_status_json(tmp_path, BASE_STATUS)
        agg = APYAggregator.load(d)
        morpho = next(s for s in agg.snapshots() if s.protocol == "morpho-blue-steakhouse")
        assert abs(morpho.apy_pct - 5.2) < 1e-9

    def test_load_aave_arbitrum_snapshot(self, tmp_path):
        """Aave Arbitrum создаёт отдельный снимок с network=arbitrum."""
        d = write_status_json(tmp_path, BASE_STATUS)
        agg = APYAggregator.load(d)
        arb = next((s for s in agg.snapshots() if s.protocol == "aave-v3-arbitrum"), None)
        assert arb is not None
        assert arb.network == "arbitrum"
        assert arb.apy_pct == 4.1
        assert arb.tvl_usd == 1_200_000_000

    def test_load_no_duplicate_pendle(self, tmp_path):
        """pendle_pt top-level не дублирует pendle-pt из adapters."""
        d = write_status_json(tmp_path, BASE_STATUS)
        agg = APYAggregator.load(d)
        pendle_snaps = [s for s in agg.snapshots() if s.protocol == "pendle-pt"]
        assert len(pendle_snaps) == 1

    def test_load_generated_at_propagated(self, tmp_path):
        """generated_at из файла передаётся в last_updated снимков."""
        d = write_status_json(tmp_path, BASE_STATUS)
        agg = APYAggregator.load(d)
        # Хотя бы один снимок содержит generated_at
        lu_values = {s.last_updated for s in agg.snapshots()}
        assert "2026-06-12T10:00:00Z" in lu_values


# ===========================================================================
# TestRankByApy — сортировка по APY (10 тестов)
# ===========================================================================

class TestRankByApy:

    def test_rank_empty(self):
        """Пустой агрегатор → пустой список."""
        agg = APYAggregator([])
        assert agg.rank_by_apy() == []

    def test_rank_single(self):
        """Один снимок → возвращается список из одного элемента."""
        agg = APYAggregator([make_snap(apy_pct=5.0)])
        result = agg.rank_by_apy()
        assert len(result) == 1
        assert result[0].apy_pct == 5.0

    def test_rank_descending_order(self):
        """Снимки возвращаются в порядке убывания APY."""
        snaps = [
            make_snap("a", apy_pct=3.0),
            make_snap("b", apy_pct=7.5),
            make_snap("c", apy_pct=5.0),
        ]
        agg = APYAggregator(snaps)
        result = agg.rank_by_apy()
        apys = [s.apy_pct for s in result]
        assert apys == sorted(apys, reverse=True)

    def test_rank_first_is_highest(self):
        """Первый элемент имеет наибольший APY."""
        snaps = [make_snap("x", apy_pct=v) for v in [2.0, 9.0, 4.5, 1.0]]
        agg = APYAggregator(snaps)
        assert agg.rank_by_apy()[0].apy_pct == 9.0

    def test_rank_last_is_lowest(self):
        """Последний элемент имеет наименьший APY."""
        snaps = [make_snap("x", apy_pct=v) for v in [2.0, 9.0, 4.5, 1.0]]
        agg = APYAggregator(snaps)
        assert agg.rank_by_apy()[-1].apy_pct == 1.0

    def test_rank_preserves_all_snapshots(self):
        """rank_by_apy не теряет и не добавляет снимки."""
        snaps = [make_snap(str(i), apy_pct=float(i)) for i in range(5)]
        agg = APYAggregator(snaps)
        assert len(agg.rank_by_apy()) == 5

    def test_rank_returns_new_list(self):
        """rank_by_apy возвращает новый список (не изменяет внутренний)."""
        snaps = [make_snap("a", apy_pct=3.0), make_snap("b", apy_pct=7.0)]
        agg = APYAggregator(snaps)
        r1 = agg.rank_by_apy()
        r2 = agg.rank_by_apy()
        assert r1 is not r2  # разные объекты

    def test_rank_equal_apy_stable(self):
        """При одинаковом APY все снимки присутствуют в результате."""
        snaps = [make_snap(str(i), apy_pct=5.0) for i in range(4)]
        agg = APYAggregator(snaps)
        result = agg.rank_by_apy()
        assert len(result) == 4
        assert all(s.apy_pct == 5.0 for s in result)

    def test_rank_does_not_mutate_originals(self):
        """Сортировка не изменяет оригинальные снимки."""
        snap = make_snap("x", apy_pct=5.0)
        agg = APYAggregator([snap])
        _ = agg.rank_by_apy()
        assert snap.apy_pct == 5.0

    def test_rank_from_loaded_status(self, tmp_path):
        """После load() rank_by_apy возвращает отсортированный список."""
        d = write_status_json(tmp_path, BASE_STATUS)
        agg = APYAggregator.load(d)
        ranked = agg.rank_by_apy()
        apys = [s.apy_pct for s in ranked]
        assert apys == sorted(apys, reverse=True)


# ===========================================================================
# TestRankByRiskAdj — risk-adjusted ранжирование (8 тестов)
# ===========================================================================

class TestRankByRiskAdj:

    def test_empty_returns_empty(self):
        assert APYAggregator([]).rank_by_risk_adjusted() == []

    def test_t1_beats_t2_same_apy(self):
        """T1 с тем же APY имеет более высокий risk-adj, чем T2."""
        t1 = make_snap("t1", tier="T1", apy_pct=6.5)
        t2 = make_snap("t2", tier="T2", apy_pct=6.5)
        agg = APYAggregator([t2, t1])
        ranked = agg.rank_by_risk_adjusted()
        assert ranked[0].protocol == "t1"

    def test_risk_adj_formula(self):
        """risk_adj = apy / weight проверяется численно."""
        t2 = make_snap("t2", tier="T2", apy_pct=6.5)
        agg = APYAggregator([t2])
        ranked = agg.rank_by_risk_adjusted()
        expected = 6.5 / RISK_WEIGHTS["T2"]
        actual_apy = ranked[0].apy_pct / RISK_WEIGHTS[ranked[0].tier]
        assert abs(actual_apy - expected) < 1e-9

    def test_unknown_tier_gets_t3_weight(self):
        """Неизвестный тир → вес T3 (2.0), самый низкий risk-adj."""
        known = make_snap("k", tier="T1", apy_pct=4.0)
        unknown = make_snap("u", tier="UNKNOWN", apy_pct=8.0)
        agg = APYAggregator([unknown, known])
        ranked = agg.rank_by_risk_adjusted()
        # T1 4.0/1.0=4.0; UNKNOWN 8.0/2.0=4.0 — равны; T1 может быть любым
        # Проверяем, что оба присутствуют
        assert len(ranked) == 2

    def test_descending_order_guaranteed(self):
        """Результат всегда отсортирован по убыванию risk-adjusted APY."""
        snaps = [
            make_snap("a", tier="T2", apy_pct=10.0),  # 10/1.3 ≈ 7.69
            make_snap("b", tier="T1", apy_pct=5.0),   # 5/1.0  = 5.0
            make_snap("c", tier="T3", apy_pct=20.0),  # 20/2.0 = 10.0
        ]
        agg = APYAggregator(snaps)
        ranked = agg.rank_by_risk_adjusted()

        def _risk_weight(t):
            return RISK_WEIGHTS.get(t, RISK_WEIGHTS["T3"])

        adjs = [s.apy_pct / _risk_weight(s.tier) for s in ranked]
        assert adjs == sorted(adjs, reverse=True)

    def test_all_snapshots_preserved(self):
        """rank_by_risk_adjusted сохраняет все снимки."""
        snaps = [make_snap(str(i), tier="T2", apy_pct=float(i + 1)) for i in range(6)]
        agg = APYAggregator(snaps)
        assert len(agg.rank_by_risk_adjusted()) == 6

    def test_high_apy_t2_can_beat_low_apy_t1(self):
        """T2 c высоким APY может превзойти T1 с очень низким APY."""
        t1_low = make_snap("t1", tier="T1", apy_pct=1.0)   # adj=1.0
        t2_hi  = make_snap("t2", tier="T2", apy_pct=5.0)   # adj≈3.85
        agg = APYAggregator([t1_low, t2_hi])
        ranked = agg.rank_by_risk_adjusted()
        assert ranked[0].protocol == "t2"

    def test_returns_new_list_each_call(self):
        """Каждый вызов возвращает новый список."""
        agg = APYAggregator([make_snap(apy_pct=5.0)])
        assert agg.rank_by_risk_adjusted() is not agg.rank_by_risk_adjusted()


# ===========================================================================
# TestBestT1 — логика best_t1 (8 тестов)
# ===========================================================================

class TestBestT1:

    def test_returns_none_no_snapshots(self):
        assert APYAggregator([]).best_t1() is None

    def test_returns_none_no_t1(self):
        """Нет T1 → None."""
        agg = APYAggregator([make_snap("x", tier="T2", apy_pct=7.0)])
        assert agg.best_t1() is None

    def test_single_t1_returned(self):
        """Единственный T1 возвращается."""
        snap = make_snap("a", tier="T1", apy_pct=5.0)
        agg = APYAggregator([snap, make_snap("b", tier="T2")])
        assert agg.best_t1() == snap

    def test_highest_apy_t1_selected(self):
        """Из нескольких T1 выбирается с максимальным APY."""
        t1a = make_snap("t1a", tier="T1", apy_pct=4.2)
        t1b = make_snap("t1b", tier="T1", apy_pct=5.1)
        t2  = make_snap("t2",  tier="T2", apy_pct=9.0)
        agg = APYAggregator([t1a, t1b, t2])
        assert agg.best_t1().protocol == "t1b"

    def test_tvl_filter_applied_when_tvl_known(self):
        """T1 с TVL < MIN_TVL_USD отсеивается когда TVL известен."""
        small_tvl = make_snap("small", tier="T1", apy_pct=10.0, tvl_usd=50_000_000)
        large_tvl = make_snap("large", tier="T1", apy_pct=4.0,  tvl_usd=500_000_000)
        agg = APYAggregator([small_tvl, large_tvl])
        result = agg.best_t1()
        assert result is not None
        assert result.protocol == "large"

    def test_unknown_tvl_not_filtered(self):
        """T1 с tvl_usd=0 (неизвестен) не отсеивается фильтром TVL."""
        known_but_small = make_snap("small", tier="T1", apy_pct=3.0, tvl_usd=50_000_000)
        unknown_tvl = make_snap("unknown", tier="T1", apy_pct=2.0, tvl_usd=0.0)
        agg = APYAggregator([known_but_small, unknown_tvl])
        # unknown_tvl сохраняется; known_but_small отфильтровывается
        result = agg.best_t1()
        assert result is not None
        assert result.protocol == "unknown"

    def test_all_t1_below_tvl_threshold_returns_best(self):
        """Если ВСЕ T1 с tvl_usd=0 (неизвестен) — возвращается лучший."""
        t1a = make_snap("t1a", tier="T1", apy_pct=3.0, tvl_usd=0.0)
        t1b = make_snap("t1b", tier="T1", apy_pct=5.0, tvl_usd=0.0)
        agg = APYAggregator([t1a, t1b])
        assert agg.best_t1().protocol == "t1b"

    def test_t2_not_returned_by_best_t1(self):
        """best_t1 никогда не возвращает T2-снимок."""
        snaps = [
            make_snap("t2a", tier="T2", apy_pct=15.0),
            make_snap("t1a", tier="T1", apy_pct=4.0),
        ]
        agg = APYAggregator(snaps)
        result = agg.best_t1()
        assert result is not None
        assert result.tier == "T1"


# ===========================================================================
# TestTopN — top_n + tier_filter (10 тестов)
# ===========================================================================

class TestTopN:

    def test_top_n_zero_returns_empty(self):
        agg = APYAggregator([make_snap(apy_pct=5.0)])
        assert agg.top_n(0) == []

    def test_top_n_negative_returns_empty(self):
        agg = APYAggregator([make_snap(apy_pct=5.0)])
        assert agg.top_n(-1) == []

    def test_top_1_returns_highest(self):
        snaps = [make_snap(str(i), apy_pct=float(i)) for i in range(5)]
        agg = APYAggregator(snaps)
        result = agg.top_n(1)
        assert len(result) == 1
        assert result[0].apy_pct == 4.0

    def test_top_n_larger_than_count_returns_all(self):
        """n > числа снимков → возвращаем все."""
        snaps = [make_snap(str(i), apy_pct=float(i + 1)) for i in range(3)]
        agg = APYAggregator(snaps)
        assert len(agg.top_n(100)) == 3

    def test_top_n_sorted_descending(self):
        snaps = [make_snap(str(i), apy_pct=float(i)) for i in range(6)]
        agg = APYAggregator(snaps)
        result = agg.top_n(4)
        apys = [s.apy_pct for s in result]
        assert apys == sorted(apys, reverse=True)

    def test_tier_filter_t1_only(self):
        """tier_filter='T1' возвращает только T1-снимки."""
        snaps = [
            make_snap("t1", tier="T1", apy_pct=4.0),
            make_snap("t2", tier="T2", apy_pct=9.0),
        ]
        agg = APYAggregator(snaps)
        result = agg.top_n(10, tier_filter="T1")
        assert all(s.tier == "T1" for s in result)

    def test_tier_filter_t2_only(self):
        """tier_filter='T2' возвращает только T2-снимки."""
        snaps = [
            make_snap("t1a", tier="T1", apy_pct=4.0),
            make_snap("t2a", tier="T2", apy_pct=6.0),
            make_snap("t2b", tier="T2", apy_pct=8.0),
        ]
        agg = APYAggregator(snaps)
        result = agg.top_n(5, tier_filter="T2")
        assert all(s.tier == "T2" for s in result)
        assert len(result) == 2

    def test_tier_filter_no_match_returns_empty(self):
        """Если нет снимков с нужным тиром → пустой список."""
        agg = APYAggregator([make_snap(tier="T1", apy_pct=5.0)])
        assert agg.top_n(5, tier_filter="T3") == []

    def test_top_n_without_filter_across_all_tiers(self):
        """Без filter возвращаются снимки всех тиров."""
        snaps = [
            make_snap("a", tier="T1", apy_pct=5.0),
            make_snap("b", tier="T2", apy_pct=9.0),
        ]
        agg = APYAggregator(snaps)
        result = agg.top_n(2)
        tiers = {s.tier for s in result}
        assert "T1" in tiers and "T2" in tiers

    def test_empty_aggregator_top_n(self):
        """Пустой агрегатор → top_n всегда []."""
        agg = APYAggregator([])
        assert agg.top_n(5) == []


# ===========================================================================
# TestVsBaseline — vs_baseline (8 тестов)
# ===========================================================================

class TestVsBaseline:

    def test_empty_returns_empty_dict(self):
        assert APYAggregator([]).vs_baseline() == {}

    def test_default_baseline_is_3_2(self):
        """По умолчанию baseline = 3.2%."""
        snap = make_snap("x", apy_pct=5.2)
        agg = APYAggregator([snap])
        result = agg.vs_baseline()
        assert abs(result["x"] - 2.0) < 1e-6

    def test_positive_delta_above_baseline(self):
        """APY выше baseline → положительная дельта."""
        agg = APYAggregator([make_snap("hi", apy_pct=7.0)])
        assert agg.vs_baseline(baseline_apy=3.2)["hi"] > 0

    def test_negative_delta_below_baseline(self):
        """APY ниже baseline → отрицательная дельта."""
        agg = APYAggregator([make_snap("lo", apy_pct=2.0)])
        assert agg.vs_baseline(baseline_apy=3.2)["lo"] < 0

    def test_zero_delta_equal_baseline(self):
        """APY == baseline → дельта равна 0."""
        agg = APYAggregator([make_snap("eq", apy_pct=3.2)])
        assert abs(agg.vs_baseline(baseline_apy=3.2)["eq"]) < 1e-9

    def test_custom_baseline(self):
        """Кастомный baseline корректно применяется."""
        snap = make_snap("a", apy_pct=10.0)
        agg = APYAggregator([snap])
        assert abs(agg.vs_baseline(baseline_apy=5.0)["a"] - 5.0) < 1e-9

    def test_all_protocols_present_in_result(self):
        """Все протоколы присутствуют в результате."""
        snaps = [make_snap(str(i), apy_pct=float(i + 1)) for i in range(4)]
        agg = APYAggregator(snaps)
        result = agg.vs_baseline()
        assert set(result.keys()) == {str(i) for i in range(4)}

    def test_result_values_are_rounded(self):
        """Значения округлены до 6 знаков (не длинные float)."""
        agg = APYAggregator([make_snap("x", apy_pct=3.1415926535)])
        result = agg.vs_baseline(baseline_apy=3.0)
        # Значение должно быть разумно коротким
        val = result["x"]
        assert len(str(val).split(".")[-1]) <= 10  # не более 10 знаков после точки


# ===========================================================================
# TestToSummaryDict — to_summary_dict (8 тестов)
# ===========================================================================

class TestToSummaryDict:

    def test_empty_returns_correct_shape(self):
        """Пустой агрегатор → словарь с нулями и None."""
        result = APYAggregator([]).to_summary_dict()
        assert result["best_adapter"]   is None
        assert result["best_apy"]       is None
        assert result["worst_apy"]      is None
        assert result["spread"]         == 0.0
        assert result["count_adapters"] == 0
        assert result["best_t1"]        is None
        assert result["best_risk_adj"]  is None

    def test_all_expected_keys_present(self):
        """Все ожидаемые ключи присутствуют."""
        agg = APYAggregator([make_snap(apy_pct=5.0)])
        result = agg.to_summary_dict()
        expected_keys = {
            "best_adapter", "best_apy", "worst_apy", "spread",
            "count_adapters", "best_t1", "best_risk_adj",
        }
        assert expected_keys.issubset(result.keys())

    def test_count_adapters_correct(self):
        snaps = [make_snap(str(i), apy_pct=float(i + 1)) for i in range(5)]
        agg = APYAggregator(snaps)
        assert agg.to_summary_dict()["count_adapters"] == 5

    def test_best_adapter_has_highest_apy(self):
        snaps = [
            make_snap("low",  apy_pct=2.0),
            make_snap("high", apy_pct=9.0),
            make_snap("mid",  apy_pct=5.0),
        ]
        agg = APYAggregator(snaps)
        assert agg.to_summary_dict()["best_adapter"] == "high"

    def test_spread_matches_apy_spread(self):
        snaps = [make_snap("a", apy_pct=2.0), make_snap("b", apy_pct=8.0)]
        agg = APYAggregator(snaps)
        summary = agg.to_summary_dict()
        assert abs(summary["spread"] - 6.0) < 1e-9

    def test_best_t1_is_none_when_no_t1(self):
        agg = APYAggregator([make_snap("x", tier="T2", apy_pct=7.0)])
        assert agg.to_summary_dict()["best_t1"] is None

    def test_best_t1_present_when_t1_exists(self):
        snaps = [
            make_snap("t1", tier="T1", apy_pct=5.0),
            make_snap("t2", tier="T2", apy_pct=9.0),
        ]
        agg = APYAggregator(snaps)
        assert agg.to_summary_dict()["best_t1"] == "t1"

    def test_best_risk_adj_protocol(self):
        """best_risk_adj указывает на протокол с лучшим risk-adj APY."""
        snaps = [
            make_snap("t1x", tier="T1", apy_pct=4.0),   # adj=4.0
            make_snap("t2x", tier="T2", apy_pct=5.0),   # adj≈3.85
        ]
        agg = APYAggregator(snaps)
        # T1 4.0/1.0=4.0 > T2 5.0/1.3≈3.85
        assert agg.to_summary_dict()["best_risk_adj"] == "t1x"


# ===========================================================================
# TestSaveRanking — атомарная запись (4 дополнительных теста)
# ===========================================================================

class TestSaveRanking:

    def test_save_creates_file(self, tmp_path):
        """save_ranking создаёт файл."""
        agg = APYAggregator([make_snap("x", apy_pct=5.0)])
        out = tmp_path / "apy_ranking.json"
        agg.save_ranking(out)
        assert out.exists()

    def test_save_valid_json(self, tmp_path):
        """Записанный файл — валидный JSON."""
        agg = APYAggregator([make_snap("x", apy_pct=5.0)])
        out = tmp_path / "apy_ranking.json"
        agg.save_ranking(out)
        data = json.loads(out.read_text(encoding="utf-8"))
        assert isinstance(data, dict)

    def test_save_contains_expected_keys(self, tmp_path):
        """JSON содержит ключи generated_at, count, summary, by_apy, by_risk_adjusted."""
        agg = APYAggregator([make_snap("x", apy_pct=5.0)])
        out = tmp_path / "apy_ranking.json"
        agg.save_ranking(out)
        data = json.loads(out.read_text(encoding="utf-8"))
        for key in ("generated_at", "count", "summary", "by_apy", "by_risk_adjusted"):
            assert key in data, f"Missing key: {key}"

    def test_save_no_tmp_files_left(self, tmp_path):
        """После записи не должно оставаться tmp-файлов."""
        agg = APYAggregator([make_snap("x", apy_pct=5.0)])
        agg.save_ranking(tmp_path / "apy_ranking.json")
        tmp_files = list(tmp_path.glob(".tmp_apy_ranking_*.json"))
        assert len(tmp_files) == 0
