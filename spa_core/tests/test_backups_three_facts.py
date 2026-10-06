"""spa_core/tests/test_backups_three_facts.py — RM-TRUTH-01 / ADR-580 §C3: backups and recovery
are THREE separate, honest facts (local archive · off-host copy · restore drill), never one
rolled-up "HEALTHY". The live defect this guards: ``data/dr_offsite_status.json`` with
``is_real_remote: false`` must never read as a healthy off-host copy — the only copy that left
the Mac is a DIFFERENT, unrelated channel (iCloud), and that is not what this file claims.
"""
# FROZEN-DATE-OK: injected-clock — NOW is passed explicitly into every studio_backups(data, NOW)
# call below, and every fixture file's mtime/`last_ts`/`last_offsite_ts` is derived from the SAME
# NOW anchor (os.utime pins the archive's mtime to NOW.timestamp()) — both sides of the staleness
# comparison are pinned, so the test is immune to the real calendar.
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from spa_core.studio_os import company_truth as ct

NOW = datetime(2026, 10, 5, 12, 0, 0, tzinfo=timezone.utc)


def _w(p: Path, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj), encoding="utf-8")


def test_same_host_offsite_is_never_green_even_with_local_and_drill_ok(tmp_path):
    import os
    data = tmp_path / "data"
    (data / "backups").mkdir(parents=True)
    archive = data / "backups" / "spa_state_a.tar.gz"
    archive.write_bytes(b"x")
    os.utime(archive, (NOW.timestamp(), NOW.timestamp()))
    _w(data / "dr_offsite_status.json", {"verified": True, "is_real_remote": False,
                                         "last_offsite_ts": NOW.isoformat()})
    _w(data / "resilience_status.json", {"restore_drill": {"all_ok": True, "stale": False,
                                                           "never_run": False, "last_ts": NOW.isoformat()}})
    out = ct.studio_backups(data, NOW)
    assert out["local_backup"]["state"] in (ct.MEASURED, ct.STALE)
    assert out["recovery_tested"]["value"] == "OK"
    # the card the owner actually reads is the off-host row — THIS is the dishonesty guard.
    # Raw shape (2026-10-06 integration fix): ``renderBackupOffHost`` reads ``is_real_remote``
    # RAW and composes "НЕТ — копия на том же диске" itself; a pre-composed ``display_ru`` here
    # was never read by the real renderer.
    assert out["off_host_backup"]["value"] is False
    assert out["off_host_backup"]["is_real_remote"] is False
    assert out["off_host_backup"]["state"] == ct.MEASURED_ZERO  # measured, but never green
    assert out["off_host_backup"]["display_ru"] is None  # never a pre-composed sentence either


def test_real_offsite_copy_is_green(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    _w(data / "dr_offsite_status.json", {"verified": True, "is_real_remote": True, "last_offsite_ts": NOW.isoformat()})
    out = ct.studio_backups(data, NOW)
    assert out["off_host_backup"]["value"] is True
    assert out["off_host_backup"]["state"] == ct.MEASURED


def test_absence_of_each_file_is_its_own_unknown_row(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    out = ct.studio_backups(data, NOW)
    assert out["local_backup"]["state"] == ct.NOT_MEASURED
    assert out["off_host_backup"]["state"] == ct.NOT_MEASURED
    assert out["recovery_tested"]["state"] == ct.NOT_MEASURED
    # never one green over three — all three independently absent must say so independently
    for row in ("local_backup", "off_host_backup", "recovery_tested"):
        assert out[row]["value"] is None


def test_restore_drill_states_are_distinct_words_not_collapsed():
    cases = [
        ({"all_ok": True, "stale": False, "never_run": False}, "OK"),
        ({"all_ok": False, "stale": False, "never_run": False}, "FAILED"),
        ({"all_ok": True, "stale": True, "never_run": False}, "STALE"),
        ({"never_run": True}, "NEVER_RUN"),
    ]
    for drill, expect in cases:
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            data = Path(td)
            _w(data / "resilience_status.json", {"restore_drill": dict(drill, last_ts=NOW.isoformat())})
            out = ct.studio_backups(data, NOW)
            assert out["recovery_tested"]["value"] == expect, (drill, out["recovery_tested"])


def test_local_backup_age_goes_stale_past_its_threshold(tmp_path):
    import os
    data = tmp_path / "data"
    (data / "backups").mkdir(parents=True)
    old = data / "backups" / "spa_state_old.tar.gz"
    old.write_bytes(b"x")
    old_ts = (NOW - __import__("datetime").timedelta(hours=40)).timestamp()
    os.utime(old, (old_ts, old_ts))
    out = ct.studio_backups(data, NOW, manifest=None)
    assert out["local_backup"]["state"] == ct.STALE
