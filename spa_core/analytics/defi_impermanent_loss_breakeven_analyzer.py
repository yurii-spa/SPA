"""
MP-993: DeFiImpermanentLossBreakevenAnalyzer

For a constant-product (x*y=k) liquidity position: does the fee/reward income earned
over the holding horizon offset the impermanent loss implied by an expected price
divergence? Computes IL for the expected divergence, the fee income over the horizon,
the net P&L vs simply holding, and three break-even points — the days, the divergence,
and the fee APR at which fees exactly cover IL.

Impermanent loss for constant-product AMMs, given price-ratio multiple r:
    IL(r) = 1 - 2*sqrt(r) / (1 + r)          (>= 0, symmetric: IL(r) == IL(1/r))

Distinct from concentrated_liquidity_analyzer (tick-range mechanics) and the various
yield comparators: no prior module computes IL vs fee-income break-even for an LP
position (gap confirmed v7.31).

Pure stdlib, read-only/advisory, all divisions guarded, atomic tempfile+os.replace
writes, ring-buffer 100 (`data/impermanent_loss_breakeven_log.json`).
"""

import json
import math
import os
import time


class DeFiImpermanentLossBreakevenAnalyzer:
    """
    Per-position LP fee-vs-IL break-even analysis.

    Input fields (per position dict):
      name, protocol, pair,
      fee_apr_pct                       (trading-fee yield)
      reward_apr_pct                    (incentive yield, optional)
      expected_price_divergence_pct     (expected move of one asset vs the other, e.g. 50)
      horizon_days
      position_size_usd
    """

    LOG_CAP = 100

    # Search bound for break-even divergence (price-ratio multiple).
    MAX_R = 25.0

    # ------------------------------------------------------------------ #
    # IL helper
    # ------------------------------------------------------------------ #

    @staticmethod
    def _il_fraction(r: float) -> float:
        """Impermanent loss as a positive fraction for price-ratio multiple r > 0."""
        if r <= 0:
            return 0.0
        return 1.0 - (2.0 * math.sqrt(r)) / (1.0 + r)

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
        pair = p.get("pair", "unknown")

        fee_apr = float(p.get("fee_apr_pct", 0.0))
        reward_apr = float(p.get("reward_apr_pct", 0.0))
        divergence = abs(float(p.get("expected_price_divergence_pct", 0.0)))
        horizon_days = max(0.0, float(p.get("horizon_days", 0.0)))
        size = max(0.0, float(p.get("position_size_usd", 0.0)))

        total_apr = fee_apr + reward_apr
        horizon_years = horizon_days / 365.0 if horizon_days > 0 else 0.0

        # Expected IL from the divergence.
        r = 1.0 + divergence / 100.0
        il_pct = self._il_fraction(r) * 100.0

        # Fee/reward income over the horizon.
        fee_income_pct = total_apr * horizon_years
        net_pnl_pct = fee_income_pct - il_pct

        # Break-even days: time for fee income to offset the expected IL.
        if total_apr > 0:
            breakeven_days = round((il_pct / total_apr) * 365.0, 2)
        else:
            breakeven_days = None

        # Fee APR that would offset the expected IL over the chosen horizon.
        if horizon_years > 0:
            required_fee_apr_pct = round(il_pct / horizon_years, 4)
        else:
            required_fee_apr_pct = None

        # Break-even divergence: the price move at which IL == fee income over horizon.
        breakeven_divergence_pct = self._breakeven_divergence(fee_income_pct)

        # $ figures over the horizon.
        il_usd = size * (il_pct / 100.0)
        fee_income_usd = size * (fee_income_pct / 100.0)
        net_pnl_usd = fee_income_usd - il_usd

        lp_score = self._lp_score(fee_income_pct, il_pct)
        grade = self._grade(lp_score)
        classification = self._classify(net_pnl_pct, fee_income_pct, il_pct)
        flags = self._flags(
            total_apr, divergence, horizon_days, net_pnl_pct,
            fee_income_pct, il_pct, size,
        )

        return {
            "name": name,
            "protocol": protocol,
            "pair": pair,
            "total_apr_pct": round(total_apr, 4),
            "expected_divergence_pct": round(divergence, 4),
            "il_pct": round(il_pct, 4),
            "fee_income_pct": round(fee_income_pct, 4),
            "net_pnl_pct": round(net_pnl_pct, 4),
            "breakeven_days": breakeven_days,
            "breakeven_divergence_pct": breakeven_divergence_pct,
            "required_fee_apr_pct": required_fee_apr_pct,
            "il_usd": round(il_usd, 2),
            "fee_income_usd": round(fee_income_usd, 2),
            "net_pnl_usd": round(net_pnl_usd, 2),
            "lp_score": round(lp_score, 4),
            "grade": grade,
            "classification": classification,
            "flags": flags,
        }

    def _breakeven_divergence(self, fee_income_pct: float) -> float:
        """
        Smallest price-ratio divergence (%) whose IL equals the fee income over the
        horizon. IL is monotone increasing in r>=1, so we scan upward. Returns None
        if fees can't be matched within MAX_R (i.e. IL never gets that large).
        """
        if fee_income_pct <= 0:
            return 0.0
        target = fee_income_pct / 100.0
        # IL at MAX_R is the ceiling we can represent here.
        if self._il_fraction(self.MAX_R) < target:
            return None
        lo, hi = 1.0, self.MAX_R
        for _ in range(60):  # bisection -> sub-1e-6 precision on r
            mid = (lo + hi) / 2.0
            if self._il_fraction(mid) < target:
                lo = mid
            else:
                hi = mid
        return round((hi - 1.0) * 100.0, 4)

    # ------------------------------------------------------------------ #
    # Score / grade / classification / flags
    # ------------------------------------------------------------------ #

    def _lp_score(self, fee_income_pct: float, il_pct: float) -> float:
        """
        Coverage = fee income / IL. coverage 1.0 (exact break-even) -> 50;
        coverage 2.0 (fees double the IL) -> 100. No IL with positive fees -> 100.
        """
        if il_pct <= 0:
            return 100.0 if fee_income_pct > 0 else 50.0
        coverage = fee_income_pct / il_pct
        return max(0.0, min(100.0, coverage * 50.0))

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

    def _classify(self, net_pnl_pct, fee_income_pct, il_pct) -> str:
        if fee_income_pct <= 0 and il_pct <= 0:
            return "INSUFFICIENT_DATA"
        if net_pnl_pct >= 5.0:
            return "STRONGLY_PROFITABLE"
        if net_pnl_pct >= 0.5:
            return "PROFITABLE"
        if net_pnl_pct >= -0.5:
            return "MARGINAL"
        if il_pct > fee_income_pct:
            return "IL_DOMINATED"
        return "UNPROFITABLE"

    def _flags(
        self, total_apr, divergence, horizon_days, net_pnl_pct,
        fee_income_pct, il_pct, size,
    ) -> list:
        flags = []
        if total_apr <= 0 and size <= 0:
            flags.append("INSUFFICIENT_DATA")
        if il_pct > fee_income_pct:
            flags.append("IL_EXCEEDS_FEES")
        if fee_income_pct >= il_pct and il_pct > 0:
            flags.append("FEES_COVER_IL")
        if divergence >= 50.0:
            flags.append("HIGH_DIVERGENCE")
        if 0 <= divergence < 5.0:
            flags.append("STABLE_PAIR")
        if total_apr > 0 and total_apr < 2.0:
            flags.append("THIN_FEES")
        if horizon_days >= 365.0:
            flags.append("LONG_HORIZON")
        return flags

    # ------------------------------------------------------------------ #
    # Aggregates
    # ------------------------------------------------------------------ #

    def _compute_aggregates(self, results: list) -> dict:
        if not results:
            return {
                "best_position": None,
                "worst_position": None,
                "average_net_pnl_pct": None,
                "profitable_count": 0,
                "il_dominated_count": 0,
            }

        best = max(results, key=lambda r: r["net_pnl_pct"])
        worst = min(results, key=lambda r: r["net_pnl_pct"])
        avg = sum(r["net_pnl_pct"] for r in results) / len(results)
        profitable = sum(
            1 for r in results
            if r["classification"] in ("PROFITABLE", "STRONGLY_PROFITABLE")
        )
        il_dominated = sum(1 for r in results if r["classification"] == "IL_DOMINATED")

        return {
            "best_position": {
                "name": best["name"],
                "net_pnl_pct": best["net_pnl_pct"],
                "classification": best["classification"],
            },
            "worst_position": {
                "name": worst["name"],
                "net_pnl_pct": worst["net_pnl_pct"],
                "classification": worst["classification"],
            },
            "average_net_pnl_pct": round(avg, 4),
            "profitable_count": profitable,
            "il_dominated_count": il_dominated,
        }

    # ------------------------------------------------------------------ #
    # Ring-buffer log (atomic write)
    # ------------------------------------------------------------------ #

    def _write_log(self, result: dict, data_dir: str = "data") -> None:
        os.makedirs(data_dir, exist_ok=True)
        log_path = os.path.join(data_dir, "impermanent_loss_breakeven_log.json")

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
            "average_net_pnl_pct": agg.get("average_net_pnl_pct"),
            "profitable_count": agg.get("profitable_count", 0),
            "il_dominated_count": agg.get("il_dominated_count", 0),
        })

        if len(log) > self.LOG_CAP:
            log = log[-self.LOG_CAP:]

        tmp_path = log_path + ".tmp"
        with open(tmp_path, "w") as f:
            json.dump(log, f, indent=2)
        os.replace(tmp_path, log_path)
