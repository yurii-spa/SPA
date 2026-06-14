"""
MP-1125: ProtocolDeFiGovernanceAttackSurfaceAnalyzer
=====================================================
Advisory-only analytics module. Pure stdlib. Read-only / no external deps.

Analyzes governance attack surface — how easy it is for a malicious actor to
take over a protocol through governance. Protocols with low quorum thresholds,
short timelocks, and concentrated token ownership are highly vulnerable.

Inputs
------
total_token_supply        float  Total governance token supply
top_10_holders_pct        float  % of tokens held by top-10 addresses (0-100)
quorum_threshold_pct      float  % of total supply needed for quorum (e.g. 4.0)
timelock_hours            float  Delay between vote passing and execution
vote_duration_hours       float  How long the voting period lasts
has_multisig_override     bool   Emergency multisig exists
token_price_usd           float  Token price in USD
protocol_tvl_usd          float  TVL in USD
protocol_name             str

Outputs (all returned in a dict from .analyze())
------------------------------------------------
tokens_to_attack_pct      float  quorum_threshold_pct / 2 + 0.01
                                 (majority of quorum — just enough to control outcome)
attack_cost_usd           float  tokens_to_attack_pct/100 * total_token_supply
                                 * token_price_usd
attack_cost_to_tvl_ratio  float  attack_cost_usd / protocol_tvl_usd
                                 (0.0 if tvl <= 0)
concentration_risk_score  int 0-40
                          top_10_holders_pct > 66 → 40
                          top_10_holders_pct > 50 → 30
                          top_10_holders_pct > 33 → 20
                          top_10_holders_pct > 20 → 10
                          else                    → 0
timelock_safety_score     int 0-30
                          timelock_hours >= 168 → 30
                          timelock_hours >= 72  → 20
                          timelock_hours >= 24  → 10
                          timelock_hours >= 6   → 5
                          else                  → 0
governance_attack_score   int 0-100 (100=most vulnerable)
                          = concentration_risk_score
                            + (30 - timelock_safety_score)   [low timelock penalty]
                            + low_quorum_penalty             [low quorum penalty]
                          clamped [0, 100]

                          low_quorum_penalty:
                            quorum_threshold_pct <  2.0 → 30
                            quorum_threshold_pct <  5.0 → 20
                            quorum_threshold_pct < 15.0 → 10
                            else                        → 0

governance_label          str
  <= 15 → FORTRESS_GOVERNANCE
  <= 35 → STRONG_GOVERNANCE
  <= 55 → ADEQUATE_GOVERNANCE
  <= 75 → WEAK_GOVERNANCE
  > 75  → GOVERNANCE_EXPLOIT_RISK

Ring-buffer log (100 entries max) → data/governance_attack_surface_log.json
Atomic writes: tmp + os.replace
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(os.path.dirname(_HERE))

LOG_FILENAME = "governance_attack_surface_log.json"
LOG_MAX_ENTRIES = 100
SCHEMA_VERSION = 1
MODULE_TAG = "MP-1125"

# Label thresholds — (upper_bound_inclusive, label)
_GOVERNANCE_LABELS = [
    (15,  "FORTRESS_GOVERNANCE"),
    (35,  "STRONG_GOVERNANCE"),
    (55,  "ADEQUATE_GOVERNANCE"),
    (75,  "WEAK_GOVERNANCE"),
    (100, "GOVERNANCE_EXPLOIT_RISK"),
]

# Concentration thresholds (descending order)
_CONCENTRATION_TIERS = [
    (66.0, 40),
    (50.0, 30),
    (33.0, 20),
    (20.0, 10),
]

# Timelock thresholds (descending order: hours, score)
_TIMELOCK_TIERS = [
    (168.0, 30),
    (72.0,  20),
    (24.0,  10),
    (6.0,    5),
]

# Quorum penalty thresholds (ascending quorum → lower penalty)
_QUORUM_PENALTY_TIERS = [
    (2.0,  30),
    (5.0,  20),
    (15.0, 10),
]

TIMELOCK_MAX_SAFETY_SCORE = 30


# ---------------------------------------------------------------------------
# Pure computation helpers (importable for unit testing)
# ---------------------------------------------------------------------------

def compute_tokens_to_attack_pct(quorum_threshold_pct: float) -> float:
    """Minimum token % to control quorum outcome: quorum/2 + 0.01."""
    return quorum_threshold_pct / 2.0 + 0.01


def compute_attack_cost_usd(
    tokens_to_attack_pct: float,
    total_token_supply: float,
    token_price_usd: float,
) -> float:
    """Cost to acquire tokens_to_attack_pct% of supply at market price."""
    return (tokens_to_attack_pct / 100.0) * total_token_supply * token_price_usd


def compute_attack_cost_to_tvl_ratio(
    attack_cost_usd: float,
    protocol_tvl_usd: float,
) -> float:
    """attack_cost_usd / protocol_tvl_usd. Returns 0.0 when tvl <= 0."""
    if protocol_tvl_usd <= 0.0:
        return 0.0
    return attack_cost_usd / protocol_tvl_usd


def compute_concentration_risk_score(top_10_holders_pct: float) -> int:
    """0-40 score based on token concentration among top-10 holders."""
    for threshold, score in _CONCENTRATION_TIERS:
        if top_10_holders_pct > threshold:
            return score
    return 0


def compute_timelock_safety_score(timelock_hours: float) -> int:
    """0-30 score (higher = safer) based on timelock duration."""
    for min_hours, score in _TIMELOCK_TIERS:
        if timelock_hours >= min_hours:
            return score
    return 0


def compute_low_timelock_penalty(timelock_safety_score: int) -> int:
    """Penalty for short timelock: TIMELOCK_MAX_SAFETY_SCORE - timelock_safety_score."""
    return TIMELOCK_MAX_SAFETY_SCORE - timelock_safety_score


def compute_low_quorum_penalty(quorum_threshold_pct: float) -> int:
    """
    Penalty for low quorum (easy to pass proposals with few tokens).
    quorum < 2%  → 30
    quorum < 5%  → 20
    quorum < 15% → 10
    else         → 0
    """
    for upper, penalty in _QUORUM_PENALTY_TIERS:
        if quorum_threshold_pct < upper:
            return penalty
    return 0


def compute_governance_attack_score(
    concentration_risk_score: int,
    timelock_safety_score: int,
    quorum_threshold_pct: float,
) -> int:
    """
    0-100 governance attack score (100=most vulnerable).
    = concentration_risk + low_timelock_penalty + low_quorum_penalty
    clamped [0, 100].
    """
    low_timelock = compute_low_timelock_penalty(timelock_safety_score)
    low_quorum = compute_low_quorum_penalty(quorum_threshold_pct)
    raw = concentration_risk_score + low_timelock + low_quorum
    return max(0, min(100, raw))


def governance_label(governance_attack_score: int) -> str:
    """Map governance_attack_score → governance label."""
    for upper, label in _GOVERNANCE_LABELS:
        if governance_attack_score <= upper:
            return label
    return "GOVERNANCE_EXPLOIT_RISK"


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def _resolve_log_path(data_dir: Optional[str] = None) -> str:
    if data_dir:
        return os.path.join(data_dir, LOG_FILENAME)
    return os.path.join(_REPO_ROOT, "data", LOG_FILENAME)


def _iso_now() -> str:
    t = time.gmtime()
    return (
        f"{t.tm_year:04d}-{t.tm_mon:02d}-{t.tm_mday:02d}T"
        f"{t.tm_hour:02d}:{t.tm_min:02d}:{t.tm_sec:02d}Z"
    )


def _atomic_write(path: str, data: Any) -> None:
    """Write JSON to path atomically (tmp + os.replace)."""
    dir_ = os.path.dirname(os.path.abspath(path))
    os.makedirs(dir_, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=dir_, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _load_log(path: str) -> List[Dict[str, Any]]:
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return []


def _append_log(path: str, entry: Dict[str, Any]) -> None:
    """Append entry to ring-buffer log (cap LOG_MAX_ENTRIES). Atomic write."""
    entries = _load_log(path)
    entries.append(entry)
    if len(entries) > LOG_MAX_ENTRIES:
        entries = entries[-LOG_MAX_ENTRIES:]
    _atomic_write(path, entries)


# ---------------------------------------------------------------------------
# Main analyzer class
# ---------------------------------------------------------------------------

class ProtocolDeFiGovernanceAttackSurfaceAnalyzer:
    """
    Analyzes governance attack surface for a DeFi protocol.

    Usage::

        analyzer = ProtocolDeFiGovernanceAttackSurfaceAnalyzer()
        result = analyzer.analyze(
            total_token_supply=1_000_000_000.0,
            top_10_holders_pct=35.0,
            quorum_threshold_pct=4.0,
            timelock_hours=48.0,
            vote_duration_hours=72.0,
            has_multisig_override=True,
            token_price_usd=2.50,
            protocol_tvl_usd=500_000_000.0,
            protocol_name="CompoundDAO",
        )
    """

    def __init__(self, data_dir: Optional[str] = None) -> None:
        self._data_dir = data_dir

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(
        self,
        total_token_supply: float,
        top_10_holders_pct: float,
        quorum_threshold_pct: float,
        timelock_hours: float,
        vote_duration_hours: float,
        has_multisig_override: bool,
        token_price_usd: float,
        protocol_tvl_usd: float,
        protocol_name: str,
    ) -> Dict[str, Any]:
        """Compute and return governance attack surface metrics."""
        tta_pct = compute_tokens_to_attack_pct(quorum_threshold_pct)
        cost_usd = compute_attack_cost_usd(tta_pct, total_token_supply, token_price_usd)
        cost_tvl = compute_attack_cost_to_tvl_ratio(cost_usd, protocol_tvl_usd)
        conc = compute_concentration_risk_score(top_10_holders_pct)
        tls = compute_timelock_safety_score(timelock_hours)
        gas = compute_governance_attack_score(conc, tls, quorum_threshold_pct)
        gl = governance_label(gas)

        result: Dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "module": MODULE_TAG,
            "timestamp": _iso_now(),
            "protocol_name": protocol_name,
            "inputs": {
                "total_token_supply": total_token_supply,
                "top_10_holders_pct": top_10_holders_pct,
                "quorum_threshold_pct": quorum_threshold_pct,
                "timelock_hours": timelock_hours,
                "vote_duration_hours": vote_duration_hours,
                "has_multisig_override": has_multisig_override,
                "token_price_usd": token_price_usd,
                "protocol_tvl_usd": protocol_tvl_usd,
            },
            "tokens_to_attack_pct": tta_pct,
            "attack_cost_usd": cost_usd,
            "attack_cost_to_tvl_ratio": cost_tvl,
            "concentration_risk_score": conc,
            "timelock_safety_score": tls,
            "governance_attack_score": gas,
            "governance_label": gl,
        }
        return result

    def analyze_and_log(
        self,
        total_token_supply: float,
        top_10_holders_pct: float,
        quorum_threshold_pct: float,
        timelock_hours: float,
        vote_duration_hours: float,
        has_multisig_override: bool,
        token_price_usd: float,
        protocol_tvl_usd: float,
        protocol_name: str,
    ) -> Dict[str, Any]:
        """Compute analysis, append to ring-buffer log, return result."""
        result = self.analyze(
            total_token_supply=total_token_supply,
            top_10_holders_pct=top_10_holders_pct,
            quorum_threshold_pct=quorum_threshold_pct,
            timelock_hours=timelock_hours,
            vote_duration_hours=vote_duration_hours,
            has_multisig_override=has_multisig_override,
            token_price_usd=token_price_usd,
            protocol_tvl_usd=protocol_tvl_usd,
            protocol_name=protocol_name,
        )
        log_path = _resolve_log_path(self._data_dir)
        _append_log(log_path, result)
        return result

    # ------------------------------------------------------------------
    # Convenience: batch analysis
    # ------------------------------------------------------------------

    def analyze_batch(self, protocols: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Analyze a list of protocol dicts (same keys as .analyze() kwargs)."""
        results = []
        for p in protocols:
            results.append(
                self.analyze(
                    total_token_supply=float(p.get("total_token_supply", 0.0)),
                    top_10_holders_pct=float(p.get("top_10_holders_pct", 0.0)),
                    quorum_threshold_pct=float(p.get("quorum_threshold_pct", 4.0)),
                    timelock_hours=float(p.get("timelock_hours", 0.0)),
                    vote_duration_hours=float(p.get("vote_duration_hours", 0.0)),
                    has_multisig_override=bool(p.get("has_multisig_override", False)),
                    token_price_usd=float(p.get("token_price_usd", 0.0)),
                    protocol_tvl_usd=float(p.get("protocol_tvl_usd", 0.0)),
                    protocol_name=p.get("protocol_name", "Unknown"),
                )
            )
        return results


# ---------------------------------------------------------------------------
# Module-level helper: run with sample data & write log
# ---------------------------------------------------------------------------

def run(data_dir: Optional[str] = None) -> List[Dict[str, Any]]:
    """Run analyzer on sample protocols, write log, return results."""
    analyzer = ProtocolDeFiGovernanceAttackSurfaceAnalyzer(data_dir=data_dir)
    samples = [
        dict(
            total_token_supply=1_000_000_000.0, top_10_holders_pct=25.0,
            quorum_threshold_pct=20.0, timelock_hours=168.0,
            vote_duration_hours=120.0, has_multisig_override=True,
            token_price_usd=5.00, protocol_tvl_usd=8_000_000_000.0,
            protocol_name="AaveDAO",
        ),
        dict(
            total_token_supply=100_000_000.0, top_10_holders_pct=72.0,
            quorum_threshold_pct=1.0, timelock_hours=2.0,
            vote_duration_hours=24.0, has_multisig_override=False,
            token_price_usd=0.10, protocol_tvl_usd=5_000_000.0,
            protocol_name="RiskyDAO",
        ),
        dict(
            total_token_supply=500_000_000.0, top_10_holders_pct=45.0,
            quorum_threshold_pct=4.0, timelock_hours=48.0,
            vote_duration_hours=72.0, has_multisig_override=True,
            token_price_usd=2.50, protocol_tvl_usd=500_000_000.0,
            protocol_name="CompoundDAO",
        ),
        dict(
            total_token_supply=10_000_000.0, top_10_holders_pct=80.0,
            quorum_threshold_pct=0.5, timelock_hours=0.0,
            vote_duration_hours=6.0, has_multisig_override=False,
            token_price_usd=1.00, protocol_tvl_usd=10_000_000.0,
            protocol_name="ExploitTarget",
        ),
        dict(
            total_token_supply=2_000_000_000.0, top_10_holders_pct=15.0,
            quorum_threshold_pct=30.0, timelock_hours=336.0,
            vote_duration_hours=168.0, has_multisig_override=True,
            token_price_usd=10.00, protocol_tvl_usd=20_000_000_000.0,
            protocol_name="FortressProtocol",
        ),
    ]
    results = []
    for s in samples:
        r = analyzer.analyze_and_log(**s)
        results.append(r)
    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="MP-1125 ProtocolDeFiGovernanceAttackSurfaceAnalyzer"
    )
    p.add_argument(
        "--check", action="store_true",
        help="Compute and print results without writing log",
    )
    p.add_argument(
        "--run", action="store_true",
        help="Compute and write to log file",
    )
    p.add_argument(
        "--data-dir", default=None, metavar="DIR",
        help="Override data directory (default: <repo>/data/)",
    )
    return p


def _print_results(results: List[Dict[str, Any]]) -> None:
    for r in results:
        print(
            f"  {r['protocol_name']:30s} | "
            f"attack_score={r['governance_attack_score']:3d} | "
            f"attack_cost=${r['attack_cost_usd']:,.0f} | "
            f"{r['governance_label']}"
        )


if __name__ == "__main__":
    args = _build_parser().parse_args()
    if not args.check and not args.run:
        args.check = True

    analyzer = ProtocolDeFiGovernanceAttackSurfaceAnalyzer(data_dir=args.data_dir)
    results: List[Dict[str, Any]] = []

    if args.run:
        results = run(data_dir=args.data_dir)
    else:
        # dry-run sample
        results = [
            analyzer.analyze(
                total_token_supply=1_000_000_000.0,
                top_10_holders_pct=25.0,
                quorum_threshold_pct=10.0,
                timelock_hours=72.0,
                vote_duration_hours=72.0,
                has_multisig_override=True,
                token_price_usd=3.00,
                protocol_tvl_usd=1_000_000_000.0,
                protocol_name="CheckSample",
            )
        ]

    print(f"\n{MODULE_TAG} GovernanceAttackSurfaceAnalyzer — {len(results)} result(s)")
    _print_results(results)
    sys.exit(0)
