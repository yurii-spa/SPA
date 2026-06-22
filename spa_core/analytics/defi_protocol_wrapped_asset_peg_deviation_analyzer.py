#!/usr/bin/env python3
"""DeFi Protocol Wrapped Asset Peg Deviation Analyzer (SPA-V784 / MP-1092).

Monitors peg deviation for wrapped/staked/synthetic assets (wstETH, cbETH,
rETH, stETH vs ETH; USDC vs USDT; etc.). Large deviations signal depeg risk
or redemption mechanism failure.

Design constraints
------------------
* Pure stdlib only — no numpy / scipy / requests / pandas / web3.
* Advisory / read-only: never modifies risk/, execution/, monitoring/, allocator/.
* Atomic writes: tmp + os.replace (POSIX-atomic).
* Ring-buffer log capped at 100 entries in data/wrapped_asset_peg_deviation_log.json.
* Never raises on the happy path; degenerate inputs degrade gracefully.
* NOT imported from risk/, execution/, monitoring/ (LLM_FORBIDDEN_AGENTS).

Peg deviation computation
-------------------------
  observed_ratio     = wrapped_price_usd / underlying_price_usd
  peg_deviation_pct  = (observed_ratio - expected_ratio) / expected_ratio * 100  (signed)
  abs_deviation_pct  = abs(peg_deviation_pct)

  Label (by abs_deviation_pct):
    ON_PEG             abs < 0.1%
    SLIGHT_DEVIATION   0.1% <= abs < 0.5%
    MODERATE_DEPEG     0.5% <= abs < 2.0%
    SEVERE_DEPEG       2.0% <= abs < 5.0%
    CRITICAL_DEPEG     abs >= 5.0%

  Risk score (0-100, higher = more risk):
    Base score from abs_deviation_pct (linear interpolation per band):
      [0, 0.1%)   -> [0, 10)
      [0.1, 0.5%) -> [10, 30)
      [0.5, 2.0%) -> [30, 60)
      [2.0, 5.0%) -> [60, 85)
      [5.0, inf)  -> [85, 100]  (clamps at 10% above severe threshold)
    Modifiers (cumulative, capped at 100):
      redemption disabled           -> +10
      redemption_pressure > 0.5     -> +10
      redemption_pressure > 0.1     -> +5  (exclusive with above)

  redemption_pressure_ratio = daily_redemption_volume_usd / protocol_tvl_usd
  (returns 0.0 if tvl <= 0)

CLI
---
  python3 -m spa_core.analytics.defi_protocol_wrapped_asset_peg_deviation_analyzer --check
  python3 -m spa_core.analytics.defi_protocol_wrapped_asset_peg_deviation_analyzer --run
  python3 -m spa_core.analytics.defi_protocol_wrapped_asset_peg_deviation_analyzer --run --data-dir PATH
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from spa_core.utils.atomic import atomic_save
from spa_core.base import BaseAnalytics

# ---------------------------------------------------------------------------
# Constants & paths
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _PROJECT_ROOT / "data"

LOG_FILENAME = "wrapped_asset_peg_deviation_log.json"
RING_BUFFER_CAP = 100

SCHEMA_VERSION = 1
SOURCE_NAME = "defi_protocol_wrapped_asset_peg_deviation_analyzer"
MP_TAG = "MP-1092"

# Peg label thresholds (abs deviation %)
LABEL_ON_PEG_MAX: float = 0.1
LABEL_SLIGHT_MAX: float = 0.5
LABEL_MODERATE_MAX: float = 2.0
LABEL_SEVERE_MAX: float = 5.0

# Risk score band boundary scores
SCORE_AT_ON_PEG_MAX: int = 10       # score at abs_dev == 0.1 (boundary: SLIGHT_DEVIATION)
SCORE_AT_SLIGHT_MAX: int = 30       # score at abs_dev == 0.5 (boundary: MODERATE_DEPEG)
SCORE_AT_MODERATE_MAX: int = 60     # score at abs_dev == 2.0 (boundary: SEVERE_DEPEG)
SCORE_AT_SEVERE_MAX: int = 85       # score at abs_dev == 5.0 (boundary: CRITICAL_DEPEG)
SCORE_MAX: int = 100

# Upper limit of extra deviation credited above SEVERE_MAX for score interpolation
_CRITICAL_EXTRA_RANGE: float = 5.0  # +5% above threshold => score 100

# Redemption pressure modifier thresholds
REDEMPTION_PRESSURE_HIGH: float = 0.5
REDEMPTION_PRESSURE_MED: float = 0.1

log = logging.getLogger("spa.analytics.defi_protocol_wrapped_asset_peg_deviation_analyzer")


# ---------------------------------------------------------------------------
# Core computation helpers (public for unit testing)
# ---------------------------------------------------------------------------


def compute_observed_ratio(wrapped_price_usd: float, underlying_price_usd: float) -> float:
    """Compute wrapped/underlying price ratio.

    Raises ValueError if underlying_price_usd <= 0.
    """
    if underlying_price_usd <= 0.0:
        raise ValueError(
            f"underlying_price_usd must be > 0, got {underlying_price_usd}"
        )
    return wrapped_price_usd / underlying_price_usd


def compute_peg_deviation_pct(observed_ratio: float, expected_ratio: float) -> float:
    """Compute signed peg deviation as a percentage.

    peg_deviation_pct = (observed_ratio - expected_ratio) / expected_ratio * 100

    Raises ValueError if expected_ratio <= 0.
    """
    if expected_ratio <= 0.0:
        raise ValueError(f"expected_ratio must be > 0, got {expected_ratio}")
    return (observed_ratio - expected_ratio) / expected_ratio * 100.0


def compute_redemption_pressure_ratio(
    daily_redemption_volume_usd: float,
    protocol_tvl_usd: float,
) -> float:
    """Compute daily redemption volume relative to TVL.

    Returns 0.0 if tvl <= 0 (safe default).
    """
    if protocol_tvl_usd <= 0.0:
        return 0.0
    return daily_redemption_volume_usd / protocol_tvl_usd


def peg_label(abs_deviation_pct: float) -> str:
    """Classify peg quality by absolute deviation percentage.

    Thresholds (exclusive upper bounds):
      < 0.1%  -> ON_PEG
      < 0.5%  -> SLIGHT_DEVIATION
      < 2.0%  -> MODERATE_DEPEG
      < 5.0%  -> SEVERE_DEPEG
      >= 5.0% -> CRITICAL_DEPEG
    """
    if abs_deviation_pct < LABEL_ON_PEG_MAX:
        return "ON_PEG"
    if abs_deviation_pct < LABEL_SLIGHT_MAX:
        return "SLIGHT_DEVIATION"
    if abs_deviation_pct < LABEL_MODERATE_MAX:
        return "MODERATE_DEPEG"
    if abs_deviation_pct < LABEL_SEVERE_MAX:
        return "SEVERE_DEPEG"
    return "CRITICAL_DEPEG"


def peg_risk_score(
    abs_deviation_pct: float,
    redemption_enabled: bool,
    redemption_pressure_ratio: float,
) -> int:
    """Compute peg risk score 0-100 (higher = more risk).

    Base score via linear interpolation within each band, then add modifiers.

    Band boundaries (score at threshold = left edge of next band):
      abs_dev=0.0   -> 0
      abs_dev=0.1   -> 10   (SLIGHT boundary)
      abs_dev=0.5   -> 30   (MODERATE boundary)
      abs_dev=2.0   -> 60   (SEVERE boundary)
      abs_dev=5.0   -> 85   (CRITICAL boundary)
      abs_dev>=10.0 -> 100  (capped)

    Modifiers (cumulative):
      redemption disabled           -> +10
      redemption_pressure > 0.5     -> +10
      redemption_pressure > 0.1     -> +5  (exclusive; only if <=0.5)
    """
    # --- Base score ---
    if abs_deviation_pct < LABEL_ON_PEG_MAX:
        t = abs_deviation_pct / LABEL_ON_PEG_MAX
        base = round(t * SCORE_AT_ON_PEG_MAX)
    elif abs_deviation_pct < LABEL_SLIGHT_MAX:
        t = (abs_deviation_pct - LABEL_ON_PEG_MAX) / (LABEL_SLIGHT_MAX - LABEL_ON_PEG_MAX)
        base = round(SCORE_AT_ON_PEG_MAX + t * (SCORE_AT_SLIGHT_MAX - SCORE_AT_ON_PEG_MAX))
    elif abs_deviation_pct < LABEL_MODERATE_MAX:
        t = (abs_deviation_pct - LABEL_SLIGHT_MAX) / (LABEL_MODERATE_MAX - LABEL_SLIGHT_MAX)
        base = round(SCORE_AT_SLIGHT_MAX + t * (SCORE_AT_MODERATE_MAX - SCORE_AT_SLIGHT_MAX))
    elif abs_deviation_pct < LABEL_SEVERE_MAX:
        t = (abs_deviation_pct - LABEL_MODERATE_MAX) / (LABEL_SEVERE_MAX - LABEL_MODERATE_MAX)
        base = round(SCORE_AT_MODERATE_MAX + t * (SCORE_AT_SEVERE_MAX - SCORE_AT_MODERATE_MAX))
    else:
        t = min(
            (abs_deviation_pct - LABEL_SEVERE_MAX) / _CRITICAL_EXTRA_RANGE,
            1.0,
        )
        base = round(SCORE_AT_SEVERE_MAX + t * (SCORE_MAX - SCORE_AT_SEVERE_MAX))

    # --- Modifiers ---
    modifier = 0
    if not redemption_enabled:
        modifier += 10
    if redemption_pressure_ratio > REDEMPTION_PRESSURE_HIGH:
        modifier += 10
    elif redemption_pressure_ratio > REDEMPTION_PRESSURE_MED:
        modifier += 5

    return min(SCORE_MAX, base + modifier)


# ---------------------------------------------------------------------------
# Main analysis function (module-level)
# ---------------------------------------------------------------------------


def analyze(
    wrapped_price_usd: float,
    underlying_price_usd: float,
    expected_ratio: float,
    redemption_enabled: bool,
    protocol_tvl_usd: float,
    daily_redemption_volume_usd: float,
    asset_name: str,
    protocol_name: str,
) -> Dict[str, Any]:
    """Analyze peg deviation for a single wrapped/synthetic asset.

    Parameters
    ----------
    wrapped_price_usd:
        Current price of the wrapped asset in USD (e.g. stETH price in USD).
    underlying_price_usd:
        Current price of the underlying asset in USD (e.g. ETH price in USD).
    expected_ratio:
        Theoretical wrapped/underlying ratio (e.g. 1.0 for stETH, ~1.15 for
        wstETH based on rebasing accumulation).
    redemption_enabled:
        Whether users can redeem wrapped->underlying 1:1 on-chain.
    protocol_tvl_usd:
        Total value locked in the protocol (USD).
    daily_redemption_volume_usd:
        Daily redemption volume (USD).
    asset_name:
        Human-readable name of the wrapped asset (e.g. "stETH", "wstETH").
    protocol_name:
        Name of the issuing protocol (e.g. "Lido", "Coinbase", "RocketPool").

    Returns
    -------
    Dict containing all computed outputs plus raw inputs and metadata.
    """
    timestamp = datetime.now(timezone.utc).isoformat()

    observed_ratio = compute_observed_ratio(wrapped_price_usd, underlying_price_usd)
    peg_deviation_pct_val = compute_peg_deviation_pct(observed_ratio, expected_ratio)
    abs_deviation_pct_val = abs(peg_deviation_pct_val)
    redemption_pressure_ratio = compute_redemption_pressure_ratio(
        daily_redemption_volume_usd, protocol_tvl_usd
    )
    label = peg_label(abs_deviation_pct_val)
    risk_score = peg_risk_score(
        abs_deviation_pct_val, redemption_enabled, redemption_pressure_ratio
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "source": SOURCE_NAME,
        "mp_tag": MP_TAG,
        "timestamp": timestamp,
        "asset_name": str(asset_name),
        "protocol_name": str(protocol_name),
        # Raw inputs echoed
        "wrapped_price_usd": float(wrapped_price_usd),
        "underlying_price_usd": float(underlying_price_usd),
        "expected_ratio": float(expected_ratio),
        "redemption_enabled": bool(redemption_enabled),
        "protocol_tvl_usd": float(protocol_tvl_usd),
        "daily_redemption_volume_usd": float(daily_redemption_volume_usd),
        # Computed outputs
        "observed_ratio": round(observed_ratio, 8),
        "peg_deviation_pct": round(peg_deviation_pct_val, 6),
        "abs_deviation_pct": round(abs_deviation_pct_val, 6),
        "redemption_pressure_ratio": round(redemption_pressure_ratio, 8),
        "peg_risk_score": risk_score,
        "peg_label": label,
    }


# ---------------------------------------------------------------------------
# Stateful class
# ---------------------------------------------------------------------------


class DeFiProtocolWrappedAssetPegDeviationAnalyzer(BaseAnalytics):
    OUTPUT_PATH = "data/defi_wrapped_peg_deviation.json"
    """Stateful analyzer that accumulates results into a ring-buffer log.

    Usage
    -----
    ::

        analyzer = DeFiProtocolWrappedAssetPegDeviationAnalyzer(data_dir="/path/to/data")
        result   = analyzer.analyze(
            wrapped_price_usd=3198.0,
            underlying_price_usd=3200.0,
            expected_ratio=1.0,
            redemption_enabled=True,
            protocol_tvl_usd=15_000_000_000,
            daily_redemption_volume_usd=50_000_000,
            asset_name="stETH",
            protocol_name="Lido",
        )
        label = result["peg_label"]   # e.g. "ON_PEG"
        score = result["peg_risk_score"]
        analyzer.save()  # atomic ring-buffer append
    """

    def __init__(
        self,
        data_dir: Optional["Path | str"] = None,
        ring_cap: int = RING_BUFFER_CAP,
    ) -> None:
        self._data_dir = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR
        self._ring_cap = ring_cap
        self._last_result: Optional[Dict[str, Any]] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(
        self,
        wrapped_price_usd: float,
        underlying_price_usd: float,
        expected_ratio: float,
        redemption_enabled: bool,
        protocol_tvl_usd: float,
        daily_redemption_volume_usd: float,
        asset_name: str,
        protocol_name: str,
    ) -> Dict[str, Any]:
        """Run peg deviation analysis and cache the result for save()."""
        result = analyze(
            wrapped_price_usd=wrapped_price_usd,
            underlying_price_usd=underlying_price_usd,
            expected_ratio=expected_ratio,
            redemption_enabled=redemption_enabled,
            protocol_tvl_usd=protocol_tvl_usd,
            daily_redemption_volume_usd=daily_redemption_volume_usd,
            asset_name=asset_name,
            protocol_name=protocol_name,
        )
        self._last_result = result
        return result

    def get_last_result(self) -> Optional[Dict[str, Any]]:
        """Return the result from the last analyze() call, or None."""
        return self._last_result

    def save(self) -> bool:
        """Atomically append last result to the ring-buffer log file.

        Returns True on success, False on any error (never raises).
        """
        if self._last_result is None:
            log.warning("save() called before analyze() — nothing to write")
            return False
        try:
            log_path = self._data_dir / LOG_FILENAME
            existing: List[Dict[str, Any]] = _load_json_list(log_path)
            existing.append(self._last_result)
            if len(existing) > self._ring_cap:
                existing = existing[-self._ring_cap:]
            _atomic_write(log_path, existing)
            log.info(
                "wrapped_asset_peg_deviation_log written (%d entries)", len(existing)
            )
            return True
        except Exception as exc:  # noqa: BLE001
            log.error("save() failed: %s", exc)
            return False


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------



    def to_dict(self) -> dict:
        """Return internal state as a plain dict. LLM FORBIDDEN."""
        return getattr(self, '_data', {})

def _load_json_list(path: Path) -> List[Any]:
    """Load a JSON list from *path*; return [] on any error."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
            return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []


def _atomic_write(path: Path, data: Any) -> None:
    """Write *data* as JSON to *path* atomically via tmp + os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_save(data, str(path))
# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="defi_protocol_wrapped_asset_peg_deviation_analyzer",
        description="MP-1092 DeFi Wrapped Asset Peg Deviation Analyzer",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check",
        action="store_true",
        default=True,
        help="Compute and print; do NOT write to disk (default)",
    )
    mode.add_argument(
        "--run",
        action="store_true",
        default=False,
        help="Compute, print, and atomically write last result to log file",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help="Override default data/ directory path",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> None:
    """CLI entry-point — exit 0 always (pure advisory)."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    parser = _build_cli_parser()
    args = parser.parse_args(argv)
    data_dir = Path(args.data_dir) if args.data_dir else _DEFAULT_DATA_DIR
    write_mode: bool = args.run

    # Demo cases covering all peg label categories
    demo_cases = [
        {
            "asset_name": "stETH",
            "protocol_name": "Lido",
            "wrapped_price_usd": 3198.0,
            "underlying_price_usd": 3200.0,
            "expected_ratio": 1.0,
            "redemption_enabled": True,
            "protocol_tvl_usd": 15_000_000_000,
            "daily_redemption_volume_usd": 50_000_000,
        },
        {
            "asset_name": "wstETH",
            "protocol_name": "Lido",
            "wrapped_price_usd": 3740.0,
            "underlying_price_usd": 3200.0,
            "expected_ratio": 1.15,
            "redemption_enabled": True,
            "protocol_tvl_usd": 10_000_000_000,
            "daily_redemption_volume_usd": 20_000_000,
        },
        {
            "asset_name": "cbETH",
            "protocol_name": "Coinbase",
            "wrapped_price_usd": 3100.0,
            "underlying_price_usd": 3200.0,
            "expected_ratio": 1.0,
            "redemption_enabled": False,
            "protocol_tvl_usd": 2_000_000_000,
            "daily_redemption_volume_usd": 5_000_000,
        },
        {
            "asset_name": "rETH",
            "protocol_name": "RocketPool",
            "wrapped_price_usd": 3040.0,
            "underlying_price_usd": 3200.0,
            "expected_ratio": 1.0,
            "redemption_enabled": True,
            "protocol_tvl_usd": 3_000_000_000,
            "daily_redemption_volume_usd": 10_000_000,
        },
    ]

    analyzer = DeFiProtocolWrappedAssetPegDeviationAnalyzer(data_dir=data_dir)
    results = []
    for case in demo_cases:
        r = analyzer.analyze(**case)
        results.append(r)

    print(json.dumps(results, indent=2, ensure_ascii=False))

    if write_mode:
        ok = analyzer.save()
        status_str = "OK" if ok else "FAILED"
        print(f"[{SOURCE_NAME}] save: {status_str}", file=sys.stderr)

    sys.exit(0)


if __name__ == "__main__":
    main()
