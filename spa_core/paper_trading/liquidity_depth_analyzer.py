#!/usr/bin/env python3
"""Protocol Liquidity Depth & Slippage Estimator (SPA / MP-126) — read-only / advisory.

Estimates market depth and expected entry/exit slippage for each whitelisted
protocol.  The core question is: *"Given our $100K USDC position, how much
slippage should we expect, and which pools are too shallow to absorb our size
without material impact?"*

Slippage model
==============
A deliberately simple, transparent first-order linear model::

    slippage_bps = k * (amount_usd / tvl_usd) * 10_000

where:
  * ``amount_usd``  — USD notional being entered or exited.
  * ``tvl_usd``     — total value locked in the pool (from
    ``adapter_orchestrator_status.json`` when available, otherwise a
    documented conservative static fallback).
  * ``k``           — liquidity-tier coefficient:
      - T1-liquidity (Aave V3, Compound V3, Morpho Blue): k = 0.5
        (deep, institutional-grade markets).
      - T2-liquidity (Yearn V3, Euler V2, Maple): k = 2.0
        (smaller pools, epoch-based or vault-style liquidity).
      - unknown: k = 2.0 (conservative).

The formula is intentionally NOT a sophisticated AMM curve — it is an
advisory first-order estimate that surfaces large-size risks without
requiring live price-impact simulation.

Capacity curve
==============
:func:`get_capacity_curve` samples the slippage at 10 notional breakpoints
(from $1K to $10M) and returns a list of ``{amount_usd, slippage_bps}``
points.  The curve is *monotonically non-decreasing* by construction of the
linear model.

Portfolio analysis
==================
:func:`analyze_portfolio_liquidity` accepts a ``positions`` dict
(``{protocol_slug: usd_value}``) and computes:

  * Per-position slippage (both enter and exit at current size).
  * Worst-case single-protocol exit time (instant for T1, varies for T2).
  * An advisory ``verdict`` (ok / warn / fail) and ``worst_case_bps``.
  * A portfolio-wide ``liquidity_score`` (0–100, higher = more liquid).

Low-liquidity flags
===================
:func:`flag_low_liquidity_protocols` returns a list of protocol slugs whose
expected slippage at our current AUM_REFERENCE_USD exceeds *threshold_bps*
(default 50 bps = 0.5%).

Data sources
============
Reads (in priority order, all tolerant):

1. ``data/adapter_orchestrator_status.json`` — live TVL per protocol.
2. ``data/adapter_status.json``              — protocol registry / tiers.
3. If neither is available: static conservative TVL fallback table
   (documented below).

Design notes / safety
======================
  * Pure stdlib (json, math, os, datetime, pathlib, logging, argparse,
    typing).  No web3 / numpy / pandas / requests / network.
  * STRICTLY READ-ONLY (SPA-BL-011) and ADVISORY ONLY.  Never touches
    risk/execution/allocator/cycle_runner; never writes to data/.
  * All public functions NEVER raise — they return structured dicts / lists
    even on bad input.
  * ``LLM_FORBIDDEN_AGENTS`` = {risk, execution, monitoring} — LLM calls
    are NOT made here.

CLI (offline, exit 0, no tracebacks)::

    python3 -m spa_core.paper_trading.liquidity_depth_analyzer --check
    python3 -m spa_core.paper_trading.liquidity_depth_analyzer --check --data-dir <dir>
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

log = logging.getLogger("spa.paper_trading.liquidity_depth_analyzer")

# ─── Repo / data paths ────────────────────────────────────────────────────────

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"

# Source file names (read-only; this module NEVER writes to these).
ORCHESTRATOR_FILENAME = "adapter_orchestrator_status.json"
ADAPTER_STATUS_FILENAME = "adapter_status.json"

DISCLAIMER = "NOT investment advice — advisory estimates only"

# ─── Slippage model constants ─────────────────────────────────────────────────

# Liquidity-tier coefficients for the linear slippage model.
# T1-liquidity = deep, institutional markets (AMM/lending with large TVL).
# T2-liquidity = smaller / vault / epoch-based pools.
K_T1 = 0.5   # k for T1-liquidity protocols
K_T2 = 2.0   # k for T2-liquidity protocols and unknowns

# Warning threshold: slippage > WARN_THRESHOLD_BPS at AUM_REFERENCE_USD → warn.
WARN_THRESHOLD_BPS: int = 50

# Reference position size for portfolio-level checks and flag_low_liquidity.
# Represents our total paper-trading capital.
AUM_REFERENCE_USD: float = 100_000.0

# ─── Protocol registry (liquidity tier + conservative TVL fallback) ───────────
#
# Liquidity tier is NOT the same as the allocation tier from RiskPolicy:
#   - RiskPolicy T1: aave_v3, compound_v3           (allocation cap 40%)
#   - RiskPolicy T2: morpho_blue, yearn_v3, ...     (allocation cap 20%)
#
# Liquidity tier groups by market depth for slippage estimation:
#   - T1-liquidity: aave_v3, compound_v3, morpho_blue (large, institutional)
#   - T2-liquidity: yearn_v3, euler_v2, maple          (smaller / vault pools)

# Maps canonical protocol slug → liquidity tier label used by this module.
PROTOCOL_LIQUIDITY_TIER: Dict[str, str] = {
    "aave_v3":      "T1",
    "compound_v3":  "T1",
    "morpho_blue":  "T1",
    "yearn_v3":     "T2",
    "euler_v2":     "T2",
    "maple":        "T2",
}

# Conservative static TVL fallback (used when live data is unavailable).
# Intentionally low-side estimates so that slippage is OVERSTATED, not
# understated — a safer direction for an advisory module.
CONSERVATIVE_TVL_USD: Dict[str, float] = {
    "aave_v3":      2_000_000_000.0,   # $2B — very deep mainnet lending
    "compound_v3":    500_000_000.0,   # $500M
    "morpho_blue":    200_000_000.0,   # $200M
    "yearn_v3":        50_000_000.0,   # $50M vault
    "euler_v2":        30_000_000.0,   # $30M
    "maple":           20_000_000.0,   # $20M credit pool
}

# Fallback TVL for protocols NOT in the registry (very conservative).
DEFAULT_FALLBACK_TVL_USD: float = 5_000_000.0   # $5M — TVL floor from RiskPolicy

# Capacity curve sample points (USD notional).
CURVE_SAMPLE_POINTS_USD: Tuple[float, ...] = (
    1_000.0,
    5_000.0,
    10_000.0,
    25_000.0,
    50_000.0,
    100_000.0,
    250_000.0,
    500_000.0,
    1_000_000.0,
    10_000_000.0,
)


# ─── Tolerant IO helpers ──────────────────────────────────────────────────────


def _read_json(path: Path) -> Any:
    """Read JSON tolerantly: missing/broken file → None, never raises."""
    path = Path(path)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def _num(value: Any) -> Optional[float]:
    """Finite float or None (bool excluded; NaN/inf are not data)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    f = float(value)
    return f if math.isfinite(f) else None


# ─── Protocol data loader ─────────────────────────────────────────────────────


def _normalize_slug(name: Any) -> str:
    """Normalise a protocol name to a canonical lowercase underscore slug."""
    import re
    s = str(name).strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")


def _load_protocol_data(data_dir: Path) -> Dict[str, Dict[str, Any]]:
    """Load live TVL and tier data from the orchestrator status file.

    Returns a dict keyed by normalised protocol slug::

        {
          "aave_v3": {"tvl_usd": 183_871_978.0, "tier": "T1", "apy_pct": 3.21},
          ...
        }

    Falls back gracefully to an empty dict if the file is missing/broken.
    The caller fills in any gaps with CONSERVATIVE_TVL_USD.
    """
    result: Dict[str, Dict[str, Any]] = {}
    orch = _read_json(data_dir / ORCHESTRATOR_FILENAME)
    if isinstance(orch, dict):
        adapters = orch.get("adapters", [])
        if isinstance(adapters, list):
            for entry in adapters:
                if not isinstance(entry, dict):
                    continue
                slug = _normalize_slug(entry.get("protocol", ""))
                if not slug:
                    continue
                tvl = _num(entry.get("tvl_usd"))
                tier = entry.get("tier", "unknown")
                apy = _num(entry.get("apy_pct"))
                result[slug] = {
                    "tvl_usd": tvl,
                    "tier": str(tier) if tier else "unknown",
                    "apy_pct": apy,
                    "source": "live",
                }
    return result


def _get_tvl(
    protocol_slug: str,
    live_data: Dict[str, Dict[str, Any]],
) -> Tuple[float, str]:
    """Return (tvl_usd, source) for *protocol_slug*.

    Priority:
    1. Live data from adapter_orchestrator_status.json (if tvl_usd > 0).
    2. Conservative static fallback from CONSERVATIVE_TVL_USD.
    3. DEFAULT_FALLBACK_TVL_USD for unknown protocols.
    """
    if protocol_slug in live_data:
        tvl_live = live_data[protocol_slug].get("tvl_usd")
        if isinstance(tvl_live, float) and tvl_live > 0:
            return tvl_live, "live"
    if protocol_slug in CONSERVATIVE_TVL_USD:
        return CONSERVATIVE_TVL_USD[protocol_slug], "conservative_static"
    return DEFAULT_FALLBACK_TVL_USD, "default_fallback"


def _get_liquidity_tier(
    protocol_slug: str,
    live_data: Dict[str, Dict[str, Any]],
) -> str:
    """Return the *liquidity* tier ('T1' or 'T2') for *protocol_slug*.

    Uses :data:`PROTOCOL_LIQUIDITY_TIER` first (authoritative for this module),
    then falls back to 'T2' (conservative) for unknowns.
    """
    return PROTOCOL_LIQUIDITY_TIER.get(protocol_slug, "T2")


def _slippage_k(liquidity_tier: str) -> float:
    """Return the slippage coefficient *k* for the given *liquidity_tier*."""
    return K_T1 if liquidity_tier == "T1" else K_T2


# ─── Core slippage computation ────────────────────────────────────────────────


def _compute_slippage_bps(
    amount_usd: float,
    tvl_usd: float,
    k: float,
) -> float:
    """Core formula: slippage_bps = k * (amount_usd / tvl_usd) * 10_000.

    Clamps the result to [0, 10_000] (0–100%).
    Returns 0.0 if *amount_usd* <= 0 or *tvl_usd* <= 0.
    """
    if amount_usd <= 0.0 or tvl_usd <= 0.0:
        return 0.0
    raw = k * (amount_usd / tvl_usd) * 10_000.0
    return max(0.0, min(raw, 10_000.0))


# ─── Public API ───────────────────────────────────────────────────────────────


def estimate_slippage(
    protocol: str,
    amount_usd: float,
    direction: str = "enter",
    data_dir: Optional[str | os.PathLike] = None,
) -> Dict[str, Any]:
    """Estimate slippage for entering or exiting *amount_usd* in *protocol*.

    Parameters
    ----------
    protocol:
        Protocol name or slug (e.g. ``"aave_v3"``, ``"Aave V3"``).
    amount_usd:
        USD notional of the position to enter or exit.  Non-positive values
        return ``slippage_bps = 0``.
    direction:
        ``"enter"`` or ``"exit"`` (currently symmetric — same formula for
        both; the field is retained for future asymmetric models).
    data_dir:
        Override the data directory (default: ``<repo>/data``).

    Returns
    -------
    dict with keys::

        {
          "protocol": str,           # normalised slug
          "direction": str,          # "enter" | "exit"
          "amount_usd": float,
          "tvl_usd": float,
          "tvl_source": str,         # "live" | "conservative_static" | "default_fallback"
          "liquidity_tier": str,     # "T1" | "T2"
          "k": float,
          "slippage_bps": float,
          "slippage_pct": float,
          "verdict": str,            # "ok" | "warn" | "fail"
          "warn_threshold_bps": int,
          "advisory_only": True,
          "disclaimer": str,
          "notes": list[str],
        }

    NEVER raises.
    """
    try:
        ddir = Path(data_dir) if data_dir is not None else _DEFAULT_DATA_DIR
        slug = _normalize_slug(protocol)
        notes: List[str] = []

        direction_clean = str(direction).strip().lower()
        if direction_clean not in ("enter", "exit"):
            notes.append(
                f"unknown direction '{direction}' — defaulting to 'enter'"
            )
            direction_clean = "enter"

        amount = _num(amount_usd)
        if amount is None:
            notes.append(f"amount_usd '{amount_usd}' is not a finite number — treated as 0")
            amount = 0.0
        elif amount < 0:
            notes.append(f"amount_usd {amount_usd} is negative — treated as 0")
            amount = 0.0

        live_data = _load_protocol_data(ddir)
        tvl, tvl_source = _get_tvl(slug, live_data)
        tier = _get_liquidity_tier(slug, live_data)
        k = _slippage_k(tier)

        if slug not in PROTOCOL_LIQUIDITY_TIER and slug not in live_data:
            notes.append(
                f"protocol '{slug}' not in registry — using T2 coefficient (conservative)"
            )

        slippage_bps = _compute_slippage_bps(amount, tvl, k)
        slippage_pct = slippage_bps / 100.0

        if slippage_bps >= 200:
            verdict = "fail"
        elif slippage_bps > WARN_THRESHOLD_BPS:
            verdict = "warn"
        else:
            verdict = "ok"

        return {
            "protocol": slug,
            "direction": direction_clean,
            "amount_usd": round(amount, 6),
            "tvl_usd": round(tvl, 2),
            "tvl_source": tvl_source,
            "liquidity_tier": tier,
            "k": k,
            "slippage_bps": round(slippage_bps, 4),
            "slippage_pct": round(slippage_pct, 6),
            "verdict": verdict,
            "warn_threshold_bps": WARN_THRESHOLD_BPS,
            "advisory_only": True,
            "disclaimer": DISCLAIMER,
            "notes": notes,
        }
    except Exception as exc:
        log.warning("estimate_slippage degraded: %s", exc)
        return {
            "protocol": str(protocol),
            "direction": str(direction),
            "amount_usd": float(amount_usd) if isinstance(amount_usd, (int, float)) else 0.0,
            "tvl_usd": 0.0,
            "tvl_source": "error",
            "liquidity_tier": "unknown",
            "k": K_T2,
            "slippage_bps": 0.0,
            "slippage_pct": 0.0,
            "verdict": "warn",
            "warn_threshold_bps": WARN_THRESHOLD_BPS,
            "advisory_only": True,
            "disclaimer": DISCLAIMER,
            "notes": [f"internal error: {type(exc).__name__}: {exc}"],
        }


def get_capacity_curve(
    protocol: str,
    data_dir: Optional[str | os.PathLike] = None,
) -> List[Dict[str, Any]]:
    """Return the slippage capacity curve for *protocol*.

    Samples :data:`CURVE_SAMPLE_POINTS_USD` notional breakpoints and returns
    a list of ``{amount_usd, slippage_bps, slippage_pct, verdict}`` dicts,
    sorted ascending by *amount_usd*.  The curve is monotonically
    non-decreasing in *slippage_bps* by construction of the linear model.

    Returns an empty list only on a catastrophic internal error (NEVER raises).
    """
    try:
        ddir = Path(data_dir) if data_dir is not None else _DEFAULT_DATA_DIR
        slug = _normalize_slug(protocol)
        live_data = _load_protocol_data(ddir)
        tvl, tvl_source = _get_tvl(slug, live_data)
        tier = _get_liquidity_tier(slug, live_data)
        k = _slippage_k(tier)

        curve: List[Dict[str, Any]] = []
        for amount in CURVE_SAMPLE_POINTS_USD:
            bps = _compute_slippage_bps(amount, tvl, k)
            pct = bps / 100.0
            if bps >= 200:
                verdict = "fail"
            elif bps > WARN_THRESHOLD_BPS:
                verdict = "warn"
            else:
                verdict = "ok"
            curve.append({
                "amount_usd": amount,
                "slippage_bps": round(bps, 4),
                "slippage_pct": round(pct, 6),
                "verdict": verdict,
            })

        return curve
    except Exception as exc:
        log.warning("get_capacity_curve degraded for '%s': %s", protocol, exc)
        return []


def analyze_portfolio_liquidity(
    positions: Dict[str, float],
    data_dir: Optional[str | os.PathLike] = None,
) -> Dict[str, Any]:
    """Analyse exit/entry liquidity for an entire portfolio.

    Parameters
    ----------
    positions:
        ``{protocol_slug: usd_value}`` mapping of current positions.
        Non-positive values and non-string keys are skipped.
    data_dir:
        Override the data directory.

    Returns
    -------
    dict with keys::

        {
          "available": bool,
          "advisory_only": True,
          "total_aum_usd": float,
          "num_positions": int,
          "worst_case_bps": float,        # max slippage across all exit slippages
          "worst_case_protocol": str | None,
          "avg_exit_slippage_bps": float,
          "liquidity_score": float,       # 0–100, higher = more liquid
          "verdict": str,                 # "ok" | "warn" | "fail"
          "positions": {                  # per-position detail
              "<slug>": {
                  "usd": float,
                  "share": float,         # fraction of total AUM
                  "liquidity_tier": str,
                  "tvl_usd": float,
                  "enter_slippage_bps": float,
                  "exit_slippage_bps": float,
                  "verdict": str,
              },
              ...
          },
          "high_slippage_protocols": list[str],   # exit_slippage_bps > WARN_THRESHOLD_BPS
          "disclaimer": str,
          "notes": list[str],
        }

    NEVER raises.
    """
    try:
        ddir = Path(data_dir) if data_dir is not None else _DEFAULT_DATA_DIR
        notes: List[str] = []

        if not isinstance(positions, dict):
            return _portfolio_empty_result(
                notes=["positions must be a dict — got " + type(positions).__name__],
                available=False,
            )

        live_data = _load_protocol_data(ddir)

        # Parse positions.
        parsed: Dict[str, float] = {}
        for proto, usd in positions.items():
            slug = _normalize_slug(proto)
            if not slug:
                notes.append("skipped position with empty protocol name")
                continue
            val = _num(usd)
            if val is None:
                notes.append(f"{slug}: non-numeric USD value — skipped")
                continue
            if val <= 0:
                notes.append(f"{slug}: non-positive USD value ({usd}) — skipped")
                continue
            parsed[slug] = parsed.get(slug, 0.0) + val

        if not parsed:
            return _portfolio_empty_result(
                notes=notes + ["no valid positions to analyse"],
                available=True,
            )

        total_aum = sum(parsed.values())
        if total_aum <= 0:
            return _portfolio_empty_result(
                notes=notes + ["total AUM is zero"],
                available=True,
            )

        # Per-position slippage.
        pos_detail: Dict[str, Dict[str, Any]] = {}
        exit_bps_list: List[float] = []
        high_slippage: List[str] = []

        for slug, usd in parsed.items():
            tvl, tvl_source = _get_tvl(slug, live_data)
            tier = _get_liquidity_tier(slug, live_data)
            k = _slippage_k(tier)
            share = usd / total_aum

            enter_bps = _compute_slippage_bps(usd, tvl, k)
            exit_bps = _compute_slippage_bps(usd, tvl, k)  # symmetric model

            if exit_bps >= 200:
                pos_verdict = "fail"
            elif exit_bps > WARN_THRESHOLD_BPS:
                pos_verdict = "warn"
            else:
                pos_verdict = "ok"

            pos_detail[slug] = {
                "usd": round(usd, 6),
                "share": round(share, 9),
                "liquidity_tier": tier,
                "tvl_usd": round(tvl, 2),
                "tvl_source": tvl_source,
                "enter_slippage_bps": round(enter_bps, 4),
                "exit_slippage_bps": round(exit_bps, 4),
                "verdict": pos_verdict,
            }
            exit_bps_list.append(exit_bps)
            if exit_bps > WARN_THRESHOLD_BPS:
                high_slippage.append(slug)

        worst_bps = max(exit_bps_list) if exit_bps_list else 0.0
        worst_proto = max(
            pos_detail, key=lambda p: pos_detail[p]["exit_slippage_bps"]
        ) if pos_detail else None
        avg_bps = sum(exit_bps_list) / len(exit_bps_list) if exit_bps_list else 0.0

        # Liquidity score: 100 = zero slippage on all exits, 0 = >200 bps avg.
        liquidity_score = max(0.0, 100.0 - avg_bps / 2.0)
        liquidity_score = min(100.0, liquidity_score)

        if worst_bps >= 200:
            verdict = "fail"
        elif worst_bps > WARN_THRESHOLD_BPS or high_slippage:
            verdict = "warn"
        else:
            verdict = "ok"

        return {
            "available": True,
            "advisory_only": True,
            "execution_mode": "read_only",
            "total_aum_usd": round(total_aum, 6),
            "num_positions": len(parsed),
            "worst_case_bps": round(worst_bps, 4),
            "worst_case_protocol": worst_proto,
            "avg_exit_slippage_bps": round(avg_bps, 4),
            "liquidity_score": round(liquidity_score, 4),
            "verdict": verdict,
            "positions": pos_detail,
            "high_slippage_protocols": sorted(high_slippage),
            "disclaimer": DISCLAIMER,
            "notes": notes,
        }
    except Exception as exc:
        log.warning("analyze_portfolio_liquidity degraded: %s", exc)
        return _portfolio_empty_result(
            notes=[f"internal error: {type(exc).__name__}: {exc}"],
            available=False,
        )


def _portfolio_empty_result(
    notes: List[str],
    available: bool = False,
) -> Dict[str, Any]:
    """Stable-schema empty portfolio result."""
    return {
        "available": available,
        "advisory_only": True,
        "execution_mode": "read_only",
        "total_aum_usd": 0.0,
        "num_positions": 0,
        "worst_case_bps": 0.0,
        "worst_case_protocol": None,
        "avg_exit_slippage_bps": 0.0,
        "liquidity_score": 100.0,
        "verdict": "warn",
        "positions": {},
        "high_slippage_protocols": [],
        "disclaimer": DISCLAIMER,
        "notes": notes,
    }


def flag_low_liquidity_protocols(
    threshold_bps: int = WARN_THRESHOLD_BPS,
    reference_usd: float = AUM_REFERENCE_USD,
    data_dir: Optional[str | os.PathLike] = None,
) -> List[str]:
    """Return protocol slugs whose slippage exceeds *threshold_bps* at *reference_usd*.

    Evaluates all protocols in :data:`PROTOCOL_LIQUIDITY_TIER` plus any
    additional protocols found in the live orchestrator data.

    Parameters
    ----------
    threshold_bps:
        Slippage threshold in basis points (default 50 bps = 0.5%).
    reference_usd:
        Reference position size for the check (default :data:`AUM_REFERENCE_USD`
        = $100K, our full paper-trading capital).
    data_dir:
        Override the data directory.

    Returns
    -------
    Sorted list of protocol slugs (str) whose slippage > threshold.
    NEVER raises; returns ``[]`` on any internal error.
    """
    try:
        ddir = Path(data_dir) if data_dir is not None else _DEFAULT_DATA_DIR
        live_data = _load_protocol_data(ddir)

        # Evaluate all known protocols (registry + live).
        all_slugs = set(PROTOCOL_LIQUIDITY_TIER.keys()) | set(live_data.keys())

        flagged: List[str] = []
        for slug in all_slugs:
            tvl, _ = _get_tvl(slug, live_data)
            tier = _get_liquidity_tier(slug, live_data)
            k = _slippage_k(tier)
            ref = _num(reference_usd)
            if ref is None or ref <= 0:
                ref = AUM_REFERENCE_USD
            bps = _compute_slippage_bps(ref, tvl, k)
            if bps > threshold_bps:
                flagged.append(slug)

        return sorted(flagged)
    except Exception as exc:
        log.warning("flag_low_liquidity_protocols degraded: %s", exc)
        return []


# ─── CLI ──────────────────────────────────────────────────────────────────────


def _build_report(data_dir: Path) -> Dict[str, Any]:
    """Build a comprehensive advisory report for the CLI."""
    live_data = _load_protocol_data(data_dir)
    all_slugs = sorted(set(PROTOCOL_LIQUIDITY_TIER.keys()) | set(live_data.keys()))

    per_protocol: Dict[str, Any] = {}
    for slug in all_slugs:
        est = estimate_slippage(slug, AUM_REFERENCE_USD, "exit", data_dir)
        curve = get_capacity_curve(slug, data_dir)
        per_protocol[slug] = {
            "liquidity_tier": est["liquidity_tier"],
            "tvl_usd": est["tvl_usd"],
            "tvl_source": est["tvl_source"],
            "slippage_at_100k_bps": est["slippage_bps"],
            "slippage_at_100k_pct": est["slippage_pct"],
            "verdict": est["verdict"],
            "capacity_curve_points": len(curve),
        }

    flagged_50 = flag_low_liquidity_protocols(50, AUM_REFERENCE_USD, data_dir)
    flagged_100 = flag_low_liquidity_protocols(100, AUM_REFERENCE_USD, data_dir)

    return {
        "schema_version": 1,
        "source": "liquidity_depth_analyzer",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "advisory_only": True,
        "execution_mode": "read_only",
        "reference_position_usd": AUM_REFERENCE_USD,
        "warn_threshold_bps": WARN_THRESHOLD_BPS,
        "protocols_evaluated": len(per_protocol),
        "per_protocol": per_protocol,
        "flagged_gt_50bps": flagged_50,
        "flagged_gt_100bps": flagged_100,
        "disclaimer": DISCLAIMER,
    }


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python3 -m spa_core.paper_trading.liquidity_depth_analyzer",
        description=(
            "Protocol Liquidity Depth & Slippage Estimator (SPA / MP-126): "
            "read-only / advisory slippage estimates for all whitelisted "
            "protocols at the reference position size. Offline."
        ),
        add_help=True,
    )
    p.add_argument(
        "--check", action="store_true",
        help="compute and print the JSON report (default)",
    )
    p.add_argument("--data-dir", default=None, help="override data directory")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_arg_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        if exc.code not in (0, None):
            print(
                "ERROR: invalid arguments — use --check [--data-dir DIR]",
                file=sys.stderr,
            )
        return 0

    try:
        ddir = Path(args.data_dir) if args.data_dir else _DEFAULT_DATA_DIR
        report = _build_report(ddir)
        print(json.dumps(report, ensure_ascii=False, indent=2))
    except Exception as exc:
        print(
            f"liquidity_depth_analyzer: ERROR — {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
