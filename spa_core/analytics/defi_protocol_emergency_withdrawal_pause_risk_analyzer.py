"""
MP-1149: DeFiProtocolEmergencyWithdrawalPauseRiskAnalyzer
=========================================================
Advisory/read-only analytics module.

Quantifies *fund-trapping* risk from a protocol's emergency-pause / withdrawal-
gate machinery: the specific path by which a privileged operator can FREEZE
withdrawals, how long funds could be locked, who controls the switch, and the
probability-weighted opportunity cost of being trapped.

This is the "if they hit the emergency-pause button, how many days are MY funds
stuck, how likely is that, and what does the trapped capital cost me?" question.

Distinct from:
  * admin_key_control_risk → scores the BREADTH/SPEED of admin power generally
                             (mint, upgrade, rug). This module isolates the
                             withdrawal-pause TRAP path: lockup duration,
                             pause probability, emergency-exit bypass, and the
                             trapped-capital opportunity cost — a quantitative
                             exit-side metric, not a governance-breadth score.
  * withdrawal_queue_risk  → orderly queue/cooldown, not adversarial freeze.

Pure stdlib, read-only/advisory, atomic ring-buffer log, sentinels (no inf/NaN).
"""

import json
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional

# ── constants ─────────────────────────────────────────────────────────────────
LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "data", "emergency_withdrawal_pause_risk_log.json"
)
LOG_CAP = 100

# Controller centralization scores (0 = most centralized/risky, 1 = safest)
CONTROLLER_SAFETY = {
    "NONE": 1.0,        # no pause capability at all
    "DAO": 0.85,        # on-chain token vote (slow, transparent)
    "TIMELOCK": 0.7,    # timelocked multisig (delay before pause takes effect)
    "MULTISIG": 0.45,   # plain multisig
    "EOA": 0.1,         # single externally-owned account → worst
}
DEFAULT_CONTROLLER_SAFETY = 0.3   # unknown controller type

# Pause-duration thresholds (days)
PAUSE_LONG_DAYS = 7.0
PAUSE_SEVERE_DAYS = 30.0

# Pause-probability thresholds (annual %)
PROB_HIGH_PCT = 10.0
PROB_MODERATE_PCT = 3.0

# Default opportunity-cost APY for trapped capital (pct/yr) when none supplied
DEFAULT_TRAPPED_APY_PCT = 6.0

USD_SENTINEL_ZERO = 0.0


# ── helpers ───────────────────────────────────────────────────────────────────

def _f(val, default: float = 0.0) -> float:
    try:
        if val is None:
            return default
        return float(val)
    except (TypeError, ValueError):
        return default


def _clamp(val: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, val))


def _mean(values: List[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _multisig_strength(threshold_m: float, total_n: float) -> float:
    """
    0..1 multisig robustness from m-of-n. Higher m and higher n → stronger.
    A 1-of-n or m-of-1 is effectively an EOA. 4-of-7 type setups → strong.
    """
    if total_n <= 1 or threshold_m <= 0:
        return 0.0
    ratio = _clamp(threshold_m / total_n, 0.0, 1.0)
    # signers count bonus saturating around 7 signers
    size_factor = _clamp(total_n / 7.0, 0.0, 1.0)
    return _clamp(0.6 * ratio + 0.4 * size_factor, 0.0, 1.0)


def _build_default_cfg(overrides: Optional[dict] = None) -> dict:
    cfg = {"log_path": LOG_PATH, "log_cap": LOG_CAP}
    if overrides:
        cfg.update(overrides)
    return cfg


def _grade_from_safety(safety_score: float) -> str:
    if safety_score >= 85:
        return "A"
    if safety_score >= 70:
        return "B"
    if safety_score >= 55:
        return "C"
    if safety_score >= 40:
        return "D"
    return "F"


# ── main class ────────────────────────────────────────────────────────────────

class DeFiProtocolEmergencyWithdrawalPauseRiskAnalyzer:
    """
    Analyzes emergency withdrawal-pause / fund-trapping risk per position.

    Per-position input dict fields:
        protocol                   : str
        position_usd               : float
        has_pausable_withdrawals   : bool   (can withdrawals be frozen?)
        pause_controller_type      : str    NONE|DAO|TIMELOCK|MULTISIG|EOA
        multisig_threshold_m       : float  (optional, for MULTISIG/TIMELOCK)
        multisig_total_n           : float  (optional)
        unpause_timelock_hours     : float  (delay to unpause once decided)
        historical_max_pause_days  : float  (longest known/observed pause)
        annual_pause_probability_pct : float (implied prob of a pause / yr)
        emergency_exit_available   : bool   (bypass withdraw path exists?)
        assumed_apy_pct            : float  (opportunity-cost APY of trapped cap)
    """

    # ── public API ────────────────────────────────────────────────────────────

    def analyze(
        self,
        position: dict,
        cfg: Optional[dict] = None,
        write_log: bool = False,
    ) -> dict:
        cfg = _build_default_cfg(cfg)
        result = self._analyze_one(position)
        if write_log:
            self._write_log([result], self._aggregate([result]), cfg)
        return result

    def analyze_portfolio(
        self,
        positions: List[dict],
        cfg: Optional[dict] = None,
        write_log: bool = False,
    ) -> dict:
        cfg = _build_default_cfg(cfg)
        results = [self._analyze_one(p) for p in positions]
        agg = self._aggregate(results)
        if write_log:
            self._write_log(results, agg, cfg)
        return {"positions": results, "aggregate": agg}

    # ── per-position ────────────────────────────────────────────────────────────

    def _analyze_one(self, p: dict) -> dict:
        protocol = p.get("protocol", "UNKNOWN")
        position = _f(p.get("position_usd"))
        has_pausable = bool(p.get("has_pausable_withdrawals", False))
        controller = str(p.get("pause_controller_type", "") or "").upper()
        m = _f(p.get("multisig_threshold_m"))
        n = _f(p.get("multisig_total_n"))
        unpause_hours = max(0.0, _f(p.get("unpause_timelock_hours")))
        hist_pause_days = max(0.0, _f(p.get("historical_max_pause_days")))
        prob_pct = _clamp(_f(p.get("annual_pause_probability_pct")), 0.0, 100.0)
        emergency_exit = bool(p.get("emergency_exit_available", False))
        assumed_apy = _f(p.get("assumed_apy_pct"), DEFAULT_TRAPPED_APY_PCT)

        # Insufficient data: no position size to reason about
        if position <= 0:
            return self._insufficient(protocol)

        # No pause capability → negligible trap risk fast-path
        if not has_pausable:
            return self._no_pause(protocol, position)

        # ── controller centralization ───────────────────────────────────────────
        if controller in ("MULTISIG", "TIMELOCK") and n > 0:
            base = CONTROLLER_SAFETY.get(controller, DEFAULT_CONTROLLER_SAFETY)
            ms = _multisig_strength(m, n)
            # blend the type-floor with the actual m-of-n strength
            controller_safety = _clamp(0.5 * base + 0.5 * ms, 0.0, 1.0)
        elif controller in CONTROLLER_SAFETY:
            controller_safety = CONTROLLER_SAFETY[controller]
        else:
            controller_safety = DEFAULT_CONTROLLER_SAFETY
        controller_centralization_pct = round((1.0 - controller_safety) * 100.0, 2)

        # ── lockup duration ──────────────────────────────────────────────────────
        worst_case_locked_days = hist_pause_days + unpause_hours / 24.0
        expected_trapped_days_per_year = prob_pct / 100.0 * worst_case_locked_days

        # ── exposure & opportunity cost ──────────────────────────────────────────
        pausable_exposure_usd = 0.0 if emergency_exit else position
        # opportunity cost of capital that is expected to be trapped this year
        opportunity_cost_usd = (
            pausable_exposure_usd
            * (assumed_apy / 100.0)
            * (expected_trapped_days_per_year / 365.25)
        )

        # ── trap-risk score (higher = MORE risk) ─────────────────────────────────
        trap_risk_score = self._trap_risk_score(
            controller_safety, worst_case_locked_days, prob_pct, emergency_exit,
        )
        safety_score = round(_clamp(100.0 - trap_risk_score, 0.0, 100.0), 2)

        classification = self._classify(trap_risk_score)
        grade = _grade_from_safety(safety_score)
        flags = self._flags(
            controller, controller_safety, worst_case_locked_days, prob_pct,
            emergency_exit, classification,
        )

        return {
            "protocol": protocol,
            "position_usd": round(position, 2),
            "has_pausable_withdrawals": True,
            "pause_controller_type": controller or "UNKNOWN",
            "controller_centralization_pct": controller_centralization_pct,
            "worst_case_locked_days": round(worst_case_locked_days, 2),
            "expected_trapped_days_per_year": round(expected_trapped_days_per_year, 4),
            "pausable_exposure_usd": round(pausable_exposure_usd, 2),
            "opportunity_cost_usd": round(opportunity_cost_usd, 2),
            "emergency_exit_available": emergency_exit,
            "trap_risk_score": round(trap_risk_score, 2),
            "safety_score": safety_score,
            "classification": classification,
            "grade": grade,
            "flags": flags,
        }

    # ── scoring ────────────────────────────────────────────────────────────────

    def _trap_risk_score(
        self,
        controller_safety: float,
        worst_case_locked_days: float,
        prob_pct: float,
        emergency_exit: bool,
    ) -> float:
        """
        0–100, higher = more fund-trapping risk. Weighted:
          controller centralization (≈35) + lockup duration (≈30)
          + pause probability (≈25) + no-emergency-exit penalty (≈10).
        """
        centralization = 35.0 * (1.0 - controller_safety)

        # Duration — saturating: 7d → ~18, 30d → ~27, →30 cap
        duration = 30.0 * (1.0 - 1.0 / (1.0 + worst_case_locked_days / 10.0))

        probability = 25.0 * _clamp(prob_pct / 25.0, 0.0, 1.0)

        exit_penalty = 0.0 if emergency_exit else 10.0

        return _clamp(centralization + duration + probability + exit_penalty, 0.0, 100.0)

    def _classify(self, trap_risk_score: float) -> str:
        if trap_risk_score >= 70:
            return "SEVERE"
        if trap_risk_score >= 50:
            return "HIGH"
        if trap_risk_score >= 30:
            return "MODERATE"
        if trap_risk_score >= 12:
            return "LOW"
        return "NEGLIGIBLE"

    def _flags(
        self,
        controller: str,
        controller_safety: float,
        worst_case_locked_days: float,
        prob_pct: float,
        emergency_exit: bool,
        classification: str,
    ) -> List[str]:
        flags: List[str] = ["PAUSABLE_WITHDRAWALS"]

        if controller == "EOA":
            flags.append("EOA_PAUSE_CONTROLLER")
        if controller_safety >= 0.7:
            flags.append("DECENTRALIZED_PAUSE_CONTROL")
        if not emergency_exit:
            flags.append("NO_EMERGENCY_EXIT")
        else:
            flags.append("EMERGENCY_EXIT_AVAILABLE")
        if worst_case_locked_days >= PAUSE_SEVERE_DAYS:
            flags.append("SEVERE_LOCKUP_DURATION")
        elif worst_case_locked_days >= PAUSE_LONG_DAYS:
            flags.append("LONG_HISTORICAL_PAUSE")
        if prob_pct >= PROB_HIGH_PCT:
            flags.append("HIGH_PAUSE_PROBABILITY")
        if classification == "SEVERE":
            flags.append("SEVERE_TRAP_RISK")

        return flags

    def _no_pause(self, protocol: str, position: float) -> dict:
        return {
            "protocol": protocol,
            "position_usd": round(position, 2),
            "has_pausable_withdrawals": False,
            "pause_controller_type": "NONE",
            "controller_centralization_pct": 0.0,
            "worst_case_locked_days": 0.0,
            "expected_trapped_days_per_year": 0.0,
            "pausable_exposure_usd": 0.0,
            "opportunity_cost_usd": 0.0,
            "emergency_exit_available": True,
            "trap_risk_score": 0.0,
            "safety_score": 100.0,
            "classification": "NEGLIGIBLE",
            "grade": "A",
            "flags": ["NO_PAUSE_RISK"],
        }

    def _insufficient(self, protocol: str) -> dict:
        return {
            "protocol": protocol,
            "position_usd": 0.0,
            "has_pausable_withdrawals": False,
            "pause_controller_type": "UNKNOWN",
            "controller_centralization_pct": 0.0,
            "worst_case_locked_days": 0.0,
            "expected_trapped_days_per_year": 0.0,
            "pausable_exposure_usd": 0.0,
            "opportunity_cost_usd": 0.0,
            "emergency_exit_available": False,
            "trap_risk_score": 0.0,
            "safety_score": 0.0,
            "classification": "INSUFFICIENT_DATA",
            "grade": "F",
            "flags": ["INSUFFICIENT_DATA"],
        }

    # ── aggregate ────────────────────────────────────────────────────────────────

    def _aggregate(self, results: List[dict]) -> dict:
        scored = [r for r in results if r["classification"] != "INSUFFICIENT_DATA"]
        if not scored:
            return {
                "most_trap_prone_position": None,
                "least_trap_prone_position": None,
                "avg_trap_risk_score": 0.0,
                "high_trap_count": 0,
                "total_pausable_exposure_usd": 0.0,
                "position_count": len(results),
            }
        by_risk = sorted(scored, key=lambda r: r["trap_risk_score"], reverse=True)
        avg = _mean([r["trap_risk_score"] for r in scored])
        high_count = sum(
            1 for r in scored if r["classification"] in ("HIGH", "SEVERE")
        )
        total_exposure = sum(r["pausable_exposure_usd"] for r in results)
        return {
            "most_trap_prone_position": by_risk[0]["protocol"],
            "least_trap_prone_position": by_risk[-1]["protocol"],
            "avg_trap_risk_score": round(avg, 2),
            "high_trap_count": high_count,
            "total_pausable_exposure_usd": round(total_exposure, 2),
            "position_count": len(results),
        }

    # ── ring-buffer log ───────────────────────────────────────────────────────

    def _write_log(self, results: List[dict], agg: dict, cfg: dict) -> None:
        log_path = cfg["log_path"]
        cap = cfg["log_cap"]
        os.makedirs(os.path.dirname(log_path), exist_ok=True)

        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "position_count": len(results),
            "aggregate": agg,
            "snapshots": [
                {
                    "protocol": r["protocol"],
                    "classification": r["classification"],
                    "trap_risk_score": r["trap_risk_score"],
                    "pausable_exposure_usd": r["pausable_exposure_usd"],
                    "flags": r["flags"],
                }
                for r in results
            ],
        }

        log: List[dict] = []
        if os.path.exists(log_path):
            try:
                with open(log_path, "r") as fh:
                    log = json.load(fh)
                if not isinstance(log, list):
                    log = []
            except (json.JSONDecodeError, OSError):
                log = []

        log.append(entry)
        if len(log) > cap:
            log = log[-cap:]

        tmp = log_path + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(log, fh, indent=2)
        os.replace(tmp, log_path)


# ── CLI ───────────────────────────────────────────────────────────────────────

def _demo_positions() -> List[dict]:
    return [
        {
            "protocol": "BlueChipLending",
            "position_usd": 250_000.0,
            "has_pausable_withdrawals": True,
            "pause_controller_type": "TIMELOCK",
            "multisig_threshold_m": 5,
            "multisig_total_n": 9,
            "unpause_timelock_hours": 48.0,
            "historical_max_pause_days": 2.0,
            "annual_pause_probability_pct": 2.0,
            "emergency_exit_available": True,
            "assumed_apy_pct": 6.0,
        },
        {
            "protocol": "DegenVault",
            "position_usd": 100_000.0,
            "has_pausable_withdrawals": True,
            "pause_controller_type": "EOA",
            "unpause_timelock_hours": 0.0,
            "historical_max_pause_days": 21.0,
            "annual_pause_probability_pct": 15.0,
            "emergency_exit_available": False,
            "assumed_apy_pct": 12.0,
        },
        {
            "protocol": "ImmutableAMM",
            "position_usd": 50_000.0,
            "has_pausable_withdrawals": False,
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="MP-1149 Emergency Withdrawal Pause Risk Analyzer"
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = DeFiProtocolEmergencyWithdrawalPauseRiskAnalyzer()
    result = analyzer.analyze_portfolio(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)
