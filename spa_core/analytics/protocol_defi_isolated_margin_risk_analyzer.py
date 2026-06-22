#!/usr/bin/env python3
"""DeFi Isolated Margin Risk Analyzer (SPA-V755 / MP-1035) — read-only / advisory.

Analyzes risk in isolated margin positions (e.g., Morpho, Euler isolated markets).
Computes health score, margin of safety, liquidation price, and time-to-liquidation
estimates from position parameters.

Design constraints
------------------
* Pure stdlib only — no numpy / scipy / requests / pandas / web3.
* Advisory / read-only: never modifies risk/, execution/, monitoring/, allocator/.
* Atomic writes: tmp + os.replace (POSIX-atomic).
* Ring-buffer log capped at 100 entries → data/isolated_margin_risk_log.json.
* Never raises on the happy path; degenerate inputs degrade gracefully with warnings.
* NOT imported from risk/, execution/, monitoring/ (LLM_FORBIDDEN_AGENTS).

Key Computations
----------------
collateral_amount (units):
  collateral_amount = collateral_value_usd / oracle_price_usd
  (number of collateral tokens held)

Liquidation price:
  Liquidation occurs when:
    collateral_amount × liquidation_price × liquidation_ltv = borrow_value_usd
  ∴ liquidation_price_usd = borrow_value_usd / (collateral_amount × liquidation_ltv)
                           = borrow_value_usd × oracle_price_usd
                             / (collateral_value_usd × liquidation_ltv)

Margin of safety:
  margin_of_safety_pct = (oracle_price_usd − liquidation_price_usd)
                          / oracle_price_usd × 100
  (% price drop that triggers liquidation)

Health score (0–100):
  Derived from health_factor using a piecewise mapping:
    HF ≤ 1.0:  score = max(0,  HF × 20)           (0–20; at or below liquidation)
    1.0<HF≤2.0: score = 20 + (HF − 1.0) × 40       (20–60; warning to moderate)
    2.0<HF≤3.0: score = 60 + (HF − 2.0) × 30       (60–90; moderate to safe)
    HF > 3.0:  score = 90 + min(10, (HF − 3.0) × 5) (90–100; fortress)

  Then, if collateral_volatility_30d_pct > 30 %, penalise score by
  min(10, (volatility − 30) × 0.5) points (high-vol collateral is riskier).

time_to_liquidation_days:
  Uses the caller-supplied days_to_liquidation_at_trend directly.
  If ≤ 0 or health_factor < 1.0: set to 0 (already liquidatable).
  If health_factor > 3.0 and trend is positive: may be set to None (no threat).

Labels (first matching wins, highest priority first):
  LIQUIDATION_IMMINENT  health_factor < 1.1  OR  time_to_liquidation_days ≤ 3
  WARNING               health_factor < 1.3  OR  time_to_liquidation_days ≤ 14
  MONITOR               health_factor < 1.6  OR  margin_of_safety_pct < 15
  SAFE                  health_factor < 2.5  OR  margin_of_safety_pct < 30
  FORTRESS_POSITION     (default)

CLI
---
  python3 -m spa_core.analytics.protocol_defi_isolated_margin_risk_analyzer --check
  python3 -m spa_core.analytics.protocol_defi_isolated_margin_risk_analyzer --run
  python3 -m spa_core.analytics.protocol_defi_isolated_margin_risk_analyzer --run --data-dir PATH
"""
from __future__ import annotations

import argparse
import json
import logging
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

LOG_FILENAME = "isolated_margin_risk_log.json"
RING_BUFFER_CAP = 100

SCHEMA_VERSION = 1
SOURCE_NAME = "protocol_defi_isolated_margin_risk_analyzer"
MP_TAG = "MP-1035"

# Label thresholds
LIQUIDATION_IMMINENT_HF: float = 1.1
LIQUIDATION_IMMINENT_DAYS: int = 3
WARNING_HF: float = 1.3
WARNING_DAYS: int = 14
MONITOR_HF: float = 1.6
MONITOR_MARGIN: float = 15.0    # %
SAFE_HF: float = 2.5
SAFE_MARGIN: float = 30.0       # %

# Volatility penalty
VOL_PENALTY_THRESHOLD: float = 30.0   # % — above this, apply score penalty
VOL_PENALTY_RATE: float = 0.5         # pts penalty per % vol above threshold
VOL_PENALTY_MAX: float = 10.0         # max penalty pts

# Health score piecewise breakpoints
HS_BAND1_HF: float = 1.0   # HF ≤ 1.0 → 0–20 pts
HS_BAND2_HF: float = 2.0   # HF ≤ 2.0 → 20–60 pts
HS_BAND3_HF: float = 3.0   # HF ≤ 3.0 → 60–90 pts
                            # HF > 3.0 → 90–100 pts

log = logging.getLogger("spa.analytics.protocol_defi_isolated_margin_risk_analyzer")

# ---------------------------------------------------------------------------
# Core math helpers
# ---------------------------------------------------------------------------


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _compute_liquidation_price(
    collateral_value_usd: float,
    borrow_value_usd: float,
    oracle_price_usd: float,
    liquidation_ltv: float,
) -> Tuple[Optional[float], List[str]]:
    """Return (liquidation_price_usd, warnings).

    liquidation_price_usd = borrow_value_usd × oracle_price_usd
                            / (collateral_value_usd × liquidation_ltv)
    """
    warnings: List[str] = []

    if collateral_value_usd <= 0.0:
        warnings.append("collateral_value_usd ≤ 0; liquidation_price indeterminate.")
        return None, warnings
    if liquidation_ltv <= 0.0:
        warnings.append("liquidation_ltv ≤ 0; liquidation_price indeterminate.")
        return None, warnings
    if oracle_price_usd <= 0.0:
        warnings.append("oracle_price_usd ≤ 0; liquidation_price indeterminate.")
        return None, warnings

    liq_price = borrow_value_usd * oracle_price_usd / (collateral_value_usd * liquidation_ltv)
    return liq_price, warnings


def _compute_margin_of_safety(
    oracle_price_usd: float,
    liquidation_price_usd: Optional[float],
) -> Tuple[Optional[float], List[str]]:
    """Return (margin_of_safety_pct, warnings).

    margin_of_safety_pct = (oracle_price − liq_price) / oracle_price × 100
    """
    warnings: List[str] = []

    if liquidation_price_usd is None:
        warnings.append("liquidation_price is None; margin_of_safety indeterminate.")
        return None, warnings
    if oracle_price_usd <= 0.0:
        warnings.append("oracle_price_usd ≤ 0; margin_of_safety indeterminate.")
        return None, warnings

    margin = (oracle_price_usd - liquidation_price_usd) / oracle_price_usd * 100.0
    return margin, warnings


def _compute_health_score(
    health_factor: float,
    collateral_volatility_30d_pct: float,
) -> float:
    """Piecewise health score 0–100, penalised for high collateral volatility."""
    hf = max(0.0, health_factor)

    if hf <= HS_BAND1_HF:
        score = hf * 20.0
    elif hf <= HS_BAND2_HF:
        score = 20.0 + (hf - HS_BAND1_HF) * 40.0
    elif hf <= HS_BAND3_HF:
        score = 60.0 + (hf - HS_BAND2_HF) * 30.0
    else:
        score = 90.0 + min(VOL_PENALTY_MAX, (hf - HS_BAND3_HF) * 5.0)

    # Volatility penalty
    vol = max(0.0, collateral_volatility_30d_pct)
    if vol > VOL_PENALTY_THRESHOLD:
        penalty = min(VOL_PENALTY_MAX, (vol - VOL_PENALTY_THRESHOLD) * VOL_PENALTY_RATE)
        score -= penalty

    return _clamp(score, 0.0, 100.0)


def _compute_time_to_liquidation(
    health_factor: float,
    days_to_liquidation_at_trend: Optional[float],
) -> Optional[float]:
    """Determine effective time-to-liquidation in days.

    * Already liquidatable (HF < 1) → 0.
    * Trend supplied and > 0 → use as-is.
    * Trend ≤ 0 → 0 (no convergence / already there).
    * Trend None → None (unknown).
    """
    if health_factor < 1.0:
        return 0.0

    if days_to_liquidation_at_trend is None:
        return None

    if days_to_liquidation_at_trend <= 0:
        return 0.0

    return float(days_to_liquidation_at_trend)


def _compute_label(
    health_factor: float,
    margin_of_safety_pct: Optional[float],
    time_to_liquidation_days: Optional[float],
) -> str:
    """Assign risk label (highest priority / most severe first)."""
    margin = margin_of_safety_pct if margin_of_safety_pct is not None else 0.0
    ttl = time_to_liquidation_days  # may be None

    # 1. Liquidation imminent
    imminent_by_hf = health_factor < LIQUIDATION_IMMINENT_HF
    imminent_by_ttl = ttl is not None and ttl <= LIQUIDATION_IMMINENT_DAYS
    if imminent_by_hf or imminent_by_ttl:
        return "LIQUIDATION_IMMINENT"

    # 2. Warning
    warning_by_hf = health_factor < WARNING_HF
    warning_by_ttl = ttl is not None and ttl <= WARNING_DAYS
    if warning_by_hf or warning_by_ttl:
        return "WARNING"

    # 3. Monitor
    monitor_by_hf = health_factor < MONITOR_HF
    monitor_by_margin = margin < MONITOR_MARGIN
    if monitor_by_hf or monitor_by_margin:
        return "MONITOR"

    # 4. Safe
    safe_by_hf = health_factor < SAFE_HF
    safe_by_margin = margin < SAFE_MARGIN
    if safe_by_hf or safe_by_margin:
        return "SAFE"

    # 5. Fortress
    return "FORTRESS_POSITION"


# ---------------------------------------------------------------------------
# Main analyzer class
# ---------------------------------------------------------------------------


class ProtocolDeFiIsolatedMarginRiskAnalyzer:
    """Analyze risk in DeFi isolated margin positions.

    Parameters
    ----------
    position_size_usd : float
        Total position size in USD.
    collateral_value_usd : float
        Current market value of collateral in USD.
    borrow_value_usd : float
        Current outstanding borrow (debt) in USD.
    oracle_price_usd : float
        Oracle price of collateral asset (USD per token).
    liquidation_ltv : float
        LTV ratio at which position is liquidated (e.g., 0.825 for 82.5 %).
    health_factor : float
        Current health factor (collateral × liquidation_ltv / borrow).
        Values < 1.0 mean the position is already liquidatable.
    days_to_liquidation_at_trend : float or None
        Estimated days until liquidation at the current price trend.
        None if trend is unknown or improving.
    collateral_volatility_30d_pct : float
        Annualised 30-day volatility of the collateral asset (%).
    """

    def __init__(
        self,
        position_size_usd: float = 100_000.0,
        collateral_value_usd: float = 150_000.0,
        borrow_value_usd: float = 80_000.0,
        oracle_price_usd: float = 2_000.0,
        liquidation_ltv: float = 0.825,
        health_factor: float = 1.55,
        days_to_liquidation_at_trend: Optional[float] = None,
        collateral_volatility_30d_pct: float = 25.0,
    ) -> None:
        self.position_size_usd = float(position_size_usd)
        self.collateral_value_usd = float(collateral_value_usd)
        self.borrow_value_usd = float(borrow_value_usd)
        self.oracle_price_usd = float(oracle_price_usd)
        self.liquidation_ltv = float(liquidation_ltv)
        self.health_factor = float(health_factor)
        self.days_to_liquidation_at_trend = (
            float(days_to_liquidation_at_trend)
            if days_to_liquidation_at_trend is not None
            else None
        )
        self.collateral_volatility_30d_pct = float(collateral_volatility_30d_pct)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self) -> Dict[str, Any]:
        """Run isolated margin risk analysis.

        Returns a result dict with health_score, label, and all computed fields.
        Never raises; degenerate inputs produce warnings in the result.
        """
        warnings: List[str] = []

        # Current LTV
        if self.collateral_value_usd > 0:
            current_ltv = self.borrow_value_usd / self.collateral_value_usd
        else:
            current_ltv = None
            warnings.append("collateral_value_usd ≤ 0; current_ltv indeterminate.")

        # Liquidation price
        liq_price, liq_warnings = _compute_liquidation_price(
            collateral_value_usd=self.collateral_value_usd,
            borrow_value_usd=self.borrow_value_usd,
            oracle_price_usd=self.oracle_price_usd,
            liquidation_ltv=self.liquidation_ltv,
        )
        warnings.extend(liq_warnings)

        # Margin of safety
        margin, margin_warnings = _compute_margin_of_safety(self.oracle_price_usd, liq_price)
        warnings.extend(margin_warnings)

        # Health score
        health_score = _compute_health_score(
            self.health_factor, self.collateral_volatility_30d_pct
        )

        # Time to liquidation
        ttl = _compute_time_to_liquidation(self.health_factor, self.days_to_liquidation_at_trend)

        # Label
        label = _compute_label(self.health_factor, margin, ttl)

        # Collateral amount
        if self.oracle_price_usd > 0:
            collateral_amount = self.collateral_value_usd / self.oracle_price_usd
        else:
            collateral_amount = None
            warnings.append("oracle_price_usd ≤ 0; collateral_amount indeterminate.")

        return {
            "schema_version": SCHEMA_VERSION,
            "source": SOURCE_NAME,
            "mp_tag": MP_TAG,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "position_size_usd": round(self.position_size_usd, 4),
            "collateral_value_usd": round(self.collateral_value_usd, 4),
            "borrow_value_usd": round(self.borrow_value_usd, 4),
            "oracle_price_usd": round(self.oracle_price_usd, 6),
            "liquidation_ltv": round(self.liquidation_ltv, 6),
            "collateral_amount": round(collateral_amount, 6) if collateral_amount is not None else None,
            "current_ltv_pct": round(current_ltv * 100.0, 4) if current_ltv is not None else None,
            "health_factor": round(self.health_factor, 6),
            "health_score": round(health_score, 4),
            "liquidation_price_usd": round(liq_price, 6) if liq_price is not None else None,
            "margin_of_safety_pct": round(margin, 4) if margin is not None else None,
            "time_to_liquidation_days": (
                round(ttl, 2) if ttl is not None else None
            ),
            "collateral_volatility_30d_pct": round(self.collateral_volatility_30d_pct, 4),
            "label": label,
            "warnings": warnings,
        }


# ---------------------------------------------------------------------------
# Convenience top-level function
# ---------------------------------------------------------------------------


def analyze_isolated_margin(
    position_size_usd: float = 100_000.0,
    collateral_value_usd: float = 150_000.0,
    borrow_value_usd: float = 80_000.0,
    oracle_price_usd: float = 2_000.0,
    liquidation_ltv: float = 0.825,
    health_factor: float = 1.55,
    days_to_liquidation_at_trend: Optional[float] = None,
    collateral_volatility_30d_pct: float = 25.0,
) -> Dict[str, Any]:
    """Convenience wrapper — single call to analyze and return result."""
    return ProtocolDeFiIsolatedMarginRiskAnalyzer(
        position_size_usd=position_size_usd,
        collateral_value_usd=collateral_value_usd,
        borrow_value_usd=borrow_value_usd,
        oracle_price_usd=oracle_price_usd,
        liquidation_ltv=liquidation_ltv,
        health_factor=health_factor,
        days_to_liquidation_at_trend=days_to_liquidation_at_trend,
        collateral_volatility_30d_pct=collateral_volatility_30d_pct,
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
        description="DeFi Isolated Margin Risk Analyzer (MP-1035)"
    )
    p.add_argument("--check", action="store_true", help="Compute and print; no file write.")
    p.add_argument("--run", action="store_true", help="Compute, print, and write to log.")
    p.add_argument("--data-dir", default=str(_DEFAULT_DATA_DIR), help="Path to data/ dir.")
    p.add_argument("--position-size", type=float, default=100_000.0)
    p.add_argument("--collateral-value", type=float, default=150_000.0)
    p.add_argument("--borrow-value", type=float, default=80_000.0)
    p.add_argument("--oracle-price", type=float, default=2_000.0)
    p.add_argument("--liquidation-ltv", type=float, default=0.825)
    p.add_argument("--health-factor", type=float, default=1.55)
    p.add_argument("--days-to-liquidation", type=float, default=None)
    p.add_argument("--volatility", type=float, default=25.0)
    return p


def main(argv: Optional[List[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = _build_parser().parse_args(argv)

    if not args.check and not args.run:
        args.check = True

    result = analyze_isolated_margin(
        position_size_usd=args.position_size,
        collateral_value_usd=args.collateral_value,
        borrow_value_usd=args.borrow_value,
        oracle_price_usd=args.oracle_price,
        liquidation_ltv=args.liquidation_ltv,
        health_factor=args.health_factor,
        days_to_liquidation_at_trend=args.days_to_liquidation,
        collateral_volatility_30d_pct=args.volatility,
    )

    print(json.dumps(result, indent=2))

    if args.run:
        data_dir = Path(args.data_dir)
        log_path = write_log(result, data_dir)
        log.info("Log written → %s", log_path)

    return 0


if __name__ == "__main__":
    sys.exit(main())
