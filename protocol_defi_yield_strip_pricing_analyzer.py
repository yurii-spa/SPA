#!/usr/bin/env python3
"""Protocol DeFi Yield Strip Pricing Analyzer (SPA / MP-1077) — read-only / advisory.

Analyses pricing efficiency of Principal Token (PT) / Yield Token (YT) strips
in Pendle-style yield tokenization protocols.

Computes:
  pt_implied_yield_pct    — annualised return an investor earns by buying PT at
                            discount and holding to maturity
  yt_leverage_factor      — yield amplification factor for YT holders
  rate_arbitrage_bps      — difference (PT implied yield − fixed rate locked), in
                            basis points; positive = PT cheaper than locked fixed rate
  pricing_efficiency_score — composite 0–100 score for how efficiently the strip
                             is priced relative to fundamentals
  strip_label             — one of: DEEP_DISCOUNT_OPPORTUNITY / FAIR_PRICED /
                             SLIGHT_PREMIUM / OVERPRICED / AVOID_STRIP

Design constraints
------------------
* Pure stdlib only — no numpy / scipy / requests / pandas / web3.
* Advisory / read-only: never modifies risk/, execution/, monitoring/, allocator/.
* Atomic writes: tmp + os.replace (POSIX-atomic).
* Ring-buffer log capped at 100 entries in data/yield_strip_pricing_log.json.
* Never raises on the happy path; degenerate inputs degrade gracefully.
* NOT imported from risk/, execution/, monitoring/ (LLM_FORBIDDEN_AGENTS).

Metric definitions
------------------
  pt_discount_pct      — how many % below face value the PT trades.
                         e.g. PT at 95 cents on the dollar → pt_discount_pct = 5
  pt_implied_yield_pct — annualised: (discount / (100 - discount)) * (365 / days_to_maturity) * 100
                         (simple, not compound)
  yt_leverage_factor   — underlying_apy_pct / yt_implied_apy_pct when yt_implied > 0
                         else underlying_apy_pct / max(0.01, yt_implied)
  rate_arbitrage_bps   — (pt_implied_yield_pct - fixed_rate_locked_pct) * 100
  pricing_efficiency_score — see scorer docstring
  strip_label          — see STRIP_LABELS

Labels (based on rate_arbitrage_bps)
-------------------------------------
  DEEP_DISCOUNT_OPPORTUNITY  arb_bps >  200
  FAIR_PRICED                -100 ≤ arb_bps ≤ 200
  SLIGHT_PREMIUM             -200 ≤ arb_bps < -100
  OVERPRICED                 -500 ≤ arb_bps < -200
  AVOID_STRIP                arb_bps < -500

CLI
---
  python3 -m spa_core.analytics.protocol_defi_yield_strip_pricing_analyzer --check
  python3 -m spa_core.analytics.protocol_defi_yield_strip_pricing_analyzer --run
  python3 -m spa_core.analytics.protocol_defi_yield_strip_pricing_analyzer --run --data-dir PATH
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
from typing import Any, Dict, Optional

# ---------------------------------------------------------------------------
# Constants & paths
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _PROJECT_ROOT / "data"

LOG_FILENAME = "yield_strip_pricing_log.json"
RING_BUFFER_CAP = 100

SCHEMA_VERSION = 1
SOURCE_NAME = "protocol_defi_yield_strip_pricing_analyzer"
MP_TAG = "MP-1077"

# Strip label thresholds (rate_arbitrage_bps)
THRESHOLD_DEEP_DISCOUNT = 200.0    # arb > 200 bps → big opportunity
THRESHOLD_FAIR_LOW      = -100.0   # arb ≥ -100 → fair priced
THRESHOLD_SLIGHT_LOW    = -200.0   # arb ≥ -200 → slight premium
THRESHOLD_OVERPRICED    = -500.0   # arb ≥ -500 → overpriced

log = logging.getLogger("spa.analytics.protocol_defi_yield_strip_pricing_analyzer")


# ---------------------------------------------------------------------------
# Core metric computations (pure functions, no IO)
# ---------------------------------------------------------------------------

def _compute_pt_implied_yield(
    pt_discount_pct: float,
    days_to_maturity: float,
) -> float:
    """Annualised simple yield from buying PT at a discount.

    Formula: (discount / (100 - discount)) * (365 / days_to_maturity) * 100

    Returns 0.0 on degenerate inputs (days <= 0, discount >= 100, discount < 0).
    """
    d = float(pt_discount_pct)
    dtm = float(days_to_maturity)

    if d < 0.0:
        d = 0.0
    if d >= 100.0:
        return 0.0   # undefined / PT worthless
    if dtm <= 0.0:
        return 0.0   # matured or invalid

    face_frac = 100.0 - d
    if face_frac <= 0.0:
        return 0.0

    return round((d / face_frac) * (365.0 / dtm) * 100.0, 6)


def _compute_yt_leverage_factor(
    underlying_apy_pct: float,
    yt_implied_apy_pct: float,
) -> float:
    """Leverage factor = underlying_apy / yt_implied_apy.

    Clamped to [0, 100].  Returns 0 if underlying is 0.
    """
    ua = float(underlying_apy_pct)
    ya = float(yt_implied_apy_pct)

    if ua <= 0.0:
        return 0.0
    if ya <= 0.0:
        ya = 0.01  # avoid div-by-zero; very high leverage

    factor = ua / ya
    return round(min(100.0, max(0.0, factor)), 6)


def _compute_rate_arbitrage_bps(
    pt_implied_yield_pct: float,
    fixed_rate_locked_pct: float,
) -> float:
    """Difference in basis points: (PT implied yield − fixed rate locked) × 100."""
    return round((float(pt_implied_yield_pct) - float(fixed_rate_locked_pct)) * 100.0, 4)


def _strip_label(rate_arbitrage_bps: float) -> str:
    """Map rate_arbitrage_bps to a strip label."""
    arb = float(rate_arbitrage_bps)
    if arb > THRESHOLD_DEEP_DISCOUNT:
        return "DEEP_DISCOUNT_OPPORTUNITY"
    if arb >= THRESHOLD_FAIR_LOW:
        return "FAIR_PRICED"
    if arb >= THRESHOLD_SLIGHT_LOW:
        return "SLIGHT_PREMIUM"
    if arb >= THRESHOLD_OVERPRICED:
        return "OVERPRICED"
    return "AVOID_STRIP"


# ---------------------------------------------------------------------------
# Pricing efficiency score (0–100)
# ---------------------------------------------------------------------------

def _compute_pricing_efficiency_score(
    pt_discount_pct: float,
    underlying_apy_pct: float,
    pt_implied_yield_pct: float,
    yt_leverage_factor: float,
    rate_arbitrage_bps: float,
    tvl_usd: float,
    liquidity_depth_usd: float,
    days_to_maturity: float,
) -> float:
    """Composite 0–100 efficiency score.

    Dimensions and weights:
      yield_alignment  (0.30) — how close pt_implied_yield is to underlying_apy
      arb_opportunity  (0.20) — moderate positive arb preferred
      yt_leverage_ok   (0.15) — leverage 2–8× preferred
      liquidity_ratio  (0.20) — liquidity_depth / tvl ratio
      time_value       (0.15) — prefer >30 days to maturity
    """
    # 1. yield_alignment (0.30)
    ua = float(underlying_apy_pct)
    pty = float(pt_implied_yield_pct)
    if ua <= 0.0:
        align_score = 50.0
    else:
        spread_pct = abs(pty - ua) / ua * 100.0  # % deviation
        if spread_pct <= 5.0:
            align_score = 100.0
        elif spread_pct <= 20.0:
            align_score = round(100.0 - (spread_pct - 5.0) / 15.0 * 50.0, 4)
        elif spread_pct <= 50.0:
            align_score = round(50.0 - (spread_pct - 20.0) / 30.0 * 50.0, 4)
        else:
            align_score = 0.0

    # 2. arb_opportunity (0.20) — prefer small positive arb (0–200 bps)
    arb = float(rate_arbitrage_bps)
    if 0.0 <= arb <= 200.0:
        arb_score = 100.0 - (arb / 200.0) * 20.0  # 80–100 in sweet spot
    elif arb > 200.0:
        # Very large arb suggests mispricing / risk
        excess = min((arb - 200.0) / 300.0, 1.0)
        arb_score = round(80.0 - excess * 80.0, 4)
    else:
        # Negative arb (overpriced PT)
        penalty = min(abs(arb) / 500.0, 1.0)
        arb_score = round(max(0.0, 80.0 - penalty * 80.0), 4)

    # 3. yt_leverage_ok (0.15) — prefer 2–8×
    lev = float(yt_leverage_factor)
    if 2.0 <= lev <= 8.0:
        lev_score = 100.0
    elif lev < 2.0:
        lev_score = round(lev / 2.0 * 100.0, 4)
    else:
        # > 8: penalise
        excess = min((lev - 8.0) / 12.0, 1.0)
        lev_score = round(max(0.0, 100.0 - excess * 100.0), 4)

    # 4. liquidity_ratio (0.20) — liquidity_depth / tvl
    tvl = float(tvl_usd)
    liq = float(liquidity_depth_usd)
    if tvl <= 0.0:
        liq_score = 0.0
    else:
        ratio = min(liq / tvl, 1.0)
        liq_score = round(ratio * 100.0, 4)

    # 5. time_value (0.15) — prefer >30 days
    dtm = float(days_to_maturity)
    if dtm <= 0.0:
        time_score = 0.0
    elif dtm <= 7.0:
        time_score = round(dtm / 7.0 * 20.0, 4)
    elif dtm <= 30.0:
        time_score = round(20.0 + (dtm - 7.0) / 23.0 * 40.0, 4)
    elif dtm <= 180.0:
        time_score = round(60.0 + (dtm - 30.0) / 150.0 * 40.0, 4)
    else:
        time_score = 100.0

    raw = (
        0.30 * align_score
        + 0.20 * arb_score
        + 0.15 * lev_score
        + 0.20 * liq_score
        + 0.15 * time_score
    )
    return round(min(100.0, max(0.0, raw)), 2)


# ---------------------------------------------------------------------------
# Core analyze function
# ---------------------------------------------------------------------------

def analyze(data: Dict[str, Any]) -> Dict[str, Any]:
    """Analyse a yield-strip snapshot.

    Parameters
    ----------
    data : dict
        Required keys:
          protocol_name          str
          underlying_apy_pct     float  ≥ 0
          pt_discount_pct        float  0–100
          yt_implied_apy_pct     float  ≥ 0
          maturity_days          float  total maturity in days
          days_to_maturity       float  remaining days until maturity
          fixed_rate_locked_pct  float  ≥ 0
          variable_rate_current_pct float ≥ 0
          tvl_usd                float  ≥ 0
          liquidity_depth_usd    float  ≥ 0

    Returns
    -------
    dict
        pt_implied_yield_pct, yt_leverage_factor, rate_arbitrage_bps,
        pricing_efficiency_score, strip_label, mp_tag, source, schema_version
    """
    protocol_name = str(data.get("protocol_name", "unknown"))
    underlying_apy = float(data.get("underlying_apy_pct", 0.0))
    pt_discount = float(data.get("pt_discount_pct", 0.0))
    yt_implied_apy = float(data.get("yt_implied_apy_pct", 0.0))
    maturity_days = float(data.get("maturity_days", 0.0))
    days_to_maturity = float(data.get("days_to_maturity", 0.0))
    fixed_rate_locked = float(data.get("fixed_rate_locked_pct", 0.0))
    variable_rate_current = float(data.get("variable_rate_current_pct", 0.0))
    tvl_usd = float(data.get("tvl_usd", 0.0))
    liquidity_depth_usd = float(data.get("liquidity_depth_usd", 0.0))

    # Core metrics
    pt_implied_yield = _compute_pt_implied_yield(pt_discount, days_to_maturity)
    yt_leverage_factor = _compute_yt_leverage_factor(underlying_apy, yt_implied_apy)
    rate_arbitrage_bps = _compute_rate_arbitrage_bps(pt_implied_yield, fixed_rate_locked)
    pricing_efficiency_score = _compute_pricing_efficiency_score(
        pt_discount_pct=pt_discount,
        underlying_apy_pct=underlying_apy,
        pt_implied_yield_pct=pt_implied_yield,
        yt_leverage_factor=yt_leverage_factor,
        rate_arbitrage_bps=rate_arbitrage_bps,
        tvl_usd=tvl_usd,
        liquidity_depth_usd=liquidity_depth_usd,
        days_to_maturity=days_to_maturity,
    )
    label = _strip_label(rate_arbitrage_bps)

    return {
        "protocol_name":          protocol_name,
        "pt_implied_yield_pct":   pt_implied_yield,
        "yt_leverage_factor":     yt_leverage_factor,
        "rate_arbitrage_bps":     rate_arbitrage_bps,
        "pricing_efficiency_score": pricing_efficiency_score,
        "strip_label":            label,
        # Echo selected inputs for traceability
        "underlying_apy_pct":     underlying_apy,
        "pt_discount_pct":        pt_discount,
        "days_to_maturity":       days_to_maturity,
        "variable_rate_current_pct": variable_rate_current,
        "mp_tag":                 MP_TAG,
        "source":                 SOURCE_NAME,
        "schema_version":         SCHEMA_VERSION,
    }


# ---------------------------------------------------------------------------
# Ring-buffer log helpers
# ---------------------------------------------------------------------------

def _load_json_list(path: Path) -> list:
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _atomic_write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        os.replace(tmp, str(path))
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _append_log(result: Dict[str, Any], data_dir: Path) -> None:
    log_path = data_dir / LOG_FILENAME
    entries = _load_json_list(log_path)
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        **result,
    }
    entries.append(entry)
    if len(entries) > RING_BUFFER_CAP:
        entries = entries[-RING_BUFFER_CAP:]
    _atomic_write(log_path, entries)


# ---------------------------------------------------------------------------
# Public class
# ---------------------------------------------------------------------------

class ProtocolDeFiYieldStripPricingAnalyzer:
    """Analyse pricing efficiency of DeFi PT/YT yield strips.

    Usage
    -----
    analyzer = ProtocolDeFiYieldStripPricingAnalyzer()
    result = analyzer.analyze(data_dict)
    # result keys: pt_implied_yield_pct, yt_leverage_factor,
    #              rate_arbitrage_bps, pricing_efficiency_score, strip_label
    """

    def analyze(
        self,
        data: Dict[str, Any],
        *,
        write_log: bool = False,
        data_dir: Optional[Path] = None,
    ) -> Dict[str, Any]:
        """Analyse ``data`` and return a strip-pricing result dict.

        Parameters
        ----------
        data        : input snapshot dict (see module docstring for keys)
        write_log   : if True, atomically append result to ring-buffer log
        data_dir    : override default data directory (default: <repo>/data/)
        """
        result = analyze(data)

        if write_log:
            _dir = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR
            try:
                _append_log(result, _dir)
            except Exception as exc:
                log.warning("log write failed: %s", exc)

        return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _demo_data() -> Dict[str, Any]:
    return {
        "protocol_name":           "Pendle sUSDe Demo",
        "underlying_apy_pct":                  12.0,
        "pt_discount_pct":                      4.5,
        "yt_implied_apy_pct":                   3.0,
        "maturity_days":                       180.0,
        "days_to_maturity":                     90.0,
        "fixed_rate_locked_pct":                9.5,
        "variable_rate_current_pct":           12.0,
        "tvl_usd":                      50_000_000.0,
        "liquidity_depth_usd":           5_000_000.0,
    }


def _main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        description=f"Protocol DeFi Yield Strip Pricing Analyzer ({MP_TAG})"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true", help="Compute and print (no write)")
    group.add_argument("--run",   action="store_true", help="Compute, print, write log")
    parser.add_argument("--data-dir", type=str, default=None)
    args = parser.parse_args(argv)

    import logging
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)

    data_dir = Path(args.data_dir) if args.data_dir else _DEFAULT_DATA_DIR
    demo = _demo_data()
    analyzer = ProtocolDeFiYieldStripPricingAnalyzer()
    result = analyzer.analyze(demo, write_log=args.run, data_dir=data_dir)

    print(json.dumps(result, indent=2))
    if args.run:
        print(f"\n[{MP_TAG}] Logged to {data_dir / LOG_FILENAME}")
    return 0


if __name__ == "__main__":
    sys.exit(_main())
