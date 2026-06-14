"""
MP-834 DeFiOracleRiskScorer
Advisory-only analytics module.
Scores DeFi protocols based on oracle dependencies and price feed risks.
Identifies manipulation exposure, SPOFs, and TWAP vulnerabilities.

Data log: data/oracle_risk_log.json (ring-buffer 100 entries).
Pure stdlib, read-only advisory, atomic writes.
"""

import json
import os
import time
import tempfile

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_VALID_ORACLE_TYPES = {"CHAINLINK", "UNISWAP_TWAP", "BAND", "PYTH", "INTERNAL", "NONE"}
_LOG_RING_SIZE = 100
_DEFAULT_MAX_RISK = 100

# Base risk scores by oracle type (0-40)
_BASE_RISK = {
    "CHAINLINK":    5,
    "PYTH":        10,
    "BAND":        15,
    "UNISWAP_TWAP": 20,
    "INTERNAL":    35,
    "NONE":        40,
}

# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------


def _base_risk(oracle_type: str) -> int:
    return _BASE_RISK.get(oracle_type, 40)


def _source_risk(oracle_count: int) -> int:
    if oracle_count >= 3:
        return 0
    if oracle_count == 2:
        return 5
    if oracle_count == 1:
        return 15
    return 20  # 0 sources


def _twap_risk(twap_window_minutes: int) -> int:
    if twap_window_minutes >= 60:
        return 0
    if twap_window_minutes >= 30:
        return 5
    if twap_window_minutes >= 10:
        return 10
    if twap_window_minutes > 0:
        return 15
    return 20  # no TWAP


def _safety_reduction(uses_fallback: bool, circuit_breaker: bool,
                      max_price_deviation_pct: float) -> int:
    reduction = 0
    if uses_fallback:
        reduction += 5
    if circuit_breaker:
        reduction += 5
    if max_price_deviation_pct <= 2.0:
        reduction += 5
    return reduction


def _incident_penalty(historical_incidents: int) -> int:
    return min(20, historical_incidents * 5)


def _compute_score(oracle_type: str, oracle_count: int, twap_window_minutes: int,
                   uses_fallback: bool, circuit_breaker: bool,
                   max_price_deviation_pct: float, historical_incidents: int) -> int:
    raw = (
        _base_risk(oracle_type)
        + _source_risk(oracle_count)
        + _twap_risk(twap_window_minutes)
        + _incident_penalty(historical_incidents)
        - _safety_reduction(uses_fallback, circuit_breaker, max_price_deviation_pct)
    )
    return max(0, min(100, raw))


def _oracle_grade(score: int) -> str:
    if score <= 20:
        return "A"
    if score <= 40:
        return "B"
    if score <= 60:
        return "C"
    if score <= 80:
        return "D"
    return "F"


def _manipulation_risk(score: int) -> str:
    if score <= 25:
        return "LOW"
    if score <= 50:
        return "MEDIUM"
    if score <= 75:
        return "HIGH"
    return "CRITICAL"


def _single_point_of_failure(oracle_count: int, uses_fallback: bool) -> bool:
    return oracle_count <= 1 and not uses_fallback


def _risk_factors(oracle_type: str, oracle_count: int, twap_window_minutes: int,
                  uses_fallback: bool, circuit_breaker: bool,
                  historical_incidents: int) -> list:
    factors = []
    if oracle_count <= 1:
        factors.append("Single oracle source — no redundancy")
    if not uses_fallback:
        factors.append("No fallback oracle")
    if twap_window_minutes == 0:
        factors.append("No TWAP protection")
    elif 0 < twap_window_minutes < 30:
        factors.append("Short TWAP window — flash loan vulnerable")
    if not circuit_breaker:
        factors.append("No circuit breaker")
    if historical_incidents > 0:
        factors.append(f"{historical_incidents} past oracle incident(s)")
    if oracle_type == "INTERNAL":
        factors.append("Internal oracle — centralization risk")
    if oracle_type == "NONE":
        factors.append("No oracle — relies on manual/admin")
    return factors


def _recommendations(score: int, spof: bool, twap_window_minutes: int,
                     circuit_breaker: bool) -> list:
    recs = []
    if score > 60:
        recs.append("Consider avoiding until oracle infrastructure improves")
    if spof:
        recs.append("Protocol has single oracle SPOF — use small positions only")
    if 0 < twap_window_minutes < 30:
        recs.append("Short TWAP window — vulnerable to flash loan manipulation")
    if not circuit_breaker:
        recs.append("No circuit breaker — price manipulation could cause cascading liquidations")
    return recs


# ---------------------------------------------------------------------------
# Core analyze function
# ---------------------------------------------------------------------------


def analyze(protocols: list, config: dict = None) -> dict:
    """
    Score DeFi protocols on oracle risk.

    Parameters
    ----------
    protocols : list[dict]
        Each dict: name, oracle_type, oracle_count, twap_window_minutes,
                   uses_fallback, circuit_breaker, max_price_deviation_pct,
                   historical_incidents.
    config : dict | None
        max_risk (int, default 100) — filter protocols with score > max_risk.

    Returns
    -------
    dict with scored protocol list and summary stats.
    """
    cfg = config or {}
    max_risk = int(cfg.get("max_risk", _DEFAULT_MAX_RISK))

    scored = []
    filtered_count = 0

    for proto in protocols:
        name = str(proto.get("name", ""))
        oracle_type = str(proto.get("oracle_type", "NONE"))
        oracle_count = int(proto.get("oracle_count", 0))
        twap_window = int(proto.get("twap_window_minutes", 0))
        uses_fallback = bool(proto.get("uses_fallback", False))
        circuit_breaker = bool(proto.get("circuit_breaker", False))
        max_dev = float(proto.get("max_price_deviation_pct", 100.0))
        incidents = int(proto.get("historical_incidents", 0))

        # Clamp incidents for scoring (cap at 4 → 20 pts)
        incidents_capped = min(incidents, 4)

        score = _compute_score(
            oracle_type, oracle_count, twap_window,
            uses_fallback, circuit_breaker, max_dev, incidents_capped
        )

        if score > max_risk:
            filtered_count += 1
            continue

        spof = _single_point_of_failure(oracle_count, uses_fallback)
        grade = _oracle_grade(score)
        manip = _manipulation_risk(score)
        factors = _risk_factors(
            oracle_type, oracle_count, twap_window,
            uses_fallback, circuit_breaker, incidents
        )
        recs = _recommendations(score, spof, twap_window, circuit_breaker)

        scored.append({
            "name": name,
            "oracle_type": oracle_type,
            "oracle_risk_score": score,
            "oracle_grade": grade,
            "manipulation_risk": manip,
            "single_point_of_failure": spof,
            "recommendations": recs,
            "risk_factors": factors,
        })

    # Summary
    if scored:
        safest = min(scored, key=lambda p: p["oracle_risk_score"])["name"]
        riskiest = max(scored, key=lambda p: p["oracle_risk_score"])["name"]
        average = sum(p["oracle_risk_score"] for p in scored) / len(scored)
        critical_count = sum(1 for p in scored if p["manipulation_risk"] == "CRITICAL")
    else:
        safest = None
        riskiest = None
        average = 0.0
        critical_count = 0

    return {
        "protocols": scored,
        "safest_protocol": safest,
        "riskiest_protocol": riskiest,
        "average_oracle_risk": average,
        "critical_count": critical_count,
        "filtered_count": filtered_count,
        "timestamp": time.time(),
    }


# ---------------------------------------------------------------------------
# Log persistence (ring-buffer 100)
# ---------------------------------------------------------------------------


def log_result(result: dict, data_dir: str = "data") -> None:
    """Atomically append result snapshot to ring-buffer log (max 100 entries)."""
    log_path = os.path.join(data_dir, "oracle_risk_log.json")

    try:
        with open(log_path, "r", encoding="utf-8") as fh:
            log = json.load(fh)
        if not isinstance(log, list):
            log = []
    except (FileNotFoundError, json.JSONDecodeError):
        log = []

    snapshot = {
        "timestamp": result["timestamp"],
        "protocol_count": len(result["protocols"]),
        "critical_count": result["critical_count"],
        "filtered_count": result["filtered_count"],
        "average_oracle_risk": result["average_oracle_risk"],
        "safest_protocol": result["safest_protocol"],
        "riskiest_protocol": result["riskiest_protocol"],
    }
    log.append(snapshot)

    if len(log) > _LOG_RING_SIZE:
        log = log[-_LOG_RING_SIZE:]

    os.makedirs(data_dir, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=data_dir, prefix=".oracle_risk_log_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(log, fh, indent=2)
        os.replace(tmp_path, log_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

_SAMPLE_PROTOCOLS = [
    {
        "name": "Aave V3",
        "oracle_type": "CHAINLINK",
        "oracle_count": 3,
        "twap_window_minutes": 0,
        "uses_fallback": True,
        "circuit_breaker": True,
        "max_price_deviation_pct": 1.5,
        "historical_incidents": 0,
    },
    {
        "name": "UniswapV3-Pool",
        "oracle_type": "UNISWAP_TWAP",
        "oracle_count": 1,
        "twap_window_minutes": 30,
        "uses_fallback": False,
        "circuit_breaker": False,
        "max_price_deviation_pct": 10.0,
        "historical_incidents": 1,
    },
    {
        "name": "CustomProtocol",
        "oracle_type": "INTERNAL",
        "oracle_count": 1,
        "twap_window_minutes": 0,
        "uses_fallback": False,
        "circuit_breaker": False,
        "max_price_deviation_pct": 20.0,
        "historical_incidents": 2,
    },
]


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="MP-834 DeFiOracleRiskScorer")
    parser.add_argument("--check", action="store_true",
                        help="Compute and print, no write (default)")
    parser.add_argument("--run", action="store_true",
                        help="Compute, print, and write log")
    parser.add_argument("--data-dir", default="data", help="Data directory")
    args = parser.parse_args()

    result = analyze(_SAMPLE_PROTOCOLS)

    print(f"Protocols scored  : {len(result['protocols'])}")
    print(f"Average risk      : {result['average_oracle_risk']:.1f}")
    print(f"Critical count    : {result['critical_count']}")
    print(f"Safest            : {result['safest_protocol']}")
    print(f"Riskiest          : {result['riskiest_protocol']}")
    for p in result["protocols"]:
        print(f"  {p['name']:25s} score={p['oracle_risk_score']:3d}  "
              f"grade={p['oracle_grade']}  manip={p['manipulation_risk']}")

    if args.run:
        log_result(result, data_dir=args.data_dir)
        print(f"Log written to    : {args.data_dir}/oracle_risk_log.json")
