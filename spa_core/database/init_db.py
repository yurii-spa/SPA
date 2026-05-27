"""
SPA Database Initializer
Создаёт базу данных (SQLite или PostgreSQL) и применяет схему.

Использование:
    python init_db.py              # инициализация / проверка
    python init_db.py --reset      # сброс и пересоздание (⚠️ удаляет данные!)

BL-008 Phase 2
--------------
The legacy `get_connection(db_path)` helper now delegates to
`spa_core.database.connection.get_connection`, the new dual-driver
abstraction. Backwards-compatible: callers that pass a `Path` continue to
get a SQLite connection rooted at that path; callers without arguments get
the env-resolved backend (SQLite by default, PostgreSQL when
`SPA_DATABASE_URL=postgres://...`).
"""

import sqlite3
import logging
import argparse
from pathlib import Path
from contextlib import contextmanager
from typing import Iterator, Optional

# BL-008 Phase 2 — delegate to the new dual-driver abstraction.
from .connection import get_connection as _abstract_get_connection
from .db_url import get_db_url, is_postgres, is_sqlite

log = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent / "spa.db"
SCHEMA_PATH = Path(__file__).parent / "schema.sql"
SCHEMA_PG_PATH = Path(__file__).parent / "schema_postgres.sql"

# Whitelist для заполнения таблицы protocols (v2.0.0 — M4 expansion: 7 → 15)
# INSERT OR IGNORE позволяет добавлять новые записи в существующую БД
INITIAL_PROTOCOLS = [
    # ── T1: Blue-chip lending ──────────────────────────────────────────────────
    {
        "key":      "aave-v3-usdc-ethereum",
        "protocol": "Aave V3",
        "asset":    "USDC",
        "chain":    "Ethereum",
        "tier":     "T1",
        "pool_id":  "aa70268e-4b52-42bf-a116-608b370f9501",
        "notes":    "T1. Лимит 40% портфеля.",
    },
    {
        "key":      "aave-v3-usdt-ethereum",
        "protocol": "Aave V3",
        "asset":    "USDT",
        "chain":    "Ethereum",
        "tier":     "T1",
        "pool_id":  "f981a304-bb6c-45b8-b0c5-fd2f515ad23a",
        "notes":    "T1. Лимит 30% портфеля.",
    },
    {
        "key":      "aave-v3-usdc-base",
        "protocol": "Aave V3",
        "asset":    "USDC",
        "chain":    "Base",
        "tier":     "T1",
        "pool_id":  "7e0661bf-8cf3-45e6-9424-31916d4c7b84",
        "notes":    "T1. Aave V3 на Base. TVL $35M.",
    },
    {
        "key":      "aave-v3-usdc-arbitrum",
        "protocol": "Aave V3",
        "asset":    "USDC",
        "chain":    "Arbitrum",
        "tier":     "T1",
        "pool_id":  "d9fa8e14-0447-4207-9ae8-7810199dfa1f",
        "notes":    "T1. Aave V3 на Arbitrum. TVL $21M.",
    },
    {
        "key":      "compound-v3-usdc-ethereum",
        "protocol": "Compound V3",
        "asset":    "USDC",
        "chain":    "Ethereum",
        "tier":     "T1",
        "pool_id":  "7da72d09-56ca-4ec5-a45f-59114353e487",
        "notes":    "T1. Лимит 30% портфеля.",
    },
    {
        "key":      "morpho-usdc-ethereum",
        "protocol": "Morpho",
        "asset":    "USDC",
        "chain":    "Ethereum",
        "tier":     "T1",
        "pool_id":  "b55f43a8-f444-4cd8-a3a4-0a4e786ba566",
        "notes":    "T1 агрегатор. morpho-blue/STEAKUSDC. TVL $114M.",
    },
    {
        "key":      "spark-usdc-ethereum",
        "protocol": "Spark",
        "asset":    "USDC",
        "chain":    "Ethereum",
        "tier":     "T1",
        "pool_id":  "c5c74dd1-995c-4445-9d84-3e710bad7d52",
        "notes":    "T1. spark-savings USDC. TVL $404M.",
    },
    {
        "key":      "spark-usdt-ethereum",
        "protocol": "Spark",
        "asset":    "USDT",
        "chain":    "Ethereum",
        "tier":     "T1",
        "pool_id":  "a5d67f7e-5b51-4a9d-969d-caf051a7f5a4",
        "notes":    "T1. spark-savings USDT. TVL $905M.",
    },
    {
        "key":      "sky-susds-ethereum",
        "protocol": "Sky",
        "asset":    "sUSDS",
        "chain":    "Ethereum",
        "tier":     "T1",
        "pool_id":  "d8c4eff5-c8a9-46fc-a888-057c4c668e72",
        "notes":    "T1. Sky (MakerDAO) sUSDS vault. TVL $5.8B.",
    },
    # ── T2: Higher yield ───────────────────────────────────────────────────────
    {
        "key":      "fluid-usdc-ethereum",
        "protocol": "Fluid",
        "asset":    "USDC",
        "chain":    "Ethereum",
        "tier":     "T2",
        "pool_id":  "4438dabc-7f0c-430b-8136-2722711ae663",
        "notes":    "T2. fluid-lending USDC. TVL $200M.",
    },
    {
        "key":      "fluid-usdt-ethereum",
        "protocol": "Fluid",
        "asset":    "USDT",
        "chain":    "Ethereum",
        "tier":     "T2",
        "pool_id":  "4e8cc592-c8d5-4824-8155-128ba521e903",
        "notes":    "T2. fluid-lending USDT. TVL $131M.",
    },
    {
        "key":      "ethena-susde-ethereum",
        "protocol": "Ethena",
        "asset":    "sUSDe",
        "chain":    "Ethereum",
        "tier":     "T2",
        "pool_id":  "66985a81-9c51-46ca-9977-42b4fe7bc6df",
        "notes":    "T2. Ethena sUSDe yield vault. TVL $1.8B.",
    },
    {
        "key":      "yearn-v3-usdc-ethereum",
        "protocol": "Yearn V3",
        "asset":    "USDC",
        "chain":    "Ethereum",
        "tier":     "T2",
        "pool_id":  "7d89af7a-24c9-4292-aa38-7c71b05fbd6d",
        "notes":    "T2. Лимит 20% портфеля. TVL $28M.",
    },
    {
        "key":      "maple-usdc-ethereum",
        "protocol": "Maple",
        "asset":    "USDC",
        "chain":    "Ethereum",
        "tier":     "T2",
        "pool_id":  "43641cf5-a92e-416b-bce9-27113d3c0db6",
        "notes":    "T2. Лимит 15% портфеля. 48h GSM lock.",
    },
    {
        "key":      "euler-v2-usdc-ethereum",
        "protocol": "Euler V2",
        "asset":    "USDC",
        "chain":    "Ethereum",
        "tier":     "T2",
        "pool_id":  "31a0cd94-b781-4e0d-a9f1-1702bc2c238f",
        "notes":    "T2. Лимит 15% портфеля.",
    },
]


def get_db_path() -> Path:
    return DB_PATH


@contextmanager
def get_connection(db_path: Path = None) -> Iterator[object]:
    """
    Context manager для получения соединения с БД.

    BL-008 Phase 2 — теперь делегирует в `spa_core.database.connection`.
    Backwards-compatible:
      * `db_path=None` (most callers): use env-resolved URL
        (SQLite default, PostgreSQL if `SPA_DATABASE_URL` is set).
      * `db_path=Path("/tmp/x.db")`: force a SQLite connection at that path.
        This preserves the historical contract used by tests + the engine.
    """
    if db_path is not None:
        # Legacy SQLite-by-path callers — build a sqlite URL so the new
        # abstraction routes to SQLite regardless of the env variable.
        url: Optional[str] = f"sqlite:///{db_path}"
    else:
        url = None  # resolved from env by the abstraction

    with _abstract_get_connection(url) as conn:
        yield conn


def init_database(db_path: Path = None, reset: bool = False) -> None:
    """
    Инициализировать базу данных.

    SQLite path: reset=True удаляет файл и пересоздаёт его.
    PostgreSQL path: schema_postgres.sql применяется к подключенной БД.
    `reset` для PG не поддерживается (требует DROP DATABASE на стороне сервера).
    """
    url = get_db_url() if db_path is None else f"sqlite:///{db_path}"

    if is_postgres(url):
        # Postgres path — нет файла для удаления; reset бессмыслен здесь.
        if reset:
            log.warning(
                "init_database(reset=True) is a no-op for PostgreSQL — "
                "drop the database server-side and re-run."
            )
        if not SCHEMA_PG_PATH.exists():
            raise FileNotFoundError(
                f"PostgreSQL schema file missing: {SCHEMA_PG_PATH}"
            )
        schema_sql = SCHEMA_PG_PATH.read_text(encoding="utf-8")
        log.info(f"Initializing PostgreSQL database via {SCHEMA_PG_PATH.name}")
        with _abstract_get_connection(url) as conn:
            with conn.cursor() as cur:
                cur.execute(schema_sql)
            conn.commit()
            log.info("Schema applied successfully (PostgreSQL).")
            _seed_protocols(conn, backend="postgres")
        log.info("Database ready (PostgreSQL).")
        return

    # SQLite path (default)
    path = db_path or DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)

    if reset and path.exists():
        log.warning(f"RESET: deleting existing database at {path}")
        path.unlink()

    log.info(f"Initializing database at {path}")

    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")

    # NOTE: `executescript` is SQLite-specific; we keep raw sqlite3 here only
    # for the bootstrap multi-statement DDL. Everything downstream goes through
    # the abstraction.
    with sqlite3.connect(str(path)) as conn:
        conn.executescript(schema_sql)
        log.info("Schema applied successfully.")
        _seed_protocols(conn, backend="sqlite")

    log.info("Database ready.")


def _seed_protocols(conn, backend: str = "sqlite") -> None:
    """
    Upsert протоколов из INITIAL_PROTOCOLS.

    SQLite: INSERT OR IGNORE — существующие записи не трогаются.
    Postgres: INSERT ... ON CONFLICT (key) DO NOTHING — эквивалент.

    Позволяет безопасно расширять whitelist без сброса БД.
    """
    cursor = conn.cursor()

    def _scalar_count() -> int:
        cursor.execute("SELECT COUNT(*) FROM protocols")
        row = cursor.fetchone()
        # sqlite3.Row supports indexing by int; RealDictCursor returns dict-like.
        if isinstance(row, dict):
            return int(next(iter(row.values())))
        return int(row[0])

    before = _scalar_count()

    if backend == "postgres":
        sql = """
            INSERT INTO protocols
                (key, protocol, asset, chain, tier, pool_id, notes)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (key) DO NOTHING
        """
    else:
        sql = """
            INSERT OR IGNORE INTO protocols
                (key, protocol, asset, chain, tier, pool_id, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """

    for p in INITIAL_PROTOCOLS:
        cursor.execute(sql, (
            p["key"], p["protocol"], p["asset"], p["chain"],
            p["tier"], p.get("pool_id"), p.get("notes"),
        ))

    conn.commit()
    after = _scalar_count()
    added = after - before
    if added:
        log.info(f"Protocols: added {added} new entries (total {after}).")
    else:
        log.info(f"Protocols: {after} entries, no new ones.")


def check_database(db_path: Path = None) -> dict:
    """Вернуть статистику по БД.

    SQLite-only: PostgreSQL не имеет одного файла, и stats() для PG
    тривиально получается через `SELECT count(*)` — не входит в scope Phase 2.
    """
    path = db_path or DB_PATH

    # PG fast path — нет файла, отдаём только статусы таблиц.
    if db_path is None and is_postgres(get_db_url()):
        try:
            with get_connection() as conn:
                cur = conn.cursor()
                cur.execute("SELECT COUNT(*) FROM protocols")
                protocols = _first_int(cur.fetchone())
                cur.execute("SELECT COUNT(*) FROM apy_snapshots")
                snapshots = _first_int(cur.fetchone())
                cur.execute("SELECT COUNT(*) FROM paper_trades")
                trades = _first_int(cur.fetchone())
                cur.execute("SELECT COUNT(*) FROM risk_events")
                risk_events = _first_int(cur.fetchone())
                try:
                    cur.execute("SELECT COUNT(*) FROM agent_decisions")
                    decisions_count = _first_int(cur.fetchone())
                except Exception:
                    decisions_count = 0
                return {
                    "status": "ok",
                    "backend": "postgres",
                    "protocols": protocols,
                    "snapshots": snapshots,
                    "trades": trades,
                    "risk_events": risk_events,
                    "agent_decisions": decisions_count,
                }
        except Exception as e:
            return {"status": "error", "backend": "postgres", "error": str(e)}

    if not path.exists():
        return {"status": "missing", "path": str(path)}

    with get_connection(path) as conn:
        # agent_decisions may not exist yet on older DBs — safe fallback
        try:
            decisions_count = conn.execute("SELECT COUNT(*) FROM agent_decisions").fetchone()[0]
        except Exception:
            decisions_count = 0

        stats = {
            "status": "ok",
            "path": str(path),
            "size_mb": round(path.stat().st_size / 1e6, 3),
            "protocols": conn.execute("SELECT COUNT(*) FROM protocols").fetchone()[0],
            "snapshots": conn.execute("SELECT COUNT(*) FROM apy_snapshots").fetchone()[0],
            "trades": conn.execute("SELECT COUNT(*) FROM paper_trades").fetchone()[0],
            "risk_events": conn.execute("SELECT COUNT(*) FROM risk_events").fetchone()[0],
            "agent_decisions": decisions_count,
        }

        # Последний снимок
        last = conn.execute(
            "SELECT timestamp, protocol FROM apy_snapshots ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
        if last:
            stats["last_snapshot"] = dict(last)

        return stats


def _first_int(row) -> int:
    """Извлечь первое целое из строки результата (sqlite3.Row или RealDictCursor)."""
    if row is None:
        return 0
    if isinstance(row, dict):
        return int(next(iter(row.values())))
    return int(row[0])


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    )

    parser = argparse.ArgumentParser(description="SPA Database Initializer")
    parser.add_argument("--reset", action="store_true",
                        help="Delete and recreate the database (loses all data!)")
    parser.add_argument("--check", action="store_true",
                        help="Print database statistics and exit")
    args = parser.parse_args()

    if args.check:
        import json
        stats = check_database()
        print(json.dumps(stats, indent=2, ensure_ascii=False))
    else:
        init_database(reset=args.reset)
        stats = check_database()
        print(f"\nDatabase stats:")
        print(f"  Path:            {stats['path']}")
        print(f"  Size:            {stats.get('size_mb', '?')} MB")
        print(f"  Protocols:       {stats.get('protocols', 0)}")
        print(f"  Snapshots:       {stats.get('snapshots', 0)}")
        print(f"  Trades:          {stats.get('trades', 0)}")
        print(f"  Agent Decisions: {stats.get('agent_decisions', 0)}")
