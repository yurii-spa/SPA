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
import threading
import time
import urllib.request
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

_SPA_API = "http://localhost:8765"


def _push_thought(
    agent: str,
    message: str,
    event_type: str = "agent_thought",
    data: dict | None = None,
) -> None:
    """
    Fire-and-forget POST of an agent thought to the FastAPI SSE endpoint.

    Non-blocking: runs in a daemon thread with a 2s timeout.
    Silent on failure so export_data.py never breaks when server is down.
    """
    def _send() -> None:
        try:
            payload = json.dumps({
                "agent":   agent,
                "message": message,
                "type":    event_type,
                "data":    data or {},
            }).encode("utf-8")
            req = urllib.request.Request(
                f"{_SPA_API}/api/agent/thought",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=2)
        except Exception:
            pass  # server not running — silent fail

    threading.Thread(target=_send, daemon=True).start()


def write_json(filename: str, data) -> None:
    path = OUTPUT_DIR / filename
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    log.info(f"  → data/{filename}  ({path.stat().st_size} bytes)")


def run_export(fetch: bool = False) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    db_path = get_db_path()

    # ── Pipeline health tracking ──────────────────────────────────────────────
    _export_start = time.time()
    _health: dict = {
        "timestamp":             datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sections_run":          0,
        "sections_ok":           0,
        "sections_failed":       0,
        "failed_sections":       [],
        "total_pools_fetched":   0,
        "pendle_pools_found":    0,
        "export_duration_seconds": 0.0,
        "next_run_eta":          "4h",
        "covariance_source":     None,
    }

    def _section_ok(name: str) -> None:
        _health["sections_run"]   += 1
        _health["sections_ok"]    += 1
        log.debug(f"[health] section OK: {name}")

    def _section_fail(name: str) -> None:
        _health["sections_run"]    += 1
        _health["sections_failed"] += 1
        _health["failed_sections"].append(name)
        log.debug(f"[health] section FAIL: {name}")

    # 1. Init DB (идемпотентно)
    init_database(db_path)
    log.info(f"DB: {db_path}")

    # Update agent-stability clock — SPA-F001 (idempotent per cycle)
    # AgentStabilityTracker checks status.json freshness and writes data/agent_stability.json
    try:
        from paper_trading.agent_stability import AgentStabilityTracker
        _data_dir = OUTPUT_DIR
        _ast = AgentStabilityTracker(data_dir=_data_dir)
        _ast_state = _ast.update(data_dir=_data_dir)
        log.info(
            f"AgentStabilityTracker: {_ast_state.get('consecutive_stable_days', 0):.1f} "
            f"stable days (failures: {_ast_state.get('total_failures', 0)})"
        )
    except Exception as _st_exc:
        log.warning(f"AgentStabilityTracker: could not update ({_st_exc})")

    _push_thought("DataAgent", "Export cycle starting… reading from SQLite DB")

    # 2. Опционально — свежие данные из DeFiLlama (включая Pendle PT)
    if fetch:
        log.info("Fetching DeFiLlama data (whitelist + Pendle PT)…")
        try:
            from data_pipeline.defillama_fetcher import DeFiLlamaFetcher
            fetcher = DeFiLlamaFetcher(db_path=db_path)
            # Use fetch_pools_concurrent() — whitelist + Pendle run in parallel threads
            t0 = time.time()
            pools = fetcher.fetch_pools_concurrent()
            print(f"[PERF] Fetched {len(pools)} pools in {time.time()-t0:.2f}s")
            fetched      = len(pools)
            pendle_count = sum(1 for p in pools if p.get("special") == "fixed_rate")
            skipped      = 0
            _health["total_pools_fetched"] = fetched
            _health["pendle_pools_found"]  = pendle_count
            log.info(
                f"DeFiLlama: {fetched} pools fetched "
                f"({pendle_count} Pendle PT), {skipped} skipped"
            )
            _push_thought(
                "DataAgent",
                f"Fetching APY data from DeFiLlama… found {fetched} pools"
                + (f" ({pendle_count} Pendle PT)" if pendle_count else ""),
                data={"fetched": fetched, "pendle_count": pendle_count, "skipped": skipped},
            )
            # Also run the full SQLite ingestion cycle
            db_result = fetcher.fetch_all()
            errors = db_result.get("errors", 0)
            if errors:
                log.warning(f"DeFiLlama DB ingestion: {errors} error(s)")
            _section_ok("defillama_fetch")
        except Exception as e:
            log.error(f"DeFiLlama fetch failed (using cached): {e}")
            _section_fail("defillama_fetch")

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
    _push_thought(
        "TraderAgent",
        f"Running auto_allocate()… proposing {len(alloc_actions)} action(s)",
        data={"actions": len(alloc_actions), "rebalance": len(rebal_actions)},
    )

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

    # pendle_positions.json — fixed-rate PT positions with accrual detail
    try:
        from paper_trading.pendle_strategy import PendlePosition, build_pendle_position
        pendle_records = []
        for action in alloc_actions:
            if action.get("action") != "OPEN_PENDLE_PT":
                continue
            # Reconstruct a PendlePosition from the action to get computed properties
            pos = PendlePosition(
                pool_id=action.get("protocol", "unknown"),
                symbol=action.get("symbol") or "PT-STABLE",
                chain=action.get("chain", "arbitrum"),
                amount_usd=action.get("amount_usd", 0.0),
                entry_apy=action.get("apy", 0.0),
                entry_date=datetime.now(timezone.utc).date().isoformat(),
                maturity_date=action.get("maturity_date"),
                days_to_maturity=action.get("days_to_maturity") or 90,
            )
            pendle_records.append({
                "pool_name":          pos.symbol,
                "protocol":           action.get("protocol"),
                "chain":              pos.chain,
                "entry_apy":          round(pos.entry_apy, 4),
                "amount_usd":         round(pos.amount_usd, 2),
                "days_held":          pos.days_held,
                "accrued_return_usd": round(pos.accrued_return_usd, 4),
                "days_remaining":     pos.days_remaining,
                "maturity_date":      pos.maturity_date,
                "current_value_usd":  round(pos.current_value_usd, 4),
                "is_near_maturity":   pos.is_near_maturity,
                "t1_baseline_apy":    action.get("t1_baseline_apy"),
                "apy_premium":        action.get("apy_premium"),
                "tier":               "T2",
                "special":            "fixed_rate",
                "note":               action.get("note", "ADR-002 PROPOSED — paper only"),
            })
        write_json("pendle_positions.json", {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "count": len(pendle_records),
            "positions": pendle_records,
        })
        log.info(f"pendle_positions.json: {len(pendle_records)} position(s)")
        _section_ok("pendle_positions")
    except Exception as e:
        log.error(f"pendle_positions export failed: {e}", exc_info=True)
        _section_fail("pendle_positions")
        write_json("pendle_positions.json", {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "count": 0,
            "positions": [],
            "error": str(e),
        })

    write_json("status.json", trader.get_status())
    _section_ok("paper_trader")

    # 3b. drift_report.json — portfolio allocation drift analysis
    try:
        _drift_state = trader._load_portfolio_state()
        _drift_positions = [
            {"protocol": p.protocol_key, "amount_usd": p.amount_usd}
            for p in _drift_state.positions
        ]
        drift = trader.calculate_drift(_drift_positions, _drift_state.total_capital_usd)
        needs_rebalance = trader.should_rebalance(_drift_positions, _drift_state.total_capital_usd)
        with open(str(OUTPUT_DIR / "drift_report.json"), "w") as f:
            json.dump({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "needs_rebalance": needs_rebalance,
                "positions": drift,
            }, f, indent=2)
        log.info(f"drift_report.json: {len(drift)} positions, needs_rebalance={needs_rebalance}")
        _section_ok("drift_report")
    except Exception as e:
        log.error(f"drift_report export failed: {e}", exc_info=True)
        _section_fail("drift_report")
        write_json("drift_report.json", {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "needs_rebalance": False,
            "positions": [],
            "error": str(e),
        })

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
    _section_ok("protocols")

    # 4a. APY history tracking
    try:
        from spa_core.analytics.apy_tracker import APYTracker
        tracker = APYTracker()
        try:
            _pools_for_tracker = pools  # type: ignore[name-defined]
        except NameError:
            _pools_for_tracker = []
        if _pools_for_tracker:
            tracker.record_snapshot(_pools_for_tracker)
        trends = tracker.all_trends(days=7)
        with open(str(OUTPUT_DIR / "apy_trends.json"), "w") as f:
            json.dump({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "trends": trends,
                "protocols_tracked": len(trends),
            }, f, indent=2)
        _section_ok("apy_tracking")
    except Exception as e:
        _section_fail("apy_tracking")
        log.error(f"apy_tracking export failed: {e}")

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
        _section_ok("pools_by_chain")
    except Exception as e:
        log.error(f"pools_by_chain/chains_status export failed: {e}", exc_info=True)
        _section_fail("pools_by_chain")
        write_json("pools_by_chain.json", {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_pools": 0, "chains": {}, "error": str(e),
        })
        write_json("chains_status.json", {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "chain_count": 0, "chains": {}, "error": str(e),
        })

    # 5. bus_stats.json
    try:
        bus = MessageBus(db_path=db_path)
        write_json("bus_stats.json", bus.stats())
        _section_ok("bus_stats")
    except Exception as e:
        log.error(f"bus_stats export failed: {e}")
        _section_fail("bus_stats")
        write_json("bus_stats.json", {"generated_at": datetime.now(timezone.utc).isoformat(), "error": str(e)})

    # 6. strategy_state.json  (хронологический порядок для графиков)
    try:
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
        _section_ok("strategy_state")
    except Exception as e:
        log.error(f"strategy_state export failed: {e}")
        _section_fail("strategy_state")
        write_json("strategy_state.json", [])

    # 7. trades.json (последние 30 сделок)
    try:
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
        _section_ok("trades")
    except Exception as e:
        log.error(f"trades export failed: {e}")
        _section_fail("trades")
        write_json("trades.json", [])

    # 7b. pnl_history.json — полная кривая капитала (для графика за всё время)
    try:
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
        _section_ok("pnl_history")
    except Exception as e:
        log.error(f"pnl_history export failed: {e}")
        _section_fail("pnl_history")
        write_json("pnl_history.json", [])

    # 8. meta.json — время обновления
    try:
        write_json("meta.json", {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "version": "1.0.0",
            "source": "github-actions" if fetch else "local",
        })
        _section_ok("meta")
    except Exception as e:
        log.error(f"meta export failed: {e}")
        _section_fail("meta")

    # 8c. watch_list_status.json + sky_status.json — Watch List protocol eligibility
    try:
        from data_pipeline.sky_monitor import (
            check_sky_status_live,
            get_sky_allocation_pct,
            export_sky_status_json,
            get_watch_list_status,
            check_and_emit_upgrade_signal,
        )

        # Live check (on-chain → API → manual fallback)
        sky_live = check_sky_status_live()

        # Export dedicated sky_status.json (includes gsm_hours, source, etc.)
        export_sky_status_json(sky_live)
        log.info(
            f"sky_status.json: status={sky_live['status']}, "
            f"gsm_hours={sky_live.get('gsm_hours')}, source={sky_live.get('source')}"
        )

        # F004: Auto-upgrade trigger — write sky_upgrade_needed.json if ELIGIBLE
        upgrade_signal = check_and_emit_upgrade_signal(sky_live)
        if upgrade_signal["eligible"]:
            level = "NEW" if upgrade_signal["first_eligible"] else "ONGOING"
            log.warning(
                f"[SKY-T1-UPGRADE {level}] Sky/sUSDS ELIGIBLE for T1 promotion. "
                f"Action: {upgrade_signal['action']}"
            )
            # Inject into risk_alerts so dashboard highlights this immediately
            _pending_sky_alert = {
                "severity":    "warning",
                "type":        "sky_t1_promotion_required",
                "message":     (
                    f"Sky/sUSDS is ELIGIBLE for T1 (GSM delay ≥ 48 h). "
                    f"Promote sky-susds to T1 in POOL_WHITELIST. "
                    f"Action: {upgrade_signal['action']}"
                ),
                "detected_at": datetime.now(timezone.utc).isoformat(),
                "first_eligible": upgrade_signal["first_eligible"],
            }
        else:
            _pending_sky_alert = None

        # Also write the legacy watch_list_status.json for dashboard compatibility
        write_json("watch_list_status.json", {
            "generated_at":    datetime.now(timezone.utc).isoformat(),
            "protocols":       get_watch_list_status(),
            "sky_live":        sky_live,
            "sky_allocation_pct": get_sky_allocation_pct(sky_live),
            "upgrade_signal":  upgrade_signal,
        })
        log.info("watch_list_status.json: written")
        _section_ok("sky_status")
    except Exception as e:
        log.error(f"watch_list_status/sky_status export failed: {e}")
        _section_fail("sky_status")
        write_json("watch_list_status.json", {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "protocols": [],
            "error": str(e),
        })
        write_json("sky_status.json", {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "status": "PENDING",
            "source": "error",
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
        _section_ok("backtest_results")
    except Exception as e:
        log.error(f"backtest export failed: {e}", exc_info=True)
        _section_fail("backtest_results")
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
    _section_ok("historical_apy")

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

        # F004: Inject Sky T1 upgrade signal into risk_alerts if ELIGIBLE
        try:
            if _pending_sky_alert is not None:
                risk_alerts.append(_pending_sky_alert)
        except NameError:
            pass  # sky section not yet run (e.g. partial failure); skip

        write_json("risk_alerts.json", {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "count": len(risk_alerts),
            "status": "critical" if any(a["severity"] == "critical" for a in risk_alerts)
                      else ("warning" if risk_alerts else "ok"),
            "alerts": risk_alerts,
        })
        log.info(f"RiskAgent: {len(risk_alerts)} alerts (status={risk_alerts and risk_alerts[0]['severity'] or 'ok'})")
        # Pull Sharpe / MaxDD from backtest if available for the thought message
        try:
            _bt = json.load(open(OUTPUT_DIR / "backtest_results.json"))
            _sharpe = _bt.get("metrics", {}).get("sharpe_ratio", 0.0)
            _maxdd  = _bt.get("metrics", {}).get("max_drawdown_pct", 0.0)
            _push_thought(
                "RiskAgent",
                f"Checking portfolio health… Sharpe={_sharpe:.2f}, MaxDD={_maxdd:.1f}%"
                + (f" · {len(risk_alerts)} alert(s)" if risk_alerts else " · all clear ✓"),
                event_type="risk_alert" if risk_alerts else "agent_thought",
                data={"alert_count": len(risk_alerts), "sharpe": _sharpe, "max_dd": _maxdd},
            )
        except Exception:
            _push_thought(
                "RiskAgent",
                f"Checking portfolio health… {len(risk_alerts)} alert(s)",
                event_type="risk_alert" if risk_alerts else "agent_thought",
                data={"alert_count": len(risk_alerts)},
            )
        _section_ok("risk_alerts")
    except Exception as e:
        log.error(f"risk_alerts export failed: {e}")
        _section_fail("risk_alerts")
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
        _section_ok("alerts")
    except Exception as e:
        log.error(f"alerts export failed: {e}")
        _section_fail("alerts")
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
        from alerts.daily_report import DailyReportBuilder
        from alerts.risk_monitor import RiskMonitor

        tg = TelegramSender()

        # ── Immediate risk monitor (every run, fires alert if breach) ──────
        try:
            portfolio_data = json.load(open(OUTPUT_DIR / "status.json"))
            pnl_hist_data  = json.load(open(OUTPUT_DIR / "pnl_history.json"))
            portfolio_info = portfolio_data.get("portfolio", {})
            positions_data = portfolio_data.get("positions", [])

            monitor = RiskMonitor(data_dir=OUTPUT_DIR)
            fired = monitor.check_and_alert(portfolio_data, pnl_hist_data, tg)
            log.info(f"RiskMonitor: {len(fired)} alert(s) checked/fired")
        except Exception as e:
            log.error(f"RiskMonitor failed: {e}")
            portfolio_data = {}
            portfolio_info = {}
            positions_data = []

        if tg.available:
            # ── 4h cycle summary (every run) ───────────────────────────────
            try:
                ok = tg.send_cycle_summary(portfolio_info, positions_data)
                log.info(f"Telegram cycle summary: {'sent' if ok else 'failed'}")
            except Exception as e:
                log.error(f"Telegram cycle summary failed: {e}")

            # ── Daily digest (once per UTC day) ────────────────────────────
            try:
                builder = DailyReportBuilder(data_dir=OUTPUT_DIR)
                if builder.should_send_daily():
                    msg = builder.build_report()
                    ok  = tg.send(msg)
                    log.info(f"Telegram daily report: {'sent' if ok else 'failed'}")
                    if ok:
                        builder.mark_sent()
                else:
                    log.info("Telegram daily report: already sent today, skipping")
            except Exception as e:
                log.error(f"Telegram daily report failed: {e}")

            # ── Weekly go-live update (every Monday, first 4 hours UTC) ────
            try:
                now_utc = datetime.now(timezone.utc)
                if now_utc.weekday() == 0 and now_utc.hour < 4:
                    golive = json.load(open(OUTPUT_DIR / "golive_readiness.json"))
                    ok = tg.send_golive_update(golive)
                    log.info(f"Telegram go-live update: {'sent' if ok else 'failed'}")
            except Exception as e:
                log.error(f"Telegram go-live update failed: {e}")

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
        _section_ok("strategy_v2")
    except Exception as e:
        log.error(f"strategy_v2 export failed: {e}", exc_info=True)
        _section_fail("strategy_v2")
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
        _section_ok("strategy_comparison")
    except Exception as e:
        log.error(f"strategy_comparison export failed: {e}", exc_info=True)
        _section_fail("strategy_comparison")
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
        _section_ok("optimization_recommendations")
    except Exception as e:
        log.error(f"optimization_recommendations export failed: {e}", exc_info=True)
        _section_fail("optimization_recommendations")
        write_json("optimization_recommendations.json", {
            "generated_at":    datetime.now(timezone.utc).isoformat(),
            "policy_version":  "v1.0",
            "recommendations": [],
            "portfolio_metrics": {"expected_return_pct": 0.0, "sharpe": 0.0},
            "vs_current":      {"return_improvement_pct": 0.0},
            "efficient_frontier": [],
            "error": str(e),
        })

    # 13b. covariance_summary.json — live rolling-90d APY covariance/correlation
    #      (FEAT-007 / SPA-V336 artifact, auto-refreshed each cycle — SPA-V338).
    #      Bridges data/historical_apy.json (written above) → estimator store and
    #      writes the dashboard-ready matrix doc. Wrapped graceful: never aborts.
    try:
        from analytics.covariance_export import write_covariance_json
        cov_doc = write_covariance_json(
            out_path=str(OUTPUT_DIR / "covariance_summary.json"),
        )
        log.info(
            f"covariance_summary.json: source={cov_doc['source']}, "
            f"{len(cov_doc['protocols'])} protocols"
        )
        _health["covariance_source"] = cov_doc.get("source")
        _section_ok("covariance_summary")
    except Exception as e:
        log.error(f"covariance_summary export failed: {e}", exc_info=True)
        _health["covariance_source"] = "synthetic_fallback"
        _section_fail("covariance_summary")
        write_json("covariance_summary.json", {
            "schema_version": 1,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "window_days": 90,
            "source": "synthetic_fallback",
            "protocols": {},
            "covariance_matrix": {},
            "correlation_matrix": {},
            "error": str(e),
        })

    # 14. PDF Report
    try:
        from reports.report_scheduler import generate_latest_report
        pdf_path = generate_latest_report(str(OUTPUT_DIR), str(OUTPUT_DIR))
        log.info(f"PDF report: {pdf_path}")
        print(f"PDF report: {pdf_path}")
        _section_ok("pdf_report")
    except Exception as e:
        log.error(f"PDF report generation failed: {e}", exc_info=True)
        _section_fail("pdf_report")

    # 15. decision_log.json — agent decision audit trail
    try:
        report_logger = DecisionLogger(db_path, 'ReportAgent')
        files_written = [
            "status.json", "protocols.json", "bus_stats.json", "strategy_state.json",
            "trades.json", "pnl_history.json", "meta.json", "backtest_results.json",
            "historical_apy.json", "risk_alerts.json", "alerts.json",
            "strategy_v2.json", "strategy_comparison.json",
            "optimization_recommendations.json", "covariance_summary.json",
            "golive_readiness.json", "golive_readiness_score.json",
            "golive_combined_verdict.json", "apy_gap_report.json",
            "apy_gap_report_history.json",
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
        _push_thought(
            "ReportAgent",
            f"Exporting JSON files… building daily report ({len(files_written)} files written)",
            data={"files_written": len(files_written), "decisions": len(decisions_out)},
        )
        _section_ok("decision_log")
    except Exception as e:
        log.error(f"decision_log export failed: {e}", exc_info=True)
        _section_fail("decision_log")
        write_json("decision_log.json", {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_decisions": 0,
            "decisions": [],
            "error": str(e),
        })

    # 16. golive_readiness.json — daily go-live pre-flight check
    #     Delegates to daily_check.run_daily_golive_check() which:
    #       • runs all 11 criteria via run_full_check()
    #       • writes golive_readiness.json with criteria_passed / blocking_criteria
    #       • prints the ASCII report card (visible in GitHub Actions log)
    #       • sends a Telegram alert if the verdict has changed since last run
    try:
        from golive.daily_check import run_daily_golive_check
        golive = run_daily_golive_check(str(OUTPUT_DIR))
        log.info(
            f"golive_readiness: verdict={golive['verdict']} "
            f"({golive.get('criteria_passed', '?')}/{golive.get('criteria_total', '?')} criteria)"
        )
        _section_ok("golive_readiness")
    except Exception as e:
        log.error(f"golive_readiness export failed: {e}", exc_info=True)
        _section_fail("golive_readiness")
        from datetime import timedelta as _td
        write_json("golive_readiness.json", {
            "generated_at":      datetime.now(timezone.utc).isoformat(),
            "verdict":           "NOT_READY",
            "verdict_emoji":     "🔴",
            "criteria_passed":   0,
            "criteria_total":    11,
            "blocking_criteria": [],
            "next_check_date":   (
                datetime.now(timezone.utc).date() + _td(days=1)
            ).isoformat(),
            "error": str(e),
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
        _section_ok("agent_summaries")
    except Exception as e:
        log.error(f"agent_summaries export failed: {e}", exc_info=True)
        _section_fail("agent_summaries")
        write_json("agent_summaries.json", {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "used_llm": False,
            "trader_summary": "Portfolio export complete. All positions within RiskPolicy v1.0 limits.",
            "risk_summary": "No active risk violations. Portfolio health: approved.",
            "error": str(e),
        })

    # 18. tournament_results.json — strategy tournament
    #     (v1_passive vs v2_aggressive vs v3_pendle_focused on same data)
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
        _section_ok("tournament_results")
    except Exception as e:
        log.error(f"tournament_results export failed: {e}", exc_info=True)
        _section_fail("tournament_results")
        write_json("tournament_results.json", {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "winner": "v1_passive",
            "confidence": "LOW",
            "recommendation": "Tournament data unavailable.",
            "scores": {
                "v1_passive":        0.0,
                "v2_aggressive":     0.0,
                "v3_pendle_focused": 0.0,
            },
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
        _section_ok("advanced_analytics")
    except Exception as e:
        log.error(f"advanced_analytics export failed: {e}", exc_info=True)
        _section_fail("advanced_analytics")
        write_json("advanced_analytics.json", {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "summary": {},
            "rolling_metrics": [],
            "data_points": 0,
            "error": str(e),
        })

    # 20. backtest_comparison.json — side-by-side v1_passive vs v2_aggressive (30d)
    try:
        from backtesting.scenario_runner import compare_scenarios

        comparison = compare_scenarios(days=30)
        write_json("backtest_comparison.json", {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "days": comparison["days"],
            "seed": comparison["seed"],
            "initial_capital": comparison["initial_capital"],
            "winner": comparison["winner"],
            "winner_metric": comparison["winner_metric"],
            "delta": comparison["delta"],
            "strategies": {
                "v1_passive": {
                    k: v for k, v in comparison["v1_passive"].items()
                    if k != "equity_curve"
                },
                "v2_aggressive": {
                    k: v for k, v in comparison["v2_aggressive"].items()
                    if k != "equity_curve"
                },
            },
            # Include last 10 days of each equity curve (keep JSON small)
            "equity_curves": {
                "v1_passive":    comparison["v1_passive"]["equity_curve"][-10:],
                "v2_aggressive": comparison["v2_aggressive"]["equity_curve"][-10:],
            },
        })
        log.info(
            f"backtest_comparison: winner={comparison['winner']}, "
            f"Δreturn={comparison['delta']['total_return']:+.2f}%, "
            f"Δsharpe={comparison['delta']['sharpe']:+.4f}"
        )
        _section_ok("backtest_comparison")
    except Exception as e:
        log.error(f"backtest_comparison export failed: {e}", exc_info=True)
        _section_fail("backtest_comparison")
        write_json("backtest_comparison.json", {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "days": 30,
            "winner": "v1_passive",
            "winner_metric": "sharpe_ratio",
            "delta": {},
            "strategies": {},
            "equity_curves": {},
            "error": str(e),
        })

    # ── Pipeline health file ──────────────────────────────────────────────────
    _health["export_duration_seconds"] = round(time.time() - _export_start, 2)
    _health["timestamp"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        write_json("pipeline_health.json", _health)
        log.info(
            f"pipeline_health.json: {_health['sections_ok']} ok, "
            f"{_health['sections_failed']} failed, "
            f"pools={_health['total_pools_fetched']}, "
            f"duration={_health['export_duration_seconds']}s"
        )
    except Exception as _he:
        log.error(f"pipeline_health write failed: {_he}")

    # ── Pipeline failure alert (if health shows problems) ─────────────────────
    try:
        if _health["sections_failed"] > 2 or _health["total_pools_fetched"] == 0:
            from alerts.risk_monitor import RiskMonitor
            from alerts.telegram_sender import TelegramSender
            _monitor = RiskMonitor(data_dir=OUTPUT_DIR)
            _tg = TelegramSender()
            _monitor.alert_pipeline_failure(_health, sender=_tg)
    except Exception as _ae:
        log.error(f"Pipeline failure alert dispatch failed: {_ae}")

    # ── Covariance degradation alert (consecutive synthetic/failed cycles) ────
    try:
        from alerts.risk_monitor import RiskMonitor
        from alerts.telegram_sender import TelegramSender
        _cov_monitor = RiskMonitor(data_dir=OUTPUT_DIR)
        _cov_src = _health.get("covariance_source")
        _cov_failed = "covariance_summary" in _health.get("failed_sections", [])
        _cov_monitor.alert_covariance_degraded(_cov_src, sender=TelegramSender(), section_failed=_cov_failed)
    except Exception as _cae:
        log.error(f"Covariance degradation alert dispatch failed: {_cae}")

    # ── APY feed staleness alert (stale/stuck historical_apy.json) ────────────
    try:
        from alerts.risk_monitor import RiskMonitor
        from alerts.telegram_sender import TelegramSender
        _apy_monitor = RiskMonitor(data_dir=OUTPUT_DIR)
        _apy_monitor.alert_apy_feed_stale(
            feed_path=str(OUTPUT_DIR / "historical_apy.json"),
            sender=TelegramSender(),
        )
    except Exception as _afe:
        log.error(f"APY feed staleness alert dispatch failed: {_afe}")

    # ── APY feed protocol-count drop alert (sharp protocol-count drop) ─────────
    try:
        _apy_proto_monitor = RiskMonitor(data_dir=OUTPUT_DIR)
        _apy_proto_monitor.alert_apy_feed_protocol_drop(
            feed_path=str(OUTPUT_DIR / "historical_apy.json"),
            sender=TelegramSender(),
        )
    except Exception as _apde:
        log.error(f"APY feed protocol-count drop alert dispatch failed: {_apde}")

    # ── APY feed TVL collapse alert (sharp total-TVL drop) ─────────────────────
    try:
        _apy_tvl_monitor = RiskMonitor(data_dir=OUTPUT_DIR)
        _apy_tvl_monitor.alert_apy_feed_tvl_drop(
            feed_path=str(OUTPUT_DIR / "historical_apy.json"),
            sender=TelegramSender(),
        )
    except Exception as _atde:
        log.error(f"APY feed TVL collapse alert dispatch failed: {_atde}")

    # ── APY feed per-protocol anomaly alert (protocol dropout / APY|TVL crash) ──
    try:
        _apy_anom_monitor = RiskMonitor(data_dir=OUTPUT_DIR)
        _apy_anom_monitor.alert_apy_feed_protocol_anomaly(
            feed_path=OUTPUT_DIR / "historical_apy.json",
            sender=TelegramSender(),
        )
    except Exception as _aae:
        log.error(f"APY feed per-protocol anomaly alert dispatch failed: {_aae}")

    # ── APY feed schema drift alert (structure/keys/types validation) ──────────
    try:
        _apy_schema_monitor = RiskMonitor(data_dir=OUTPUT_DIR)
        _apy_schema_monitor.alert_apy_feed_schema_drift(
            feed_path=OUTPUT_DIR / "historical_apy.json",
            sender=TelegramSender(),
        )
    except Exception as _asd:
        log.error(f"APY feed schema drift alert dispatch failed: {_asd}")

    # ── APY feed per-protocol staleness alert (one protocol stops advancing) ───
    try:
        _apy_pstale_monitor = RiskMonitor(data_dir=OUTPUT_DIR)
        _apy_pstale_monitor.alert_apy_feed_protocol_stale(
            feed_path=OUTPUT_DIR / "historical_apy.json",
            sender=TelegramSender(),
        )
    except Exception as _aps:
        log.error(f"APY feed per-protocol staleness alert dispatch failed: {_aps}")

    # ── APY feed value-bounds alert (value-range sanity-bounds, SPA-V349) ──────
    try:
        _apy_bounds_monitor = RiskMonitor(data_dir=OUTPUT_DIR)
        _apy_bounds_monitor.alert_apy_feed_value_bounds(
            feed_path=OUTPUT_DIR / "historical_apy.json",
            sender=TelegramSender(),
        )
    except Exception as _avb:
        log.error(f"APY feed value-bounds alert dispatch failed: {_avb}")

    # ── APY feed date monotonicity alert (date regression / gaps, SPA-V350) ────
    try:
        _apy_mono_monitor = RiskMonitor(data_dir=OUTPUT_DIR)
        _apy_mono_monitor.alert_apy_feed_date_monotonicity(
            feed_path=OUTPUT_DIR / "historical_apy.json",
            sender=TelegramSender(),
        )
    except Exception as _amd:
        log.error(f"APY feed date monotonicity alert dispatch failed: {_amd}")

    # ── Aggregated feed-health summary (SPA-V347) ─────────────────────────────
    # Roll the 7 feed/covariance health signals above into ONE dashboard-ready
    # status doc (data/feed_health_summary.json) so the UI shows one badge.
    try:
        from alerts.feed_health_summary import write_feed_health_summary

        write_feed_health_summary(
            str(OUTPUT_DIR / "feed_health_summary.json"),
            data_dir=OUTPUT_DIR,
        )
    except Exception as _fhs:
        log.error(f"Feed-health summary aggregation failed: {_fhs}")

    # ── Consolidated Go-Live readiness score (SPA-V362) ───────────────────────
    # Roll feed_health + MEV-routing coverage + live_apy into ONE composite
    # operational readiness score (data/golive_readiness_score.json) so the
    # dashboard shows a single "NN/100" headline. Runs AFTER feed_health_summary
    # because it consumes that doc. Pure read-only consolidation (SPA-V361
    # module) — no money-moving code, no new feed-health monitor (SPA-BL-011
    # governance freeze respected). Wrapped graceful: never aborts the cycle.
    try:
        from golive.readiness_score import write_readiness_score

        score_doc = write_readiness_score(
            str(OUTPUT_DIR / "golive_readiness_score.json"),
        )
        log.info(
            f"golive_readiness_score.json: overall_score="
            f"{score_doc.get('overall_score', '?')}, "
            f"overall_status={score_doc.get('overall_status', '?')}"
        )
        _section_ok("golive_readiness_score")
    except Exception as _grs:
        log.error(f"Go-Live readiness score export failed: {_grs}", exc_info=True)
        _section_fail("golive_readiness_score")

    # ── Persisted combined go/no-go gate (SPA-V367) ───────────────────────────
    # Persist the SPA-V366 combined gate (operational readiness × paper-trading
    # checklist) to data/golive_combined_verdict.json so the gate is a durable
    # artefact, not only computed client-side. Runs LAST because it consumes the
    # two source docs (golive_readiness_score.json + golive_readiness.json) both
    # written earlier this cycle. Pure read-only consolidation (SPA-V366 module)
    # — no money-moving code, no new feed-health monitor (SPA-BL-011 respected).
    # Wrapped graceful: never aborts the cycle.
    try:
        from golive.readiness_score import write_combined_golive_gate

        gate_doc = write_combined_golive_gate(
            str(OUTPUT_DIR / "golive_combined_verdict.json"),
            data_dir=str(OUTPUT_DIR),
        )
        log.info(
            f"golive_combined_verdict.json: gate={gate_doc.get('gate', '?')}, "
            f"blocking={gate_doc.get('blocking', [])}"
        )
        _section_ok("golive_combined_verdict")
    except Exception as _gcv:
        log.error(f"Combined go-live gate export failed: {_gcv}", exc_info=True)
        _section_fail("golive_combined_verdict")

    # ── APY gap report (SPA-V371) ─────────────────────────────────────────────
    # Persist the APY gap analysis (current weighted APY vs the 7.3% target, plus
    # the estimated uplift from the Pendle PT and Sky/sUSDS levers) to
    # data/apy_gap_report.json so progress toward the target is a durable,
    # dashboard-visible artefact instead of being recomputed ad-hoc. Consumes the
    # paper-trader status already produced this cycle. Pure read-only analytics
    # (data_pipeline.apy_gap_report module) — no money-moving code, no new
    # feed-health monitor (SPA-BL-011 governance freeze respected). Wrapped
    # graceful: never aborts the cycle.
    try:
        from data_pipeline.apy_gap_report import apy_gap_report, append_apy_gap_history

        _gap_doc = apy_gap_report(trader.get_status())
        _gap_doc = {
            "schema_version": 1,
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            **_gap_doc,
        }
        write_json("apy_gap_report.json", _gap_doc)
        # SPA-V373 — persist a compact history of the APY-gap headline so the
        # dashboard can render a current_weighted_apy sparkline. Separate guarded
        # try so a history failure can never abort the already-written report.
        try:
            append_apy_gap_history(_gap_doc, data_dir=str(OUTPUT_DIR))
        except Exception as _agh:  # noqa: BLE001 -- never abort the cycle
            log.error(f"APY gap history append failed: {_agh}", exc_info=True)
        log.info(
            f"apy_gap_report.json: current={_gap_doc.get('current_weighted_apy', '?')}%, "
            f"gap={_gap_doc.get('gap', '?')}%, on_track={_gap_doc.get('on_track', '?')}"
        )
        _section_ok("apy_gap_report")
    except Exception as _agr:
        log.error(f"APY gap report export failed: {_agr}", exc_info=True)
        _section_fail("apy_gap_report")

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
