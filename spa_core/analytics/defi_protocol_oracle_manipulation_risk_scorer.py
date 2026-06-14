"""
MP-1124: DeFiProtocolOracleManipulationRiskScorer
==================================================
Advisory-only analytics module. Pure stdlib. Read-only / no external deps.

Scores how vulnerable a DeFi protocol is to oracle price manipulation attacks.
Protocols using low-liquidity on-chain price feeds are far more vulnerable than
those using Chainlink with multiple data sources.

Inputs
------
oracle_type               str    chainlink | twap_uniswap | twap_curve |
                                 pyth | band | single_dex | custom
twap_period_minutes       int    TWAP window in minutes (0 if not applicable)
oracle_pool_liquidity_usd float  Liquidity in the oracle pricing pool (0 if chainlink)
protocol_tvl_usd          float  TVL that could be exploited
max_flash_loan_available_usd float  Max flash loan that could be used to manipulate
num_oracle_sources        int    Number of independent price feeds (1 for single-source)
has_circuit_breaker       bool   Does protocol have price deviation circuit breaker
protocol_name             str

Outputs (all returned in a dict from .score())
----------------------------------------------
oracle_source_score       int 0-40  Higher = safer
                          chainlink=40, pyth=35, twap_curve=25,
                          twap_uniswap=20, band=20, single_dex=5, custom=0
manipulation_cost_ratio   float  oracle_pool_liquidity / max_flash_loan_available
                                 (higher = safer; 0.0 if max_flash_loan is 0)
tvl_at_risk_ratio         float  protocol_tvl / oracle_pool_liquidity when
                                 num_oracle_sources==1, else 0.0
circuit_breaker_bonus     int    15 if has_circuit_breaker else 0
multi_source_bonus        int    min(max(num_oracle_sources-1, 0), 3) * 5
manipulation_risk_score   int 0-100 (100=highest risk)
                          = 100 - oracle_source_score - circuit_breaker_bonus
                            - multi_source_bonus, clamped [0,100]
risk_label                str    NEGLIGIBLE_ORACLE_RISK / LOW_ORACLE_RISK /
                                 MODERATE_ORACLE_RISK / HIGH_ORACLE_RISK /
                                 CRITICAL_ORACLE_RISK

Label thresholds (manipulation_risk_score)
------------------------------------------
<= 10  → NEGLIGIBLE_ORACLE_RISK
<= 30  → LOW_ORACLE_RISK
<= 55  → MODERATE_ORACLE_RISK
<= 75  → HIGH_ORACLE_RISK
> 75   → CRITICAL_ORACLE_RISK

Ring-buffer log (100 entries max) → data/oracle_manipulation_risk_log.json
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

LOG_FILENAME = "oracle_manipulation_risk_log.json"
LOG_MAX_ENTRIES = 100
SCHEMA_VERSION = 1
MODULE_TAG = "MP-1124"

# oracle_source_score lookup (int, 0-40; higher = safer)
ORACLE_SOURCE_SCORES: Dict[str, int] = {
    "chainlink":    40,
    "pyth":         35,
    "twap_curve":   25,
    "twap_uniswap": 20,
    "band":         20,
    "single_dex":    5,
    "custom":        0,
}

# Label thresholds — (upper_bound_inclusive, label)
_RISK_LABELS = [
    (10,  "NEGLIGIBLE_ORACLE_RISK"),
    (30,  "LOW_ORACLE_RISK"),
    (55,  "MODERATE_ORACLE_RISK"),
    (75,  "HIGH_ORACLE_RISK"),
    (100, "CRITICAL_ORACLE_RISK"),
]

CIRCUIT_BREAKER_BONUS = 15
MULTI_SOURCE_BONUS_PER_EXTRA = 5
MULTI_SOURCE_MAX_EXTRAS = 3  # capped at 3 extra sources → max 15 pts


# ---------------------------------------------------------------------------
# Pure computation helpers (importable for unit testing)
# ---------------------------------------------------------------------------

def compute_oracle_source_score(oracle_type: str) -> int:
    """Return oracle_source_score (0-40) for the given oracle type."""
    return ORACLE_SOURCE_SCORES.get(oracle_type.lower() if oracle_type else "", 0)


def compute_manipulation_cost_ratio(
    oracle_pool_liquidity_usd: float,
    max_flash_loan_available_usd: float,
) -> float:
    """oracle_pool_liquidity / max_flash_loan. Returns 0.0 when flash loan is 0."""
    if max_flash_loan_available_usd <= 0.0:
        return 0.0
    return oracle_pool_liquidity_usd / max_flash_loan_available_usd


def compute_tvl_at_risk_ratio(
    protocol_tvl_usd: float,
    oracle_pool_liquidity_usd: float,
    num_oracle_sources: int,
) -> float:
    """protocol_tvl / oracle_pool_liquidity when single-source, else 0.0."""
    if num_oracle_sources == 1 and oracle_pool_liquidity_usd > 0.0:
        return protocol_tvl_usd / oracle_pool_liquidity_usd
    return 0.0


def compute_circuit_breaker_bonus(has_circuit_breaker: bool) -> int:
    """15 if has_circuit_breaker else 0."""
    return CIRCUIT_BREAKER_BONUS if has_circuit_breaker else 0


def compute_multi_source_bonus(num_oracle_sources: int) -> int:
    """min(max(num_oracle_sources-1, 0), 3) * 5."""
    extras = min(max(num_oracle_sources - 1, 0), MULTI_SOURCE_MAX_EXTRAS)
    return extras * MULTI_SOURCE_BONUS_PER_EXTRA


def compute_manipulation_risk_score(
    oracle_source_score: int,
    circuit_breaker_bonus: int,
    multi_source_bonus: int,
) -> int:
    """100 - oracle_source_score - circuit_breaker_bonus - multi_source_bonus, clamped [0,100]."""
    raw = 100 - oracle_source_score - circuit_breaker_bonus - multi_source_bonus
    return max(0, min(100, raw))


def risk_label(manipulation_risk_score: int) -> str:
    """Map manipulation_risk_score → risk label string."""
    for upper, label in _RISK_LABELS:
        if manipulation_risk_score <= upper:
            return label
    return "CRITICAL_ORACLE_RISK"


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
# Main scorer class
# ---------------------------------------------------------------------------

class DeFiProtocolOracleManipulationRiskScorer:
    """
    Scores oracle manipulation risk for a DeFi protocol.

    Usage::

        scorer = DeFiProtocolOracleManipulationRiskScorer()
        result = scorer.score(
            oracle_type="chainlink",
            twap_period_minutes=0,
            oracle_pool_liquidity_usd=0.0,
            protocol_tvl_usd=50_000_000.0,
            max_flash_loan_available_usd=500_000_000.0,
            num_oracle_sources=5,
            has_circuit_breaker=True,
            protocol_name="Aave V3",
        )
    """

    def __init__(self, data_dir: Optional[str] = None) -> None:
        self._data_dir = data_dir

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def score(
        self,
        oracle_type: str,
        twap_period_minutes: int,
        oracle_pool_liquidity_usd: float,
        protocol_tvl_usd: float,
        max_flash_loan_available_usd: float,
        num_oracle_sources: int,
        has_circuit_breaker: bool,
        protocol_name: str,
    ) -> Dict[str, Any]:
        """Compute and return oracle manipulation risk metrics."""
        oss = compute_oracle_source_score(oracle_type)
        mcr = compute_manipulation_cost_ratio(
            oracle_pool_liquidity_usd, max_flash_loan_available_usd
        )
        tar = compute_tvl_at_risk_ratio(
            protocol_tvl_usd, oracle_pool_liquidity_usd, num_oracle_sources
        )
        cbb = compute_circuit_breaker_bonus(has_circuit_breaker)
        msb = compute_multi_source_bonus(num_oracle_sources)
        mrs = compute_manipulation_risk_score(oss, cbb, msb)
        rl = risk_label(mrs)

        result: Dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "module": MODULE_TAG,
            "timestamp": _iso_now(),
            "protocol_name": protocol_name,
            "inputs": {
                "oracle_type": oracle_type,
                "twap_period_minutes": twap_period_minutes,
                "oracle_pool_liquidity_usd": oracle_pool_liquidity_usd,
                "protocol_tvl_usd": protocol_tvl_usd,
                "max_flash_loan_available_usd": max_flash_loan_available_usd,
                "num_oracle_sources": num_oracle_sources,
                "has_circuit_breaker": has_circuit_breaker,
            },
            "oracle_source_score": oss,
            "manipulation_cost_ratio": mcr,
            "tvl_at_risk_ratio": tar,
            "circuit_breaker_bonus": cbb,
            "multi_source_bonus": msb,
            "manipulation_risk_score": mrs,
            "risk_label": rl,
        }
        return result

    def score_and_log(
        self,
        oracle_type: str,
        twap_period_minutes: int,
        oracle_pool_liquidity_usd: float,
        protocol_tvl_usd: float,
        max_flash_loan_available_usd: float,
        num_oracle_sources: int,
        has_circuit_breaker: bool,
        protocol_name: str,
    ) -> Dict[str, Any]:
        """Compute risk, append to ring-buffer log, return result."""
        result = self.score(
            oracle_type=oracle_type,
            twap_period_minutes=twap_period_minutes,
            oracle_pool_liquidity_usd=oracle_pool_liquidity_usd,
            protocol_tvl_usd=protocol_tvl_usd,
            max_flash_loan_available_usd=max_flash_loan_available_usd,
            num_oracle_sources=num_oracle_sources,
            has_circuit_breaker=has_circuit_breaker,
            protocol_name=protocol_name,
        )
        log_path = _resolve_log_path(self._data_dir)
        _append_log(log_path, result)
        return result

    # ------------------------------------------------------------------
    # Convenience: batch scoring
    # ------------------------------------------------------------------

    def score_batch(self, protocols: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Score a list of protocol dicts (same keys as .score() kwargs)."""
        results = []
        for p in protocols:
            results.append(
                self.score(
                    oracle_type=p.get("oracle_type", "custom"),
                    twap_period_minutes=p.get("twap_period_minutes", 0),
                    oracle_pool_liquidity_usd=float(p.get("oracle_pool_liquidity_usd", 0.0)),
                    protocol_tvl_usd=float(p.get("protocol_tvl_usd", 0.0)),
                    max_flash_loan_available_usd=float(
                        p.get("max_flash_loan_available_usd", 0.0)
                    ),
                    num_oracle_sources=int(p.get("num_oracle_sources", 1)),
                    has_circuit_breaker=bool(p.get("has_circuit_breaker", False)),
                    protocol_name=p.get("protocol_name", "Unknown"),
                )
            )
        return results


# ---------------------------------------------------------------------------
# Module-level helper: run with sample data & write log
# ---------------------------------------------------------------------------

def run(data_dir: Optional[str] = None) -> List[Dict[str, Any]]:
    """Run scorer on sample protocols, write log, return results."""
    scorer = DeFiProtocolOracleManipulationRiskScorer(data_dir=data_dir)
    samples = [
        dict(
            oracle_type="chainlink", twap_period_minutes=0,
            oracle_pool_liquidity_usd=0.0, protocol_tvl_usd=5_000_000_000.0,
            max_flash_loan_available_usd=2_000_000_000.0,
            num_oracle_sources=10, has_circuit_breaker=True,
            protocol_name="Aave V3",
        ),
        dict(
            oracle_type="twap_uniswap", twap_period_minutes=30,
            oracle_pool_liquidity_usd=2_000_000.0, protocol_tvl_usd=100_000_000.0,
            max_flash_loan_available_usd=500_000_000.0,
            num_oracle_sources=1, has_circuit_breaker=False,
            protocol_name="SmallDex Protocol",
        ),
        dict(
            oracle_type="single_dex", twap_period_minutes=0,
            oracle_pool_liquidity_usd=500_000.0, protocol_tvl_usd=50_000_000.0,
            max_flash_loan_available_usd=200_000_000.0,
            num_oracle_sources=1, has_circuit_breaker=False,
            protocol_name="RiskyFarm",
        ),
        dict(
            oracle_type="pyth", twap_period_minutes=0,
            oracle_pool_liquidity_usd=0.0, protocol_tvl_usd=800_000_000.0,
            max_flash_loan_available_usd=1_000_000_000.0,
            num_oracle_sources=3, has_circuit_breaker=True,
            protocol_name="PythProtocol",
        ),
        dict(
            oracle_type="custom", twap_period_minutes=5,
            oracle_pool_liquidity_usd=300_000.0, protocol_tvl_usd=20_000_000.0,
            max_flash_loan_available_usd=100_000_000.0,
            num_oracle_sources=1, has_circuit_breaker=False,
            protocol_name="CustomOracle",
        ),
    ]
    results = []
    log_path = _resolve_log_path(data_dir)
    for s in samples:
        r = scorer.score_and_log(**s)
        results.append(r)
    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="MP-1124 DeFiProtocolOracleManipulationRiskScorer"
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
            f"oracle_type={r['inputs']['oracle_type']:15s} | "
            f"risk_score={r['manipulation_risk_score']:3d} | "
            f"{r['risk_label']}"
        )


if __name__ == "__main__":
    args = _build_parser().parse_args()
    if not args.check and not args.run:
        args.check = True

    scorer = DeFiProtocolOracleManipulationRiskScorer(data_dir=args.data_dir)
    results = run(data_dir=args.data_dir) if args.run else []

    if args.check and not args.run:
        # dry-run sample
        samples_dry = [
            dict(
                oracle_type="chainlink", twap_period_minutes=0,
                oracle_pool_liquidity_usd=0.0, protocol_tvl_usd=1_000_000_000.0,
                max_flash_loan_available_usd=500_000_000.0,
                num_oracle_sources=5, has_circuit_breaker=True,
                protocol_name="CheckSample",
            )
        ]
        results = [scorer.score(**s) for s in samples_dry]

    print(f"\n{MODULE_TAG} OracleManipulationRiskScorer — {len(results)} result(s)")
    _print_results(results)
    sys.exit(0)
