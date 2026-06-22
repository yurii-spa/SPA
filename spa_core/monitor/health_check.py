"""
SPA Portfolio Health Check — M3
Terminal dashboard + alert сохранение в risk_events.

Использование:
    python health_check.py              # текстовый dashboard
    python health_check.py --json       # JSON вывод
    python health_check.py --loop 300   # обновлять каждые 5 минут
    python health_check.py --alerts-only  # только активные alerts
"""

from __future__ import annotations

import json
import logging
import sys
import time
import argparse
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from database.init_db import get_connection, get_db_path
from paper_trading.engine import PaperTrader
from monitor.alerts import AlertEngine, Alert

log = logging.getLogger(__name__)

SEVERITY_ICON = {
    "INFO":     "ℹ️ ",
    "WARNING":  "⚠️ ",
    "CRITICAL": "🚨",
}

SEVERITY_ORDER = {"INFO": 0, "WARNING": 1, "CRITICAL": 2}


# ─── Health Check ─────────────────────────────────────────────────────────────

class HealthCheck:
    """Полная проверка здоровья портфеля и данных."""

    def __init__(self, db_path: Path = None):
        self.db_path = db_path or get_db_path()
        self.trader  = PaperTrader(db_path=self.db_path)
        self.alert_engine = AlertEngine()

    def run(self) -> dict:
        """Выполнить полную проверку. Вернуть структурированный результат."""
        ts = datetime.now(timezone.utc).isoformat()

        # 1. Данные из БД
        current_snapshots = self._get_latest_snapshots()
        previous_snapshots = self._get_previous_snapshots()

        # 2. Состояние портфеля
        portfolio_status = self.trader.get_status()

        # 3. Market alerts (данные DeFiLlama)
        market_alerts = self.alert_engine.check_snapshots(current_snapshots, previous_snapshots)
        pipeline_alerts = self.alert_engine.check_pipeline_health(current_snapshots)
        all_alerts = pipeline_alerts + market_alerts

        # 4. Risk Policy alerts уже в portfolio_status["risk"]
        risk = portfolio_status["risk"]
        for v in risk["violations"]:
            all_alerts.append(Alert(
                severity="CRITICAL",
                event_type="RISK_POLICY_VIOLATION",
                protocol_key=None,
                message=v,
            ))
        for w in risk["warnings"]:
            all_alerts.append(Alert(
                severity="WARNING",
                event_type="RISK_POLICY_WARNING",
                protocol_key=None,
                message=w,
            ))

        # 5. Сохранить CRITICAL alerts в risk_events
        critical_count = self._save_critical_alerts(all_alerts)

        # 6. Финальный результат
        all_alerts_sorted = sorted(all_alerts, key=lambda a: -SEVERITY_ORDER[a.severity])

        return {
            "timestamp": ts,
            "portfolio": portfolio_status,
            "market_data": {
                "protocols": len(current_snapshots),
                "snapshots": [
                    {
                        "protocol_key": s["protocol_key"],
                        "apy_total": s["apy_total"],
                        "apy_base": s.get("apy_base"),
                        "tvl_usd": s["tvl_usd"],
                        "tier": s.get("tier"),
                        "timestamp": s["timestamp"],
                    }
                    for s in current_snapshots
                ],
            },
            "alerts": [
                {
                    "severity": a.severity,
                    "event_type": a.event_type,
                    "protocol_key": a.protocol_key,
                    "message": a.message,
                    "details": a.details,
                    "timestamp": a.timestamp,
                }
                for a in all_alerts_sorted
            ],
            "summary": {
                "total_alerts": len(all_alerts),
                "critical": sum(1 for a in all_alerts if a.severity == "CRITICAL"),
                "warnings":  sum(1 for a in all_alerts if a.severity == "WARNING"),
                "info":      sum(1 for a in all_alerts if a.severity == "INFO"),
                "new_risk_events_saved": critical_count,
                "overall_status": (
                    "CRITICAL" if any(a.severity == "CRITICAL" for a in all_alerts)
                    else "WARNING" if any(a.severity == "WARNING" for a in all_alerts)
                    else "OK"
                ),
            },
        }

    def print_dashboard(self, result: dict | None = None) -> None:
        """Вывести dashboard в консоль."""
        r = result or self.run()
        p = r["portfolio"]["portfolio"]
        pt = r["portfolio"]["paper_trading"]
        mkt = r["market_data"]
        summary = r["summary"]

        status_icon = {"OK": "✅", "WARNING": "⚠️ ", "CRITICAL": "🚨"}.get(summary["overall_status"], "❓")
        print(f"\n{'═'*65}")
        print(f"  {status_icon} SPA Health Check — {r['timestamp'][:19]} UTC")
        print(f"  Overall: {summary['overall_status']}  |  "
              f"🚨 {summary['critical']}  ⚠️  {summary['warnings']}  ℹ️  {summary['info']}")
        print(f"{'═'*65}")

        # ── Portfolio ──────────────────────────────────────────────────────────
        pnl_sign = "+" if p["total_pnl_usd"] >= 0 else ""
        print("\n  💰 PORTFOLIO")
        print(f"     Capital:   ${p['total_capital_usd']:>10,.2f}")
        print(f"     Deployed:  ${p['deployed_usd']:>10,.2f}   ({1-p['cash_pct']:.0%})")
        print(f"     Cash:      ${p['cash_usd']:>10,.2f}   ({p['cash_pct']:.0%})")
        print(f"     PnL:       {pnl_sign}${p['total_pnl_usd']:>9.2f}")
        print(f"     Drawdown:  {p['total_drawdown_pct']:.2%}")

        # VaR
        risk = r["portfolio"]["risk"]
        var_icon = "🔴" if risk["var_breach"] else "🟢"
        print(f"     VaR 95%/7d: {var_icon} ${risk['var_usd']:.2f}  ({risk['var_pct']:.3f}%)")

        # ── Positions ──────────────────────────────────────────────────────────
        positions = r["portfolio"]["positions"]
        if positions:
            print("\n  📊 POSITIONS")
            print(f"     {'Protocol':<35} {'Tier':<4} {'$Amount':>9} {'APY':>6} {'PnL':>9} {'Days':>5}")
            print(f"     {'─'*72}")
            for pos in positions:
                sign = "+" if pos["unrealized_pnl_usd"] >= 0 else ""
                print(f"     {pos['protocol_key']:<35} {pos['tier']:<4} "
                      f"${pos['amount_usd']:>8,.0f} {pos['current_apy']:>5.2f}% "
                      f"{sign}${pos['unrealized_pnl_usd']:>7.2f} {pos['days_held']:>5.1f}d")
        else:
            print("\n  📊 POSITIONS: none")

        # ── Market Data ────────────────────────────────────────────────────────
        if mkt["snapshots"]:
            print(f"\n  📈 MARKET DATA  ({mkt['protocols']} protocols)")
            print(f"     {'Protocol':<35} {'Tier':<4} {'APY%':>7} {'TVL':>12}")
            print(f"     {'─'*62}")
            for s in sorted(mkt["snapshots"], key=lambda x: -(x.get("apy_total") or 0)):
                tvl = s["tvl_usd"] or 0
                tvl_str = f"${tvl/1e9:.2f}B" if tvl >= 1e9 else f"${tvl/1e6:.0f}M"
                tier = s.get("tier", "??")
                print(f"     {s['protocol_key']:<35} {tier:<4} {(s['apy_total'] or 0):>7.2f} {tvl_str:>12}")

        # ── Alerts ─────────────────────────────────────────────────────────────
        alerts = r["alerts"]
        if alerts:
            print(f"\n  🔔 ALERTS ({len(alerts)})")
            for a in alerts:
                icon = SEVERITY_ICON.get(a["severity"], "  ")
                proto = f"[{a['protocol_key']}] " if a["protocol_key"] else ""
                print(f"     {icon} {proto}{a['message']}")
        else:
            print("\n  🔔 ALERTS: none — all clear")

        # ── Paper Trading Clock ────────────────────────────────────────────────
        clock_icon = "✅" if pt["go_live_ready"] else "⏳"
        print(f"\n  {clock_icon} PAPER TRADING CLOCK")
        print(f"     Week {pt['weeks_elapsed']:.1f} / {pt['min_weeks_required']} required")
        if pt["go_live_ready"]:
            print("     ✅ Eligible for Go-Live (requires ADR + Owner approval)")
        else:
            weeks_left = pt["min_weeks_required"] - pt["weeks_elapsed"]
            print(f"     ⏳ {weeks_left:.1f} weeks remaining")

        print(f"\n{'═'*65}\n")

    # ── Private helpers ───────────────────────────────────────────────────────

    def _get_latest_snapshots(self) -> list[dict]:
        """Последний снапшот для каждого протокола."""
        with get_connection(self.db_path) as conn:
            rows = conn.execute("""
                SELECT s.*, p.tier
                FROM apy_snapshots s
                JOIN protocols p ON s.protocol_key = p.key
                WHERE s.id IN (
                    SELECT MAX(id) FROM apy_snapshots
                    GROUP BY protocol_key
                )
                ORDER BY s.apy_total DESC
            """).fetchall()
        return [dict(r) for r in rows]

    def _get_previous_snapshots(self) -> list[dict]:
        """Предпоследний снапшот для каждого протокола (для сравнения)."""
        with get_connection(self.db_path) as conn:
            rows = conn.execute("""
                SELECT s.*
                FROM apy_snapshots s
                WHERE s.id IN (
                    SELECT id FROM (
                        SELECT id, protocol_key,
                               ROW_NUMBER() OVER (
                                   PARTITION BY protocol_key ORDER BY id DESC
                               ) AS rn
                        FROM apy_snapshots
                    ) ranked WHERE rn = 2
                )
            """).fetchall()
        return [dict(r) for r in rows]

    def _save_critical_alerts(self, alerts: list[Alert]) -> int:
        """Сохранить CRITICAL и WARNING alerts в risk_events."""
        count = 0
        with get_connection(self.db_path) as conn:
            for a in alerts:
                if a.severity in ("CRITICAL", "WARNING"):
                    conn.execute("""
                        INSERT INTO risk_events
                            (timestamp, event_type, severity, protocol_key,
                             message, details_json, resolved)
                        VALUES (?, ?, ?, ?, ?, ?, 0)
                    """, (
                        a.timestamp, a.event_type, a.severity,
                        a.protocol_key, a.message,
                        json.dumps(a.details) if a.details else None,
                    ))
                    count += 1
            conn.commit()
        return count


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main():
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    parser = argparse.ArgumentParser(description="SPA Health Check CLI")
    parser.add_argument("--json",        action="store_true", help="JSON output")
    parser.add_argument("--alerts-only", action="store_true", help="Show only active alerts")
    parser.add_argument("--loop",        type=int, metavar="SECONDS",
                        help="Repeat every N seconds")
    args = parser.parse_args()

    checker = HealthCheck()

    def once():
        result = checker.run()
        if args.json:
            print(json.dumps(result, indent=2, default=str))
        elif args.alerts_only:
            alerts = result["alerts"]
            if not alerts:
                print("✅ No alerts")
            else:
                for a in alerts:
                    icon = SEVERITY_ICON.get(a["severity"], "  ")
                    proto = f"[{a['protocol_key']}] " if a["protocol_key"] else ""
                    print(f"{icon} {proto}{a['message']}")
        else:
            checker.print_dashboard(result)

    if args.loop:
        while True:
            once()
            time.sleep(args.loop)
    else:
        once()


if __name__ == "__main__":
    main()
