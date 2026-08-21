"""
Tests for edge_proportional_drawdown_exit.py (Idea #70: PDE).

All tests use only the module's internal deterministic fixture — no external files,
no network, no RiskPolicy, no spa_core.execution. IS_ADVISORY=True.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

# ── Load the edge script as a module ──────────────────────────────────────────

_SCRIPT = Path(__file__).parents[2] / "scripts" / "edge_proportional_drawdown_exit.py"
_spec = importlib.util.spec_from_file_location("edge_pde", _SCRIPT)
_mod = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(_mod)  # type: ignore[union-attr]


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_raw(n: int = 100, drift: float = 0.0003) -> list:
    """Simple constant-drift series."""
    eq = [100_000.0]
    for _ in range(n - 1):
        eq.append(eq[-1] * (1.0 + drift))
    return eq


def _make_crash(n: int = 100, crash_at: int = 50, crash_frac: float = 0.15,
                spread_days: int = 5) -> list:
    """Series with a crash starting at day `crash_at` spread over `spread_days` days."""
    eq = [100_000.0]
    daily_loss = 1.0 - (1.0 - crash_frac) ** (1.0 / spread_days)
    for i in range(1, n):
        if crash_at <= i < crash_at + spread_days:
            eq.append(eq[-1] * (1.0 - daily_loss))
        else:
            eq.append(eq[-1])
    return eq


# ── Unit tests ─────────────────────────────────────────────────────────────────

class TestPdeExposure:
    def test_fully_invested_below_start(self) -> None:
        assert _mod._pde_exposure(0.005, 0.02, 0.08) == pytest.approx(1.0)

    def test_fully_out_above_full(self) -> None:
        assert _mod._pde_exposure(0.09, 0.02, 0.08) == pytest.approx(0.0)

    def test_midpoint(self) -> None:
        assert _mod._pde_exposure(0.05, 0.02, 0.08) == pytest.approx(0.5)

    def test_at_d_start(self) -> None:
        assert _mod._pde_exposure(0.02, 0.02, 0.08) == pytest.approx(1.0)

    def test_at_d_full(self) -> None:
        assert _mod._pde_exposure(0.08, 0.02, 0.08) == pytest.approx(0.0)

    def test_degenerate_equal_thresholds(self) -> None:
        # d_full == d_start: exposure should be 0 or 1 depending on comparison
        assert _mod._pde_exposure(0.05, 0.05, 0.05) in {0.0, 1.0}

    def test_no_negative_exposure(self) -> None:
        assert _mod._pde_exposure(100.0, 0.02, 0.08) == pytest.approx(0.0)

    def test_no_exposure_above_one(self) -> None:
        assert _mod._pde_exposure(0.0, 0.02, 0.08) == pytest.approx(1.0)


class TestApplyPde:
    def test_no_crash_no_change(self) -> None:
        """With no drawdown, PDE should be identity (fully invested, no cost)."""
        raw = _make_raw(50, drift=0.0003)
        guarded, cost = _mod.apply_pde(raw, d_start=0.02, d_full=0.08, roundtrip=0.0)
        # Fully invested the whole time → no deviation from raw
        assert guarded[-1] == pytest.approx(raw[-1], rel=1e-6)
        assert cost == pytest.approx(0.0, abs=1e-6)

    def test_crash_reduces_drawdown(self) -> None:
        """PDE should reduce maxDD relative to raw on a large crash."""
        raw = _make_crash(100, crash_at=50, crash_frac=0.15)
        guarded, cost = _mod.apply_pde(raw, d_start=0.02, d_full=0.08, roundtrip=0.0)
        raw_dd = _mod._max_drawdown(raw)
        pde_dd = _mod._max_drawdown(guarded)
        assert pde_dd < raw_dd

    def test_short_series_passthrough(self) -> None:
        """Series of length < 2 should be returned unchanged."""
        raw = [100_000.0]
        guarded, cost = _mod.apply_pde(raw, d_start=0.02, d_full=0.08)
        assert guarded == [100_000.0]
        assert cost == pytest.approx(0.0, abs=1e-6)

    def test_cost_positive(self) -> None:
        """Transaction cost must be non-negative."""
        raw = _make_crash(100, crash_at=40, crash_frac=0.20)
        _, cost = _mod.apply_pde(raw, d_start=0.02, d_full=0.08, roundtrip=0.0096)
        assert cost >= 0.0

    def test_cost_zero_when_roundtrip_zero(self) -> None:
        raw = _make_crash(100, crash_at=40, crash_frac=0.20)
        _, cost = _mod.apply_pde(raw, d_start=0.02, d_full=0.08, roundtrip=0.0)
        assert cost == pytest.approx(0.0, abs=1e-9)

    def test_length_preserved(self) -> None:
        raw = _make_raw(200)
        guarded, _ = _mod.apply_pde(raw, d_start=0.02, d_full=0.08)
        assert len(guarded) == len(raw)

    def test_first_value_unchanged(self) -> None:
        raw = _make_raw(50)
        guarded, _ = _mod.apply_pde(raw, d_start=0.02, d_full=0.08)
        assert guarded[0] == pytest.approx(raw[0], rel=1e-9)

    def test_deeper_start_higher_dd(self) -> None:
        """A later trigger (d_start=0.05) should allow a larger drawdown than d_start=0.01."""
        raw = _make_crash(100, crash_at=50, crash_frac=0.20)
        g_early, _ = _mod.apply_pde(raw, d_start=0.01, d_full=0.08, roundtrip=0.0)
        g_late, _ = _mod.apply_pde(raw, d_start=0.05, d_full=0.15, roundtrip=0.0)
        # Earlier exit should protect more (lower DD or equal)
        assert _mod._max_drawdown(g_early) <= _mod._max_drawdown(g_late) + 0.01


class TestBinaryGuardian:
    def test_no_crash_no_change(self) -> None:
        raw = _make_raw(50)
        guarded, cost = _mod.apply_binary_guardian(raw, roundtrip=0.0)
        assert guarded[-1] == pytest.approx(raw[-1], rel=1e-6)
        assert cost == pytest.approx(0.0, abs=1e-9)

    def test_fires_on_large_crash(self) -> None:
        raw = _make_crash(100, crash_at=50, crash_frac=0.15)
        guarded, cost = _mod.apply_binary_guardian(raw, derisk_dd=0.04, roundtrip=0.0)
        assert _mod._max_drawdown(guarded) < _mod._max_drawdown(raw)

    def test_length_preserved(self) -> None:
        raw = _make_raw(200)
        guarded, _ = _mod.apply_binary_guardian(raw)
        assert len(guarded) == len(raw)


class TestMaxDrawdown:
    def test_no_drawdown(self) -> None:
        eq = [100.0, 101.0, 102.0, 103.0]
        assert _mod._max_drawdown(eq) == pytest.approx(0.0, abs=1e-9)

    def test_full_loss(self) -> None:
        eq = [100.0, 0.0]
        assert _mod._max_drawdown(eq) == pytest.approx(1.0)

    def test_known_dd(self) -> None:
        eq = [100.0, 80.0, 90.0]
        assert _mod._max_drawdown(eq) == pytest.approx(0.20, rel=1e-6)

    def test_empty(self) -> None:
        assert _mod._max_drawdown([]) == pytest.approx(0.0, abs=1e-9)


class TestApy:
    def test_zero_growth(self) -> None:
        eq = [100.0] * 366
        assert _mod._apy(eq) == pytest.approx(0.0, abs=1e-6)

    def test_known_apy(self) -> None:
        # 10% in 365 days
        eq = [100.0, 110.0]
        result = _mod._apy([100.0] + [100.0 * (1.1 ** (i / 365.0)) for i in range(1, 366)])
        assert result == pytest.approx(0.10, rel=0.01)


class TestPortfolioFunctions:
    def test_raw_equal_weight_consistent(self) -> None:
        """When all books are identical, portfolio == single book."""
        raw = _make_raw(100)
        books = {"a": list(raw), "b": list(raw)}
        port = _mod.raw_equal_weight(books)
        assert port[-1] == pytest.approx(raw[-1], rel=1e-6)

    def test_pde_portfolio_length(self) -> None:
        raw = _make_raw(150)
        books = {"a": list(raw), "b": list(raw)}
        port, _ = _mod.apply_pde_portfolio(books, d_start=0.02, d_full=0.08)
        assert len(port) == len(raw)

    def test_pde_portfolio_no_crash_identity(self) -> None:
        """Without drawdown, portfolio PDE should be same as raw."""
        raw = _make_raw(100, drift=0.0003)
        books = {"a": list(raw), "b": list(raw)}
        port, cost = _mod.apply_pde_portfolio(books, d_start=0.02, d_full=0.08, roundtrip=0.0)
        raw_port = _mod.raw_equal_weight(books)
        assert port[-1] == pytest.approx(raw_port[-1], rel=1e-6)
        assert cost == pytest.approx(0.0, abs=1e-6)


class TestFixtureSeries:
    def test_fixture_length(self) -> None:
        spec = _mod._BOOK_SPECS["susde_dn"]
        series = _mod._build_series(spec)
        # 2024-07-01 to 2026-05-31 inclusive
        import datetime
        n = (_mod._BACKTEST_END - _mod._BACKTEST_START).days + 1
        assert len(series) == n

    def test_fixture_initial_value_close(self) -> None:
        spec = _mod._BOOK_SPECS["susde_dn"]
        series = _mod._build_series(spec)
        assert series[0] == pytest.approx(_mod._INITIAL * (1.0 + spec["daily_drift"]), rel=1e-3)

    def test_fixture_positive_throughout(self) -> None:
        for name, spec in _mod._BOOK_SPECS.items():
            series = _mod._build_series(spec)
            assert all(v > 0 for v in series), f"Non-positive equity in {name}"

    def test_fixture_deterministic(self) -> None:
        """Same spec → same series (no randomness)."""
        spec = _mod._BOOK_SPECS["lrt_carry"]
        s1 = _mod._build_series(spec)
        s2 = _mod._build_series(spec)
        assert s1 == s2

    def test_stress_window_causes_loss(self) -> None:
        """Books with window_hits > 0 should show lower equity during stress windows."""
        spec = _mod._BOOK_SPECS["lrt_carry"]
        series = _mod._build_series(spec)
        # rseth_depeg_2026_04 hit = 22% — equity should be lower at end of April 2026
        import datetime
        start = _mod._BACKTEST_START
        idx_may1 = (datetime.date(2026, 5, 1) - start).days
        idx_mar31 = (datetime.date(2026, 3, 31) - start).days
        # By start of May, equity should be below what it would be without the 22% hit
        assert series[idx_may1] < series[idx_mar31]


class TestPdeVsBinaryOnCrash:
    """PDE should outperform binary guardian on large fast tails."""

    def test_pde_better_calmar_on_large_depeg(self) -> None:
        """On a 22% depeg (lrt_carry level), PDE Calmar > binary Calmar."""
        spec = _mod._BOOK_SPECS["lrt_carry"]
        raw = _mod._build_series(spec)
        g_binary, bg_cost = _mod.apply_binary_guardian(raw, roundtrip=0.0096)
        # Try the best PDE config for lrt_carry
        best_pde_calmar = -float("inf")
        for d_start, d_full in [(0.01, 0.06), (0.02, 0.08), (0.03, 0.10)]:
            g_pde, _ = _mod.apply_pde(raw, d_start=d_start, d_full=d_full, roundtrip=0.0096)
            c = _mod._calmar(g_pde)
            if c > best_pde_calmar:
                best_pde_calmar = c
        binary_calmar = _mod._calmar(g_binary)
        # PDE should do better (or at least comparable) on the catastrophic tail book
        assert best_pde_calmar > binary_calmar

    def test_pde_portfolio_better_calmar_than_binary_portfolio(self) -> None:
        """PDE at portfolio level should outperform binary portfolio guardian on the 3-book fixture."""
        books = {name: _mod._build_series(spec) for name, spec in _mod._BOOK_SPECS.items()
                 if name in ("susde_dn", "lrt_carry", "leverage_loop")}
        best_pde_calmar = -float("inf")
        for d_start, d_full in [(0.01, 0.06), (0.02, 0.08), (0.02, 0.06), (0.03, 0.10)]:
            port, _ = _mod.apply_pde_portfolio(books, d_start=d_start, d_full=d_full, roundtrip=0.0096)
            c = _mod._calmar(port)
            if c > best_pde_calmar:
                best_pde_calmar = c
        bg_port, _ = _mod.apply_binary_guardian_portfolio(books, roundtrip=0.0096)
        binary_calmar = _mod._calmar(bg_port)
        assert best_pde_calmar > binary_calmar
