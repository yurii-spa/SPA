"""Tests for the real paper-trading cycle runner (SPA-V409).

The orchestrator and allocator are injected as in-process fakes so the suite is
fully deterministic and hits no network / no real adapters.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from spa_core.paper_trading import cycle_runner as cr


# ─── Fakes ────────────────────────────────────────────────────────────────────


def _fake_orch_result(apy_map, status="ok"):
    # aave_v3 is the T1 anchor (как в реальном снимке оркестратора); остальные T2.
    adapters = [
        {
            "protocol": p,
            "apy_pct": a,
            "tvl_usd": 1e7,
            "tier": "T1" if p == "aave_v3" else "T2",
            "status": "ok",
        }
        for p, a in apy_map.items()
    ]
    return SimpleNamespace(adapters=adapters, status=status, data_freshness="live")


def _orch_fn(apy_map, status="ok"):
    def _fn(data_dir):
        return _fake_orch_result(apy_map, status=status)

    return _fn


class _FakeAllocator:
    def __init__(self, target_usd, model="risk_adjusted", strategy_loop=False):
        self._target = target_usd
        self._model = model
        self._loop = strategy_loop

    def allocate(self):
        return SimpleNamespace(
            target_usd=dict(self._target),
            target_weights={p: v / 100_000 for p, v in self._target.items()},
            expected_apy_pct=3.0,
            model_used=self._model,
            strategy_loop_active=self._loop,
        )


def _run(tmp_path, apy_map, target_usd, *, now=None, status="ok", **kw):
    now = now or datetime(2026, 6, 10, 8, 0, tzinfo=timezone.utc)
    return cr.run_cycle(
        data_dir=tmp_path,
        now=now,
        orchestrator_fn=_orch_fn(apy_map, status=status),
        allocator=_FakeAllocator(target_usd, **kw),
    )


def _load(tmp_path, name):
    p = tmp_path / name
    return json.loads(p.read_text()) if p.exists() else None


APY = {"aave_v3": 4.0, "morpho_blue": 5.0, "yearn_v3": 3.0, "maple": 4.7}
# RiskPolicy-compliant target (MP-005): T1 aave 40% (== cap), T2 total 34% < 35%.
TARGET = {"aave_v3": 40000.0, "morpho_blue": 20000.0, "yearn_v3": 14000.0}


# ─── Core loop ──────────────────────────────────────────────────────────────


def test_full_cycle_writes_trade(tmp_path):
    res = _run(tmp_path, APY, TARGET)
    assert res.status == "ok"
    assert res.traded is True
    trades = _load(tmp_path, "trades.json")
    assert len(trades) == 1
    assert trades[0]["trade_id"] == "T001"
    assert trades[0]["type"] == "rebalance"
    assert trades[0]["reason"] == "orchestrator_cycle"
    assert trades[0]["to_allocation"]["aave_v3"] == 40000.0


def test_idempotent_no_trade_when_allocation_unchanged(tmp_path):
    # First cycle establishes positions == target.
    _run(tmp_path, APY, TARGET)
    # Second cycle next day, same target → no new trade.
    res2 = _run(
        tmp_path, APY, TARGET, now=datetime(2026, 6, 11, 8, 0, tzinfo=timezone.utc)
    )
    assert res2.traded is False
    trades = _load(tmp_path, "trades.json")
    assert len(trades) == 1  # still just the first trade


def test_equity_accrues_daily_yield(tmp_path):
    res = _run(tmp_path, APY, TARGET)
    # Expected: Σ pos * apy / 100 / 365.
    expected = sum(TARGET[p] * APY[p] / 100 / 365 for p in TARGET)
    assert res.daily_yield_usd == pytest.approx(expected, abs=1e-3)
    assert res.current_equity == pytest.approx(100_000 + expected, abs=1e-2)


def test_equity_curve_updated(tmp_path):
    _run(tmp_path, APY, TARGET)
    eq = _load(tmp_path, "equity_curve_daily.json")
    assert eq["is_demo"] is False
    assert eq["source"] == "cycle_runner"
    assert len(eq["daily"]) == 1
    bar = eq["daily"][0]
    # prompt-mandated flat fields present.
    assert bar["date"] == "2026-06-10"
    assert "equity" in bar and "apy_today" in bar and "daily_return_pct" in bar
    assert bar["equity"] == bar["close_equity"]


def test_status_is_not_demo(tmp_path):
    _run(tmp_path, APY, TARGET)
    st = _load(tmp_path, "paper_trading_status.json")
    assert st["is_demo"] is False
    assert st["paper_start_date"] == "2026-05-20"
    assert st["strategy_loop_active"] is False
    assert st["last_allocation_model"] == "risk_adjusted"
    assert st["current_positions"]["aave_v3"] == 40000.0


def test_current_positions_written(tmp_path):
    _run(tmp_path, APY, TARGET)
    pos = _load(tmp_path, "current_positions.json")
    assert pos["is_demo"] is False
    assert pos["deployed_usd"] == pytest.approx(74000.0, abs=1e-6)
    assert pos["cash_usd"] == pytest.approx(26000.0, abs=1e-6)
    assert pos["positions"]["morpho_blue"] == 20000.0


# ─── Ring buffers ─────────────────────────────────────────────────────────────


def test_ring_buffer_trades_max_500(tmp_path):
    # Seed 500 existing trades, then a cycle that trades → should cap at 500.
    seed = [{"trade_id": f"T{i:03d}", "type": "rebalance"} for i in range(1, 501)]
    (tmp_path / "trades.json").write_text(json.dumps(seed))
    res = _run(tmp_path, APY, TARGET)
    assert res.traded is True
    trades = _load(tmp_path, "trades.json")
    assert len(trades) == 500
    assert trades[-1]["trade_id"] == "T501"  # newest kept
    assert trades[0]["trade_id"] == "T002"   # oldest dropped


def test_trade_id_increments_from_existing(tmp_path):
    (tmp_path / "trades.json").write_text(
        json.dumps([{"trade_id": "T007", "type": "rebalance"}])
    )
    res = _run(tmp_path, APY, TARGET)
    assert res.trade_id == "T008"


def test_equity_curve_ring_buffer_365(tmp_path):
    # Pre-fill with 365 dummy bars; one more cycle keeps it at 365.
    daily = [
        {
            "date": f"2025-01-{(i % 28) + 1:02d}",
            "open_equity": 100000.0,
            "close_equity": 100000.0,
            "daily_return_pct": 0.0,
        }
        for i in range(365)
    ]
    (tmp_path / "equity_curve_daily.json").write_text(
        json.dumps({"source": "cycle_runner", "daily": daily, "summary": {}})
    )
    _run(tmp_path, APY, TARGET)
    eq = _load(tmp_path, "equity_curve_daily.json")
    assert len(eq["daily"]) == 365
    assert eq["daily"][-1]["date"] == "2026-06-10"


# ─── No-live-data path ────────────────────────────────────────────────────────


def test_graceful_when_orchestrator_returns_no_live_data(tmp_path):
    res = cr.run_cycle(
        data_dir=tmp_path,
        now=datetime(2026, 6, 10, 8, 0, tzinfo=timezone.utc),
        orchestrator_fn=_orch_fn({}, status="no_live_data"),
        allocator=_FakeAllocator(TARGET),
    )
    assert res.status == "skipped_no_live_data"
    assert res.traded is False
    assert res.daily_yield_usd == 0.0
    # No trade written, but status doc still produced honestly.
    assert _load(tmp_path, "trades.json") is None
    st = _load(tmp_path, "paper_trading_status.json")
    assert st["last_cycle_status"] == "skipped_no_live_data"
    assert any("no_live_data" in n for n in st["notes"])


def test_no_live_data_when_status_ok_but_no_apy(tmp_path):
    # status "ok" but adapters carry no usable APY → still treated as no live data.
    res = cr.run_cycle(
        data_dir=tmp_path,
        now=datetime(2026, 6, 10, 8, 0, tzinfo=timezone.utc),
        orchestrator_fn=_orch_fn({}, status="ok"),
        allocator=_FakeAllocator(TARGET),
    )
    assert res.status == "skipped_no_live_data"


# ─── Idempotency / multi-day behaviour ────────────────────────────────────────


def test_same_day_rerun_does_not_double_accrue(tmp_path):
    res1 = _run(tmp_path, APY, TARGET)
    # Re-run same calendar day (later timestamp) → equity bar recomputed, not compounded.
    res2 = _run(
        tmp_path, APY, TARGET, now=datetime(2026, 6, 10, 20, 0, tzinfo=timezone.utc)
    )
    eq = _load(tmp_path, "equity_curve_daily.json")
    assert len(eq["daily"]) == 1  # still one bar for 2026-06-10
    assert res2.current_equity == pytest.approx(res1.current_equity, abs=1e-6)


def test_two_days_compound(tmp_path):
    res1 = _run(tmp_path, APY, TARGET)
    res2 = _run(
        tmp_path, APY, TARGET, now=datetime(2026, 6, 11, 8, 0, tzinfo=timezone.utc)
    )
    eq = _load(tmp_path, "equity_curve_daily.json")
    assert len(eq["daily"]) == 2
    assert res2.current_equity > res1.current_equity  # second day adds more yield
    assert eq["summary"]["num_days"] == 2


def test_days_running_counts_from_paper_start(tmp_path):
    res = _run(
        tmp_path, APY, TARGET, now=datetime(2026, 6, 10, 8, 0, tzinfo=timezone.utc)
    )
    # 2026-05-20 .. 2026-06-10 inclusive = 22 days.
    assert res.days_running == 22


# ─── Allocation diff threshold ────────────────────────────────────────────────


def test_small_allocation_drift_under_threshold_no_trade(tmp_path):
    _run(tmp_path, APY, TARGET)  # positions = TARGET
    # Drift one pool by a tiny amount (< 1% of capital total L1 distance);
    # yearn stays well under its T2 cap so the policy gate keeps approving.
    drifted = {**TARGET, "yearn_v3": TARGET["yearn_v3"] + 300.0}  # L1 = 300 < 1000
    res = _run(
        tmp_path,
        APY,
        drifted,
        now=datetime(2026, 6, 11, 8, 0, tzinfo=timezone.utc),
    )
    assert res.traded is False


def test_large_allocation_change_triggers_trade(tmp_path):
    _run(tmp_path, APY, TARGET)
    changed = {"aave_v3": 40000.0, "maple": 20000.0, "yearn_v3": 14000.0}  # big swap
    res = _run(
        tmp_path,
        APY,
        changed,
        now=datetime(2026, 6, 11, 8, 0, tzinfo=timezone.utc),
    )
    assert res.traded is True
    trades = _load(tmp_path, "trades.json")
    assert len(trades) == 2


# ─── Dry-run & summary integrity ──────────────────────────────────────────────


def test_dry_run_writes_nothing(tmp_path):
    cr.run_cycle(
        data_dir=tmp_path,
        now=datetime(2026, 6, 10, 8, 0, tzinfo=timezone.utc),
        orchestrator_fn=_orch_fn(APY),
        allocator=_FakeAllocator(TARGET),
        write=False,
    )
    assert _load(tmp_path, "trades.json") is None
    assert _load(tmp_path, "equity_curve_daily.json") is None
    assert _load(tmp_path, "paper_trading_status.json") is None


def test_summary_has_golive_compatible_num_days(tmp_path):
    # readiness_checker C005 reads summary.num_days — must remain present.
    _run(tmp_path, APY, TARGET)
    _run(tmp_path, APY, TARGET, now=datetime(2026, 6, 11, 8, 0, tzinfo=timezone.utc))
    eq = _load(tmp_path, "equity_curve_daily.json")
    assert "summary" in eq and "num_days" in eq["summary"]
    assert eq["summary"]["num_days"] == 2
    assert eq["summary"]["positive_days"] >= 1


def test_demo_curve_archived_and_real_curve_starts_at_capital(tmp_path):
    # Simulate a pre-existing DEMO equity curve (source != cycle_runner).
    demo = {
        "source": "equity_curve",
        "is_demo": True,
        "summary": {"num_days": 8, "end_equity": 98815.79},
        "daily": [{"date": "2026-05-22", "open_equity": 99000.0, "close_equity": 98815.79}],
    }
    (tmp_path / "equity_curve_daily.json").write_text(json.dumps(demo))
    res = _run(tmp_path, APY, TARGET)
    # Real curve starts fresh from capital, not the demo's 98,815.79.
    expected_yield = sum(TARGET[p] * APY[p] / 100 / 365 for p in TARGET)
    assert res.current_equity == pytest.approx(100_000 + expected_yield, abs=1e-2)
    eq = _load(tmp_path, "equity_curve_daily.json")
    assert eq["source"] == "cycle_runner"
    assert eq["is_demo"] is False
    assert len(eq["daily"]) == 1
    # Demo file preserved for audit.
    backup = _load(tmp_path, "equity_curve_daily.demo_backup.json")
    assert backup["is_demo"] is True


def test_strategy_loop_flag_propagates(tmp_path):
    res = _run(tmp_path, APY, TARGET, strategy_loop=True)
    assert res.strategy_loop_active is True
    st = _load(tmp_path, "paper_trading_status.json")
    assert st["strategy_loop_active"] is True
    trades = _load(tmp_path, "trades.json")
    assert trades[0]["strategy_loop_active"] is True
