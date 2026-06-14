"""
MP-1030: DeFiProtocolOracleManipulationRiskAnalyzer
====================================================
Advisory-only analytics module.

Analyzes the risk of oracle price manipulation attacks on DeFi protocols.

Per oracle entry it computes:
  manipulation_feasibility_score   0-100  (HIGHER = easier/cheaper to attack)
  cost_to_attack_ratio             float  (tvl_at_risk / manipulation_cost; > 1 = profitable attack)
  oracle_quality_grade             A-F    (A = best, F = worst)
  label:
    MANIPULATION_PROOF       feasibility < 20
    WELL_PROTECTED           feasibility < 40
    MODERATE_RISK            feasibility < 60
    HIGH_RISK                feasibility < 80
    CRITICAL_VULNERABILITY   feasibility >= 80

Inputs per oracle dict:
  oracle_type                      str   chainlink | twap | spot | custom
  twap_window_seconds              float TWAP window in seconds (0 if not TWAP)
  oracle_sources_count             int   number of independent price sources
  historical_manipulation_incidents int  past confirmed manipulation events
  tvl_at_risk_usd                  float USD value a successful attack can extract
  manipulation_cost_usd_estimate   float estimated USD cost to execute the attack

Pure stdlib. Read-only / advisory. No external dependencies.
Ring-buffer log capped at 100 entries → data/oracle_manipulation_risk_log.json
Atomic writes: tmp + os.replace.
"""

from __future__ import annotations

import json
import math
import os
import tempfile
import time
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(os.path.dirname(_HERE))
LOG_PATH = os.path.join(_REPO_ROOT, "data", "oracle_manipulation_risk_log.json")
LOG_MAX_ENTRIES = 100

# Oracle type quality rankings (higher = better baseline protection)
ORACLE_TYPE_BASE_SCORE: dict[str, float] = {
    "chainlink": 15.0,   # aggregated, decentralized — best
    "twap":      30.0,   # depends on window; moderate
    "spot":      70.0,   # trivially manipulable (flash loan / sandwich)
    "custom":    50.0,   # unknown; assume moderate
}

# Label thresholds (manipulation_feasibility_score)
LABELS = [
    (0.0,  20.0, "MANIPULATION_PROOF"),
    (20.0, 40.0, "WELL_PROTECTED"),
    (40.0, 60.0, "MODERATE_RISK"),
    (60.0, 80.0, "HIGH_RISK"),
    (80.0, 101.0, "CRITICAL_VULNERABILITY"),
]

# Grade thresholds (same score → inverted: low score = good → high grade)
GRADE_THRESHOLDS = [
    (0.0,  20.0, "A"),
    (20.0, 40.0, "B"),
    (40.0, 60.0, "C"),
    (60.0, 80.0, "D"),
    (80.0, 101.0, "F"),
]

# TWAP: shorter window = easier to sustain price deviation → more risk
TWAP_STRONG_WINDOW_SECONDS = 1800.0   # 30 min → well protected
TWAP_WEAK_WINDOW_SECONDS   = 300.0    # 5 min  → risky

# Source count scoring
SOURCE_FLOOR = 1
SOURCE_STRONG = 5    # ≥5 sources → maximum diversity bonus

# Incident weight (each confirmed past incident adds risk)
INCIDENT_WEIGHT = 10.0
MAX_INCIDENT_CONTRIBUTION = 40.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def _iso_now() -> str:
    t = time.gmtime()
    return (
        f"{t.tm_year:04d}-{t.tm_mon:02d}-{t.tm_mday:02d}T"
        f"{t.tm_hour:02d}:{t.tm_min:02d}:{t.tm_sec:02d}Z"
    )


def _label(score: float) -> str:
    for lo, hi, lbl in LABELS:
        if lo <= score < hi:
            return lbl
    return "CRITICAL_VULNERABILITY"


def _grade(score: float) -> str:
    for lo, hi, g in GRADE_THRESHOLDS:
        if lo <= score < hi:
            return g
    return "F"


# ---------------------------------------------------------------------------
# Sub-score computations (public for unit testability)
# ---------------------------------------------------------------------------

def compute_oracle_type_risk(oracle_type: str) -> float:
    """
    Base risk contribution from oracle type (0-100).
    spot oracles are trivially manipulable; chainlink aggregated feeds are robust.
    """
    ot = (oracle_type or "custom").strip().lower()
    return ORACLE_TYPE_BASE_SCORE.get(ot, ORACLE_TYPE_BASE_SCORE["custom"])


def compute_twap_window_risk(oracle_type: str, twap_window_seconds: float) -> float:
    """
    Extra risk penalty for TWAP oracles based on window length (0-40).
    Non-TWAP oracles return 0 — the window is irrelevant.

    Shorter window → attacker only needs to sustain manipulation briefly → high risk.
    Window >= TWAP_STRONG_WINDOW_SECONDS → 0 additional risk.
    Window <= TWAP_WEAK_WINDOW_SECONDS   → 40 additional risk.
    """
    ot = (oracle_type or "").strip().lower()
    if ot != "twap":
        return 0.0

    w = max(0.0, float(twap_window_seconds))
    if w <= 0.0:
        # No window specified for TWAP → treat as worst case
        return 40.0
    if w >= TWAP_STRONG_WINDOW_SECONDS:
        return 0.0
    if w <= TWAP_WEAK_WINDOW_SECONDS:
        return 40.0
    # Linear interpolation between weak and strong
    ratio = (w - TWAP_WEAK_WINDOW_SECONDS) / (TWAP_STRONG_WINDOW_SECONDS - TWAP_WEAK_WINDOW_SECONDS)
    return round(40.0 * (1.0 - ratio), 4)


def compute_source_diversity_risk(oracle_sources_count: int) -> float:
    """
    Risk from insufficient price source diversity (0-30).
    1 source → 30; ≥ SOURCE_STRONG sources → 0 (linear in between).
    """
    n = max(1, int(oracle_sources_count))
    if n >= SOURCE_STRONG:
        return 0.0
    # Linear: 1 → 30, (SOURCE_STRONG-1) → ~6
    risk = 30.0 * (SOURCE_STRONG - n) / (SOURCE_STRONG - SOURCE_FLOOR)
    return round(_clamp(risk, 0.0, 30.0), 4)


def compute_incident_history_risk(historical_manipulation_incidents: int) -> float:
    """
    Risk contribution from confirmed past manipulation events (0 - MAX_INCIDENT_CONTRIBUTION).
    Each incident adds INCIDENT_WEIGHT, capped at MAX_INCIDENT_CONTRIBUTION.
    """
    n = max(0, int(historical_manipulation_incidents))
    return round(min(n * INCIDENT_WEIGHT, MAX_INCIDENT_CONTRIBUTION), 4)


def compute_cost_to_attack_ratio(tvl_at_risk_usd: float,
                                  manipulation_cost_usd_estimate: float) -> float:
    """
    ratio = tvl_at_risk / manipulation_cost.
    > 1 means the attack is profitable → higher risk.
    Returns 0.0 when cost is 0 or negative (undefined; treated as "free" attack = infinite ratio,
    clamped to a sentinel 9999.0).
    """
    tvl = max(0.0, float(tvl_at_risk_usd))
    cost = float(manipulation_cost_usd_estimate)
    if cost <= 0.0:
        return 9999.0 if tvl > 0.0 else 0.0
    return round(tvl / cost, 6)


def compute_cost_ratio_risk(cost_to_attack_ratio: float) -> float:
    """
    Translate cost_to_attack_ratio into a 0-30 risk score.
    ratio < 0.1   → 0   (extremely costly relative to gain → not worth attacking)
    ratio 0.1-1.0 → 5-15 (moderate profitability)
    ratio > 1.0   → 15-30 (attack pays for itself — linear up to ratio=10 → 30)
    """
    r = float(cost_to_attack_ratio)
    if r <= 0.0:
        return 0.0
    if r < 0.1:
        return 0.0
    if r < 1.0:
        # Linear 0→15 as ratio goes 0.1→1.0
        return round(15.0 * (r - 0.1) / 0.9, 4)
    # ratio >= 1.0: linear up to ratio=10 → max 30
    return round(_clamp(15.0 + 15.0 * min(r - 1.0, 9.0) / 9.0, 0.0, 30.0), 4)


def compute_manipulation_feasibility_score(
    oracle_type: str,
    twap_window_seconds: float,
    oracle_sources_count: int,
    historical_manipulation_incidents: int,
    tvl_at_risk_usd: float,
    manipulation_cost_usd_estimate: float,
) -> tuple[float, float]:
    """
    Compute the composite manipulation feasibility score (0-100) and cost_to_attack_ratio.

    Components (sum → clamp 0-100):
      oracle_type_risk         0-70   (base risk per oracle type)
      twap_window_risk         0-40   (extra TWAP penalty for short windows; 0 for non-TWAP)
      source_diversity_risk    0-30   (fewer sources → higher risk)
      incident_history_risk    0-40   (past incidents)
      cost_ratio_risk          0-30   (attack profitability)

    Because a spot oracle already scores 70 from oracle_type and could accumulate
    additional penalties, the total is clamped to 100.

    Returns
    -------
    (manipulation_feasibility_score, cost_to_attack_ratio)
    """
    type_risk     = compute_oracle_type_risk(oracle_type)
    twap_risk     = compute_twap_window_risk(oracle_type, twap_window_seconds)
    source_risk   = compute_source_diversity_risk(oracle_sources_count)
    incident_risk = compute_incident_history_risk(historical_manipulation_incidents)
    ratio         = compute_cost_to_attack_ratio(tvl_at_risk_usd, manipulation_cost_usd_estimate)
    cost_risk     = compute_cost_ratio_risk(ratio)

    raw = type_risk + twap_risk + source_risk + incident_risk + cost_risk
    score = round(_clamp(raw), 2)
    return score, ratio


# ---------------------------------------------------------------------------
# Single-entry analysis
# ---------------------------------------------------------------------------

def _analyze_one(entry: dict[str, Any]) -> dict[str, Any]:
    oracle_type     = str(entry.get("oracle_type", "custom"))
    twap_window     = float(entry.get("twap_window_seconds", 0.0))
    sources         = int(entry.get("oracle_sources_count", 1))
    incidents       = int(entry.get("historical_manipulation_incidents", 0))
    tvl             = float(entry.get("tvl_at_risk_usd", 0.0))
    manip_cost      = float(entry.get("manipulation_cost_usd_estimate", 0.0))

    score, ratio = compute_manipulation_feasibility_score(
        oracle_type, twap_window, sources, incidents, tvl, manip_cost
    )
    lbl   = _label(score)
    grade = _grade(score)

    return {
        "name":                            entry.get("name", "unknown"),
        "oracle_type":                     oracle_type,
        "twap_window_seconds":             twap_window,
        "oracle_sources_count":            sources,
        "historical_manipulation_incidents": incidents,
        "tvl_at_risk_usd":                 tvl,
        "manipulation_cost_usd_estimate":  manip_cost,
        "manipulation_feasibility_score":  score,
        "cost_to_attack_ratio":            ratio,
        "oracle_quality_grade":            grade,
        "label":                           lbl,
    }


# ---------------------------------------------------------------------------
# Main analyzer class
# ---------------------------------------------------------------------------

class DeFiProtocolOracleManipulationRiskAnalyzer:
    """
    Analyzes oracle price manipulation risk across DeFi protocol oracle configurations.
    Advisory / read-only. Pure stdlib. No execution side-effects.

    Usage
    -----
    analyzer = DeFiProtocolOracleManipulationRiskAnalyzer()
    result = analyzer.analyze([
        {
            "name": "Aave USDC/ETH",
            "oracle_type": "chainlink",
            "twap_window_seconds": 0,
            "oracle_sources_count": 5,
            "historical_manipulation_incidents": 0,
            "tvl_at_risk_usd": 50_000_000,
            "manipulation_cost_usd_estimate": 500_000_000,
        }
    ])
    """

    def __init__(self, log_path: Optional[str] = None) -> None:
        self.log_path: str = log_path or LOG_PATH

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self, oracles: list[dict[str, Any]],
                config: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        """
        Analyze a list of oracle configurations.

        Parameters
        ----------
        oracles : list[dict]
            Each dict may contain:
              name                              str   (optional, default 'unknown')
              oracle_type                       str   chainlink|twap|spot|custom
              twap_window_seconds               float 0 if not TWAP
              oracle_sources_count              int   ≥ 1
              historical_manipulation_incidents int   ≥ 0
              tvl_at_risk_usd                   float ≥ 0
              manipulation_cost_usd_estimate    float ≥ 0
        config : dict, optional
            log_path : str  — override log file path

        Returns
        -------
        dict with keys:
            oracles                    list[dict]   per-oracle analysis
            most_vulnerable            str | None   name of highest-risk oracle
            most_protected             str | None   name of lowest-risk oracle
            avg_feasibility_score      float
            critical_vulnerability_count int
            manipulation_proof_count   int
            analyzed_at                str          ISO UTC timestamp
        """
        if config is None:
            config = {}
        if not isinstance(oracles, list) or len(oracles) == 0:
            raise ValueError("oracles must be a non-empty list")

        results = [_analyze_one(e) for e in oracles]

        scores = [r["manipulation_feasibility_score"] for r in results]
        avg    = round(sum(scores) / len(scores), 2)

        sorted_by_score = sorted(results, key=lambda r: r["manipulation_feasibility_score"])
        most_protected  = sorted_by_score[0]["name"]
        most_vulnerable = sorted_by_score[-1]["name"]

        critical_count = sum(1 for r in results if r["label"] == "CRITICAL_VULNERABILITY")
        safe_count     = sum(1 for r in results if r["label"] == "MANIPULATION_PROOF")

        output: dict[str, Any] = {
            "oracles":                       results,
            "most_vulnerable":               most_vulnerable,
            "most_protected":                most_protected,
            "avg_feasibility_score":         avg,
            "critical_vulnerability_count":  critical_count,
            "manipulation_proof_count":      safe_count,
            "analyzed_at":                   _iso_now(),
        }

        log_path = config.get("log_path", self.log_path)
        _append_log(output, log_path)
        return output

    # ------------------------------------------------------------------
    # Convenience: single oracle
    # ------------------------------------------------------------------

    def analyze_one(self, oracle: dict[str, Any]) -> dict[str, Any]:
        """Analyze a single oracle dict without logging."""
        return _analyze_one(oracle)


# ---------------------------------------------------------------------------
# Ring-buffer log helpers
# ---------------------------------------------------------------------------

def _atomic_write(path: str, data: object) -> None:
    """Write JSON atomically using tmp + os.replace."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    dir_ = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(dir=dir_, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _init_log(path: str) -> list:
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return []


def _append_log(result: dict[str, Any], log_path: str = LOG_PATH) -> None:
    """Append a compact snapshot to the ring-buffer log."""
    entries = _init_log(log_path)
    snapshot = {
        "ts":                          result.get("analyzed_at", _iso_now()),
        "oracle_count":                len(result.get("oracles", [])),
        "avg_feasibility_score":       result.get("avg_feasibility_score"),
        "critical_vulnerability_count": result.get("critical_vulnerability_count"),
        "manipulation_proof_count":    result.get("manipulation_proof_count"),
        "most_vulnerable":             result.get("most_vulnerable"),
        "most_protected":              result.get("most_protected"),
    }
    entries.append(snapshot)
    if len(entries) > LOG_MAX_ENTRIES:
        entries = entries[-LOG_MAX_ENTRIES:]
    try:
        _atomic_write(log_path, entries)
    except OSError:
        pass  # advisory — never crash the caller on log failure


# ---------------------------------------------------------------------------
# Module-level convenience alias
# ---------------------------------------------------------------------------

def analyze(oracles: list[dict[str, Any]],
            config: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Module-level shorthand — delegates to DeFiProtocolOracleManipulationRiskAnalyzer."""
    return DeFiProtocolOracleManipulationRiskAnalyzer().analyze(oracles, config)
