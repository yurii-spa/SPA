"""
MP-994: DeFiLendingProtocolBadDebtMonitor
Monitors accumulated bad debts in DeFi lending protocols.
Pure stdlib only. Advisory/read-only. Atomic writes.
Data log: data/bad_debt_log.json (ring-buffer, max 100 entries)
"""

import json
import os
import time
from pathlib import Path

_LOG_CAP = 100
_DEFAULT_DATA_FILE = Path("data/bad_debt_log.json")

# Health label thresholds
_PRISTINE_MAX_RATIO = 0.01      # < 0.01% bad_debt_ratio
_PRISTINE_MIN_COVERAGE = 10.0   # reserve covers 10x bad debt
_HEALTHY_MAX_RATIO = 0.1        # < 0.1%
_WATCHLIST_MAX_RATIO = 0.5      # >= 0.1%, < 0.5%
_STRESSED_MIN_RATIO = 0.5       # >= 0.5% OR reserve < 2x
_STRESSED_MIN_COVERAGE = 2.0
_INSOLVENT_MIN_RATIO = 2.0      # >= 2% OR reserve < 1x
_INSOLVENT_MIN_COVERAGE = 1.0

# Contagion score weights (each component max = 25)
_CONTAGION_RATIO_MAX = 25.0
_CONTAGION_FAILED_MAX = 25.0
_CONTAGION_LARGE_MAX = 25.0
_CONTAGION_TREND_MAX = 25.0

# Flag thresholds
_BAD_DEBT_ACCEL_TREND = 50.0     # trend > 50% in 30d
_RESERVE_DEPLETED_COVERAGE = 1.5  # reserve/bad_debt < 1.5
_LARGE_POSITION_PCT = 10.0        # largest > 10% of total_borrowed
_FAILED_LIQ_FLAG_PCT = 5.0        # failed_liq_pct > 5%


class DeFiLendingProtocolBadDebtMonitor:
    """
    Monitors accumulated bad debts in DeFi lending protocols.

    Each protocol dict must include:
        name (str), total_borrowed_usd (float), bad_debt_usd (float),
        bad_debt_trend_pct_30d (float), reserve_fund_usd (float),
        total_tvl_usd (float), largest_underwater_position_usd (float),
        avg_collateral_ratio_pct (float), liquidation_count_30d (int),
        failed_liquidation_count_30d (int), protocol_covers_bad_debt (bool),
        token_inflation_risk (bool)
    """

    def __init__(self, data_file: Path = _DEFAULT_DATA_FILE):
        self.data_file = Path(data_file)

    # ------------------------------------------------------------------
    # Core calculations
    # ------------------------------------------------------------------

    def _bad_debt_ratio_pct(self, protocol: dict) -> float:
        """bad_debt_usd / total_borrowed_usd * 100."""
        total = protocol.get("total_borrowed_usd", 0.0)
        bad = protocol.get("bad_debt_usd", 0.0)
        if total <= 0.0:
            return 0.0
        return round(bad / total * 100.0, 6)

    def _reserve_coverage_ratio(self, protocol: dict) -> float:
        """reserve_fund_usd / max(bad_debt_usd, 1)."""
        reserve = protocol.get("reserve_fund_usd", 0.0)
        bad = protocol.get("bad_debt_usd", 0.0)
        if bad <= 0.0:
            return 9999.0  # effectively infinite coverage when no bad debt
        return round(reserve / bad, 6)

    def _failed_liq_pct(self, protocol: dict) -> float:
        """failed_liquidation_count_30d / max(liquidation_count_30d, 1) * 100."""
        total_liq = protocol.get("liquidation_count_30d", 0)
        failed = protocol.get("failed_liquidation_count_30d", 0)
        if total_liq <= 0:
            return 0.0
        return round(failed / total_liq * 100.0, 4)

    def _contagion_risk_score(
        self,
        bad_debt_ratio: float,
        failed_liq_pct: float,
        protocol: dict,
    ) -> float:
        """Contagion risk 0-100 from four equally-weighted components (25 each)."""
        # Component 1: bad_debt_ratio contribution (2% = full 25 pts)
        ratio_score = min(_CONTAGION_RATIO_MAX, bad_debt_ratio / 2.0 * _CONTAGION_RATIO_MAX)

        # Component 2: failed liquidations (100% failed = full 25 pts)
        failed_score = min(_CONTAGION_FAILED_MAX, failed_liq_pct / 100.0 * _CONTAGION_FAILED_MAX)

        # Component 3: largest underwater position relative to total borrowed
        total = protocol.get("total_borrowed_usd", 0.0)
        largest = protocol.get("largest_underwater_position_usd", 0.0)
        if total > 0.0:
            large_ratio_pct = largest / total * 100.0
        else:
            large_ratio_pct = 0.0
        # 10%+ position → approaching full score
        large_score = min(_CONTAGION_LARGE_MAX, large_ratio_pct / 10.0 * _CONTAGION_LARGE_MAX)

        # Component 4: 30-day trend (50%+ acceleration = full 25 pts)
        trend = protocol.get("bad_debt_trend_pct_30d", 0.0)
        trend_clipped = max(0.0, trend)  # negative trend (improving) → 0 risk
        trend_score = min(_CONTAGION_TREND_MAX, trend_clipped / 50.0 * _CONTAGION_TREND_MAX)

        total_score = ratio_score + failed_score + large_score + trend_score
        return round(max(0.0, min(100.0, total_score)), 2)

    def _solvency_score(
        self,
        bad_debt_ratio: float,
        reserve_coverage: float,
        failed_liq_pct: float,
    ) -> float:
        """Solvency score 0-100 (higher = more solvent). 100 - weighted risk."""
        # Bad debt deduction: up to 50 points (2% ratio = full 50)
        bad_debt_deduct = min(50.0, bad_debt_ratio / 2.0 * 50.0)

        # Reserve shortage deduction: up to 30 points (below 2x coverage)
        if reserve_coverage >= 2.0:
            reserve_deduct = 0.0
        elif reserve_coverage <= 0.0:
            reserve_deduct = 30.0
        else:
            reserve_deduct = min(30.0, (2.0 - reserve_coverage) / 2.0 * 30.0)

        # Failed liquidations deduction: up to 20 points
        failed_deduct = min(20.0, failed_liq_pct / 100.0 * 20.0)

        score = 100.0 - bad_debt_deduct - reserve_deduct - failed_deduct
        return round(max(0.0, min(100.0, score)), 2)

    def _health_label(
        self,
        bad_debt_ratio: float,
        reserve_coverage: float,
    ) -> str:
        """
        INSOLVENT > STRESSED > WATCHLIST > HEALTHY > PRISTINE
        (checked from most severe to least).
        """
        # INSOLVENT: bad_debt_ratio >= 2% OR reserve_coverage < 1x (when bad debt exists)
        if bad_debt_ratio >= _INSOLVENT_MIN_RATIO or (
            reserve_coverage < _INSOLVENT_MIN_COVERAGE and reserve_coverage < 9000.0
        ):
            return "INSOLVENT"

        # STRESSED: bad_debt_ratio >= 0.5% OR reserve_coverage < 2x (when bad debt exists)
        if bad_debt_ratio >= _STRESSED_MIN_RATIO or (
            reserve_coverage < _STRESSED_MIN_COVERAGE and reserve_coverage < 9000.0
        ):
            return "STRESSED"

        # WATCHLIST: bad_debt_ratio >= 0.1%
        if bad_debt_ratio >= _HEALTHY_MAX_RATIO:
            return "WATCHLIST"

        # PRISTINE: very low bad debt AND high reserve coverage
        if bad_debt_ratio < _PRISTINE_MAX_RATIO and reserve_coverage >= _PRISTINE_MIN_COVERAGE:
            return "PRISTINE"

        return "HEALTHY"

    def _compute_flags(
        self,
        protocol: dict,
        bad_debt_ratio: float,
        reserve_coverage: float,
        failed_liq_pct_val: float,
    ) -> list:
        flags = []

        trend = protocol.get("bad_debt_trend_pct_30d", 0.0)
        if trend > _BAD_DEBT_ACCEL_TREND:
            flags.append("BAD_DEBT_ACCELERATING")

        bad_debt = protocol.get("bad_debt_usd", 0.0)
        if bad_debt > 0.0 and reserve_coverage < _RESERVE_DEPLETED_COVERAGE:
            flags.append("RESERVE_DEPLETED")

        total = protocol.get("total_borrowed_usd", 0.0)
        largest = protocol.get("largest_underwater_position_usd", 0.0)
        if total > 0.0 and largest / total * 100.0 > _LARGE_POSITION_PCT:
            flags.append("LARGE_UNDERWATER_POSITION")

        if failed_liq_pct_val > _FAILED_LIQ_FLAG_PCT:
            flags.append("FAILED_LIQUIDATIONS")

        if protocol.get("token_inflation_risk", False):
            flags.append("TOKEN_INFLATION_RISK")

        # Positive flag — protocol absorbed losses
        if protocol.get("protocol_covers_bad_debt", False):
            flags.append("PROTOCOL_COVERED")

        return flags

    def _analyze_protocol(self, protocol: dict) -> dict:
        name = protocol.get("name", "unknown")
        bd_ratio = self._bad_debt_ratio_pct(protocol)
        reserve_cov = self._reserve_coverage_ratio(protocol)
        failed_pct = self._failed_liq_pct(protocol)
        contagion = self._contagion_risk_score(bd_ratio, failed_pct, protocol)
        solvency = self._solvency_score(bd_ratio, reserve_cov, failed_pct)
        health = self._health_label(bd_ratio, reserve_cov)
        flags = self._compute_flags(protocol, bd_ratio, reserve_cov, failed_pct)

        return {
            "name": name,
            "bad_debt_ratio_pct": bd_ratio,
            "reserve_coverage_ratio": reserve_cov,
            "failed_liq_pct": failed_pct,
            "contagion_risk_score": contagion,
            "solvency_score": solvency,
            "health_label": health,
            "flags": flags,
            # pass-through key metrics
            "bad_debt_usd": protocol.get("bad_debt_usd", 0.0),
            "reserve_fund_usd": protocol.get("reserve_fund_usd", 0.0),
            "total_borrowed_usd": protocol.get("total_borrowed_usd", 0.0),
            "total_tvl_usd": protocol.get("total_tvl_usd", 0.0),
            "bad_debt_trend_pct_30d": protocol.get("bad_debt_trend_pct_30d", 0.0),
            "largest_underwater_position_usd": protocol.get("largest_underwater_position_usd", 0.0),
            "avg_collateral_ratio_pct": protocol.get("avg_collateral_ratio_pct", 0.0),
            "liquidation_count_30d": protocol.get("liquidation_count_30d", 0),
            "failed_liquidation_count_30d": protocol.get("failed_liquidation_count_30d", 0),
            "protocol_covers_bad_debt": protocol.get("protocol_covers_bad_debt", False),
            "token_inflation_risk": protocol.get("token_inflation_risk", False),
        }

    # ------------------------------------------------------------------
    # Aggregates
    # ------------------------------------------------------------------

    def _compute_aggregates(self, results: list) -> dict:
        if not results:
            return {
                "healthiest": None,
                "most_stressed": None,
                "total_bad_debt_usd": 0.0,
                "insolvent_count": 0,
                "total_reserve_usd": 0.0,
            }

        healthiest = max(results, key=lambda r: r["solvency_score"])
        most_stressed = min(results, key=lambda r: r["solvency_score"])
        total_bad_debt = round(sum(r["bad_debt_usd"] for r in results), 6)
        insolvent_count = sum(1 for r in results if r["health_label"] == "INSOLVENT")
        total_reserve = round(sum(r["reserve_fund_usd"] for r in results), 6)

        return {
            "healthiest": healthiest["name"],
            "most_stressed": most_stressed["name"],
            "total_bad_debt_usd": total_bad_debt,
            "insolvent_count": insolvent_count,
            "total_reserve_usd": total_reserve,
        }

    # ------------------------------------------------------------------
    # Atomic log write
    # ------------------------------------------------------------------

    def _append_log(self, entry: dict) -> None:
        """Ring-buffer append to data_file (max _LOG_CAP entries). Atomic write."""
        self.data_file.parent.mkdir(parents=True, exist_ok=True)

        # Load existing log
        if self.data_file.exists():
            try:
                with open(self.data_file, "r", encoding="utf-8") as fh:
                    log = json.load(fh)
                    if not isinstance(log, list):
                        log = []
            except (json.JSONDecodeError, OSError):
                log = []
        else:
            log = []

        log.append(entry)
        if len(log) > _LOG_CAP:
            log = log[-_LOG_CAP:]

        tmp = str(self.data_file) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(log, fh, indent=2)
        os.replace(tmp, str(self.data_file))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def monitor(self, protocols: list, config: dict = None) -> dict:
        """
        Monitor bad debts across DeFi lending protocols.

        Parameters
        ----------
        protocols : list of dict
            See class docstring for required fields.
        config : dict, optional
            Reserved for future configuration options.

        Returns
        -------
        dict with keys: protocols (list of analyzed results),
                        aggregates (dict), timestamp (float),
                        config (dict).
        """
        if config is None:
            config = {}

        analyzed = [self._analyze_protocol(p) for p in protocols]
        aggregates = self._compute_aggregates(analyzed)

        result = {
            "protocols": analyzed,
            "aggregates": aggregates,
            "timestamp": time.time(),
            "config": config,
        }

        # Persist log entry
        log_entry = {
            "timestamp": result["timestamp"],
            "protocol_count": len(analyzed),
            "insolvent_count": aggregates["insolvent_count"],
            "total_bad_debt_usd": aggregates["total_bad_debt_usd"],
            "total_reserve_usd": aggregates["total_reserve_usd"],
            "most_stressed": aggregates["most_stressed"],
            "summary": [
                {
                    "name": r["name"],
                    "health_label": r["health_label"],
                    "bad_debt_ratio_pct": r["bad_debt_ratio_pct"],
                    "solvency_score": r["solvency_score"],
                }
                for r in analyzed
            ],
        }
        self._append_log(log_entry)

        return result
