"""MP-1228 — tests for the go-live gate improvements.

Covers the three changes shipped in v1228:

1. Honesty fix — ``min_track_days_30`` / ``gap_monitor_30d`` count ONLY equity
   bars dated on/after ``PAPER_REAL_START`` (post-teardown). Pre-teardown bars
   are demo/void per CLAUDE.md and must never inflate the track length.
2. Rich reporting — every criterion is classified PASS / FAIL / PENDING with
   ``blocking``, ``estimated_days_to_pass`` and ``target_date`` metadata.
3. Three new criteria (Group 9) — ``adapter_registry_complete``,
   ``backtest_completed``, ``audit_trail_signed``.

Every test builds an isolated data dir under ``tmp_path``; ``now`` is frozen for
determinism. The real repo_root is used so file-presence checks (adapters,
components, risk snapshot, audit signer) resolve against the live tree.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from spa_core.paper_trading.golive_checker import (
    GoLiveChecker,
    MIN_TRACK_DAYS,
    PAPER_REAL_START,
    TIME_GATED_CRITERIA,
)

NOW = datetime(2026, 6, 25, 12, 0, tzinfo=timezone.utc)


# ─── helpers ──────────────────────────────────────────────────────────────────

def _write(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj), encoding="utf-8")


def _consecutive(start: datetime, n: int) -> list[str]:
    """n consecutive ISO dates starting at *start*."""
    return [(start + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(n)]


def _equity(dates, is_demo=False, max_drawdown_pct=0.0):
    return {
        "generated_at": NOW.isoformat(),
        "source": "cycle_runner",
        "is_demo": is_demo,
        "summary": {"num_days": len(dates), "max_drawdown_pct": max_drawdown_pct},
        "daily": [
            {"date": d, "open_equity": 100_000.0, "close_equity": 100_010.0}
            for d in dates
        ],
    }


def _full_data_dir(tmp_path: Path, *, now: datetime = NOW, **overrides) -> Path:
    """Data dir where every data-side criterion can pass."""
    ddir = tmp_path / "data"
    today = now.strftime("%Y-%m-%d")
    # 30 honest days ending the day before `now`.
    honest = _consecutive(now - timedelta(days=MIN_TRACK_DAYS), MIN_TRACK_DAYS)
    docs = {
        "equity_curve_daily.json": _equity(honest),
        "trades.json": [{"trade_id": "T001", "ts": now.isoformat(), "is_demo": False}],
        "paper_trading_status.json": {
            "is_demo": False, "source": "cycle_runner", "apy_today_pct": 4.5,
        },
        "adapter_status.json": {
            "compound_v3": {"status": "ok"},
            "morpho_steakhouse": {"status": "ok"},
            "aave_arbitrum": {"status": "ok"},
        },
        "gap_monitor.json": {"status": "ok", "gap_detected": False},
        "telegram_alert_state.json": {"daily_summary": today},
        "adapter_registry.json": {
            "adapters": {f"p{i}": {"tier": "T1"} for i in range(22)}
        },
        "backtest_vs_paper.json": {"paper_days": 15, "summary": {"rank_correlation": 0.8}},
    }
    docs.update(overrides)
    for name, doc in docs.items():
        if doc is not None:
            _write(ddir / name, doc)
    return ddir


def _home_with_autopush(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    plist = home / "Library" / "LaunchAgents" / "com.spa.autopush.plist"
    plist.parent.mkdir(parents=True, exist_ok=True)
    plist.write_text("<plist/>", encoding="utf-8")
    return home


def _checker(tmp_path: Path, *, now: datetime = NOW, paper_start=None, **dd) -> GoLiveChecker:
    ddir = _full_data_dir(tmp_path, now=now, **dd)
    return GoLiveChecker(
        data_dir=ddir, now=now, home_dir=_home_with_autopush(tmp_path),
        paper_start=paper_start,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Honesty fix — pre-teardown bars excluded
# ═══════════════════════════════════════════════════════════════════════════════

def test_paper_start_defaults_to_real_start(tmp_path):
    """No explicit paper_start → defaults to PAPER_REAL_START (2026-06-10)."""
    chk = GoLiveChecker(data_dir=tmp_path, now=NOW)
    assert chk.paper_start == PAPER_REAL_START
    assert chk.paper_start == datetime(2026, 6, 10).date()


def test_pre_teardown_bars_excluded_from_min_track(tmp_path):
    """31 bars from 2026-05-21, but only 11 are post-teardown → min_track fails."""
    dates = _consecutive(datetime(2026, 5, 21, tzinfo=timezone.utc), 31)  # …06-20
    ddir = _full_data_dir(tmp_path, now=NOW, **{"equity_curve_daily.json": _equity(dates)})
    res = GoLiveChecker(data_dir=ddir, now=NOW, home_dir=_home_with_autopush(tmp_path)).check(write=False)
    assert res.checks["min_track_days_30"] is False
    # 2026-06-10 … 2026-06-20 == 11 honest days
    assert res.real_track_days == 11


def test_pre_teardown_bars_excluded_from_gap_30d(tmp_path):
    dates = _consecutive(datetime(2026, 5, 21, tzinfo=timezone.utc), 31)
    ddir = _full_data_dir(tmp_path, now=NOW, **{"equity_curve_daily.json": _equity(dates)})
    res = GoLiveChecker(data_dir=ddir, now=NOW, home_dir=_home_with_autopush(tmp_path)).check(write=False)
    assert res.checks["gap_monitor_30d"] is False


def test_real_track_days_counts_only_post_teardown(tmp_path):
    """A bar exactly on PAPER_REAL_START counts; the day before does not."""
    dates = ["2026-06-09", "2026-06-10", "2026-06-11"]
    ddir = _full_data_dir(tmp_path, now=NOW, **{"equity_curve_daily.json": _equity(dates)})
    res = GoLiveChecker(data_dir=ddir, now=NOW, home_dir=_home_with_autopush(tmp_path)).check(write=False)
    assert res.real_track_days == 2  # 06-10 and 06-11 only


def test_injected_paper_start_changes_count(tmp_path):
    """Injecting an early paper_start makes pre-teardown bars count again."""
    dates = _consecutive(datetime(2026, 5, 21, tzinfo=timezone.utc), 31)
    ddir = _full_data_dir(tmp_path, now=NOW, **{"equity_curve_daily.json": _equity(dates)})
    res = GoLiveChecker(
        data_dir=ddir, now=NOW, home_dir=_home_with_autopush(tmp_path),
        paper_start=datetime(2026, 5, 1, tzinfo=timezone.utc),
    ).check(write=False)
    assert res.real_track_days == 31
    assert res.checks["min_track_days_30"] is True


def test_mixed_pre_and_post_only_post_counted(tmp_path):
    dates = ["2026-05-01", "2026-05-15", "2026-06-10", "2026-06-15", "2026-06-20"]
    ddir = _full_data_dir(tmp_path, now=NOW, **{"equity_curve_daily.json": _equity(dates)})
    res = GoLiveChecker(data_dir=ddir, now=NOW, home_dir=_home_with_autopush(tmp_path)).check(write=False)
    assert res.real_track_days == 3  # 06-10, 06-15, 06-20


def test_exactly_30_honest_days_passes(tmp_path):
    """30 consecutive post-teardown days → both track criteria pass (default cutoff)."""
    now = datetime(2026, 7, 12, 12, 0, tzinfo=timezone.utc)
    dates = _consecutive(datetime(2026, 6, 12, tzinfo=timezone.utc), 30)  # all >= 06-10
    ddir = _full_data_dir(tmp_path, now=now, **{"equity_curve_daily.json": _equity(dates)})
    res = GoLiveChecker(data_dir=ddir, now=now, home_dir=_home_with_autopush(tmp_path)).check(write=False)
    assert res.real_track_days == 30
    assert res.checks["min_track_days_30"] is True
    assert res.checks["gap_monitor_30d"] is True


def test_29_honest_days_is_pending(tmp_path):
    now = datetime(2026, 7, 11, 12, 0, tzinfo=timezone.utc)
    dates = _consecutive(datetime(2026, 6, 12, tzinfo=timezone.utc), 29)
    ddir = _full_data_dir(tmp_path, now=now, **{"equity_curve_daily.json": _equity(dates)})
    res = GoLiveChecker(data_dir=ddir, now=now, home_dir=_home_with_autopush(tmp_path)).check(write=False)
    assert res.checks["min_track_days_30"] is False
    assert res.details["min_track_days_30"]["status"] == "PENDING"


# ═══════════════════════════════════════════════════════════════════════════════
# 2. PENDING vs FAIL classification + estimates
# ═══════════════════════════════════════════════════════════════════════════════

def test_min_track_pending_not_fail(tmp_path):
    dates = _consecutive(datetime(2026, 6, 10, tzinfo=timezone.utc), 11)
    ddir = _full_data_dir(tmp_path, now=NOW, **{"equity_curve_daily.json": _equity(dates)})
    res = GoLiveChecker(data_dir=ddir, now=NOW, home_dir=_home_with_autopush(tmp_path)).check(write=False)
    assert res.details["min_track_days_30"]["status"] == "PENDING"


def test_gap_30d_pending_not_fail(tmp_path):
    dates = _consecutive(datetime(2026, 6, 10, tzinfo=timezone.utc), 11)
    ddir = _full_data_dir(tmp_path, now=NOW, **{"equity_curve_daily.json": _equity(dates)})
    res = GoLiveChecker(data_dir=ddir, now=NOW, home_dir=_home_with_autopush(tmp_path)).check(write=False)
    assert res.details["gap_monitor_30d"]["status"] == "PENDING"


def test_time_gated_set_is_exactly_two(tmp_path):
    assert TIME_GATED_CRITERIA == {"min_track_days_30", "gap_monitor_30d"}


def test_pending_carries_estimated_days(tmp_path):
    dates = _consecutive(datetime(2026, 6, 10, tzinfo=timezone.utc), 11)  # 11 honest days
    ddir = _full_data_dir(tmp_path, now=NOW, **{"equity_curve_daily.json": _equity(dates)})
    res = GoLiveChecker(data_dir=ddir, now=NOW, home_dir=_home_with_autopush(tmp_path)).check(write=False)
    det = res.details["min_track_days_30"]
    assert det["estimated_days_to_pass"] == MIN_TRACK_DAYS - 11  # 19


def test_pending_carries_target_date(tmp_path):
    dates = _consecutive(datetime(2026, 6, 10, tzinfo=timezone.utc), 11)
    ddir = _full_data_dir(tmp_path, now=NOW, **{"equity_curve_daily.json": _equity(dates)})
    res = GoLiveChecker(data_dir=ddir, now=NOW, home_dir=_home_with_autopush(tmp_path)).check(write=False)
    det = res.details["min_track_days_30"]
    expected = (NOW.date() + timedelta(days=19)).isoformat()
    assert det["target_date"] == expected


def test_real_defect_is_fail_status(tmp_path):
    """A missing required file is a FAIL (defect), not PENDING."""
    ddir = _full_data_dir(tmp_path, now=NOW, **{"trades.json": []})
    res = GoLiveChecker(data_dir=ddir, now=NOW, home_dir=_home_with_autopush(tmp_path)).check(write=False)
    assert res.details["trades_real"]["status"] == "FAIL"
    assert res.details["trades_real"]["estimated_days_to_pass"] is None


def test_pass_criterion_detail(tmp_path):
    res = _checker(tmp_path).check(write=False)
    det = res.details["risk_policy_snapshot"]
    assert det["status"] == "PASS"
    assert det["blocking"] is False
    assert det["estimated_days_to_pass"] == 0


def test_pending_is_still_blocking(tmp_path):
    """PENDING criteria still block go-live (blocking=True)."""
    dates = _consecutive(datetime(2026, 6, 10, tzinfo=timezone.utc), 11)
    ddir = _full_data_dir(tmp_path, now=NOW, **{"equity_curve_daily.json": _equity(dates)})
    res = GoLiveChecker(data_dir=ddir, now=NOW, home_dir=_home_with_autopush(tmp_path)).check(write=False)
    assert res.details["min_track_days_30"]["blocking"] is True
    assert res.ready is False


def test_estimated_days_equals_remainder(tmp_path):
    dates = _consecutive(datetime(2026, 6, 10, tzinfo=timezone.utc), 5)  # 5 honest days
    ddir = _full_data_dir(tmp_path, now=NOW, **{"equity_curve_daily.json": _equity(dates)})
    res = GoLiveChecker(data_dir=ddir, now=NOW, home_dir=_home_with_autopush(tmp_path)).check(write=False)
    assert res.real_track_days == 5
    assert res.details["min_track_days_30"]["estimated_days_to_pass"] == 25


# ═══════════════════════════════════════════════════════════════════════════════
# 3. New criteria — Group 9
# ═══════════════════════════════════════════════════════════════════════════════

def test_adapter_registry_passes_at_threshold(tmp_path):
    reg = {"adapters": {f"p{i}": {} for i in range(20)}}  # exactly 20
    res = _checker(tmp_path, **{"adapter_registry.json": reg}).check(write=False)
    assert res.checks["adapter_registry_complete"] is True


def test_adapter_registry_fails_below_threshold(tmp_path):
    reg = {"adapters": {f"p{i}": {} for i in range(5)}}
    res = _checker(tmp_path, **{"adapter_registry.json": reg}).check(write=False)
    assert res.checks["adapter_registry_complete"] is False
    assert any("adapter_registry_complete" in b for b in res.blockers)


def test_adapter_registry_fails_when_missing(tmp_path):
    res = _checker(tmp_path, **{"adapter_registry.json": None}).check(write=False)
    assert res.checks["adapter_registry_complete"] is False


def test_backtest_passes_with_vs_paper(tmp_path):
    res = _checker(tmp_path).check(write=False)  # fixture has backtest_vs_paper.json
    assert res.checks["backtest_completed"] is True


def test_backtest_passes_with_results_file(tmp_path):
    res = _checker(
        tmp_path,
        **{"backtest_vs_paper.json": None, "backtest_results.json": {"sharpe": 1.2}},
    ).check(write=False)
    assert res.checks["backtest_completed"] is True


def test_backtest_fails_when_absent(tmp_path):
    res = _checker(
        tmp_path, **{"backtest_vs_paper.json": None, "backtest_results.json": None}
    ).check(write=False)
    assert res.checks["backtest_completed"] is False


def test_audit_trail_signed_passes_with_signer_deployed(tmp_path):
    """Signer module exists in the real repo + no chain file → vacuous pass."""
    res = _checker(tmp_path).check(write=False)
    assert res.checks["audit_trail_signed"] is True


def test_audit_trail_signed_fails_when_signer_missing(tmp_path):
    """Empty repo_root → signer file absent → criterion fails."""
    ddir = _full_data_dir(tmp_path, now=NOW)
    res = GoLiveChecker(
        data_dir=ddir, now=NOW, repo_root=tmp_path / "empty_repo",
        home_dir=_home_with_autopush(tmp_path),
    ).check(write=False)
    assert res.checks["audit_trail_signed"] is False


# ═══════════════════════════════════════════════════════════════════════════════
# to_dict / structure
# ═══════════════════════════════════════════════════════════════════════════════

def test_to_dict_has_criteria_list_and_total_29(tmp_path):
    d = _checker(tmp_path).check(write=False).to_dict()
    assert d["total"] == 29
    assert d["version"] == "v6.0-29criteria"
    assert isinstance(d["criteria"], list)
    assert len(d["criteria"]) == 29
    # every entry has a name + status
    for c in d["criteria"]:
        assert "name" in c and "status" in c
    assert "real_track_days" in d


def test_full_fixture_is_ready_29_of_29(tmp_path):
    """The full fixture (30 honest days, all files present) → 29/29 READY."""
    now = datetime(2026, 7, 12, 12, 0, tzinfo=timezone.utc)
    res = _checker(tmp_path, now=now).check(write=False)
    failing = [n for n, ok in res.checks.items() if not ok]
    assert failing == [], f"still failing: {failing}"
    assert res.ready is True
