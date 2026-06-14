#!/usr/bin/env python3
"""DeFi Protocol Interest Rate Sensitivity Analyzer (SPA-v769 / MP-1062) — read-only / advisory.

Analyzes how a DeFi lending protocol's borrow/supply rates respond to changes in
utilization, models rate at 80 % and 95 % utilization, computes a sensitivity score
(0–100), and estimates P&L impact for a lender or borrower position.

Design constraints
------------------
* Pure stdlib only — no numpy / scipy / requests / pandas / web3.
* Advisory / read-only: never modifies risk/, execution/, monitoring/, allocator/.
* Atomic writes: tmp + os.replace (POSIX-atomic).
* Ring-buffer log capped at 100 entries → data/interest_rate_sensitivity_log.json.
* Never raises on the happy path; degenerate inputs degrade gracefully with warnings.
* NOT imported from risk/, execution/, monitoring/ (LLM_FORBIDDEN_AGENTS).

Rate Models
-----------
LINEAR:
  borrow_rate = base_rate + slope1 × (util / 100)

KINKED (standard Aave / Compound style):
  util ∈ [0, kink]:  borrow_rate = base_rate + slope1 × (util / kink)
  util ∈ (kink, 100]: borrow_rate = base_rate + slope1 + slope2 × ((util − kink) / (100 − kink))

JUMP:
  Same formula as KINKED — slope2 is expected to be very large, producing a
  characteristic rate "jump" above the kink point.

Supply rate (no-reserve-factor simplification):
  supply_rate = borrow_rate × (util / 100)

Sensitivity score (0–100):
  Derived from the rate "jump" between current utilization and 95 % utilization,
  normalised against a 50 % rate change ceiling.
  score = clamp(delta_95_vs_current / 0.50 × 100, 0, 100)

P&L impact at 80 % utilization:
  For LENDER:   (supply_at_80pct − current_supply_rate) × position_usd × duration_days / 36500
  For BORROWER: (rate_at_80pct  − current_borrow_rate) × position_usd × duration_days / 36500

Sensitivity labels (first match wins):
  EXTREME_RATE_RISK    score ≥ 80
  HIGH_SENSITIVITY     score ≥ 60
  MODERATE_SENSITIVITY score ≥ 40
  LOW_SENSITIVITY      score ≥ 20
  RATE_STABLE          score <  20

CLI
---
  python3 -m spa_core.analytics.defi_protocol_interest_rate_sensitivity_analyzer --check
  python3 -m spa_core.analytics.defi_protocol_interest_rate_sensitivity_analyzer --run
  python3 -m spa_core.analytics.defi_protocol_interest_rate_sensitivity_analyzer --run --data-dir PATH
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _PROJECT_ROOT / "data"

LOG_FILENAME = "interest_rate_sensitivity_log.json"
RING_BUFFER_CAP = 100

SCHEMA_VERSION = 1
SOURCE_NAME = "defi_protocol_interest_rate_sensitivity_analyzer"
MP_TAG = "MP-1062"

UTIL_80: float = 80.0
UTIL_95: float = 95.0
UTIL_100: float = 100.0

# Sensitivity label thresholds (score 0–100)
THRESHOLD_EXTREME: float = 80.0
THRESHOLD_HIGH: float = 60.0
THRESHOLD_MODERATE: float = 40.0
THRESHOLD_LOW: float = 20.0

# Score normalisation: a delta of 50 % point in rate → score 100
SCORE_NORMALISER: float = 50.0  # % point rate change that maps to score = 100

VALID_RATE_MODELS = {"linear", "kinked", "jump"}
VALID_POSITION_TYPES = {"lender", "borrower"}

DAYS_PER_YEAR: float = 365.0

log = logging.getLogger("spa.analytics.defi_protocol_interest_rate_sensitivity_analyzer")

# ---------------------------------------------------------------------------
# Low-level math helpers (importable for tests)
# ---------------------------------------------------------------------------


def _clamp(value: float, lo: float, hi: float) -> float:
    """Clamp *value* to [lo, hi]."""
    return max(lo, min(hi, value))


def _compute_borrow_rate(
    model_type: str,
    utilization: float,
    kink_utilization_pct: float,
    base_rate_pct: float,
    slope1_pct: float,
    slope2_pct: float,
) -> Tuple[float, List[str]]:
    """Return (borrow_rate_pct, warnings) for a given utilization %.

    *utilization* is clamped to [0, 100].
    *kink_utilization_pct* must be in (0, 100); defaults to 80 if degenerate.
    """
    warnings: List[str] = []
    util = _clamp(utilization, 0.0, 100.0)

    # Guard kink
    kink = _clamp(kink_utilization_pct, 1.0, 99.0)
    if kink != kink_utilization_pct:
        warnings.append(f"kink_utilization_pct clamped to {kink}")

    model = (model_type or "kinked").lower()
    if model not in VALID_RATE_MODELS:
        warnings.append(f"Unknown rate_model '{model_type}'; defaulting to 'kinked'")
        model = "kinked"

    if model == "linear":
        rate = base_rate_pct + slope1_pct * (util / 100.0)
    else:
        # kinked / jump — identical formula
        if util <= kink:
            rate = base_rate_pct + slope1_pct * (util / kink)
        else:
            above = (util - kink) / (100.0 - kink) if kink < 100.0 else 0.0
            rate = base_rate_pct + slope1_pct + slope2_pct * above

    rate = max(0.0, rate)
    return rate, warnings


def _compute_supply_rate(borrow_rate_pct: float, utilization_pct: float) -> float:
    """Supply rate = borrow_rate × (utilization / 100), clamped ≥ 0."""
    return max(0.0, borrow_rate_pct * (_clamp(utilization_pct, 0.0, 100.0) / 100.0))


def _compute_sensitivity_score(
    current_rate: float,
    rate_at_95: float,
) -> float:
    """Score 0–100 — measures how much the rate spikes from current to 95 % util.

    delta = rate_at_95 − current_rate
    score = clamp(delta / SCORE_NORMALISER × 100, 0, 100)
    """
    delta = max(0.0, rate_at_95 - current_rate)
    return _clamp(delta / SCORE_NORMALISER * 100.0, 0.0, 100.0)


def _compute_sensitivity_label(score: float) -> str:
    """Return sensitivity label for a score in [0, 100]."""
    if score >= THRESHOLD_EXTREME:
        return "EXTREME_RATE_RISK"
    if score >= THRESHOLD_HIGH:
        return "HIGH_SENSITIVITY"
    if score >= THRESHOLD_MODERATE:
        return "MODERATE_SENSITIVITY"
    if score >= THRESHOLD_LOW:
        return "LOW_SENSITIVITY"
    return "RATE_STABLE"


def _compute_pnl_impact(
    rate_at_80_pct: float,
    current_rate_pct: float,
    position_usd: float,
    duration_days: float,
    position_type: str,
    current_borrow_rate_pct: float,
    current_supply_rate_pct: float,
    utilization_at_80: float,
) -> float:
    """Return estimated P&L impact (USD) if utilization moves to 80 %.

    Positive = gain; negative = loss.

    For LENDER:   supply_at_80pct  vs current_supply_rate
    For BORROWER: borrow_at_80pct  vs current_borrow_rate
    """
    days = max(0.0, duration_days)
    usd = max(0.0, position_usd)

    if position_type == "lender":
        supply_at_80 = _compute_supply_rate(rate_at_80_pct, utilization_at_80)
        delta = supply_at_80 - current_supply_rate_pct
    else:
        # borrower: positive delta = higher cost = negative PnL
        delta = -(rate_at_80_pct - current_borrow_rate_pct)

    return delta / 100.0 * usd * days / DAYS_PER_YEAR


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------


def _load_json_list(path: Path) -> List[Any]:
    """Load a JSON list from *path*; return [] on any error."""
    try:
        text = path.read_text(encoding="utf-8")
        data = json.loads(text)
        if isinstance(data, list):
            return data
        return []
    except Exception:
        return []


def _atomic_write(path: Path, data: Any) -> None:
    """Atomically write JSON to *path* via tmp + os.replace."""
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
# Public API — analyze
# ---------------------------------------------------------------------------


def analyze_interest_rate_sensitivity(params: Dict[str, Any]) -> Dict[str, Any]:
    """Analyse interest rate sensitivity for a DeFi lending protocol position.

    Parameters
    ----------
    params : dict with keys
        protocol_name          str  — protocol identifier
        current_borrow_rate_pct float
        current_supply_rate_pct float
        utilization_rate_pct   float — current utilization (0–100)
        rate_model             str   — "linear" | "kinked" | "jump"
        kink_utilization_pct   float — kink point (ignored for linear)
        base_rate_pct          float
        slope1_pct             float
        slope2_pct             float — above-kink slope (ignored for linear)
        position_type          str   — "lender" | "borrower"
        position_usd           float
        duration_days          float

    Returns
    -------
    dict with keys
        protocol_name           str
        rate_at_80pct_util_pct  float
        rate_at_95pct_util_pct  float
        max_rate_pct            float  (rate at 100 % util)
        rate_sensitivity_score  float  (0–100)
        pnl_impact_at_80pct_usd float
        sensitivity_label       str
        warnings                list[str]
        timestamp_utc           str
        schema_version          int
        source                  str
        mp_tag                  str
    """
    warnings: List[str] = []

    # -- extract + validate inputs ------------------------------------------
    protocol_name = str(params.get("protocol_name", "unknown"))

    def _pct(key: str, default: float = 0.0) -> float:
        val = params.get(key, default)
        try:
            return float(val)
        except (TypeError, ValueError):
            warnings.append(f"Non-numeric value for '{key}'; using {default}")
            return default

    current_borrow = _pct("current_borrow_rate_pct")
    current_supply = _pct("current_supply_rate_pct")
    current_util = _clamp(_pct("utilization_rate_pct", 70.0), 0.0, 100.0)
    kink_util = _clamp(_pct("kink_utilization_pct", 80.0), 1.0, 99.0)
    base_rate = _pct("base_rate_pct")
    slope1 = _pct("slope1_pct")
    slope2 = _pct("slope2_pct")
    position_usd = max(0.0, _pct("position_usd"))
    duration_days = max(0.0, _pct("duration_days", 30.0))

    rate_model_raw = str(params.get("rate_model", "kinked")).lower().strip()
    if rate_model_raw not in VALID_RATE_MODELS:
        warnings.append(f"Unknown rate_model '{rate_model_raw}'; defaulting to 'kinked'")
        rate_model_raw = "kinked"

    position_type = str(params.get("position_type", "lender")).lower().strip()
    if position_type not in VALID_POSITION_TYPES:
        warnings.append(f"Unknown position_type '{position_type}'; defaulting to 'lender'")
        position_type = "lender"

    # -- compute rates at key utilization points ----------------------------
    rate_at_80, w80 = _compute_borrow_rate(
        rate_model_raw, UTIL_80, kink_util, base_rate, slope1, slope2
    )
    warnings.extend(w80)

    rate_at_95, w95 = _compute_borrow_rate(
        rate_model_raw, UTIL_95, kink_util, base_rate, slope1, slope2
    )
    warnings.extend(w95)

    max_rate, wmax = _compute_borrow_rate(
        rate_model_raw, UTIL_100, kink_util, base_rate, slope1, slope2
    )
    warnings.extend(wmax)

    # -- sensitivity score & label -----------------------------------------
    score = _compute_sensitivity_score(current_borrow, rate_at_95)
    label = _compute_sensitivity_label(score)

    # -- P&L impact --------------------------------------------------------
    pnl = _compute_pnl_impact(
        rate_at_80_pct=rate_at_80,
        current_rate_pct=rate_at_80,     # kept for signature clarity
        position_usd=position_usd,
        duration_days=duration_days,
        position_type=position_type,
        current_borrow_rate_pct=current_borrow,
        current_supply_rate_pct=current_supply,
        utilization_at_80=UTIL_80,
    )

    return {
        "protocol_name": protocol_name,
        "rate_at_80pct_util_pct": round(rate_at_80, 6),
        "rate_at_95pct_util_pct": round(rate_at_95, 6),
        "max_rate_pct": round(max_rate, 6),
        "rate_sensitivity_score": round(score, 4),
        "pnl_impact_at_80pct_usd": round(pnl, 4),
        "sensitivity_label": label,
        "warnings": warnings,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "schema_version": SCHEMA_VERSION,
        "source": SOURCE_NAME,
        "mp_tag": MP_TAG,
    }


def write_log(result: Dict[str, Any], data_dir: Optional[Path] = None) -> Path:
    """Append *result* to ring-buffer log (≤ RING_BUFFER_CAP entries).

    Returns path to the log file.
    """
    base = data_dir or _DEFAULT_DATA_DIR
    log_path = Path(base) / LOG_FILENAME
    existing = _load_json_list(log_path)
    existing.append(result)
    if len(existing) > RING_BUFFER_CAP:
        existing = existing[-RING_BUFFER_CAP:]
    _atomic_write(log_path, existing)
    return log_path


# ---------------------------------------------------------------------------
# Main class (thin wrapper for ergonomics)
# ---------------------------------------------------------------------------


class DeFiProtocolInterestRateSensitivityAnalyzer:
    """Advisory wrapper around :func:`analyze_interest_rate_sensitivity`.

    Usage::

        analyzer = DeFiProtocolInterestRateSensitivityAnalyzer()
        result = analyzer.analyze(params_dict)
        analyzer.save(result)          # appends to ring-buffer log
    """

    def __init__(self, data_dir: Optional[Path] = None) -> None:
        self._data_dir = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR

    # ------------------------------------------------------------------
    def analyze(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Run sensitivity analysis. Returns result dict."""
        return analyze_interest_rate_sensitivity(params)

    def save(self, result: Dict[str, Any]) -> Path:
        """Write result to ring-buffer log. Returns log path."""
        return write_log(result, self._data_dir)

    def analyze_and_save(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Convenience: analyze then save. Returns result dict."""
        result = self.analyze(params)
        self.save(result)
        return result


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

_DEMO_PARAMS: Dict[str, Any] = {
    "protocol_name": "Aave V3 (demo)",
    "current_borrow_rate_pct": 4.5,
    "current_supply_rate_pct": 3.0,
    "utilization_rate_pct": 72.0,
    "rate_model": "kinked",
    "kink_utilization_pct": 80.0,
    "base_rate_pct": 0.0,
    "slope1_pct": 4.0,
    "slope2_pct": 75.0,
    "position_type": "lender",
    "position_usd": 100_000.0,
    "duration_days": 30.0,
}


def _main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="DeFi Protocol Interest Rate Sensitivity Analyzer (MP-1062)"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Compute and print; do NOT write log (default mode)",
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="Compute, print, AND write to log file",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help="Override data directory (default: <repo>/data/)",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    data_dir = Path(args.data_dir) if args.data_dir else None
    analyzer = DeFiProtocolInterestRateSensitivityAnalyzer(data_dir=data_dir)
    result = analyzer.analyze(_DEMO_PARAMS)

    print(json.dumps(result, indent=2, ensure_ascii=False))

    if args.run:
        log_path = analyzer.save(result)
        print(f"\n✓ Log written → {log_path}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(_main())
