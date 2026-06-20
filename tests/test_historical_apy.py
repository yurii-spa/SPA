"""Tests for the historical APY pipeline (MP-1238).

Covers the fetcher's synthetic generator + orchestration and the APYDatabase
query layer. Network is never required: tests drive the synthetic path and a
temp data dir, so they are fully offline and deterministic.
"""
from __future__ import annotations

import json
import os
from datetime import date

import pytest

from spa_core.data import apy_database as db
from spa_core.data import historical_apy_fetcher as fetcher

PROTOCOLS = fetcher.PROTOCOLS
END = date(2026, 6, 20)


# --- fixtures ---------------------------------------------------------------


@pytest.fixture()
def store(tmp_path):
    """A populated historical_apy store (synthetic) + a bound APYDatabase."""
    data_dir = str(tmp_path)
    fetcher.run(data_dir, days=365, force_synthetic=True, write=True)
    database = db.APYDatabase(data_dir=os.path.join(data_dir, "historical_apy"))
    return database


# --- synthetic generator: shape & ranges -----------------------------------


def test_synthetic_returns_requested_length():
    series = fetcher.generate_synthetic("aave_v3_usdc", days=365, end=END)
    assert len(series) == 365


def test_synthetic_custom_length():
    assert len(fetcher.generate_synthetic("aave_v3_usdc", days=90, end=END)) == 90


def test_synthetic_rows_have_date_and_apy():
    series = fetcher.generate_synthetic("aave_v3_usdc", days=10, end=END)
    for row in series:
        assert set(row.keys()) == {"date", "apy"}


def test_synthetic_apy_in_valid_band():
    for proto in PROTOCOLS:
        for row in fetcher.generate_synthetic(proto, days=365, end=END):
            assert 0.0 <= row["apy"] <= 50.0


def test_synthetic_dates_are_iso_and_sorted():
    series = fetcher.generate_synthetic("aave_v3_usdc", days=365, end=END)
    dates = [r["date"] for r in series]
    assert dates == sorted(dates)
    for d in dates:
        date.fromisoformat(d)  # raises if malformed


def test_synthetic_ends_on_requested_end_date():
    series = fetcher.generate_synthetic("aave_v3_usdc", days=365, end=END)
    assert series[-1]["date"] == END.isoformat()


def test_synthetic_is_deterministic():
    a = fetcher.generate_synthetic("aave_v3_usdc", days=365, end=END)
    b = fetcher.generate_synthetic("aave_v3_usdc", days=365, end=END)
    assert a == b


def test_synthetic_differs_per_protocol():
    a = fetcher.generate_synthetic("aave_v3_usdc", days=365, end=END)
    b = fetcher.generate_synthetic("sky_susds", days=365, end=END)
    assert a != b


def test_synthetic_no_consecutive_date_gaps():
    series = fetcher.generate_synthetic("aave_v3_usdc", days=30, end=END)
    days = [date.fromisoformat(r["date"]) for r in series]
    for prev, nxt in zip(days, days[1:]):
        assert (nxt - prev).days == 1


def test_base_rate_regimes_reflect_documented_history():
    # 2025 bull regime should price above the 2026 current regime.
    assert fetcher._base_rate(date(2025, 3, 1)) > fetcher._base_rate(date(2026, 3, 1))


# --- chart parsing (no network) ---------------------------------------------


def test_fetch_chart_filters_anomalies(monkeypatch):
    payload = {
        "status": "success",
        "data": [
            {"timestamp": "2025-01-01T12:00:00Z", "apy": 4.0},
            {"timestamp": "2025-01-02T12:00:00Z", "apy": 999.0},   # too high
            {"timestamp": "2025-01-03T12:00:00Z", "apy": -1.0},    # negative
            {"timestamp": "2025-01-04T12:00:00Z", "apy": 5.0},
        ],
    }
    monkeypatch.setattr(fetcher, "_http_get_json", lambda url, **kw: payload)
    series = fetcher.fetch_chart("pool", days=365)
    apys = [r["apy"] for r in series]
    assert apys == [4.0, 5.0]


def test_fetch_chart_collapses_to_one_per_day(monkeypatch):
    payload = {
        "status": "success",
        "data": [
            {"timestamp": "2025-01-01T06:00:00Z", "apy": 4.0},
            {"timestamp": "2025-01-01T18:00:00Z", "apy": 4.5},  # later same day wins
        ],
    }
    monkeypatch.setattr(fetcher, "_http_get_json", lambda url, **kw: payload)
    series = fetcher.fetch_chart("pool", days=365)
    assert series == [{"date": "2025-01-01", "apy": 4.5}]


def test_fetch_chart_handles_network_failure(monkeypatch):
    monkeypatch.setattr(fetcher, "_http_get_json", lambda url, **kw: None)
    assert fetcher.fetch_chart("pool") == []


def test_build_falls_back_to_synthetic_on_empty(monkeypatch):
    monkeypatch.setattr(fetcher, "fetch_chart", lambda *a, **k: [])
    series, source = fetcher.build_protocol_series("aave_v3_usdc", days=365)
    assert source == "synthetic"
    assert len(series) == 365


def test_build_backfills_young_pool(monkeypatch):
    real = fetcher.generate_synthetic("morpho_blue_usdc", days=56, end=END)
    monkeypatch.setattr(fetcher, "fetch_chart", lambda *a, **k: real)
    series, source = fetcher.build_protocol_series("morpho_blue_usdc", days=365)
    assert source == "defillama+synthetic"
    assert len(series) == 365


# --- run() orchestration ----------------------------------------------------


def test_run_writes_all_protocol_files(tmp_path):
    fetcher.run(str(tmp_path), days=365, force_synthetic=True, write=True)
    out = os.path.join(str(tmp_path), "historical_apy")
    for proto in PROTOCOLS:
        assert os.path.exists(os.path.join(out, f"{proto}.json"))


def test_run_check_mode_writes_nothing(tmp_path):
    fetcher.run(str(tmp_path), days=365, force_synthetic=True, write=False)
    assert not os.path.isdir(os.path.join(str(tmp_path), "historical_apy"))


def test_run_files_contain_365_points(tmp_path):
    fetcher.run(str(tmp_path), days=365, force_synthetic=True, write=True)
    out = os.path.join(str(tmp_path), "historical_apy")
    for proto in PROTOCOLS:
        with open(os.path.join(out, f"{proto}.json")) as fh:
            assert len(json.load(fh)) == 365


# --- APYDatabase ------------------------------------------------------------


def test_list_available_protocols(store):
    assert sorted(store.list_available_protocols()) == sorted(PROTOCOLS)


def test_get_apy_history_full(store):
    assert len(store.get_apy_history("aave_v3_usdc")) == 365


def test_get_apy_history_range_inclusive(store):
    rows = store.get_apy_history(
        "aave_v3_usdc", start_date="2026-06-01", end_date="2026-06-10"
    )
    assert len(rows) == 10
    assert rows[0]["date"] == "2026-06-01"
    assert rows[-1]["date"] == "2026-06-10"


def test_get_apy_history_open_start(store):
    rows = store.get_apy_history("aave_v3_usdc", end_date="2025-06-25")
    assert all(r["date"] <= "2025-06-25" for r in rows)
    assert len(rows) == 5  # 2025-06-21 .. 06-25


def test_get_apy_history_unknown_protocol(store):
    assert store.get_apy_history("does_not_exist") == []


def test_get_average_apy_matches_manual_mean(store):
    rows = store.get_apy_history("aave_v3_usdc")[-30:]
    expected = sum(r["apy"] for r in rows) / len(rows)
    assert store.get_average_apy("aave_v3_usdc", period_days=30) == pytest.approx(expected)


def test_get_average_apy_in_band(store):
    for proto in PROTOCOLS:
        assert 0.0 <= store.get_average_apy(proto, period_days=365) <= 50.0


def test_get_apy_volatility_nonnegative(store):
    for proto in PROTOCOLS:
        assert store.get_apy_volatility(proto, period_days=365) >= 0.0


def test_get_apy_volatility_constant_series_is_zero(tmp_path):
    out = os.path.join(str(tmp_path), "historical_apy")
    os.makedirs(out)
    rows = [{"date": f"2026-01-{i:02d}", "apy": 5.0} for i in range(1, 11)]
    with open(os.path.join(out, "flat.json"), "w") as fh:
        json.dump(rows, fh)
    database = db.APYDatabase(data_dir=out)
    assert database.get_apy_volatility("flat", period_days=10) == 0.0


def test_period_days_limits_window(store):
    assert len(store.get_apy_history("aave_v3_usdc")) == 365
    # average over 7 days uses only the trailing 7 readings
    vals = [r["apy"] for r in store.get_apy_history("aave_v3_usdc")[-7:]]
    assert store.get_average_apy("aave_v3_usdc", period_days=7) == pytest.approx(
        sum(vals) / 7
    )


def test_module_level_helpers_use_real_store():
    # The repo's populated data dir exposes the live protocols via the singleton.
    protocols = db.list_available_protocols()
    assert "aave_v3_usdc" in protocols
    assert db.get_average_apy("aave_v3_usdc", period_days=30) > 0.0
