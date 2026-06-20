#!/usr/bin/env python3
"""DeFi Protocol Interest Rate Model Analyzer (SPA-V755 / MP-1034) — read-only / advisory.

Analyzes lending protocol interest rate models (kink, linear, jump, custom) for
borrow/supply rate dynamics given utilization rates and model parameters.

Design constraints
------------------
* Pure stdlib only — no numpy / scipy / requests / pandas / web3.
* Advisory / read-only: never modifies risk/, execution/, monitoring/, allocator/.
* Atomic writes: tmp + os.replace (POSIX-atomic).
* Ring-buffer log capped at 100 entries → data/interest_rate_model_log.json.
* Never raises on the happy path; degenerate inputs degrade gracefully with warnings.
* NOT imported from risk/, execution/, monitoring/ (LLM_FORBIDDEN_AGENTS).

Interest Rate Models
--------------------
KINK (standard Aave / Compound style):
  utilization ∈ [0, kink_point]:
    borrow_rate = base_rate + slope1 × (utilization / kink_point)
  utilization ∈ (kink_point, 100]:
    borrow_rate = base_rate + slope1 + slope2 × ((utilization − kink_point) / (100 − kink_point))

LINEAR:
  borrow_rate = base_rate + slope1 × (utilization / 100)
  (slope2 / kink_point ignored)

JUMP:
  Identical formula to KINK — slope2 is expected to be very large,
  creating the characteristic rate "jump" above the kink.

CUSTOM:
  Same formula as KINK — user supplies arbitrary coefficients.

Supply rate (protocol-fee-free approximation):
  supply_rate = borrow_rate × (utilization / 100)

Spread:
  spread_pct = borrow_rate − supply_rate

Utilization efficiency score (0–100):
  score = max(0, 100 − 2 × |utilization − optimal_utilization_pct|)
  Peak at optimal utilization; −2 pt per % deviation.

Rate volatility risk:
  LOW    : utilization < kink_point × 0.75
  MEDIUM : kink_point × 0.75 ≤ utilization < kink_point × 1.05
  HIGH   : utilization ≥ kink_point × 1.05

Labels (first matching wins, highest priority first):
  CRISIS_RATES         borrow_rate ≥ 25 % OR utilization ≥ 95 %
  OPTIMAL_UTILIZATION  |utilization − optimal_utilization_pct| ≤ 3 (and not crisis)
  ABOVE_KINK           utilization ≥ kink_point (and not optimal, not crisis)
  APPROACHING_KINK     utilization ≥ kink_point × 0.85 (and below kink)
  HEALTHY_ZONE         (default)

CLI
---
  python3 -m spa_core.analytics.defi_protocol_interest_rate_model_analyzer --check
  python3 -m spa_core.analytics.defi_protocol_interest_rate_model_analyzer --run
  python3 -m spa_core.analytics.defi_protocol_interest_rate_model_analyzer --run --data-dir PATH
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _PROJECT_ROOT / "data"

LOG_FILENAME = "interest_rate_model_log.json"
RING_BUFFER_CAP = 100

SCHEMA_VERSION = 1
SOURCE_NAME = "defi_protocol_interest_rate_model_analyzer"
MP_TAG = "MP-1034"

CRISIS_BORROW_RATE_THRESHOLD: float = 25.0   # %
CRISIS_UTILIZATION_THRESHOLD: float = 95.0   # %
OPTIMAL_BAND_PCT: float = 3.0                # ± % around optimal_utilization_pct
APPROACHING_KINK_FACTOR: float = 0.85        # 85 % of kink_point
VOLATILITY_LOW_FACTOR: float = 0.75          # below 75 % of kink → LOW
VOLATILITY_HIGH_FACTOR: float = 1.05         # above 105 % of kink → HIGH

VALID_MODEL_TYPES = {"kink", "linear", "jump", "custom"}

log = logging.getLogger("spa.analytics.defi_protocol_interest_rate_model_analyzer")

# ---------------------------------------------------------------------------
# Core math helpers
# ---------------------------------------------------------------------------


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _compute_borrow_rate(
    model_type: str,
    utilization: float,
    kink_point: float,
    base_rate: float,
    slope1: float,
    slope2: float,
) -> Tuple[float, List[str]]:
    """Compute borrow rate (%) given model parameters.

    Returns (borrow_rate_pct, warnings).
    """
    warnings: List[str] = []
    u = _clamp(utilization, 0.0, 100.0)

    if model_type not in VALID_MODEL_TYPES:
        warnings.append(
            f"Unknown model_type '{model_type}'; falling back to 'kink'."
        )
        model_type = "kink"

    if model_type == "linear":
        rate = base_rate + slope1 * (u / 100.0)
    else:
        # kink / jump / custom — all use the two-slope kink formula
        kink = _clamp(kink_point, 0.1, 99.9)
        if kink_point <= 0.0 or kink_point >= 100.0:
            warnings.append(
                f"kink_point_pct={kink_point} out of valid range (0,100); clamped to {kink}."
            )
        if u <= kink:
            rate = base_rate + slope1 * (u / kink)
        else:
            remaining = 100.0 - kink
            if remaining < 1e-9:
                warnings.append(
                    "kink_point_pct is too close to 100; slope2 segment degenerate."
                )
                rate = base_rate + slope1 + slope2
            else:
                rate = base_rate + slope1 + slope2 * ((u - kink) / remaining)

    rate = max(0.0, rate)
    return rate, warnings


def _compute_supply_rate(borrow_rate: float, utilization: float) -> float:
    """Supply rate = borrow_rate × utilization_fraction (no reserve factor)."""
    return borrow_rate * (utilization / 100.0)


def _compute_utilization_efficiency(
    utilization: float, optimal_utilization: float
) -> float:
    """Score 0–100; peak at optimal_utilization_pct; −2 pt per % deviation."""
    deviation = abs(utilization - optimal_utilization)
    score = 100.0 - 2.0 * deviation
    return _clamp(score, 0.0, 100.0)


def _compute_rate_volatility_risk(utilization: float, kink_point: float) -> str:
    """LOW / MEDIUM / HIGH depending on proximity to kink."""
    kink = _clamp(kink_point, 0.1, 99.9)
    if utilization >= kink * VOLATILITY_HIGH_FACTOR:
        return "HIGH"
    if utilization >= kink * VOLATILITY_LOW_FACTOR:
        return "MEDIUM"
    return "LOW"


def _compute_label(
    utilization: float,
    borrow_rate: float,
    kink_point: float,
    optimal_utilization: float,
) -> str:
    """Assign utilization / rate label (highest priority first)."""
    # 1. Crisis
    if borrow_rate >= CRISIS_BORROW_RATE_THRESHOLD or utilization >= CRISIS_UTILIZATION_THRESHOLD:
        return "CRISIS_RATES"
    # 2. Optimal zone
    if abs(utilization - optimal_utilization) <= OPTIMAL_BAND_PCT:
        return "OPTIMAL_UTILIZATION"
    # 3. Above kink
    if utilization >= kink_point:
        return "ABOVE_KINK"
    # 4. Approaching kink
    if utilization >= kink_point * APPROACHING_KINK_FACTOR:
        return "APPROACHING_KINK"
    # 5. Default
    return "HEALTHY_ZONE"


# ---------------------------------------------------------------------------
# Main analyzer class
# ---------------------------------------------------------------------------


class DeFiProtocolInterestRateModelAnalyzer:
    """Analyze lending protocol interest rate model dynamics.

    Parameters
    ----------
    model_type : str
        One of "kink", "linear", "jump", "custom".
    utilization_rate_pct : float
        Current pool utilization (0–100).
    kink_point_pct : float
        Utilization % at which slope changes (kink/jump/custom models).
    base_rate_pct : float
        Minimum borrow rate at 0 % utilization (%).
    slope1_pct : float
        Rate increase per 1 % utilization in the first segment (%).
    slope2_pct : float
        Rate increase per 1 % utilization above the kink (%).
    optimal_utilization_pct : float
        Protocol's target utilization for efficiency scoring / labelling.
    """

    def __init__(
        self,
        model_type: str = "kink",
        utilization_rate_pct: float = 50.0,
        kink_point_pct: float = 80.0,
        base_rate_pct: float = 0.0,
        slope1_pct: float = 4.0,
        slope2_pct: float = 75.0,
        optimal_utilization_pct: float = 80.0,
    ) -> None:
        self.model_type = model_type.lower().strip() if model_type else "kink"
        self.utilization_rate_pct = float(utilization_rate_pct)
        self.kink_point_pct = float(kink_point_pct)
        self.base_rate_pct = float(base_rate_pct)
        self.slope1_pct = float(slope1_pct)
        self.slope2_pct = float(slope2_pct)
        self.optimal_utilization_pct = float(optimal_utilization_pct)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self) -> Dict[str, Any]:
        """Run the interest rate model analysis.

        Returns a result dict with all computed fields and a label.
        Never raises; degenerate inputs produce warnings in the result.
        """
        warnings: List[str] = []

        # Validate / clamp inputs
        utilization = _clamp(self.utilization_rate_pct, 0.0, 100.0)
        if utilization != self.utilization_rate_pct:
            warnings.append(
                f"utilization_rate_pct={self.utilization_rate_pct} clamped to {utilization}."
            )

        optimal = _clamp(self.optimal_utilization_pct, 0.0, 100.0)
        if optimal != self.optimal_utilization_pct:
            warnings.append(
                f"optimal_utilization_pct={self.optimal_utilization_pct} clamped to {optimal}."
            )

        # Core computations
        borrow_rate, model_warnings = _compute_borrow_rate(
            model_type=self.model_type,
            utilization=utilization,
            kink_point=self.kink_point_pct,
            base_rate=self.base_rate_pct,
            slope1=self.slope1_pct,
            slope2=self.slope2_pct,
        )
        warnings.extend(model_warnings)

        supply_rate = _compute_supply_rate(borrow_rate, utilization)
        spread = borrow_rate - supply_rate
        efficiency = _compute_utilization_efficiency(utilization, optimal)
        volatility_risk = _compute_rate_volatility_risk(utilization, self.kink_point_pct)
        label = _compute_label(utilization, borrow_rate, self.kink_point_pct, optimal)

        return {
            "schema_version": SCHEMA_VERSION,
            "source": SOURCE_NAME,
            "mp_tag": MP_TAG,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "model_type": self.model_type,
            "utilization_rate_pct": round(utilization, 6),
            "kink_point_pct": round(self.kink_point_pct, 6),
            "base_rate_pct": round(self.base_rate_pct, 6),
            "slope1_pct": round(self.slope1_pct, 6),
            "slope2_pct": round(self.slope2_pct, 6),
            "optimal_utilization_pct": round(optimal, 6),
            "borrow_rate_pct": round(borrow_rate, 6),
            "supply_rate_pct": round(supply_rate, 6),
            "spread_pct": round(spread, 6),
            "utilization_efficiency_score": round(efficiency, 4),
            "rate_volatility_risk": volatility_risk,
            "label": label,
            "warnings": warnings,
        }


# ---------------------------------------------------------------------------
# Convenience top-level functions
# ---------------------------------------------------------------------------


def analyze_rate_model(
    model_type: str = "kink",
    utilization_rate_pct: float = 50.0,
    kink_point_pct: float = 80.0,
    base_rate_pct: float = 0.0,
    slope1_pct: float = 4.0,
    slope2_pct: float = 75.0,
    optimal_utilization_pct: float = 80.0,
) -> Dict[str, Any]:
    """Convenience wrapper — single call to analyze and return result."""
    return DeFiProtocolInterestRateModelAnalyzer(
        model_type=model_type,
        utilization_rate_pct=utilization_rate_pct,
        kink_point_pct=kink_point_pct,
        base_rate_pct=base_rate_pct,
        slope1_pct=slope1_pct,
        slope2_pct=slope2_pct,
        optimal_utilization_pct=optimal_utilization_pct,
    ).analyze()


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------


def _load_json_list(path: Path) -> List[Any]:
    """Load a JSON array from *path*; return [] on any error."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, list):
            return data
        log.warning("Expected JSON list in %s, got %s — resetting.", path, type(data))
    except FileNotFoundError:
        pass
    except Exception as exc:  # noqa: BLE001
        log.warning("Could not read %s: %s — resetting.", path, exc)
    return []


def _atomic_write(path: Path, data: Any) -> None:
    """Write *data* as JSON to *path* atomically (tmp + os.replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_save(data, str(path))
def write_log(result: Dict[str, Any], data_dir: Path = _DEFAULT_DATA_DIR) -> Path:
    """Append *result* to the ring-buffer log; return log file path."""
    log_path = data_dir / LOG_FILENAME
    entries = _load_json_list(log_path)
    entries.append(result)
    if len(entries) > RING_BUFFER_CAP:
        entries = entries[-RING_BUFFER_CAP:]
    _atomic_write(log_path, entries)
    return log_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="DeFi Protocol Interest Rate Model Analyzer (MP-1034)"
    )
    p.add_argument("--check", action="store_true", help="Compute and print; no file write.")
    p.add_argument("--run", action="store_true", help="Compute, print, and write to log.")
    p.add_argument("--data-dir", default=str(_DEFAULT_DATA_DIR), help="Path to data/ dir.")
    p.add_argument("--model-type", default="kink", choices=list(VALID_MODEL_TYPES))
    p.add_argument("--utilization", type=float, default=50.0)
    p.add_argument("--kink-point", type=float, default=80.0)
    p.add_argument("--base-rate", type=float, default=0.0)
    p.add_argument("--slope1", type=float, default=4.0)
    p.add_argument("--slope2", type=float, default=75.0)
    p.add_argument("--optimal-utilization", type=float, default=80.0)
    return p


def main(argv: Optional[List[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = _build_parser().parse_args(argv)

    if not args.check and not args.run:
        args.check = True  # default to --check

    result = analyze_rate_model(
        model_type=args.model_type,
        utilization_rate_pct=args.utilization,
        kink_point_pct=args.kink_point,
        base_rate_pct=args.base_rate,
        slope1_pct=args.slope1,
        slope2_pct=args.slope2,
        optimal_utilization_pct=args.optimal_utilization,
    )

    print(json.dumps(result, indent=2))

    if args.run:
        data_dir = Path(args.data_dir)
        log_path = write_log(result, data_dir)
        log.info("Log written → %s", log_path)

    return 0


if __name__ == "__main__":
    sys.exit(main())
