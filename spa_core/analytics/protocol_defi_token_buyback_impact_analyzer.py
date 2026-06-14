"""
MP-1001: ProtocolDeFiTokenBuybackImpactAnalyzer
Analyzes DeFi protocol token buyback programs and their price impact.

Read-only analytics module. Writes ring-buffer log to
data/token_buyback_log.json (cap 100, atomic write).

stdlib only — no external dependencies.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LOG_CAP = 100
_LOG_FILENAME = "token_buyback_log.json"

VALID_SOURCES = frozenset({
    "protocol_revenue", "treasury", "inflation", "external",
})

VALID_MECHANISMS = frozenset({
    "market_buy", "burn", "stake_distribute", "treasury_hold",
})

_ALL_LABELS = frozenset({
    "HIGHLY_ACCRETIVE",
    "ACCRETIVE",
    "NEUTRAL",
    "INFLATIONARY_OFFSET",
    "UNSUSTAINABLE",
})

_ALL_FLAGS = frozenset({
    "DEFLATIONARY_PRESSURE",
    "REVENUE_FUNDED",
    "TREASURY_DRAWDOWN",
    "MEANINGFUL_BUY_PRESSURE",
    "INFLATION_FUNDED_BUYBACK",
    "CONSISTENT_PROGRAM",
})


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class ProtocolDeFiTokenBuybackImpactAnalyzer:
    """
    Analyzes DeFi protocol token buyback programs.

    Metrics computed per program:
      • annualized_buyback_usd          = weekly_buyback × 52
      • buyback_yield_pct               = annualized / market_cap × 100
      • buyback_to_volume_ratio         = weekly_buyback / (daily_vol × 7) × 100
      • supply_reduction_rate_pct       = annual_burn / market_cap × 100
      • sustainability_score (0-100)

    Labels (mutually exclusive, priority order):
      HIGHLY_ACCRETIVE > INFLATIONARY_OFFSET > UNSUSTAINABLE > ACCRETIVE > NEUTRAL

    Flags (independent):
      DEFLATIONARY_PRESSURE, REVENUE_FUNDED, TREASURY_DRAWDOWN,
      MEANINGFUL_BUY_PRESSURE, INFLATION_FUNDED_BUYBACK, CONSISTENT_PROGRAM
    """

    def __init__(self, data_dir: str = "data") -> None:
        self.data_dir = data_dir
        self.log_path = os.path.join(data_dir, _LOG_FILENAME)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self, programs: list, config: dict) -> dict:
        """
        Analyze token buyback programs.

        Args:
            programs: list[dict] — each dict describes one buyback program.
            config:   dict — optional overrides:
                        log_enabled (bool, default True)
                        data_dir    (str, overrides self.data_dir)

        Returns:
            dict with keys: timestamp, module, mp, program_count, programs, aggregates
        """
        if not isinstance(programs, list):
            raise TypeError("programs must be a list")
        if not isinstance(config, dict):
            raise TypeError("config must be a dict")

        data_dir = config.get("data_dir", self.data_dir)
        log_enabled = config.get("log_enabled", True)

        results = [self._analyze_program(p) for p in programs]
        aggregates = self._compute_aggregates(results)

        output = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "module": "ProtocolDeFiTokenBuybackImpactAnalyzer",
            "mp": "MP-1001",
            "program_count": len(results),
            "programs": results,
            "aggregates": aggregates,
        }

        if log_enabled:
            self._append_log(output, data_dir)

        return output

    # ------------------------------------------------------------------
    # Per-program analysis
    # ------------------------------------------------------------------

    def _analyze_program(self, program: dict) -> dict:
        name = program.get("name", "unknown")
        protocol = program.get("protocol", "")
        weekly_buyback_usd = float(program.get("weekly_buyback_usd", 0.0))
        buyback_source = str(program.get("buyback_source", "external"))
        market_cap = float(program.get("token_circulating_supply_usd", 1.0))
        daily_volume = float(program.get("token_daily_volume_usd", 1.0))
        fdv = float(program.get("token_fdv_usd", 0.0))
        mechanism = str(program.get("buyback_mechanism", "market_buy"))
        price_impact = float(program.get("price_impact_estimate_pct", 0.0))
        consistency = float(program.get("buyback_consistency_score", 0.0))
        revenue_coverage = float(program.get("revenue_coverage_ratio", 1.0))
        burn_pct = float(program.get("burn_pct", 0.0))

        # Guard against division by zero
        if market_cap <= 0.0:
            market_cap = 1.0
        if daily_volume <= 0.0:
            daily_volume = 1.0

        # ── Core metrics ──────────────────────────────────────────────
        annualized_buyback_usd = weekly_buyback_usd * 52.0
        buyback_yield_pct = annualized_buyback_usd / market_cap * 100.0

        weekly_volume = daily_volume * 7.0
        buyback_to_volume_ratio = (
            weekly_buyback_usd / weekly_volume * 100.0
            if weekly_volume > 0 else 0.0
        )

        # Annual amount actually burned (supply destroyed)
        annual_burned_usd = annualized_buyback_usd * (burn_pct / 100.0)
        supply_reduction_rate_pct = annual_burned_usd / market_cap * 100.0

        sustainability_score = self._compute_sustainability_score(
            buyback_source, revenue_coverage, burn_pct
        )

        # ── Label & flags ─────────────────────────────────────────────
        label = self._determine_label(
            buyback_source, buyback_yield_pct, burn_pct, mechanism
        )
        flags = self._compute_flags(
            buyback_source, supply_reduction_rate_pct,
            buyback_to_volume_ratio, consistency,
        )

        return {
            # Input fields
            "name": name,
            "protocol": protocol,
            "weekly_buyback_usd": weekly_buyback_usd,
            "buyback_source": buyback_source,
            "token_circulating_supply_usd": market_cap,
            "token_daily_volume_usd": daily_volume,
            "token_fdv_usd": fdv,
            "buyback_mechanism": mechanism,
            "price_impact_estimate_pct": price_impact,
            "buyback_consistency_score": consistency,
            "revenue_coverage_ratio": revenue_coverage,
            "burn_pct": burn_pct,
            # Derived
            "annualized_buyback_usd": round(annualized_buyback_usd, 2),
            "buyback_yield_pct": round(buyback_yield_pct, 4),
            "buyback_to_volume_ratio": round(buyback_to_volume_ratio, 4),
            "supply_reduction_rate_pct": round(supply_reduction_rate_pct, 4),
            "sustainability_score": sustainability_score,
            "label": label,
            "flags": flags,
        }

    # ------------------------------------------------------------------
    # Sustainability score (0-100)
    # ------------------------------------------------------------------

    def _compute_sustainability_score(
        self, source: str, revenue_coverage: float, burn_pct: float
    ) -> int:
        """
        Higher = more sustainable.
        protocol_revenue + coverage≤1 → ~80-100
        external                      → ~55-65
        treasury                      → ~25-45
        inflation                     → 0-20
        """
        if source == "protocol_revenue":
            if revenue_coverage <= 1.0:
                base = 90
            else:
                # Penalise over-spending vs revenue
                penalty = min(40, int((revenue_coverage - 1.0) * 40))
                base = max(50, 90 - penalty)
        elif source == "external":
            base = 60
        elif source == "treasury":
            base = 35
        elif source == "inflation":
            base = 10
        else:
            base = 50

        # Small bonus for burning (vs distributing)
        burn_bonus = int(burn_pct * 0.1)  # up to +10 for 100% burn
        return min(100, max(0, base + burn_bonus))

    # ------------------------------------------------------------------
    # Label determination
    # ------------------------------------------------------------------

    def _determine_label(
        self,
        source: str,
        buyback_yield_pct: float,
        burn_pct: float,
        mechanism: str,
    ) -> str:
        """
        Priority:
          1. HIGHLY_ACCRETIVE  — revenue-funded, yield>5%, burn>80%
          2. INFLATIONARY_OFFSET — inflation source (circular)
          3. UNSUSTAINABLE      — treasury source (draining reserves)
          4. ACCRETIVE          — yield>2% (any sustainable source)
          5. NEUTRAL            — yield<1% OR mechanism≠burn
        """
        if (source == "protocol_revenue"
                and buyback_yield_pct > 5.0
                and burn_pct > 80.0):
            return "HIGHLY_ACCRETIVE"

        if source == "inflation":
            return "INFLATIONARY_OFFSET"

        if source == "treasury":
            return "UNSUSTAINABLE"

        if buyback_yield_pct > 2.0:
            return "ACCRETIVE"

        return "NEUTRAL"

    # ------------------------------------------------------------------
    # Flag computation
    # ------------------------------------------------------------------

    def _compute_flags(
        self,
        source: str,
        supply_reduction_rate_pct: float,
        buyback_to_volume_ratio: float,
        consistency: float,
    ) -> list:
        flags: list[str] = []

        if supply_reduction_rate_pct > 2.0:
            flags.append("DEFLATIONARY_PRESSURE")

        if source == "protocol_revenue":
            flags.append("REVENUE_FUNDED")

        if source == "treasury":
            flags.append("TREASURY_DRAWDOWN")

        if buyback_to_volume_ratio > 5.0:
            flags.append("MEANINGFUL_BUY_PRESSURE")

        if source == "inflation":
            flags.append("INFLATION_FUNDED_BUYBACK")

        if consistency > 80.0:
            flags.append("CONSISTENT_PROGRAM")

        return flags

    # ------------------------------------------------------------------
    # Aggregates
    # ------------------------------------------------------------------

    def _compute_aggregates(self, results: list) -> dict:
        if not results:
            return {
                "most_accretive": None,
                "least_accretive": None,
                "total_weekly_buyback_usd": 0.0,
                "highly_accretive_count": 0,
                "unsustainable_count": 0,
            }

        most_accretive = max(results, key=lambda r: r["buyback_yield_pct"])
        least_accretive = min(results, key=lambda r: r["buyback_yield_pct"])
        total_weekly = sum(r["weekly_buyback_usd"] for r in results)
        highly_accretive_count = sum(
            1 for r in results if r["label"] == "HIGHLY_ACCRETIVE"
        )
        unsustainable_count = sum(
            1 for r in results if r["label"] == "UNSUSTAINABLE"
        )

        return {
            "most_accretive": most_accretive["name"],
            "least_accretive": least_accretive["name"],
            "total_weekly_buyback_usd": round(total_weekly, 2),
            "highly_accretive_count": highly_accretive_count,
            "unsustainable_count": unsustainable_count,
        }

    # ------------------------------------------------------------------
    # Ring-buffer log (atomic write)
    # ------------------------------------------------------------------

    def _append_log(self, record: dict, data_dir: str) -> None:
        """Append compact entry to ring-buffer log (cap=LOG_CAP). Atomic."""
        os.makedirs(data_dir, exist_ok=True)
        log_path = os.path.join(data_dir, _LOG_FILENAME)

        try:
            with open(log_path, "r") as fh:
                log: list = json.load(fh)
            if not isinstance(log, list):
                log = []
        except (FileNotFoundError, json.JSONDecodeError):
            log = []

        entry = {
            "timestamp": record["timestamp"],
            "program_count": record["program_count"],
            "aggregates": record["aggregates"],
        }
        log.append(entry)
        log = log[-LOG_CAP:]  # ring-buffer

        tmp_path = log_path + ".tmp"
        with open(tmp_path, "w") as fh:
            json.dump(log, fh, indent=2)
        os.replace(tmp_path, log_path)
