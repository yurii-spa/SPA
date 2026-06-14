"""P3-2 tests — Telegram down-alerts for launchd agents (uptime_monitor).

Exercises _process_agent_alerts on a tmp data dir. The Telegram send helper
(_send_agent_alert) is mocked everywhere — no real Keychain reads, no real
Telegram API calls.

Covered cases:
  * test_alert_sent_on_state_change_to_down  — running→down fires one alert
  * test_no_alert_if_already_down            — down→down fires nothing
  * test_no_alert_if_still_running           — running→running fires nothing
  * test_rate_limit_1hr                      — second down within 1h suppressed
  * test_prev_state_written                  — running-state persisted to disk
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

from spa_core.monitoring import uptime_monitor as um


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _checks(running: bool, age_seconds: int = 600) -> dict:
    """Build a minimal checks dict with a single launchd agent."""
    return {
        "launchd_daily_cycle": {
            "running": running,
            "method": "output_file_age",
            "age_seconds": age_seconds,
            "file": "data/paper_trading_status.json",
        }
    }


def _write_prev(data_dir: Path, agents: dict, alerts: dict | None = None) -> None:
    """Seed uptime_prev_state.json directly."""
    state = {"agents": agents, "alerts": alerts or {}}
    (data_dir / um.UPTIME_PREV_STATE_FILE).write_text(
        json.dumps(state), encoding="utf-8"
    )


# ─── Tests ───────────────────────────────────────────────────────────────────


def test_alert_sent_on_state_change_to_down(tmp_path: Path) -> None:
    """Agent was running last run, now down → exactly one Telegram alert."""
    _write_prev(tmp_path, {"com.spa.daily_cycle": {"running": True}})

    with mock.patch.object(
        um, "_send_agent_alert", return_value=True
    ) as send:
        um._process_agent_alerts(tmp_path, _checks(running=False, age_seconds=600), now=1000.0)

    send.assert_called_once()
    label, age_minutes, file_hint = send.call_args.args
    assert label == "com.spa.daily_cycle"
    assert age_minutes == 10  # 600s // 60
    assert file_hint == "data/paper_trading_status.json"


def test_no_alert_if_already_down(tmp_path: Path) -> None:
    """Agent was already down last run → no alert (no transition)."""
    _write_prev(tmp_path, {"com.spa.daily_cycle": {"running": False}})

    with mock.patch.object(um, "_send_agent_alert", return_value=True) as send:
        um._process_agent_alerts(tmp_path, _checks(running=False), now=1000.0)

    send.assert_not_called()


def test_no_alert_if_still_running(tmp_path: Path) -> None:
    """Agent still running → no alert."""
    _write_prev(tmp_path, {"com.spa.daily_cycle": {"running": True}})

    with mock.patch.object(um, "_send_agent_alert", return_value=True) as send:
        um._process_agent_alerts(tmp_path, _checks(running=True), now=1000.0)

    send.assert_not_called()


def test_rate_limit_1hr(tmp_path: Path) -> None:
    """A second running→down within 1h is suppressed; after 1h it fires again."""
    # First transition fires and records the alert timestamp at t=1000.
    _write_prev(tmp_path, {"com.spa.daily_cycle": {"running": True}})
    with mock.patch.object(um, "_send_agent_alert", return_value=True) as send1:
        um._process_agent_alerts(tmp_path, _checks(running=False), now=1000.0)
    send1.assert_called_once()

    # Simulate a flap back to running, then down again 30 min later (< 1h) →
    # rate-limited, no alert.
    _write_prev(
        tmp_path,
        {"com.spa.daily_cycle": {"running": True}},
        alerts={"com.spa.daily_cycle": 1000.0},
    )
    with mock.patch.object(um, "_send_agent_alert", return_value=True) as send2:
        um._process_agent_alerts(tmp_path, _checks(running=False), now=1000.0 + 1800)
    send2.assert_not_called()

    # Down again > 1h after the last alert → fires.
    _write_prev(
        tmp_path,
        {"com.spa.daily_cycle": {"running": True}},
        alerts={"com.spa.daily_cycle": 1000.0},
    )
    with mock.patch.object(um, "_send_agent_alert", return_value=True) as send3:
        um._process_agent_alerts(tmp_path, _checks(running=False), now=1000.0 + 3700)
    send3.assert_called_once()


def test_prev_state_written(tmp_path: Path) -> None:
    """Fresh running-state is persisted to uptime_prev_state.json each run."""
    with mock.patch.object(um, "_send_agent_alert", return_value=True):
        um._process_agent_alerts(tmp_path, _checks(running=True), now=1000.0)

    path = tmp_path / um.UPTIME_PREV_STATE_FILE
    assert path.exists()
    state = json.loads(path.read_text(encoding="utf-8"))
    assert state["agents"]["com.spa.daily_cycle"]["running"] is True
    assert "alerts" in state
