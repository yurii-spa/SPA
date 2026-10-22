"""BL-008 Phase 2 — the side-store door (`spa_core.database.side_store`).

The Phase-2 scan (`migrate_callsites`) demands zero raw ``sqlite3.connect`` outside the
abstraction. Four writing call-sites own SELF-CONTAINED stores (market.db, evidence.db,
the memory index tmp file, a throw-away copy of the portfolio DB) — not the main DB.
They now open through `open_side_store`, which must (a) hand back EXACTLY what the raw
connect gave them (same timeout, isolation, no row_factory/pragma/journal change) and
(b) refuse the main DB, so it cannot become a way around `get_connection()`.

Every guarantee is checked on a temporary DB; no live store is opened.
"""
from __future__ import annotations

import hashlib
import importlib
import sqlite3
import time
import types
from pathlib import Path

import pytest

from spa_core.database import db_url
from spa_core.database import migrate_callsites as mc
from spa_core.database import side_store as ss

_REAL_CONNECT = sqlite3.connect


@pytest.fixture
def spy(monkeypatch):
    """Record every sqlite3.connect made THROUGH the door (args, kwargs)."""
    calls = []

    def _spy(*a, **kw):
        calls.append((a, kw))
        return _REAL_CONNECT(*a, **kw)

    # Replace the door's OWN module reference (not the global sqlite3.connect): a call-site
    # that went back to a raw connect would bypass this spy, and the wiring tests go red.
    monkeypatch.setattr(ss, "sqlite3", types.SimpleNamespace(connect=_spy))
    return calls


@pytest.fixture(autouse=True)
def _main_db_elsewhere(monkeypatch, tmp_path):
    # Hermetic: the env-resolved main DB is a temp file unless a test says otherwise.
    monkeypatch.setenv(db_url.ENV_VAR, f"sqlite:///{tmp_path / 'main.db'}")


# ── (a) pass-through: the door adds nothing to the connection ─────────────────────────────

def test_connection_is_the_plain_stdlib_one(tmp_path):
    p = tmp_path / "s.db"
    door, raw = ss.open_side_store(p), _REAL_CONNECT(str(tmp_path / "r.db"))
    try:
        assert type(door) is type(raw) is sqlite3.Connection
        assert door.row_factory is None and raw.row_factory is None
        assert door.isolation_level == raw.isolation_level == ""
        assert (door.execute("PRAGMA journal_mode").fetchone()
                == raw.execute("PRAGMA journal_mode").fetchone())
        # deferred transaction + explicit commit, as with the raw connect
        door.execute("CREATE TABLE t (x)"); door.execute("INSERT INTO t VALUES (1)")
        assert door.in_transaction
        door.rollback()
        assert door.execute("SELECT COUNT(*) FROM t").fetchone() == (0,)
    finally:
        door.close(); raw.close()


def test_existing_wal_journal_mode_is_left_as_is(tmp_path):
    p = tmp_path / "w.db"
    c = _REAL_CONNECT(str(p)); c.execute("PRAGMA journal_mode=WAL"); c.close()
    d = ss.open_side_store(p)
    try:
        assert d.execute("PRAGMA journal_mode").fetchone() == ("wal",)
    finally:
        d.close()


def test_timeout_is_honoured(tmp_path):
    p = tmp_path / "lock.db"
    holder = _REAL_CONNECT(str(p), isolation_level=None)
    holder.execute("CREATE TABLE t (x)")
    holder.execute("BEGIN IMMEDIATE")
    try:
        c = ss.open_side_store(p, timeout=0.3)
        t0 = time.monotonic()
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            c.execute("BEGIN IMMEDIATE")
        assert 0.25 <= time.monotonic() - t0 < 3.0
        c.close()
    finally:
        holder.rollback(); holder.close()


def test_default_timeout_and_isolation_are_passed_through(tmp_path, spy):
    ss.open_side_store(tmp_path / "a.db").close()
    ss.open_side_store(tmp_path / "b.db", timeout=30, isolation_level=None).close()
    assert spy[0] == ((str(tmp_path / "a.db"),), {"timeout": 5.0})
    assert spy[1] == ((str(tmp_path / "b.db"),), {"timeout": 30, "isolation_level": None})


def test_readonly_never_creates_and_never_writes(tmp_path):
    missing = tmp_path / "nope.db"
    with pytest.raises(sqlite3.OperationalError):
        ss.open_side_store(missing, readonly=True)
    assert not missing.exists()
    p = tmp_path / "ro.db"
    c = _REAL_CONNECT(str(p)); c.execute("CREATE TABLE t (x)"); c.commit(); c.close()
    r = ss.open_side_store(p, readonly=True)
    try:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            r.execute("INSERT INTO t VALUES (1)")
    finally:
        r.close()


# ── (b) the main DB is refused ─────────────────────────────────────────────────────────────

def test_env_main_db_is_refused(tmp_path, monkeypatch, spy):
    main = tmp_path / "main.db"
    with pytest.raises(ss.MainDatabaseRefused):
        ss.open_side_store(main)
    assert spy == [] and not main.exists()  # refused BEFORE sqlite touched anything


def test_package_default_main_db_is_refused_even_under_postgres(monkeypatch, spy):
    monkeypatch.setenv(db_url.ENV_VAR, "postgresql://u@h/db")
    with pytest.raises(ss.MainDatabaseRefused):
        ss.open_side_store(db_url._DEFAULT_SQLITE_PATH)
    with pytest.raises(ss.MainDatabaseRefused):
        ss.open_side_store(db_url._DEFAULT_SQLITE_PATH, readonly=True)
    assert spy == []


def test_symlink_to_main_db_is_refused(tmp_path):
    main = tmp_path / "main.db"
    _REAL_CONNECT(str(main)).close()
    link = tmp_path / "alias.db"
    link.symlink_to(main)
    with pytest.raises(ss.MainDatabaseRefused):
        ss.open_side_store(link)


# ── the four owners keep their guarantees through the door ────────────────────────────────

def test_evidence_store_append_only_through_the_door(tmp_path, spy):
    from spa_core.trading_research import evidence
    conn = evidence.connect(tmp_path / "ev" / "evidence.db")
    try:
        assert spy and spy[-1][1] == {"timeout": 30}
        assert conn.row_factory is None
        evidence.register(conn, "c1", "h", {"k": 1}, now_ms=1, code_version="v")
        conn.commit()
        for sql in ("UPDATE candidates SET def_hash='x'", "DELETE FROM candidates"):
            with pytest.raises(sqlite3.IntegrityError, match="append-only"):
                conn.execute(sql)
    finally:
        conn.close()


def test_market_store_candles_immutable_through_the_door(tmp_path, spy):
    from spa_core.trading_research import market_data as md
    conn = md.connect(tmp_path / "md" / "market.db")
    try:
        assert spy and spy[-1][1] == {"timeout": 30}
        conn.execute("INSERT INTO candles VALUES ('BTC','1h',0,1,1,1,1,1,'s',0)")
        conn.commit()
        for sql in ("UPDATE candles SET close=2", "DELETE FROM candles"):
            with pytest.raises(sqlite3.IntegrityError, match="immutable"):
                conn.execute(sql)
    finally:
        conn.close()


def test_memory_index_build_still_atomic_through_the_door(tmp_path, monkeypatch, spy):
    from spa_core.studio_os.memory import index as ix
    target = tmp_path / "index.db"
    _REAL_CONNECT(str(target)).close()
    before = target.read_bytes()

    def boom(conn):
        conn.execute("CREATE TABLE half (x)")
        raise RuntimeError("mid-build")

    monkeypatch.setattr(ix, "_build_into", boom)
    with pytest.raises(RuntimeError):
        ix.build(target)
    assert target.read_bytes() == before                      # failed build never published
    assert not list(tmp_path.glob("index.db.building.*"))     # its tmp was discarded
    tmp_opened = Path(spy[-1][0][0])
    assert tmp_opened.name.startswith("index.db.building.") and spy[-1][1] == {"timeout": 5.0}

    def ok(conn):
        conn.execute("CREATE TABLE done (x)"); conn.commit(); conn.close()
        return {"ok": True}

    monkeypatch.setattr(ix, "_build_into", ok)
    assert ix.build(target) == {"ok": True}
    c = _REAL_CONNECT(str(target))
    try:
        assert c.execute("SELECT name FROM sqlite_master").fetchall() == [("done",)]
    finally:
        c.close()


def _sha(p: Path):
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None


def test_portfolio_snapshot_checks_the_copy_and_leaves_source_bytes(tmp_path, spy):
    importlib.import_module("spa_core.api.server")
    from spa_core.api import _shared
    src = tmp_path / "live" / "spa.db"; src.parent.mkdir()
    w = _REAL_CONNECT(str(src))
    w.execute("PRAGMA journal_mode=WAL"); w.execute("PRAGMA wal_autocheckpoint=0")
    w.execute("CREATE TABLE a (n)"); w.execute("INSERT INTO a VALUES (7)"); w.commit()
    try:
        side = [src.with_name("spa.db" + s) for s in ("", "-wal", "-shm")]
        before = [_sha(p) for p in side]
        dst = tmp_path / "copy" / "spa.db"; dst.parent.mkdir()
        assert _shared._snapshot_sqlite(src, dst) is None
        assert [_sha(p) for p in side] == before                # source + sidecars untouched
        assert [Path(a[0]) for a, _ in spy] == [dst]            # only the COPY was opened
        c = _REAL_CONNECT(str(dst))
        assert c.execute("SELECT n FROM a").fetchone() == (7,)  # WAL tail replayed into the copy
        c.close()
    finally:
        w.close()


def test_portfolio_snapshot_refuses_when_the_copy_target_is_the_main_db(tmp_path, monkeypatch):
    importlib.import_module("spa_core.api.server")
    from spa_core.api import _shared
    src = tmp_path / "src.db"
    c = _REAL_CONNECT(str(src)); c.execute("CREATE TABLE a (n)"); c.commit(); c.close()
    dst = tmp_path / "main.db"           # the env-resolved main DB (fixture)
    with pytest.raises(ss.MainDatabaseRefused):
        _shared._snapshot_sqlite(src, dst)


# ── the scan: the door is the only new exemption, and aliases no longer walk past ────────

def test_scan_still_flags_raw_connect_next_to_the_door(tmp_path):
    root = tmp_path / "spa_core"; (root / "database").mkdir(parents=True)
    (root / "database" / "side_store.py").write_text("import sqlite3\nsqlite3.connect('x')\n")
    (root / "database" / "other.py").write_text("import sqlite3\nsqlite3.connect('x')\n")
    hits = mc.find_raw_sqlite_connects(root)
    assert [h[0] for h in hits] == ["spa_core/database/other.py"]


@pytest.mark.parametrize("src", [
    "import sqlite3 as s\nc = s.connect('x.db')\n",
    "from sqlite3 import connect\nc = connect('x.db')\n",
    "from sqlite3 import connect as op\nc = op('x.db')\n",
    "from sqlite3 import dbapi2 as d\nc = d.connect('x.db')\n",
    "import sqlite3.dbapi2 as d\nc = d.connect('x.db')\n",
])
def test_scan_follows_aliases(src):
    assert mc._sqlite_connect_linenos(src) == [2]


def test_scan_does_not_flag_unrelated_connect():
    assert mc._sqlite_connect_linenos("import socket as s\ns.connect(('h', 1))\n") == []
    assert mc._sqlite_connect_linenos(
        "from spa_core.database.side_store import open_side_store\nopen_side_store('x')\n") == []
