"""
MP-1025: ProtocolDeFiYieldCurvePositionAnalyzer
Analyzes DeFi portfolio positions relative to yield curve (duration risk).

Read-only analytics module. Writes ring-buffer log to
data/yield_curve_position_log.json (cap 100, atomic write).

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
_LOG_FILENAME = "yield_curve_position_log.json"

# Default benchmark (SOFR/RFR analog)
_DEFAULT_BENCHMARK_RATE_PCT = 5.25

# Duration thresholds (days)
_DURATION_IMMUNE_DAYS = 7
_DURATION_SHORT_DAYS = 30
_DURATION_MEDIUM_DAYS = 180

# Rate sensitivity normalization
_MAX_RATE_SENSITIVITY = 10.0       # pct: 10% sensitivity = max score
_MAX_DURATION_DAYS = 365.0         # normalize duration to 365d

# Carry / rate premium thresholds
_POSITIVE_CARRY_THRESHOLD = 2.0    # rate_premium > 2% → POSITIVE_CARRY flag
_BENCHMARK_LAGGING_THRESHOLD = 2.0 # current_rate < benchmark - 2% → BENCHMARK_LAGGING flag
_DURATION_MISMATCH_RATIO = 3.0     # lend_duration > 3× borrow_duration → DURATION_MISMATCH

# Rate shock for IRV
_RATE_SHOCK_PCT = 1.0              # 1% assumed rate shock

# Position types
_VARIABLE_TYPES = frozenset({"variable_rate_lending", "variable_rate_borrowing"})
_FIXED_LEND_TYPES = frozenset({"fixed_rate_lending"})
_FIXED_BORROW_TYPES = frozenset({"fixed_rate_borrowing"})
_LENDING_TYPES = frozenset({"fixed_rate_lending", "variable_rate_lending"})
_BORROWING_TYPES = frozenset({"fixed_rate_borrowing", "variable_rate_borrowing"})

_ALL_LABELS = frozenset({
    "DURATION_IMMUNE",
    "SHORT_DURATION",
    "MEDIUM_DURATION",
    "LONG_DURATION_RISK",
    "RATE_TRAPPED",
})

_ALL_FLAGS = frozenset({
    "REFINANCING_IMMINENT",
    "RATE_ENVIRONMENT_MISMATCH",
    "POSITIVE_CARRY",
    "DURATION_MISMATCH",
    "BENCHMARK_LAGGING",
})


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class ProtocolDeFiYieldCurvePositionAnalyzer:
    """
    Analyzes DeFi portfolio positions for duration risk, rate premium,
    carry, and interest rate variance (IRV).
    """

    def __init__(self, data_dir: str = "data") -> None:
        self.data_dir = data_dir
        self.log_path = os.path.join(data_dir, _LOG_FILENAME)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self, positions: list, config: dict) -> dict:
        """
        Analyze yield curve position risk across a list of DeFi positions.

        Args:
            positions: list[dict] — each dict describes one DeFi position.
            config:    dict — optional overrides:
                         log_enabled     (bool, default True)
                         data_dir        (str, overrides self.data_dir)
                         benchmark_rate  (float, default 5.25%)
                         rate_shock_pct  (float, default 1.0%)

        Returns:
            dict with keys: timestamp, module, mp, position_count, positions, aggregates
        """
        if not isinstance(positions, list):
            raise TypeError("positions must be a list")
        if not isinstance(config, dict):
            raise TypeError("config must be a dict")

        data_dir = config.get("data_dir", self.data_dir)
        log_enabled = config.get("log_enabled", True)
        benchmark_rate = float(config.get("benchmark_rate", _DEFAULT_BENCHMARK_RATE_PCT))
        rate_shock_pct = float(config.get("rate_shock_pct", _RATE_SHOCK_PCT))

        results = [self._analyze_position(p, benchmark_rate, rate_shock_pct) for p in positions]
        aggregates = self._compute_aggregates(results)

        output = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "module": "ProtocolDeFiYieldCurvePositionAnalyzer",
            "mp": "MP-1025",
            "position_count": len(results),
            "benchmark_rate_pct": benchmark_rate,
            "rate_shock_pct": rate_shock_pct,
            "positions": results,
            "aggregates": aggregates,
        }

        if log_enabled:
            self._append_log(output, data_dir)

        return output

    # ------------------------------------------------------------------
    # Per-position analysis
    # ------------------------------------------------------------------

    def _analyze_position(self, position: dict, benchmark_rate: float, rate_shock_pct: float) -> dict:
        name = position.get("name", "unknown")
        protocol = position.get("protocol", "")
        position_type = position.get("position_type", "variable_rate_lending")
        effective_duration_days = float(position.get("effective_duration_days", 1.0))
        rate_sensitivity_pct = float(position.get("rate_sensitivity_pct", 0.0))
        current_rate_pct = float(position.get("current_rate_pct", 0.0))
        pos_benchmark = float(position.get("benchmark_rate_pct", benchmark_rate))
        rate_environment = position.get("rate_environment", "stable")
        notional_value_usd = float(position.get("notional_value_usd", 0.0))
        collateral_posted_usd = float(position.get("collateral_posted_usd", 0.0))
        refinancing_risk = bool(position.get("refinancing_risk", False))

        # Core metrics
        duration_risk_score = self._compute_duration_risk_score(
            effective_duration_days, rate_sensitivity_pct
        )
        rate_premium_pct = current_rate_pct - pos_benchmark
        carry_score = self._compute_carry_score(rate_premium_pct, position_type)
        irv_usd = self._compute_irv_usd(notional_value_usd, rate_sensitivity_pct, rate_shock_pct)

        label = self._determine_label(
            effective_duration_days, rate_sensitivity_pct, position_type, rate_environment
        )
        flags = self._compute_flags(
            refinancing_risk, position_type, rate_environment,
            rate_premium_pct, effective_duration_days, current_rate_pct, pos_benchmark
        )

        return {
            "name": name,
            "protocol": protocol,
            "position_type": position_type,
            "effective_duration_days": effective_duration_days,
            "rate_sensitivity_pct": rate_sensitivity_pct,
            "current_rate_pct": current_rate_pct,
            "benchmark_rate_pct": pos_benchmark,
            "rate_environment": rate_environment,
            "notional_value_usd": notional_value_usd,
            "collateral_posted_usd": collateral_posted_usd,
            "refinancing_risk": refinancing_risk,
            "duration_risk_score": round(duration_risk_score, 2),
            "rate_premium_pct": round(rate_premium_pct, 4),
            "carry_score": round(carry_score, 2),
            "interest_rate_var_usd": round(irv_usd, 2),
            "label": label,
            "flags": flags,
        }

    # ------------------------------------------------------------------
    # Metric computation
    # ------------------------------------------------------------------

    def _compute_duration_risk_score(
        self, effective_duration_days: float, rate_sensitivity_pct: float
    ) -> float:
        """
        Duration risk score 0-100.
        Combines effective duration (normalized to 365d) and rate sensitivity (normalized to 10%).
        """
        duration_norm = min(1.0, effective_duration_days / _MAX_DURATION_DAYS)
        sensitivity_norm = min(1.0, abs(rate_sensitivity_pct) / _MAX_RATE_SENSITIVITY)
        score = (duration_norm * 0.55 + sensitivity_norm * 0.45) * 100.0
        return min(100.0, max(0.0, score))

    def _compute_carry_score(self, rate_premium_pct: float, position_type: str) -> float:
        """
        Carry score 0-100.
        Lending positions with positive premium (current > benchmark) score high.
        Borrowing positions with negative premium score high (borrowing below benchmark).
        """
        if position_type in _LENDING_TYPES:
            # Positive carry for lending = current > benchmark
            # rate_premium_pct = current - benchmark; +5% → score 100
            normalized = min(1.0, max(0.0, (rate_premium_pct + 5.0) / 10.0))
        elif position_type in _BORROWING_TYPES:
            # Good carry for borrowing = borrowing below benchmark (negative premium)
            # negative rate_premium → good; capped at ±5%
            normalized = min(1.0, max(0.0, (-rate_premium_pct + 5.0) / 10.0))
        else:
            # LP / staking: symmetric, neutral carry at 50
            normalized = min(1.0, max(0.0, (rate_premium_pct + 5.0) / 10.0))
        return normalized * 100.0

    def _compute_irv_usd(
        self, notional_value_usd: float, rate_sensitivity_pct: float, rate_shock_pct: float
    ) -> float:
        """
        Interest Rate Variance (IRV) in USD.
        = notional_value × (rate_sensitivity_pct / 100) × (rate_shock_pct / 100) × 100
        Simplified: notional × rate_sensitivity_pct × rate_shock_pct / 100
        """
        return abs(notional_value_usd * rate_sensitivity_pct * rate_shock_pct / 100.0)

    # ------------------------------------------------------------------
    # Label
    # ------------------------------------------------------------------

    def _determine_label(
        self,
        effective_duration_days: float,
        rate_sensitivity_pct: float,
        position_type: str,
        rate_environment: str,
    ) -> str:
        """
        DURATION_IMMUNE  — duration < 7d AND variable rate type
        SHORT_DURATION   — duration ≤ 30d
        MEDIUM_DURATION  — duration ≤ 180d
        LONG_DURATION_RISK — duration > 180d AND rate_sensitive (sensitivity > 2%)
        RATE_TRAPPED     — fixed_rate AND rates_rising
        """
        is_variable = position_type in _VARIABLE_TYPES
        is_fixed = position_type in (_FIXED_LEND_TYPES | _FIXED_BORROW_TYPES)
        is_rate_sensitive = abs(rate_sensitivity_pct) > 2.0

        if effective_duration_days < _DURATION_IMMUNE_DAYS and is_variable:
            return "DURATION_IMMUNE"
        if is_fixed and rate_environment == "rising":
            return "RATE_TRAPPED"
        if effective_duration_days > _DURATION_MEDIUM_DAYS and is_rate_sensitive:
            return "LONG_DURATION_RISK"
        if effective_duration_days <= _DURATION_SHORT_DAYS:
            return "SHORT_DURATION"
        return "MEDIUM_DURATION"

    # ------------------------------------------------------------------
    # Flags
    # ------------------------------------------------------------------

    def _compute_flags(
        self,
        refinancing_risk: bool,
        position_type: str,
        rate_environment: str,
        rate_premium_pct: float,
        effective_duration_days: float,
        current_rate_pct: float,
        benchmark_rate_pct: float,
    ) -> list:
        flags = []

        if refinancing_risk:
            flags.append("REFINANCING_IMMINENT")

        # RATE_ENVIRONMENT_MISMATCH:
        # fixed_borrow AND rates_falling → locked into high borrowing cost
        # fixed_lend AND rates_rising → locked into low lending yield
        is_fixed_borrow = position_type in _FIXED_BORROW_TYPES
        is_fixed_lend = position_type in _FIXED_LEND_TYPES
        if (is_fixed_borrow and rate_environment == "falling") or \
           (is_fixed_lend and rate_environment == "rising"):
            flags.append("RATE_ENVIRONMENT_MISMATCH")

        if rate_premium_pct > _POSITIVE_CARRY_THRESHOLD:
            flags.append("POSITIVE_CARRY")

        # DURATION_MISMATCH: only meaningful for lending positions with long duration
        # detected at portfolio level; here we mark if duration is very long vs. short borrow
        # For individual positions, flag if lending duration is very long (>3× medium)
        if position_type in _LENDING_TYPES and effective_duration_days > _DURATION_MEDIUM_DAYS * _DURATION_MISMATCH_RATIO:
            flags.append("DURATION_MISMATCH")

        # BENCHMARK_LAGGING: current_rate < benchmark - 2%
        if current_rate_pct < (benchmark_rate_pct - _BENCHMARK_LAGGING_THRESHOLD):
            flags.append("BENCHMARK_LAGGING")

        return flags

    # ------------------------------------------------------------------
    # Aggregates
    # ------------------------------------------------------------------

    def _compute_aggregates(self, results: list) -> dict:
        if not results:
            return {
                "highest_duration_risk": None,
                "lowest_risk": None,
                "total_irv_usd": 0.0,
                "portfolio_duration_days": 0.0,
                "rate_trapped_count": 0,
                "duration_immune_count": 0,
            }

        scores = [(r["name"], r["duration_risk_score"]) for r in results]
        highest_duration_risk = max(scores, key=lambda x: x[1])[0]
        lowest_risk = min(scores, key=lambda x: x[1])[0]

        total_irv = sum(r["interest_rate_var_usd"] for r in results)

        # Portfolio duration: weighted average by notional_value_usd
        total_notional = sum(r["notional_value_usd"] for r in results)
        if total_notional > 0:
            portfolio_duration = sum(
                r["effective_duration_days"] * r["notional_value_usd"]
                for r in results
            ) / total_notional
        else:
            portfolio_duration = 0.0

        rate_trapped = sum(1 for r in results if r["label"] == "RATE_TRAPPED")
        duration_immune = sum(1 for r in results if r["label"] == "DURATION_IMMUNE")

        return {
            "highest_duration_risk": highest_duration_risk,
            "lowest_risk": lowest_risk,
            "total_irv_usd": round(total_irv, 2),
            "portfolio_duration_days": round(portfolio_duration, 2),
            "rate_trapped_count": rate_trapped,
            "duration_immune_count": duration_immune,
        }

    # ------------------------------------------------------------------
    # Ring-buffer log (atomic write)
    # ------------------------------------------------------------------

    def _append_log(self, entry: dict, data_dir: str) -> None:
        log_path = os.path.join(data_dir, _LOG_FILENAME)
        os.makedirs(data_dir, exist_ok=True)

        try:
            with open(log_path, "r", encoding="utf-8") as fh:
                log = json.load(fh)
            if not isinstance(log, list):
                log = []
        except (FileNotFoundError, json.JSONDecodeError):
            log = []

        log.append(entry)
        if len(log) > LOG_CAP:
            log = log[-LOG_CAP:]

        tmp_path = log_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(log, fh, indent=2)
        os.replace(tmp_path, log_path)
