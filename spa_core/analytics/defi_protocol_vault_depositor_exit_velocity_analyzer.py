"""
MP-1172: DeFiProtocolVaultDepositorExitVelocityAnalyzer
=======================================================
Advisory/read-only analytics module.

Measures the VELOCITY and ACCELERATION of depositor net outflows from a vault
as an early bank-run / exit-stampede signal. The question is not "how big is
the withdrawal queue" or "how long is the lockup" — it is "is a run forming
RIGHT NOW?". A vault whose net outflows are small and steady is calm; a vault
whose outflow rate is large AND accelerating versus the prior window (and versus
its own trailing baseline) is draining and may be entering a bank run.

Angle: "net outflow was 1% of TVL yesterday, 9% today, and 4.5x the 3-day
baseline → outflows are accelerating fast, a run is forming, exit now."

HIGHER score = calmer / lower run-risk.

Distinct from:
  * defi_protocol_withdrawal_queue_risk_analyzer (Tier-A) — queue length /
    processing capacity (can the protocol service redemptions), not the rate of
    change of net outflows.
  * defi_protocol_vault_redemption_cooldown_exposure_analyzer — lockup /
    cooldown duration (how long you are trapped), not run formation.
  * exit-liquidity / NAV-discount modules — market depth and price impact on
    exit, not depositor flow velocity.
  THIS module isolates the *rate of change of net outflows* — is a run forming
  right now.

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
    "data", "vault_depositor_exit_velocity_log.json"
)
LOG_CAP = 100

# Scoring ceilings (full-penalty points).
RATE_CEILING_PCT = 25.0     # outflow rate at/above this → full rate penalty
ACCEL_CEILING_PCT = 10.0    # acceleration at/above this → full decel penalty
MULT_CEILING = 3.0          # vs-baseline multiple at/above this → full penalty

# Behaviour thresholds.
ACCEL_THRESHOLD_PCT = 1.0   # acceleration above this → "is_accelerating"
CALM_RATE_PCT = 2.0         # outflow rate above this → at least ELEVATED
ELEVATED_RATE_PCT = 8.0     # outflow rate above this → at least DRAINING
RUN_RATE_PCT = 20.0         # outflow rate above this → BANK_RUN
BASELINE_SPIKE_MULT = 2.0   # vs-baseline ratio at/above this → spike flag
RAPID_DRAIN_DAYS = 5.0      # days_to_50pct_drain at/below this → rapid-drain flag


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

class DeFiProtocolVaultDepositorExitVelocityAnalyzer:
    """
    Measures the velocity and acceleration of depositor net outflows from a
    vault as an early bank-run signal. Combines the current 24h net-outflow rate
    (as % of TVL), its acceleration versus the prior 24h window, and its size
    versus the trailing 3-day baseline into a single run-risk score.

    HIGHER score = calmer / lower run-risk.

    Per-position input dict fields:
        vault / token              : str
        tvl_usd                    : float (default 0; max(0,..)); <=0 → INSUFF.
        net_outflow_24h_usd        : float — net withdrawals last 24h
                                     (positive=outflow, negative=net inflow).
        net_outflow_prev_24h_usd   : float — net outflow in the prior 24h window.
        outflow_3d_avg_usd         : float (default 0) — avg daily net outflow
                                     over the trailing 3d (baseline).
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
        tvl_usd = max(0.0, _f(p.get("tvl_usd")))

        # Insufficient data fast-path: no TVL gives no basis for a rate.
        if tvl_usd <= 0:
            return self._insufficient(token)

        net_outflow = _f(p.get("net_outflow_24h_usd"))
        net_outflow_prev = _f(p.get("net_outflow_prev_24h_usd"))
        outflow_3d_avg = _f(p.get("outflow_3d_avg_usd"))

        outflow_rate_pct = _safe_div(net_outflow, tvl_usd, 0.0) * 100.0
        prev_outflow_rate_pct = _safe_div(net_outflow_prev, tvl_usd, 0.0) * 100.0
        acceleration_pct = outflow_rate_pct - prev_outflow_rate_pct

        acceleration_ratio = (
            _safe_div(outflow_rate_pct, prev_outflow_rate_pct, None)
            if prev_outflow_rate_pct > 0 else None
        )
        if acceleration_ratio is not None and not math.isfinite(acceleration_ratio):
            acceleration_ratio = None

        vs_baseline_ratio = (
            _safe_div(net_outflow, outflow_3d_avg, None)
            if outflow_3d_avg > 0 else None
        )
        if vs_baseline_ratio is not None and not math.isfinite(vs_baseline_ratio):
            vs_baseline_ratio = None

        days_to_50pct_drain = (
            _safe_div(0.5 * tvl_usd, net_outflow, None)
            if net_outflow > 0 else None
        )
        if (days_to_50pct_drain is not None
                and not math.isfinite(days_to_50pct_drain)):
            days_to_50pct_drain = None

        is_net_inflow = net_outflow < 0
        is_accelerating = acceleration_pct > ACCEL_THRESHOLD_PCT

        score = self._score(
            outflow_rate_pct, acceleration_pct, outflow_3d_avg, vs_baseline_ratio)
        classification = self._classify(
            outflow_rate_pct, is_accelerating, acceleration_pct)
        grade = _grade_from_score(score)
        recommendation = self._recommend(classification)
        flags = self._flags(
            classification,
            is_accelerating,
            is_net_inflow,
            vs_baseline_ratio,
            days_to_50pct_drain,
        )

        return {
            "token": token,
            "tvl_usd": round(tvl_usd, 4),
            "net_outflow_24h_usd": round(net_outflow, 4),
            "net_outflow_prev_24h_usd": round(net_outflow_prev, 4),
            "outflow_rate_pct": round(outflow_rate_pct, 4),
            "prev_outflow_rate_pct": round(prev_outflow_rate_pct, 4),
            "acceleration_pct": round(acceleration_pct, 4),
            "acceleration_ratio": (
                round(acceleration_ratio, 4)
                if acceleration_ratio is not None else None),
            "vs_baseline_ratio": (
                round(vs_baseline_ratio, 4)
                if vs_baseline_ratio is not None else None),
            "days_to_50pct_drain": (
                round(days_to_50pct_drain, 4)
                if days_to_50pct_drain is not None else None),
            "is_net_inflow": is_net_inflow,
            "is_accelerating": is_accelerating,
            "score": round(score, 2),
            "classification": classification,
            "recommendation": recommendation,
            "grade": grade,
            "flags": flags,
        }

    # ── scoring ────────────────────────────────────────────────────────────────

    def _score(
        self,
        outflow_rate_pct: float,
        acceleration_pct: float,
        outflow_3d_avg: float,
        vs_baseline_ratio,
    ) -> float:
        """
        0–100, HIGHER = calmer / lower run-risk. Components:
          rate (50) — current outflow rate vs RATE_CEILING_PCT (only positive
            outflows penalised; net inflow gets full credit).
          decel (30) — acceleration vs ACCEL_CEILING_PCT (only positive /
            accelerating outflows penalised; deceleration gets full credit).
          baseline (20) — size vs trailing 3d baseline; no baseline or a None
            ratio gives full credit; excess over 1x penalised up to MULT_CEILING.
        """
        rate_comp = 50.0 * (
            1.0 - _clamp(
                max(0.0, outflow_rate_pct) / RATE_CEILING_PCT, 0.0, 1.0))
        decel_comp = 30.0 * (
            1.0 - _clamp(
                max(0.0, acceleration_pct) / ACCEL_CEILING_PCT, 0.0, 1.0))
        if outflow_3d_avg <= 0 or vs_baseline_ratio is None:
            baseline_comp = 20.0
        else:
            excess = max(0.0, vs_baseline_ratio - 1.0)
            baseline_comp = 20.0 * (
                1.0 - _clamp(excess / (MULT_CEILING - 1.0), 0.0, 1.0))
        total = rate_comp + decel_comp + baseline_comp
        return _clamp(total, 0.0, 100.0)

    def _classify(
        self,
        outflow_rate_pct: float,
        is_accelerating: bool,
        acceleration_pct: float,
    ) -> str:
        if outflow_rate_pct > RUN_RATE_PCT:
            return "BANK_RUN"
        if (outflow_rate_pct > ELEVATED_RATE_PCT
                or (is_accelerating and acceleration_pct >= ACCEL_CEILING_PCT)):
            return "DRAINING"
        if outflow_rate_pct > CALM_RATE_PCT or is_accelerating:
            return "ELEVATED"
        return "CALM"

    def _recommend(self, classification: str) -> str:
        if classification == "INSUFFICIENT_DATA":
            return "VERIFY_DATA"
        if classification == "BANK_RUN":
            return "EXIT_NOW"
        if classification == "DRAINING":
            return "REDUCE_OR_EXIT"
        if classification == "ELEVATED":
            return "MONITOR_CLOSELY"
        # CALM
        return "HOLD"

    def _flags(
        self,
        classification: str,
        is_accelerating: bool,
        is_net_inflow: bool,
        vs_baseline_ratio,
        days_to_50pct_drain,
    ) -> List[str]:
        flags: List[str] = []

        if classification == "CALM":
            flags.append("CALM")
        if classification == "ELEVATED":
            flags.append("ELEVATED")
        if classification == "DRAINING":
            flags.append("DRAINING")
        if classification == "BANK_RUN":
            flags.append("BANK_RUN")
        if is_accelerating:
            flags.append("ACCELERATING_OUTFLOWS")
        if is_net_inflow:
            flags.append("NET_INFLOW")
        if (vs_baseline_ratio is not None
                and vs_baseline_ratio >= BASELINE_SPIKE_MULT):
            flags.append("ABOVE_BASELINE_SPIKE")
        if (days_to_50pct_drain is not None
                and days_to_50pct_drain <= RAPID_DRAIN_DAYS):
            flags.append("RAPID_DRAIN")

        return flags

    def _insufficient(self, token: str) -> dict:
        return {
            "token": token,
            "tvl_usd": 0.0,
            "net_outflow_24h_usd": 0.0,
            "net_outflow_prev_24h_usd": 0.0,
            "outflow_rate_pct": 0.0,
            "prev_outflow_rate_pct": 0.0,
            "acceleration_pct": 0.0,
            "acceleration_ratio": None,
            "vs_baseline_ratio": None,
            "days_to_50pct_drain": None,
            "is_net_inflow": False,
            "is_accelerating": False,
            "score": 0.0,
            "classification": "INSUFFICIENT_DATA",
            "recommendation": "VERIFY_DATA",
            "grade": "F",
            "flags": ["INSUFFICIENT_DATA"],
        }

    # ── aggregate ────────────────────────────────────────────────────────────────

    def _aggregate(self, results: List[dict]) -> dict:
        scored = [r for r in results if r["classification"] != "INSUFFICIENT_DATA"]
        if not scored:
            return {
                "highest_run_risk_vault": None,
                "calmest_vault": None,
                "avg_score": 0.0,
                "bank_run_count": 0,
                "position_count": len(results),
            }
        # Higher score = calmer → lowest score is highest run-risk.
        by_score = sorted(scored, key=lambda r: r["score"])
        avg = _mean([r["score"] for r in scored])
        bank_run = sum(
            1 for r in results if r["classification"] == "BANK_RUN")
        return {
            "highest_run_risk_vault": by_score[0]["token"],
            "calmest_vault": by_score[-1]["token"],
            "avg_score": round(avg, 2),
            "bank_run_count": bank_run,
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
            "vault": "USDC-Vault-Calm",
            "tvl_usd": 10_000_000.0,
            "net_outflow_24h_usd": 50_000.0,
            "net_outflow_prev_24h_usd": 40_000.0,
            "outflow_3d_avg_usd": 60_000.0,
        },
        {
            "vault": "ETH-Vault-NetInflow",
            "tvl_usd": 8_000_000.0,
            "net_outflow_24h_usd": -120_000.0,
            "net_outflow_prev_24h_usd": -50_000.0,
            "outflow_3d_avg_usd": 0.0,
        },
        {
            "vault": "ARB-Vault-Elevated",
            "tvl_usd": 5_000_000.0,
            "net_outflow_24h_usd": 250_000.0,
            "net_outflow_prev_24h_usd": 100_000.0,
            "outflow_3d_avg_usd": 120_000.0,
        },
        {
            "vault": "OP-Vault-Draining",
            "tvl_usd": 4_000_000.0,
            "net_outflow_24h_usd": 480_000.0,
            "net_outflow_prev_24h_usd": 120_000.0,
            "outflow_3d_avg_usd": 130_000.0,
        },
        {
            "vault": "DAI-Vault-BankRun",
            "tvl_usd": 3_000_000.0,
            "net_outflow_24h_usd": 900_000.0,
            "net_outflow_prev_24h_usd": 300_000.0,
            "outflow_3d_avg_usd": 150_000.0,
        },
        {
            "vault": "Mystery-Vault-NoData",
            "tvl_usd": 0.0,
            "net_outflow_24h_usd": 0.0,
            "net_outflow_prev_24h_usd": 0.0,
            "outflow_3d_avg_usd": 0.0,
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="MP-1172 Vault Depositor Exit Velocity Analyzer"
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = DeFiProtocolVaultDepositorExitVelocityAnalyzer()
    result = analyzer.analyze_portfolio(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)
