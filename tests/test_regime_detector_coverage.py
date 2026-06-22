"""
tests/test_regime_detector_coverage.py

MP-1468 (v10.84) — Coverage tests for spa_core/paper_trading/regime_detector.py
(790 lines, previously untested in tests/).

15 tests on compute_trend, compute_volatility, detect_regime.
stdlib-only, no external dependencies.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from spa_core.paper_trading.regime_detector import (
    compute_trend,
    compute_volatility,
    detect_regime,
    regime_transition_matrix,
)


# ─── compute_trend ────────────────────────────────────────────────────────────


def test_01_trend_up_monotone():
    """Strictly rising series → direction='UP'."""
    result = compute_trend([1.0, 2.0, 3.0, 4.0, 5.0])
    assert result["direction"] == "UP"
    assert result["slope"] > 0


def test_02_trend_down_monotone():
    """Strictly falling series → direction='DOWN'."""
    result = compute_trend([5.0, 4.0, 3.0, 2.0, 1.0])
    assert result["direction"] == "DOWN"
    assert result["slope"] < 0


def test_03_trend_flat():
    """Constant series → direction='FLAT'."""
    result = compute_trend([5.0, 5.0, 5.0, 5.0])
    assert result["direction"] == "FLAT"


def test_04_trend_empty():
    """Empty list → safe default (FLAT, slope=0)."""
    result = compute_trend([])
    assert result["direction"] == "FLAT"
    assert result["slope"] == 0


def test_05_trend_single():
    """Single element → safe default."""
    result = compute_trend([42.0])
    assert result["slope"] == 0


def test_06_trend_r_squared_in_range():
    """r_squared always in [0, 1]."""
    for values in [[1, 2, 3], [3, 1, 2], [5, 5, 5], []]:
        r = compute_trend(values)
        assert 0.0 <= r["r_squared"] <= 1.0


def test_07_trend_perfect_line_r_squared():
    """Perfect linear series → r_squared close to 1.0."""
    values = [float(i) for i in range(10)]
    r = compute_trend(values)
    assert r["r_squared"] > 0.99


# ─── compute_volatility ───────────────────────────────────────────────────────


def test_08_volatility_constant_normal():
    """Constant series → ratio=1.0, level='NORMAL'."""
    result = compute_volatility([5.0, 5.0, 5.0, 5.0, 5.0])
    assert result["ratio"] == 1.0
    assert result["level"] == "NORMAL"


def test_09_volatility_empty():
    """Empty list → safe default (all zeros, NORMAL)."""
    result = compute_volatility([])
    assert result["current_vol"] == 0.0
    assert result["level"] == "NORMAL"


def test_10_volatility_keys_present():
    """Return dict has all required keys."""
    result = compute_volatility([1.0, 2.0, 1.5, 3.0, 2.5])
    for key in ("current_vol", "mean_vol", "ratio", "level"):
        assert key in result


def test_11_volatility_level_valid():
    """Level is always one of HIGH/NORMAL/LOW."""
    for values in [[1, 1, 1], [1, 100, 1], [1.0001]*10]:
        result = compute_volatility(values)
        assert result["level"] in ("HIGH", "NORMAL", "LOW")


# ─── detect_regime ────────────────────────────────────────────────────────────


def _make_apy_history(protocol_values: dict) -> list:
    """Build apy_history entries from {protocol: [apys...]}."""
    from datetime import date, timedelta
    base = date(2026, 1, 1)
    days = max(len(v) for v in protocol_values.values())
    result = []
    for i in range(days):
        entry = {"date": str(base + timedelta(days=i))}
        for proto, vals in protocol_values.items():
            if i < len(vals):
                entry.setdefault("protocols", {})[proto] = vals[i]
        result.append(entry)
    return result


def test_12_detect_regime_returns_dict():
    """detect_regime returns a dict with 'regime' key."""
    apys = [{"date": f"2026-01-{i+1:02d}", "protocols": {"aave": 5.0 + i * 0.1}}
            for i in range(30)]
    result = detect_regime(apys)
    assert isinstance(result, dict)
    assert "regime" in result


def test_13_detect_regime_valid_values():
    """regime is always one of the 4 valid values."""
    valid = {"BULL", "BEAR", "SIDEWAYS", "VOLATILE"}
    apys = [{"date": f"2026-01-{i+1:02d}", "protocols": {"aave": float(5 + i)}}
            for i in range(30)]
    result = detect_regime(apys)
    assert result["regime"] in valid


def test_14_detect_regime_empty_history():
    """Empty apy_history → safe result (SIDEWAYS or error-safe)."""
    result = detect_regime([])
    assert isinstance(result, dict)
    assert result.get("regime") in {"BULL", "BEAR", "SIDEWAYS", "VOLATILE", None}


def test_15_regime_transition_matrix_empty():
    """Empty history list → empty matrix, no error."""
    result = regime_transition_matrix([])
    assert isinstance(result, dict)
