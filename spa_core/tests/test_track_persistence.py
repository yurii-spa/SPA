"""SPA-V415 (v4.15) tests — MP-109: SQLite track persistence + off-site backup.

TrackStore (spa_core/persistence/track_store.py):
* зеркалирование trades.json + equity_curve_daily.json в SQLite;
* идемпотентный re-sync (повторный вызов не создаёт дублей);
* upsert обновляет изменённую запись по натуральному ключу (trade_id / date);
* raw_json сохраняет неизвестные/дополнительные поля (loss-less);
* битый/отсутствующий JSON → status="error" БЕЗ исключения;
* JSON-источники никогда не модифицируются (SQLite — зеркало, не истина).

Backup (spa_core/persistence/backup.py):
* датированная папка YYYY-MM-DD + manifest.json с корректными sha256;
* атомарные копии (нет .tmp-огрызков);
* ротация: хранит последние 14, удаляет ТОЛЬКО датированные папки и ТОЛЬКО
  внутри backup_dir;
* run_backup никогда не бросает (status="error" при невозможности).

cycle_runner (MP-109 post-cycle шаг):
* инъектируемый track_persister_fn вызывается после analytics/shadow;
* dry-run (write=False) шаг пропускает;
* исключение в persister → WARNING + note track_persist_failed, цикл НЕ падает;
* дефолтная проводка _default_track_persister при отсутствии fn.

Все тесты network-free и не пишут вне tmp_path.
"""
from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from spa_core.paper_trading import cycle_runner as cr
from spa_core.persistence.backup import run_backup
from spa_core.persistence.track_store import TrackStore

NOW = datetime(2026, 6, 10, 8, 0, tzinfo=timezone.utc)


# ─── fixtures / helpers ──────────────────────────────────────────────────────


def _trade(tid="T001", **extra):
    rec = {
        "trade_id": tid,
        "ts": "2026-06-10T18:40:35.254234+00:00",
        "type": "rebalance",
        "from_allocation": {"aave_v3": 21536.48, "maple": 20000.0},
        "to_allocation": {"aave_v3": 33142.85, "maple": 11632.64},
        "diff_usd": 85427.03,
        "reason": "orchestrator_cycle",
        "model_used": "risk_adjusted",
        "strategy_loop_active": False,
        "capital": 100000.0,
        "is_demo": False,
    }
    rec.update(extra)
    return rec


def _equity_doc(dates=("2026-06-10",)):
    daily = []
    eq = 100000.0
    for i, d in enumerate(dates):
        eq += 8.61
        daily.append(
            {
                "date": d,
                "open_equity": eq - 8.61,
                "close_equity": eq,
                "high_equity": eq,
                "low_equity": eq - 8.61,
                "snapshots": 1,
                "daily_return_pct": 0.0086 if i else 0.0,
                "cumulative_return_pct": 0.0086 * (i + 1),
                "drawdown_pct": 0.0,
                "equity": eq,
                "apy_today": 3.14,
                "daily_yield_usd": 8.61,
                "positions": {"aave_v3": 33142.85},
            }
        )
    return {
        "generated_at": "2026-06-10T18:40:35+00:00",
        "source": "cycle_runner",
        "is_demo": False,
        "summary": {"num_days": len(daily)},
        "daily": daily,
    }


def _seed(tmp_path, trades=None, equity=None):
    (tmp_path / "trades.json").write_text(
        json.dumps(trades if trades is not None else [_trade()]), encoding="utf-8"
    )
    (tmp_path / "equity_curve_daily.json").write_text(
        json.dumps(equity if equity is not None else _equity_doc()), encoding="utf-8"
    )


def _db_rows(db_path, table):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(f"SELECT * FROM {table}")]
    finally:
        conn.close()


def _store(tmp_path):
    return TrackStore(db_path=tmp_path / "track.db")


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ─── TrackStore: sync / idempotency / upsert / loss-less ─────────────────────


def test_sync_mirrors_trades_and_equity(tmp_path):
    _seed(
        tmp_path,
        trades=[_trade("T001"), _trade("T002")],
        equity=_equity_doc(("2026-06-09", "2026-06-10")),
    )
    res = _store(tmp_path).sync_from_json(tmp_path)
    assert res["status"] == "ok"
    assert res["trades_total"] == 2
    assert res["equity_points_total"] == 2
    trades = _db_rows(tmp_path / "track.db", "trades")
    assert {t["trade_id"] for t in trades} == {"T001", "T002"}
    assert trades[0]["diff_usd"] == pytest.approx(85427.03)
    eq = _db_rows(tmp_path / "track.db", "equity_curve")
    assert {b["date"] for b in eq} == {"2026-06-09", "2026-06-10"}
    assert json.loads(eq[0]["positions"]) == {"aave_v3": 33142.85}


def test_resync_is_idempotent_no_duplicates(tmp_path):
    _seed(tmp_path)
    store = _store(tmp_path)
    for _ in range(3):
        res = store.sync_from_json(tmp_path)
        assert res["status"] == "ok"
    assert len(_db_rows(tmp_path / "track.db", "trades")) == 1
    assert len(_db_rows(tmp_path / "track.db", "equity_curve")) == 1


def test_upsert_updates_amended_record(tmp_path):
    _seed(tmp_path)
    store = _store(tmp_path)
    store.sync_from_json(tmp_path)
    # The JSON record for the same trade_id / date is amended → row updated.
    _seed(
        tmp_path,
        trades=[_trade("T001", diff_usd=99999.99, reason="amended")],
        equity=_equity_doc(),
    )
    res = store.sync_from_json(tmp_path)
    assert res["status"] == "ok"
    trades = _db_rows(tmp_path / "track.db", "trades")
    assert len(trades) == 1  # updated in place, not duplicated
    assert trades[0]["diff_usd"] == pytest.approx(99999.99)
    assert trades[0]["reason"] == "amended"


def test_raw_json_preserves_unknown_fields(tmp_path):
    _seed(
        tmp_path,
        trades=[_trade("T001", exotic_field={"nested": [1, 2, 3]}, slippage_bps=4.2)],
    )
    _store(tmp_path).sync_from_json(tmp_path)
    row = _db_rows(tmp_path / "track.db", "trades")[0]
    raw = json.loads(row["raw_json"])
    assert raw["exotic_field"] == {"nested": [1, 2, 3]}
    assert raw["slippage_bps"] == 4.2
    # The whole original record survives verbatim.
    assert raw == _trade("T001", exotic_field={"nested": [1, 2, 3]}, slippage_bps=4.2)


def test_sync_missing_json_returns_error_status_without_raising(tmp_path):
    res = _store(tmp_path).sync_from_json(tmp_path)  # no JSON files at all
    assert res["status"] == "error"
    assert any("missing" in e for e in res["errors"])


def test_sync_corrupt_json_returns_error_status_without_raising(tmp_path, caplog):
    (tmp_path / "trades.json").write_text("{not json!!!", encoding="utf-8")
    (tmp_path / "equity_curve_daily.json").write_text(
        json.dumps(_equity_doc()), encoding="utf-8"
    )
    with caplog.at_level(logging.WARNING, logger="spa.track_store"):
        res = _store(tmp_path).sync_from_json(tmp_path)
    assert res["status"] == "error"
    assert any("trades.json" in e for e in res["errors"])
    assert any("track sync" in r.getMessage() for r in caplog.records)
    # The readable source is still mirrored (partial sync beats no sync).
    assert res["equity_points_total"] == 1


def test_sync_never_modifies_json_sources(tmp_path):
    _seed(tmp_path)
    before_trades = (tmp_path / "trades.json").read_bytes()
    before_equity = (tmp_path / "equity_curve_daily.json").read_bytes()
    _store(tmp_path).sync_from_json(tmp_path)
    _store(tmp_path).sync_from_json(tmp_path)
    assert (tmp_path / "trades.json").read_bytes() == before_trades
    assert (tmp_path / "equity_curve_daily.json").read_bytes() == before_equity


# ─── Backup: dated folder, manifest, atomicity, rotation ─────────────────────


def test_backup_creates_dated_folder_and_manifest_with_sha256(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _seed(data_dir)
    (data_dir / "paper_trading_status.json").write_text("{}", encoding="utf-8")
    (tmp_path / "KANBAN.json").write_text('{"columns": {}}', encoding="utf-8")  # repo root
    _store(data_dir).sync_from_json(data_dir)

    broot = tmp_path / "backups"
    res = run_backup(data_dir, broot, now=NOW)
    assert res["status"] == "ok"
    dest = broot / "2026-06-10"
    assert dest.is_dir()
    assert set(res["files"]) == {
        "track.db",
        "trades.json",
        "equity_curve_daily.json",
        "paper_trading_status.json",
        "KANBAN.json",  # picked up from the parent (repo root)
    }
    assert "SPA_sprint_log.md" in res["skipped"]
    manifest = json.loads((dest / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["ts"] == NOW.isoformat()
    by_name = {f["name"]: f for f in manifest["files"]}
    for name in res["files"]:
        assert by_name[name]["sha256"] == _sha256(dest / name)
        assert by_name[name]["size_bytes"] == (dest / name).stat().st_size
    # Copies are byte-identical to the sources.
    assert _sha256(dest / "trades.json") == _sha256(data_dir / "trades.json")
    # Atomic copies: no tmp leftovers anywhere in the dated folder.
    assert [p.name for p in dest.iterdir() if p.suffix == ".tmp"] == []


def test_backup_rotation_keeps_last_14_only_dated_dirs(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _seed(data_dir)
    broot = tmp_path / "backups"
    # 16 historical dated folders + non-dated bystanders that must survive.
    for i in range(1, 17):
        (broot / f"2026-05-{i:02d}").mkdir(parents=True)
    (broot / "not_a_date").mkdir()
    (broot / "2026-05-01-manual").mkdir()
    outside = tmp_path / "2026-05-01"
    outside.mkdir()  # same-looking dir OUTSIDE backup_dir — must be untouched

    res = run_backup(data_dir, broot, now=NOW)
    assert res["status"] == "ok"
    kept = sorted(p.name for p in broot.iterdir() if p.is_dir())
    dated_kept = [n for n in kept if n.startswith("2026-") and len(n) == 10]
    # 16 old + 1 new = 17 dated → rotation keeps the newest 14.
    assert len(dated_kept) == 14
    assert "2026-06-10" in dated_kept  # newest (today) kept
    assert res["rotated_out"] == ["2026-05-01", "2026-05-02", "2026-05-03"]
    # Non-dated dirs and anything outside backup_dir are never touched.
    assert "not_a_date" in kept and "2026-05-01-manual" in kept
    assert outside.is_dir()


def test_backup_never_raises_returns_error_status(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _seed(data_dir)
    # backup_dir path collides with an existing FILE → mkdir fails inside.
    broot = tmp_path / "backups"
    broot.write_text("i am a file", encoding="utf-8")
    res = run_backup(data_dir, broot, now=NOW)
    assert res["status"] == "error"
    assert res["errors"]


def test_backup_dir_resolution_env_var(tmp_path, monkeypatch):
    from spa_core.persistence.backup import default_backup_dir

    monkeypatch.setenv("SPA_BACKUP_DIR", str(tmp_path / "env_backups"))
    assert default_backup_dir() == tmp_path / "env_backups"


# ─── cycle_runner integration (MP-109 post-cycle step) ───────────────────────


APY = {"aave_v3": 4.0, "morpho_blue": 5.0, "yearn_v3": 3.0}
TARGET = {"aave_v3": 40000.0, "morpho_blue": 20000.0, "yearn_v3": 14000.0}


def _orch_fn(d):
    adapters = [
        {
            "protocol": p,
            "apy_pct": a,
            "tvl_usd": 1e8,
            "tier": "T1" if p == "aave_v3" else "T2",
            "status": "ok",
        }
        for p, a in APY.items()
    ]
    return SimpleNamespace(adapters=adapters, status="ok")


class _FakeAllocator:
    def allocate(self):
        return SimpleNamespace(
            target_usd=dict(TARGET),
            expected_apy_pct=3.0,
            model_used="risk_adjusted",
            strategy_loop_active=False,
        )


def _run(tmp_path, *, track_persister_fn, write=True):
    return cr.run_cycle(
        data_dir=tmp_path,
        now=NOW,
        orchestrator_fn=_orch_fn,
        allocator=_FakeAllocator(),
        risk_scorer_fn=lambda d: None,
        track_persister_fn=track_persister_fn,
        write=write,
    )


def test_cycle_invokes_persister_after_track_is_written(tmp_path):
    seen: list = []

    def _persister(ddir):
        # By the time the persister runs, the track artefacts must be on disk.
        assert (ddir / "trades.json").exists()
        assert (ddir / "equity_curve_daily.json").exists()
        assert (ddir / "paper_trading_status.json").exists()
        seen.append(ddir)

    res = _run(tmp_path, track_persister_fn=_persister)
    assert res.status == "ok"
    assert seen == [tmp_path]


def test_cycle_dry_run_skips_persister(tmp_path):
    seen: list = []
    res = _run(tmp_path, track_persister_fn=lambda d: seen.append(d), write=False)
    assert res.status == "ok"
    assert seen == []


def test_persister_exception_does_not_crash_cycle(tmp_path, caplog):
    def _boom(ddir):
        raise OSError("icloud is gone")

    with caplog.at_level(logging.WARNING, logger="spa.cycle_runner"):
        res = _run(tmp_path, track_persister_fn=_boom)
    assert res.status == "ok"
    assert any("track_persist_failed" in n for n in res.notes)
    assert any("OSError" in n for n in res.notes)
    # The failure is now LOUD (logged, not silently swallowed).
    assert any("track persistence/backup raised" in r.getMessage() for r in caplog.records)
    # ...and OBSERVABLE: a status flag flips so monitoring can SEE it even though
    # the cycle itself still reports status:ok.
    status = json.loads((tmp_path / "track_persist_status.json").read_text())
    assert status["track_persist_ok"] is False
    assert "OSError" in status["reason"]
    # The JSON track record is fully persisted despite the broken persister.
    assert (tmp_path / "trades.json").exists()
    assert (tmp_path / "equity_curve_daily.json").exists()


def test_persist_silent_empty_mirror_is_flagged(tmp_path):
    """CORE BUG: a persister that returns cleanly but leaves a 0-byte track.db
    (a direct ``sqlite3.connect`` stub — the observed live root cause) is no
    longer treated as healthy. On-disk verification flips track_persist_ok."""
    def _stub_persister(ddir):
        # Header-less 0-byte stub, exactly like a connect() that never wrote.
        sqlite3.connect(str(ddir / "track.db")).close()
        # Legacy contract: persister returns None.

    notes: list[str] = []
    ok = cr._persist_track(tmp_path, _stub_persister, notes)
    assert ok is False
    assert any("track_persist_failed" in n for n in notes)
    status = json.loads((tmp_path / "track_persist_status.json").read_text())
    assert status["track_persist_ok"] is False
    assert status["db_size_bytes"] == 0


def test_persist_success_writes_valid_nonempty_db_and_ok_flag(tmp_path):
    """A healthy default persist → non-empty integrity-clean track.db + ok flag."""
    _seed(tmp_path)  # real-shaped trades.json + equity_curve_daily.json
    notes: list[str] = []
    ok = cr._persist_track(tmp_path, cr._default_track_persister, notes)
    assert ok is True
    db = tmp_path / "track.db"
    assert db.stat().st_size > 0
    conn = sqlite3.connect(str(db))
    try:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("SELECT COUNT(*) FROM equity_curve").fetchone()[0] > 0
    finally:
        conn.close()
    status = json.loads((tmp_path / "track_persist_status.json").read_text())
    assert status["track_persist_ok"] is True
    assert status["db_size_bytes"] > 0


def test_backup_dir_unavailable_does_not_block_local_track_db(tmp_path, monkeypatch):
    """ROOT-CAUSE DECOUPLING: an unwritable / exploding backup dir must NOT
    prevent the local crash-recovery track.db from being written + flagged ok."""
    from spa_core.persistence import backup as _backup_mod

    _seed(tmp_path)

    def _broken_backup(data_dir, backup_dir=None, **kw):
        # run_backup is itself fail-safe → returns status="error", never raises.
        return {"status": "error", "errors": ["RuntimeError: icloud unavailable"]}

    monkeypatch.setattr(_backup_mod, "run_backup", _broken_backup)

    notes: list[str] = []
    ok = cr._persist_track(tmp_path, None, notes)  # default persister
    # The local mirror is healthy DESPITE the backup failure.
    assert ok is True
    assert (tmp_path / "track.db").stat().st_size > 0
    status = json.loads((tmp_path / "track_persist_status.json").read_text())
    assert status["track_persist_ok"] is True
    assert status["backup_status"] == "error"  # backup failure recorded, not masked


def test_default_persister_wired_when_fn_omitted(tmp_path, monkeypatch):
    seen: list = []
    monkeypatch.setattr(cr, "_default_track_persister", lambda d: seen.append(d))
    res = _run(tmp_path, track_persister_fn=None)
    assert res.status == "ok"
    assert seen == [tmp_path]


def test_end_to_end_cycle_then_real_sync_and_backup(tmp_path):
    """Полный путь: цикл пишет трек → TrackStore зеркалит → run_backup в tmp."""
    backup_root = tmp_path / "offsite"

    def _persister(ddir):
        TrackStore(db_path=ddir / "track.db").sync_from_json(ddir)
        run_backup(ddir, backup_root, now=NOW)

    res = _run(tmp_path, track_persister_fn=_persister)
    assert res.status == "ok"
    assert res.traded is True
    # SQLite mirror reflects the trade and today's equity bar.
    trades = _db_rows(tmp_path / "track.db", "trades")
    assert [t["trade_id"] for t in trades] == ["T001"]
    eq = _db_rows(tmp_path / "track.db", "equity_curve")
    assert [b["date"] for b in eq] == ["2026-06-10"]
    # Off-site dated folder carries the db + JSONs + manifest.
    dest = backup_root / "2026-06-10"
    assert (dest / "track.db").exists()
    assert (dest / "trades.json").exists()
    assert (dest / "manifest.json").exists()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
