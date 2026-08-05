"""S2 (2026-08-05) — consumers of data/agent_health.json must SEE staleness.

Incident replayed here: at 08:43 the snapshot was 8h old (the hourly monitor
was itself down since 07:00Z), yet every owner-facing surface kept rendering
its "healthy 69/69, critical 0" as CURRENT fleet state. These are the
POSITIVE CONTROLS for the consumer wiring: on unfixed code the stale snapshot
renders as calm/healthy and every test here reds.

Hermetic: all reads are pointed at a tmp data dir; nothing touches live data/.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from spa_core.monitoring import agent_health_monitor as ahm

NOW = datetime(2026, 8, 5, 8, 43, 0, tzinfo=timezone.utc)


def _write_stale_healthy_snapshot(data: Path, hours_old: float = 8.0) -> None:
    ts = datetime(2026, 8, 5, 8, 43, tzinfo=timezone.utc)
    old = ts.timestamp() - hours_old * 3600.0
    old_iso = datetime.fromtimestamp(old, tz=timezone.utc).isoformat()
    (data / "agent_health.json").write_text(json.dumps({
        "timestamp": old_iso,
        "overall_status": "OK",
        "healthy_count": 69, "warning_count": 0, "critical_count": 0,
        "total_agents": 69,
        "agents": [], "system_checks": {}, "system_issues": [],
    }), encoding="utf-8")


@pytest.fixture
def stale_data_dir(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    _write_stale_healthy_snapshot(data)
    return data


# ── telegram /warnings view ──────────────────────────────────────────────────
def test_warnings_view_surfaces_stale_snapshot(stale_data_dir, monkeypatch):
    from spa_core.telegram.views import _base as B
    from spa_core.telegram.views import warnings as W

    monkeypatch.setattr(B, "DATA_DIR", stale_data_dir)
    warns = W._active_warnings()

    stale = [w for w in warns if w.get("key") == "agent_health_stale"]
    assert stale, "an 8h-old snapshot must surface as a warning, not as calm"
    assert "UNKNOWN" in stale[0]["detail"]
    # and the stale healthy snapshot must NOT show up as a CRITICAL fleet claim
    assert not any(w.get("key") == "agent_health" for w in warns)


def test_warnings_view_quiet_on_fresh_healthy_snapshot(tmp_path, monkeypatch):
    # Control: a FRESH healthy snapshot produces no agent_health warnings.
    from spa_core.telegram.views import _base as B
    from spa_core.telegram.views import warnings as W

    data = tmp_path / "data"
    data.mkdir()
    (data / "agent_health.json").write_text(json.dumps({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "overall_status": "OK", "healthy_count": 69, "critical_count": 0,
        "total_agents": 69, "agents": [],
    }), encoding="utf-8")
    monkeypatch.setattr(B, "DATA_DIR", data)
    warns = W._active_warnings()
    assert not any(str(w.get("key", "")).startswith("agent_health") for w in warns)


# ── telegram /health views ───────────────────────────────────────────────────
def test_health_menu_marks_stale_snapshot(stale_data_dir, monkeypatch):
    from spa_core.telegram.views import _base as B
    from spa_core.telegram.views import health as H

    monkeypatch.setattr(B, "DATA_DIR", stale_data_dir)
    text, _kb = H.render_menu()
    assert "STALE" in text
    assert "UNKNOWN" in text


def test_health_agents_overall_shows_stale_not_ok(stale_data_dir, monkeypatch):
    from spa_core.telegram.views import _base as B
    from spa_core.telegram.views import health as H

    monkeypatch.setattr(B, "DATA_DIR", stale_data_dir)
    ah = H._read_agent_health()
    assert ah["snapshot_stale"] is True
    assert ah["overall_status"] == ahm.STALE  # never "OK" from an 8h-old file


# ── /status summary block ────────────────────────────────────────────────────
def test_status_summary_agents_block_marks_stale(stale_data_dir, monkeypatch):
    from spa_core.telegram import status_summary as S

    monkeypatch.setattr(S, "_REPO", stale_data_dir.parent)
    # no launchctl in CI — the loaded count degrades to "?", that's fine
    block = S._agents_block()
    assert "НЕСВЕЖИЙ" in block
    assert "CRITICAL: 0" not in block  # the stale zero may not read as calm
