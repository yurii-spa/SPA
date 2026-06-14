"""
MP-992: DeFiGasCostYieldDragAnalyzer

Quantifies how transaction (gas) costs drag on a yield position's *net* return and
the minimum economical position size below which a strategy stops being profitable.

A high headline APY can be entirely consumed by gas on small positions or on L1:
entry + exit are one-time costs amortised over the holding period, while
harvest/compound transactions recur. This module nets all of that against the gross
APY and reports the break-even position size (gas is fixed in USD per tx, so the drag
shrinks as the position grows).

Distinct from compounding_strategy_selector / defi_reward_harvesting_optimizer (which
choose *when/how often* to compound): no prior module computes gas-drag on net APY or
the minimum economical position size (gap confirmed v7.31).

Pure stdlib, read-only/advisory, all divisions guarded, atomic tempfile+os.replace
writes, ring-buffer 100 (`data/gas_cost_yield_drag_log.json`).
"""

import json
import os
import time


class DeFiGasCostYieldDragAnalyzer:
    """
    Per-position gas-drag / net-yield analysis.

    Input fields (per position dict):
      name, protocol, chain,
      gross_apy_pct              (headline yield before gas)
      position_size_usd
      entry_gas_usd, exit_gas_usd   (one-time, amortised over holding period)
      harvest_gas_usd, harvests_per_year   (recurring compound/claim cost)
      holding_days
    """

    LOG_CAP = 100

    # Drag-ratio classification thresholds (gas_drag / gross_apy)
    NEGLIGIBLE = 0.05
    LOW = 0.15
    MODERATE = 0.35

    L1_CHAINS = {"ethereum", "mainnet", "eth", "l1"}

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def analyze(self, positions: list, config: dict = None) -> dict:
        if config is None:
            config = {}

        results = [self._analyze_one(p) for p in positions]
        aggregates = self._compute_aggregates(results)

        output = {
            "positions": results,
            "aggregates": aggregates,
            "position_count": len(results),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }

        if config.get("write_log", False):
            self._write_log(output, config.get("data_dir", "data"))

        return output

    # ------------------------------------------------------------------ #
    # Per-position analysis
    # ------------------------------------------------------------------ #

    def _analyze_one(self, p: dict) -> dict:
        name = p.get("name", "unknown")
        protocol = p.get("protocol", "unknown")
        chain = str(p.get("chain", "unknown")).lower()

        gross_apy = float(p.get("gross_apy_pct", 0.0))
        size = max(0.0, float(p.get("position_size_usd", 0.0)))
        entry_gas = max(0.0, float(p.get("entry_gas_usd", 0.0)))
        exit_gas = max(0.0, float(p.get("exit_gas_usd", 0.0)))
        harvest_gas = max(0.0, float(p.get("harvest_gas_usd", 0.0)))
        harvests = max(0.0, float(p.get("harvests_per_year", 0.0)))
        holding_days = max(0.0, float(p.get("holding_days", 0.0)))

        holding_years = holding_days / 365.0 if holding_days > 0 else 0.0

        one_time_gas = entry_gas + exit_gas
        recurring_gas = harvest_gas * harvests
        # Amortise the one-time entry+exit over the holding period (annualised).
        annualized_one_time = one_time_gas / holding_years if holding_years > 0 else one_time_gas
        total_annual_gas_usd = recurring_gas + annualized_one_time

        gas_drag_pct = (total_annual_gas_usd / size) * 100.0 if size > 0 else 0.0
        net_apy_pct = gross_apy - gas_drag_pct

        # Gas is fixed per tx, so the break-even size is where drag == gross APY.
        if gross_apy > 0:
            breakeven_position_usd = total_annual_gas_usd / (gross_apy / 100.0)
        else:
            breakeven_position_usd = None

        # Realised P&L over the actual holding period.
        gross_profit_usd = size * (gross_apy / 100.0) * holding_years
        total_gas_over_holding = one_time_gas + recurring_gas * holding_years
        net_profit_usd = gross_profit_usd - total_gas_over_holding

        drag_ratio = (gas_drag_pct / gross_apy) if gross_apy > 0 else None
        drag_score = self._drag_score(net_apy_pct, gross_apy)
        grade = self._grade(drag_score)
        classification = self._classify(net_apy_pct, drag_ratio, gross_apy)
        flags = self._flags(
            gross_apy, size, net_apy_pct, drag_ratio, harvests,
            breakeven_position_usd, chain, one_time_gas,
        )

        return {
            "name": name,
            "protocol": protocol,
            "chain": chain,
            "gross_apy_pct": round(gross_apy, 4),
            "position_size_usd": round(size, 2),
            "total_annual_gas_usd": round(total_annual_gas_usd, 2),
            "gas_drag_pct": round(gas_drag_pct, 4),
            "net_apy_pct": round(net_apy_pct, 4),
            "breakeven_position_usd": (
                round(breakeven_position_usd, 2) if breakeven_position_usd is not None else None
            ),
            "gross_profit_usd": round(gross_profit_usd, 2),
            "net_profit_usd": round(net_profit_usd, 2),
            "drag_ratio": round(drag_ratio, 4) if drag_ratio is not None else None,
            "drag_score": round(drag_score, 4),
            "grade": grade,
            "classification": classification,
            "flags": flags,
        }

    # ------------------------------------------------------------------ #
    # Score / grade / classification / flags
    # ------------------------------------------------------------------ #

    def _drag_score(self, net_apy_pct: float, gross_apy: float) -> float:
        """100 = zero gas drag; 0 = gas eats the entire (or more than the) yield."""
        if gross_apy <= 0:
            return 0.0
        score = 100.0 * (net_apy_pct / gross_apy)
        return max(0.0, min(100.0, score))

    def _grade(self, score: float) -> str:
        if score >= 90.0:
            return "A"
        if score >= 75.0:
            return "B"
        if score >= 60.0:
            return "C"
        if score >= 45.0:
            return "D"
        return "F"

    def _classify(self, net_apy_pct, drag_ratio, gross_apy) -> str:
        if gross_apy <= 0:
            return "UNPROFITABLE"
        if net_apy_pct <= 0:
            return "UNPROFITABLE"
        if drag_ratio is None:
            return "MODERATE_DRAG"
        if drag_ratio < self.NEGLIGIBLE:
            return "NEGLIGIBLE_DRAG"
        if drag_ratio < self.LOW:
            return "LOW_DRAG"
        if drag_ratio < self.MODERATE:
            return "MODERATE_DRAG"
        return "HIGH_DRAG"

    def _flags(
        self, gross_apy, size, net_apy_pct, drag_ratio, harvests,
        breakeven_position_usd, chain, one_time_gas,
    ) -> list:
        flags = []
        if gross_apy <= 0 or size <= 0:
            flags.append("INSUFFICIENT_DATA")
        if net_apy_pct < 0:
            flags.append("NEGATIVE_NET_YIELD")
        if breakeven_position_usd is not None and size < breakeven_position_usd:
            flags.append("BELOW_BREAKEVEN")
        if drag_ratio is not None and drag_ratio >= self.MODERATE:
            flags.append("HIGH_GAS_DRAG")
        if harvests >= 52:
            flags.append("EXCESSIVE_HARVESTING")
        if 0 < size < 1000:
            flags.append("TINY_POSITION")
        if chain in self.L1_CHAINS and one_time_gas > 50:
            flags.append("L1_EXPENSIVE")
        return flags

    # ------------------------------------------------------------------ #
    # Aggregates
    # ------------------------------------------------------------------ #

    def _compute_aggregates(self, results: list) -> dict:
        if not results:
            return {
                "best_net_yield": None,
                "worst_net_yield": None,
                "highest_drag_position": None,
                "average_gas_drag_pct": None,
                "below_breakeven_count": 0,
                "unprofitable_count": 0,
            }

        best = max(results, key=lambda r: r["net_apy_pct"])
        worst = min(results, key=lambda r: r["net_apy_pct"])
        highest_drag = max(results, key=lambda r: r["gas_drag_pct"])
        avg_drag = sum(r["gas_drag_pct"] for r in results) / len(results)
        below_be = sum(1 for r in results if "BELOW_BREAKEVEN" in r["flags"])
        unprofitable = sum(1 for r in results if r["classification"] == "UNPROFITABLE")

        return {
            "best_net_yield": {
                "name": best["name"],
                "net_apy_pct": best["net_apy_pct"],
                "classification": best["classification"],
            },
            "worst_net_yield": {
                "name": worst["name"],
                "net_apy_pct": worst["net_apy_pct"],
                "classification": worst["classification"],
            },
            "highest_drag_position": {
                "name": highest_drag["name"],
                "gas_drag_pct": highest_drag["gas_drag_pct"],
            },
            "average_gas_drag_pct": round(avg_drag, 4),
            "below_breakeven_count": below_be,
            "unprofitable_count": unprofitable,
        }

    # ------------------------------------------------------------------ #
    # Ring-buffer log (atomic write)
    # ------------------------------------------------------------------ #

    def _write_log(self, result: dict, data_dir: str = "data") -> None:
        os.makedirs(data_dir, exist_ok=True)
        log_path = os.path.join(data_dir, "gas_cost_yield_drag_log.json")

        try:
            with open(log_path, "r") as f:
                log = json.load(f)
            if not isinstance(log, list):
                log = []
        except (FileNotFoundError, json.JSONDecodeError):
            log = []

        agg = result.get("aggregates", {})
        log.append({
            "timestamp": result.get("timestamp", ""),
            "position_count": result.get("position_count", 0),
            "average_gas_drag_pct": agg.get("average_gas_drag_pct"),
            "below_breakeven_count": agg.get("below_breakeven_count", 0),
            "unprofitable_count": agg.get("unprofitable_count", 0),
        })

        if len(log) > self.LOG_CAP:
            log = log[-self.LOG_CAP:]

        tmp_path = log_path + ".tmp"
        with open(tmp_path, "w") as f:
            json.dump(log, f, indent=2)
        os.replace(tmp_path, log_path)
