"""
SPA Data Exporter — для GitHub Actions и локального запуска.
Читает из SQLite, пишет JSON-файлы в ../data/ (рядом с index.html).

Использование:
    cd spa_core
    python export_data.py          # экспорт
    python export_data.py --fetch  # сначала fetch DeFiLlama, потом экспорт
"""

from __future__ import annotations

import json
import sys
import argparse
import logging
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from database.init_db import init_database, get_connection, get_db_path
from paper_trading.engine import PaperTrader
from message_bus.bus import MessageBus

log = logging.getLogger("spa.export")

# data/ живёт рядом с index.html в корне репо (на уровень выше spa_core/)
OUTPUT_DIR = Path(__file__).parent.parent / "data"


def write_json(filename: str, data) -> None:
    path = OUTPUT_DIR / filename
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    log.info(f"  → data/{filename}  ({path.stat().st_size} bytes)")


def run_export(fetch: bool = False) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    db_path = get_db_path()

    # 1. Init DB (идемпотентно)
    init_database(db_path)
    log.info(f"DB: {db_path}")

    # 2. Опционально — свежие данные из DeFiLlama
    if fetch:
        log.info("Fetching DeFiLlama data…")
        try:
            from data_pipeline.defillama_fetcher import DeFiLlamaFetcher
            fetcher = DeFiLlamaFetcher(db_path=db_path)
            result = fetcher.fetch_all()
            fetched = result.get("fetched", 0)
            errors  = result.get("errors", 0)
            log.info(f"DeFiLlama: {fetched} fetched, {errors} errors")
        except Exception as e:
            log.error(f"DeFiLlama fetch failed (using cached): {e}")

    # 3. Paper Trader: обновить PnL → попробовать открыть позиции → экспорт статуса
    trader = PaperTrader(db_path=db_path)
    updated = trader.update_prices()
    if updated:
        log.info(f"Updated PnL for {updated} open positions")
    alloc_actions = trader.auto_allocate()
    log.info(f"auto_allocate: {alloc_actions}")
    write_json("status.json", trader.get_status())

    # 4. protocols.json
    with get_connection(db_path) as conn:
        rows = conn.execute("""
            SELECT p.key, p.protocol, p.asset, p.chain, p.tier, p.is_active,
                   s.apy_total, s.apy_base, s.apy_reward,
                   s.tvl_usd, s.timestamp AS last_snapshot
            FROM protocols p
            LEFT JOIN (
                SELECT protocol_key,
                       apy_total, apy_base, apy_reward, tvl_usd, timestamp,
                       ROW_NUMBER() OVER (
                           PARTITION BY protocol_key ORDER BY timestamp DESC
                       ) AS rn
                FROM apy_snapshots
                WHERE is_valid = 1
            ) s ON p.key = s.protocol_key AND s.rn = 1
            ORDER BY p.tier, COALESCE(s.apy_total, 0) DESC
        """).fetchall()
    write_json("protocols.json", [dict(r) for r in rows])

    # 5. bus_stats.json
    bus = MessageBus(db_path=db_path)
    write_json("bus_stats.json", bus.stats())

    # 6. strategy_state.json  (хронологический порядок для графиков)
    with get_connection(db_path) as conn:
        rows = conn.execute("""
            SELECT timestamp, total_capital_usd, deployed_capital_usd,
                   cash_usd, total_pnl_usd, total_pnl_pct,
                   current_apy, trade_count
            FROM strategy_state
            WHERE strategy_id = 'paper-v1'
            ORDER BY timestamp DESC LIMIT 48
        """).fetchall()
    write_json("strategy_state.json", list(reversed([dict(r) for r in rows])))

    # 7. trades.json (последние 30 сделок)
    with get_connection(db_path) as conn:
        rows = conn.execute("""
            SELECT trade_id, strategy_id, timestamp_open, timestamp_close,
                   protocol_key, asset, action, amount_usd,
                   apy_at_open, net_apy_annualized, pnl_usd, reason
            FROM paper_trades
            WHERE strategy_id = 'paper-v1'
            ORDER BY timestamp_open DESC LIMIT 30
        """).fetchall()
    write_json("trades.json", [dict(r) for r in rows])

    # 8. meta.json — время обновления
    write_json("meta.json", {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "version": "1.0.0",
        "source": "github-actions" if fetch else "local",
    })

    log.info(f"✅ Export complete → {OUTPUT_DIR}/")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    )
    parser = argparse.ArgumentParser(description="SPA Data Exporter")
    parser.add_argument("--fetch", action="store_true",
                        help="Fetch fresh data from DeFiLlama before export")
    args = parser.parse_args()
    run_export(fetch=args.fetch)
