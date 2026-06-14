"""
MP-967: DeFiLockupOpportunityCostAnalyzer

From the *allocator's* perspective: is the extra yield offered for locking capital
(vesting, fixed-term vaults, withdrawal queues, ve-locks) enough to justify giving
up liquidity? Computes the hurdle (required term premium) a locked position must
clear — illiquidity charge plus reinvestment-option value driven by rate volatility —
and compares it to the premium actually offered.

Distinct from YieldCurveSteepnessAnalyzer (term structure of *offered* yields) and
from token_vesting_tracker (tracks vesting schedules): no prior module computes the
opportunity-cost hurdle / break-even liquid APY for a lock decision (gap confirmed v7.21).

Pure stdlib, read-only/advisory, all divisions guarded, atomic tempfile+os.replace
writes, ring-buffer 100 (`data/lockup_opportunity_cost_log.json`).
"""

import json
import math
import os
import time


class DeFiLockupOpportunityCostAnalyzer:
    """
    Per-position lock-vs-stay-liquid analysis.

    Input fields (per position dict):
      name, protocol,
      locked_apy_pct              (yield offered for locking)
      liquid_alternative_apy_pct  (best comparable liquid yield)
      lock_days                   (capital lock duration)
      early_exit_available (bool), early_exit_penalty_pct
      expected_rate_volatility_pct (annualised st.dev. of liquid rates; drives option value)
      capital_usd

    Required term premium / hurdle (annualised, pp) — rises monotonically with term:
      illiquidity_charge = ILLIQUIDITY_BASE_PCT * (lock_days / 365)
      option_value       = OPTION_COEF * rate_volatility * sqrt(lock_days / 365)
      required_term_premium = illiquidity_charge + option_value
    penalty_charge (= penalty_pct / (lock_days/365)) is reported for reference and
    drives early_exit_breakeven_days, but is excluded from the base hurdle.
    """

    LOG_CAP = 100

    ILLIQUIDITY_BASE_PCT = 2.0   # pp/yr illiquidity charge for a full-year lock
    OPTION_COEF = 0.5            # weight on reinvestment-option (rate-vol) value

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

        locked_apy = float(p.get("locked_apy_pct", 0.0))
        liquid_apy = float(p.get("liquid_alternative_apy_pct", 0.0))
        lock_days = max(0.0, float(p.get("lock_days", 0.0)))
        early_exit = bool(p.get("early_exit_available", False))
        penalty_pct = max(0.0, float(p.get("early_exit_penalty_pct", 0.0)))
        rate_vol = max(0.0, float(p.get("expected_rate_volatility_pct", 0.0)))
        capital = max(0.0, float(p.get("capital_usd", 0.0)))

        lock_years = lock_days / 365.0 if lock_days > 0 else 0.0

        # ── Offered premium ──
        nominal_spread_pct = locked_apy - liquid_apy

        # ── Required term premium (the hurdle) ──
        illiquidity_charge = self.ILLIQUIDITY_BASE_PCT * lock_years
        option_value = self.OPTION_COEF * rate_vol * math.sqrt(lock_years) if lock_years > 0 else 0.0
        # The hurdle rises monotonically with lock term and rate volatility. The
        # early-exit penalty is NOT part of the base hurdle (you only pay it if you
        # unwind early) — it is reported separately and drives early_exit_breakeven_days.
        required_term_premium_pct = illiquidity_charge + option_value
        # Informational: penalty amortised over the lock term (annualised cost of an
        # early unwind), reported for reference, excluded from the hurdle above.
        if penalty_pct > 0 and lock_years > 0:
            penalty_charge = penalty_pct / lock_years
        else:
            penalty_charge = 0.0

        # ── Decision metrics ──
        excess_premium_pct = nominal_spread_pct - required_term_premium_pct
        breakeven_liquid_apy_pct = locked_apy - required_term_premium_pct

        # $ value of the flexibility surrendered over the lock term
        opportunity_cost_usd = capital * (required_term_premium_pct / 100.0) * lock_years

        # Days for the locked-yield advantage to recover an early-exit penalty
        daily_advantage = (nominal_spread_pct / 100.0) / 365.0 if nominal_spread_pct > 0 else 0.0
        if daily_advantage > 0:
            early_exit_breakeven_days = round((penalty_pct / 100.0) / daily_advantage, 2)
        else:
            early_exit_breakeven_days = None  # advantage never recovers the penalty

        lock_score = self._lock_score(excess_premium_pct, nominal_spread_pct)
        grade = self._grade(lock_score)
        classification = self._classify(excess_premium_pct, nominal_spread_pct)
        flags = self._flags(
            nominal_spread_pct, excess_premium_pct, penalty_pct,
            lock_days, early_exit, rate_vol, locked_apy, liquid_apy,
        )

        return {
            "name": name,
            "protocol": protocol,
            "locked_apy_pct": round(locked_apy, 4),
            "liquid_alternative_apy_pct": round(liquid_apy, 4),
            "lock_days": round(lock_days, 4),
            "nominal_spread_pct": round(nominal_spread_pct, 4),
            "illiquidity_charge_pct": round(illiquidity_charge, 4),
            "option_value_pct": round(option_value, 4),
            "penalty_charge_pct": round(penalty_charge, 4),
            "required_term_premium_pct": round(required_term_premium_pct, 4),
            "excess_premium_pct": round(excess_premium_pct, 4),
            "breakeven_liquid_apy_pct": round(breakeven_liquid_apy_pct, 4),
            "opportunity_cost_usd": round(opportunity_cost_usd, 2),
            "early_exit_breakeven_days": early_exit_breakeven_days,
            "lock_score": round(lock_score, 4),
            "grade": grade,
            "classification": classification,
            "flags": flags,
        }

    # ------------------------------------------------------------------ #
    # Score / grade / classification / flags
    # ------------------------------------------------------------------ #

    def _lock_score(self, excess_premium_pct: float, nominal_spread_pct: float) -> float:
        """
        50 = exactly meets the hurdle. Each +1pp of excess premium adds 12.5 points;
        each -1pp removes 12.5. A negative raw spread can't score above the hurdle line.
        """
        score = 50.0 + excess_premium_pct * 12.5
        if nominal_spread_pct < 0:
            score = min(score, 25.0)
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

    def _classify(self, excess_premium_pct: float, nominal_spread_pct: float) -> str:
        if nominal_spread_pct < 0:
            return "AVOID"
        if excess_premium_pct >= 2.0:
            return "STRONGLY_WORTH_LOCKING"
        if excess_premium_pct >= 0.5:
            return "WORTH_LOCKING"
        if excess_premium_pct >= -0.5:
            return "MARGINAL"
        return "NOT_WORTH_LOCKING"

    def _flags(
        self, nominal_spread_pct, excess_premium_pct, penalty_pct,
        lock_days, early_exit, rate_vol, locked_apy, liquid_apy,
    ) -> list:
        flags = []
        if locked_apy <= 0 and liquid_apy <= 0:
            flags.append("INSUFFICIENT_DATA")
        if nominal_spread_pct < 0:
            flags.append("NEGATIVE_SPREAD")
        if -0.5 <= excess_premium_pct < 0.5 and nominal_spread_pct >= 0:
            flags.append("INSUFFICIENT_PREMIUM")
        if excess_premium_pct >= 2.0:
            flags.append("ATTRACTIVE_PREMIUM")
        if penalty_pct >= 5.0:
            flags.append("HIGH_EXIT_PENALTY")
        if lock_days >= 365.0:
            flags.append("LONG_LOCKUP")
        if not early_exit:
            flags.append("NO_EARLY_EXIT")
        if rate_vol >= 5.0:
            flags.append("HIGH_RATE_VOLATILITY")
        return flags

    # ------------------------------------------------------------------ #
    # Aggregates
    # ------------------------------------------------------------------ #

    def _compute_aggregates(self, results: list) -> dict:
        if not results:
            return {
                "best_opportunity": None,
                "worst_opportunity": None,
                "average_excess_premium_pct": None,
                "worth_locking_count": 0,
                "avoid_count": 0,
            }

        best = max(results, key=lambda r: r["excess_premium_pct"])
        worst = min(results, key=lambda r: r["excess_premium_pct"])
        avg = sum(r["excess_premium_pct"] for r in results) / len(results)
        worth = sum(
            1 for r in results
            if r["classification"] in ("WORTH_LOCKING", "STRONGLY_WORTH_LOCKING")
        )
        avoid = sum(1 for r in results if r["classification"] == "AVOID")

        return {
            "best_opportunity": {
                "name": best["name"],
                "excess_premium_pct": best["excess_premium_pct"],
                "classification": best["classification"],
            },
            "worst_opportunity": {
                "name": worst["name"],
                "excess_premium_pct": worst["excess_premium_pct"],
                "classification": worst["classification"],
            },
            "average_excess_premium_pct": round(avg, 4),
            "worth_locking_count": worth,
            "avoid_count": avoid,
        }

    # ------------------------------------------------------------------ #
    # Ring-buffer log (atomic write)
    # ------------------------------------------------------------------ #

    def _write_log(self, result: dict, data_dir: str = "data") -> None:
        os.makedirs(data_dir, exist_ok=True)
        log_path = os.path.join(data_dir, "lockup_opportunity_cost_log.json")

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
            "average_excess_premium_pct": agg.get("average_excess_premium_pct"),
            "worth_locking_count": agg.get("worth_locking_count", 0),
            "avoid_count": agg.get("avoid_count", 0),
        })

        if len(log) > self.LOG_CAP:
            log = log[-self.LOG_CAP:]

        tmp_path = log_path + ".tmp"
        with open(tmp_path, "w") as f:
            json.dump(log, f, indent=2)
        os.replace(tmp_path, log_path)
