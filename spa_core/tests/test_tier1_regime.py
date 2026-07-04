"""Tests for spa_core/backtesting/tier1/regime.py — pure stdlib, deterministic."""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime as _dt

import os
import pytest

from spa_core.backtesting.tier1 import regime as reg


def _synthetic(values):
    """Build [(date, apy)] with a monotonic daily date axis from a list of values."""
    base = _dt.date(2024, 1, 1)
    return [((base + _dt.timedelta(days=i)).isoformat(), float(v))
            for i, v in enumerate(values)]


# ---------------------------------------------------------------------------
# real-data driven
# ---------------------------------------------------------------------------
def test_aggregate_series_monotonic_axis():
    series = reg.aggregate_rate_series()
    if not series:
        pytest.skip("no real APY history available")
    dates = [d for d, _ in series]
    assert dates == sorted(dates)
    assert len(set(dates)) == len(dates)  # strictly unique / increasing
    assert all(isinstance(v, float) and v >= 0 for _, v in series)


def test_regimes_in_allowed_label_set():
    series = reg.aggregate_rate_series()
    if not series:
        pytest.skip("no real APY history available")
    labels = reg.classify_regimes(series)
    assert len(labels) == len(series)
    assert all(r in reg.REGIME_LABELS for _, r in labels)
    # date axis preserved
    assert [d for d, _ in labels] == [d for d, _ in series]


def test_current_regime_valid_label():
    cur = reg.current_regime()
    assert cur["regime"] in reg.REGIME_LABELS
    assert cur["trend"] in ("up", "down", "flat")


def test_determinism():
    a = reg.aggregate_rate_series()
    b = reg.aggregate_rate_series()
    assert a == b
    if a:
        assert reg.classify_regimes(a) == reg.classify_regimes(b)
        assert reg.current_regime(a) == reg.current_regime(b)


def test_summary_counts_consistent():
    series = reg.aggregate_rate_series()
    if not series:
        pytest.skip("no real APY history available")
    summary = reg.regime_summary(series)
    counts = summary["regime_counts"]
    assert set(counts).issubset(set(reg.REGIME_LABELS))
    assert sum(counts.values()) == len(series) == summary["n_days"]
    assert summary["current"]["regime"] in reg.REGIME_LABELS


@pytest.mark.skipif(os.environ.get("GITHUB_ACTIONS") == "true", reason="data/env-dependent (needs committed data/ or the Mac host); runs locally, skipped in the data-less GitHub CI")
def test_build_report_atomic_and_shape(tmp_path, monkeypatch):
    out_file = tmp_path / "tier1_regime.json"
    monkeypatch.setattr(reg, "_DATA", tmp_path)
    monkeypatch.setattr(reg, "_OUT", out_file)
    rep = reg.build_report(write=True)
    assert rep["model"] == "tier1_regime"
    assert rep["llm_forbidden"] is True
    assert rep["current"]["regime"] in reg.REGIME_LABELS
    import json
    on_disk = json.loads(out_file.read_text())
    assert on_disk["current"]["regime"] in reg.REGIME_LABELS
    # no leftover temp files
    leftovers = [p for p in tmp_path.iterdir() if p.name.startswith(".tier1regime_")]
    assert not leftovers


# ---------------------------------------------------------------------------
# synthetic series — controlled classification
# ---------------------------------------------------------------------------
def test_rising_series_classifies_rising():
    # steady strong uptrend around the median -> latter part RISING (not HIGH/LOW band)
    series = _synthetic([5.0 + 0.05 * i for i in range(120)])
    labels = reg.classify_regimes(series, window=30)
    tail = [r for _, r in labels[-20:]]
    assert "RISING" in tail
    assert "FALLING" not in tail


def test_falling_series_classifies_falling():
    series = _synthetic([10.0 - 0.05 * i for i in range(120)])
    labels = reg.classify_regimes(series, window=30)
    tail = [r for _, r in labels[-20:]]
    assert "FALLING" in tail
    assert "RISING" not in tail


def test_flat_series_classifies_normal():
    series = _synthetic([5.0] * 120)
    labels = reg.classify_regimes(series, window=30)
    assert all(r == "NORMAL" for _, r in labels)


def test_high_and_low_bands():
    # long flat baseline at 4 sets the median; a sustained jump to 8 -> HIGH_YIELD,
    # a sustained drop to 1 -> LOW_YIELD.
    vals = [4.0] * 80 + [8.0] * 40 + [1.0] * 40
    series = _synthetic(vals)
    labels = [r for _, r in reg.classify_regimes(series, window=30)]
    assert "HIGH_YIELD" in labels
    assert "LOW_YIELD" in labels


def test_rolling_slope_sign():
    up = reg._rolling_slope([float(i) for i in range(40)], 30)
    assert up[-1] > 0
    down = reg._rolling_slope([float(40 - i) for i in range(40)], 30)
    assert down[-1] < 0


def test_empty_series_safe():
    assert reg.aggregate_rate_series({}, ["nope"]) == []
    assert reg.classify_regimes([]) == []
    cur = reg.current_regime([])
    assert cur["regime"] in reg.REGIME_LABELS
