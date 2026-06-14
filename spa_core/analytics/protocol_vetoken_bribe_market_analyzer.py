"""
MP-937: ProtocolVeTokenBribeMarketAnalyzer
===========================================
Advisory-only analytics module.
Analyzes the bribe market for ve-token voting (Curve/Balancer wars and analogues).
Computes efficiency ratios, value capture scores, competitive pressure,
voter yield scores, and flags dominant/overbribed/high-APR gauges.

Pure stdlib. Read-only / advisory. No external dependencies.
Ring-buffer log capped at 100 entries → data/vetoken_bribe_market_log.json.
Atomic writes: tmp + os.replace.
"""

import json
import os
import time
import tempfile
import math
from typing import Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
    "vetoken_bribe_market_log.json",
)
LOG_MAX_ENTRIES = 100

# Efficiency label thresholds (based on briber_roi_pct)
HIGHLY_EFFICIENT_THRESHOLD = 200.0   # ROI ≥ 200%
EFFICIENT_THRESHOLD = 130.0          # ROI ≥ 130%
NEUTRAL_THRESHOLD = 100.0            # ROI ≥ 100% (break-even)
INEFFICIENT_THRESHOLD = 70.0         # ROI ≥ 70%
# Below 70% → WASTEFUL


# ---------------------------------------------------------------------------
# Validate input
# ---------------------------------------------------------------------------

def _validate_gauge(gauge: dict, idx: int) -> None:
    required = {
        "protocol",
        "gauge_name",
        "weekly_bribe_usd",
        "weekly_emissions_usd",
        "total_votes_vetoken",
        "bribe_per_vote_usd",
        "emissions_per_vote_usd",
        "voter_apr_pct",
        "briber_roi_pct",
        "vote_share_pct",
        "lock_duration_avg_days",
    }
    missing = required - set(gauge.keys())
    if missing:
        raise ValueError(f"Gauge {idx} ({gauge.get('gauge_name', '?')}) missing fields: {missing}")

    if float(gauge["weekly_bribe_usd"]) < 0:
        raise ValueError(f"Gauge {idx}: weekly_bribe_usd must be non-negative")
    if float(gauge["weekly_emissions_usd"]) < 0:
        raise ValueError(f"Gauge {idx}: weekly_emissions_usd must be non-negative")
    if float(gauge["total_votes_vetoken"]) < 0:
        raise ValueError(f"Gauge {idx}: total_votes_vetoken must be non-negative")
    if float(gauge["vote_share_pct"]) < 0 or float(gauge["vote_share_pct"]) > 100:
        raise ValueError(f"Gauge {idx}: vote_share_pct must be 0-100")
    if float(gauge["lock_duration_avg_days"]) < 0:
        raise ValueError(f"Gauge {idx}: lock_duration_avg_days must be non-negative")


# ---------------------------------------------------------------------------
# Compute per-gauge metrics
# ---------------------------------------------------------------------------

def _efficiency_label(briber_roi_pct: float) -> str:
    if briber_roi_pct >= HIGHLY_EFFICIENT_THRESHOLD:
        return "HIGHLY_EFFICIENT"
    elif briber_roi_pct >= EFFICIENT_THRESHOLD:
        return "EFFICIENT"
    elif briber_roi_pct >= NEUTRAL_THRESHOLD:
        return "NEUTRAL"
    elif briber_roi_pct >= INEFFICIENT_THRESHOLD:
        return "INEFFICIENT"
    else:
        return "WASTEFUL"


def _value_capture_score(
    briber_roi_pct: float,
    vote_share_pct: float,
    weekly_emissions_usd: float,
    weekly_bribe_usd: float,
) -> float:
    """
    Composite 0-100 score measuring how well the briber captures value.
    Components:
      - ROI component (40%): normalized to [0,100] via sigmoid around 100%
      - Vote share component (30%): vote_share_pct capped at 50%
      - Emission efficiency component (30%): emissions / (bribes + emissions) * 100
    """
    # ROI component: sigmoid centred at 150% ROI
    roi_norm = 1.0 / (1.0 + math.exp(-(briber_roi_pct - 150.0) / 50.0))
    roi_score = roi_norm * 100.0

    # Vote share component
    vote_score = min(100.0, vote_share_pct / 50.0 * 100.0)

    # Emission efficiency component
    total = weekly_bribe_usd + weekly_emissions_usd
    if total > 0:
        eff_score = weekly_emissions_usd / total * 100.0
    else:
        eff_score = 0.0

    return round(
        0.40 * roi_score + 0.30 * vote_score + 0.30 * eff_score,
        2,
    )


def _competitive_pressure(weekly_bribe_usd: float, avg_bribe_usd: float) -> float:
    """
    0-100 score: how much this gauge is competed over vs average.
    Normalized via log-scale relative to the average.
    """
    if avg_bribe_usd <= 0:
        return 0.0
    ratio = weekly_bribe_usd / avg_bribe_usd
    # log-scale: ratio 1 → 50, ratio 4 → 100, ratio 0.25 → 0
    log_r = math.log(max(ratio, 1e-9)) / math.log(4.0)
    score = 50.0 + log_r * 50.0
    return round(max(0.0, min(100.0, score)), 2)


def _voter_yield_score(voter_apr_pct: float) -> float:
    """
    0-100 score for voter APR attractiveness.
    APR ≥ 100% → 100, APR ≤ 0% → 0, linear in between scaled via sqrt.
    """
    if voter_apr_pct <= 0:
        return 0.0
    score = min(100.0, (voter_apr_pct / 100.0) ** 0.5 * 100.0)
    return round(score, 2)


def _compute_flags(gauge: dict, avg_bribe_usd: float) -> list:
    flags = []
    briber_roi = float(gauge["briber_roi_pct"])
    voter_apr = float(gauge["voter_apr_pct"])
    vote_share = float(gauge["vote_share_pct"])
    lock_days = float(gauge["lock_duration_avg_days"])
    weekly_bribe = float(gauge["weekly_bribe_usd"])

    if briber_roi < 100.0:
        flags.append("OVERBRIBED")
    if voter_apr > 50.0:
        flags.append("HIGH_VOTER_APR")
    if vote_share > 30.0:
        flags.append("DOMINANT_GAUGE")

    comp_pressure = _competitive_pressure(weekly_bribe, avg_bribe_usd)
    if comp_pressure < 20.0:
        flags.append("LOW_COMPETITION")

    if lock_days > 365.0:
        flags.append("LONG_LOCK")

    return flags


# ---------------------------------------------------------------------------
# Per-gauge analysis
# ---------------------------------------------------------------------------

def _analyze_single_gauge(
    gauge: dict, idx: int, avg_bribe_usd: float
) -> dict:
    _validate_gauge(gauge, idx)

    briber_roi = float(gauge["briber_roi_pct"])
    voter_apr = float(gauge["voter_apr_pct"])
    vote_share = float(gauge["vote_share_pct"])
    weekly_bribe = float(gauge["weekly_bribe_usd"])
    weekly_emissions = float(gauge["weekly_emissions_usd"])

    efficiency_ratio = round(briber_roi / 100.0, 4)
    label = _efficiency_label(briber_roi)

    vcs = _value_capture_score(
        briber_roi, vote_share, weekly_emissions, weekly_bribe
    )
    comp = _competitive_pressure(weekly_bribe, avg_bribe_usd)
    vys = _voter_yield_score(voter_apr)
    flags = _compute_flags(gauge, avg_bribe_usd)

    return {
        "protocol": gauge["protocol"],
        "gauge_name": gauge["gauge_name"],
        "efficiency_label": label,
        "efficiency_ratio": efficiency_ratio,
        "value_capture_score": vcs,
        "competitive_pressure": comp,
        "voter_yield_score": vys,
        "briber_roi_pct": briber_roi,
        "voter_apr_pct": voter_apr,
        "vote_share_pct": vote_share,
        "weekly_bribe_usd": weekly_bribe,
        "weekly_emissions_usd": weekly_emissions,
        "total_votes_vetoken": float(gauge["total_votes_vetoken"]),
        "bribe_per_vote_usd": float(gauge["bribe_per_vote_usd"]),
        "emissions_per_vote_usd": float(gauge["emissions_per_vote_usd"]),
        "lock_duration_avg_days": float(gauge["lock_duration_avg_days"]),
        "flags": flags,
    }


# ---------------------------------------------------------------------------
# Aggregates
# ---------------------------------------------------------------------------

def _compute_aggregates(results: list) -> dict:
    if not results:
        return {
            "most_efficient_gauge": None,
            "least_efficient_gauge": None,
            "total_weekly_bribes_usd": 0.0,
            "average_voter_apr": 0.0,
            "total_weekly_emissions_usd": 0.0,
            "average_briber_roi_pct": 0.0,
            "average_value_capture_score": 0.0,
            "overbribed_count": 0,
            "dominant_gauge_count": 0,
        }

    most_eff = max(results, key=lambda r: r["briber_roi_pct"])
    least_eff = min(results, key=lambda r: r["briber_roi_pct"])

    total_bribes = sum(r["weekly_bribe_usd"] for r in results)
    total_emissions = sum(r["weekly_emissions_usd"] for r in results)
    avg_voter_apr = sum(r["voter_apr_pct"] for r in results) / len(results)
    avg_roi = sum(r["briber_roi_pct"] for r in results) / len(results)
    avg_vcs = sum(r["value_capture_score"] for r in results) / len(results)

    overbribed_count = sum(1 for r in results if "OVERBRIBED" in r["flags"])
    dominant_count = sum(1 for r in results if "DOMINANT_GAUGE" in r["flags"])

    return {
        "most_efficient_gauge": most_eff["gauge_name"],
        "least_efficient_gauge": least_eff["gauge_name"],
        "total_weekly_bribes_usd": round(total_bribes, 4),
        "average_voter_apr": round(avg_voter_apr, 2),
        "total_weekly_emissions_usd": round(total_emissions, 4),
        "average_briber_roi_pct": round(avg_roi, 2),
        "average_value_capture_score": round(avg_vcs, 2),
        "overbribed_count": overbribed_count,
        "dominant_gauge_count": dominant_count,
    }


# ---------------------------------------------------------------------------
# Ring-buffer log
# ---------------------------------------------------------------------------

def _atomic_write(path: str, data) -> None:
    dir_ = os.path.dirname(path)
    if dir_ and not os.path.exists(dir_):
        os.makedirs(dir_, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=dir_ or ".", prefix=".tmp_")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _append_log(result: dict, log_path: str, cap: int = LOG_MAX_ENTRIES) -> None:
    try:
        if os.path.exists(log_path):
            with open(log_path, "r") as f:
                log = json.load(f)
            if not isinstance(log, list):
                log = []
        else:
            log = []
    except (json.JSONDecodeError, OSError):
        log = []

    entry = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "result": result,
    }
    log.append(entry)
    if len(log) > cap:
        log = log[-cap:]

    _atomic_write(log_path, log)


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class ProtocolVeTokenBribeMarketAnalyzer:
    """
    MP-937: Analyzes bribe market dynamics for ve-token governance.

    Evaluates gauge efficiency, briber ROI, voter APR, and competitive pressure
    in ve-token vote markets (Curve wars, Balancer wars, etc.).

    Usage:
        analyzer = ProtocolVeTokenBribeMarketAnalyzer()
        result = analyzer.analyze(gauges, config)
    """

    def __init__(self, log_path: str = LOG_PATH):
        self.log_path = log_path

    def analyze(self, gauges: list, config: dict) -> dict:
        """
        Analyze a list of gauge bribe market entries.

        Args:
            gauges: list of gauge dicts, each containing:
                - protocol (str)
                - gauge_name (str)
                - weekly_bribe_usd (float): total USD bribes this week
                - weekly_emissions_usd (float): total USD emissions this week
                - total_votes_vetoken (float): total veToken votes on gauge
                - bribe_per_vote_usd (float): USD bribed per veToken vote
                - emissions_per_vote_usd (float): USD emissions per veToken vote
                - voter_apr_pct (float): APR for voting on this gauge
                - briber_roi_pct (float): emissions received / bribes paid * 100
                - vote_share_pct (float): fraction of total votes (0-100)
                - lock_duration_avg_days (float): avg veToken lock duration
            config: dict with optional keys:
                - write_log (bool, default True)

        Returns:
            dict with 'gauges' (list of per-gauge results)
            and 'aggregates' (summary stats).
        """
        if not isinstance(gauges, list):
            raise TypeError("gauges must be a list")

        write_log = config.get("write_log", True)

        # Compute average bribe for competitive pressure normalization
        valid_bribes = []
        for g in gauges:
            try:
                bribe = float(g.get("weekly_bribe_usd", 0))
                if bribe >= 0:
                    valid_bribes.append(bribe)
            except (ValueError, TypeError):
                pass
        avg_bribe = sum(valid_bribes) / len(valid_bribes) if valid_bribes else 0.0

        gauge_results = []
        errors = []

        for i, g in enumerate(gauges):
            try:
                res = _analyze_single_gauge(g, i, avg_bribe)
                gauge_results.append(res)
            except (ValueError, KeyError, TypeError) as e:
                errors.append({
                    "gauge_name": g.get("gauge_name", f"<gauge_{i}>"),
                    "error": str(e),
                })

        aggregates = _compute_aggregates(gauge_results)

        result = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "module": "ProtocolVeTokenBribeMarketAnalyzer",
            "mp": "MP-937",
            "gauges": gauge_results,
            "aggregates": aggregates,
            "errors": errors,
            "total_analyzed": len(gauge_results),
            "total_errors": len(errors),
        }

        if write_log:
            try:
                _append_log(result, self.log_path)
            except OSError:
                pass  # advisory — never crash on log write failure

        return result
