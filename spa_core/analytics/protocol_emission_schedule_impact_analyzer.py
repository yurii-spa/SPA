"""
MP-961: ProtocolEmissionScheduleImpactAnalyzer
Анализирует влияние расписания эмиссии токенов на цену и доходность протокола.
Только stdlib Python. Атомарные записи (tmp + os.replace).
"""

import json
import os
from datetime import datetime
from typing import Any
from spa_core.utils.atomic import atomic_save


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_LOG_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "data", "emission_schedule_log.json")
_LOG_CAP = 100

EMISSION_LABELS = (
    "DEFLATIONARY",
    "ULTRA_LOW",
    "LOW_INFLATION",
    "MODERATE_INFLATION",
    "HIGH_INFLATION",
    "HYPERINFLATIONARY",
)


def _atomic_write(path: str, data: Any) -> None:
    abs_path = os.path.abspath(path)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    atomic_save(data, str(abs_path))
def _load_log(path: str) -> list:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return []


# ---------------------------------------------------------------------------
# Core class
# ---------------------------------------------------------------------------
class ProtocolEmissionScheduleImpactAnalyzer:
    """
    Analyzes token emission schedules and their impact on price/yield.
    Computes inflation rate, sell pressure, nearest unlock events, and
    risk flags for each protocol's token.
    """

    def __init__(self, log_path: str | None = None):
        self._log_path = log_path or _LOG_FILE

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def analyze(self, schedules: list[dict], config: dict | None = None) -> dict:
        """
        Args:
            schedules: list of emission schedule dicts (see module docstring)
            config: optional overrides (log_enabled, log_path, …)

        Returns:
            dict with per-schedule results and aggregate metrics
        """
        config = config or {}
        results = []
        for sched in schedules:
            results.append(self._analyze_schedule(sched))

        aggregate = self._aggregate(results)
        output = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "schedule_count": len(schedules),
            "schedules": results,
            "aggregate": aggregate,
        }

        if config.get("log_enabled", True):
            self._append_log(output, config.get("log_path", self._log_path))

        return output

    # ------------------------------------------------------------------
    # Per-schedule analysis
    # ------------------------------------------------------------------
    def _analyze_schedule(self, s: dict) -> dict:
        protocol = s.get("protocol", "unknown")
        token_name = s.get("token_name", "TOKEN")
        price = float(s.get("current_price_usd", 1.0))
        circulating = float(s.get("circulating_supply", 1_000_000.0))
        max_supply = float(s.get("max_supply", 0.0))
        daily_emission = float(s.get("daily_emission_tokens", 0.0))
        unlock_events = s.get("emission_unlock_events", []) or []
        buy_pressure = float(s.get("current_buy_pressure_usd_daily", 1.0))
        staking_sink_pct = float(s.get("staking_sink_rate_pct", 0.0))
        burn_rate = float(s.get("burn_rate_tokens_daily", 0.0))

        # Safety clamps
        circulating = max(circulating, 1.0)
        buy_pressure = max(buy_pressure, 1e-9)
        staking_sink_pct = max(0.0, min(staking_sink_pct, 100.0))

        # --- Core metrics ---
        staking_absorbed = daily_emission * staking_sink_pct / 100.0
        net_daily_emission = daily_emission - burn_rate - staking_absorbed
        sell_pressure_usd = net_daily_emission * price
        price_impact_ratio = sell_pressure_usd / buy_pressure

        # Inflation rate (annualised, based on net emission vs circulating supply)
        inflation_rate_annual = (net_daily_emission * 365.0 / circulating) * 100.0

        # Months to max supply
        months_to_max = None
        if max_supply > 0 and net_daily_emission > 0:
            remaining_tokens = max_supply - circulating
            if remaining_tokens > 0:
                months_to_max = remaining_tokens / net_daily_emission / 30.0
            else:
                months_to_max = 0.0

        # Nearest unlock event
        nearest_unlock = self._nearest_unlock(unlock_events)

        # Emission label
        emission_label = self._emission_label(inflation_rate_annual)

        # Flags
        flags = self._compute_flags(
            unlock_events=unlock_events,
            circulating=circulating,
            price_impact_ratio=price_impact_ratio,
            burn_rate=burn_rate,
            daily_emission=daily_emission,
            max_supply=max_supply,
        )

        return {
            "protocol": protocol,
            "token_name": token_name,
            "net_daily_emission": round(net_daily_emission, 6),
            "sell_pressure_usd_daily": round(sell_pressure_usd, 4),
            "price_impact_ratio": round(price_impact_ratio, 6),
            "inflation_rate_annual_pct": round(inflation_rate_annual, 4),
            "months_to_max_supply": round(months_to_max, 2) if months_to_max is not None else None,
            "nearest_unlock_event": nearest_unlock,
            "emission_label": emission_label,
            "flags": flags,
            # meta
            "staking_absorbed_daily": round(staking_absorbed, 6),
            "burn_rate_tokens_daily": round(burn_rate, 6),
            "current_price_usd": price,
            "circulating_supply": circulating,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _nearest_unlock(unlock_events: list[dict]) -> dict | None:
        future = [e for e in unlock_events if float(e.get("date_days_from_now", -1)) >= 0]
        if not future:
            return None
        nearest = min(future, key=lambda e: float(e.get("date_days_from_now", float("inf"))))
        return {
            "date_days_from_now": float(nearest.get("date_days_from_now", 0)),
            "tokens_unlocked": float(nearest.get("tokens_unlocked", 0)),
            "recipient": nearest.get("recipient", "unknown"),
        }

    @staticmethod
    def _emission_label(inflation_rate: float) -> str:
        if inflation_rate < 0.0:
            return "DEFLATIONARY"
        if inflation_rate <= 2.0:
            return "ULTRA_LOW"
        if inflation_rate <= 10.0:
            return "LOW_INFLATION"
        if inflation_rate <= 30.0:
            return "MODERATE_INFLATION"
        if inflation_rate <= 100.0:
            return "HIGH_INFLATION"
        return "HYPERINFLATIONARY"

    @staticmethod
    def _compute_flags(
        unlock_events: list[dict],
        circulating: float,
        price_impact_ratio: float,
        burn_rate: float,
        daily_emission: float,
        max_supply: float,
    ) -> list[str]:
        flags = []

        # Check unlock events
        imminent_unlock = False
        team_unlock_risk = False
        for event in unlock_events:
            days = float(event.get("date_days_from_now", float("inf")))
            tokens = float(event.get("tokens_unlocked", 0.0))
            recipient = str(event.get("recipient", "")).lower()
            if days >= 0 and days < 30 and tokens / circulating > 0.01:
                imminent_unlock = True
                if recipient in ("team", "founder", "founders"):
                    team_unlock_risk = True

        if imminent_unlock:
            flags.append("IMMINENT_UNLOCK")
        if team_unlock_risk:
            flags.append("TEAM_UNLOCK_RISK")
        if price_impact_ratio > 2.0:
            flags.append("SELL_PRESSURE_DOMINATES")
        if daily_emission > 0 and burn_rate / daily_emission > 0.5:
            flags.append("BURN_OFFSETTING")
        if max_supply > 0 and circulating / max_supply > 0.9:
            flags.append("NEAR_MAX_SUPPLY")

        return flags

    # ------------------------------------------------------------------
    # Aggregates
    # ------------------------------------------------------------------
    @staticmethod
    def _aggregate(results: list[dict]) -> dict:
        if not results:
            return {
                "most_inflationary": None,
                "most_deflationary": None,
                "average_inflation_rate": 0.0,
                "imminent_unlock_count": 0,
                "deflationary_count": 0,
            }

        sorted_asc = sorted(results, key=lambda r: r["inflation_rate_annual_pct"])
        most_deflationary = sorted_asc[0]
        most_inflationary = sorted_asc[-1]

        avg_inflation = sum(r["inflation_rate_annual_pct"] for r in results) / len(results)
        imminent = sum(1 for r in results if "IMMINENT_UNLOCK" in r["flags"])
        deflation_count = sum(1 for r in results if r["emission_label"] == "DEFLATIONARY")

        return {
            "most_inflationary": {
                "protocol": most_inflationary["protocol"],
                "token_name": most_inflationary["token_name"],
                "inflation_rate_annual_pct": most_inflationary["inflation_rate_annual_pct"],
            },
            "most_deflationary": {
                "protocol": most_deflationary["protocol"],
                "token_name": most_deflationary["token_name"],
                "inflation_rate_annual_pct": most_deflationary["inflation_rate_annual_pct"],
            },
            "average_inflation_rate": round(avg_inflation, 4),
            "imminent_unlock_count": imminent,
            "deflationary_count": deflation_count,
        }

    # ------------------------------------------------------------------
    # Ring-buffer log
    # ------------------------------------------------------------------
    def _append_log(self, entry: dict, path: str) -> None:
        log = _load_log(path)
        log.append({
            "ts": entry["timestamp"],
            "schedule_count": entry["schedule_count"],
            "aggregate": entry["aggregate"],
        })
        if len(log) > _LOG_CAP:
            log = log[-_LOG_CAP:]
        try:
            _atomic_write(path, log)
        except Exception:
            pass
