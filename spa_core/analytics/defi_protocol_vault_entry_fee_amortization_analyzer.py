"""
MP-1188: DeFiProtocolVaultEntryFeeAmortizationAnalyzer
======================================================
Advisory/read-only analytics module.

Some vaults charge a ONE-TIME fee on principal at entry (`deposit_fee_pct`)
and/or at exit (`exit_fee_pct`) — distinct from a streaming management fee or a
performance fee on profit. A one-time round-trip fee, amortized across the
holder's intended holding horizon, lowers the effective NET APR below the quoted
headline (gross) APR. Over a 365-day horizon a 0.5% round-trip fee costs
~0.5%/yr; over a 30-day horizon the SAME fee annualizes to ~6%/yr of drag and
can erase most of a modest headline. This measures how much a one-time
entry/exit fee erodes the headline APR given YOUR horizon, the breakeven holding
period, and the net APR you would actually realize.

HIGHER score = fee drag is small relative to the headline over your horizon.

Distinct from:
  * defi_protocol_vault_gas_breakeven_analyzer / vault_round_trip_cost_analyzer
    — those are fixed GAS/trading costs in $ vs position size; THIS is the
    protocol-charged percentage deposit/withdraw fee on principal.
  * performance_fee_high_water_mark / performance_fee_crystallization_frequency
    — those are fees on PROFIT; THIS is a fee on PRINCIPAL charged once at
    entry/exit.

Pure stdlib, read-only/advisory, atomic ring-buffer log, sentinels (no inf/NaN).
"""

import json
import math
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional

# ── constants ─────────────────────────────────────────────────────────────────
LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "data", "vault_entry_fee_amortization_log.json"
)
LOG_CAP = 100

# Default holding horizon (days) when none / non-positive supplied.
DEFAULT_HOLDING_HORIZON_DAYS = 30.0

# Classification thresholds on the retained_fraction (net_apr / headline).
# retained at/above this → NEGLIGIBLE.
NEGLIGIBLE_FRACTION = 0.90
# at/above this → MILD.
MILD_FRACTION = 0.75
# at/above this → MODERATE; below (but net>0) → HEAVY; net<=0 → FEE_TRAP.
MODERATE_FRACTION = 0.55

# Flag: deposit fee is large in absolute terms.
HIGH_DEPOSIT_FEE = 1.0
# Flag: short horizon amplifies the annualized fee drag.
SHORT_HORIZON_DAYS = 14.0

# Number of days in a year used for annualization.
DAYS_PER_YEAR = 365.0


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


def _safe_div(num: float, den: float, sentinel):
    if den <= 0:
        return sentinel
    return num / den


def _build_default_cfg(overrides: Optional[dict] = None) -> dict:
    cfg = {"log_path": LOG_PATH, "log_cap": LOG_CAP}
    if overrides:
        cfg.update(overrides)
    return cfg


def _grade_from_score(score: float) -> str:
    if score >= 85:
        return "A"
    if score >= 70:
        return "B"
    if score >= 55:
        return "C"
    if score >= 40:
        return "D"
    return "F"


# ── main class ────────────────────────────────────────────────────────────────

class DeFiProtocolVaultEntryFeeAmortizationAnalyzer:
    """
    Measures how much a vault's ONE-TIME deposit/exit fee on principal erodes the
    headline (gross) APR once amortized across the holder's intended horizon.
    round_trip_fee_pct = deposit_fee_pct + exit_fee_pct is a one-time charge; its
    annualized drag = round_trip_fee_pct × (365 / horizon) — the SAME fee hurts
    much more on a short horizon. net_apr_pct = headline − annualized_fee_drag;
    retained_fraction = net / headline (clamped [0,1]). breakeven_horizon_days is
    the holding period over which the gross yield recovers the one-time fee.
    HIGHER score = the fee drag is small relative to the headline over your
    horizon. Advisory only — it does not move funds.

    Per-position input dict fields:
        vault / token          : str
        headline_apr_pct       : float gross APR; <=0 / non-finite →
                                 INSUFFICIENT_DATA.
        deposit_fee_pct        : float one-time entry fee on principal;
                                 clamp max(0,..), non-finite → 0.
        exit_fee_pct           : float one-time exit fee on principal;
                                 clamp max(0,..), non-finite → 0.
        holding_horizon_days   : float; default 30.0; <=0 / non-finite →
                                 default.
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

    # ── per-position ───────────────────────────────────────────────────────────

    def _analyze_one(self, p: dict) -> dict:
        token = p.get("vault", p.get("token", "UNKNOWN"))
        headline = _f(p.get("headline_apr_pct"))

        # Insufficient data fast-path: a non-positive / non-finite headline gives
        # nothing to amortize the fee against.
        if headline <= 0 or not math.isfinite(headline):
            return self._insufficient(token)

        deposit_fee = max(0.0, _f(p.get("deposit_fee_pct")))
        if not math.isfinite(deposit_fee):
            deposit_fee = 0.0

        exit_fee = max(0.0, _f(p.get("exit_fee_pct")))
        if not math.isfinite(exit_fee):
            exit_fee = 0.0

        horizon = max(0.0, _f(p.get("holding_horizon_days"),
                              DEFAULT_HOLDING_HORIZON_DAYS))
        if horizon <= 0 or not math.isfinite(horizon):
            horizon = DEFAULT_HOLDING_HORIZON_DAYS

        round_trip_fee = deposit_fee + exit_fee

        # Amortize the one-time fee over the horizon → annualized drag.
        annualized_fee_drag = round_trip_fee * (DAYS_PER_YEAR / horizon)
        if not math.isfinite(annualized_fee_drag):
            annualized_fee_drag = 0.0

        # Net APR may be negative; report the true value (do NOT clamp to 0).
        net_apr = headline - annualized_fee_drag
        if not math.isfinite(net_apr):
            net_apr = headline

        # retained_fraction = net / headline, clamped [0,1].
        retained_fraction = _clamp(
            _safe_div(net_apr, headline, 0.0), 0.0, 1.0)
        if not math.isfinite(retained_fraction):
            retained_fraction = 0.0

        # fee_drag_fraction = drag / headline, clamped [0,1].
        fee_drag_fraction = _clamp(
            _safe_div(annualized_fee_drag, headline, 0.0), 0.0, 1.0)
        if not math.isfinite(fee_drag_fraction):
            fee_drag_fraction = 0.0

        # breakeven_horizon_days: holding days for gross yield to recover fee.
        # = round_trip_fee_pct × 365 / headline_apr_pct. No fee → 0.0.
        if round_trip_fee <= 0:
            breakeven_horizon = 0.0
        else:
            breakeven_horizon = _safe_div(
                round_trip_fee * DAYS_PER_YEAR, headline, None)
            if breakeven_horizon is not None and not math.isfinite(
                    breakeven_horizon):
                breakeven_horizon = None

        breakeven_beyond_horizon = bool(
            breakeven_horizon is not None and breakeven_horizon > horizon)

        net_negative = bool(net_apr <= 0)
        high_deposit_fee = bool(deposit_fee >= HIGH_DEPOSIT_FEE)
        short_horizon_penalty = bool(
            horizon <= SHORT_HORIZON_DAYS and round_trip_fee > 0)

        score = self._score(retained_fraction)
        classification = self._classify(retained_fraction, net_apr)
        grade = _grade_from_score(score)
        recommendation = self._recommend(classification)
        flags = self._flags(
            classification, breakeven_beyond_horizon, high_deposit_fee,
            short_horizon_penalty, net_negative)

        return {
            "token": token,
            "headline_apr_pct": round(headline, 4),
            "deposit_fee_pct": round(deposit_fee, 4),
            "exit_fee_pct": round(exit_fee, 4),
            "round_trip_fee_pct": round(round_trip_fee, 4),
            "holding_horizon_days": round(horizon, 4),
            "annualized_fee_drag_pct": round(annualized_fee_drag, 4),
            "net_apr_pct": round(net_apr, 4),
            "retained_fraction": round(retained_fraction, 4),
            "fee_drag_fraction": round(fee_drag_fraction, 4),
            "breakeven_horizon_days": (
                round(breakeven_horizon, 4)
                if breakeven_horizon is not None else None),
            "breakeven_beyond_horizon": breakeven_beyond_horizon,
            "score": round(score, 2),
            "classification": classification,
            "recommendation": recommendation,
            "grade": grade,
            "flags": flags,
        }

    # ── scoring ────────────────────────────────────────────────────────────────

    def _score(self, retained_fraction: float) -> float:
        """
        0–100, HIGHER = less fee drag over the horizon.
          retention (100) — 100 × retained_fraction, where retained_fraction is
            net_apr / headline. A headline with no fee drag scores 100; a
            headline fully erased (or net negative) scores 0.
        """
        frac = _clamp(retained_fraction, 0.0, 1.0)
        total = 100.0 * frac
        return _clamp(total, 0.0, 100.0)

    def _classify(self, retained_fraction: float, net_apr: float) -> str:
        if net_apr <= 0:
            return "FEE_TRAP"
        frac = _clamp(retained_fraction, 0.0, 1.0)
        if frac >= NEGLIGIBLE_FRACTION:
            return "NEGLIGIBLE"
        if frac >= MILD_FRACTION:
            return "MILD"
        if frac >= MODERATE_FRACTION:
            return "MODERATE"
        return "HEAVY"

    def _recommend(self, classification: str) -> str:
        if classification == "INSUFFICIENT_DATA":
            return "VERIFY_DATA"
        if classification == "NEGLIGIBLE":
            return "NO_ACTION"
        if classification == "MILD":
            return "MONITOR"
        if classification == "MODERATE":
            return "EXTEND_HORIZON"
        if classification == "HEAVY":
            return "EXTEND_HORIZON_OR_AVOID"
        # FEE_TRAP
        return "AVOID"

    def _flags(
        self,
        classification: str,
        breakeven_beyond_horizon: bool,
        high_deposit_fee: bool,
        short_horizon_penalty: bool,
        net_negative: bool,
    ) -> List[str]:
        flags: List[str] = []

        if classification == "NEGLIGIBLE":
            flags.append("NEGLIGIBLE")
        if classification == "MILD":
            flags.append("MILD")
        if classification == "MODERATE":
            flags.append("MODERATE")
        if classification == "HEAVY":
            flags.append("HEAVY")
        if classification == "FEE_TRAP":
            flags.append("FEE_TRAP")
        if breakeven_beyond_horizon:
            flags.append("BREAKEVEN_BEYOND_HORIZON")
        if high_deposit_fee:
            flags.append("HIGH_DEPOSIT_FEE")
        if short_horizon_penalty:
            flags.append("SHORT_HORIZON_PENALTY")
        if net_negative:
            flags.append("NET_NEGATIVE")

        return flags

    def _insufficient(self, token: str) -> dict:
        return {
            "token": token,
            "headline_apr_pct": 0.0,
            "deposit_fee_pct": 0.0,
            "exit_fee_pct": 0.0,
            "round_trip_fee_pct": 0.0,
            "holding_horizon_days": round(DEFAULT_HOLDING_HORIZON_DAYS, 4),
            "annualized_fee_drag_pct": None,
            "net_apr_pct": None,
            "retained_fraction": None,
            "fee_drag_fraction": None,
            "breakeven_horizon_days": None,
            "breakeven_beyond_horizon": False,
            "score": 0.0,
            "classification": "INSUFFICIENT_DATA",
            "recommendation": "VERIFY_DATA",
            "grade": "F",
            "flags": ["INSUFFICIENT_DATA"],
        }

    # ── aggregate ────────────────────────────────────────────────────────────────

    def _aggregate(self, results: List[dict]) -> dict:
        scored = [r for r in results
                  if r["classification"] != "INSUFFICIENT_DATA"]
        if not scored:
            return {
                "lowest_fee_drag_vault": None,
                "highest_fee_drag_vault": None,
                "avg_score": 0.0,
                "fee_trap_count": 0,
                "avg_net_apr_pct": 0.0,
                "position_count": len(results),
            }
        # Higher score = less fee drag → highest score is the lowest fee drag.
        by_score = sorted(scored, key=lambda r: r["score"])
        avg = _mean([r["score"] for r in scored])
        trap = sum(
            1 for r in results
            if r["classification"] == "FEE_TRAP")
        avg_net = _mean([
            r["net_apr_pct"] for r in scored
            if isinstance(r["net_apr_pct"], (int, float))])
        return {
            "lowest_fee_drag_vault": by_score[-1]["token"],
            "highest_fee_drag_vault": by_score[0]["token"],
            "avg_score": round(avg, 2),
            "fee_trap_count": trap,
            "avg_net_apr_pct": round(avg_net, 4),
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
                    "token": r["token"],
                    "classification": r["classification"],
                    "score": r["score"],
                    "recommendation": r["recommendation"],
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
            "vault": "USDC-Vault-Negligible",
            "headline_apr_pct": 12.0,
            "deposit_fee_pct": 0.1,
            "exit_fee_pct": 0.0,
            "holding_horizon_days": 365.0,
        },
        {
            "vault": "ETH-Vault-Mild",
            "headline_apr_pct": 20.0,
            "deposit_fee_pct": 0.2,
            "exit_fee_pct": 0.0,
            "holding_horizon_days": 30.0,
        },
        {
            "vault": "ARB-Vault-Moderate",
            "headline_apr_pct": 20.0,
            "deposit_fee_pct": 0.25,
            "exit_fee_pct": 0.2,
            "holding_horizon_days": 30.0,
        },
        {
            "vault": "OP-Vault-Heavy",
            "headline_apr_pct": 18.0,
            "deposit_fee_pct": 0.5,
            "exit_fee_pct": 0.5,
            "holding_horizon_days": 30.0,
        },
        {
            "vault": "CRV-Vault-FeeTrap",
            "headline_apr_pct": 5.0,
            "deposit_fee_pct": 1.0,
            "exit_fee_pct": 1.0,
            "holding_horizon_days": 30.0,
        },
        {
            "vault": "Mystery-Vault-NoData",
            "headline_apr_pct": 0.0,
            "deposit_fee_pct": 0.5,
            "exit_fee_pct": 0.5,
            "holding_horizon_days": 30.0,
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="MP-1188 Vault Entry Fee Amortization Analyzer"
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = DeFiProtocolVaultEntryFeeAmortizationAnalyzer()
    result = analyzer.analyze_portfolio(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)
