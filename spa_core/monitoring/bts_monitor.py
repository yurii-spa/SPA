"""
bts_monitor.py — BTS Monitor (Basis Trade System).

Runs every 15 min via LaunchAgent com.spa.bts-monitor.
Reads perp_funding_rates.json + adapter_status.json.
Feeds BasisTradeAnalyzer to produce ranked opportunities.
Writes data/basis_trade_opportunities.json.
Fires Telegram alert on NEW EXCELLENT opportunity (transition from non-EXCELLENT).

Atomic writes: tmp-file + os.replace. stdlib only.
Never raises exceptions outward (fail-safe).
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set

from spa_core.analytics.basis_trade_analyzer import (
    BasisTradeAnalyzer,
    BasisTradeInput,
    BasisTradeResult,
)
from spa_core.utils.atomic import atomic_save, atomic_load

log = logging.getLogger("spa.monitoring.bts_monitor")

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _PROJECT_ROOT / "data"

OPP_FILENAME = "basis_trade_opportunities.json"
STATUS_FILENAME = "bts_monitor_status.json"
FUNDING_FILENAME = "perp_funding_rates.json"
ADAPTER_STATUS_FILENAME = "adapter_status.json"

TRACKED_ASSETS = ("ETH", "BTC", "SOL")
DEFAULT_SPOT_YIELD = 0.05
DEFAULT_EXEC_COST_BPS = 20.0
DEFAULT_CAPITAL_USD = 20000.0
TOP_N = 5

STALE_AFTER_S = 1800
ALERT_COOLDOWN_S = 3600


@dataclass
class BTSOpportunity:
    asset: str
    spot_yield_pct: float
    perp_funding_pct: float
    net_spread_bps: float
    edge_quality: str
    recommended_action: str
    annual_pnl_usd: float
    gross_spread_bps: float = 0.0
    capital_usd: float = DEFAULT_CAPITAL_USD

    def to_dict(self) -> dict:
        return {
            "asset": self.asset,
            "spot_yield_pct": round(self.spot_yield_pct, 2),
            "perp_funding_pct": round(self.perp_funding_pct, 2),
            "net_spread_bps": round(self.net_spread_bps, 1),
            "gross_spread_bps": round(self.gross_spread_bps, 1),
            "edge_quality": self.edge_quality,
            "recommended_action": self.recommended_action,
            "annual_pnl_usd": round(self.annual_pnl_usd, 2),
            "capital_usd": round(self.capital_usd, 2),
        }


class BTSMonitor:
    """
    BTS opportunity scanner.

    Reads funding rates + adapter status, runs BasisTradeAnalyzer,
    writes ranked opportunities, fires Telegram on NEW EXCELLENT transitions.
    """

    def __init__(
        self,
        data_dir: Optional[Path] = None,
        use_alert_dispatcher: bool = True,
        analyzer: Optional[BasisTradeAnalyzer] = None,
    ) -> None:
        self._data_dir = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR
        self._opp_path = self._data_dir / OPP_FILENAME
        self._status_path = self._data_dir / STATUS_FILENAME
        self._funding_path = self._data_dir / FUNDING_FILENAME
        self._adapter_status_path = self._data_dir / ADAPTER_STATUS_FILENAME
        self._use_alert_dispatcher = use_alert_dispatcher
        self._analyzer = analyzer or BasisTradeAnalyzer()
        self._dispatcher = None

    def _get_dispatcher(self):
        if not self._use_alert_dispatcher:
            return None
        if self._dispatcher is not None:
            return self._dispatcher
        try:
            from spa_core.alerts.alert_dispatcher import AlertDispatcher
            self._dispatcher = AlertDispatcher(
                suppress_duplicates=True,
                cooldown_seconds=ALERT_COOLDOWN_S,
            )
        except Exception as exc:
            log.debug("AlertDispatcher unavailable: %s", exc)
            self._dispatcher = None
        return self._dispatcher

    def _load_funding_data(self) -> Optional[dict]:
        try:
            data = atomic_load(str(self._funding_path), default=None)
            if not data:
                return None
            gen_at = data.get("generated_at", "")
            if isinstance(gen_at, str) and gen_at:
                try:
                    dt = datetime.fromisoformat(gen_at.replace("Z", "+00:00"))
                    age_s = (datetime.now(timezone.utc) - dt).total_seconds()
                    if age_s > STALE_AFTER_S:
                        log.info("Funding data stale (age %.0fs > %ds)", age_s, STALE_AFTER_S)
                        return None
                except (ValueError, TypeError):
                    pass
            if data.get("stale", False):
                log.info("Funding data marked stale by feed")
                return None
            return data
        except Exception as exc:
            log.warning("Failed to load funding data: %s", exc)
            return None

    def _load_adapter_status(self) -> dict:
        try:
            return atomic_load(str(self._adapter_status_path), default={})
        except Exception:
            return {}

    def _get_spot_yield(self, adapter_status: dict) -> float:
        best_yield = DEFAULT_SPOT_YIELD
        yield_keys = {
            "aave_v3": "apy",
            "aave_usdc": "apy",
            "compound_v3": "apy",
            "morpho_steakhouse": "apy",
            "morpho_usdc": "apy",
        }
        for key, apy_field in yield_keys.items():
            entry = adapter_status.get(key, {})
            if isinstance(entry, dict):
                apy = entry.get(apy_field)
                if apy is not None:
                    try:
                        apy_val = float(apy)
                        if apy_val > 1.0:
                            apy_val = apy_val / 100.0
                        if apy_val > best_yield:
                            best_yield = apy_val
                    except (ValueError, TypeError):
                        continue
        return best_yield

    def scan(self) -> List[BTSOpportunity]:
        funding_data = self._load_funding_data()
        if funding_data is None:
            log.info("No valid funding data — returning empty opportunities")
            return []

        adapter_status = self._load_adapter_status()
        spot_yield = self._get_spot_yield(adapter_status)

        rates = funding_data.get("rates", {})
        if not rates:
            log.info("No rates in funding data")
            return []

        inputs = []
        for asset in TRACKED_ASSETS:
            rate_info = rates.get(asset)
            if not rate_info:
                continue
            funding_annual = rate_info.get("funding_rate_annual")
            if funding_annual is None:
                continue
            try:
                funding_annual = float(funding_annual)
            except (ValueError, TypeError):
                continue
            inputs.append(BasisTradeInput(
                asset=asset,
                spot_yield_annual=spot_yield,
                perp_funding_annual=funding_annual,
                execution_cost_bps=DEFAULT_EXEC_COST_BPS,
                capital_usd=DEFAULT_CAPITAL_USD,
            ))

        if not inputs:
            log.info("No valid inputs built from funding data")
            return []

        results = self._analyzer.analyze_batch(inputs)
        top = self._analyzer.top_opportunities(results, n=TOP_N)

        opportunities = []
        for r in top:
            opportunities.append(BTSOpportunity(
                asset=r.asset,
                spot_yield_pct=round(r.spot_yield_annual * 100, 2),
                perp_funding_pct=round(r.perp_funding_annual * 100, 2),
                net_spread_bps=r.net_spread_bps,
                gross_spread_bps=r.gross_spread_bps,
                edge_quality=r.edge_quality,
                recommended_action=r.recommended_action,
                annual_pnl_usd=r.annual_pnl_usd,
                capital_usd=r.capital_usd,
            ))

        return opportunities

    def _load_previous_excellent(self) -> Set[str]:
        try:
            data = atomic_load(str(self._opp_path), default={})
            if not isinstance(data, dict):
                return set()
            opps = data.get("opportunities", [])
            return {
                o["asset"]
                for o in opps
                if isinstance(o, dict) and o.get("edge_quality") == "EXCELLENT"
            }
        except Exception:
            return set()

    def _detect_new_excellent(
        self, current: List[BTSOpportunity],
    ) -> List[BTSOpportunity]:
        prev_excellent = self._load_previous_excellent()
        new_excellent = []
        for opp in current:
            if opp.edge_quality == "EXCELLENT" and opp.asset not in prev_excellent:
                new_excellent.append(opp)
        return new_excellent

    def _create_alerts(self, new_excellent: List[BTSOpportunity]) -> int:
        if not new_excellent:
            return 0

        dispatcher = self._get_dispatcher()
        sent = 0
        for opp in new_excellent:
            title = f"BTS EXCELLENT: {opp.asset}"
            msg = (
                f"New EXCELLENT basis trade opportunity\n"
                f"Asset: {opp.asset}\n"
                f"Net spread: {opp.net_spread_bps:.0f} bps\n"
                f"Perp funding: {opp.perp_funding_pct:.1f}%\n"
                f"Spot yield: {opp.spot_yield_pct:.1f}%\n"
                f"Annual PnL: ${opp.annual_pnl_usd:,.0f}"
            )
            if dispatcher:
                try:
                    from spa_core.alerts.alert_dispatcher import AlertLevel
                    alert = dispatcher.create_alert(
                        level=AlertLevel.WARNING,
                        title=title,
                        message=msg,
                    )
                    dispatcher.dispatch(alert)
                    sent += 1
                except Exception as exc:
                    log.warning("Alert dispatch failed for %s: %s", opp.asset, exc)
            else:
                log.info("ALERT (log-only): %s — %s", title, msg)
                sent += 1
        return sent

    def _save_opportunities(
        self,
        opps: List[BTSOpportunity],
        stale: bool,
    ) -> None:
        now_iso = datetime.now(timezone.utc).isoformat()
        excellent_count = sum(1 for o in opps if o.edge_quality == "EXCELLENT")
        enter_count = sum(1 for o in opps if o.recommended_action == "ENTER")

        payload = {
            "timestamp": now_iso,
            "generated_at": time.time(),
            "stale_feed": stale,
            "opportunities": [o.to_dict() for o in opps],
            "summary": {
                "excellent_count": excellent_count,
                "enter_count": enter_count,
                "total_analyzed": len(opps),
            },
        }
        try:
            atomic_save(payload, str(self._opp_path))
        except Exception as exc:
            log.error("Failed to save opportunities: %s", exc)

    def _save_status(
        self,
        opps: List[BTSOpportunity],
        new_excellent_count: int,
        errors: List[str],
    ) -> None:
        now_iso = datetime.now(timezone.utc).isoformat()
        payload = {
            "last_run": now_iso,
            "opportunities_found": len(opps),
            "new_excellent": new_excellent_count,
            "status": "ok" if not errors else "error",
            "errors": errors,
        }
        try:
            atomic_save(payload, str(self._status_path))
        except Exception as exc:
            log.error("Failed to save status: %s", exc)

    def run(self) -> dict:
        errors: List[str] = []
        opps: List[BTSOpportunity] = []
        new_excellent_count = 0

        try:
            new_excellent = self._detect_new_excellent([])
            opps = self.scan()
            stale = len(opps) == 0

            if opps:
                new_excellent = self._detect_new_excellent(opps)
                new_excellent_count = len(new_excellent)
                if new_excellent:
                    self._create_alerts(new_excellent)

            self._save_opportunities(opps, stale)

        except Exception as exc:
            log.error("BTS monitor scan failed: %s", exc)
            errors.append(str(exc))
            self._save_opportunities([], True)

        self._save_status(opps, new_excellent_count, errors)

        report = {
            "opportunities": len(opps),
            "new_excellent": new_excellent_count,
            "errors": errors,
            "status": "ok" if not errors else "error",
        }
        log.info("BTS monitor run complete: %s", report)
        return report


if __name__ == "__main__":
    import argparse
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(description="BTS Monitor")
    parser.add_argument("--run", action="store_true", help="Run monitor scan")
    parser.add_argument("--check", action="store_true", help="Run scan (read-only, no write)")
    args = parser.parse_args()

    if args.run or args.check:
        monitor = BTSMonitor(use_alert_dispatcher=args.run)
        if args.check:
            opps = monitor.scan()
            for o in opps:
                print(json.dumps(o.to_dict(), indent=2))
        else:
            result = monitor.run()
            print(json.dumps(result, indent=2))
    else:
        parser.print_help()
        sys.exit(0)
