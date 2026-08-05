"""
Тесты spa_core.analytics._apy_series — читатель APY-рядов линии A1.

Ключевой положительный контроль: оси дат файлов historical_apy НЕ совпадают
(память проекта historical-apy-axis-misaligned) — ряды обязаны выравниваться
ПО ДАТЕ, а не по индексу строки. Тест строит две оси со сдвигом и проверяет,
что join по дате даёт правильные пары, а недобор min_days даёт None
(fail-closed), никакой интерполяции.
"""
# FROZEN-DATE-OK: даты — ПРЕДМЕТ теста (выравнивание осей по дате, historical-apy-axis-misaligned); все даты — синтетические фикстуры, часы не читаются.
import json

import pytest

from spa_core.analytics import _apy_series as apy_series


@pytest.fixture(autouse=True)
def _fresh_cache():
    apy_series.clear_cache()
    yield
    apy_series.clear_cache()


def _write_hist(data_dir, stem, rows):
    hist = data_dir / "historical_apy"
    hist.mkdir(exist_ok=True)
    (hist / (stem + ".json")).write_text(json.dumps(rows), encoding="utf-8")


# ─── Выравнивание по дате (положительный контроль) ───────────────────────────

def test_misaligned_axes_join_by_date_not_by_index(tmp_path):
    """Оси со сдвигом на 2 дня: join по индексу дал бы пары (07-01, 07-03);
    join по дате обязан пересечь только общие даты 07-03/07-04."""
    _write_hist(tmp_path, "aave_v3_usdc", [
        {"date": "2026-07-01", "apy": 1.0},
        {"date": "2026-07-02", "apy": 2.0},
        {"date": "2026-07-03", "apy": 3.0},
        {"date": "2026-07-04", "apy": 4.0},
    ])
    _write_hist(tmp_path, "compound_v3_usdc", [
        {"date": "2026-07-03", "apy": 30.0},
        {"date": "2026-07-04", "apy": 40.0},
        {"date": "2026-07-05", "apy": 50.0},
    ])
    aligned = apy_series.get_aligned(
        ["aave_v3", "compound_v3"], data_dir=tmp_path)
    assert aligned is not None
    assert [d for d, _ in aligned["aave_v3"]] == ["2026-07-03", "2026-07-04"]
    assert [d for d, _ in aligned["compound_v3"]] == ["2026-07-03", "2026-07-04"]
    # Значения спарены по ДАТЕ: 3.0↔30.0, 4.0↔40.0 (по индексу было бы 1.0↔30.0)
    assert [v for _, v in aligned["aave_v3"]] == [3.0, 4.0]
    assert [v for _, v in aligned["compound_v3"]] == [30.0, 40.0]


def test_series_sorted_by_date_even_if_file_unsorted(tmp_path):
    _write_hist(tmp_path, "aave_v3_usdc", [
        {"date": "2026-07-03", "apy": 3.0},
        {"date": "2026-07-01", "apy": 1.0},
        {"date": "2026-07-02", "apy": 2.0},
    ])
    series = apy_series.get_series("aave_v3", data_dir=tmp_path)
    assert [d for d, _ in series] == ["2026-07-01", "2026-07-02", "2026-07-03"]


# ─── Fail-closed ─────────────────────────────────────────────────────────────

def test_min_days_shortfall_returns_none(tmp_path):
    _write_hist(tmp_path, "aave_v3_usdc", [
        {"date": "2026-07-01", "apy": 1.0},
        {"date": "2026-07-02", "apy": 2.0},
    ])
    assert apy_series.get_series("aave_v3", data_dir=tmp_path) is not None
    assert apy_series.get_series("aave_v3", min_days=3,
                                 data_dir=tmp_path) is None


def test_unknown_protocol_and_bad_names_return_none(tmp_path):
    _write_hist(tmp_path, "aave_v3_usdc", [{"date": "2026-07-01", "apy": 1.0}])
    assert apy_series.get_series("__nonexistent__", data_dir=tmp_path) is None
    assert apy_series.get_series(None, data_dir=tmp_path) is None
    assert apy_series.get_series("", data_dir=tmp_path) is None
    assert apy_series.get_series(42, data_dir=tmp_path) is None


def test_gaps_are_not_interpolated(tmp_path):
    """Дыра в датах остаётся дырой: только фактические точки."""
    _write_hist(tmp_path, "aave_v3_usdc", [
        {"date": "2026-06-01", "apy": 1.0},
        {"date": "2026-06-02", "apy": 2.0},
        {"date": "2026-08-01", "apy": 3.0},  # разрыв ~2 месяца
    ])
    series = apy_series.get_series("aave_v3", data_dir=tmp_path)
    assert len(series) == 3
    assert [d for d, _ in series] == ["2026-06-01", "2026-06-02", "2026-08-01"]


def test_malformed_rows_and_absurd_values_dropped(tmp_path):
    _write_hist(tmp_path, "aave_v3_usdc", [
        {"date": "2026-07-01", "apy": 1.5},
        {"date": "2026-07-02"},                       # нет apy
        {"apy": 2.0},                                  # нет даты
        {"date": "not-a-date", "apy": 2.0},
        {"date": "2026-07-03", "apy": float("nan")},
        {"date": "2026-07-04", "apy": 1e9},            # вне диапазона
        {"date": "2026-07-05", "apy": True},           # bool ≠ число
        "garbage",
    ])
    series = apy_series.get_series("aave_v3", data_dir=tmp_path)
    assert series == [("2026-07-01", 1.5)]


def test_aligned_none_when_any_protocol_missing(tmp_path):
    _write_hist(tmp_path, "aave_v3_usdc", [{"date": "2026-07-01", "apy": 1.0}])
    assert apy_series.get_aligned(["aave_v3", "compound_v3"],
                                  data_dir=tmp_path) is None


def test_aligned_none_when_no_common_dates(tmp_path):
    _write_hist(tmp_path, "aave_v3_usdc", [{"date": "2026-07-01", "apy": 1.0}])
    _write_hist(tmp_path, "compound_v3_usdc",
                [{"date": "2026-07-02", "apy": 2.0}])
    assert apy_series.get_aligned(["aave_v3", "compound_v3"],
                                  data_dir=tmp_path) is None


# ─── Слияние источников и приоритет ──────────────────────────────────────────

def test_snapshot_sources_merge_and_hist_priority(tmp_path):
    _write_hist(tmp_path, "aave_v3_usdc", [
        {"date": "2026-08-04", "apy": 3.0},
        {"date": "2026-08-05", "apy": 3.1},  # та же дата, что у снапшота
    ])
    (tmp_path / "adapter_status.json").write_text(json.dumps({
        "generated_at": "2026-08-05T08:00:00+00:00",
        "adapters": {
            "aave_v3": {"apy": 9.9,
                        "last_updated": "2026-08-05T08:00:00+00:00"},
            "maple": {"apy": 4.8,
                      "last_updated": "2026-08-05T08:00:00+00:00"},
        },
    }), encoding="utf-8")
    (tmp_path / "apy_ranking.json").write_text(json.dumps({
        "generated_at": "2026-08-05T08:43:00+00:00",
        "by_apy": [
            {"protocol": "maple", "apy_pct": 7.7,
             "last_updated": "2026-08-05T08:43:00+00:00"},
            {"protocol": "pendle", "apy_pct": 8.0,
             "last_updated": "2026-08-05T08:43:00+00:00"},
        ],
    }), encoding="utf-8")
    # historical файл главнее снапшота на ту же дату (9.9 не подменяет 3.1)
    assert apy_series.get_series("aave_v3", data_dir=tmp_path)[-1] == \
        ("2026-08-05", 3.1)
    # adapter_status главнее ranking на ту же дату (4.8, не 7.7)
    assert apy_series.get_series("maple", data_dir=tmp_path) == \
        [("2026-08-05", 4.8)]
    # ranking даёт точку протоколам, которых больше нигде нет
    assert apy_series.get_series("pendle", data_dir=tmp_path) == \
        [("2026-08-05", 8.0)]
    protos = apy_series.list_protocols(data_dir=tmp_path)
    assert protos == ["aave_v3", "maple", "pendle"]


def test_aliases_conservative(tmp_path):
    _write_hist(tmp_path, "morpho_blue_usdc",
                [{"date": "2026-07-01", "apy": 5.0}])
    _write_hist(tmp_path, "sky_susds", [{"date": "2026-07-01", "apy": 4.5}])
    assert apy_series.get_series("morpho", data_dir=tmp_path) == \
        [("2026-07-01", 5.0)]
    assert apy_series.get_series("spark_susds", data_dir=tmp_path) == \
        [("2026-07-01", 4.5)]
    assert apy_series.get_series("sky", data_dir=tmp_path) == \
        [("2026-07-01", 4.5)]
    # morpho_steakhouse — ДРУГОЙ vault: чужой ряд ему не подставляется
    assert apy_series.get_series("morpho_steakhouse",
                                 data_dir=tmp_path) is None


def test_cache_invalidated_on_file_change(tmp_path):
    _write_hist(tmp_path, "aave_v3_usdc", [{"date": "2026-07-01", "apy": 1.0}])
    assert apy_series.get_series("aave_v3", data_dir=tmp_path) == \
        [("2026-07-01", 1.0)]
    # меняем файл (размер меняется → сигнатура кеша меняется)
    _write_hist(tmp_path, "aave_v3_usdc", [
        {"date": "2026-07-01", "apy": 1.0},
        {"date": "2026-07-02", "apy": 2.25},
    ])
    assert apy_series.get_series("aave_v3", data_dir=tmp_path)[-1] == \
        ("2026-07-02", 2.25)


def test_stats_and_days_available(tmp_path):
    _write_hist(tmp_path, "aave_v3_usdc", [
        {"date": "2026-07-01", "apy": 2.0},
        {"date": "2026-07-02", "apy": 4.0},
        {"date": "2026-07-03", "apy": 3.0},
    ])
    st = apy_series.stats("aave_v3", data_dir=tmp_path)
    assert st["n"] == 3
    assert st["current"] == 3.0
    assert st["mean"] == 3.0
    assert st["min"] == 2.0 and st["max"] == 4.0
    # просадка от пика 4.0 к 3.0 = 25%
    assert abs(st["max_drawdown_pct"] - 25.0) < 1e-9
    assert apy_series.days_available("aave_v3", data_dir=tmp_path) == 3
    assert apy_series.days_available("maple", data_dir=tmp_path) == 0
    assert apy_series.stats("aave_v3", min_days=5, data_dir=tmp_path) is None
