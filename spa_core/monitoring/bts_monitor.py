"""
bts_monitor.py — BTS Monitor (Basis Trade System).

Runs every 15 min via LaunchAgent com.spa.bts-monitor.
Reads perp_funding_rates.json + adapter_status.json.
Feeds BasisTradeAnalyzer to produce ranked opportunities.
Writes data/basis_trade_opportunities.json.
Fires Telegram alert on NEW EXCELLENT opportunity (transition from non-EXCELLENT).

Atomic writes: tmp-file + os.replace. stdlib only.
Never raises exceptions outward (fail-safe).

Honesty contract (cycle #78). The funding payload is read through
`spa_core.feeds.funding_schema`, which knows the shape the producer actually writes
(`assets` / `fetched_at`) and still accepts the legacy shape (`rates` / `generated_at`).
Before that, this monitor asked only for the legacy keys, found nothing 96 times a day,
and published `status: "ok", errors: [], 0 opportunities` — a verdict about a file it
had never read. Now `status` is "ok" ONLY when the scan actually happened; otherwise it
is "unchecked" and `unchecked[]` carries the verbatim reason. Thresholds
(STALE_AFTER_S, ALERT_COOLDOWN_S), the alert transport and the ranking are unchanged.
"""
from __future__ import annotations

import json
import logging
import os
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
from spa_core.feeds.funding_schema import feed_age_seconds, read_rates
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

# Verdict vocabulary. "ok" is reserved for a scan that actually happened: before #78 it
# was published whenever no exception was raised, including the 96 runs a day in which
# the monitor read nothing at all.
STATUS_OK = "ok"
STATUS_UNCHECKED = "unchecked"
STATUS_ERROR = "error"

# Owner-armed Telegram transport (cycle #78). This monitor's alert path had never fired
# once: it could not read the feed, so it never found an opportunity to alert about.
# Repointing it at the real schema makes it live again — and a read-only smoke on a COPY
# of production data showed the FIRST run would send three "BTS EXCELLENT … Annual PnL
# $N" messages, because EXCELLENT is >=100bps net against a hardcoded 5% spot baseline
# and any non-negative funding clears it. Switching on a dormant owner-facing claim from
# an unvalidated model is not an autonomous call (ORCHESTRATOR_PROTOCOL, "запрещено
# автономно"), so the transport stays disarmed until the owner arms it, while the
# artifacts below are written honestly and completely either way. The suppression is
# recorded verbatim in the status file — it is never silent.
BTS_ALERTS_ARMED_ENV = "SPA_BTS_ALERTS_ARMED"


def _alerts_armed() -> bool:
    return os.environ.get(BTS_ALERTS_ARMED_ENV, "").strip().lower() in {"1", "true", "yes"}


def _verdict(errors: List[str], unchecked: List[str]) -> str:
    """An error outranks an unmeasured check; both outrank "ok"."""
    if errors:
        return STATUS_ERROR
    if unchecked:
        return STATUS_UNCHECKED
    return STATUS_OK


@dataclass
class FundingLoad:
    """Outcome of loading the funding payload.

    `data` is None whenever the payload must not be scanned. `stale` describes the
    FEED (not the number of opportunities). `unchecked` is a verbatim reason something
    could not be measured; `refusal` is a verbatim reason the payload was rejected.
    """

    data: Optional[dict]
    stale: bool
    unchecked: Optional[str] = None
    refusal: Optional[str] = None


@dataclass
class BTSScan:
    """Result of one scan: what was found, whether the FEED was stale, and what was
    not measured (verbatim). An empty `opportunities` list means "measured, nothing
    qualified" only when `unchecked` is empty."""

    opportunities: List["BTSOpportunity"]
    stale_feed: bool
    unchecked: List[str]
    refusal: Optional[str] = None


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
        """Back-compat wrapper: the payload only, verdict discarded."""
        return self._load_funding_verdict().data

    def _load_funding_verdict(self) -> "FundingLoad":
        """Load the funding payload AND say why it is unusable when it is.

        The staleness threshold (STALE_AFTER_S) and the "feed says stale" rule are
        unchanged; what is new is that an age which could not be computed is reported
        as NOT MEASURED instead of silently passing for fresh (the pre-#78 code asked
        for `generated_at`, a key the live feed never writes, so the age check never
        ran once in production).
        """
        try:
            data = atomic_load(str(self._funding_path), default=None)
        except Exception as exc:
            return FundingLoad(None, True, f"funding file unreadable: {exc}")
        if not data:
            return FundingLoad(
                None, True, None, refusal=f"no funding data at {self._funding_path.name}"
            )

        unchecked: Optional[str] = None
        age = feed_age_seconds(data)
        if age.measured and age.age_seconds is not None:
            if age.age_seconds > STALE_AFTER_S:
                log.info(
                    "Funding data stale (age %.0fs > %ds)", age.age_seconds, STALE_AFTER_S
                )
                return FundingLoad(
                    None,
                    True,
                    None,
                    refusal=(
                        f"feed age {age.age_seconds:.0f}s exceeds {STALE_AFTER_S}s "
                        f"(from {age.source_key!r})"
                    ),
                )
        else:
            unchecked = f"feed age NOT MEASURED — {age.unchecked}"
            log.info("Funding age not measured: %s", age.unchecked)

        if data.get("stale", False):
            log.info("Funding data marked stale by feed")
            return FundingLoad(
                None, True, unchecked, refusal="feed marked its own payload stale"
            )
        return FundingLoad(data, False, unchecked)

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
        """Ranked opportunities only. See `scan_with_reasons` for what was NOT measured."""
        return self.scan_with_reasons().opportunities

    def scan_with_reasons(self) -> "BTSScan":
        """Scan the feed and report, verbatim, everything that could not be measured.

        An empty result now carries its reason: "the feed said there are no assets" and
        "the file was in a shape this monitor cannot read" are different facts, and
        before #78 both were published identically as `status: ok, 0 opportunities`.
        """
        unchecked: List[str] = []

        load = self._load_funding_verdict()
        if load.unchecked:
            unchecked.append(load.unchecked)
        funding_data = load.data
        if funding_data is None:
            reason = load.refusal or "no valid funding data"
            log.info("No valid funding data — returning empty opportunities (%s)", reason)
            # A refused payload means NO scan happened. "0 opportunities" is then a
            # non-statement, and publishing it as `status: ok` is the defect this file
            # exists to prevent — so the refusal is carried as an unchecked reason too.
            unchecked.append(f"scan NOT PERFORMED — {reason}")
            return BTSScan([], load.stale, unchecked, refusal=reason)

        adapter_status = self._load_adapter_status()
        spot_yield = self._get_spot_yield(adapter_status)

        rates_read = read_rates(funding_data)
        if not rates_read.measured:
            log.info("Funding rates NOT MEASURED: %s", rates_read.unchecked)
            unchecked.append(f"funding rates NOT MEASURED — {rates_read.unchecked}")
            return BTSScan([], load.stale, unchecked)
        rates = rates_read.rates
        if not rates:
            log.info(
                "No rates in funding data (feed reported an empty %r map)",
                rates_read.source_key,
            )
            return BTSScan([], load.stale, unchecked)

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
            log.info(
                "No valid inputs built from funding data (tracked %s; feed offered %s)",
                list(TRACKED_ASSETS),
                sorted(str(k) for k in rates.keys()),
            )
            return BTSScan([], load.stale, unchecked)

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

        return BTSScan(opportunities, load.stale, unchecked)

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
        unchecked: Optional[List[str]] = None,
    ) -> None:
        now_iso = datetime.now(timezone.utc).isoformat()
        excellent_count = sum(1 for o in opps if o.edge_quality == "EXCELLENT")
        enter_count = sum(1 for o in opps if o.recommended_action == "ENTER")
        unchecked = list(unchecked or [])

        payload = {
            "timestamp": now_iso,
            "generated_at": time.time(),
            "stale_feed": stale,
            "opportunities": [o.to_dict() for o in opps],
            "unchecked": unchecked,
            "summary": {
                "excellent_count": excellent_count,
                "enter_count": enter_count,
                "total_analyzed": len(opps),
                "measured": not unchecked,
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
        unchecked: Optional[List[str]] = None,
        suppressed: Optional[List[str]] = None,
    ) -> None:
        now_iso = datetime.now(timezone.utc).isoformat()
        unchecked = list(unchecked or [])
        suppressed = list(suppressed or [])
        payload = {
            "last_run": now_iso,
            "opportunities_found": len(opps),
            "new_excellent": new_excellent_count,
            "status": _verdict(errors, unchecked),
            "errors": errors,
            "unchecked": unchecked,
            "suppressed_alerts": suppressed,
        }
        try:
            atomic_save(payload, str(self._status_path))
        except Exception as exc:
            log.error("Failed to save status: %s", exc)

    def run(self) -> dict:
        errors: List[str] = []
        unchecked: List[str] = []
        suppressed: List[str] = []
        opps: List[BTSOpportunity] = []
        new_excellent_count = 0

        try:
            scan = self.scan_with_reasons()
            opps = scan.opportunities
            unchecked = list(scan.unchecked)
            # `stale` describes the FEED. Before #78 it was `len(opps) == 0`, i.e. the
            # monitor published "the feed is stale" whenever nothing qualified — a claim
            # about a file, derived from something else entirely.
            stale = scan.stale_feed

            if opps:
                new_excellent = self._detect_new_excellent(opps)
                new_excellent_count = len(new_excellent)
                if new_excellent:
                    if _alerts_armed():
                        self._create_alerts(new_excellent)
                    else:
                        assets = ", ".join(o.asset for o in new_excellent)
                        note = (
                            f"{len(new_excellent)} new EXCELLENT ({assets}) NOT sent to "
                            f"Telegram: transport disarmed pending owner review "
                            f"(set {BTS_ALERTS_ARMED_ENV}=1 to arm)"
                        )
                        log.info(note)
                        suppressed.append(note)

            self._save_opportunities(opps, stale, unchecked)

        except Exception as exc:
            log.error("BTS monitor scan failed: %s", exc)
            errors.append(str(exc))
            self._save_opportunities([], True, unchecked)

        self._save_status(opps, new_excellent_count, errors, unchecked, suppressed)

        report = {
            "opportunities": len(opps),
            "new_excellent": new_excellent_count,
            "errors": errors,
            "unchecked": unchecked,
            "suppressed_alerts": suppressed,
            "status": _verdict(errors, unchecked),
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
