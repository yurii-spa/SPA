"""Tests for the 29-criteria go-live gate (MP-006 / MP-384 / MP-417 / MP-1228).

Every test builds its own isolated data dir and, where needed, a fake home
dir under ``tmp_path`` so no test ever touches real state on disk.
``now`` is frozen at NOW for fully deterministic results.

The synthetic equity histories below predate the real teardown date, so the
helpers inject an early ``paper_start`` (EARLY_PAPER_START) — otherwise the
MP-1228 honesty rule would (correctly) discard those bars as pre-teardown.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from spa_core.paper_trading import cycle_runner as cr
from spa_core.paper_trading.golive_checker import GoLiveChecker, GoLiveResult

NOW = datetime(2026, 6, 10, 12, 0, tzinfo=timezone.utc)
# Early enough that all synthetic May/June fixtures count as honest track days.
EARLY_PAPER_START = datetime(2026, 5, 1, tzinfo=timezone.utc)

# 30 consecutive dates ending the day before NOW → passes freshness + 30d checks
_30D_DATES = [
    (datetime(2026, 5, 11, tzinfo=timezone.utc) + timedelta(days=i)).strftime("%Y-%m-%d")
    for i in range(30)
]  # 2026-05-11 … 2026-06-09  (latest is ~27 h before NOW → fresh)

# All 29 check names in order
ALL_CHECKS = [
    # Group 1
    "equity_curve_real", "trades_real", "status_real", "no_demo_data",
    "data_fresh_48h", "cycle_runner_exists",
    # Group 2
    "compound_v3_adapter", "morpho_steakhouse_adapter",
    "aave_arbitrum_adapter", "pendle_pt_adapter",
    # Group 3
    "multi_strategy_runner", "promotion_engine", "safe_tx_builder",
    "http_server", "adr022_exists",
    # Group 4
    "adapter_status_has_compound", "adapter_status_has_morpho",
    "adapter_status_has_arbitrum",
    # Group 5
    "gap_monitor_ok", "gap_monitor_30d",
    # Group 6
    "autopush_installed", "telegram_alert_today",
    # Group 7
    "min_track_days_30", "apy_above_floor", "drawdown_below_kill",
    # Group 8
    "risk_policy_snapshot",
    # Group 9 (MP-1228)
    "adapter_registry_complete", "backtest_completed", "audit_trail_signed",
]
TOTAL_CHECKS = len(ALL_CHECKS)  # 29


# ─── Low-level write helper ───────────────────────────────────────────────────

def _write(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj), encoding="utf-8")


# ─── Document factories ───────────────────────────────────────────────────────

def _equity_doc(dates=("2026-06-09", "2026-06-10"), is_demo=False,
                apy_pct=4.5, max_drawdown_pct=0.0):
    return {
        "generated_at": NOW.isoformat(),
        "source": "cycle_runner",
        "is_demo": is_demo,
        "summary": {
            "num_days": len(dates),
            "total_return_pct": apy_pct / 365 * len(dates),
            "max_drawdown_pct": max_drawdown_pct,
        },
        "daily": [
            {"date": d, "open_equity": 100_000.0, "close_equity": 100_010.0}
            for d in dates
        ],
    }


def _equity_doc_30d(is_demo=False, apy_pct=4.5):
    """30 days of equity data; latest date is yesterday relative to NOW."""
    return _equity_doc(dates=_30D_DATES, is_demo=is_demo, apy_pct=apy_pct)


def _trades(n=1, is_demo=False):
    return [
        {"trade_id": f"T{i + 1:03d}", "ts": NOW.isoformat(), "is_demo": is_demo}
        for i in range(n)
    ]


def _adapter_status():
    return {
        "compound_v3": {"status": "ok", "apy_pct": 4.8},
        "morpho_steakhouse": {"status": "ok", "apy_pct": 6.5},
        "aave_arbitrum": {"status": "ok", "apy_pct": 4.6},
    }


def _gap_monitor(status="ok"):
    return {
        "checked_at": NOW.isoformat(),
        "gap_detected": status != "ok",
        "last_entry_date": "2026-06-09T00:00:00+00:00",
        "hours_since_last_entry": 12.0,
        "status": status,
        "message": "ok" if status == "ok" else "GAP DETECTED",
    }


def _telegram_alert_state(date_str="2026-06-10"):
    return {"daily_summary": date_str}


def _adapter_registry(n=20):
    return {
        "version": "1.0",
        "adapters": {f"protocol_{i}": {"tier": "T1", "status": "ok"} for i in range(n)},
    }


def _backtest_vs_paper():
    return {
        "generated_at": NOW.isoformat(),
        "paper_days": 11,
        "summary": {"rank_correlation": 0.8},
    }


# ─── Data-dir factories ───────────────────────────────────────────────────────

def _make_data_dir(tmp_path: Path, **overrides) -> Path:
    """Minimal data dir: Group 1 (6 criteria) can pass; overrides patch files.

    Does NOT include adapter_status, gap_monitor, telegram state, etc.
    Use _make_full_data_dir() when you need all 26 checks to pass.
    """
    ddir = tmp_path / "data"
    docs = {
        "equity_curve_daily.json": _equity_doc(),
        "trades.json": _trades(),
        "paper_trading_status.json": {
            "is_demo": False,
            "source": "cycle_runner",
            "apy_today_pct": 4.5,
        },
    }
    docs.update(overrides)
    for name, doc in docs.items():
        if doc is not None:
            _write(ddir / name, doc)
    return ddir


def _make_full_data_dir(tmp_path: Path, now: datetime = NOW, **overrides) -> Path:
    """Full data dir where all *data-side* criteria pass.

    Pass home_dir=<tmp_path/"home"> and repo_root=<real_repo> to GoLiveChecker
    for complete 26/26 coverage (see _full_checker()).
    """
    ddir = tmp_path / "data"
    today = now.strftime("%Y-%m-%d")
    docs = {
        "equity_curve_daily.json": _equity_doc_30d(),
        "trades.json": _trades(),
        "paper_trading_status.json": {
            "is_demo": False,
            "source": "cycle_runner",
            "apy_today_pct": 4.5,
        },
        "adapter_status.json": _adapter_status(),
        "gap_monitor.json": _gap_monitor("ok"),
        "telegram_alert_state.json": _telegram_alert_state(today),
        "adapter_registry.json": _adapter_registry(),
        "backtest_vs_paper.json": _backtest_vs_paper(),
    }
    docs.update(overrides)
    for name, doc in docs.items():
        if doc is not None:
            _write(ddir / name, doc)
    return ddir


def _fake_home_with_autopush(tmp_path: Path) -> Path:
    """Create a fake home dir that has com.spa.autopush.plist installed."""
    home = tmp_path / "home"
    plist = home / "Library" / "LaunchAgents" / "com.spa.autopush.plist"
    plist.parent.mkdir(parents=True, exist_ok=True)
    plist.write_text("<plist/>", encoding="utf-8")
    return home


# ─── Checker factory helpers ──────────────────────────────────────────────────

def _check(ddir: Path, *, now: datetime = NOW, paper_start=EARLY_PAPER_START, **kw) -> GoLiveResult:
    """Instantiate GoLiveChecker with defaults (uses real repo for file checks).

    Injects an early ``paper_start`` so synthetic pre-teardown histories still
    count as honest track days (MP-1228 honesty rule).
    """
    return GoLiveChecker(data_dir=ddir, now=now, paper_start=paper_start, **kw).check()


def _full_checker(tmp_path: Path, now: datetime = NOW, **data_overrides) -> GoLiveResult:
    """Run all 29 checks against a fully-populated fixture.

    Uses the real repo_root (so adapter/component file checks pass)
    and a fake home_dir with autopush plist installed.
    """
    ddir = _make_full_data_dir(tmp_path, now=now, **data_overrides)
    home = _fake_home_with_autopush(tmp_path)
    return GoLiveChecker(
        data_dir=ddir, now=now, home_dir=home, paper_start=EARLY_PAPER_START
    ).check(write=False)


# ═══════════════════════════════════════════════════════════════════════════════
# Group 1: Data Integrity (original MP-006 criteria)
# ═══════════════════════════════════════════════════════════════════════════════

def test_group1_all_pass_with_minimal_fixture(tmp_path):
    """Group 1 (6 core criteria) all pass when given the minimal data dir."""
    result = _check(_make_data_dir(tmp_path))
    group1 = {
        "equity_curve_real", "trades_real", "status_real",
        "no_demo_data", "data_fresh_48h", "cycle_runner_exists",
    }
    for name in group1:
        assert result.checks[name] is True, f"Expected Group 1 check '{name}' to PASS"
    assert result.timestamp == NOW.isoformat()
    assert isinstance(result, GoLiveResult)


def test_all_checks_present(tmp_path):
    """result.checks always contains exactly 29 named criteria."""
    result = _check(_make_data_dir(tmp_path))
    assert set(result.checks.keys()) == set(ALL_CHECKS)
    assert len(result.checks) == TOTAL_CHECKS == 29


def test_all_pass_with_full_fixture(tmp_path):
    """All 29 criteria pass when the full fixture is provided."""
    result = _full_checker(tmp_path)
    failing = [name for name, ok in result.checks.items() if not ok]
    assert failing == [], f"Expected 29/29 PASS; still failing: {failing}"
    assert result.ready is True
    assert result.blockers == []


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
    assert result.checks["equity_curve_real"] is True  # curve itself is fine
    assert any("stalled" in b for b in result.blockers)


def test_fresh_data_yesterday_passes(tmp_path):
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
    assert result.checks["trades_real"] is False
    assert result.checks["no_demo_data"] is False


def test_status_missing_or_demo(tmp_path):
    ddir = _make_data_dir(tmp_path, **{"paper_trading_status.json": None})
    assert _check(ddir).checks["status_real"] is False

    ddir2 = _make_data_dir(tmp_path / "b", **{"paper_trading_status.json": {"is_demo": True}})
    result = _check(ddir2)
    assert result.checks["status_real"] is False
    assert result.checks["no_demo_data"] is False


def test_cycle_runner_missing(tmp_path):
    result = GoLiveChecker(
        data_dir=_make_data_dir(tmp_path),
        repo_root=tmp_path / "empty_repo",
        now=NOW,
        home_dir=tmp_path / "home",
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


# ═══════════════════════════════════════════════════════════════════════════════
# Group 5: Continuity
# ═══════════════════════════════════════════════════════════════════════════════

def test_gap_monitor_ok_passes_when_status_ok(tmp_path):
    ddir = _make_full_data_dir(tmp_path, **{"gap_monitor.json": _gap_monitor("ok")})
    result = _check(ddir, home_dir=_fake_home_with_autopush(tmp_path))
    assert result.checks["gap_monitor_ok"] is True


def test_gap_monitor_ok_fails_when_gap_detected(tmp_path):
    ddir = _make_full_data_dir(tmp_path, **{"gap_monitor.json": _gap_monitor("gap")})
    result = _check(ddir, home_dir=_fake_home_with_autopush(tmp_path))
    assert result.checks["gap_monitor_ok"] is False
    assert any("gap_monitor" in b for b in result.blockers)


def test_gap_monitor_ok_fails_when_missing(tmp_path):
    ddir = _make_full_data_dir(tmp_path, **{"gap_monitor.json": None})
    result = _check(ddir, home_dir=_fake_home_with_autopush(tmp_path))
    assert result.checks["gap_monitor_ok"] is False


def test_gap_monitor_30d_passes_with_30_dates(tmp_path):
    ddir = _make_full_data_dir(tmp_path)  # uses _equity_doc_30d → 30 dates
    result = _check(ddir, home_dir=_fake_home_with_autopush(tmp_path))
    assert result.checks["gap_monitor_30d"] is True


def test_gap_monitor_30d_fails_with_fewer_dates(tmp_path):
    short_equity = _equity_doc(dates=("2026-06-09", "2026-06-10"))  # only 2 dates
    ddir = _make_full_data_dir(tmp_path, **{"equity_curve_daily.json": short_equity})
    result = _check(ddir, home_dir=_fake_home_with_autopush(tmp_path))
    assert result.checks["gap_monitor_30d"] is False
    assert any("9/30" in b or "2/30" in b or "/30" in b for b in result.blockers)


# ═══════════════════════════════════════════════════════════════════════════════
# Group 6: Infrastructure
# ═══════════════════════════════════════════════════════════════════════════════

def test_autopush_installed_passes_when_plist_present(tmp_path):
    home = _fake_home_with_autopush(tmp_path)
    ddir = _make_full_data_dir(tmp_path)
    result = GoLiveChecker(data_dir=ddir, now=NOW, home_dir=home).check(write=False)
    assert result.checks["autopush_installed"] is True


def test_autopush_installed_fails_when_plist_missing(tmp_path):
    home = tmp_path / "home_no_plist"
    home.mkdir(parents=True, exist_ok=True)
    ddir = _make_full_data_dir(tmp_path)
    result = GoLiveChecker(data_dir=ddir, now=NOW, home_dir=home).check(write=False)
    assert result.checks["autopush_installed"] is False
    assert any("com.spa.autopush.plist" in b for b in result.blockers)


def test_telegram_alert_today_passes_when_today(tmp_path):
    today = NOW.strftime("%Y-%m-%d")
    ddir = _make_full_data_dir(tmp_path, **{"telegram_alert_state.json": {"daily_summary": today}})
    result = _check(ddir, home_dir=_fake_home_with_autopush(tmp_path))
    assert result.checks["telegram_alert_today"] is True


def test_telegram_alert_today_fails_when_yesterday(tmp_path):
    yesterday = (NOW - timedelta(days=1)).strftime("%Y-%m-%d")
    ddir = _make_full_data_dir(
        tmp_path, **{"telegram_alert_state.json": {"daily_summary": yesterday}}
    )
    result = _check(ddir, home_dir=_fake_home_with_autopush(tmp_path))
    assert result.checks["telegram_alert_today"] is False
    assert any("telegram" in b.lower() for b in result.blockers)


def test_telegram_alert_today_fails_when_missing(tmp_path):
    ddir = _make_full_data_dir(tmp_path, **{"telegram_alert_state.json": None})
    result = _check(ddir, home_dir=_fake_home_with_autopush(tmp_path))
    assert result.checks["telegram_alert_today"] is False


# ═══════════════════════════════════════════════════════════════════════════════
# Group 7: Performance
# ═══════════════════════════════════════════════════════════════════════════════

def test_min_track_days_passes_with_30_days(tmp_path):
    ddir = _make_full_data_dir(tmp_path)
    result = _check(ddir, home_dir=_fake_home_with_autopush(tmp_path))
    assert result.checks["min_track_days_30"] is True


def test_min_track_days_fails_with_fewer(tmp_path):
    short = _equity_doc(dates=("2026-06-08", "2026-06-09", "2026-06-10"))  # 3 days
    ddir = _make_full_data_dir(tmp_path, **{"equity_curve_daily.json": short})
    result = _check(ddir, home_dir=_fake_home_with_autopush(tmp_path))
    assert result.checks["min_track_days_30"] is False
    assert any("30" in b for b in result.blockers)


def test_apy_above_floor_passes(tmp_path):
    ddir = _make_full_data_dir(tmp_path)  # default apy_pct=4.5 > 1.0
    result = _check(ddir, home_dir=_fake_home_with_autopush(tmp_path))
    assert result.checks["apy_above_floor"] is True


def test_apy_above_floor_fails_below_1pct(tmp_path):
    st = {"is_demo": False, "source": "cycle_runner", "apy_today_pct": 0.5}
    ddir = _make_full_data_dir(tmp_path, **{"paper_trading_status.json": st})
    result = _check(ddir, home_dir=_fake_home_with_autopush(tmp_path))
    assert result.checks["apy_above_floor"] is False
    assert any("APY" in b or "apy" in b.lower() for b in result.blockers)


def test_drawdown_below_kill_passes_at_zero(tmp_path):
    ddir = _make_full_data_dir(tmp_path)  # default drawdown 0%
    result = _check(ddir, home_dir=_fake_home_with_autopush(tmp_path))
    assert result.checks["drawdown_below_kill"] is True


def test_drawdown_below_kill_fails_at_5pct(tmp_path):
    eq = _equity_doc_30d()
    eq["summary"]["max_drawdown_pct"] = 5.5  # exceeds 5% kill switch
    ddir = _make_full_data_dir(tmp_path, **{"equity_curve_daily.json": eq})
    result = _check(ddir, home_dir=_fake_home_with_autopush(tmp_path))
    assert result.checks["drawdown_below_kill"] is False
    assert any("5" in b and "%" in b for b in result.blockers)


# ═══════════════════════════════════════════════════════════════════════════════
# Group 8: Compliance
# ═══════════════════════════════════════════════════════════════════════════════

def test_risk_policy_snapshot_passes_when_versions_exist(tmp_path):
    # Uses real repo_root by default — spa_core/risk/versions/v1_0_passive.py exists.
    ddir = _make_full_data_dir(tmp_path)
    result = _check(ddir, home_dir=_fake_home_with_autopush(tmp_path))
    assert result.checks["risk_policy_snapshot"] is True


def test_risk_policy_snapshot_fails_when_versions_missing(tmp_path):
    ddir = _make_full_data_dir(tmp_path)
    result = GoLiveChecker(
        data_dir=ddir,
        now=NOW,
        repo_root=tmp_path / "empty_repo",  # no risk/versions/ dir
        home_dir=_fake_home_with_autopush(tmp_path),
    ).check(write=False)
    assert result.checks["risk_policy_snapshot"] is False
    assert any("versions" in b or "snapshot" in b.lower() for b in result.blockers)


# ═══════════════════════════════════════════════════════════════════════════════
# Persistence & reporting
# ═══════════════════════════════════════════════════════════════════════════════

def test_writes_golive_status_json(tmp_path):
    ddir = _make_data_dir(tmp_path)
    result = _check(ddir)
    out = json.loads((ddir / "golive_status.json").read_text(encoding="utf-8"))
    assert out["source"] == "golive_checker"
    assert out["total"] == 29
    assert "passed" in out
    assert out["passed"] == sum(result.checks.values())
    assert out["version"] == "v6.0-29criteria"


def test_to_dict_contains_passed_and_total(tmp_path):
    result = _full_checker(tmp_path)
    d = result.to_dict()
    assert d["passed"] == 29
    assert d["total"] == 29
    assert d["ready"] is True


def test_dry_run_writes_nothing(tmp_path):
    ddir = _make_data_dir(tmp_path)
    GoLiveChecker(data_dir=ddir, now=NOW, home_dir=tmp_path / "home").check(write=False)
    assert not (ddir / "golive_status.json").exists()


def test_own_output_excluded_from_demo_scan(tmp_path):
    """golive_status.json itself is excluded so a re-check doesn't find stale data."""
    ddir = _make_full_data_dir(tmp_path)
    home = _fake_home_with_autopush(tmp_path)
    # First run writes status file
    GoLiveChecker(data_dir=ddir, now=NOW, home_dir=home).check()
    # Second run should not be confused by its own output
    result2 = GoLiveChecker(data_dir=ddir, now=NOW, home_dir=home).check(write=False)
    assert result2.checks["no_demo_data"] is True


def test_summary_contains_blockers_and_verdict(tmp_path):
    ddir = _make_data_dir(tmp_path, **{"trades.json": []})
    text = _check(ddir).summary()
    assert "NOT READY" in text
    assert "trades.json" in text
    assert "[FAIL] trades_real" in text
    assert "[PASS] status_real" in text

    full_text = _full_checker(tmp_path).summary()
    assert "Verdict: READY" in full_text
    assert "29/29" in full_text


def test_summary_shows_group_headers(tmp_path):
    text = _full_checker(tmp_path).summary()
    assert "Group 1" in text
    assert "Group 6" in text
    assert "Group 8" in text


# ═══════════════════════════════════════════════════════════════════════════════
# cycle_runner integration
# ═══════════════════════════════════════════════════════════════════════════════

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
        risk_scorer_fn=lambda d: None,
        track_persister_fn=lambda d: None,
        **kw,
    )


def test_cycle_runner_writes_golive_status(tmp_path):
    result = _run_cycle(tmp_path)
    assert result.status == "ok"  # gate never blocks the cycle
    out = json.loads((tmp_path / "golive_status.json").read_text(encoding="utf-8"))
    assert out["source"] == "golive_checker"
    assert out["total"] == 29
    # First-ever cycle: files don't exist yet → not ready
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


# ═══════════════════════════════════════════════════════════════════════════════
# MP-1193: API contract — check() exists, run_all_checks() must NOT be used
# ═══════════════════════════════════════════════════════════════════════════════

def test_golive_checker_has_check_not_run_all_checks(tmp_path):
    """GoLiveChecker exposes check(), NOT run_all_checks().

    Regression guard: if anyone adds run_all_checks() as an alias they break
    the API contract; if they accidentally rename check() callers break too.
    This test pins the correct public interface so a future refactor is caught
    immediately rather than silently returning {"status": "error"}.
    """
    checker = GoLiveChecker(data_dir=tmp_path, now=NOW)
    assert callable(getattr(checker, "check", None)), (
        "GoLiveChecker.check() must exist — it is the canonical public API"
    )
    assert not hasattr(checker, "run_all_checks"), (
        "GoLiveChecker must NOT expose run_all_checks() — callers must use check()"
    )


def test_golive_checker_check_returns_golive_result_no_attribute_error(tmp_path):
    """GoLiveChecker().check() must return a GoLiveResult without AttributeError.

    This is the core regression: the checker was previously being called as
    .run_all_checks() in some paths, raising AttributeError caught by a broad
    except that returned {"status": "error"} — making GoLive score always wrong.
    Here we verify check() runs to completion and returns the correct type.
    """
    ddir = tmp_path / "data"
    ddir.mkdir()

    # Must not raise AttributeError (or any exception)
    result = GoLiveChecker(data_dir=ddir, now=NOW).check(write=False)

    assert isinstance(result, GoLiveResult), (
        f"check() must return GoLiveResult, got {type(result).__name__}"
    )
    assert isinstance(result.ready, bool)
    assert isinstance(result.blockers, list)
    assert isinstance(result.checks, dict)
    assert len(result.checks) == 29, (
        f"Expected 29 criteria, got {len(result.checks)}"
    )
