"""
test_agent_health_monitor.py — tests for the SPA Agent Health heartbeat monitor.

Covers:
  * launchctl output parsing (PID / exit / header / malformed lines)
  * plist discovery + classification (high/mid/daily/always_on/on_demand)
  * file-age freshness with mocked mtimes
  * per-agent OK / WARNING / CRITICAL classification
  * system-state checks (equity/cycle/portfolio/red_flags/autopush)
  * report assembly + counts + overall rollup
  * alert dedup (don't re-alert on the same issues)
  * Telegram message formatting
  * JSON output format + atomic write
  * fail-safe behaviour (no exceptions escape run())

Pure stdlib + pytest. No network, no real launchctl, no real Telegram.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from spa_core.monitoring import agent_health_monitor as ahm


NOW = datetime(2026, 6, 21, 10, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _write_plist(path: Path, *, label: str, start_interval=None,
                 calendar=False, keepalive=False, log_path="/tmp/x.log"):
    """Write a minimal valid plist."""
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">',
        '<plist version="1.0"><dict>',
        f'<key>Label</key><string>{label}</string>',
    ]
    if start_interval is not None:
        parts.append(f'<key>StartInterval</key><integer>{start_interval}</integer>')
    if calendar:
        parts.append('<key>StartCalendarInterval</key><dict>'
                     '<key>Hour</key><integer>8</integer></dict>')
    if keepalive:
        parts.append('<key>KeepAlive</key><true/>')
    if log_path:
        parts.append(f'<key>StandardOutPath</key><string>{log_path}</string>')
    parts.append('</dict></plist>')
    path.write_text("\n".join(parts), encoding="utf-8")


def _touch(path: Path, age_minutes: float):
    """Create a file with mtime age_minutes in the past relative to NOW."""
    path.write_text("log", encoding="utf-8")
    mtime = NOW.timestamp() - age_minutes * 60.0
    os.utime(path, (mtime, mtime))


# ===========================================================================
# 1. launchctl parsing
# ===========================================================================
def test_parse_launchctl_basic():
    text = "PID\tStatus\tLabel\n123\t0\tcom.spa.foo\n-\t0\tcom.spa.bar"
    out = ahm.parse_launchctl_list(text)
    assert out["com.spa.foo"] == {"pid": 123, "exit": 0}
    assert out["com.spa.bar"] == {"pid": 0, "exit": 0}


def test_parse_launchctl_skips_header():
    out = ahm.parse_launchctl_list("PID\tStatus\tLabel")
    assert out == {}


def test_parse_launchctl_dash_exit():
    out = ahm.parse_launchctl_list("-\t-\tcom.spa.x")
    assert out["com.spa.x"]["pid"] == 0
    assert out["com.spa.x"]["exit"] is None


def test_parse_launchctl_nonzero_exit():
    out = ahm.parse_launchctl_list("-\t256\tcom.spa.x")
    assert out["com.spa.x"]["exit"] == 256


def test_parse_launchctl_empty_and_garbage():
    assert ahm.parse_launchctl_list("") == {}
    assert ahm.parse_launchctl_list("not tab separated line") == {}
    assert ahm.parse_launchctl_list(None) == {}


def test_parse_launchctl_bad_pid_field():
    out = ahm.parse_launchctl_list("abc\t0\tcom.spa.x")
    assert out["com.spa.x"]["pid"] == 0


# ===========================================================================
# 2. plist discovery + label
# ===========================================================================
def test_discover_plists_excludes_disabled(tmp_path):
    _write_plist(tmp_path / "com.spa.a.plist", label="com.spa.a", start_interval=300)
    (tmp_path / "com.spa.b.plist.disabled").write_text("x")
    (tmp_path / "other.txt").write_text("x")
    found = ahm.discover_plists(tmp_path)
    assert len(found) == 1
    assert found[0].name == "com.spa.a.plist"


def test_label_from_path():
    assert ahm.label_from_path(Path("/x/com.spa.foo.plist")) == "com.spa.foo"


# ===========================================================================
# 3. classification
# ===========================================================================
def test_classify_high_freq():
    assert ahm.classify_agent({"StartInterval": 300}) == ahm.CAT_HIGH_FREQ
    assert ahm.classify_agent({"StartInterval": 600}) == ahm.CAT_HIGH_FREQ


def test_classify_mid_freq():
    assert ahm.classify_agent({"StartInterval": 900}) == ahm.CAT_MID_FREQ
    assert ahm.classify_agent({"StartInterval": 5400}) == ahm.CAT_MID_FREQ


def test_classify_daily_by_interval():
    assert ahm.classify_agent({"StartInterval": 86400}) == ahm.CAT_DAILY


def test_classify_daily_by_calendar():
    assert ahm.classify_agent({"StartCalendarInterval": {"Hour": 8}}) == ahm.CAT_DAILY


def test_classify_always_on():
    assert ahm.classify_agent({"KeepAlive": True}) == ahm.CAT_ALWAYS_ON
    # KeepAlive wins over interval
    assert ahm.classify_agent({"KeepAlive": True, "StartInterval": 300}) == ahm.CAT_ALWAYS_ON


def test_classify_on_demand_and_none():
    assert ahm.classify_agent({}) == ahm.CAT_ON_DEMAND
    assert ahm.classify_agent(None) == ahm.CAT_ON_DEMAND


def test_classify_weekly():
    # Weekday-based schedule → CAT_WEEKLY (Saturday backup, etc.)
    assert ahm.classify_agent({"StartCalendarInterval": {"Weekday": 6, "Hour": 10}}) == ahm.CAT_WEEKLY
    assert ahm.classify_agent({"StartCalendarInterval": {"Weekday": 0}}) == ahm.CAT_WEEKLY


def test_classify_one_time():
    # Month + Day = specific date → CAT_ONE_TIME (runs once, no freshness alarm)
    assert ahm.classify_agent({"StartCalendarInterval": {"Month": 6, "Day": 19, "Hour": 10}}) == ahm.CAT_ONE_TIME
    assert ahm.classify_agent({"StartCalendarInterval": {"Month": 12, "Day": 31}}) == ahm.CAT_ONE_TIME


def test_classify_daily_by_calendar_hour_only():
    # Hour/Minute only (no Weekday, no Month+Day) → CAT_DAILY
    assert ahm.classify_agent({"StartCalendarInterval": {"Hour": 8, "Minute": 0}}) == ahm.CAT_DAILY
    assert ahm.classify_agent({"StartCalendarInterval": {}}) == ahm.CAT_DAILY


def test_weekly_threshold_in_map():
    # CAT_WEEKLY must have a freshness threshold (7 days in minutes)
    assert ahm.CAT_WEEKLY in ahm._FRESHNESS_THRESHOLD_MIN
    assert ahm._FRESHNESS_THRESHOLD_MIN[ahm.CAT_WEEKLY] == 7 * 24 * 60


def test_one_time_not_in_threshold_map():
    # CAT_ONE_TIME is excluded from freshness checks — no alarms
    assert ahm.CAT_ONE_TIME not in ahm._FRESHNESS_THRESHOLD_MIN


# ===========================================================================
# 4. file age + iso helpers
# ===========================================================================
def test_file_age_minutes(tmp_path):
    p = tmp_path / "log"
    _touch(p, 45)
    age = ahm.file_age_minutes(str(p), NOW)
    assert 44 < age < 46


def test_file_age_missing():
    assert ahm.file_age_minutes("/nonexistent/path.log", NOW) is None
    assert ahm.file_age_minutes(None, NOW) is None


def test_hours_since_z_suffix():
    h = ahm._hours_since("2026-06-21T08:00:00Z", NOW)
    assert abs(h - 2.0) < 0.01


def test_hours_since_naive_treated_utc():
    h = ahm._hours_since("2026-06-21T07:00:00", NOW)
    assert abs(h - 3.0) < 0.01


def test_hours_since_bad_input():
    assert ahm._hours_since(None, NOW) is None
    assert ahm._hours_since("garbage", NOW) is None


# ===========================================================================
# 5. per-agent check
# ===========================================================================
def _lc(label, pid=0, exit=0):
    return {label: {"pid": pid, "exit": exit}}


def test_agent_not_loaded_is_critical():
    h = ahm.check_agent("com.spa.x", {"StartInterval": 300}, True, {}, NOW)
    assert h.status == ahm.CRITICAL
    assert "not loaded" in h.issue


def test_calendar_agent_not_resident_fresh_log_ok(tmp_path):
    """P5-4 core fix: a calendar agent (StartCalendarInterval + RunAtLoad:False)
    that is NOT in launchctl right now — because it correctly exited between
    scheduled runs — is HEALTHY when its log is fresh (judged by freshness, not
    residency). This is the chronic false-'not loaded in launchctl' CRITICAL."""
    logp = tmp_path / "d.log"
    _touch(logp, 60 * 6)  # 6h ago < 26h daily window
    plist = {"StartCalendarInterval": {"Hour": 8}, "RunAtLoad": False,
             "StandardOutPath": str(logp)}
    h = ahm.check_agent("com.spa.telegram_daily", plist, True, {}, NOW)  # NOT loaded
    assert h.status == ahm.OK
    assert "not loaded" not in h.issue
    assert h.loaded is False


def test_calendar_agent_not_resident_stale_log_flagged(tmp_path):
    """Real-outage still caught: a calendar agent whose log is STALE beyond its
    window is flagged CRITICAL even though 'not resident' is no longer the trigger."""
    logp = tmp_path / "d.log"
    _touch(logp, 60 * 60)  # 60h ago > 2x 26h daily window → CRITICAL
    plist = {"StartCalendarInterval": {"Hour": 8}, "RunAtLoad": False,
             "StandardOutPath": str(logp)}
    h = ahm.check_agent("com.spa.telegram_daily", plist, True, {}, NOW)  # NOT loaded
    assert h.status == ahm.CRITICAL
    assert "stale" in h.issue


def test_calendar_agent_not_resident_missing_log_warning():
    """A non-resident calendar agent with a MISSING log (e.g. /tmp wiped on reboot
    or not yet fired in its first window) is advisory WARNING — fail-closed but
    not a false CRITICAL."""
    plist = {"StartCalendarInterval": {"Hour": 8}, "RunAtLoad": False,
             "StandardOutPath": "/nonexistent/x.log"}
    h = ahm.check_agent("com.spa.weekly_backup", plist, True, {}, NOW)  # NOT loaded
    assert h.status == ahm.WARNING
    assert "missing" in h.issue


def test_keepalive_agent_not_resident_critical():
    """A KeepAlive daemon absent from launchctl is a REAL outage → CRITICAL
    (residency IS required for always-on servers)."""
    plist = {"KeepAlive": True, "RunAtLoad": True, "StandardOutPath": "/tmp/x.log"}
    h = ahm.check_agent("com.spa.apiserver", plist, True, {}, NOW)  # NOT loaded
    assert h.status == ahm.CRITICAL
    assert "not loaded" in h.issue


def test_interval_agent_not_resident_critical():
    """A StartInterval guardian launchd keeps resident — absence is a real fault."""
    plist = {"StartInterval": 300, "StandardOutPath": "/tmp/x.log"}
    h = ahm.check_agent("com.spa.watchdog", plist, True, {}, NOW)  # NOT loaded
    assert h.status == ahm.CRITICAL
    assert "not loaded" in h.issue


def test_requires_residency_matrix():
    assert ahm.requires_residency(ahm.CAT_ALWAYS_ON, {"KeepAlive": True}) is True
    assert ahm.requires_residency(ahm.CAT_HIGH_FREQ, {"StartInterval": 300}) is True
    assert ahm.requires_residency(ahm.CAT_MID_FREQ, {"StartInterval": 1800}) is True
    assert ahm.requires_residency(ahm.CAT_DAILY, {"RunAtLoad": False}) is False
    assert ahm.requires_residency(ahm.CAT_WEEKLY, {"RunAtLoad": False}) is False
    assert ahm.requires_residency(ahm.CAT_ONE_TIME, {}) is False


def test_retired_agent_skipped(tmp_path, monkeypatch):
    """A RETIRED agent (bot_commands, superseded by telegram_bot) is neither
    flagged nor counted — even though its .plist lingers on the host."""
    la, data = _make_env(tmp_path)
    _write_plist(la / "com.spa.bot_commands.plist", label="com.spa.bot_commands",
                 keepalive=True, log_path="/tmp/x.log")
    _write_json(data, "red_flags.json", {"red_flags": []})
    lc = "PID\tStatus\tLabel"  # bot_commands NOT loaded — would be CRITICAL if counted
    mon = ahm.AgentHealthMonitor(data_dir=data, launch_agents_dir=la,
                                 launchctl_output=lc,
                                 autopush_log="/nonexistent.log", now=NOW)
    rep = mon.collect()
    labels = [a["label"] for a in rep["agents"]]
    assert "com.spa.bot_commands" not in labels
    assert rep["total_agents"] == 0


def test_agent_fresh_high_freq_ok(tmp_path):
    logp = tmp_path / "h.log"
    _touch(logp, 5)
    plist = {"StartInterval": 300, "StandardOutPath": str(logp)}
    h = ahm.check_agent("com.spa.x", plist, True, _lc("com.spa.x"), NOW)
    assert h.status == ahm.OK
    assert h.issue == ""


def test_agent_stale_high_freq_warning(tmp_path):
    logp = tmp_path / "h.log"
    _touch(logp, 40)  # > 30 threshold, < 60 (2x)
    plist = {"StartInterval": 300, "StandardOutPath": str(logp)}
    h = ahm.check_agent("com.spa.x", plist, True, _lc("com.spa.x"), NOW)
    assert h.status == ahm.WARNING
    assert "stale" in h.issue


def test_agent_very_stale_high_freq_critical(tmp_path):
    logp = tmp_path / "h.log"
    _touch(logp, 200)  # > 2x threshold
    plist = {"StartInterval": 300, "StandardOutPath": str(logp)}
    h = ahm.check_agent("com.spa.x", plist, True, _lc("com.spa.x"), NOW)
    assert h.status == ahm.CRITICAL


def test_agent_fresh_stderr_only_ok(tmp_path):
    """Regression: a module that logs via Python `logging` writes to stderr,
    so StandardOutPath stays empty/frozen. Freshness must be judged by the
    freshest of both streams (the red_flag_monitor false-stale bug)."""
    out = tmp_path / "rf.log"
    err = tmp_path / "rf_err.log"
    _touch(out, 60 * 24 * 2.2)  # stdout frozen 2.2 days ago
    _touch(err, 4)              # stderr written 4 min ago
    plist = {"StartInterval": 300,
             "StandardOutPath": str(out),
             "StandardErrorPath": str(err)}
    h = ahm.check_agent("com.spa.red_flag_monitor", plist, True,
                        _lc("com.spa.red_flag_monitor"), NOW)
    assert h.status == ahm.OK
    assert h.issue == ""
    assert h.log_age_min < 5


def test_freshest_log_age_minutes_ignores_missing(tmp_path):
    err = tmp_path / "e.log"
    _touch(err, 7)
    paths = ["/nonexistent/out.log", str(err)]
    assert abs(ahm.freshest_log_age_minutes(paths, NOW) - 7) < 1
    assert ahm.freshest_log_age_minutes([], NOW) is None
    assert ahm.freshest_log_age_minutes(["/nope/a", "/nope/b"], NOW) is None


def test_agent_daily_fresh_ok(tmp_path):
    logp = tmp_path / "d.log"
    _touch(logp, 60 * 10)  # 10h < 26h
    plist = {"StartCalendarInterval": {"Hour": 8}, "StandardOutPath": str(logp)}
    h = ahm.check_agent("com.spa.x", plist, True, _lc("com.spa.x"), NOW)
    assert h.status == ahm.OK


def test_agent_daily_stale_warning(tmp_path):
    logp = tmp_path / "d.log"
    _touch(logp, 60 * 28)  # 28h > 26h, < 52h
    plist = {"StartCalendarInterval": {"Hour": 8}, "StandardOutPath": str(logp)}
    h = ahm.check_agent("com.spa.x", plist, True, _lc("com.spa.x"), NOW)
    assert h.status == ahm.WARNING


def test_agent_always_on_pid_zero_critical():
    plist = {"KeepAlive": True, "StandardOutPath": "/tmp/x.log"}
    h = ahm.check_agent("com.spa.srv", plist, True, _lc("com.spa.srv", pid=0), NOW)
    assert h.status == ahm.CRITICAL
    assert "PID=0" in h.issue


def test_agent_always_on_pid_live_ok():
    plist = {"KeepAlive": True, "StandardOutPath": "/tmp/x.log"}
    h = ahm.check_agent("com.spa.srv", plist, True, _lc("com.spa.srv", pid=999), NOW)
    assert h.status == ahm.OK


def test_agent_always_on_ignores_log_age():
    # No log freshness check for always-on even with old/no log
    plist = {"KeepAlive": True, "StandardOutPath": "/nonexistent.log"}
    h = ahm.check_agent("com.spa.srv", plist, True, _lc("com.spa.srv", pid=5), NOW)
    assert h.status == ahm.OK


def test_agent_nonzero_exit_warning(tmp_path):
    logp = tmp_path / "h.log"
    _touch(logp, 1)
    plist = {"StartInterval": 300, "StandardOutPath": str(logp)}
    h = ahm.check_agent("com.spa.x", plist, True, _lc("com.spa.x", pid=0, exit=1), NOW)
    assert h.status == ahm.WARNING
    assert "last_exit=1" in h.issue


def test_agent_always_on_nonzero_exit_critical():
    # pid=0 means server is DOWN (crashed, not restarted) + exit=1 → CRITICAL.
    # When pid != 0, launchctl retains the old exit code after a clean restart,
    # so nonzero exit is intentionally ignored while the process is alive (see
    # agent_health_monitor.py _server_alive logic).
    plist = {"KeepAlive": True, "StandardOutPath": "/tmp/x.log"}
    h = ahm.check_agent("com.spa.srv", plist, True, _lc("com.spa.srv", pid=0, exit=1), NOW)
    assert h.status == ahm.CRITICAL


def test_agent_always_on_alive_with_stale_exit_ok():
    # pid != 0 (server alive) + exit=1 (stale from prior restart) → OK.
    # Avoids false CRITICAL when launchd auto-restarts the always-on server.
    plist = {"KeepAlive": True, "StandardOutPath": "/tmp/x.log"}
    h = ahm.check_agent("com.spa.srv", plist, True, _lc("com.spa.srv", pid=7, exit=1), NOW)
    assert h.status == ahm.OK


def test_agent_malformed_plist_warning():
    # parse_ok False, loaded, no plist data → WARNING malformed
    h = ahm.check_agent("com.spa.x", {}, False, _lc("com.spa.x", pid=1), NOW)
    assert h.status == ahm.WARNING
    assert "malformed" in h.issue


def test_agent_log_missing_critical():
    plist = {"StartInterval": 300, "StandardOutPath": "/nonexistent/x.log"}
    h = ahm.check_agent("com.spa.x", plist, True, _lc("com.spa.x"), NOW)
    assert h.status == ahm.CRITICAL
    assert "missing" in h.issue


def test_agent_on_demand_no_freshness():
    # on-demand agent loaded, exit 0 → OK regardless of logs
    h = ahm.check_agent("com.spa.x", {}, True, _lc("com.spa.x", pid=0, exit=0), NOW)
    assert h.status == ahm.OK


def test_agent_to_dict_shape(tmp_path):
    logp = tmp_path / "h.log"
    _touch(logp, 5)
    plist = {"StartInterval": 300, "StandardOutPath": str(logp)}
    d = ahm.check_agent("com.spa.x", plist, True, _lc("com.spa.x"), NOW).to_dict()
    assert set(d.keys()) == {"label", "status", "pid", "last_exit",
                             "log_age_min", "category", "loaded", "issue"}


# ===========================================================================
# 6. system checks
# ===========================================================================
def _write_json(data_dir: Path, name: str, obj: dict):
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / name).write_text(json.dumps(obj), encoding="utf-8")


def test_system_all_ok(tmp_path):
    d = tmp_path / "data"
    _write_json(d, "equity_curve_daily.json", {"generated_at": "2026-06-21T08:00:00Z"})
    _write_json(d, "cycle_status.json", {"last_run": "2026-06-21T08:00:00Z"})
    _write_json(d, "portfolio_health.json", {"health_score": 95})
    _write_json(d, "red_flags.json", {"red_flags": []})
    push = tmp_path / "push.log"
    _touch(push, 30)
    checks, status, issues = ahm.check_system(d, NOW, str(push))
    assert status == ahm.OK
    assert issues == []
    assert checks["portfolio_health_score"] == 95.0
    assert checks["critical_flags"] == 0


def test_system_stale_equity_critical(tmp_path):
    d = tmp_path / "data"
    _write_json(d, "equity_curve_daily.json", {"generated_at": "2026-06-19T00:00:00Z"})
    checks, status, issues = ahm.check_system(d, NOW, "/nonexistent.log")
    assert status == ahm.CRITICAL
    assert checks["equity_last_update_h"] > ahm.EQUITY_STALE_H


def test_system_stale_cycle_critical(tmp_path):
    d = tmp_path / "data"
    _write_json(d, "cycle_status.json", {"last_run": "2026-06-20T00:00:00Z"})
    checks, status, issues = ahm.check_system(d, NOW, "/nonexistent.log")
    assert status == ahm.CRITICAL
    assert any("cycle" in i for i in issues)


def test_system_low_portfolio_health_warning(tmp_path):
    d = tmp_path / "data"
    _write_json(d, "portfolio_health.json", {"health_score": 63.3})
    checks, status, issues = ahm.check_system(d, NOW, "/nonexistent.log")
    assert status == ahm.WARNING
    assert checks["portfolio_health_score"] == 63.3


def test_system_critical_red_flags(tmp_path):
    # Held-protocol contract (2026-06-23): only CRITICAL flags on protocols we
    # actually HOLD drive system CRITICAL (critical_flags). Flags on external
    # protocols are advisory (advisory_flags / WARNING). aave_v3 is held below.
    d = tmp_path / "data"
    _write_json(d, "current_positions.json", {"positions": {"aave_v3": 50_000.0}})
    _write_json(d, "red_flags.json", {"red_flags": [
        {"protocol": "aave_v3", "severity": "CRITICAL"},   # held → counts
        {"protocol": "pendle", "severity": "critical"},    # external → advisory
        {"severity": "WARN"}]})
    checks, status, issues = ahm.check_system(d, NOW, "/nonexistent.log")
    assert checks["critical_flags"] == 1       # only the held-protocol CRITICAL
    assert checks.get("advisory_flags") == 1   # the external CRITICAL
    assert status == ahm.CRITICAL


def test_system_external_red_flags_advisory(tmp_path):
    # CRITICAL flags on non-held protocols → advisory WARNING, not system CRITICAL.
    d = tmp_path / "data"
    _write_json(d, "current_positions.json", {"positions": {"aave_v3": 50_000.0}})
    _write_json(d, "red_flags.json", {"red_flags": [
        {"protocol": "pendle", "severity": "CRITICAL"},
        {"protocol": "ethena", "severity": "CRITICAL"}]})
    checks, status, issues = ahm.check_system(d, NOW, "/nonexistent.log")
    assert checks["critical_flags"] == 0
    assert checks.get("advisory_flags") == 2
    assert status == ahm.WARNING


def test_system_autopush_lag_warning(tmp_path):
    d = tmp_path / "data"
    d.mkdir(parents=True, exist_ok=True)
    push = tmp_path / "push.log"
    _touch(push, 60 * 3)  # 3h > 2h
    checks, status, issues = ahm.check_system(d, NOW, str(push))
    assert status == ahm.WARNING
    assert checks["autopush_lag_h"] > ahm.AUTOPUSH_LAG_H


def test_system_cycle_fallback_to_cycle_health(tmp_path):
    d = tmp_path / "data"
    _write_json(d, "cycle_health.json",
                {"checks": {"cycle_gap": {"last_cycle_at": "2026-06-21T08:00:00Z"}}})
    checks, status, issues = ahm.check_system(d, NOW, "/nonexistent.log")
    assert checks["cycle_freshness_h"] is not None
    assert abs(checks["cycle_freshness_h"] - 2.0) < 0.01


def test_system_missing_files_no_crash(tmp_path):
    d = tmp_path / "data"
    d.mkdir(parents=True, exist_ok=True)
    checks, status, issues = ahm.check_system(d, NOW, "/nonexistent.log")
    assert status == ahm.OK
    assert checks["critical_flags"] == 0


# ===========================================================================
# 6b. track-accrual SLA (P4-2) — the one thing that matters: the honest
#     go-live track accruing a fresh EVIDENCED bar daily.
# ===========================================================================
def _track_bar(date, evidenced=True):
    return {"date": date, "close_equity": 100000.0, "open_equity": 100000.0,
            "evidenced": evidenced, "source": "cycle" if evidenced else "backfill"}


def test_track_fresh_bar_ok(tmp_path):
    d = tmp_path / "data"
    # NOW = 2026-06-21 → a same-day evidenced bar is fresh
    _write_json(d, "equity_curve_daily.json",
                {"generated_at": "2026-06-21T08:00:00Z",
                 "daily": [_track_bar("2026-06-21")]})
    checks, status, issues = ahm.check_system(d, NOW, "/nonexistent.log")
    assert checks["track_fresh"] is True
    assert not any("track accrual STALE" in i for i in issues)


def test_track_stale_bar_warns(tmp_path):
    d = tmp_path / "data"
    # newest evidenced bar 2026-06-18 → ~88h old at NOW (>30h SLA) → advisory WARN
    _write_json(d, "equity_curve_daily.json",
                {"generated_at": "2026-06-21T08:00:00Z",
                 "daily": [_track_bar("2026-06-18")]})
    checks, status, issues = ahm.check_system(d, NOW, "/nonexistent.log")
    assert checks["track_fresh"] is False
    assert status == ahm.WARNING
    assert any("track accrual STALE" in i for i in issues)


def test_track_non_evidenced_bar_does_not_freshen(tmp_path):
    d = tmp_path / "data"
    # fresh-dated bar but NON-evidenced (backfill) → newest evidenced is old → stale
    _write_json(d, "equity_curve_daily.json",
                {"daily": [_track_bar("2026-06-17", evidenced=True),
                           _track_bar("2026-06-21", evidenced=False)]})
    checks, status, issues = ahm.check_system(d, NOW, "/nonexistent.log")
    assert checks["track_fresh"] is False
    assert any("track accrual STALE" in i for i in issues)


def test_track_no_daily_series_not_flagged(tmp_path):
    # a bare equity file (generated_at only, no `daily`) is NOT a track surface
    # for the SLA check — handled by the equity freshness check, no double-flag.
    d = tmp_path / "data"
    _write_json(d, "equity_curve_daily.json", {"generated_at": "2026-06-21T08:00:00Z"})
    checks, status, issues = ahm.check_system(d, NOW, "/nonexistent.log")
    assert not any("track accrual STALE" in i for i in issues)


def test_track_stale_fires_one_debounced_alert(tmp_path, monkeypatch):
    la, data = _make_env(tmp_path)
    # equity file is fresh by generated_at (so the CRITICAL equity check passes),
    # but the newest EVIDENCED bar is stale → isolates the advisory track-SLA
    # WARNING and lets us demonstrate the debounce (no re-alert every run).
    _write_json(data, "equity_curve_daily.json",
                {"generated_at": "2026-06-21T09:30:00Z",
                 "daily": [_track_bar("2026-06-18")]})  # evidenced bar stale
    # Phase-1 Telegram rebuild: agent_health pushes ONLY on overall CRITICAL via
    # the single push authority (push_policy edge-trigger). An advisory WARNING
    # (stale track) no longer pushes at all — its detail lives in the digest /
    # on-demand views. So here we assert the WARNING is DETECTED but NOT pushed.
    sent = []
    monkeypatch.setattr(ahm, "_push_via_policy", lambda rep: (sent.append(rep) or False))
    lc = "PID\tStatus\tLabel"
    mon = ahm.AgentHealthMonitor(data_dir=data, launch_agents_dir=la,
                                 launchctl_output=lc,
                                 autopush_log="/nonexistent.log", now=NOW)
    rep = mon.run(send=True)
    # advisory WARNING → detected, but no Tier-1 push (WARNING is not critical)
    assert rep["overall_status"] == ahm.WARNING
    assert rep["alert_sent"] is False
    assert any("track accrual STALE" in s for s in rep["system_issues"])


# ===========================================================================
# 7. report assembly + counts
# ===========================================================================
def test_build_report_counts():
    agents = [
        ahm.AgentHealth("a", status=ahm.OK),
        ahm.AgentHealth("b", status=ahm.WARNING, issue="w"),
        ahm.AgentHealth("c", status=ahm.CRITICAL, issue="c"),
    ]
    rep = ahm.build_report(agents, {}, ahm.OK, [], NOW)
    assert rep["healthy_count"] == 1
    assert rep["warning_count"] == 1
    assert rep["critical_count"] == 1
    assert rep["total_agents"] == 3
    assert rep["overall_status"] == ahm.CRITICAL


def test_build_report_overall_from_system():
    agents = [ahm.AgentHealth("a", status=ahm.OK)]
    rep = ahm.build_report(agents, {}, ahm.CRITICAL, ["boom"], NOW)
    assert rep["overall_status"] == ahm.CRITICAL


def test_build_report_all_ok():
    agents = [ahm.AgentHealth("a", status=ahm.OK), ahm.AgentHealth("b", status=ahm.OK)]
    rep = ahm.build_report(agents, {}, ahm.OK, [], NOW)
    assert rep["overall_status"] == ahm.OK


def test_report_json_serializable():
    agents = [ahm.AgentHealth("a", status=ahm.OK)]
    rep = ahm.build_report(agents, {"x": 1}, ahm.OK, [], NOW)
    # round-trips through json
    assert json.loads(json.dumps(rep))["timestamp"] == NOW.isoformat()


# ===========================================================================
# 8. dedup / should_alert
# ===========================================================================
def _report(overall, agents=None, sys_issues=None):
    return {
        "overall_status": overall,
        "agents": agents or [],
        "system_issues": sys_issues or [],
    }


def test_alert_on_critical():
    cur = _report(ahm.CRITICAL, agents=[{"label": "x", "status": ahm.CRITICAL, "issue": "down"}])
    send, new = ahm.should_alert(cur, None)
    assert send is True


def test_no_alert_when_all_ok():
    cur = _report(ahm.OK)
    send, new = ahm.should_alert(cur, None)
    assert send is False
    assert new == []


def test_alert_on_new_warning_issue():
    cur = _report(ahm.WARNING, agents=[{"label": "x", "status": ahm.WARNING, "issue": "stale"}])
    send, new = ahm.should_alert(cur, None)
    assert send is True
    assert "x::stale" in new


def test_dedup_same_issue_no_realert():
    prev = _report(ahm.WARNING, agents=[{"label": "x", "status": ahm.WARNING, "issue": "stale"}])
    cur = _report(ahm.WARNING, agents=[{"label": "x", "status": ahm.WARNING, "issue": "stale"}])
    send, new = ahm.should_alert(cur, prev)
    assert send is False
    assert new == []


def test_dedup_critical_always_alerts():
    # even if identical to previous, CRITICAL re-alerts each run
    prev = _report(ahm.CRITICAL, agents=[{"label": "x", "status": ahm.CRITICAL, "issue": "down"}])
    cur = _report(ahm.CRITICAL, agents=[{"label": "x", "status": ahm.CRITICAL, "issue": "down"}])
    send, new = ahm.should_alert(cur, prev)
    assert send is True


def test_dedup_new_issue_among_old():
    prev = _report(ahm.WARNING, agents=[{"label": "x", "status": ahm.WARNING, "issue": "stale"}])
    cur = _report(ahm.WARNING, agents=[
        {"label": "x", "status": ahm.WARNING, "issue": "stale"},
        {"label": "y", "status": ahm.WARNING, "issue": "stale"}])
    send, new = ahm.should_alert(cur, prev)
    assert send is True
    assert new == ["y::stale"]


def test_dedup_system_issue_tracked():
    prev = _report(ahm.OK)
    cur = _report(ahm.WARNING, sys_issues=["autopush lag 3.0h"])
    send, new = ahm.should_alert(cur, prev)
    assert send is True
    assert "system::autopush lag 3.0h" in new


# ===========================================================================
# 9. alert formatting
# ===========================================================================
def test_format_alert_html():
    rep = {
        "overall_status": ahm.CRITICAL,
        "timestamp": "2026-06-21T10:00:00+00:00",
        "agents": [
            {"label": "com.spa.sky_monitor", "status": ahm.CRITICAL, "issue": "log stale 3h"},
            {"label": "com.spa.fund-api", "status": ahm.WARNING, "issue": "PID=0"},
        ],
        "system_issues": ["portfolio_health 63.3/100"],
    }
    msg = ahm.format_alert(rep)
    assert "<b>SPA Agent Health Alert</b>" in msg
    assert "❌ com.spa.sky_monitor" in msg
    assert "⚠️ com.spa.fund-api" in msg
    assert "portfolio_health 63.3/100" in msg
    assert "2026-06-21 10:00 UTC" in msg
    assert "3 issue(s)" in msg


def test_format_alert_criticals_first():
    rep = {
        "overall_status": ahm.CRITICAL,
        "timestamp": "2026-06-21T10:00:00+00:00",
        "agents": [
            {"label": "w", "status": ahm.WARNING, "issue": "warn"},
            {"label": "c", "status": ahm.CRITICAL, "issue": "crit"},
        ],
        "system_issues": [],
    }
    msg = ahm.format_alert(rep)
    assert msg.index("❌ c") < msg.index("⚠️ w")


# ===========================================================================
# 10. end-to-end run (mocked launchctl + temp dirs), output + dedup + fail-safe
# ===========================================================================
def _make_env(tmp_path):
    la = tmp_path / "LaunchAgents"
    la.mkdir()
    data = tmp_path / "data"
    data.mkdir()
    return la, data


def test_run_writes_output_and_dedups(tmp_path, monkeypatch):
    la, data = _make_env(tmp_path)
    # one healthy high-freq agent
    logp = tmp_path / "ok.log"
    _touch(logp, 2)
    _write_plist(la / "com.spa.ok.plist", label="com.spa.ok",
                 start_interval=300, log_path=str(logp))
    # all system files fresh
    _write_json(data, "equity_curve_daily.json", {"generated_at": "2026-06-21T09:30:00Z"})
    _write_json(data, "red_flags.json", {"red_flags": []})
    push = tmp_path / "push.log"
    _touch(push, 10)

    sent = []
    # When all OK, _push_via_policy is still invoked (it emits the edge-triggered
    # RESOLVED if we were previously bad — a no-op otherwise) and returns False
    # (nothing pushed). Capture the call to prove no Tier-1 push happened.
    monkeypatch.setattr(ahm, "_push_via_policy", lambda rep: (sent.append(rep) or False))

    lc = "PID\tStatus\tLabel\n55\t0\tcom.spa.ok"
    mon = ahm.AgentHealthMonitor(data_dir=data, launch_agents_dir=la,
                                 launchctl_output=lc, autopush_log=str(push), now=NOW)
    rep = mon.run(send=True)
    assert rep["overall_status"] == ahm.OK
    assert rep["alert_sent"] is False  # no Tier-1 push when all OK
    # output file written
    assert (data / "agent_health.json").exists()
    saved = json.loads((data / "agent_health.json").read_text())
    assert saved["healthy_count"] == 1


def test_run_sends_alert_on_critical(tmp_path, monkeypatch):
    la, data = _make_env(tmp_path)
    # agent not in launchctl → critical
    _write_plist(la / "com.spa.down.plist", label="com.spa.down",
                 keepalive=True, log_path="/tmp/x.log")
    sent = []
    # CRITICAL → one Tier-1 push via the single push authority.
    monkeypatch.setattr(ahm, "_push_via_policy", lambda rep: (sent.append(rep) or True))

    lc = "PID\tStatus\tLabel"  # nothing loaded
    mon = ahm.AgentHealthMonitor(data_dir=data, launch_agents_dir=la,
                                 launchctl_output=lc, autopush_log="/nonexistent.log", now=NOW)
    rep = mon.run(send=True)
    assert rep["overall_status"] == ahm.CRITICAL
    assert len(sent) == 1
    assert rep["alert_sent"] is True


def test_run_check_does_not_send(tmp_path, monkeypatch):
    la, data = _make_env(tmp_path)
    _write_plist(la / "com.spa.down.plist", label="com.spa.down",
                 keepalive=True, log_path="/tmp/x.log")
    sent = []
    monkeypatch.setattr(ahm, "_push_via_policy", lambda rep: (sent.append(rep) or True))
    lc = "PID\tStatus\tLabel"
    mon = ahm.AgentHealthMonitor(data_dir=data, launch_agents_dir=la,
                                 launchctl_output=lc, autopush_log="/nonexistent.log", now=NOW)
    rep = mon.run(send=False)
    assert rep["overall_status"] == ahm.CRITICAL
    assert sent == []  # send=False suppresses the push entirely


def test_run_second_call_dedups(tmp_path, monkeypatch):
    """A persistent CRITICAL pushes ONCE then is silent — the edge-trigger fix.

    Phase-1 Telegram rebuild: dedup of a standing problem is now owned by
    push_policy's edge-trigger (push on entry, silent while it persists), NOT by
    the prior-JSON diff. We drive the real push_policy with a tmp data dir and a
    mocked transport, and assert the hourly re-fire is gone.
    """
    from spa_core.telegram import push_policy
    la, data = _make_env(tmp_path)
    # An always-on agent that is NOT loaded → CRITICAL on every run (persists).
    _write_plist(la / "com.spa.down.plist", label="com.spa.down",
                 keepalive=True, log_path="/tmp/x.log")
    sent = []
    monkeypatch.setattr(push_policy, "_send", lambda text: (sent.append(text) or True))
    # Point push_policy state at the tmp data dir so it survives across "runs".
    monkeypatch.setattr(ahm, "_push_via_policy",
                        lambda rep: _push_via_tmp(rep, data))
    lc = "PID\tStatus\tLabel"  # nothing loaded → CRITICAL
    mon = ahm.AgentHealthMonitor(data_dir=data, launch_agents_dir=la,
                                 launchctl_output=lc, autopush_log="/nonexistent.log", now=NOW)
    mon.run(send=True)   # first: entry transition → push once
    assert len(sent) == 1
    mon2 = ahm.AgentHealthMonitor(data_dir=data, launch_agents_dir=la,
                                  launchctl_output=lc, autopush_log="/nonexistent.log", now=NOW)
    mon2.run(send=True)  # second: still CRITICAL → SILENT (edge-trigger)
    assert len(sent) == 1


def _push_via_tmp(report, data_dir):
    """Test helper: run the real edge-trigger against a tmp data dir."""
    from spa_core.telegram import push_policy
    if report.get("overall_status") == ahm.CRITICAL:
        return push_policy.push_critical(
            "agent_health_critical", "CRITICAL", "t", "b", data_dir=str(data_dir)
        )
    return push_policy.resolve("agent_health_critical", "ok", data_dir=str(data_dir))


def test_run_failsafe_never_raises(tmp_path, monkeypatch):
    la, data = _make_env(tmp_path)
    mon = ahm.AgentHealthMonitor(data_dir=data, launch_agents_dir=la,
                                 launchctl_output="PID\tStatus\tLabel", now=NOW)
    # force collect() to blow up
    monkeypatch.setattr(mon, "collect", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    rep = mon.run(send=False)
    assert rep["overall_status"] == ahm.CRITICAL
    assert "error" in rep


def test_malformed_plist_regex_fallback(tmp_path):
    # a malformed plist with extractable fields via regex
    p = tmp_path / "com.spa.bad.plist"
    p.write_text(
        "<plist><dict>\n"
        "<!-- bad -- comment with double dash -->\n"
        "<key>StartInterval</key><integer>300</integer>\n"
        "<key>StandardOutPath</key><string>/tmp/bad.log</string>\n"
        "</dict></plist>", encoding="utf-8")
    plist, ok = ahm._load_plist(p)
    # plistlib may or may not reject; if it rejected, regex fallback fills fields
    assert plist is not None
    assert plist.get("StartInterval") == 300 or ok


def test_main_check_smoke(tmp_path, monkeypatch, capsys):
    la, data = _make_env(tmp_path)
    logp = tmp_path / "ok.log"
    _touch(logp, 2)
    _write_plist(la / "com.spa.ok.plist", label="com.spa.ok",
                 start_interval=300, log_path=str(logp))
    monkeypatch.setattr(ahm, "_run_launchctl_list",
                        lambda: "PID\tStatus\tLabel\n5\t0\tcom.spa.ok")
    rc = ahm.main(["--check", "--data-dir", str(data), "--launch-agents-dir", str(la)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Overall:" in out


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
