"""
spa_core/tests/test_backup_retention_cross_producer.py — every test here replays a REAL
production failure of 2026-08-04/05, found while answering the owner's "проверь прям
сейчас все ли ок".

`data/backups/` is written by two producers under two naming schemes:

    spa_state_20260805T084335Z.tar.gz   ← spa_core/backtesting/tier1/dr_backup.py
    spa_state_2026-08-05.tar.gz         ← scripts/daily_backup.py  (the BROAD 499-file one)

Three defects followed, all of them live until this file existed:

  1. `dr_backup.prune(keep=14)` sorted names LEXICALLY and deleted the tail. `'-' < '0'`,
     so the dashed series was permanently the tail. Verbatim from the production log:
       2026-08-04 → deleted: [… 'spa_state_2026-08-04.tar.gz' … 'spa_state_2026-07-21.tar.gz']
       2026-08-05 → deleted: ['spa_state_20260722T051504Z.tar.gz', 'spa_state_2026-08-05.tar.gz']
     The broad snapshot of ALL of data/ was created every morning and destroyed the same day.
  2. `offsite_copy.newest_archive()` used the same lexical sort, so a daily archive could
     never be selected — the offsite mirror only ever carried the narrow critical-set one.
  3. `scripts/daily_backup.py` hashed each live file for the manifest and then read the SAME
     live file again to fill the tar. ~69 agents rewrite data/*.json between those two reads
     (2026-08-05 the pass spanned 03:30→08:43 across a host sleep), so the archive shipped
     with a manifest that did not describe its own contents: "19 mismatches", exit 1, daily.

Each test below fails on the unfixed code. Hermetic: tmp_path only, the real data/backups/
is never touched. Time is an INPUT (archive names are literal by nature — the names are the
subject here), never `datetime.now()`.
"""
# LLM_FORBIDDEN
# FROZEN-DATE-OK: the literal dates ARE the subject — these are the archive filenames from
# the 2026-08-04/05 production sweep, replayed byte-for-byte.
from __future__ import annotations

import importlib.util
import json
import sqlite3
import tarfile
from pathlib import Path

import pytest

from spa_core.backtesting.tier1 import dr_backup as dr
from spa_core.dr import archive_names as an
from spa_core.dr import offsite_copy

_ROOT = Path(__file__).resolve().parents[2]

# The exact set that was in data/backups/ when the 2026-08-04 prune ran (14 timestamped
# survivors + the daily series it swept), from /tmp/spa_tier1_governance.log.
_PROD_DR_SERIES = [
    "spa_state_20260804T091551Z.tar.gz",
    "spa_state_20260803T051500Z.tar.gz",
    "spa_state_20260802T051501Z.tar.gz",
    "spa_state_20260801T051502Z.tar.gz",
    "spa_state_20260731T051500Z.tar.gz",
    "spa_state_20260730T051505Z.tar.gz",
    "spa_state_20260729T051501Z.tar.gz",
    "spa_state_20260728T051504Z.tar.gz",
    "spa_state_20260727T051503Z.tar.gz",
    "spa_state_20260726T051503Z.tar.gz",
    "spa_state_20260725T051501Z.tar.gz",
    "spa_state_20260724T051506Z.tar.gz",
    "spa_state_20260723T051505Z.tar.gz",
    "spa_state_20260722T051504Z.tar.gz",
    "spa_state_20260721T051500Z.tar.gz",
]
_PROD_DAILY_SERIES = [f"spa_state_2026-07-{d:02d}.tar.gz" for d in range(21, 32)] + [
    f"spa_state_2026-08-{d:02d}.tar.gz" for d in range(1, 5)
]


def _touch_all(directory: Path, names) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for n in names:
        (directory / n).write_bytes(b"archive-bytes-" + n.encode())


def _names(directory: Path) -> set:
    return {p.name for p in directory.glob("spa_state_*.tar.gz")}


# ─────────────────────────────────────────────────────── 1. the name → instant contract

def test_dashed_name_sorts_below_every_timestamped_name_lexically():
    """The trap itself, stated once: this is WHY a lexical sort was wrong, not a style nit."""
    newest_daily = "spa_state_2026-08-05.tar.gz"
    oldest_dr = "spa_state_20260101T000000Z.tar.gz"
    assert sorted([newest_daily, oldest_dr], reverse=True)[0] == oldest_dr
    # …and the instant-based order gets it right.
    assert an.newest_first([newest_daily, oldest_dr])[0] == newest_daily


@pytest.mark.parametrize("name,series", [
    ("spa_state_20260805T084335Z.tar.gz", an.SERIES_DR),
    ("spa_state_2026-08-05.tar.gz", an.SERIES_DAILY),
    ("spa_state_manual_copy.tar.gz", an.SERIES_UNKNOWN),
    ("spa_state_2026-13-99.tar.gz", an.SERIES_UNKNOWN),   # parseable shape, impossible date
    ("something_else.tar.gz", an.SERIES_UNKNOWN),
])
def test_parse_archive_name_series(name, series):
    assert an.archive_series(name) == series


def test_unparseable_name_falls_back_to_mtime_not_lexical_position(tmp_path):
    """An unrecognised name must not be ordered by its bytes — it is ordered by its mtime."""
    _touch_all(tmp_path, ["spa_state_aaa_manual.tar.gz", "spa_state_20260101T000000Z.tar.gz"])
    manual = tmp_path / "spa_state_aaa_manual.tar.gz"
    import os
    os.utime(manual, (1_900_000_000, 1_900_000_000))  # far future vs the 2026-01-01 name
    assert an.newest_first(tmp_path.glob("spa_state_*.tar.gz"))[0] == manual


# ────────────────────────────────────────── 2. dr_backup.prune — the 2026-08-04/05 sweep

def test_prune_does_not_delete_the_other_producers_series(tmp_path, monkeypatch):
    """POSITIVE CONTROL for the 2026-08-04 sweep: 15 daily archives deleted in one run."""
    backups = tmp_path / "backups"
    _touch_all(backups, _PROD_DR_SERIES + _PROD_DAILY_SERIES)
    monkeypatch.setattr(dr, "_BACKUPS", backups)

    result = dr.prune(keep=14)

    survived = _names(backups)
    assert set(_PROD_DAILY_SERIES) <= survived, (
        "the daily series was deleted by a ring buffer that does not own it — "
        "this is the 2026-08-04 sweep"
    )
    assert not [n for n in result["deleted"] if an.archive_series(n) != an.SERIES_DR]
    # …and every daily archive is reported as foreign, not silently ignored.
    assert set(result["foreign"]) == set(_PROD_DAILY_SERIES)


def test_prune_still_ring_buffers_its_own_series(tmp_path, monkeypatch):
    """The fix must not disable retention: the oldest OWN archive still goes."""
    backups = tmp_path / "backups"
    _touch_all(backups, _PROD_DR_SERIES + _PROD_DAILY_SERIES)
    monkeypatch.setattr(dr, "_BACKUPS", backups)

    result = dr.prune(keep=14)

    assert result["deleted"] == ["spa_state_20260721T051500Z.tar.gz"], result["deleted"]
    assert not (backups / "spa_state_20260721T051500Z.tar.gz").exists()
    assert len([n for n in _names(backups) if an.archive_series(n) == an.SERIES_DR]) == 14


def test_prune_never_deletes_an_unparseable_archive(tmp_path, monkeypatch):
    """Fail-CLOSED on deletion: a name we cannot read is left alone, not assumed old."""
    backups = tmp_path / "backups"
    # The name is deliberately one that ALSO sorts low lexically ("2026-…" < "2026081…"),
    # so this test reddens on the pre-2026-08-05 code instead of passing by luck.
    _touch_all(backups, _PROD_DR_SERIES + ["spa_state_2026-08-05_hand_copied.tar.gz"])
    monkeypatch.setattr(dr, "_BACKUPS", backups)

    dr.prune(keep=1)

    assert (backups / "spa_state_2026-08-05_hand_copied.tar.gz").exists()


def test_prune_keep_zero_still_spares_foreign_series(tmp_path, monkeypatch):
    backups = tmp_path / "backups"
    _touch_all(backups, _PROD_DR_SERIES[:3] + _PROD_DAILY_SERIES[:3])
    monkeypatch.setattr(dr, "_BACKUPS", backups)

    dr.prune(keep=0)

    assert _names(backups) == set(_PROD_DAILY_SERIES[:3])


def test_list_backups_returns_the_true_newest_first(tmp_path, monkeypatch):
    """A daily archive written today outranks a timestamped one from last week."""
    backups = tmp_path / "backups"
    _touch_all(backups, ["spa_state_20260801T051502Z.tar.gz", "spa_state_2026-08-05.tar.gz"])
    monkeypatch.setattr(dr, "_BACKUPS", backups)

    assert dr.list_backups()[0].name == "spa_state_2026-08-05.tar.gz"


# ──────────────────────────────────────────────── 3. offsite_copy — selection + retention

def test_offsite_newest_archive_can_select_the_daily_series(tmp_path):
    """Defect 2: the broad snapshot could never be mirrored offsite, however fresh it was."""
    _touch_all(tmp_path, ["spa_state_20260801T051502Z.tar.gz", "spa_state_2026-08-05.tar.gz"])
    assert offsite_copy.newest_archive(tmp_path).name == "spa_state_2026-08-05.tar.gz"


def test_offsite_prune_keeps_each_series_separately(tmp_path):
    """One producer's volume must not evict the other's history from the mirror."""
    _touch_all(tmp_path, _PROD_DR_SERIES + _PROD_DAILY_SERIES)

    offsite_copy._prune_offsite(tmp_path, keep=3)

    kept = _names(tmp_path)
    assert len([n for n in kept if an.archive_series(n) == an.SERIES_DR]) == 3
    assert len([n for n in kept if an.archive_series(n) == an.SERIES_DAILY]) == 3
    assert "spa_state_2026-08-04.tar.gz" in kept          # newest daily survives
    assert "spa_state_20260804T091551Z.tar.gz" in kept    # newest dr survives


def test_offsite_prune_never_deletes_an_unparseable_archive(tmp_path):
    _touch_all(tmp_path, _PROD_DR_SERIES + ["spa_state_2026-08-05_hand_copied.tar.gz"])
    offsite_copy._prune_offsite(tmp_path, keep=1)
    assert (tmp_path / "spa_state_2026-08-05_hand_copied.tar.gz").exists()


# ────────────────────────────────── 4. daily_backup — manifest must describe the archive

def _load_daily_backup():
    spec = importlib.util.spec_from_file_location(
        "daily_backup_race_under_test", str(_ROOT / "scripts" / "daily_backup.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _seed_data(data: Path) -> None:
    data.mkdir(parents=True, exist_ok=True)
    (data / "golive_status.json").write_text(json.dumps({"passed": 29}))
    (data / "equity_curve_daily.json").write_text(json.dumps({"daily": []}))
    (data / "paper_evidence_history.json").write_text(json.dumps({"days": []}))
    (data / "current_positions.json").write_text(json.dumps([]))
    (data / "adapter_status.json").write_text(json.dumps({"tick": 0}))
    con = sqlite3.connect(str(data / "track.db"))
    try:
        con.execute("CREATE TABLE evidence_records(id INTEGER, val TEXT)")
        con.commit()
    finally:
        con.close()


def _wire(mod, tmp_path, monkeypatch):
    data = tmp_path / "data"
    backups = data / "backups"
    _seed_data(data)
    backups.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(mod, "_DATA", str(data))
    monkeypatch.setattr(mod, "_BACKUPS", str(backups))
    return data, backups


def test_manifest_describes_the_archive_even_when_the_fleet_rewrites_mid_run(
        tmp_path, monkeypatch):
    """POSITIVE CONTROL for the daily "19 mismatches, exit 1".

    A live agent rewrites `adapter_status.json` in the window between capture and tar. The
    archive must still verify, and must carry the bytes as they were AT CAPTURE — a
    per-file point-in-time snapshot, with a manifest that tells the truth about it.
    """
    mod = _load_daily_backup()
    data, _backups = _wire(mod, tmp_path, monkeypatch)
    victim = data / "adapter_status.json"
    captured = victim.read_bytes()

    real_copyfile = mod.shutil.copyfile

    def copy_then_let_an_agent_write(src, dst, *a, **kw):
        out = real_copyfile(src, dst, *a, **kw)
        if str(src).endswith("adapter_status.json"):
            victim.write_text(json.dumps({"tick": 1, "written_by": "the fleet"}))
        return out

    monkeypatch.setattr(mod.shutil, "copyfile", copy_then_let_an_agent_write)

    rep = mod.snapshot(date_str="2026-08-05")
    assert rep["written"] is True

    vrep = mod.verify(rep["archive"])
    assert vrep["valid"] is True, vrep["mismatches"]

    with tarfile.open(rep["archive"], "r:gz") as tar:
        stored = tar.extractfile("adapter_status.json").read()
    assert stored == captured
    assert victim.read_bytes() != captured  # the live file really did move on


def test_manifest_records_how_the_bytes_were_captured(tmp_path, monkeypatch):
    mod = _load_daily_backup()
    _wire(mod, tmp_path, monkeypatch)
    rep = mod.snapshot(date_str="2026-08-05")
    with tarfile.open(rep["archive"], "r:gz") as tar:
        manifest = json.loads(tar.extractfile(mod.MANIFEST_NAME).read().decode())
    assert manifest["capture"] == "staged-once"
    assert manifest["vanished_sources"] == []


def test_source_deleted_mid_run_is_recorded_not_guessed(tmp_path, monkeypatch):
    """A non-critical file that disappears between the glob and the copy is NAMED, and the
    archive is still produced — silence about it would be the fail-OPEN answer."""
    mod = _load_daily_backup()
    data, _backups = _wire(mod, tmp_path, monkeypatch)
    doomed = data / "adapter_status.json"

    real_copyfile = mod.shutil.copyfile

    def vanish_first(src, dst, *a, **kw):
        if str(src).endswith("adapter_status.json"):
            doomed.unlink()
        return real_copyfile(src, dst, *a, **kw)

    monkeypatch.setattr(mod.shutil, "copyfile", vanish_first)

    rep = mod.snapshot(date_str="2026-08-05")
    with tarfile.open(rep["archive"], "r:gz") as tar:
        manifest = json.loads(tar.extractfile(mod.MANIFEST_NAME).read().decode())
        assert "adapter_status.json" not in tar.getnames()
    assert manifest["vanished_sources"] == ["adapter_status.json"]


def test_critical_source_deleted_mid_run_still_fails_closed(tmp_path, monkeypatch):
    """The tolerance above must NOT extend to the recovery set."""
    mod = _load_daily_backup()
    data, backups = _wire(mod, tmp_path, monkeypatch)
    doomed = data / "golive_status.json"

    real_copyfile = mod.shutil.copyfile

    def vanish_first(src, dst, *a, **kw):
        if str(src).endswith("golive_status.json"):
            doomed.unlink()
        return real_copyfile(src, dst, *a, **kw)

    monkeypatch.setattr(mod.shutil, "copyfile", vanish_first)

    with pytest.raises(mod.BackupIncompleteError):
        mod.snapshot(date_str="2026-08-05")
    assert list(Path(backups).glob("spa_state_*.tar.gz")) == []
