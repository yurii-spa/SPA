"""
MP-1137: ProtocolDeFiProtocolConcentrationRiskAnalyzer
=======================================================
Advisory-only analytics module.

Analyzes portfolio-level concentration risk across DeFi protocols.
A portfolio too concentrated in one protocol, chain, or yield type is exposed
to correlated failures.

Inputs:
  positions           list[dict] — each dict must contain:
                        protocol_name  str   (e.g. "Aave")
                        chain          str   (e.g. "Ethereum")
                        yield_type     str   (e.g. "lending" / "staking" / "lp")
                        value_usd      float (USD value of the position)
                        apy_pct        float (current APY in percent)
  total_portfolio_usd float — total portfolio size used as the HHI denominator
                               (may include cash / undeployed capital)

Outputs:
  num_positions         int   — number of position entries
  hhi_protocol          float — Herfindahl index by protocol (0-1)
  hhi_chain             float — Herfindahl index by chain (0-1)
  hhi_yield_type        float — Herfindahl index by yield type (0-1)
  largest_position_pct  float — largest single-protocol share (%)
  largest_protocol      str   — name of the dominant protocol
  blended_apy_pct       float — value-weighted average APY across positions
  concentration_score   int   — 0-100 composite:
                                  int(hhi_protocol*50 + hhi_chain*30 + hhi_yield_type*20)
  concentration_label   str   — WELL_DIVERSIFIED / GOOD_DIVERSIFICATION /
                                 MODERATE_CONCENTRATION / CONCENTRATED /
                                 SINGLE_POINT_OF_FAILURE
                                 (thresholds: <=20 / <=40 / <=60 / <=80 / <=100)

Label thresholds (concentration_score):
  <= 20  → WELL_DIVERSIFIED
  <= 40  → GOOD_DIVERSIFICATION
  <= 60  → MODERATE_CONCENTRATION
  <= 80  → CONCENTRATED
  <= 100 → SINGLE_POINT_OF_FAILURE

Log file: data/protocol_concentration_risk_log.json  (ring-buffer 100 entries)
Atomic writes: tmp + os.replace.
Pure stdlib only.  Read-only / advisory.  Python 3.9 compatible.
"""

import json
import os
import tempfile
import time
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
LOG_PATH: str = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
    "protocol_concentration_risk_log.json",
)
LOG_MAX_ENTRIES: int = 100

REQUIRED_POSITION_FIELDS: frozenset = frozenset(
    {"protocol_name", "chain", "yield_type", "value_usd", "apy_pct"}
)

# Label thresholds
LABEL_WELL_DIVERSIFIED_MAX: int = 20
LABEL_GOOD_DIVERSIFICATION_MAX: int = 40
LABEL_MODERATE_CONCENTRATION_MAX: int = 60
LABEL_CONCENTRATED_MAX: int = 80
# <= 100 → SINGLE_POINT_OF_FAILURE

# Score weights (must sum to 100 for 0-100 output range)
WEIGHT_PROTOCOL: float = 50.0
WEIGHT_CHAIN: float = 30.0
WEIGHT_YIELD_TYPE: float = 20.0


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

def _validate_positions(positions: List[Dict[str, Any]]) -> None:
    if not isinstance(positions, list):
        raise TypeError(
            f"positions must be a list, got {type(positions).__name__}"
        )
    for i, p in enumerate(positions):
        if not isinstance(p, dict):
            raise TypeError(
                f"Position {i} must be a dict, got {type(p).__name__}"
            )
        missing = REQUIRED_POSITION_FIELDS - set(p.keys())
        if missing:
            raise ValueError(
                f"Position {i} missing required fields: {sorted(missing)}"
            )
        if not isinstance(p["protocol_name"], str) or not p["protocol_name"].strip():
            raise ValueError(
                f"Position {i}: protocol_name must be a non-empty string"
            )
        if not isinstance(p["chain"], str) or not p["chain"].strip():
            raise ValueError(
                f"Position {i}: chain must be a non-empty string"
            )
        if not isinstance(p["yield_type"], str) or not p["yield_type"].strip():
            raise ValueError(
                f"Position {i}: yield_type must be a non-empty string"
            )
        val = float(p["value_usd"])
        if val < 0:
            raise ValueError(
                f"Position {i}: value_usd must be >= 0, got {val}"
            )


def _validate_total(total_portfolio_usd: float) -> None:
    if total_portfolio_usd <= 0:
        raise ValueError(
            f"total_portfolio_usd must be > 0, got {total_portfolio_usd}"
        )


# ---------------------------------------------------------------------------
# Core computations
# ---------------------------------------------------------------------------

def _group_by(
    positions: List[Dict[str, Any]], key: str
) -> Dict[str, float]:
    """Sum value_usd per unique value of *key*."""
    groups: Dict[str, float] = {}
    for p in positions:
        k = str(p[key])
        groups[k] = groups.get(k, 0.0) + float(p["value_usd"])
    return groups


def _hhi(groups: Dict[str, float], total: float) -> float:
    """
    Herfindahl-Hirschman Index (0-1) for the given grouping.

    share_i = groups[i] / total
    HHI     = sum(share_i ^ 2)

    Returns 0.0 when groups is empty (no concentration).
    """
    if total <= 0:
        # Should not reach here after validation, but guard anyway
        return 1.0
    hhi = 0.0
    for v in groups.values():
        share = float(v) / total
        hhi += share * share
    return round(hhi, 6)


def _largest(groups: Dict[str, float]) -> Tuple[str, float]:
    """Return (name, total_value) of the largest group."""
    if not groups:
        return ("", 0.0)
    name = max(groups, key=lambda k: groups[k])
    return (name, groups[name])


def _blended_apy(
    positions: List[Dict[str, Any]], total_invested: float
) -> float:
    """Value-weighted average APY across all positions."""
    if total_invested <= 0.0:
        return 0.0
    weighted = sum(
        float(p["value_usd"]) * float(p["apy_pct"]) for p in positions
    )
    return round(weighted / total_invested, 6)


def _concentration_score(
    hhi_protocol: float,
    hhi_chain: float,
    hhi_yield_type: float,
) -> int:
    """
    Weighted composite score 0-100.
    score = int(hhi_protocol*50 + hhi_chain*30 + hhi_yield_type*20)
    Clamped to [0, 100].
    """
    raw = (
        hhi_protocol * WEIGHT_PROTOCOL
        + hhi_chain * WEIGHT_CHAIN
        + hhi_yield_type * WEIGHT_YIELD_TYPE
    )
    return min(100, max(0, int(raw)))


def _concentration_label(score: int) -> str:
    """Map a concentration_score to a human-readable label."""
    if score <= LABEL_WELL_DIVERSIFIED_MAX:
        return "WELL_DIVERSIFIED"
    if score <= LABEL_GOOD_DIVERSIFICATION_MAX:
        return "GOOD_DIVERSIFICATION"
    if score <= LABEL_MODERATE_CONCENTRATION_MAX:
        return "MODERATE_CONCENTRATION"
    if score <= LABEL_CONCENTRATED_MAX:
        return "CONCENTRATED"
    return "SINGLE_POINT_OF_FAILURE"


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def _atomic_write(path: str, data: Any) -> None:
    """Write *data* as JSON to *path* atomically (tmp + os.replace)."""
    dir_ = os.path.dirname(path)
    if dir_:
        os.makedirs(dir_, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=dir_ or ".", prefix=".tmp_pca_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _load_log(path: str) -> List[Dict[str, Any]]:
    """Load log entries from *path*, returning [] on missing/corrupt file."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, list):
            return data
    except (FileNotFoundError, json.JSONDecodeError, PermissionError, OSError):
        pass
    return []


# ---------------------------------------------------------------------------
# Public class
# ---------------------------------------------------------------------------

class ProtocolDeFiProtocolConcentrationRiskAnalyzer:
    """
    Analyzes portfolio-level concentration risk across DeFi protocols,
    chains, and yield types.

    Advisory only — never modifies allocator, risk, or execution domains.
    """

    def __init__(self, log_path: Optional[str] = None) -> None:
        self._log_path: str = log_path if log_path is not None else LOG_PATH

    # ------------------------------------------------------------------
    # Analysis
    # ------------------------------------------------------------------

    def analyze(
        self,
        positions: List[Dict[str, Any]],
        total_portfolio_usd: float,
    ) -> Dict[str, Any]:
        """
        Analyze concentration risk for a DeFi portfolio.

        Returns a dict with all computed fields. Raises ValueError/TypeError on
        invalid input.
        """
        _validate_positions(positions)
        _validate_total(total_portfolio_usd)

        num_positions = len(positions)

        # Total USD invested (may differ from total_portfolio_usd due to cash)
        total_invested = sum(float(p["value_usd"]) for p in positions)

        # Group by each dimension
        by_protocol = _group_by(positions, "protocol_name")
        by_chain = _group_by(positions, "chain")
        by_yield_type = _group_by(positions, "yield_type")

        # HHI — shares relative to full portfolio (including undeployed cash)
        hhi_prot = _hhi(by_protocol, total_portfolio_usd)
        hhi_ch = _hhi(by_chain, total_portfolio_usd)
        hhi_yt = _hhi(by_yield_type, total_portfolio_usd)

        # Largest single protocol
        largest_prot, largest_val = _largest(by_protocol)
        largest_pct = round(largest_val / total_portfolio_usd * 100.0, 4)

        # Value-weighted APY (uses total_invested so cash doesn't dilute)
        blended_apy = _blended_apy(positions, total_invested)

        score = _concentration_score(hhi_prot, hhi_ch, hhi_yt)
        label = _concentration_label(score)

        return {
            "num_positions": num_positions,
            "hhi_protocol": hhi_prot,
            "hhi_chain": hhi_ch,
            "hhi_yield_type": hhi_yt,
            "largest_position_pct": largest_pct,
            "largest_protocol": largest_prot,
            "blended_apy_pct": blended_apy,
            "concentration_score": score,
            "concentration_label": label,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    def analyze_and_log(
        self,
        positions: List[Dict[str, Any]],
        total_portfolio_usd: float,
    ) -> Dict[str, Any]:
        """
        Analyze and append the result to the ring-buffer log
        (capped at LOG_MAX_ENTRIES via atomic write).
        """
        result = self.analyze(positions, total_portfolio_usd)
        entries = _load_log(self._log_path)
        entries.append(result)
        if len(entries) > LOG_MAX_ENTRIES:
            entries = entries[-LOG_MAX_ENTRIES:]
        _atomic_write(self._log_path, entries)
        return result

    def get_log(self) -> List[Dict[str, Any]]:
        """Return current log entries (empty list if log does not exist)."""
        return _load_log(self._log_path)
