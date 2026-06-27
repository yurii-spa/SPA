"""
spa_core/tests/test_resilience_status.py — tests for the R8 resilience rollup.

Proves spa_core.monitoring.resilience_status.build_posture:
  * all three proofs fresh + passing → overall OK,
  * a STALE proof (old timestamp) → WARNING + a note,
  * a FAILED proof (all_ok / passed false) → WARNING + a note,
  * a MISSING status file → "never run" + WARNING,
  * an UNVERIFIED offsite copy → WARNING; a local-stand-in dest alone does NOT
    force WARNING (mechanism proven, owner-flagged note only),
  * write_status writes data/resilience_status.json atomically with the posture,
and the briefing section renders the posture + STALE / never-run markers.

Deterministic: `now` is injected and the status paths are monkeypatched at the
tmp dir so the live data/ track is never read or written.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from spa_core.monitoring import resilience_status as rs

NOW = datetime(2026, 6, 27, 12, 0, 0, tzinfo=timezone.utc)


def _ts(days_ago: float) -> str:
    from datetime import timedelta
    return (NOW - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture
def status_dir(tmp_path, monkeypatch):
    """Point the rollup's three input paths + output at a tmp dir."""
    monkeypatch.setattr(rs, "OFFSITE_STATUS", tmp_path / "dr_offsite_status.json")
    monkeypatch.setattr(rs, "RESTORE_STATUS", tmp_path / "restore_drill_status.json")
    monkeypatch.setattr(rs, "FLEET_STATUS", tmp_path / "fleet_drill_status.json")
    monkeypatch.setattr(rs, "OUTPUT", tmp_path / "resilience_status.json")
    return tmp_path


def _write(path: Path, obj: dict) -> None:
    path.write_text(json.dumps(obj))


def _fresh_offsite(verified=True, real_remote=False, days_ago=0.5) -> dict:
    return {
        "last_offsite_ts": _ts(days_ago),
        "verified": verified,
        "is_real_remote": real_remote,
        "archive_name": "spa_state_2026-06-27.tar.gz",
    }


def _fresh_restore(all_ok=True, days_ago=1.0) -> dict:
    return {"last_drill_ts": _ts(days_ago), "all_ok": all_ok,
            "schema": "spa_restore_drill/v1"}


def _fresh_fleet(passed=True, days_ago=1.0) -> dict:
    return {"generated_at": _ts(days_ago), "passed": passed,
            "module": "drill_fleet_down"}


# ── overall posture ───────────────────────────────────────────────────────────────
def test_all_fresh_and_ok_is_OK(status_dir):
    _write(status_dir / "dr_offsite_status.json", _fresh_offsite())
    _write(status_dir / "restore_drill_status.json", _fresh_restore())
    _write(status_dir / "fleet_drill_status.json", _fresh_fleet())

    p = rs.build_posture(now=NOW)
    assert p["overall"] == "OK"
    assert p["offsite"]["verified"] is True
    assert p["restore_drill"]["all_ok"] is True
    assert p["fleet_drill"]["all_ok"] is True
    assert all(not x["stale"] and not x["never_run"]
               for x in (p["offsite"], p["restore_drill"], p["fleet_drill"]))


def test_local_standin_alone_does_not_warn(status_dir):
    """A non-real-remote (local stand-in) offsite dest is owner-flagged but the
    mechanism is proven → still OK, with an owner-flagged note."""
    _write(status_dir / "dr_offsite_status.json",
           _fresh_offsite(verified=True, real_remote=False))
    _write(status_dir / "restore_drill_status.json", _fresh_restore())
    _write(status_dir / "fleet_drill_status.json", _fresh_fleet())

    p = rs.build_posture(now=NOW)
    assert p["overall"] == "OK"
    assert any("stand-in" in n for n in p["notes"])


def test_stale_restore_drill_warns(status_dir):
    _write(status_dir / "dr_offsite_status.json", _fresh_offsite())
    _write(status_dir / "restore_drill_status.json",
           _fresh_restore(days_ago=rs.DRILL_STALE_DAYS + 1))  # > 8d → stale
    _write(status_dir / "fleet_drill_status.json", _fresh_fleet())

    p = rs.build_posture(now=NOW)
    assert p["overall"] == "WARNING"
    assert p["restore_drill"]["stale"] is True
    assert any("restore_drill" in n and "STALE" in n for n in p["notes"])


def test_stale_offsite_warns(status_dir):
    _write(status_dir / "dr_offsite_status.json",
           _fresh_offsite(days_ago=rs.OFFSITE_STALE_DAYS + 1))  # > 2d → stale
    _write(status_dir / "restore_drill_status.json", _fresh_restore())
    _write(status_dir / "fleet_drill_status.json", _fresh_fleet())

    p = rs.build_posture(now=NOW)
    assert p["overall"] == "WARNING"
    assert p["offsite"]["stale"] is True


def test_failed_fleet_drill_warns(status_dir):
    _write(status_dir / "dr_offsite_status.json", _fresh_offsite())
    _write(status_dir / "restore_drill_status.json", _fresh_restore())
    _write(status_dir / "fleet_drill_status.json", _fresh_fleet(passed=False))

    p = rs.build_posture(now=NOW)
    assert p["overall"] == "WARNING"
    assert p["fleet_drill"]["all_ok"] is False
    assert any("fleet_drill" in n and "did NOT pass" in n for n in p["notes"])


def test_unverified_offsite_warns(status_dir):
    _write(status_dir / "dr_offsite_status.json", _fresh_offsite(verified=False))
    _write(status_dir / "restore_drill_status.json", _fresh_restore())
    _write(status_dir / "fleet_drill_status.json", _fresh_fleet())

    p = rs.build_posture(now=NOW)
    assert p["overall"] == "WARNING"
    assert any("NOT verified" in n for n in p["notes"])


# ── missing → never run ───────────────────────────────────────────────────────────
def test_missing_status_is_never_run_and_warns(status_dir):
    # only write the offsite + restore; fleet is absent
    _write(status_dir / "dr_offsite_status.json", _fresh_offsite())
    _write(status_dir / "restore_drill_status.json", _fresh_restore())

    p = rs.build_posture(now=NOW)
    assert p["overall"] == "WARNING"
    assert p["fleet_drill"]["never_run"] is True
    assert p["fleet_drill"]["stale"] is True
    assert any("fleet_drill: never run" in n for n in p["notes"])


def test_all_missing_is_warning(status_dir):
    p = rs.build_posture(now=NOW)
    assert p["overall"] == "WARNING"
    for k in ("offsite", "restore_drill", "fleet_drill"):
        assert p[k]["never_run"] is True


# ── timestamp parsing tolerance ───────────────────────────────────────────────────
def test_isoformat_offset_timestamp_parses(status_dir):
    """Producers emit '...+00:00' (restore/fleet); ensure age derives, not stale."""
    iso = NOW.isoformat()  # '2026-06-27T12:00:00+00:00'
    _write(status_dir / "dr_offsite_status.json",
           {**_fresh_offsite(), "last_offsite_ts": iso})
    _write(status_dir / "restore_drill_status.json",
           {"last_drill_ts": iso, "all_ok": True})
    _write(status_dir / "fleet_drill_status.json",
           {"generated_at": iso, "passed": True})

    p = rs.build_posture(now=NOW)
    assert p["overall"] == "OK"


# ── write_status atomic output ────────────────────────────────────────────────────
def test_write_status_writes_output(status_dir):
    _write(status_dir / "dr_offsite_status.json", _fresh_offsite())
    _write(status_dir / "restore_drill_status.json", _fresh_restore())
    _write(status_dir / "fleet_drill_status.json", _fresh_fleet())

    p = rs.write_status()
    out = status_dir / "resilience_status.json"
    assert out.exists()
    written = json.loads(out.read_text())
    assert written["overall"] == p["overall"]
    assert written["schema"] == "spa_resilience_status/v1"
    assert written["llm_forbidden"] is True


# ── briefing section rendering ────────────────────────────────────────────────────
def _load_briefing(monkeypatch, data_dir: Path):
    """Import update_system_briefing as a module pointed at a tmp data dir."""
    import importlib.util
    script = Path(__file__).resolve().parents[2] / "scripts" / "update_system_briefing.py"
    spec = importlib.util.spec_from_file_location("usb_test", script)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.DATA_DIR = str(data_dir)
    return mod


def test_briefing_section_renders_ok(status_dir, monkeypatch):
    # write a fresh OK rollup directly (the section reads resilience_status.json)
    rollup = {
        "overall": "OK",
        "generated_at": _ts(0),
        "offsite": {"last_ts": _ts(0.5), "verified": True, "is_real_remote": False,
                    "stale": False, "never_run": False},
        "restore_drill": {"last_ts": _ts(1), "all_ok": True, "stale": False, "never_run": False},
        "fleet_drill": {"last_ts": _ts(1), "all_ok": True, "stale": False, "never_run": False},
        "notes": ["offsite: dest is the LOCAL stand-in (no real remote configured) [owner-flagged]"],
    }
    _write(status_dir / "resilience_status.json", rollup)
    usb = _load_briefing(monkeypatch, status_dir)
    out = usb.build_resilience_section()
    assert "Resilience" in out
    assert "OK" in out
    assert "Offsite copy" in out
    assert "Restore drill" in out
    assert "Fleet-down drill" in out
    assert "STALE" not in out  # nothing stale in this fixture's proof lines


def test_briefing_section_renders_stale_and_never_run(status_dir, monkeypatch):
    rollup = {
        "overall": "WARNING",
        "generated_at": _ts(0),
        "offsite": {"last_ts": _ts(5), "verified": True, "is_real_remote": True,
                    "stale": True, "never_run": False},
        "restore_drill": {"last_ts": _ts(2), "all_ok": True, "stale": False, "never_run": False},
        "fleet_drill": {"last_ts": None, "all_ok": False, "stale": True, "never_run": True},
        "notes": ["offsite: STALE (> 2d since last copy)",
                  "fleet_drill: never run (fleet_drill_status.json missing)"],
    }
    _write(status_dir / "resilience_status.json", rollup)
    usb = _load_briefing(monkeypatch, status_dir)
    out = usb.build_resilience_section()
    assert "WARNING" in out
    assert "STALE" in out
    assert "NEVER RUN" in out
    assert "Why WARNING" in out


def test_briefing_section_missing_rollup(status_dir, monkeypatch):
    usb = _load_briefing(monkeypatch, status_dir)  # no resilience_status.json written
    out = usb.build_resilience_section()
    assert "ROLLUP UNAVAILABLE" in out
