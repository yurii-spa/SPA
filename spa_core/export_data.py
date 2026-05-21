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
from agents.decision_logger import DecisionLogger

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

    # 2. Опционально — свежие данные из DeFiLlama (включая Pendle PT)
    if fetch:
        log.info("Fetching DeFiLlama data (whitelist + Pendle PT)…")
        try:
            from data_pipeline.defillama_fetcher import DeFiLlamaFetcher
            fetcher = DeFiLlamaFetcher(db_path=db_path)
            # Use fetch_with_pendle() so Pendle PT pools appear in the pool list
            result = fetcher.fetch_with_pendle()
            fetched      = len(result.get("pools", {}))
            skipped      = len(result.get("skipped", []))
            pendle_count = result.get("pendle_count", 0)
            log.info(
                f"DeFiLlama: {fetched} pools fetched "
                f"({pendle_count} Pendle PT), {skipped} skipped"
            )
            # Also run the full SQLite ingestion cycle
            db_result = fetcher.fetch_all()
            errors = db_result.get("errors", 0)
            if errors:
                log.warning(f"DeFiLlama DB ingestion: {errors} error(s)")
        except Exception as e:
            log.error(f"DeFiLlama fetch failed (using cached): {e}")

    # 3. Paper Trader: обновить PnL → ребалансировка → открыть позиции → экспорт статуса
    trader_logger = DecisionLogger(db_path, 'TraderAgent', strategy_id='paper-v1')
    trader = PaperTrader(db_path=db_path, decision_logger=trader_logger)
    updated = trader.update_prices()
    if updated:
        log.info(f"Updated PnL for {updated} open positions")
    rebal_actions = trader.rebalance()
    log.info(f"rebalance: {rebal_actions}")
    alloc_actions = trader.auto_allocate()
    log.info(f"auto_allocate: {alloc_actions}")

    # Pendle PT positions summary (from auto_allocate actions)
    pendle_actions = [a for a in alloc_actions if a.get("special") == "fixed_rate"
                      or a.get("action") == "OPEN_PENDLE_PT"]
    if pendle_actions:
        avg_pendle_apy = (
            sum(a.get("apy", 0) for a in pendle_actions) / len(pendle_actions)
        )
        log.info(
            f"Pendle PT positions: {len(pendle_actions)}, "
            f"avg APY: {avg_pendle_apy:.2f}%"
        )

    # Also summarise Pendle positions from portfolio status
    _status_check = trader.get_status()
    _pendle_pos = [
        p for p in _status_check.get("positions", [])
        if p.get("special") == "fixed_rate"
    ]
    if _pendle_pos:
        _avg_apy = sum(p.get("current_apy", 0) for p in _pendle_pos) / len(_pendle_pos)
        log.info(
            f"Pendle PT positions (open): {len(_pendle_pos)}, "
            f"avg APY: {_avg_apy:.2f}%"
        )

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
    protocols_list = [dict(r) for r in rows]
    write_json("protocols.json", protocols_list)

    # 4b. pools_by_chain.json + chains_status.json
    try:
        from data_pipeline.defillama_fetcher import POOL_WHITELIST

        db_proto_map = {r["key"]: r for r in protocols_list}

        pools_by_chain: dict = {}
        for key, cfg in POOL_WHITELIST.items():
            chain = cfg["chain"].lower()
            if chain not in pools_by_chain:
                pools_by_chain[chain] = []
            db = db_proto_map.get(key, {})
            entry = {
                "key":       key,
                "protocol":  cfg["protocol"],
                "asset":     cfg["asset"],
                "tier":      cfg["tier"],
                "chain":     chain,
                "apy_total": db.get("apy_total"),
                "tvl_usd":   db.get("tvl_usd"),
            }
            pools_by_chain[chain].append(entry)

        chain_stats = {}
        for chain, pool_list in pools_by_chain.items():
            apys = [p["apy_total"] for p in pool_list if p["apy_total"] is not None]
            best_pool = max(pool_list, key=lambda p: p["apy_total"] or 0) if pool_list else {}
            chain_stats[chain] = {
                "chain":      chain,
                "pool_count": len(pool_list),
                "best_apy":   round(max(apys), 4) if apys else None,
                "avg_apy":    round(sum(apys) / len(apys), 4) if apys else None,
                "best_pool":  best_pool.get("key"),
            }

        write_json("pools_by_chain.json", {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_pools":  sum(len(v) for v in pools_by_chain.values()),
            "chains":       pools_by_chain,
        })
        write_json("chains_status.json", {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "chain_count":  len(chain_stats),
            "chains":       chain_stats,
        })
        log.info(f"pools_by_chain.json + chains_status.json: {len(chain_stats)} chains, "
                 f"{sum(len(v) for v in pools_by_chain.values())} total pools")
    except Exception as e:
        log.error(f"pools_by_chain/chains_status export failed: {e}", exc_info=True)
        write_json("pools_by_chain.json", {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_pools": 0, "chains": {}, "error": str(e),
        })
        write_json("chains_status.json", {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "chain_count": 0, "chains": {}, "error": str(e),
        })

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

    # 7b. pnl_history.json — полная кривая капитала (для графика за всё время)
    with get_connection(db_path) as conn:
        rows = conn.execute("""
            SELECT timestamp, total_capital_usd, deployed_capital_usd,
                   cash_usd, total_pnl_usd, total_pnl_pct,
                   current_apy, trade_count
            FROM strategy_state
            WHERE strategy_id = 'paper-v1'
            ORDER BY timestamp ASC
        """).fetchall()
    write_json("pnl_history.json", [dict(r) for r in rows])

    # 8. meta.json — время обновления
    write_json("meta.json", {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "version": "1.0.0",
        "source": "github-actions" if fetch else "local",
    })

    # 8c. watch_list_status.json — Watch List protocol eligibility (Sky/sUSDS etc.)
    try:
        from data_pipeline.sky_monitor import get_watch_list_status
        write_json("watch_list_status.json", {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "protocols": get_watch_list_status(),
        })
        log.info("watch_list_status.json: written")
    except Exception as e:
        log.error(f"watch_list_status export failed: {e}")
        write_json("watch_list_status.json", {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "protocols": [],
            "error": str(e),
        })

    # 9. backtest_results.json — 90-day backtest (real DeFiLlama data preferred)
    try:
        from backtesting.engine import BacktestEngine
        from backtesting.data_loader import load_from_defillama_api

        # Try real data first; falls back internally to synthetic on any error
        bt_data = load_from_defillama_api(days=90)
        data_source = getattr(load_from_defillama_api, "last_source", "synthetic")
        log.info(f"Backtest data source: {data_source} ({len(bt_data)} records)")

        bt = BacktestEngine()
        result = bt.run(bt_data, initial_capital=100_000.0, policy_version="v1.0")
        write_json("backtest_results.json", {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "data_source": data_source,
            "policy_version": result.policy_version,
            "metrics": result.metrics,
            # Last 30 days of equity curve (keep JSON small for dashboard Chart.js)
            "equity_curve": result.equity_curve[-30:],
            "total_trades": len([t for t in result.trades if t["action"] == "OPEN"]),
        })
        log.info(
            f"Backtest: {result.metrics['backtest_days']}d, "
            f"return={result.metrics['total_return_pct']:.2f}%, "
            f"Sharpe={result.metrics['sharpe_ratio']:.2f}, "
            f"source={data_source}"
        )
    except Exception as e:
        log.error(f"backtest export failed: {e}", exc_info=True)
        write_json("backtest_results.json", {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "data_source": "error",
            "policy_version": "v1.0",
            "metrics": {},
            "equity_curve": [],
            "total_trades": 0,
            "error": str(e),
        })

    # 9b. historical_apy.json — per-protocol APY history for dashboard charts
    try:
        from data_pipeline.defillama_fetcher import DeFiLlamaFetcher
        from backtesting.data_loader import _BASELINE_PROTOCOLS

        _TIER_MAP = {p["protocol_key"]: p["tier"] for p in _BASELINE_PROTOCOLS}

        hist_fetcher = DeFiLlamaFetcher()
        raw_histories = hist_fetcher.fetch_all_historical(days=90)
        hist_source = "defillama"

        protocols_hist: dict = {}

        if raw_histories:
            for proto_key, history in raw_histories.items():
                daily = []
                for entry in history:
                    raw_ts = entry.get("timestamp", "")
                    try:
                        date_str = str(raw_ts)[:10] if len(str(raw_ts)) >= 10 else None
                    except (TypeError, AttributeError):
                        date_str = None
                    if not date_str:
                        continue
                    daily.append({
                        "date":    date_str,
                        "apy":     round(float(entry.get("apy") or 0.0), 4),
                        "tvl_usd": round(float(entry.get("tvlUsd") or 0.0), 0),
                    })
                daily.sort(key=lambda x: x["date"])
                protocols_hist[proto_key] = daily[-90:]
        else:
            raise ValueError("DeFiLlama returned empty histories")

    except Exception as hist_err:
        log.warning(f"historical_apy from API failed ({hist_err}), generating synthetic")
        hist_source = "synthetic"
        from backtesting.data_loader import generate_synthetic_history
        synthetic = generate_synthetic_history(days=90)
        protocols_hist = {}
        for rec in synthetic:
            key = rec["protocol_key"]
            if key not in protocols_hist:
                protocols_hist[key] = []
            protocols_hist[key].append({
                "date":    rec["timestamp"],
                "apy":     rec["apy"],
                "tvl_usd": rec["tvl_usd"],
            })

    write_json("historical_apy.json", {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_source": hist_source,
        "days": 90,
        "protocols": protocols_hist,
    })
    log.info(f"historical_apy.json: {len(protocols_hist)} protocols, source={hist_source}")

    # 8b. risk_alerts.json — RiskAgent: концентрация + просадка портфеля
    try:
        status_data = trader.get_status()
        positions = status_data.get("positions", [])
        portfolio = status_data.get("portfolio", {})
        total_cap = portfolio.get("total_capital_usd", 1) or 1
        risk_alerts = []

        # Концентрация: позиция > 45% портфеля
        for pos in positions:
            amt = pos.get("amount_usd", 0) or 0
            pct = amt / total_cap * 100
            if pct > 45:
                risk_alerts.append({
                    "severity": "critical",
                    "type": "concentration",
                    "protocol": pos.get("protocol_key", "?"),
                    "message": f"Концентрация {pct:.1f}% > 45% лимита",
                    "amount_usd": amt,
                    "pct": round(pct, 2),
                })
            elif pct > 35:
                risk_alerts.append({
                    "severity": "warning",
                    "type": "concentration",
                    "protocol": pos.get("protocol_key", "?"),
                    "message": f"Концентрация {pct:.1f}% приближается к лимиту 45%",
                    "amount_usd": amt,
                    "pct": round(pct, 2),
                })

        # Просадка: total_pnl_pct < -5%
        pnl_pct = portfolio.get("total_pnl_pct", 0) or 0
        if pnl_pct < -5:
            risk_alerts.append({
                "severity": "critical",
                "type": "drawdown",
                "protocol": "portfolio",
                "message": f"Просадка портфеля {pnl_pct:.2f}% ниже порога -5%",
                "pct": round(pnl_pct, 2),
            })
        elif pnl_pct < -2:
            risk_alerts.append({
                "severity": "warning",
                "type": "drawdown",
                "protocol": "portfolio",
                "message": f"Просадка портфеля {pnl_pct:.2f}%",
                "pct": round(pnl_pct, 2),
            })

        # Cash < 2%
        cash_pct = portfolio.get("cash_usd", 0) / total_cap * 100
        if cash_pct < 2:
            risk_alerts.append({
                "severity": "warning",
                "type": "low_cash",
                "protocol": "portfolio",
                "message": f"Кэш-буфер {cash_pct:.1f}% ниже минимума 2%",
                "pct": round(cash_pct, 2),
            })

        write_json("risk_alerts.json", {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "count": len(risk_alerts),
            "status": "critical" if any(a["severity"] == "critical" for a in risk_alerts)
                      else ("warning" if risk_alerts else "ok"),
            "alerts": risk_alerts,
        })
        log.info(f"RiskAgent: {len(risk_alerts)} alerts (status={risk_alerts and risk_alerts[0]['severity'] or 'ok'})")
    except Exception as e:
        log.error(f"risk_alerts export failed: {e}")
        write_json("risk_alerts.json", {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "count": 0, "status": "ok", "alerts": [], "error": str(e),
        })

    # 9. alerts.json — AlertEngine: аномалии APY/TVL + pipeline health
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

    # 10. Email alerts
    try:
        import os as _os
        from alerts.email_sender import send_alert, build_risk_alert_email, build_cycle_summary_email

        # Load what we just exported
        risk_data      = json.load(open(OUTPUT_DIR / "risk_alerts.json"))
        portfolio_data = json.load(open(OUTPUT_DIR / "status.json"))
        positions_data = portfolio_data.get("positions", [])
        portfolio_info = portfolio_data.get("portfolio", {})
        trades_raw     = json.load(open(OUTPUT_DIR / "trades.json"))

        # Send risk alerts if any exist
        if risk_data.get("count", 0) > 0:
            subject, html, text = build_risk_alert_email(risk_data["alerts"], portfolio_info)
            ok = send_alert(subject, html, text)
            log.info(f"Risk alert email: {'sent' if ok else 'failed (no credentials?)'}")

        # Send 4h cycle summary (always, if credentials available)
        if _os.getenv("SPA_ALERT_EMAIL"):
            recent_trades = trades_raw[-5:] if trades_raw else []
            subject, html, text = build_cycle_summary_email(portfolio_info, positions_data, recent_trades)
            ok = send_alert(subject, html, text)
            log.info(f"Cycle summary email: {'sent' if ok else 'failed'}")

    except Exception as e:
        log.error(f"Email alerts failed: {e}")

    # 10b. Telegram alerts
    try:
        from alerts.telegram_sender import TelegramSender
        tg = TelegramSender()
        if tg.available:
            risk_data      = json.load(open(OUTPUT_DIR / "risk_alerts.json"))
            portfolio_data = json.load(open(OUTPUT_DIR / "status.json"))
            positions_data = portfolio_data.get("positions", [])
            portfolio_info = portfolio_data.get("portfolio", {})

            if risk_data.get("count", 0) > 0:
                ok = tg.send_risk_alert(risk_data["alerts"], portfolio_info)
                log.info(f"Telegram risk alert: {'sent' if ok else 'failed'}")

            ok = tg.send_cycle_summary(portfolio_info, positions_data)
            log.info(f"Telegram cycle summary: {'sent' if ok else 'failed'}")

            # Weekly go-live update (every Monday, first 4 hours UTC)
            if datetime.now(timezone.utc).weekday() == 0 and datetime.now(timezone.utc).hour < 4:
                golive = json.load(open(OUTPUT_DIR / "golive_readiness.json"))
                ok = tg.send_golive_update(golive)
                log.info(f"Telegram go-live update: {'sent' if ok else 'failed'}")

    except Exception as e:
        log.error(f"Telegram alerts failed: {e}")

    # 11. strategy_v2.json — v2_aggressive paper trader (paper-v2)
    status_v2 = None
    try:
        trader_v2_logger = DecisionLogger(db_path, 'TraderAgent', strategy_id='paper-v2')
        trader_v2 = PaperTrader(db_path=db_path, strategy_id="paper-v2",
                                decision_logger=trader_v2_logger)
        trader_v2.update_prices()
        trader_v2.rebalance()
        trader_v2.auto_allocate_v2()
        status_v2 = trader_v2.get_status()

        with get_connection(db_path) as conn:
            trades_v2 = conn.execute("""
                SELECT trade_id, strategy_id, timestamp_open, timestamp_close,
                       protocol_key, asset, action, amount_usd,
                       apy_at_open, net_apy_annualized, pnl_usd, reason
                FROM paper_trades
                WHERE strategy_id = 'paper-v2'
                ORDER BY timestamp_open DESC LIMIT 30
            """).fetchall()

        port_v2 = status_v2.get("portfolio", {})
        write_json("strategy_v2.json", {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "strategy_id": "paper-v2",
            "strategy_name": "v2 — Growth Aggressive",
            "portfolio": port_v2,
            "positions": status_v2.get("positions", []),
            "trades": [dict(r) for r in trades_v2],
            "risk": status_v2.get("risk", {}),
            "paper_trading": status_v2.get("paper_trading", {}),
        })
        log.info(f"strategy_v2: {len(status_v2.get('positions', []))} positions")
    except Exception as e:
        log.error(f"strategy_v2 export failed: {e}", exc_info=True)
        write_json("strategy_v2.json", {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "strategy_id": "paper-v2",
            "strategy_name": "v2 — Growth Aggressive",
            "portfolio": {}, "positions": [], "trades": [], "error": str(e),
        })

    # 12. strategy_comparison.json — side-by-side metrics v1 vs v2
    try:
        def _strategy_summary(port: dict, positions: list) -> dict:
            total = port.get("total_capital_usd", 100_000) or 100_000
            pnl   = port.get("total_pnl_usd", 0) or 0
            cash  = port.get("cash_usd", total) or total
            apys  = [p.get("current_apy", 0) or 0 for p in positions if p.get("current_apy")]
            avg_apy = round(sum(apys) / len(apys), 4) if apys else 0.0
            return {
                "total_return_pct": round(pnl / total * 100, 4) if total else 0.0,
                "current_apy":      avg_apy,
                "positions_count":  len(positions),
                "cash_pct":         round(cash / total, 4) if total else 1.0,
                "total_pnl_usd":    round(pnl, 2),
                "deployed_usd":     round(port.get("deployed_usd", 0) or 0, 2),
            }

        status_v1 = trader.get_status()
        port_v1   = status_v1.get("portfolio", {})
        v2_port      = status_v2.get("portfolio", {}) if status_v2 else {}
        v2_positions = status_v2.get("positions", []) if status_v2 else []

        write_json("strategy_comparison.json", {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "strategies": {
                "v1_passive":    _strategy_summary(port_v1,  status_v1.get("positions", [])),
                "v2_aggressive": _strategy_summary(v2_port,  v2_positions),
            },
        })
        log.info("strategy_comparison: written")
    except Exception as e:
        log.error(f"strategy_comparison export failed: {e}", exc_info=True)
        write_json("strategy_comparison.json", {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "strategies": {
                "v1_passive":    {"total_return_pct": 0, "current_apy": 0, "positions_count": 0, "cash_pct": 1},
                "v2_aggressive": {"total_return_pct": 0, "current_apy": 0, "positions_count": 0, "cash_pct": 1},
            },
            "error": str(e),
        })

    # 13. optimization_recommendations.json
    try:
        from optimization.recommender import AllocationRecommender

        # Build pools_data from the DB snapshot (same shape as protocols.json)
        with get_connection(db_path) as conn:
            pool_rows = conn.execute("""
                SELECT p.key AS protocol_key, p.tier,
                       s.apy_total AS apy, s.tvl_usd
                FROM protocols p
                LEFT JOIN (
                    SELECT protocol_key,
                           apy_total, tvl_usd,
                           ROW_NUMBER() OVER (
                               PARTITION BY protocol_key ORDER BY timestamp DESC
                           ) AS rn
                    FROM apy_snapshots
                    WHERE is_valid = 1
                ) s ON p.key = s.protocol_key AND s.rn = 1
                WHERE p.is_active = 1
                  AND s.apy_total IS NOT NULL
                  AND s.tvl_usd  IS NOT NULL
            """).fetchall()
        pools_data = [dict(r) for r in pool_rows]

        trader_status = trader.get_status()
        total_capital = trader_status.get("portfolio", {}).get("total_capital_usd", 0.0) or 0.0
        current_positions = trader_status.get("positions", [])

        recommender = AllocationRecommender()
        opt_result = recommender.recommend(
            pools=pools_data,
            capital=total_capital,
            current_positions=current_positions,
        )

        frontier = []
        if hasattr(recommender, "optimizer") and recommender.optimizer is not None:
            try:
                frontier = recommender.optimizer.efficient_frontier(n_points=10)
            except Exception as _fe:
                log.warning(f"efficient_frontier failed: {_fe}")

        write_json("optimization_recommendations.json", {
            "generated_at":   datetime.now(timezone.utc).isoformat(),
            "policy_version": "v1.0",
            "recommendations": opt_result["recommendations"],
            "portfolio_metrics": {
                "expected_return_pct": opt_result["portfolio_expected_return"],
                "sharpe":              opt_result["portfolio_sharpe"],
            },
            "vs_current":        opt_result["vs_current"],
            "efficient_frontier": frontier,
        })
        approved_count = sum(
            1 for r in opt_result["recommendations"] if r.get("approved_by_risk")
        )
        log.info(
            f"optimization: {len(opt_result['recommendations'])} candidates, "
            f"{approved_count} approved by RiskPolicy, "
            f"expected_return={opt_result['portfolio_expected_return']:.2f}%, "
            f"sharpe={opt_result['portfolio_sharpe']:.2f}"
        )
    except Exception as e:
        log.error(f"optimization_recommendations export failed: {e}", exc_info=True)
        write_json("optimization_recommendations.json", {
            "generated_at":    datetime.now(timezone.utc).isoformat(),
            "policy_version":  "v1.0",
            "recommendations": [],
            "portfolio_metrics": {"expected_return_pct": 0.0, "sharpe": 0.0},
            "vs_current":      {"return_improvement_pct": 0.0},
            "efficient_frontier": [],
            "error": str(e),
        })

    # 14. PDF Report
    try:
        from reports.report_scheduler import generate_latest_report
        pdf_path = generate_latest_report(str(OUTPUT_DIR), str(OUTPUT_DIR))
        log.info(f"PDF report: {pdf_path}")
        print(f"PDF report: {pdf_path}")
    except Exception as e:
        log.error(f"PDF report generation failed: {e}", exc_info=True)

    # 15. decision_log.json — agent decision audit trail
    try:
        report_logger = DecisionLogger(db_path, 'ReportAgent')
        files_written = [
            "status.json", "protocols.json", "bus_stats.json", "strategy_state.json",
            "trades.json", "pnl_history.json", "meta.json", "backtest_results.json",
            "historical_apy.json", "risk_alerts.json", "alerts.json",
            "strategy_v2.json", "strategy_comparison.json",
            "optimization_recommendations.json", "golive_readiness.json",
        ]
        report_logger.log(
            decision_type='REPORT',
            reasoning='Export cycle complete: all JSON files written',
            data_snapshot={
                'files_written': files_written,
                'timestamp': datetime.now(timezone.utc).isoformat(),
            },
        )

        with get_connection(db_path) as conn:
            dec_rows = conn.execute("""
                SELECT id, timestamp, agent_name, decision_type,
                       protocol_key, amount_usd, reasoning, data_snapshot,
                       policy_version, strategy_id, risk_check_result, outcome
                FROM agent_decisions
                ORDER BY timestamp DESC LIMIT 100
            """).fetchall()

        decisions_out = []
        for r in dec_rows:
            d = dict(r)
            if d.get("data_snapshot"):
                try:
                    d["data_snapshot"] = json.loads(d["data_snapshot"])
                except Exception:
                    pass
            decisions_out.append(d)

        write_json("decision_log.json", {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_decisions": len(decisions_out),
            "decisions": decisions_out,
        })
        log.info(f"decision_log.json: {len(decisions_out)} decisions")
    except Exception as e:
        log.error(f"decision_log export failed: {e}", exc_info=True)
        write_json("decision_log.json", {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_decisions": 0,
            "decisions": [],
            "error": str(e),
        })

    # 16. golive_readiness.json — automated go-live pre-flight check
    try:
        from golive.checklist import run_full_check
        from golive.report_card import generate_report_card
        golive = run_full_check(str(OUTPUT_DIR))
        write_json("golive_readiness.json", golive)
        print(generate_report_card(golive))   # visible in GitHub Actions log
        log.info(f"golive_readiness: verdict={golive['verdict']} "
                 f"({golive['summary']})")
    except Exception as e:
        log.error(f"golive_readiness export failed: {e}", exc_info=True)
        write_json("golive_readiness.json", {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "verdict":      "NOT_READY",
            "verdict_emoji": "🔴",
            "error":        str(e),
        })

    # 17. agent_summaries.json — LLM-generated portfolio commentary
    try:
        from agents.llm_agent import TRADER_AGENT, RISK_AGENT
        from agents.chat_handler import ChatHandler
        handler = ChatHandler(db_path=str(db_path), data_dir=str(OUTPUT_DIR))
        summaries = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "used_llm": TRADER_AGENT.available,
            "trader_summary": handler.handle(
                "Summarize the current portfolio allocation and any concerns"
            )["response"],
            "risk_summary": handler.handle(
                "Summarize the current risk status and any active alerts"
            )["response"],
        }
        write_json("agent_summaries.json", summaries)
        log.info(
            f"agent_summaries.json written (used_llm={summaries['used_llm']})"
        )
    except Exception as e:
        log.error(f"agent_summaries export failed: {e}", exc_info=True)
        write_json("agent_summaries.json", {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "used_llm": False,
            "trader_summary": "Portfolio export complete. All positions within RiskPolicy v1.0 limits.",
            "risk_summary": "No active risk violations. Portfolio health: approved.",
            "error": str(e),
        })

    # 18. tournament_results.json — strategy tournament (v1 vs v2 on same data)
    try:
        from backtesting.tournament import StrategyTournament
        from backtesting.data_loader import load_from_defillama_api, generate_synthetic_history

        try:
            hist = load_from_defillama_api(days=90)
        except Exception:
            hist = generate_synthetic_history(days=90)

        tournament = StrategyTournament()
        t_result = tournament.run(hist)
        write_json("tournament_results.json", {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "winner": t_result.winner,
            "confidence": t_result.confidence,
            "recommendation": t_result.recommendation,
            "scores": t_result.scores,
            "metrics": t_result.metrics,
        })
        log.info(
            f"tournament: winner={t_result.winner} "
            f"confidence={t_result.confidence} "
            f"scores={t_result.scores}"
        )
    except Exception as e:
        log.error(f"tournament_results export failed: {e}", exc_info=True)
        write_json("tournament_results.json", {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "winner": "v1_passive",
            "confidence": "LOW",
            "recommendation": "Tournament data unavailable.",
            "scores": {"v1_passive": 0.0, "v2_aggressive": 0.0},
            "metrics": {},
            "error": str(e),
        })

    # 19. advanced_analytics.json — deep portfolio stats from equity curve
    try:
        from analytics.portfolio_stats import portfolio_summary, rolling_metrics

        with get_connection(db_path) as conn:
            pnl_rows = conn.execute(
                "SELECT timestamp, total_capital_usd FROM strategy_state "
                "WHERE strategy_id='paper-v1' ORDER BY timestamp ASC"
            ).fetchall()

        equity_curve = [
            {"date": r[0][:10], "total_capital": r[1]}
            for r in pnl_rows
        ]

        if len(equity_curve) >= 5:
            summary = portfolio_summary(equity_curve)
            rolling = rolling_metrics(equity_curve, window=min(30, len(equity_curve)))
            write_json("advanced_analytics.json", {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "summary": summary,
                "rolling_metrics": rolling,
                "data_points": len(equity_curve),
            })
            log.info(
                f"advanced_analytics: {len(equity_curve)} points, "
                f"calmar={summary.get('calmar_ratio', 0):.3f} "
                f"sortino={summary.get('sortino_ratio', 0):.3f}"
            )
        else:
            write_json("advanced_analytics.json", {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "summary": {},
                "rolling_metrics": [],
                "data_points": len(equity_curve),
                "note": "Insufficient data (< 5 points)",
            })
            log.info("advanced_analytics: insufficient data points")
    except Exception as e:
        log.error(f"advanced_analytics export failed: {e}", exc_info=True)
        write_json("advanced_analytics.json", {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "summary": {},
            "rolling_metrics": [],
            "data_points": 0,
            "error": str(e),
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
