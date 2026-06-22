"""Tests for the MP-107 daily-monitors wiring in cycle_runner.

Covers ``_run_daily_monitors`` — the once-per-day refresh of
red_flags.json / governance_proposals.json / incidents.json. All runs are
``offline=True`` (bootstrap fixtures), so the suite never touches the network.
"""
from __future__ import annotations

import json

from spa_core.paper_trading.cycle_runner import _run_daily_monitors


def _load(tmp_path, name):
    p = tmp_path / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def test_daily_monitors_offline_write_all_three_snapshots(tmp_path):
    results = _run_daily_monitors(tmp_path, offline=True)
    assert results == {
        "red_flags": "ok", "governance": "ok", "incidents": "ok",
        "adapter_watchdog": "ok", "alpha_scan": "ok", "protocol_research": "ok",
    }

    red_flags = _load(tmp_path, "red_flags.json")
    assert isinstance(red_flags, dict) and "red_flags" in red_flags

    governance = _load(tmp_path, "governance_proposals.json")
    assert isinstance(governance, dict) and "proposals" in governance
    assert not governance.get("error")

    incidents = _load(tmp_path, "incidents.json")
    assert isinstance(incidents, dict) and incidents.get("total_incidents", 0) > 0


def test_daily_monitors_failsafe_one_broken_monitor(tmp_path, monkeypatch):
    """One crashing monitor must not block the others or raise."""
    import spa_core.alerts.red_flag_monitor as rfm

    class _Boom:
        def __init__(self, *a, **kw):
            raise RuntimeError("red flag monitor exploded")

    monkeypatch.setattr(rfm, "RedFlagMonitor", _Boom)
    results = _run_daily_monitors(tmp_path, offline=True)

    assert results["red_flags"].startswith("error:")
    assert results["governance"] == "ok"
    assert results["incidents"] == "ok"
    assert not (tmp_path / "red_flags.json").exists()
    assert (tmp_path / "governance_proposals.json").exists()
    assert (tmp_path / "incidents.json").exists()


def test_daily_monitors_failsafe_all_broken(tmp_path, monkeypatch):
    """Even with every monitor broken, the function returns (never raises)."""
    import spa_core.alerts.governance_watcher as gw
    import spa_core.alerts.red_flag_monitor as rfm
    import spa_core.data_pipeline.incidents_fetcher as inf
    import spa_core.scheduler.adapter_watchdog as awd
    import spa_core.agents.alpha_agent as aa
    import spa_core.agents.protocol_research_agent as pra

    def _boom(*a, **kw):
        raise RuntimeError("boom")

    monkeypatch.setattr(rfm, "RedFlagMonitor", _boom)
    monkeypatch.setattr(gw, "GovernanceWatcher", _boom)
    monkeypatch.setattr(inf, "build_incidents_snapshot", _boom)
    monkeypatch.setattr(awd, "run_watchdog_cycle", _boom)
    monkeypatch.setattr(aa, "run_alpha_scan", _boom)
    monkeypatch.setattr(pra, "run_research_cycle", _boom)

    results = _run_daily_monitors(tmp_path, offline=True)
    assert all(v.startswith("error:") for v in results.values())
    assert set(results) == {
        "red_flags", "governance", "incidents",
        "adapter_watchdog", "alpha_scan", "protocol_research",
    }


def test_governance_export_error_is_not_persisted(tmp_path, monkeypatch):
    """GovernanceWatcher.export returning {'error': ...} must not overwrite
    the previous snapshot with a broken document."""
    import spa_core.alerts.governance_watcher as gw

    class _ErrWatcher:
        def __init__(self, *a, **kw):
            pass

        def export(self, **kw):
            return {"error": "snapshot api down", "proposals": []}

    monkeypatch.setattr(gw, "GovernanceWatcher", _ErrWatcher)
    results = _run_daily_monitors(tmp_path, offline=True)

    assert results["governance"] == "error: snapshot api down"
    assert not (tmp_path / "governance_proposals.json").exists()
    # the other two are unaffected
    assert results["red_flags"] == "ok"
    assert results["incidents"] == "ok"


def test_monitors_write_atomically_valid_json(tmp_path):
    """Snapshots must be parseable immediately after the call (atomic write:
    tmp + os.replace — no partial files left behind)."""
    _run_daily_monitors(tmp_path, offline=True)
    for name in ("red_flags.json", "governance_proposals.json", "incidents.json"):
        json.loads((tmp_path / name).read_text(encoding="utf-8"))  # must not raise
    leftovers = [p.name for p in tmp_path.iterdir() if p.suffix == ".tmp"]
    assert leftovers == []
