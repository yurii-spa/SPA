"""
spa_core/tests/test_resilience_status.py — tests for the R8 resilience rollup.

Proves spa_core.monitoring.resilience_status.build_posture:
  * all three proofs fresh + passing + a REAL remote → overall OK,
  * all three proofs fresh + passing but the offsite dest is same-host → overall
    SAME_HOST — ADR-580 C10 (RM-TRUTH-01), see the CHANGE below,
  * a STALE proof (old timestamp) → WARNING + a note,
  * a FAILED proof (all_ok / passed false) → WARNING + a note,
  * a MISSING status file → "never run" + WARNING,
  * an UNVERIFIED offsite copy → WARNING,
  * write_status writes data/resilience_status.json atomically with the posture,
and the briefing section renders the posture + STALE / never-run markers.

CHANGE (ADR-580 C10, 2026-10-05): this file used to pin `test_local_standin_alone_does_not_warn`
— "a local-stand-in (not real remote) offsite dest ... still OK, with an owner-flagged note".
REVIEW_1 (RM-TRUTH-01 A4) measured that this IS the real production state (`dr_offsite_status.json`
has `is_real_remote: false` — the "offsite" copy lives on the same Mac mini as everything it is
meant to survive losing) and named it as dishonest: "offsite is reported OK/green while
is_real_remote is false". Per the new contract, "offsite" means `is_real_remote: true`; until
then the rollup reports the distinct value SAME_HOST, never OK. The old test is renamed/rewritten
below (`test_local_standin_alone_reports_same_host_not_ok`) to pin the CORRECTED behaviour instead
of the bug; this is an intentional test-behavior change per inv #16, recorded here and in the
owning commit (journal entry owed — not written by this worktree per its own instructions).

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


def _fresh_offsite(verified=True, real_remote=True, days_ago=0.5) -> dict:
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


def test_local_standin_alone_reports_same_host_not_ok(status_dir):
    """ADR-580 C10: a non-real-remote (local stand-in) offsite dest, with every OTHER
    proof fresh and passing, must report the distinct SAME_HOST value — never OK/green,
    and never folded into the generic WARNING either (it is not a FAILED proof, it is an
    honestly-named degraded one). The owner-flagged note stays."""
    _write(status_dir / "dr_offsite_status.json",
           _fresh_offsite(verified=True, real_remote=False))
    _write(status_dir / "restore_drill_status.json", _fresh_restore())
    _write(status_dir / "fleet_drill_status.json", _fresh_fleet())

    p = rs.build_posture(now=NOW)
    assert p["overall"] == rs.OVERALL_SAME_HOST
    assert p["overall"] not in ("OK", "WARNING")
    assert p["offsite"]["status"] == rs.OFFSITE_SAME_HOST
    assert any("stand-in" in n for n in p["notes"])


def test_real_remote_and_all_passing_is_OK(status_dir):
    """The positive control for the fix above: flip is_real_remote to True with
    everything else identical, and the SAME_HOST verdict must become OK."""
    _write(status_dir / "dr_offsite_status.json",
           _fresh_offsite(verified=True, real_remote=True))
    _write(status_dir / "restore_drill_status.json", _fresh_restore())
    _write(status_dir / "fleet_drill_status.json", _fresh_fleet())

    p = rs.build_posture(now=NOW)
    assert p["overall"] == rs.OVERALL_OK
    assert p["offsite"]["status"] == rs.OFFSITE_VERIFIED_REMOTE


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
    assert p["offsite"]["status"] == rs.OFFSITE_STALE


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
    assert p["offsite"]["status"] == rs.OFFSITE_UNVERIFIED


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
    assert p["offsite"]["status"] == rs.OFFSITE_NEVER_RUN


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
    # write a fresh OK rollup directly (the section reads resilience_status.json).
    # OK requires a REAL remote (ADR-580 C10) — see test_briefing_section_renders_same_host
    # below for the honest degraded case this used to (wrongly) also call "OK".
    rollup = {
        "overall": "OK",
        "generated_at": _ts(0),
        "offsite": {"last_ts": _ts(0.5), "verified": True, "is_real_remote": True,
                    "stale": False, "never_run": False},
        "restore_drill": {"last_ts": _ts(1), "all_ok": True, "stale": False, "never_run": False},
        "fleet_drill": {"last_ts": _ts(1), "all_ok": True, "stale": False, "never_run": False},
        "notes": [],
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


def test_briefing_section_renders_same_host(status_dir, monkeypatch):
    """ADR-580 C10: the honest degraded case — every proof passes, but the offsite
    destination is same-host. Must render its OWN icon/label, never ✅ OK and never
    bucketed under the generic "Why not OK" WARNING framing used for real failures."""
    rollup = {
        "overall": "SAME_HOST",
        "generated_at": _ts(0),
        "offsite": {"last_ts": _ts(0.5), "verified": True, "is_real_remote": False,
                    "stale": False, "never_run": False, "status": "SAME_HOST"},
        "restore_drill": {"last_ts": _ts(1), "all_ok": True, "stale": False, "never_run": False},
        "fleet_drill": {"last_ts": _ts(1), "all_ok": True, "stale": False, "never_run": False},
        "notes": ["offsite: dest is the LOCAL stand-in (no real remote configured) [owner-flagged]"],
    }
    _write(status_dir / "resilience_status.json", rollup)
    usb = _load_briefing(monkeypatch, status_dir)
    out = usb.build_resilience_section()
    assert "SAME_HOST" in out
    assert "✅ **SAME_HOST**" not in out, "SAME_HOST must not be rendered with the OK checkmark"
    assert "Why not OK" in out  # notes section still surfaces the stand-in note


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
    assert "Why not OK" in out


def test_briefing_section_missing_rollup(status_dir, monkeypatch):
    usb = _load_briefing(monkeypatch, status_dir)  # no resilience_status.json written
    out = usb.build_resilience_section()
    assert "ROLLUP UNAVAILABLE" in out
