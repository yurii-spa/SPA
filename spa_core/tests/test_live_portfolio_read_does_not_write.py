"""N1 guard: reading the live portfolio must not write the SQLite file it reads.

Defect (2026-10-17): running ``test_run_identity_key_price.py`` changed the
git-tracked ``spa_core/database/spa.db`` (sha256 + mtime). Path: the reader
sweep's HTTP batch (``run_identity_key_price._run_http_probe``) calls the GET
routes of ``spa_core.api.routers.misc`` (``/api/portfolio``, ``/api/positions``)
→ ``spa_core.api._shared.get_live_portfolio`` → ``init_database(get_db_path())``
(CREATE/INSERT OR IGNORE) and ``PaperTrader(...)`` (``_ensure_strategy_state``
INSERT/UPDATE) against ``init_db.DB_PATH`` — a path taken from ``__file__``,
i.e. the REAL tree, never the stand the sweep had prepared.

Every test here is a positive control: on origin a6329acbf each one goes red.
"""
from __future__ import annotations

import hashlib
import importlib
import os
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
REPO_DB = ROOT / "spa_core" / "database" / "spa.db"
SIDECARS = ("-wal", "-shm", "-journal")


def _fingerprint(db: Path) -> dict:
    """Bytes + mtime of the DB and which sidecars exist — all of it must hold."""
    return {
        "sha256": hashlib.sha256(db.read_bytes()).hexdigest(),
        "mtime_ns": db.stat().st_mtime_ns,
        "sidecars": sorted(s for s in SIDECARS
                           if db.with_name(db.name + s).exists()),
    }


def _shared():
    # `server` puts spa_core/ on sys.path; `_shared` imports `database.init_db`
    # and `paper_trading.engine` as top-level packages through it.
    importlib.import_module("spa_core.api.server")
    from spa_core.api import _shared
    return _shared


def _make_source(dirpath: Path) -> Path:
    """A real, schema-bearing SQLite file (copy of the tracked DB) to read."""
    src = dirpath / "spa.db"
    con = sqlite3.connect(f"file:{REPO_DB}?mode=ro&immutable=1", uri=True)
    try:
        dst = sqlite3.connect(str(src))
        con.backup(dst)
        dst.close()
    finally:
        con.close()
    return src


class LivePortfolioReadIsReadOnly(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="spa_n1_portfolio_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.env = mock.patch.dict(os.environ)
        self.env.start()
        self.addCleanup(self.env.stop)
        os.environ.pop("SPA_LIVE_ROOT", None)

    def test_default_path_source_is_byte_identical_after_read(self):
        """The path `get_db_path()` names is read, never written."""
        shared = _shared()
        import database.init_db as init_db
        src = _make_source(self.tmp)
        before = _fingerprint(src)
        with mock.patch.object(init_db, "get_db_path", return_value=src):
            status = shared.get_live_portfolio()
        self.assertIsInstance(status, dict, "reader must still answer from the copy")
        self.assertIn("portfolio", status)
        self.assertEqual(_fingerprint(src), before,
                         "get_live_portfolio wrote the database it only reads")

    def test_stand_root_is_read_and_left_untouched(self):
        """Explicit SPA_LIVE_ROOT (the census stand) wins over __file__."""
        shared = _shared()
        import database.init_db as init_db
        stand_db_dir = self.tmp / "stand" / "spa_core" / "database"
        stand_db_dir.mkdir(parents=True)
        src = _make_source(stand_db_dir)
        os.environ["SPA_LIVE_ROOT"] = str(self.tmp / "stand")
        before = _fingerprint(src)
        sentinel = self.tmp / "must_not_be_used.db"
        with mock.patch.object(init_db, "get_db_path", return_value=sentinel):
            status = shared.get_live_portfolio()
        self.assertIsInstance(status, dict)
        self.assertEqual(_fingerprint(src), before)
        self.assertFalse(sentinel.exists(), "stand given, yet __file__ path was used")

    def test_missing_source_is_not_created_on_read(self):
        """No database ⇒ None (absent observation), never a freshly built DB."""
        shared = _shared()
        import database.init_db as init_db
        ghost = self.tmp / "absent" / "spa.db"
        with mock.patch.object(init_db, "get_db_path", return_value=ghost):
            status = shared.get_live_portfolio()
        self.assertIsNone(status)
        self.assertFalse(ghost.exists(), "a read created the database")
        self.assertFalse(ghost.parent.exists())


class SweepHttpBatchLeavesRepositoryDbAlone(unittest.TestCase):
    """The exact triggering path of the defect: the G16 sweep's HTTP batch."""

    def test_misc_routes_under_the_stand_do_not_touch_repo_db(self):
        from spa_core.monitoring import run_identity_key_price as g16
        if not REPO_DB.is_file():
            self.fail(f"precondition NOT provided: {REPO_DB} absent — not measured")
        original = REPO_DB.read_bytes()
        before = _fingerprint(REPO_DB)
        try:
            with tempfile.TemporaryDirectory(prefix="spa_n1_stand_") as tmp:
                data = Path(tmp) / "s1" / "data"
                data.mkdir(parents=True)
                answer, why = g16._run_http_probe(
                    data, ["spa_core.api.routers.misc"], ROOT)
                self.assertIsNotNone(answer, f"probe did not run: {why}")
            after = _fingerprint(REPO_DB)
        finally:
            # A regression must fail loudly, not leave the tracked file dirty.
            if REPO_DB.read_bytes() != original:
                _restore_bytes(REPO_DB, original)
            for s in SIDECARS:
                side = REPO_DB.with_name(REPO_DB.name + s)
                if s not in before["sidecars"] and side.exists():
                    side.unlink()
        self.assertEqual(after["sha256"], before["sha256"],
                         "sweep HTTP batch wrote the repository spa.db")
        self.assertEqual(after["mtime_ns"], before["mtime_ns"])
        self.assertEqual(after["sidecars"], before["sidecars"])


def _restore_bytes(path: Path, data: bytes) -> None:
    """tmp in the same directory + os.replace (inv. #5 shape for bytes)."""
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".spa_db_restore_")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


if __name__ == "__main__":
    unittest.main()
