#!/usr/bin/env python3
"""Protocol DeFi Liquidity Depth Impact Analyzer (SPA-v769 / MP-1063) — read-only / advisory.

Models the price impact, slippage, fee cost, and total execution cost of a trade
against a DeFi liquidity pool.  Supports constant-product, stable-swap, and
concentrated-liquidity AMM styles.

Design constraints
------------------
* Pure stdlib only — no numpy / scipy / requests / pandas / web3.
* Advisory / read-only: never modifies risk/, execution/, monitoring/, allocator/.
* Atomic writes: tmp + os.replace (POSIX-atomic).
* Ring-buffer log capped at 100 entries → data/liquidity_depth_impact_log.json.
* Never raises on the happy path; degenerate inputs degrade gracefully with warnings.
* NOT imported from risk/, execution/, monitoring/ (LLM_FORBIDDEN_AGENTS).

Pool Types and Price-Impact Math
---------------------------------
CONSTANT_PRODUCT  (x·y = k, standard Uniswap V2 style):
  Using exact AMM math for a trade Δ into one side of the pool.
  Effective reserve  R = token_b_reserve_usd  (the input side).
  Exact price impact (bps of Δ/R term):
    price_impact_pct = Δ / (R + Δ) × 100
  Slippage = 0.5 × price_impact_pct   (classic approximation for balanced pools)

STABLE_SWAP  (Curve-style amplification):
  Stable-swap AMMs have much lower price impact for in-range swaps.
  We model the amplification as dividing the raw constant-product impact by a
  stable_amplification factor (default 10×):
    price_impact_pct = raw_constant_product_impact / 10
  Slippage = 0.5 × price_impact_pct  (stable pools even tighter in practice)

CONCENTRATED  (Uniswap V3 / Ambient style):
  Active liquidity within the current tick range is higher by concentration_factor.
  Effective reserve  R_eff = token_b_reserve_usd × concentration_factor
    price_impact_pct = Δ / (R_eff + Δ) × 100
  Slippage = 0.5 × price_impact_pct

Fee cost:
  fee_cost_pct = fee_tier_bps / 10_000 × 100

Total execution cost:
  total_execution_cost_pct = price_impact_pct + slippage_pct + fee_cost_pct

Effective spread (bps):
  effective_spread_bps = total_execution_cost_pct × 100

Liquidity labels (first matching wins):
  AVOID_TRADE_SIZE    total_execution_cost_pct ≥ 3.0
  HIGH_IMPACT         total_execution_cost_pct ≥ 1.0
  MODERATE_IMPACT     total_execution_cost_pct ≥ 0.5
  ADEQUATE_LIQUIDITY  total_execution_cost_pct ≥ 0.1
  DEEP_LIQUIDITY      total_execution_cost_pct  < 0.1

CLI
---
  python3 -m spa_core.analytics.protocol_defi_liquidity_depth_impact_analyzer --check
  python3 -m spa_core.analytics.protocol_defi_liquidity_depth_impact_analyzer --run
  python3 -m spa_core.analytics.protocol_defi_liquidity_depth_impact_analyzer --run --data-dir PATH
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
from spa_core.base import BaseAnalytics

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _PROJECT_ROOT / "data"

LOG_FILENAME = "liquidity_depth_impact_log.json"
RING_BUFFER_CAP = 100

SCHEMA_VERSION = 1
SOURCE_NAME = "protocol_defi_liquidity_depth_impact_analyzer"
MP_TAG = "MP-1063"

STABLE_AMPLIFICATION: float = 10.0   # stable-swap effective amplification factor

# Execution-cost thresholds (%) for labels
THRESHOLD_AVOID: float = 3.0
THRESHOLD_HIGH: float = 1.0
THRESHOLD_MODERATE: float = 0.5
THRESHOLD_ADEQUATE: float = 0.1

VALID_POOL_TYPES = {"constant_product", "stable_swap", "concentrated"}

log = logging.getLogger("spa.analytics.protocol_defi_liquidity_depth_impact_analyzer")

# ---------------------------------------------------------------------------
# Low-level helpers (importable for tests)
# ---------------------------------------------------------------------------


def _clamp(value: float, lo: float, hi: float) -> float:
    """Clamp *value* to [lo, hi]."""
    return max(lo, min(hi, value))


def _compute_price_impact_constant_product(
    trade_size_usd: float, reserve_usd: float
) -> float:
    """Exact constant-product price-impact percentage.

    price_impact_pct = trade_size / (reserve + trade_size) * 100

    Both inputs must be ≥ 0; if reserve + trade_size ≈ 0 returns 100 %.
    """
    if trade_size_usd <= 0.0:
        return 0.0
    denominator = reserve_usd + trade_size_usd
    if denominator <= 0.0:
        return 100.0
    return _clamp(trade_size_usd / denominator * 100.0, 0.0, 100.0)


def _compute_price_impact(
    pool_type: str,
    trade_size_usd: float,
    token_b_reserve_usd: float,
    concentration_factor: float,
) -> Tuple[float, List[str]]:
    """Return (price_impact_pct, warnings).

    token_b_reserve_usd is the input-side reserve.
    concentration_factor ≥ 1.0 (≡ 1.0 for standard pools).
    """
    warnings: List[str] = []

    if trade_size_usd <= 0.0:
        return 0.0, warnings

    conc = max(1.0, concentration_factor)
    if concentration_factor < 1.0:
        warnings.append(
            f"concentration_factor {concentration_factor} < 1.0; clamped to 1.0"
        )

    ptype = (pool_type or "constant_product").lower().strip()
    if ptype not in VALID_POOL_TYPES:
        warnings.append(
            f"Unknown pool_type '{pool_type}'; defaulting to 'constant_product'"
        )
        ptype = "constant_product"

    if ptype == "stable_swap":
        # Use amplification: effective reserve is 10× larger
        effective_reserve = max(0.0, token_b_reserve_usd) * STABLE_AMPLIFICATION
        raw = _compute_price_impact_constant_product(trade_size_usd, effective_reserve)
        impact = raw
    elif ptype == "concentrated":
        effective_reserve = max(0.0, token_b_reserve_usd) * conc
        impact = _compute_price_impact_constant_product(trade_size_usd, effective_reserve)
    else:
        # constant_product
        impact = _compute_price_impact_constant_product(
            trade_size_usd, max(0.0, token_b_reserve_usd)
        )

    return impact, warnings


def _compute_slippage(price_impact_pct: float) -> float:
    """Slippage ≈ 0.5 × price_impact for all pool types."""
    return max(0.0, price_impact_pct * 0.5)


def _compute_fee_cost_pct(fee_tier_bps: float) -> float:
    """Convert fee tier in bps to percentage: pct = bps / 100."""
    return max(0.0, fee_tier_bps / 100.0)


def _compute_effective_spread_bps(total_execution_cost_pct: float) -> float:
    """Effective spread in bps = total_execution_cost_pct * 100."""
    return max(0.0, total_execution_cost_pct * 100.0)


def _compute_liquidity_label(total_execution_cost_pct: float) -> str:
    """Return liquidity label based on total execution cost %."""
    if total_execution_cost_pct >= THRESHOLD_AVOID:
        return "AVOID_TRADE_SIZE"
    if total_execution_cost_pct >= THRESHOLD_HIGH:
        return "HIGH_IMPACT"
    if total_execution_cost_pct >= THRESHOLD_MODERATE:
        return "MODERATE_IMPACT"
    if total_execution_cost_pct >= THRESHOLD_ADEQUATE:
        return "ADEQUATE_LIQUIDITY"
    return "DEEP_LIQUIDITY"


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
    atomic_save(data, str(path))
# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def analyze_liquidity_depth_impact(params: Dict[str, Any]) -> Dict[str, Any]:
    """Analyse liquidity depth and execution cost for a DeFi pool trade.

    Parameters
    ----------
    params : dict with keys
        pool_name             str
        total_liquidity_usd   float — total pool TVL
        token_a_reserve_usd   float — reserve of token A
        token_b_reserve_usd   float — reserve of token B (input side for price-impact)
        fee_tier_bps          float — pool fee in basis points (e.g. 30 for 0.30%)
        trade_size_usd        float — size of the trade in USD
        pool_type             str   — "constant_product" | "stable_swap" | "concentrated"
        concentration_factor  float — ≥ 1.0; effective liquidity multiplier for concentrated
        volume_24h_usd        float — 24 h trading volume (informational)

    Returns
    -------
    dict with keys
        pool_name                str
        price_impact_pct         float
        slippage_pct             float
        fee_cost_pct             float
        total_execution_cost_pct float
        effective_spread_bps     float
        liquidity_label          str
        trade_size_usd           float
        total_liquidity_usd      float
        fee_tier_bps             float
        pool_type                str
        volume_24h_usd           float
        warnings                 list[str]
        timestamp_utc            str
        schema_version           int
        source                   str
        mp_tag                   str
    """
    warnings: List[str] = []

    def _flt(key: str, default: float = 0.0) -> float:
        val = params.get(key, default)
        try:
            return float(val)
        except (TypeError, ValueError):
            warnings.append(f"Non-numeric value for '{key}'; using {default}")
            return default

    pool_name = str(params.get("pool_name", "unknown"))
    total_liq = max(0.0, _flt("total_liquidity_usd"))
    token_a = max(0.0, _flt("token_a_reserve_usd"))
    token_b = max(0.0, _flt("token_b_reserve_usd"))
    fee_bps = max(0.0, _flt("fee_tier_bps"))
    trade_size = max(0.0, _flt("trade_size_usd"))
    conc_factor = max(1.0, _flt("concentration_factor", 1.0))
    vol_24h = max(0.0, _flt("volume_24h_usd"))

    pool_type_raw = str(params.get("pool_type", "constant_product")).lower().strip()

    # Validate pool type
    if pool_type_raw not in VALID_POOL_TYPES:
        warnings.append(
            f"Unknown pool_type '{pool_type_raw}'; defaulting to 'constant_product'"
        )
        pool_type_raw = "constant_product"

    # Warn on zero liquidity
    if total_liq == 0.0:
        warnings.append("total_liquidity_usd is 0; price impact will be extreme")

    # Use token_b reserve as the input-side reserve; fall back to total_liq/2
    input_reserve = token_b if token_b > 0.0 else (total_liq / 2.0 if total_liq > 0.0 else 0.0)
    if token_b <= 0.0 and total_liq > 0.0:
        warnings.append(
            "token_b_reserve_usd is 0; using total_liquidity_usd / 2 as input reserve"
        )

    # -- price impact ----------------------------------------------------
    price_impact, w_pi = _compute_price_impact(
        pool_type_raw, trade_size, input_reserve, conc_factor
    )
    warnings.extend(w_pi)

    # -- slippage, fee, total -----------------------------------------
    slippage = _compute_slippage(price_impact)
    fee_cost = _compute_fee_cost_pct(fee_bps)
    total_cost = price_impact + slippage + fee_cost
    spread_bps = _compute_effective_spread_bps(total_cost)
    label = _compute_liquidity_label(total_cost)

    return {
        "pool_name": pool_name,
        "price_impact_pct": round(price_impact, 6),
        "slippage_pct": round(slippage, 6),
        "fee_cost_pct": round(fee_cost, 6),
        "total_execution_cost_pct": round(total_cost, 6),
        "effective_spread_bps": round(spread_bps, 4),
        "liquidity_label": label,
        "trade_size_usd": round(trade_size, 4),
        "total_liquidity_usd": round(total_liq, 4),
        "fee_tier_bps": round(fee_bps, 4),
        "pool_type": pool_type_raw,
        "volume_24h_usd": round(vol_24h, 4),
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
# Main class
# ---------------------------------------------------------------------------


class ProtocolDeFiLiquidityDepthImpactAnalyzer(BaseAnalytics):
    OUTPUT_PATH = "data/protocol_liquidity_depth_impact.json"
    """Advisory wrapper around :func:`analyze_liquidity_depth_impact`.

    Usage::

        analyzer = ProtocolDeFiLiquidityDepthImpactAnalyzer()
        result = analyzer.analyze(params_dict)
        analyzer.save(result)          # appends to ring-buffer log
    """

    def __init__(self, data_dir: Optional[Path] = None) -> None:
        self._data_dir = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR

    def analyze(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Run liquidity depth impact analysis. Returns result dict."""
        return analyze_liquidity_depth_impact(params)

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


    def to_dict(self) -> dict:
        """Return internal state as a plain dict. LLM FORBIDDEN."""
        return getattr(self, '_data', {})

_DEMO_PARAMS: Dict[str, Any] = {
    "pool_name": "USDC/ETH 0.30% (demo)",
    "total_liquidity_usd": 10_000_000.0,
    "token_a_reserve_usd": 5_000_000.0,
    "token_b_reserve_usd": 5_000_000.0,
    "fee_tier_bps": 30.0,
    "trade_size_usd": 100_000.0,
    "pool_type": "constant_product",
    "concentration_factor": 1.0,
    "volume_24h_usd": 2_000_000.0,
}


def _main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Protocol DeFi Liquidity Depth Impact Analyzer (MP-1063)"
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
    analyzer = ProtocolDeFiLiquidityDepthImpactAnalyzer(data_dir=data_dir)
    result = analyzer.analyze(_DEMO_PARAMS)

    print(json.dumps(result, indent=2, ensure_ascii=False))

    if args.run:
        log_path = analyzer.save(result)
        print(f"\n✓ Log written → {log_path}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(_main())
