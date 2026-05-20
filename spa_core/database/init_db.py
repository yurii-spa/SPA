"""
SPA Database Initializer
Создаёт SQLite базу данных и применяет схему.

Использование:
    python init_db.py              # инициализация / проверка
    python init_db.py --reset      # сброс и пересоздание (⚠️ удаляет данные!)
"""

import sqlite3
import logging
import argparse
from pathlib import Path
from contextlib import contextmanager

log = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent / "spa.db"
SCHEMA_PATH = Path(__file__).parent / "schema.sql"

# Whitelist для начального заполнения таблицы protocols
INITIAL_PROTOCOLS = [
    {
        "key":      "aave-v3-usdc-ethereum",
        "protocol": "Aave V3",
        "asset":    "USDC",
        "chain":    "Ethereum",
        "tier":     "T1",
        "pool_id":  "aa70268e-4b52-42bf-a116-608b370f9501",
        "notes":    "Основной T1 протокол. Лимит 40% портфеля.",
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
        "notes":    "T1 агрегатор. Pool: morpho-blue/STEAKUSDC (highest TVL USDC vault).",
    },
    {
        "key":      "yearn-v3-usdc-ethereum",
        "protocol": "Yearn V3",
        "asset":    "USDC",
        "chain":    "Ethereum",
        "tier":     "T2",
        "pool_id":  "7d89af7a-24c9-4292-aa38-7c71b05fbd6d",
        "notes":    "T2. Лимит 20% портфеля. Pool: yearn-finance highest TVL USDC.",
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
def get_connection(db_path: Path = None) -> sqlite3.Connection:
    """Context manager для получения соединения с БД."""
    path = db_path or DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def init_database(db_path: Path = None, reset: bool = False) -> None:
    """
    Инициализировать базу данных.
    reset=True — удалить существующий файл и создать заново.
    """
    path = db_path or DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)

    if reset and path.exists():
        log.warning(f"RESET: deleting existing database at {path}")
        path.unlink()

    log.info(f"Initializing database at {path}")

    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")

    with sqlite3.connect(str(path)) as conn:
        conn.executescript(schema_sql)
        log.info("Schema applied successfully.")
        _seed_protocols(conn)

    log.info("Database ready.")


def _seed_protocols(conn: sqlite3.Connection) -> None:
    """Заполнить таблицу protocols начальными данными (если пусто)."""
    cursor = conn.cursor()
    count = cursor.execute("SELECT COUNT(*) FROM protocols").fetchone()[0]

    if count > 0:
        log.info(f"Protocols table already has {count} entries, skipping seed.")
        return

    log.info("Seeding protocols table...")
    for p in INITIAL_PROTOCOLS:
        cursor.execute("""
            INSERT OR IGNORE INTO protocols
                (key, protocol, asset, chain, tier, pool_id, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (p["key"], p["protocol"], p["asset"], p["chain"],
              p["tier"], p.get("pool_id"), p.get("notes")))

    conn.commit()
    log.info(f"Seeded {len(INITIAL_PROTOCOLS)} protocols.")


def check_database(db_path: Path = None) -> dict:
    """Вернуть статистику по БД."""
    path = db_path or DB_PATH

    if not path.exists():
        return {"status": "missing", "path": str(path)}

    with get_connection(path) as conn:
        stats = {
            "status": "ok",
            "path": str(path),
            "size_mb": round(path.stat().st_size / 1e6, 3),
            "protocols": conn.execute("SELECT COUNT(*) FROM protocols").fetchone()[0],
            "snapshots": conn.execute("SELECT COUNT(*) FROM apy_snapshots").fetchone()[0],
            "trades": conn.execute("SELECT COUNT(*) FROM paper_trades").fetchone()[0],
            "risk_events": conn.execute("SELECT COUNT(*) FROM risk_events").fetchone()[0],
        }

        # Последний снимок
        last = conn.execute(
            "SELECT timestamp, protocol FROM apy_snapshots ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
        if last:
            stats["last_snapshot"] = dict(last)

        return stats


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
        print(f"  Path:      {stats['path']}")
        print(f"  Size:      {stats.get('size_mb', '?')} MB")
        print(f"  Protocols: {stats.get('protocols', 0)}")
        print(f"  Snapshots: {stats.get('snapshots', 0)}")
        print(f"  Trades:    {stats.get('trades', 0)}")
