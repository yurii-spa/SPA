#!/usr/bin/env python3
"""Protocol DeFi LP Fee vs IL Breakeven Analyzer (SPA-V760 / MP-1045) — read-only / advisory.

Calculates the breakeven point where Uniswap v2–style LP fee income exactly offsets
impermanent loss (IL). Uses the closed-form IL formula and a linear fee-accumulation
model.

Impermanent Loss (50/50 constant-product pool)
-----------------------------------------------
    k   = current_price_ratio / initial_price_ratio   (price change factor)
    IL  = 2 * sqrt(k) / (1 + k) − 1                  (always <= 0 for k != 1)

Fee Income
----------
    daily_fee_rate_pct = (fee_tier_bps / 10_000) * daily_volume_to_tvl_ratio * 100
    fee_income_pct     = daily_fee_rate_pct * days_in_position

Breakeven
---------
    breakeven_days = |IL_pct| / daily_fee_rate_pct
    (None when fee_rate = 0 and IL != 0 → never breaks even)
    (0 when IL = 0 → already at breakeven)

Labels
------
  FEE_DOMINANT   net_lp_pnl_pct > 2.0
  PROFITABLE     0 < net_lp_pnl_pct <= 2.0
  BREAKEVEN      -0.5 <= net_lp_pnl_pct <= 0.5  (catches also exactly 0)
  IL_DOMINANT    -10 < net_lp_pnl_pct <= -0.5   (but outside BREAKEVEN band)
  FEE_FUTILE     net_lp_pnl_pct <= -10

  net_lp_pnl_pct = fee_income_pct + impermanent_loss_pct

Design constraints
------------------
* Pure stdlib only — no numpy / scipy / requests / pandas / web3.
* Advisory / read-only: never modifies risk/, execution/, monitoring/, allocator/.
* Atomic writes: tmp + os.replace (POSIX-atomic).
* Ring-buffer log capped at 100 entries in data/lp_fee_vs_il_breakeven_log.json.
* Never raises on the happy path; degenerate inputs degrade gracefully.
* NOT imported from risk/, execution/, monitoring/ (LLM_FORBIDDEN_AGENTS).

CLI
---
  python3 -m spa_core.analytics.protocol_defi_lp_fee_vs_il_breakeven_analyzer --check
  python3 -m spa_core.analytics.protocol_defi_lp_fee_vs_il_breakeven_analyzer --run
  python3 -m spa_core.analytics.protocol_defi_lp_fee_vs_il_breakeven_analyzer --run --data-dir PATH
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
from typing import Any, Dict, List, Optional

from spa_core.base import BaseAnalytics

# ---------------------------------------------------------------------------
# Constants & paths
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _PROJECT_ROOT / "data"

LOG_FILENAME = "lp_fee_vs_il_breakeven_log.json"
RING_BUFFER_CAP = 100

SCHEMA_VERSION = 1
SOURCE_NAME = "protocol_defi_lp_fee_vs_il_breakeven_analyzer"
MP_TAG = "MP-1045"

# Net P&L thresholds for labelling (in pct)
NET_FEE_DOMINANT: float = 2.0
NET_BREAKEVEN_BAND: float = 0.5   # ±0.5 % around zero
NET_IL_FUTILE: float = -10.0

log = logging.getLogger("spa.analytics.protocol_defi_lp_fee_vs_il_breakeven_analyzer")


# ---------------------------------------------------------------------------
# Math helpers
# ---------------------------------------------------------------------------


def _compute_impermanent_loss_pct(
    initial_price_ratio: float,
    current_price_ratio: float,
) -> float:
    """Compute IL for a 50/50 constant-product pool.

    IL = 2 * sqrt(k) / (1 + k) − 1  (expressed as a percentage)

    where k = current_price_ratio / initial_price_ratio.

    Returns 0.0 when k == 1 (no price change) or on degenerate inputs.
    IL is always <= 0.0 for any k != 1.
    """
    if initial_price_ratio <= 0.0 or current_price_ratio <= 0.0:
        return 0.0
    k = current_price_ratio / initial_price_ratio
    if k <= 0.0:
        return 0.0
    il_factor = 2.0 * math.sqrt(k) / (1.0 + k) - 1.0
    return round(il_factor * 100.0, 8)


def _compute_daily_fee_rate_pct(
    fee_tier_bps: float,
    daily_volume_to_tvl_ratio: float,
) -> float:
    """Return daily fee income as % of position size.

    daily_fee_rate_pct = (fee_tier_bps / 10_000) * daily_volume_to_tvl_ratio * 100

    Returns 0.0 for non-positive inputs.
    """
    if fee_tier_bps <= 0.0 or daily_volume_to_tvl_ratio <= 0.0:
        return 0.0
    return round((fee_tier_bps / 10_000.0) * daily_volume_to_tvl_ratio * 100.0, 8)


def _compute_fee_income_pct(
    daily_fee_rate_pct: float,
    days_in_position: float,
) -> float:
    """Return cumulative fee income (%) over the holding period."""
    if days_in_position < 0.0:
        return 0.0
    return round(daily_fee_rate_pct * days_in_position, 8)


def _compute_breakeven_days(
    impermanent_loss_pct: float,
    daily_fee_rate_pct: float,
) -> Optional[float]:
    """Estimate days until fee income covers IL.

    Returns
    -------
    0.0     — no IL (breakeven from day 0)
    float   — positive days required
    None    — never (fee rate = 0 and IL exists)
    """
    if impermanent_loss_pct >= 0.0:
        return 0.0  # no IL or gain from rebalancing (rare)
    abs_il = abs(impermanent_loss_pct)
    if daily_fee_rate_pct <= 0.0:
        return None  # IL but no fees — never breaks even
    return round(abs_il / daily_fee_rate_pct, 4)


def _label(net_lp_pnl_pct: float) -> str:
    """Classify LP position health."""
    if net_lp_pnl_pct > NET_FEE_DOMINANT:
        return "FEE_DOMINANT"
    if net_lp_pnl_pct > NET_BREAKEVEN_BAND:
        return "PROFITABLE"
    if net_lp_pnl_pct >= -NET_BREAKEVEN_BAND:
        return "BREAKEVEN"
    if net_lp_pnl_pct > NET_IL_FUTILE:
        return "IL_DOMINANT"
    return "FEE_FUTILE"


def _annualized_fee_apy_pct(daily_fee_rate_pct: float) -> float:
    """Convert daily fee rate to annualized APY (simple compounding)."""
    return round(daily_fee_rate_pct * 365.0, 4)


def _expected_il_from_volatility(
    volatility_30d_pct: float,
    days_in_position: float,
) -> float:
    """Approximate expected IL from realized volatility.

    Uses: E[IL] ≈ −(σ²T) / 2  for small σ and T in years.
    where σ = annualized volatility (as decimal).

    This is informational only; the actual IL uses the real price ratio.
    """
    if volatility_30d_pct <= 0.0 or days_in_position <= 0.0:
        return 0.0
    annual_vol = (volatility_30d_pct / 100.0) * math.sqrt(365.0 / 30.0)
    t_years = days_in_position / 365.0
    expected_il = -(annual_vol ** 2 * t_years) / 2.0
    return round(expected_il * 100.0, 6)


# ---------------------------------------------------------------------------
# Core analysis function
# ---------------------------------------------------------------------------


def _analyze_single(
    initial_price_ratio: float,
    current_price_ratio: float,
    fee_tier_bps: float,
    daily_volume_to_tvl_ratio: float,
    days_in_position: float,
    volatility_30d_pct: float,
    position_size_usd: float,
) -> Dict[str, Any]:
    """Compute full LP fee vs IL analysis. Never raises."""
    warnings: List[str] = []

    init = float(initial_price_ratio)
    curr = float(current_price_ratio)
    fee_bps = max(0.0, float(fee_tier_bps))
    vol_ratio = max(0.0, float(daily_volume_to_tvl_ratio))
    days = max(0.0, float(days_in_position))
    vol30 = max(0.0, float(volatility_30d_pct))
    pos_size = max(0.0, float(position_size_usd))

    if init <= 0.0:
        warnings.append("initial_price_ratio <= 0 — IL set to 0")
    if curr <= 0.0:
        warnings.append("current_price_ratio <= 0 — IL set to 0")
    if fee_bps <= 0.0:
        warnings.append("fee_tier_bps <= 0 — fee income will be 0")
    if vol_ratio <= 0.0:
        warnings.append("daily_volume_to_tvl_ratio <= 0 — fee income will be 0")
    if days <= 0.0:
        warnings.append("days_in_position <= 0 — fee income will be 0")
    if pos_size <= 0.0:
        warnings.append("position_size_usd <= 0 — USD P&L unavailable")

    k = (curr / init) if init > 0.0 and curr > 0.0 else 1.0
    il_pct = _compute_impermanent_loss_pct(init, curr)
    daily_fee_pct = _compute_daily_fee_rate_pct(fee_bps, vol_ratio)
    fee_income_pct = _compute_fee_income_pct(daily_fee_pct, days)
    net_pnl_pct = round(fee_income_pct + il_pct, 8)
    breakeven_days = _compute_breakeven_days(il_pct, daily_fee_pct)
    severity_label = _label(net_pnl_pct)
    annualized_fee_apy = _annualized_fee_apy_pct(daily_fee_pct)
    expected_il_vol = _expected_il_from_volatility(vol30, days)

    # Dollar P&L values
    il_usd: Optional[float] = round(pos_size * il_pct / 100.0, 2) if pos_size > 0 else None
    fee_usd: Optional[float] = round(pos_size * fee_income_pct / 100.0, 2) if pos_size > 0 else None
    net_usd: Optional[float] = round(pos_size * net_pnl_pct / 100.0, 2) if pos_size > 0 else None

    already_broken_even = (
        breakeven_days is not None
        and breakeven_days == 0.0
        or (breakeven_days is not None and days >= breakeven_days)
    )

    return {
        "initial_price_ratio": round(init, 8),
        "current_price_ratio": round(curr, 8),
        "price_change_factor_k": round(k, 8),
        "fee_tier_bps": round(fee_bps, 2),
        "daily_volume_to_tvl_ratio": round(vol_ratio, 6),
        "days_in_position": round(days, 2),
        "volatility_30d_pct": round(vol30, 4),
        "position_size_usd": round(pos_size, 2),
        "impermanent_loss_pct": round(il_pct, 6),
        "fee_income_pct": round(fee_income_pct, 6),
        "net_lp_pnl_pct": round(net_pnl_pct, 6),
        "daily_fee_rate_pct": round(daily_fee_pct, 8),
        "annualized_fee_apy_pct": annualized_fee_apy,
        "breakeven_days": breakeven_days,
        "already_broken_even": already_broken_even,
        "expected_il_from_vol_pct": expected_il_vol,
        "impermanent_loss_usd": il_usd,
        "fee_income_usd": fee_usd,
        "net_lp_pnl_usd": net_usd,
        "label": severity_label,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------


class ProtocolDeFiLPFeeVsILBreakevenAnalyzer(BaseAnalytics):
    """Calculate LP fee vs impermanent loss breakeven for DeFi pools.

    Usage
    -----
    ::

        analyzer = ProtocolDeFiLPFeeVsILBreakevenAnalyzer()
        result = analyzer.analyze(
            initial_price_ratio=1.0,
            current_price_ratio=1.5,
            fee_tier_bps=30,
            daily_volume_to_tvl_ratio=0.10,
            days_in_position=60,
            volatility_30d_pct=80.0,
            position_size_usd=50_000,
        )
        print(result["label"])            # → IL_DOMINANT
        print(result["breakeven_days"])   # → ~days required to offset IL
    """

    OUTPUT_PATH = "data/lp_fee_vs_il_breakeven_log.json"

    def __init__(
        self,
        data_dir: Optional[Path | str] = None,
        ring_cap: int = RING_BUFFER_CAP,
    ) -> None:
        super().__init__()
        self._data_dir = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR
        self._ring_cap = ring_cap
        self._last_result: Optional[Dict[str, Any]] = None

    def to_dict(self) -> dict:
        """Returns last LP breakeven analysis result as JSON-serializable dict."""
        return dict(self._last_result) if self._last_result else {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(
        self,
        initial_price_ratio: float,
        current_price_ratio: float,
        fee_tier_bps: float,
        daily_volume_to_tvl_ratio: float,
        days_in_position: float,
        volatility_30d_pct: float,
        position_size_usd: float,
    ) -> Dict[str, Any]:
        """Run LP fee vs IL analysis for one position.

        Returns
        -------
        Dict with impermanent_loss_pct, fee_income_pct, net_lp_pnl_pct,
        breakeven_days, label, and per-field metadata.
        """
        timestamp = datetime.now(timezone.utc).isoformat()
        try:
            detail = _analyze_single(
                initial_price_ratio=initial_price_ratio,
                current_price_ratio=current_price_ratio,
                fee_tier_bps=fee_tier_bps,
                daily_volume_to_tvl_ratio=daily_volume_to_tvl_ratio,
                days_in_position=days_in_position,
                volatility_30d_pct=volatility_30d_pct,
                position_size_usd=position_size_usd,
            )
        except Exception as exc:  # noqa: BLE001
            log.error("analyze() failed: %s", exc)
            detail = {
                "error": str(exc),
                "label": "BREAKEVEN",
                "impermanent_loss_pct": 0.0,
                "fee_income_pct": 0.0,
                "net_lp_pnl_pct": 0.0,
                "breakeven_days": 0.0,
                "warnings": [f"analysis_error: {exc}"],
            }

        result: Dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "source": SOURCE_NAME,
            "mp_tag": MP_TAG,
            "timestamp": timestamp,
            **detail,
        }
        self._last_result = result
        return result

    def analyze_batch(
        self,
        positions: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Analyze multiple LP positions at once.

        Each element of ``positions`` must be a dict matching the keyword
        arguments of :meth:`analyze`.
        """
        timestamp = datetime.now(timezone.utc).isoformat()
        per_position: List[Dict[str, Any]] = []

        for pos in positions:
            try:
                r = self.analyze(**pos)
                per_position.append(r)
            except Exception as exc:  # noqa: BLE001
                log.warning("Batch analyze failed: %s", exc)
                per_position.append({
                    "error": str(exc),
                    "label": "BREAKEVEN",
                    "impermanent_loss_pct": 0.0,
                    "fee_income_pct": 0.0,
                    "net_lp_pnl_pct": 0.0,
                })

        label_counts: Dict[str, int] = {}
        for r in per_position:
            lbl = r.get("label", "BREAKEVEN")
            label_counts[lbl] = label_counts.get(lbl, 0) + 1

        il_dominated = [
            r for r in per_position
            if r.get("label") in ("IL_DOMINANT", "FEE_FUTILE")
        ]

        batch_result: Dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "source": SOURCE_NAME,
            "mp_tag": MP_TAG,
            "timestamp": timestamp,
            "position_count": len(per_position),
            "il_dominated_count": len(il_dominated),
            "label_counts": label_counts,
            "per_position": per_position,
            "il_dominated": il_dominated,
        }
        self._last_result = batch_result
        return batch_result

    def get_label(self) -> Optional[str]:
        """Return label from last :meth:`analyze` call, or None."""
        if self._last_result is None:
            return None
        return self._last_result.get("label")

    def is_il_dominant(self) -> bool:
        """Return True if last result is IL_DOMINANT or FEE_FUTILE."""
        label = self.get_label()
        return label in ("IL_DOMINANT", "FEE_FUTILE")

    def save(self) -> bool:
        """Atomically append last result to the ring-buffer log file.

        Returns True on success, False on any error (never raises).
        """
        if self._last_result is None:
            log.warning("save() called before analyze() — nothing to write")
            return False
        try:
            log_path = self._data_dir / LOG_FILENAME
            existing: List[Any] = _load_json_list(log_path)
            existing.append(self._last_result)
            if len(existing) > self._ring_cap:
                existing = existing[-self._ring_cap:]
            _atomic_write(log_path, existing)
            log.info("lp_fee_vs_il_breakeven_log written (%d entries)", len(existing))
            return True
        except Exception as exc:  # noqa: BLE001
            log.error("save() failed: %s", exc)
            return False


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------


def _load_json_list(path: Path) -> List[Any]:
    """Load a JSON list from *path*; return [] on any error."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
            return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []


def _atomic_write(path: Path, data: Any) -> None:
    """Write *data* as JSON to *path* atomically (tmp + os.replace)."""
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
# Module-level functional API
# ---------------------------------------------------------------------------


def analyze_lp(
    initial_price_ratio: float,
    current_price_ratio: float,
    fee_tier_bps: float,
    daily_volume_to_tvl_ratio: float,
    days_in_position: float,
    volatility_30d_pct: float,
    position_size_usd: float,
    data_dir: Optional[Path | str] = None,
) -> Dict[str, Any]:
    """Functional entry-point: analyze one LP position and return result dict."""
    analyzer = ProtocolDeFiLPFeeVsILBreakevenAnalyzer(data_dir=data_dir)
    return analyzer.analyze(
        initial_price_ratio=initial_price_ratio,
        current_price_ratio=current_price_ratio,
        fee_tier_bps=fee_tier_bps,
        daily_volume_to_tvl_ratio=daily_volume_to_tvl_ratio,
        days_in_position=days_in_position,
        volatility_30d_pct=volatility_30d_pct,
        position_size_usd=position_size_usd,
    )


# ---------------------------------------------------------------------------
# Demo data
# ---------------------------------------------------------------------------


_DEMO_POSITIONS: List[Dict[str, Any]] = [
    {
        "initial_price_ratio": 1.0,
        "current_price_ratio": 1.0,
        "fee_tier_bps": 30,
        "daily_volume_to_tvl_ratio": 0.10,
        "days_in_position": 30,
        "volatility_30d_pct": 20.0,
        "position_size_usd": 10_000,
    },
    {
        "initial_price_ratio": 2000.0,
        "current_price_ratio": 3000.0,
        "fee_tier_bps": 30,
        "daily_volume_to_tvl_ratio": 0.15,
        "days_in_position": 60,
        "volatility_30d_pct": 80.0,
        "position_size_usd": 50_000,
    },
    {
        "initial_price_ratio": 1.0,
        "current_price_ratio": 4.0,
        "fee_tier_bps": 5,
        "daily_volume_to_tvl_ratio": 0.02,
        "days_in_position": 90,
        "volatility_30d_pct": 120.0,
        "position_size_usd": 100_000,
    },
]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="protocol_defi_lp_fee_vs_il_breakeven_analyzer",
        description="MP-1045 LP Fee vs IL Breakeven Analyzer — constant-product AMM analysis",
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
        help="Compute, print, and atomically write to data/lp_fee_vs_il_breakeven_log.json",
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

    analyzer = ProtocolDeFiLPFeeVsILBreakevenAnalyzer(data_dir=data_dir)
    result = analyzer.analyze_batch(_DEMO_POSITIONS)

    print(json.dumps(result, indent=2, ensure_ascii=False))

    if write_mode:
        ok = analyzer.save()
        if not ok:
            print(
                "[protocol_defi_lp_fee_vs_il_breakeven_analyzer] WARNING: save() failed",
                file=sys.stderr,
            )
        else:
            print(
                f"[protocol_defi_lp_fee_vs_il_breakeven_analyzer] Written to "
                f"{data_dir / LOG_FILENAME}",
                file=sys.stderr,
            )

    sys.exit(0)


if __name__ == "__main__":
    main()
