"""Tests for the go-live anti-demo gate (MP-006).

Every test builds its own data dir under ``tmp_path`` with a frozen ``now``,
so the suite is fully deterministic and never touches the real ``data/``.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from spa_core.paper_trading import cycle_runner as cr
from spa_core.paper_trading.golive_checker import GoLiveChecker, GoLiveResult

NOW = datetime(2026, 6, 10, 12, 0, tzinfo=timezone.utc)


# ─── Fixture helpers ──────────────────────────────────────────────────────────


def _write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj), encoding="utf-8")


def _equity_doc(dates=("2026-06-09", "2026-06-10"), is_demo=False):
    return {
        "generated_at": NOW.isoformat(),
        "source": "cycle_runner",
        "is_demo": is_demo,
        "summary": {"num_days": len(dates)},
        "daily": [
            {"date": d, "open_equity": 100_000.0, "close_equity": 100_010.0}
            for d in dates
        ],
    }


def _trades(n=1, is_demo=False):
    return [
        {"trade_id": f"T{i + 1:03d}", "ts": NOW.isoformat(), "is_demo": is_demo}
        for i in range(n)
    ]


def _make_data_dir(tmp_path, **overrides):
    """A data dir where all six criteria pass; overrides patch single files."""
    ddir = tmp_path / "data"
    docs = {
        "equity_curve_daily.json": _equity_doc(),
        "trades.json": _trades(),
        "paper_trading_status.json": {"is_demo": False, "source": "cycle_runner"},
    }
    docs.update(overrides)
    for name, doc in docs.items():
        if doc is not None:  # None → omit the file entirely
            _write(ddir / name, doc)
    return ddir


def _check(ddir, *, now=NOW, **kw):
    return GoLiveChecker(data_dir=ddir, now=now, **kw).check()


# ─── Criteria tests ───────────────────────────────────────────────────────────


def test_all_checks_pass(tmp_path):
    result = _check(_make_data_dir(tmp_path))
    assert isinstance(result, GoLiveResult)
    assert result.ready is True
    assert result.blockers == []
    assert set(result.checks) == {
        "equity_curve_real",
        "trades_real",
        "status_real",
        "no_demo_data",
        "data_fresh_48h",
        "cycle_runner_exists",
    }
    assert all(result.checks.values())
    assert result.timestamp == NOW.isoformat()


def test_no_equity_curve(tmp_path):
    ddir = _make_data_dir(tmp_path, **{"equity_curve_daily.json": None})
    result = _check(ddir)
    assert result.ready is False
    assert result.checks["equity_curve_real"] is False
    assert result.checks["data_fresh_48h"] is False  # nothing to assess either
    assert any("equity_curve_daily.json" in b for b in result.blockers)


def test_demo_data_present(tmp_path):
    ddir = _make_data_dir(tmp_path)
    _write(ddir / "pnl_history.json", {"is_demo": True, "daily": []})
    result = _check(ddir)
    assert result.ready is False
    assert result.checks["no_demo_data"] is False
    assert any("pnl_history.json" in b for b in result.blockers)


def test_demo_flag_nested_deep_is_detected(tmp_path):
    ddir = _make_data_dir(tmp_path)
    _write(ddir / "report.json", {"sections": [{"meta": {"is_demo": True}}]})
    result = _check(ddir)
    assert result.checks["no_demo_data"] is False


def test_fresh_data_check(tmp_path):
    # Last record 2026-06-07 → ≥48h old at NOW (2026-06-10) → stale.
    ddir = _make_data_dir(
        tmp_path,
        **{"equity_curve_daily.json": _equity_doc(dates=("2026-06-06", "2026-06-07"))},
    )
    result = _check(ddir)
    assert result.ready is False
    assert result.checks["data_fresh_48h"] is False
    assert result.checks["equity_curve_real"] is True  # the curve itself is fine
    assert any("stalled" in b for b in result.blockers)


def test_fresh_data_yesterday_passes(tmp_path):
    # Yesterday's bar is < 48h old → fresh.
    ddir = _make_data_dir(
        tmp_path,
        **{"equity_curve_daily.json": _equity_doc(dates=("2026-06-09",))},
    )
    assert _check(ddir).checks["data_fresh_48h"] is True


def test_no_real_trades(tmp_path):
    ddir = _make_data_dir(tmp_path, **{"trades.json": []})
    result = _check(ddir)
    assert result.ready is False
    assert result.checks["trades_real"] is False
    assert any("trades.json" in b for b in result.blockers)


def test_demo_only_trades_fail_two_checks(tmp_path):
    ddir = _make_data_dir(tmp_path, **{"trades.json": _trades(3, is_demo=True)})
    result = _check(ddir)
    assert result.checks["trades_real"] is False  # no is_demo:false trade
    assert result.checks["no_demo_data"] is False  # and the file carries demo data


def test_status_missing_or_demo(tmp_path):
    ddir = _make_data_dir(tmp_path, **{"paper_trading_status.json": None})
    assert _check(ddir).checks["status_real"] is False

    ddir2 = _make_data_dir(tmp_path / "b", **{"paper_trading_status.json": {"is_demo": True}})
    result = _check(ddir2)
    assert result.checks["status_real"] is False
    assert result.checks["no_demo_data"] is False


def test_cycle_runner_missing(tmp_path):
    # An empty repo_root has no spa_core/paper_trading/cycle_runner.py.
    result = GoLiveChecker(
        data_dir=_make_data_dir(tmp_path), repo_root=tmp_path / "empty_repo", now=NOW
    ).check()
    assert result.ready is False
    assert result.checks["cycle_runner_exists"] is False
    assert any("cycle_runner" in b for b in result.blockers)


def test_corrupt_json_is_blocker_not_crash(tmp_path):
    ddir = _make_data_dir(tmp_path)
    (ddir / "equity_curve_daily.json").write_text("{not json", encoding="utf-8")
    result = _check(ddir)  # must not raise
    assert result.ready is False
    assert result.checks["equity_curve_real"] is False


# ─── Persistence & reporting ─────────────────────────────────────────────────


def test_writes_golive_status_json(tmp_path):
    ddir = _make_data_dir(tmp_path)
    result = _check(ddir)
    out = json.loads((ddir / "golive_status.json").read_text(encoding="utf-8"))
    assert out == result.to_dict()
    assert out["ready"] is True
    assert out["source"] == "golive_checker"
    # Own output is excluded from the demo scan — a re-check stays green.
    assert _check(ddir).ready is True


def test_dry_run_writes_nothing(tmp_path):
    ddir = _make_data_dir(tmp_path)
    GoLiveChecker(data_dir=ddir, now=NOW).check(write=False)
    assert not (ddir / "golive_status.json").exists()


def test_summary_contains_blockers_and_verdict(tmp_path):
    ddir = _make_data_dir(tmp_path, **{"trades.json": []})
    text = _check(ddir).summary()
    assert "NOT READY" in text
    assert "trades.json" in text
    assert "[FAIL] trades_real" in text
    assert "[PASS] status_real" in text

    ok_text = _check(_make_data_dir(tmp_path / "ok")).summary()
    assert "verdict: READY" in ok_text


# ─── cycle_runner integration ────────────────────────────────────────────────


def _run_cycle(tmp_path, **kw):
    """One minimal real cycle with fakes (mirrors test_cycle_runner.py)."""
    adapters = [
        {"protocol": "aave_v3", "apy_pct": 4.0, "tvl_usd": 1e7, "tier": "T1", "status": "ok"}
    ]
    orch = SimpleNamespace(adapters=adapters, status="ok")
    allocator = SimpleNamespace(
        allocate=lambda: SimpleNamespace(
            target_usd={"aave_v3": 30_000.0},
            expected_apy_pct=4.0,
            model_used="fake",
            strategy_loop_active=False,
        )
    )
    return cr.run_cycle(
        data_dir=tmp_path,
        now=NOW,
        orchestrator_fn=lambda d: orch,
        allocator=allocator,
        # MP-012: no-op risk scorer keeps these tests network-free.
        risk_scorer_fn=lambda d: None,
        # MP-109: no-op track persister keeps these tests off iCloud/home dirs.
        track_persister_fn=lambda d: None,
        **kw,
    )


def test_cycle_runner_writes_golive_status(tmp_path):
    result = _run_cycle(tmp_path)
    assert result.status == "ok"  # the gate never blocks the cycle
    out = json.loads((tmp_path / "golive_status.json").read_text(encoding="utf-8"))
    assert out["source"] == "golive_checker"
    # First-ever cycle: status checked BEFORE files exist → honestly not ready.
    assert out["ready"] is False


def test_cycle_runner_logs_warning_once_per_day(tmp_path, caplog):
    with caplog.at_level(logging.WARNING, logger="spa.cycle_runner"):
        _run_cycle(tmp_path)
    assert any("Go-live NOT ready" in r.getMessage() for r in caplog.records)

    caplog.clear()  # second run same day → no repeat WARNING
    with caplog.at_level(logging.WARNING, logger="spa.cycle_runner"):
        _run_cycle(tmp_path)
    assert not any("Go-live NOT ready" in r.getMessage() for r in caplog.records)


def test_cycle_runner_dry_run_does_not_write_status(tmp_path):
    _run_cycle(tmp_path, write=False)
    assert not (tmp_path / "golive_status.json").exists()
