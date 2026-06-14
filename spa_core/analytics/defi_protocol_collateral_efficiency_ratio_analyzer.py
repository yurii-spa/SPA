#!/usr/bin/env python3
"""
MP-1058: DeFiProtocolCollateralEfficiencyRatioAnalyzer — read-only / advisory.

Analyzes collateral efficiency for DeFi lending positions: given collateral
value, borrow value, LTV parameters, APY, and oracle settings, it computes
current LTV, safety cushion, a capital-efficiency score, net carry, and an
efficiency label.

Design constraints
------------------
* Pure stdlib only — no numpy / scipy / requests / pandas / web3.
* Advisory / read-only: never modifies risk/, execution/, monitoring/, allocator/.
* Atomic writes: tmp + os.replace (POSIX-atomic).
* Ring-buffer log capped at 100 entries in data/collateral_efficiency_ratio_log.json.
* Never raises on the happy path; degenerate inputs degrade gracefully.
* NOT imported from risk/, execution/, monitoring/ (LLM_FORBIDDEN_AGENTS).

Efficiency scoring formula
--------------------------
Capital efficiency score (0–100) weights five factors:

  1. ltv_utilization_score  — how well collateral is being used
       utilization = current_ltv / max_ltv_pct   (capped at 1.0)
       score       = utilization * 50              (max 50 pts)

  2. safety_cushion_score   — how far from liquidation threshold
       cushion_ratio = safety_cushion / liquidation_threshold_pct
       score         = cushion_ratio * 20           (max 20 pts)

  3. carry_score            — net carry contribution
       if net_carry >= 0:  score = min(net_carry / 5.0, 1.0) * 20   (max 20 pts)
       else:               score = max(net_carry / 5.0, -1.0) * 20  (penalty, min -20)

  4. oracle_tolerance_score — oracle resilience
       score = min(oracle_deviation_tolerance_pct / 10.0, 1.0) * 10 (max 10 pts)

  Total = ltv_utilization_score + safety_cushion_score + carry_score + oracle_tolerance_score
  Clamped to [0, 100].

Efficiency labels
-----------------
  MAXIMUM_EFFICIENCY   score >= 85
  HIGH_EFFICIENCY      score >= 70
  MODERATE_EFFICIENCY  score >= 50
  LOW_EFFICIENCY       score >= 30
  INEFFICIENT_COLLATERAL  score < 30

CLI
---
  python3 -m spa_core.analytics.defi_protocol_collateral_efficiency_ratio_analyzer --check
  python3 -m spa_core.analytics.defi_protocol_collateral_efficiency_ratio_analyzer --run
  python3 -m spa_core.analytics.defi_protocol_collateral_efficiency_ratio_analyzer --run --data-dir PATH
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Constants & paths
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _PROJECT_ROOT / "data"

LOG_FILENAME = "collateral_efficiency_ratio_log.json"
RING_BUFFER_CAP = 100
SCHEMA_VERSION = 1
SOURCE_NAME = "defi_protocol_collateral_efficiency_ratio_analyzer"
MP_TAG = "MP-1058"

# Label thresholds (score, descending)
_LABEL_THRESHOLDS = [
    (85.0, "MAXIMUM_EFFICIENCY"),
    (70.0, "HIGH_EFFICIENCY"),
    (50.0, "MODERATE_EFFICIENCY"),
    (30.0, "LOW_EFFICIENCY"),
]

log = logging.getLogger("spa.analytics.defi_protocol_collateral_efficiency_ratio_analyzer")

# ---------------------------------------------------------------------------
# Pure computation helpers (exported for tests)
# ---------------------------------------------------------------------------


def compute_current_ltv(collateral_value_usd: float, borrowed_value_usd: float) -> float:
    """Current LTV = borrowed / collateral * 100.  Returns 0.0 if collateral <= 0."""
    if collateral_value_usd <= 0:
        return 0.0
    return (borrowed_value_usd / collateral_value_usd) * 100.0


def compute_safety_cushion(
    liquidation_threshold_pct: float, current_ltv_pct: float
) -> float:
    """Safety cushion = liquidation_threshold - current_ltv.  Can be negative (at risk)."""
    return liquidation_threshold_pct - current_ltv_pct


def compute_net_carry(
    current_apy_on_collateral_pct: float, borrow_rate_pct: float
) -> float:
    """Net carry = collateral_apy - borrow_rate."""
    return current_apy_on_collateral_pct - borrow_rate_pct


def compute_capital_efficiency_score(
    current_ltv_pct: float,
    max_ltv_pct: float,
    safety_cushion_pct: float,
    liquidation_threshold_pct: float,
    net_carry_pct: float,
    oracle_deviation_tolerance_pct: float,
) -> float:
    """Return capital efficiency score in [0, 100]."""
    # 1. LTV utilization score (max 50)
    if max_ltv_pct > 0:
        utilization = min(current_ltv_pct / max_ltv_pct, 1.0)
    else:
        utilization = 0.0
    ltv_score = utilization * 50.0

    # 2. Safety cushion score (max 20)
    if liquidation_threshold_pct > 0:
        cushion_ratio = min(max(safety_cushion_pct / liquidation_threshold_pct, 0.0), 1.0)
    else:
        cushion_ratio = 0.0
    cushion_score = cushion_ratio * 20.0

    # 3. Carry score (range: -20 to +20)
    if net_carry_pct >= 0:
        carry_score = min(net_carry_pct / 5.0, 1.0) * 20.0
    else:
        carry_score = max(net_carry_pct / 5.0, -1.0) * 20.0

    # 4. Oracle tolerance score (max 10)
    oracle_score = min(oracle_deviation_tolerance_pct / 10.0, 1.0) * 10.0

    total = ltv_score + cushion_score + carry_score + oracle_score
    return max(0.0, min(total, 100.0))


def efficiency_label(score: float) -> str:
    """Map score to human-readable efficiency label."""
    for threshold, label in _LABEL_THRESHOLDS:
        if score >= threshold:
            return label
    return "INEFFICIENT_COLLATERAL"


# ---------------------------------------------------------------------------
# Main analyzer class
# ---------------------------------------------------------------------------


class DeFiProtocolCollateralEfficiencyRatioAnalyzer:
    """Read-only analytics: measures collateral efficiency for a DeFi lending position.

    Parameters (input dict)
    -----------------------
    protocol_name                 : str   — protocol identifier
    collateral_asset              : str   — e.g. "ETH", "wstETH"
    collateral_value_usd          : float — USD value of collateral posted
    borrowed_value_usd            : float — USD value of outstanding debt
    max_ltv_pct                   : float — maximum LTV allowed by protocol (%)
    liquidation_threshold_pct     : float — LTV at which liquidation triggers (%)
    current_apy_on_collateral_pct : float — APY earned on collateral asset (%)
    borrow_rate_pct               : float — cost of borrowing (%)
    oracle_deviation_tolerance_pct: float — accepted oracle price deviation (%)

    Outputs (dict)
    --------------
    current_ltv_pct         : float  — current loan-to-value ratio (%)
    safety_cushion_pct      : float  — liquidation_threshold - current_ltv (%)
    capital_efficiency_score: float  — 0–100 composite efficiency score
    net_carry_pct           : float  — collateral_apy - borrow_rate (%)
    efficiency_label        : str    — one of the five efficiency labels
    """

    def __init__(self, data_dir: Optional[Path] = None) -> None:
        self._data_dir = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR
        self._log_path = self._data_dir / LOG_FILENAME

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze a single collateral position and return result dict."""
        self._validate(params)

        protocol_name = str(params["protocol_name"])
        collateral_asset = str(params["collateral_asset"])
        collateral_value_usd = float(params["collateral_value_usd"])
        borrowed_value_usd = float(params["borrowed_value_usd"])
        max_ltv_pct = float(params["max_ltv_pct"])
        liquidation_threshold_pct = float(params["liquidation_threshold_pct"])
        current_apy_on_collateral_pct = float(params["current_apy_on_collateral_pct"])
        borrow_rate_pct = float(params["borrow_rate_pct"])
        oracle_deviation_tolerance_pct = float(params["oracle_deviation_tolerance_pct"])

        current_ltv = compute_current_ltv(collateral_value_usd, borrowed_value_usd)
        safety_cushion = compute_safety_cushion(liquidation_threshold_pct, current_ltv)
        net_carry = compute_net_carry(current_apy_on_collateral_pct, borrow_rate_pct)
        score = compute_capital_efficiency_score(
            current_ltv,
            max_ltv_pct,
            safety_cushion,
            liquidation_threshold_pct,
            net_carry,
            oracle_deviation_tolerance_pct,
        )
        label = efficiency_label(score)

        return {
            "schema_version": SCHEMA_VERSION,
            "mp_tag": MP_TAG,
            "source": SOURCE_NAME,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "protocol_name": protocol_name,
            "collateral_asset": collateral_asset,
            "collateral_value_usd": collateral_value_usd,
            "borrowed_value_usd": borrowed_value_usd,
            "max_ltv_pct": max_ltv_pct,
            "liquidation_threshold_pct": liquidation_threshold_pct,
            "current_apy_on_collateral_pct": current_apy_on_collateral_pct,
            "borrow_rate_pct": borrow_rate_pct,
            "oracle_deviation_tolerance_pct": oracle_deviation_tolerance_pct,
            # --- outputs ---
            "current_ltv_pct": round(current_ltv, 6),
            "safety_cushion_pct": round(safety_cushion, 6),
            "capital_efficiency_score": round(score, 4),
            "net_carry_pct": round(net_carry, 6),
            "efficiency_label": label,
        }

    def analyze_and_save(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze and atomically append result to ring-buffer log."""
        result = self.analyze(params)
        self._append_to_log(result)
        result["saved_to"] = str(self._log_path)
        return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _validate(self, params: Dict[str, Any]) -> None:
        required = [
            "protocol_name", "collateral_asset", "collateral_value_usd",
            "borrowed_value_usd", "max_ltv_pct", "liquidation_threshold_pct",
            "current_apy_on_collateral_pct", "borrow_rate_pct",
            "oracle_deviation_tolerance_pct",
        ]
        missing = [k for k in required if k not in params]
        if missing:
            raise ValueError(f"Missing required params: {missing}")

    def _append_to_log(self, entry: Dict[str, Any]) -> None:
        """Load existing log, append entry, cap at RING_BUFFER_CAP, atomic save."""
        existing: List[Dict[str, Any]] = _load_json_list(self._log_path)
        existing.append(entry)
        if len(existing) > RING_BUFFER_CAP:
            existing = existing[-RING_BUFFER_CAP:]
        _atomic_write_json(self._log_path, existing)


# ---------------------------------------------------------------------------
# JSON I/O helpers
# ---------------------------------------------------------------------------


def _load_json_list(path: Path) -> List[Dict[str, Any]]:
    """Load a JSON list from *path*; return [] on any error."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, list):
            return data
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return []


def _atomic_write_json(path: Path, data: Any) -> None:
    """Write *data* as JSON to *path* using tmp + os.replace (atomic)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
        os.replace(tmp_path, str(path))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _build_sample_params() -> Dict[str, Any]:
    return {
        "protocol_name": "Aave V3",
        "collateral_asset": "wstETH",
        "collateral_value_usd": 100_000.0,
        "borrowed_value_usd": 60_000.0,
        "max_ltv_pct": 80.0,
        "liquidation_threshold_pct": 85.0,
        "current_apy_on_collateral_pct": 4.5,
        "borrow_rate_pct": 3.2,
        "oracle_deviation_tolerance_pct": 5.0,
    }


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(description=f"{MP_TAG}: Collateral Efficiency Ratio Analyzer")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", default=True,
                      help="Compute and print (no write). Default.")
    mode.add_argument("--run", action="store_true",
                      help="Compute, print, and save to log.")
    parser.add_argument("--data-dir", default=None,
                        help="Override data directory path.")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    data_dir = Path(args.data_dir) if args.data_dir else _DEFAULT_DATA_DIR
    analyzer = DeFiProtocolCollateralEfficiencyRatioAnalyzer(data_dir=data_dir)
    params = _build_sample_params()

    if args.run:
        result = analyzer.analyze_and_save(params)
        print(json.dumps(result, indent=2))
        log.info("Saved to %s", result.get("saved_to"))
    else:
        result = analyzer.analyze(params)
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
