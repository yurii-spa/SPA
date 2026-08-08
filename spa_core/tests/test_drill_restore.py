"""
spa_core/tests/test_drill_restore.py — tests for the INERT restore drill.

Proves the drill harness (scripts/drill_restore.py):
  * builds a synthetic backup tar (valid + corrupted) and validates the GOOD one
    (all_ok) and FAILS-CLOSED on a corrupted critical file,
  * NEVER writes anywhere under the real live data/ tree (sandbox guard),
  * newest-archive selection picks the latest by mtime,
  * one target PER PRODUCER SERIES, so a dead producer cannot hide behind a green
    all_ok (production defect 2026-08-05),
  * fail-closed when no archives exist,
  * rejects unsafe (absolute / traversal) tar member paths.

All deterministic, stdlib-only. The drill is pointed at synthetic tmp archives and a
tmp status path so the real data/ is never touched.

# FROZEN-DATE-OK: the literal dates here are ARCHIVE NAMES and payload contents that
# spa_core/dr/archive_names.py PARSES — the date is the subject under test (which series
# a name belongs to, and which instant it encodes), not a freshness fixture. Every one of
# them is in the past and every assertion over them is "<= today", so the calendar moving
# can only make them safer, never redder. The freshness side of this file — the only part
# that could rot — is expressed RELATIVELY (`time.time() - N*3600`, pattern 2 of
# .claude/rules/deployment.md), never against a literal date. Added when the per-series
# work introduced the words `stale`/`age_h` and so pulled the file into the ratchet's
# at-risk class (цикл #120); the baseline was NOT touched.
"""
from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import sqlite3
import subprocess
import sys
import tarfile
import time
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "drill_restore.py"
_REAL_DATA = (Path(__file__).resolve().parents[2] / "data").resolve()


def _load_drill():
    spec = importlib.util.spec_from_file_location("drill_restore", _SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


drill = _load_drill()


# --------------------------------------------------------------------------- #
# synthetic backup builders
# --------------------------------------------------------------------------- #
def _good_payloads() -> dict:
    return {
        "golive_status.json": {"passed": 26, "total": 29, "real_track_days": 6},
        "equity_curve_daily.json": {
            "summary": {"last_date": "2026-01-01"},
            "daily": [{"date": "2025-12-31", "equity": 100000.0},
                      {"date": "2026-01-01", "equity": 100010.0}],
        },
        "paper_evidence_history.json": {"schema_version": 1, "days": [{"d": 1}], "history": []},
        "current_positions.json": {"aave_v3": 23250.0},
    }


def _make_db(path: Path) -> None:
    con = sqlite3.connect(str(path))
    con.execute("CREATE TABLE evidence_records (id INTEGER PRIMARY KEY, v TEXT)")
    con.execute("INSERT INTO evidence_records (v) VALUES ('x'), ('y')")
    con.commit()
    con.close()


def _make_archive(path: Path, payloads: dict) -> None:
    with tarfile.open(path, "w:gz") as tar:
        for name, obj in payloads.items():
            data = json.dumps(obj).encode("utf-8")
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            info.mtime = 0
            import io
            tar.addfile(info, io.BytesIO(data))


@pytest.fixture
def sandbox_env(tmp_path, monkeypatch):
    """Point the drill's backups + status + db glob at a tmp tree."""
    backups = tmp_path / "backups"
    backups.mkdir()
    status = tmp_path / "restore_drill_status.json"
    monkeypatch.setattr(drill, "_BACKUPS", str(backups))
    monkeypatch.setattr(drill, "_STATUS_PATH", str(status))
    monkeypatch.setattr(drill, "ARCHIVE_GLOB", str(backups / "spa_state_*.tar.gz"))
    monkeypatch.setattr(drill, "DB_GLOB", str(backups / "spa_*.db"))
    return {"backups": backups, "status": status}


# --------------------------------------------------------------------------- #
# tests
# --------------------------------------------------------------------------- #
def test_drill_validates_good_backup(sandbox_env):
    backups = sandbox_env["backups"]
    _make_archive(backups / "spa_state_2026-01-01.tar.gz", _good_payloads())
    _make_db(backups / "spa_2026-01-01.db")

    report = drill.run_drill(quiet=True)
    assert report["all_ok"] is True, report
    files = {e["file"]: e for e in report["files_validated"]}
    for name in drill.CRITICAL_JSON:
        assert files[name]["ok"] is True, files[name]
    assert files["track.db"]["ok"] is True, files["track.db"]
    # status JSON written atomically to the tmp path
    written = json.loads(Path(sandbox_env["status"]).read_text())
    assert written["all_ok"] is True
    assert "last_drill_ts" in written


def test_drill_fails_closed_on_corrupted_json(sandbox_env):
    backups = sandbox_env["backups"]
    payloads = _good_payloads()
    report = _good_payloads  # silence linters; not used
    # corrupt a critical file: golive missing required key
    bad = dict(payloads)
    bad["golive_status.json"] = {"foo": "bar"}  # no passed/total
    _make_archive(backups / "spa_state_2026-01-02.tar.gz", bad)
    _make_db(backups / "spa_2026-01-02.db")

    rep = drill.run_drill(quiet=True)
    assert rep["all_ok"] is False, rep
    files = {e["file"]: e for e in rep["files_validated"]}
    assert files["golive_status.json"]["ok"] is False


def test_drill_fails_closed_on_unparseable_json(sandbox_env):
    backups = sandbox_env["backups"]
    arch = backups / "spa_state_2026-01-03.tar.gz"
    # write a tar where equity_curve_daily.json is not valid JSON
    with tarfile.open(arch, "w:gz") as tar:
        import io
        for name, obj in _good_payloads().items():
            if name == "equity_curve_daily.json":
                data = b"{ this is not json"
            else:
                data = json.dumps(obj).encode("utf-8")
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    _make_db(backups / "spa_2026-01-03.db")

    rep = drill.run_drill(quiet=True)
    assert rep["all_ok"] is False
    files = {e["file"]: e for e in rep["files_validated"]}
    assert files["equity_curve_daily.json"]["ok"] is False


def test_drill_fails_closed_on_corrupted_db(sandbox_env):
    backups = sandbox_env["backups"]
    _make_archive(backups / "spa_state_2026-01-04.tar.gz", _good_payloads())
    # a non-sqlite blob masquerading as a .db
    (backups / "spa_2026-01-04.db").write_bytes(b"not a sqlite database at all" * 10)

    rep = drill.run_drill(quiet=True)
    files = {e["file"]: e for e in rep["files_validated"]}
    assert files["track.db"]["ok"] is False, files["track.db"]
    assert rep["all_ok"] is False


def test_drill_fails_closed_when_db_missing(sandbox_env):
    backups = sandbox_env["backups"]
    _make_archive(backups / "spa_state_2026-01-05.tar.gz", _good_payloads())
    # no .db snapshot at all
    rep = drill.run_drill(quiet=True)
    files = {e["file"]: e for e in rep["files_validated"]}
    assert files["track.db"]["ok"] is False
    assert rep["all_ok"] is False


def test_drill_future_equity_date_fails(sandbox_env):
    backups = sandbox_env["backups"]
    payloads = _good_payloads()
    payloads["equity_curve_daily.json"] = {
        "daily": [{"date": "2999-12-31", "equity": 1.0}]
    }
    _make_archive(backups / "spa_state_2026-01-06.tar.gz", payloads)
    _make_db(backups / "spa_2026-01-06.db")
    rep = drill.run_drill(quiet=True)
    files = {e["file"]: e for e in rep["files_validated"]}
    assert files["equity_curve_daily.json"]["ok"] is False


def test_newest_archive_selection_by_mtime(sandbox_env):
    backups = sandbox_env["backups"]
    older = backups / "spa_state_2026-01-01.tar.gz"
    newer = backups / "spa_state_2026-01-02.tar.gz"
    _make_archive(older, _good_payloads())
    _make_archive(newer, _good_payloads())
    # force mtimes: older < newer
    os.utime(older, (1000, 1000))
    os.utime(newer, (2000, 2000))
    assert drill.find_newest_archive() == str(newer)


def test_fail_closed_when_no_archives(sandbox_env):
    with pytest.raises(FileNotFoundError):
        drill.find_newest_archive()


def test_unsafe_tar_member_rejected(sandbox_env, tmp_path):
    backups = sandbox_env["backups"]
    arch = backups / "spa_state_2026-01-07.tar.gz"
    with tarfile.open(arch, "w:gz") as tar:
        import io
        data = b"x"
        info = tarfile.TarInfo(name="../escape.json")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    sb = tmp_path / "sb"
    sb.mkdir()
    with pytest.raises(RuntimeError):
        drill.safe_extract(str(arch), str(sb))


def test_sandbox_guard_refuses_under_live_data(sandbox_env):
    """The hard guard must refuse any sandbox path inside the REAL live data/ tree."""
    with pytest.raises(RuntimeError):
        drill._assert_sandbox_outside_data(str(_REAL_DATA))
    with pytest.raises(RuntimeError):
        drill._assert_sandbox_outside_data(str(_REAL_DATA / "subdir"))


def test_drill_never_writes_under_live_data(sandbox_env, monkeypatch):
    """
    Sabotage tempfile.mkdtemp to point INSIDE the real data/ → the guard must abort
    BEFORE any extraction, proving the drill never writes into live data/.
    """
    backups = sandbox_env["backups"]
    _make_archive(backups / "spa_state_2026-01-08.tar.gz", _good_payloads())
    _make_db(backups / "spa_2026-01-08.db")

    poisoned = _REAL_DATA / "DRILL_SHOULD_NEVER_CREATE_THIS"
    real_mkdtemp = drill.tempfile.mkdtemp

    def _evil_mkdtemp(*a, **k):
        os.makedirs(poisoned, exist_ok=True)
        return str(poisoned)

    monkeypatch.setattr(drill.tempfile, "mkdtemp", _evil_mkdtemp)
    try:
        with pytest.raises(RuntimeError):
            drill.run_drill(quiet=True)
        # the guard fired BEFORE extracting: no critical backup files were written here
        assert not (poisoned / "golive_status.json").exists()
    finally:
        # cleanup the empty poisoned dir we created (not a critical-file write)
        try:
            import shutil
            shutil.rmtree(poisoned, ignore_errors=True)
        except Exception:
            pass
        monkeypatch.setattr(drill.tempfile, "mkdtemp", real_mkdtemp)


def test_real_data_dir_untouched_signature(sandbox_env):
    """
    End-to-end on a synthetic archive: snapshot the real data/ dir listing before/after
    a full drill run and assert the set of entries is unchanged (no stray files created).
    """
    backups = sandbox_env["backups"]
    _make_archive(backups / "spa_state_2026-01-09.tar.gz", _good_payloads())
    _make_db(backups / "spa_2026-01-09.db")

    # ИЗМЕНЁН НАМЕРЕННО 2026-08-08 (инв. №16) — и проверка НЕ ослаблена, а уточнена.
    #
    # Тест снимал листинг ЖИВОГО data/, по которому в это же время пишет работающий
    # флот. `atomic_save` создаёт промежуточный `<файл>.tmp` и тут же его заменяет —
    # и если чужой агент попал ровно между двумя снимками, тест краснел на ЧУЖОЙ
    # штатной записи. Замерено: расхождение `{'yield_volatility_surface_log.json.tmp'}`,
    # то есть файла, которого в момент второго снимка уже не существовало.
    # Вероятность выросла 08.08, когда флот пополнился тремя агентами (77 → 81).
    #
    # Вопрос теста — «не оставил ли ЛИ ДРИЛЛ мусор в живом data/», а не «работает ли
    # флот». Поэтому из сравнения исключаются ТОЛЬКО промежуточные `.tmp` от
    # atomic_save. Любой другой появившийся или исчезнувший файл по-прежнему валит
    # тест — это закреплено положительным контролем ниже.
    def _stable(entries):
        return {e for e in entries if not e.endswith(".tmp")}

    before = _stable(os.listdir(_REAL_DATA))
    drill.run_drill(quiet=True)
    after = _stable(os.listdir(_REAL_DATA))
    assert before == after, f"live data/ changed: {before ^ after}"


def test_stray_non_tmp_file_in_live_data_is_still_caught(sandbox_env, tmp_path):
    """Положительный контроль к правке выше: послабление касается ТОЛЬКО `.tmp`.

    Без этого теста «починка» вида «игнорировать любые расхождения» была бы зелёной,
    а сторож, стерегущий живой трек, перестал бы что-либо стеречь.
    """
    stray = pathlib.Path(_REAL_DATA) / "__strayfile_from_test__.json"
    def _stable(entries):
        return {e for e in entries if not e.endswith(".tmp")}
    before = _stable(os.listdir(_REAL_DATA))
    try:
        stray.write_text("{}", encoding="utf-8")
        after = _stable(os.listdir(_REAL_DATA))
        assert before != after, "появление обычного файла в живом data/ осталось незамеченным"
        assert (before ^ after) == {stray.name}
    finally:
        stray.unlink(missing_ok=True)


def test_tmp_churn_alone_does_not_trip_the_signature(sandbox_env):
    """Зеркало: одна лишь `.tmp`-текучка чужого писателя не считается изменением."""
    def _stable(entries):
        return {e for e in entries if not e.endswith(".tmp")}
    listing = set(os.listdir(_REAL_DATA))
    assert _stable(listing | {"чужой_писатель.json.tmp"}) == _stable(listing)


# --------------------------------------------------------------------------- #
# PER-SERIES COVERAGE (production defect 2026-08-05)
#
# data/backups/ is written by TWO producers with TWO naming schemes. The drill used to
# take ONE archive across both series (max by mtime), so which series got validated was
# an mtime race — and a DEAD producer stayed invisible behind a green all_ok.
#
# Every test below is a positive control: on the pre-fix drill (single mtime-max target,
# no `series` key, no `--require`) each one fails.
# --------------------------------------------------------------------------- #
def _dr_name(stamp: str = "20260101T051500Z") -> str:
    return f"spa_state_{stamp}.tar.gz"


def test_both_producer_series_are_drilled_not_just_the_newest(sandbox_env):
    """The core defect: with both series present, BOTH are validated — not whichever
    the mtime race happened to favour."""
    backups = sandbox_env["backups"]
    _make_archive(backups / "spa_state_2026-01-01.tar.gz", _good_payloads())   # daily
    _make_archive(backups / _dr_name(), _good_payloads())                      # dr
    _make_db(backups / "spa_2026-01-01.db")

    rep = drill.run_drill(quiet=True)
    assert rep["all_ok"] is True, rep
    assert sorted(rep["series_drilled"]) == ["daily", "dr"], rep["series_drilled"]
    drilled_archives = {s["archive"] for s in rep["series"]}
    assert drilled_archives == {"spa_state_2026-01-01.tar.gz", _dr_name()}, drilled_archives


def test_a_broken_archive_in_the_OTHER_series_turns_the_verdict_red(sandbox_env):
    """The whole point. The newest archive (by mtime) is healthy; the other series is
    corrupt. Pre-fix this published all_ok=true — a green light over an unrestorable
    backup series."""
    backups = sandbox_env["backups"]
    bad = dict(_good_payloads())
    bad["golive_status.json"] = {"foo": "bar"}          # no passed/total → invalid
    dr_arc = backups / _dr_name()
    daily_arc = backups / "spa_state_2026-01-02.tar.gz"
    _make_archive(dr_arc, bad)                          # the BROKEN one
    _make_archive(daily_arc, _good_payloads())          # the healthy one
    _make_db(backups / "spa_2026-01-02.db")
    os.utime(dr_arc, (1000, 1000))                      # dr is OLDER by mtime
    os.utime(daily_arc, (2000, 2000))                   # daily wins the mtime race

    rep = drill.run_drill(quiet=True)
    # compatibility head still describes the archive that landed last …
    assert rep["archive"] == "spa_state_2026-01-02.tar.gz"
    assert all(e["ok"] for e in rep["files_validated"])
    # … but the verdict now accounts for the series it used to ignore
    assert rep["all_ok"] is False, rep
    broken = next(s for s in rep["series"] if s["series"] == "dr")
    assert broken["status"] == "failed", broken


def test_newest_within_a_series_is_chosen_by_the_instant_the_name_encodes(sandbox_env):
    """Ordering INSIDE a series must not be lexical or cross-series: '-' < '0', so every
    dated name sorts below every timestamped one whatever date it carries."""
    backups = sandbox_env["backups"]
    older = backups / "spa_state_2026-01-01.tar.gz"
    newer = backups / "spa_state_2026-01-05.tar.gz"
    _make_archive(older, _good_payloads())
    _make_archive(newer, _good_payloads())
    _make_db(backups / "spa_2026-01-05.db")
    # mtimes deliberately CONTRADICT the names: the older-named file was touched last.
    os.utime(newer, (1000, 1000))
    os.utime(older, (2000, 2000))

    picked = drill.newest_by_series()
    assert picked["daily"] == str(newer), picked


def test_required_series_with_no_archive_is_a_named_finding(sandbox_env):
    """A producer that wrote NOTHING must be named, not absorbed into a green verdict."""
    backups = sandbox_env["backups"]
    _make_archive(backups / "spa_state_2026-01-03.tar.gz", _good_payloads())  # daily only
    _make_db(backups / "spa_2026-01-03.db")

    rep = drill.run_drill(quiet=True, require=("dr", "daily"))
    assert rep["all_ok"] is False, rep
    missing = next(s for s in rep["series"] if s["series"] == "dr")
    assert missing["status"] == "missing", missing
    assert "dr" in missing["detail"] and missing["archive"] is None
    # and the series that IS there still passed on its own merits
    assert next(s for s in rep["series"] if s["series"] == "daily")["all_ok"] is True


def test_required_series_gone_stale_is_a_named_finding(sandbox_env):
    """A producer that STOPPED writing looks identical to a healthy one from the archive
    contents alone — only its age gives it away."""
    backups = sandbox_env["backups"]
    daily = backups / "spa_state_2026-01-04.tar.gz"
    dr = backups / _dr_name()
    _make_archive(daily, _good_payloads())
    _make_archive(dr, _good_payloads())
    _make_db(backups / "spa_2026-01-04.db")
    stale_by = (drill.SERIES_STALE_H + 1.0) * 3600
    old = time.time() - stale_by
    os.utime(dr, (old, old))

    rep = drill.run_drill(quiet=True, require=("dr", "daily"))
    assert rep["all_ok"] is False, rep
    stale = next(s for s in rep["series"] if s["series"] == "dr")
    assert stale["status"] == "stale", stale
    assert stale["age_h"] > drill.SERIES_STALE_H


def test_one_delayed_run_does_not_raise_the_stale_alarm(sandbox_env):
    """Positive control on the threshold itself: the host slept through 2026-08-04/05 and
    a backup pass spanned 03:30→08:43. A single delayed daily run must stay green — the
    alarm sits at 2x the cadence, so only two missed days trip it."""
    backups = sandbox_env["backups"]
    daily = backups / "spa_state_2026-01-06.tar.gz"
    dr = backups / _dr_name()
    _make_archive(daily, _good_payloads())
    _make_archive(dr, _good_payloads())
    _make_db(backups / "spa_2026-01-06.db")
    delayed = time.time() - 29 * 3600     # a full day late and then some
    os.utime(dr, (delayed, delayed))

    rep = drill.run_drill(quiet=True, require=("dr", "daily"))
    assert rep["all_ok"] is True, rep
    assert next(s for s in rep["series"] if s["series"] == "dr")["status"] == "ok"


def test_unrecognised_archive_name_is_drilled_not_skipped(sandbox_env):
    """A name we cannot parse is still a backup someone may restore from. Skipping it
    silently is how a series goes unchecked — it gets its own group and is validated."""
    backups = sandbox_env["backups"]
    stray = backups / "spa_state_handcopy.tar.gz"
    bad = dict(_good_payloads())
    bad["golive_status.json"] = {"foo": "bar"}
    _make_archive(stray, bad)
    _make_archive(backups / "spa_state_2026-01-07.tar.gz", _good_payloads())
    _make_db(backups / "spa_2026-01-07.db")

    rep = drill.run_drill(quiet=True)
    assert "unknown" in rep["series_drilled"], rep["series_drilled"]
    assert rep["all_ok"] is False, rep


def test_explicit_archive_still_drills_exactly_one(sandbox_env):
    """--archive keeps its single-target meaning: the other series is NOT pulled in."""
    backups = sandbox_env["backups"]
    target = backups / "spa_state_2026-01-08.tar.gz"
    _make_archive(target, _good_payloads())
    _make_archive(backups / _dr_name(), _good_payloads())
    _make_db(backups / "spa_2026-01-08.db")

    rep = drill.run_drill(archive=str(target), quiet=True)
    assert rep["series_drilled"] == ["daily"], rep["series_drilled"]
    assert rep["archive"] == "spa_state_2026-01-08.tar.gz"


def test_scheduled_r7_step_declares_the_producer_contract():
    """Without --require the drill cannot tell a DEAD producer from an unscheduled one.
    The declaration therefore has to live at the scheduling site — and be pinned, because
    a step that is only a convention is a step that gets dropped (the fleet-parity guard
    sat un-called for 25 days for exactly that reason)."""
    src = (Path(__file__).resolve().parents[2] / "scripts" / "resilience_cycle.py").read_text()
    r7 = [ln for ln in src.splitlines() if "drill_restore.py" in ln and not ln.strip().startswith("#")]
    assert r7, "R7 restore-drill step vanished from resilience_cycle.py"
    joined = " ".join(src.splitlines()[src.splitlines().index(r7[0]):][:3])
    assert "--require" in joined, "R7 step no longer declares --require"
    for series in ("dr", "daily"):
        assert series in joined, f"R7 step no longer requires the '{series}' series"


def test_unknown_series_in_require_is_rejected(sandbox_env):
    """A typo in --require would silently require nothing — fail-CLOSED on it instead."""
    backups = sandbox_env["backups"]
    _make_archive(backups / "spa_state_2026-01-10.tar.gz", _good_payloads())
    _make_db(backups / "spa_2026-01-10.db")
    rc = subprocess.run(
        [sys.executable, str(_SCRIPT), "--require", "dr,dayly", "--quiet"],
        capture_output=True, text=True,
        cwd=str(Path(__file__).resolve().parents[2]),
    )
    assert rc.returncode == 2, rc.stdout + rc.stderr
    assert "unknown series" in (rc.stdout + rc.stderr)
