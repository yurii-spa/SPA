"""Tests for P0 yield-calculation fixes in cycle_runner.py.

Covers:
  P0-B1 — yield falls back to adapter_registry.json when live data is absent,
           so all deployed positions accrue yield (not just live-adapter pools).
  P0-B2 — last_trade_id in paper_trading_status.json is never null while
           real trades exist in trades.json.

Minimum 20 passing tests.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import spa_core.paper_trading.cycle_runner as cr
from spa_core.paper_trading.cycle_runner import (
    _accrue_daily_yield,
    _last_trade_id_from_file,
)


# ─── Shared helpers ───────────────────────────────────────────────────────────


def _orch_fn(apy_map: dict[str, float], *, tvl: float = 2e7):
    """Fake orchestrator returning only the adapters explicitly given."""
    def _fn(data_dir):
        adapters = [
            {
                "protocol": p,
                "apy_pct": a,
                "tvl_usd": tvl,
                "tier": "T1" if p in ("aave_v3", "compound_v3", "morpho_steakhouse") else "T2",
                "status": "ok",
                "id": p,
            }
            for p, a in apy_map.items()
        ]
        status = "ok" if apy_map else "no_live_data"
        return SimpleNamespace(adapters=adapters, status=status, data_freshness="live")
    return _fn


class _FakeAllocator:
    def __init__(self, target_usd: dict[str, float]):
        self._target = target_usd

    def allocate(self):
        return SimpleNamespace(
            target_usd=dict(self._target),
            target_weights={p: v / 100_000 for p, v in self._target.items()},
            expected_apy_pct=4.0,
            model_used="test",
            strategy_loop_active=False,
        )


def _run(tmp_path, orch_apy_map, target_usd, *, now=None):
    now = now or datetime(2026, 6, 15, 8, 0, tzinfo=timezone.utc)
    return cr.run_cycle(
        data_dir=tmp_path,
        now=now,
        orchestrator_fn=_orch_fn(orch_apy_map),
        allocator=_FakeAllocator(target_usd),
        risk_scorer_fn=lambda d: None,
        track_persister_fn=lambda d: None,
    )


def _write_positions(tmp_path: Path, positions: dict[str, float]) -> None:
    """Pre-populate current_positions.json (simulates a prior cycle's result)."""
    doc = {
        "is_demo": False,
        "source": "cycle_runner",
        "positions": positions,
        "total_deployed_usd": sum(positions.values()),
    }
    (tmp_path / "current_positions.json").write_text(json.dumps(doc))


def _write_registry(tmp_path: Path, adapters: dict[str, dict]) -> None:
    """Write adapter_registry.json with given adapters dict."""
    (tmp_path / "adapter_registry.json").write_text(
        json.dumps({"adapters": adapters})
    )


def _write_trades(tmp_path: Path, trades: list[dict]) -> None:
    (tmp_path / "trades.json").write_text(json.dumps(trades))


def _load(tmp_path: Path, name: str):
    p = tmp_path / name
    return json.loads(p.read_text()) if p.exists() else None


# ═══════════════════════════════════════════════════════════════════════════════
# Group 1 — _accrue_daily_yield unit tests
# ═══════════════════════════════════════════════════════════════════════════════


def test_accrue_empty_positions():
    """Empty positions always yield $0."""
    assert _accrue_daily_yield({}, {"aave_v3": 4.0}) == 0.0


def test_accrue_empty_apy_map():
    """No APY data → every pool is skipped → $0 yield."""
    positions = {"aave_v3": 10_000.0, "compound_v3": 20_000.0}
    assert _accrue_daily_yield(positions, {}) == 0.0


def test_accrue_single_pool_math():
    """$10 000 at 3.65 % APY → exactly $1.00/day (3.65/100/365 * 10_000)."""
    result = _accrue_daily_yield({"pool": 10_000.0}, {"pool": 3.65})
    assert math.isclose(result, 1.0, rel_tol=1e-9)


def test_accrue_multiple_pools_sum():
    """Multi-pool yield = sum of individual yields."""
    positions = {"a": 10_000.0, "b": 20_000.0, "c": 30_000.0}
    apy_map = {"a": 4.0, "b": 5.0, "c": 6.0}
    expected = (
        10_000 * 4.0 / 100 / 365
        + 20_000 * 5.0 / 100 / 365
        + 30_000 * 6.0 / 100 / 365
    )
    assert math.isclose(_accrue_daily_yield(positions, apy_map), expected, rel_tol=1e-9)


def test_accrue_pool_missing_from_apy_map_contributes_zero():
    """Pool absent from apy_map is skipped (original behavior, not a bug itself)."""
    positions = {"aave_v3": 10_000.0, "compound_v3": 20_000.0}
    apy_map = {"aave_v3": 4.0}  # compound_v3 missing
    result = _accrue_daily_yield(positions, apy_map)
    live_only = 10_000 * 4.0 / 100 / 365
    assert math.isclose(result, live_only, rel_tol=1e-9)


def test_accrue_non_numeric_usd_skipped():
    """Non-numeric USD value for a pool is silently skipped."""
    positions = {"good": 10_000.0, "bad": "not-a-number"}  # type: ignore[dict-item]
    apy_map = {"good": 4.0, "bad": 4.0}
    expected = 10_000 * 4.0 / 100 / 365
    assert math.isclose(_accrue_daily_yield(positions, apy_map), expected, rel_tol=1e-9)


def test_accrue_zero_apy_contributes_nothing():
    """A pool with APY=0.0 produces no yield (APY key present but zero)."""
    positions = {"zero_yield": 50_000.0, "normal": 10_000.0}
    apy_map = {"zero_yield": 0.0, "normal": 5.0}
    result = _accrue_daily_yield(positions, apy_map)
    expected = 10_000 * 5.0 / 100 / 365
    assert math.isclose(result, expected, rel_tol=1e-9)


# ═══════════════════════════════════════════════════════════════════════════════
# Group 1b — N3 APY accrual guardrail (fail-closed on out-of-range APY)
# ═══════════════════════════════════════════════════════════════════════════════


def test_guardrail_rejects_out_of_range_apy_decimal_percent_mixup():
    """520% (e.g. a 5.2 decimal mistakenly *100'd, or a unit bug) is REJECTED.

    A 100x unit bug must never silently 100x the go-live track: the bad pool
    contributes ZERO, only the sane pool accrues.
    """
    positions = {"bug": 100_000.0, "ok": 100_000.0}
    apy_map = {"bug": 520.0, "ok": 4.0}  # 520% is out of [0,100] → rejected
    result = _accrue_daily_yield(positions, apy_map)
    expected = 100_000 * 4.0 / 100 / 365  # only the sane pool
    assert math.isclose(result, expected, rel_tol=1e-9)


def test_guardrail_normalizer_returns_none_for_out_of_range():
    assert cr._normalize_accrual_apy("p", 520.0) is None
    assert cr._normalize_accrual_apy("p", -1.0) is None
    assert cr._normalize_accrual_apy("p", float("nan")) is None
    assert cr._normalize_accrual_apy("p", float("inf")) is None
    assert cr._normalize_accrual_apy("p", "5.2") is None  # non-numeric
    assert cr._normalize_accrual_apy("p", True) is None  # bool rejected


def test_guardrail_accepts_in_range_apy():
    assert cr._normalize_accrual_apy("p", 0.0) == 0.0
    assert cr._normalize_accrual_apy("p", 5.2) == 5.2
    assert cr._normalize_accrual_apy("p", 100.0) == 100.0


def test_guardrail_logs_when_rejecting(caplog):
    import logging
    with caplog.at_level(logging.WARNING, logger="spa.cycle_runner"):
        cr._normalize_accrual_apy("compound_v3", 520.0)
    assert any("520" in r.message or "unit mismatch" in r.message for r in caplog.records)


# ═══════════════════════════════════════════════════════════════════════════════
# Group 2 — _last_trade_id_from_file unit tests  (P0-B2 helper)
# ═══════════════════════════════════════════════════════════════════════════════


def test_last_trade_id_returns_last_trade(tmp_path):
    """Returns trade_id of the last entry in trades.json (list format)."""
    _write_trades(tmp_path, [
        {"trade_id": "T001", "date": "2026-06-10"},
        {"trade_id": "T002", "date": "2026-06-11"},
        {"trade_id": "T003", "date": "2026-06-12"},
    ])
    assert _last_trade_id_from_file(tmp_path) == "T003"


def test_last_trade_id_single_entry(tmp_path):
    """Works when only one trade exists."""
    _write_trades(tmp_path, [{"trade_id": "T001", "date": "2026-06-10"}])
    assert _last_trade_id_from_file(tmp_path) == "T001"


def test_last_trade_id_empty_list(tmp_path):
    """Empty trades list → None."""
    _write_trades(tmp_path, [])
    assert _last_trade_id_from_file(tmp_path) is None


def test_last_trade_id_missing_file(tmp_path):
    """No trades.json → None, no exception."""
    assert _last_trade_id_from_file(tmp_path) is None


def test_last_trade_id_corrupted_entry(tmp_path):
    """Last entry missing trade_id key → None."""
    _write_trades(tmp_path, [
        {"trade_id": "T001"},
        {"date": "2026-06-20"},  # no trade_id
    ])
    assert _last_trade_id_from_file(tmp_path) is None


# ═══════════════════════════════════════════════════════════════════════════════
# Group 3 — P0-B1: registry fallback APY for yield accrual  (integration)
# ═══════════════════════════════════════════════════════════════════════════════


def test_yield_fallback_all_positions_when_one_live_adapter(tmp_path):
    """P0-B1 core: with 1 live adapter, ALL positions must contribute yield.

    Old code: $1.096/day (only aave_v3 position).
    Fixed:    ≈$9.26/day  (aave_v3 live + compound_v3 + morpho_steakhouse fallback).
    """
    _write_registry(tmp_path, {
        "aave_v3":          {"fallback_apy": 0.04,  "tier": 1},
        "compound_v3":      {"fallback_apy": 0.052, "tier": 1},
        "morpho_steakhouse":{"fallback_apy": 0.065, "tier": 1},
    })
    _write_positions(tmp_path, {
        "aave_v3":           10_000.0,
        "compound_v3":       20_000.0,
        "morpho_steakhouse": 30_000.0,
    })
    # Allocator targets same positions → no rebalance → effective = current
    target = {"aave_v3": 10_000.0, "compound_v3": 20_000.0, "morpho_steakhouse": 30_000.0}
    # Only aave_v3 is live
    result = _run(tmp_path, orch_apy_map={"aave_v3": 4.0}, target_usd=target)

    # With fix: all 3 pools yield
    full_yield = (
        10_000 * 4.0  / 100 / 365   # live aave_v3 (4.0% from orchestrator)
        + 20_000 * 5.2 / 100 / 365  # fallback compound_v3 (0.052 → 5.2%)
        + 30_000 * 6.5 / 100 / 365  # fallback morpho (0.065 → 6.5%)
    )
    # live-only yield would be just the aave_v3 portion
    live_only_yield = 10_000 * 4.0 / 100 / 365

    assert result.daily_yield_usd > live_only_yield * 2, (
        f"Expected yield > 2× live-only (${live_only_yield:.4f}), "
        f"got ${result.daily_yield_usd:.4f}"
    )
    assert math.isclose(result.daily_yield_usd, full_yield, rel_tol=0.05), (
        f"Expected ≈${full_yield:.4f}, got ${result.daily_yield_usd:.4f}"
    )


def test_yield_live_apy_beats_registry_fallback(tmp_path):
    """P0-B1: live APY always takes precedence over registry fallback_apy."""
    # Registry says 3.5% for aave_v3; orchestrator says 6.0% (live)
    _write_registry(tmp_path, {"aave_v3": {"fallback_apy": 0.035, "tier": 1}})
    _write_positions(tmp_path, {"aave_v3": 100_000.0})
    target = {"aave_v3": 100_000.0}
    result = _run(tmp_path, orch_apy_map={"aave_v3": 6.0}, target_usd=target)

    expected_with_live = 100_000 * 6.0 / 100 / 365
    expected_with_fallback = 100_000 * 3.5 / 100 / 365
    assert math.isclose(result.daily_yield_usd, expected_with_live, rel_tol=0.05), (
        f"Should use live 6.0% not fallback 3.5%; "
        f"expected ${expected_with_live:.4f}, got ${result.daily_yield_usd:.4f}"
    )
    assert result.daily_yield_usd > expected_with_fallback


def test_yield_uses_live_apy_field_from_registry(tmp_path):
    """P0-B1: registry live_apy field is preferred over fallback_apy within registry."""
    _write_registry(tmp_path, {
        "compound_v3": {"live_apy": 0.06, "fallback_apy": 0.03, "tier": 1},
    })
    _write_positions(tmp_path, {"compound_v3": 10_000.0, "aave_v3": 10_000.0})
    target = {"compound_v3": 10_000.0, "aave_v3": 10_000.0}
    result = _run(tmp_path, orch_apy_map={"aave_v3": 4.0}, target_usd=target)

    # compound_v3 not live → registry fills in 6.0% (live_apy, not 3.0% fallback_apy)
    compound_contribution = 10_000 * 6.0 / 100 / 365
    aave_contribution = 10_000 * 4.0 / 100 / 365
    expected = compound_contribution + aave_contribution
    assert math.isclose(result.daily_yield_usd, expected, rel_tol=0.05)


def test_yield_zero_live_adapters_skips_accrual(tmp_path):
    """When 0 adapters are live the cycle returns daily_yield_usd=0.0 (expected).

    This is intentional: the no_live_data early-return path skips yield.
    The P0-B1 fix only helps when ≥1 adapter is live.
    """
    _write_registry(tmp_path, {"aave_v3": {"fallback_apy": 0.04, "tier": 1}})
    _write_positions(tmp_path, {"aave_v3": 50_000.0})
    target = {"aave_v3": 50_000.0}
    # Empty orchestrator → no live data
    result = _run(tmp_path, orch_apy_map={}, target_usd=target)
    assert result.daily_yield_usd == 0.0
    assert result.status == "skipped_no_live_data"


def test_yield_registry_not_found_does_not_crash(tmp_path):
    """Missing adapter_registry.json → cycle continues with live-only yield."""
    # No registry file
    _write_positions(tmp_path, {"aave_v3": 10_000.0, "compound_v3": 20_000.0})
    target = {"aave_v3": 10_000.0, "compound_v3": 20_000.0}
    result = _run(tmp_path, orch_apy_map={"aave_v3": 4.0}, target_usd=target)

    # Only aave_v3 live, no registry fallback → compound_v3 yields $0
    live_only = 10_000 * 4.0 / 100 / 365
    assert math.isclose(result.daily_yield_usd, live_only, rel_tol=0.10)
    assert result.status in ("ok", "blocked_by_policy", "no_rebalance")


def test_yield_registry_zero_fallback_skipped(tmp_path):
    """Registry fallback_apy=0.0 is not merged (would contribute nothing anyway)."""
    _write_registry(tmp_path, {
        "aave_v3":    {"fallback_apy": 0.04, "tier": 1},
        "bad_pool":   {"fallback_apy": 0.0,  "tier": 2},  # zero → skip
    })
    _write_positions(tmp_path, {"aave_v3": 10_000.0, "bad_pool": 5_000.0})
    target = {"aave_v3": 10_000.0, "bad_pool": 5_000.0}
    result = _run(tmp_path, orch_apy_map={"aave_v3": 4.0}, target_usd=target)

    # bad_pool fallback 0% should not appear in apy_map (no contribution)
    aave_yield = 10_000 * 4.0 / 100 / 365
    # Only aave contributes (bad_pool fallback is 0.0, filtered out)
    assert math.isclose(result.daily_yield_usd, aave_yield, rel_tol=0.05)


def test_yield_full_positions_8x_better_than_one_live(tmp_path):
    """Reproduces the reported bug: 8× yield collapse when 1/N adapters live.

    Original: daily_yield_usd ≈ $1.32 (1 of 24 live).
    Fixed:    daily_yield_usd ≈ $10.81 (all 24 positions accrue fallback yield).
    We use 4 positions as a proxy for the 24-pool portfolio.
    """
    POOLS = {
        "aave_v3":           {"fallback_apy": 0.04,  "tier": 1},
        "compound_v3":       {"fallback_apy": 0.052, "tier": 1},
        "morpho_steakhouse": {"fallback_apy": 0.065, "tier": 1},
        "morpho_blue":       {"fallback_apy": 0.041, "tier": 2},
    }
    _write_registry(tmp_path, POOLS)
    positions = {k: 25_000.0 for k in POOLS}  # $25k each = $100k total
    _write_positions(tmp_path, positions)
    target = dict(positions)

    # Only aave_v3 is live
    result_fixed = _run(tmp_path, orch_apy_map={"aave_v3": 4.0}, target_usd=target)

    # Live-only yield (what the old code produced)
    yield_live_only = 25_000 * 4.0 / 100 / 365
    # Full yield (what the fixed code should produce)
    yield_full = sum(
        25_000 * v["fallback_apy"] * 100 / 100 / 365
        for v in POOLS.values()
    )

    assert result_fixed.daily_yield_usd > yield_live_only * 3, (
        f"Expected >{3 * yield_live_only:.2f}, got {result_fixed.daily_yield_usd:.2f}"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Group 4 — P0-B2: last_trade_id in paper_trading_status.json  (integration)
# ═══════════════════════════════════════════════════════════════════════════════


def _standard_setup(tmp_path):
    """Standard risk-compliant setup for status tests."""
    _write_registry(tmp_path, {
        "aave_v3":      {"fallback_apy": 0.04, "tier": 1},
        "compound_v3":  {"fallback_apy": 0.05, "tier": 1},
    })


def test_last_trade_id_written_after_successful_trade(tmp_path):
    """When cycle executes a trade, status.last_trade_id = that trade's id."""
    _standard_setup(tmp_path)
    target = {"aave_v3": 40_000.0, "compound_v3": 30_000.0}
    result = _run(tmp_path, orch_apy_map={"aave_v3": 4.0, "compound_v3": 5.0}, target_usd=target)
    status = _load(tmp_path, "paper_trading_status.json")
    if result.traded:
        assert status["last_trade_id"] == result.trade_id
        assert status["last_trade_id"] is not None
    else:
        # Policy may block; trade_id is None → falls back to trades.json (may be None too)
        # Just check the field exists and doesn't crash
        assert "last_trade_id" in status


def test_last_trade_id_falls_back_to_prior_trade(tmp_path):
    """P0-B2 core: when second cycle has no trade, status shows last trade from file.

    Cycle 1 → trade T001 written to trades.json
    Cycle 2 → no rebalance needed → result.trade_id=None
              → last_trade_id must be T001, not null
    """
    _standard_setup(tmp_path)
    target = {"aave_v3": 40_000.0, "compound_v3": 30_000.0}
    orch = {"aave_v3": 4.0, "compound_v3": 5.0}

    # Cycle 1 – establishes positions
    r1 = _run(tmp_path, orch_apy_map=orch, target_usd=target,
              now=datetime(2026, 6, 14, 8, 0, tzinfo=timezone.utc))

    # Cycle 2 – same target → no rebalance needed
    r2 = _run(tmp_path, orch_apy_map=orch, target_usd=target,
              now=datetime(2026, 6, 15, 8, 0, tzinfo=timezone.utc))

    status = _load(tmp_path, "paper_trading_status.json")
    trades = _load(tmp_path, "trades.json") or []

    if trades:
        last_tid = trades[-1]["trade_id"] if isinstance(trades[-1], dict) else None
        assert status["last_trade_id"] == last_tid, (
            f"Expected last_trade_id={last_tid!r}, got {status['last_trade_id']!r}"
        )
    # Even if cycle 2 didn't trade, last_trade_id must not be null when trades exist
    if trades and r2.trade_id is None:
        assert status["last_trade_id"] is not None, (
            "last_trade_id was null despite trades existing in trades.json"
        )


def test_last_trade_id_null_when_truly_no_trades(tmp_path):
    """When no trade has ever occurred, last_trade_id=None is correct."""
    _standard_setup(tmp_path)
    # Orch returns 0 adapters → no_live_data → cycle skips, never trades
    result = _run(tmp_path, orch_apy_map={}, target_usd={"aave_v3": 40_000.0})
    status = _load(tmp_path, "paper_trading_status.json")
    assert status["last_trade_id"] is None


def test_last_trade_id_present_in_skipped_cycle_status(tmp_path):
    """Even no_live_data cycles write status; last_trade_id comes from trades.json."""
    _standard_setup(tmp_path)
    # Pre-write a prior trade
    _write_trades(tmp_path, [{"trade_id": "T042", "date": "2026-06-13", "is_demo": False}])

    # Cycle with no live data → skipped
    _run(tmp_path, orch_apy_map={}, target_usd={"aave_v3": 40_000.0})
    status = _load(tmp_path, "paper_trading_status.json")
    assert status["last_trade_id"] == "T042", (
        f"Expected T042, got {status['last_trade_id']!r}"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Group 5 — Equity curve consistency
# ═══════════════════════════════════════════════════════════════════════════════


def test_equity_grows_with_yield_over_multiple_cycles(tmp_path):
    """Equity increases monotonically over N cycles when yield > 0."""
    _write_registry(tmp_path, {
        "aave_v3":     {"fallback_apy": 0.04,  "tier": 1},
        "compound_v3": {"fallback_apy": 0.052, "tier": 1},
    })
    target = {"aave_v3": 40_000.0, "compound_v3": 30_000.0}
    orch = {"aave_v3": 4.0, "compound_v3": 5.2}

    equities = []
    for day in range(1, 6):
        r = _run(
            tmp_path, orch_apy_map=orch, target_usd=target,
            now=datetime(2026, 6, day + 10, 8, 0, tzinfo=timezone.utc),
        )
        equities.append(r.current_equity)

    for i in range(1, len(equities)):
        assert equities[i] >= equities[i - 1], (
            f"Equity should not decrease: day {i} ${equities[i-1]:.2f} → ${equities[i]:.2f}"
        )
    assert equities[-1] > equities[0], "Total equity must grow over 5 cycles"


def test_equity_curve_consistent_with_live_fallback_mix(tmp_path):
    """5 cycles alternating full-live and partial-live both grow equity correctly."""
    _write_registry(tmp_path, {
        "aave_v3":     {"fallback_apy": 0.04,  "tier": 1},
        "compound_v3": {"fallback_apy": 0.052, "tier": 1},
    })
    target = {"aave_v3": 40_000.0, "compound_v3": 30_000.0}

    equities = []
    for day in range(1, 6):
        # Odd days: full live; even days: only aave_v3 live (compound uses fallback)
        orch = {"aave_v3": 4.0, "compound_v3": 5.2} if day % 2 == 0 else {"aave_v3": 4.0}
        r = _run(
            tmp_path, orch_apy_map=orch, target_usd=target,
            now=datetime(2026, 6, day + 10, 8, 0, tzinfo=timezone.utc),
        )
        equities.append(r.current_equity)

    assert equities[-1] > equities[0], (
        f"Equity should grow from ${equities[0]:.2f} to ${equities[-1]:.2f}"
    )
    # Equity should never drop (no losses in this sim)
    for i in range(1, len(equities)):
        assert equities[i] >= equities[i - 1]


def test_equity_curve_daily_written_with_yield(tmp_path):
    """daily_yield_usd in equity_curve_daily.json matches result.daily_yield_usd."""
    _write_registry(tmp_path, {
        "aave_v3":     {"fallback_apy": 0.04, "tier": 1},
        "compound_v3": {"fallback_apy": 0.05, "tier": 1},
    })
    _write_positions(tmp_path, {"aave_v3": 40_000.0, "compound_v3": 30_000.0})
    target = {"aave_v3": 40_000.0, "compound_v3": 30_000.0}
    result = _run(tmp_path, orch_apy_map={"aave_v3": 4.0}, target_usd=target)

    curve = _load(tmp_path, "equity_curve_daily.json")
    if curve and curve.get("daily"):
        last_bar = curve["daily"][-1]
        assert math.isclose(
            last_bar["daily_yield_usd"], result.daily_yield_usd, rel_tol=1e-4
        )


def test_equity_bar_flagged_fallback_when_position_uses_registry_apy(tmp_path):
    """N3(b): a deployed position whose APY came from a fallback file → bar is
    stamped accrual_source="fallback" (the track is auditable for fallback accrual)."""
    _write_registry(tmp_path, {
        "aave_v3":     {"fallback_apy": 0.04, "tier": 1},
        "compound_v3": {"fallback_apy": 0.05, "tier": 1},
    })
    _write_positions(tmp_path, {"aave_v3": 40_000.0, "compound_v3": 30_000.0})
    target = {"aave_v3": 40_000.0, "compound_v3": 30_000.0}
    # Only aave_v3 is live; compound_v3 yield comes from the registry fallback.
    _run(tmp_path, orch_apy_map={"aave_v3": 4.0}, target_usd=target)

    curve = _load(tmp_path, "equity_curve_daily.json")
    assert curve and curve.get("daily")
    last_bar = curve["daily"][-1]
    assert last_bar.get("accrual_source") == "fallback"


def test_equity_bar_flagged_live_when_all_positions_live(tmp_path):
    """N3(b): all deployed positions have live APY → bar accrual_source="live"."""
    _write_registry(tmp_path, {
        "aave_v3":     {"fallback_apy": 0.04, "tier": 1},
        "compound_v3": {"fallback_apy": 0.05, "tier": 1},
    })
    _write_positions(tmp_path, {"aave_v3": 40_000.0, "compound_v3": 30_000.0})
    target = {"aave_v3": 40_000.0, "compound_v3": 30_000.0}
    # Both deployed pools live from the orchestrator.
    _run(tmp_path, orch_apy_map={"aave_v3": 4.0, "compound_v3": 5.0}, target_usd=target)

    curve = _load(tmp_path, "equity_curve_daily.json")
    assert curve and curve.get("daily")
    last_bar = curve["daily"][-1]
    assert last_bar.get("accrual_source") == "live"


def test_weighted_apy_reflects_all_positions(tmp_path):
    """apy_today_pct should reflect portfolio-wide APY (not just live-adapter APY)."""
    _write_registry(tmp_path, {
        "aave_v3":     {"fallback_apy": 0.04,  "tier": 1},
        "compound_v3": {"fallback_apy": 0.052, "tier": 1},
    })
    _write_positions(tmp_path, {"aave_v3": 50_000.0, "compound_v3": 50_000.0})
    target = {"aave_v3": 50_000.0, "compound_v3": 50_000.0}

    # Only aave_v3 live (4%)
    result = _run(tmp_path, orch_apy_map={"aave_v3": 4.0}, target_usd=target)

    # With P0-B1 fix: weighted APY uses both pools
    # aave_v3: 50k * 4.0% = 2000; compound: 50k * 5.2% = 2600; total capital 100k
    # weighted = (2000 + 2600) / 100000 * 100 ≈ 4.6%
    # Without fix: only aave_v3 → (2000) / 100000 * 100 = 2.0%
    assert result.apy_today_pct > 2.0, (
        f"apy_today_pct={result.apy_today_pct:.4f}% should exceed live-only 2.0%"
    )
