"""Churn investigation tooling: scripts/analyze_cycle_kickstart_correlation.py correlates
daily_cycle run timestamps against the deploy-gate kickstart marker log. Pure function tests —
no real /tmp files, no network, no risk-path import.
"""
import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "analyze_cycle_kickstart_correlation", _REPO_ROOT / "scripts" / "analyze_cycle_kickstart_correlation.py"
)
mod = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = mod
_SPEC.loader.exec_module(mod)


def _ts(iso: str) -> datetime:
    return datetime.strptime(iso, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)


def test_run_within_tolerance_after_kickstart_is_explained():
    gate = [_ts("2026-09-03T10:00:00")]
    cycle = [_ts("2026-09-03T10:00:45")]  # 45s after kickstart — launchctl isn't instant
    explained, unexplained = mod.correlate(cycle, gate, tolerance_seconds=120)
    assert explained == cycle
    assert unexplained == []


def test_run_before_any_kickstart_is_unexplained():
    gate = [_ts("2026-09-03T10:05:00")]
    cycle = [_ts("2026-09-03T10:00:00")]  # cycle ran BEFORE the gate fired — can't be caused by it
    explained, unexplained = mod.correlate(cycle, gate, tolerance_seconds=120)
    assert explained == []
    assert unexplained == cycle


def test_run_far_outside_window_is_unexplained():
    gate = [_ts("2026-09-03T08:00:00")]
    cycle = [_ts("2026-09-03T10:00:00")]  # 2h later, way outside a 120s tolerance
    explained, unexplained = mod.correlate(cycle, gate, tolerance_seconds=120)
    assert explained == []
    assert unexplained == cycle


def test_no_gate_kickstarts_leaves_everything_unexplained():
    cycle = [_ts("2026-09-03T08:00:00"), _ts("2026-09-03T12:00:00")]
    explained, unexplained = mod.correlate(cycle, [], tolerance_seconds=120)
    assert explained == []
    assert unexplained == cycle


def test_parse_cycle_start_line():
    (line_ts,) = [
        mod._parse_ts(m.group(1))
        for m in [mod._CYCLE_START_RE.match("[2026-08-20T22:13:58Z] Starting daily paper cycle (cycle_runner)")]
        if m
    ]
    assert line_ts == _ts("2026-08-20T22:13:58")


def test_parse_marker_line_filters_by_label():
    hit = mod._MARKER_RE.match("2026-09-03T10:00:00Z gate-kickstart label=com.spa.daily_cycle keepalive=0")
    miss = mod._MARKER_RE.match("2026-09-03T10:00:00Z gate-kickstart label=com.spa.telegram_bot keepalive=1")
    assert hit.group(2) == "com.spa.daily_cycle"
    assert miss.group(2) != "com.spa.daily_cycle"


def test_load_gate_kickstarts_missing_file_returns_empty(tmp_path):
    assert mod.load_gate_kickstarts(tmp_path / "does_not_exist.log", mod.LABEL) == []


def test_load_gate_kickstarts_reads_and_filters(tmp_path):
    marker = tmp_path / "marker.log"
    marker.write_text(
        "2026-09-03T10:00:00Z gate-kickstart label=com.spa.daily_cycle keepalive=0\n"
        "2026-09-03T11:00:00Z gate-kickstart label=com.spa.telegram_bot keepalive=1\n"
        "2026-09-03T12:00:00Z gate-kickstart label=com.spa.daily_cycle keepalive=0\n"
    )
    got = mod.load_gate_kickstarts(marker, mod.LABEL)
    assert got == [_ts("2026-09-03T10:00:00"), _ts("2026-09-03T12:00:00")]


def test_load_cycle_starts_reads_multiple_log_files(tmp_path):
    (tmp_path / "daily_cycle_20260903.log").write_text(
        "[2026-09-03T08:00:01Z] Starting daily paper cycle (cycle_runner)\n"
        "[2026-09-03T08:00:01Z] some other line\n"
    )
    (tmp_path / "daily_cycle_20260904.log").write_text(
        "[2026-09-04T08:00:02Z] Starting daily paper cycle (cycle_runner)\n"
    )
    got = mod.load_cycle_starts(tmp_path)
    assert got == [_ts("2026-09-03T08:00:01"), _ts("2026-09-04T08:00:02")]
