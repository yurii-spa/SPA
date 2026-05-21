"""
SPA Data Exporter â Ð´Ð»Ñ GitHub Actions Ð¸ Ð»Ð¾ÐºÐ°Ð»ÑÐ½Ð¾Ð³Ð¾ Ð·Ð°Ð¿ÑÑÐºÐ°.
Ð§Ð¸ÑÐ°ÐµÑ Ð¸Ð· SQLite, Ð¿Ð¸ÑÐµÑ JSON-ÑÐ°Ð¹Ð»Ñ Ð² ../data/ (ÑÑÐ´Ð¾Ð¼ Ñ index.html).

ÐÑÐ¿Ð¾Ð»ÑÐ·Ð¾Ð²Ð°Ð½Ð¸Ðµ:
    cd spa_core
    python export_data.py          # ÑÐºÑÐ¿Ð¾ÑÑ
    python export_data.py --fetch  # ÑÐ½Ð°ÑÐ°Ð»Ð° fetch DeFiLlama, Ð¿Ð¾ÑÐ¾Ð¼ ÑÐºÑÐ¿Ð¾ÑÑ
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

# data/ Ð¶Ð¸Ð²ÑÑ ÑÑÐ´Ð¾Ð¼ Ñ index.html Ð² ÐºÐ¾ÑÐ½Ðµ ÑÐµÐ¿Ð¾ (Ð½Ð° ÑÑÐ¾Ð²ÐµÐ½Ñ Ð²ÑÑÐµ spa_core/)
OUTPUT_DIR = Path(__file__).parent.parent / "data"


def write_json(filename: str, data) -> None:
    path = OUTPUT_DIR / filename
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    log.info(f"  â data/{filename}  ({path.stat().st_size} bytes)")


def run_export(fetch: bool = False) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    db_path = get_db_path()

    # 1. Init DB (Ð¸Ð´ÐµÐ¼Ð¿Ð¾ÑÐµÐ½ÑÐ½Ð¾)
    init_database(db_path)
    log.info(f"DB: {db_path}")

    # 2. ÐÐ¿ÑÐ¸Ð¾Ð½Ð°Ð»ÑÐ½Ð¾ â ÑÐ²ÐµÐ¶Ð¸Ðµ Ð´Ð°Ð½Ð½ÑÐµ Ð¸Ð· DeFiLlama
    if fetch:
        log.info("Fetching DeFiLlama dataâ¦")
        try:
            from data_pipeline.defillama_fetcher import DeFiLlamaFetcher
            fetcher = DeFiLlamaFetcher(db_path=db_path)
            result = fetcher.fetch_all()
            fetched = result.get("fetched", 0)
            errors  = result.get("errors", 0)
            log.info(f"DeFiLlama: {fetched} fetched, {errors} errors")
        except Exception as e:
            log.error(f"DeFiLlama fetch failed (using cached): {e}")

    # 3. Paper Trader: Ð¾Ð±Ð½Ð¾Ð²Ð¸ÑÑ PnL â Ð¿Ð¾Ð¿ÑÐ¾Ð±Ð¾Ð²Ð°ÑÑ Ð¾ÑÐºÑÑÑÑ Ð¿Ð¾Ð·Ð¸ÑÐ¸Ð¸ â ÑÐºÑÐ¿Ð¾ÑÑ ÑÑÐ°ÑÑÑÐ°
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

    # 6. strategy_state.json  (ÑÑÐ¾Ð½Ð¾Ð»Ð¾Ð³Ð¸ÑÐµÑÐºÐ¸Ð¹ Ð¿Ð¾ÑÑÐ´Ð¾Ðº Ð´Ð»Ñ Ð³ÑÐ°ÑÐ¸ÐºÐ¾Ð²)
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

    # 7. trades.json (Ð¿Ð¾ÑÐ»ÐµÐ´Ð½Ð¸Ðµ 30 ÑÐ´ÐµÐ»Ð¾Ðº)
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

    # 8. meta.json â Ð²ÑÐµÐ¼Ñ Ð¾Ð±Ð½Ð¾Ð²Ð»ÐµÐ½Ð¸Ñ
    write_json("meta.json", {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "version": "1.0.0",
        "source": "github-actions" if fetch else "local",
    })

    # 9. alerts.json â AlertEngine: Ð°Ð½Ð¾Ð¼Ð°Ð»Ð¸Ð¸ APY/TVL + pipeline health
    try:
        from monitor.alerts import AlertEngine
        with get_connection(db_path) as conn:
            rows_ranked = conn.execute("""
                WITH ranked AS (
                    SELECT protocol_key, apy_total, apy_base, apy_reward,
                           tvl_usd, timestamp,
                           ROW_NUMBER() OVER (
                               PARTITION BY protocol_key ORDER BY timestamp DESC
                           ) AS rn
                    FROM apy_snapshots
                    WHERE is_valid = 1
                )
                SELECT * FROM ranked WHERE rn <= 2
            """).fetchall()
        all_snaps     = [dict(r) for r in rows_ranked]
        current_snaps = [s for s in all_snaps if s["rn"] == 1]
        prev_snaps    = [s for s in all_snaps if s["rn"] == 2]
        engine = AlertEngine()
        all_alerts = engine.check_snapshots(current_snaps, prev_snaps)
        all_alerts += engine.check_pipeline_health(current_snaps)
        write_json("alerts.json", {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "count": len(all_alerts),
            "alerts": [
                {
                    "severity": a.severity,
                    "event_type": a.event_type,
                    "protocol_key": a.protocol_key,
                    "message": a.message,
                    "details": a.details,
                    "timestamp": a.timestamp,
                }
                for a in all_alerts
            ],
        })
    except Exception as e:
        log.error(f"alerts export failed: {e}")
        write_json("alerts.json", {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "count": 0,
            "alerts": [],
            "error": str(e),
        })

    log.info(f"â Export complete â {OUTPUT_DIR}/")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s â %(message)s",
    )
    parser = argparse.ArgumentParser(description="SPA Data Exporter")
    parser.add_argument("--fetch", action="store_true",
                        help="Fetch fresh data from DeFiLlama before export")
    args = parser.parse_args()
    run_export(fetch=args.fetch)
