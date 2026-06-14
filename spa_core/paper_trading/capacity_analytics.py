"""Strategy capacity & scalability analytics (SPA-V413 / MP-209 prep).

Read-only, advisory analytics layer that answers the fund's institutional
scalability question: *"How much AUM can this yield strategy actually absorb
before its own size starts eroding the realised APY?"* — i.e. the $10M+
capacity question. Where the V379–V412 paper-trading suite is mostly
return-SERIES analytics on the daily equity curve, this module looks at the
*market depth* of each pool the book deploys into and derives a per-pool
position cap, a slippage-degraded ("capacity-adjusted") APY, and a
portfolio-level scalability ceiling under the current target weights.

What it computes
================
Per pool:
  * ``max_position_usd`` = ``min(TVL * MAX_TVL_SHARE,
    daily_exit_volume_usd * MAX_DAILY_VOLUME_SHARE)`` — the largest USDC
    position we are willing to hold without dominating the pool's liquidity
    or its daily exit throughput. When the daily exit volume is unknown (we do
    not have a live volume feed in this read-only scope) we fall back to the
    proxy ``daily_exit_volume_usd = TVL * DAILY_LIQUIDITY_FRACTION`` — i.e. we
    assume a fraction of TVL turns over / can be withdrawn per day. This
    assumption is documented in the report's ``assumptions`` block and flagged
    per pool via ``volume_source`` ("proxy_from_tvl" vs "provided").
  * ``capacity_adjusted_apy`` — a deliberately simple, transparent
    yield-impact model. As a position grows toward its cap, price/yield impact
    (slippage on entry/exit, dilution of the pool's reward rate) eats into the
    realised APY::

        utilization     = clamp(position_usd / max_position_usd, 0, 1)
        slippage_penalty = MAX_SLIPPAGE_PENALTY * utilization
        effective_apy   = base_apy * (1 - slippage_penalty)

    So at a vanishingly small position ``effective_apy ~= base_apy`` (penalty
    ~0) and at the full cap ``effective_apy = base_apy * (1 - MAX_SLIPPAGE_PENALTY)``.
    The penalty is linear in utilisation; it is intentionally NOT a
    sophisticated AMM curve — this is an advisory first-order estimate.

Per portfolio (under the current ``target_weights``):
  * ``max_aum_usd`` (the scalability ceiling) = ``min_i (max_position_usd_i /
    weight_i)`` over pools with ``weight_i > 0``. This is the largest AUM that
    can be deployed at the current weights before *some* pool hits its own
    per-pool cap.
  * ``blended_apy_at_current`` / ``blended_apy_at_ceiling`` — the
    weight-blended capacity-adjusted APY of the book at the current capital and
    at the scalability ceiling (where, by construction, the binding pool sits
    at full utilisation and is taking its full slippage penalty).
  * ``grade`` (A–D) and ``verdict`` derived from the achieved ceiling.

Grade / verdict thresholds (on ``max_aum_usd``):
    A  >= $50M   scales_to_institutional
    B  >= $10M   scales_to_midsize
    C  >= $1M    capacity_constrained
    D  <  $1M    capacity_constrained
    (no usable pools / weights)  -> grade None, verdict insufficient_data

Constants (defaults; all surfaced in the report's ``assumptions`` block):
    MAX_TVL_SHARE           = 0.02   position <= 2% of pool TVL
    MAX_DAILY_VOLUME_SHARE  = 0.10   position <= 10% of daily exit volume
    DAILY_LIQUIDITY_FRACTION= 0.10   proxy: 10% of TVL withdrawable per day
    MAX_SLIPPAGE_PENALTY    = 0.30   APY haircut at full per-pool capacity

Design notes / safety
======================
  * Pure stdlib (json, math, os, datetime, pathlib, logging, argparse). No
    web3 / numpy / pandas / scipy / requests / network — mirrors the
    no-external-dependency style of the sibling paper-trading modules.
  * STRICTLY READ-ONLY and ADVISORY (SPA-BL-011 / LLM_FORBIDDEN_AGENTS). It
    reads ``adapter_orchestrator_status.json`` and ``target_allocation.json``
    and writes a single derived report JSON. It NEVER touches the execution
    path, risk / monitoring agents, wallets, money-moving code, or the
    SPA-BL-011-frozen feed-health domain. It does not enforce anything and does
    not move capital — it only computes advisory numbers.
  * The analytic core is a set of pure functions over plain Python structures
    (mirroring ``exit_latency_policy.py``); file loading is a thin wrapper. The
    positions input is accepted both as a Mapping and as a Sequence
    (see :data:`PoolsInput`), and both shapes produce identical results.
  * Defensive: missing / empty / malformed inputs degrade to a stable-schema
    object with undefined metrics set to ``None``. The module NEVER raises on
    bad data (no pools, ``tvl_usd`` None/0, ``apy`` None, ``weight`` 0, empty
    allocation are all handled).

CLI::

    python3 -m spa_core.paper_trading.capacity_analytics
    python3 -m spa_core.paper_trading.capacity_analytics \\
        --status data/adapter_orchestrator_status.json \\
        --allocation data/target_allocation.json \\
        --out data/capacity_analytics.json --no-write
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

log = logging.getLogger("spa.paper_trading.capacity_analytics")

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STATUS_PATH = _PROJECT_ROOT / "data" / "adapter_orchestrator_status.json"
DEFAULT_ALLOCATION_PATH = _PROJECT_ROOT / "data" / "target_allocation.json"
DEFAULT_OUTPUT_PATH = _PROJECT_ROOT / "data" / "capacity_analytics.json"

SCHEMA_VERSION = 1

# ─── Tunable constants (documented in the report's ``assumptions`` block) ────────

# A single position must not exceed this fraction of a pool's TVL.
MAX_TVL_SHARE: float = 0.02
# ...nor this fraction of the pool's daily withdrawable / exit volume.
MAX_DAILY_VOLUME_SHARE: float = 0.10
# Proxy used when no daily volume feed is available: assume this fraction of
# TVL can be exited per day.
DAILY_LIQUIDITY_FRACTION: float = 0.10
# APY haircut (slippage / yield-impact penalty) applied at the full per-pool cap.
MAX_SLIPPAGE_PENALTY: float = 0.30

# Scalability ceiling grade thresholds on max_aum_usd (USD).
GRADE_A_MIN_AUM: float = 50_000_000.0   # institutional
GRADE_B_MIN_AUM: float = 10_000_000.0   # mid-size
GRADE_C_MIN_AUM: float = 1_000_000.0    # constrained but usable

# A pool/portfolio is identified by a protocol name and carries a TVL (USD),
# a base APY (decimal fraction, e.g. 0.05 == 5%) and optionally a daily exit
# volume (USD). Accepted as a Mapping {protocol: {...}} or a Sequence of
# (protocol, tvl_usd, base_apy[, daily_volume_usd]) rows.
PoolsInput = Union[
    Mapping[str, Mapping[str, Optional[float]]],
    Sequence[Tuple[Any, ...]],
]


@dataclass(frozen=True)
class _Pool:
    protocol: str
    tvl_usd: Optional[float]
    base_apy: Optional[float]          # decimal fraction
    daily_volume_usd: Optional[float]  # explicit daily exit volume, if known


# ─── Coercion helpers ────────────────────────────────────────────────────────


def _as_float(value: Any) -> Optional[float]:
    """Coerce *value* to a finite float, else None (defensive)."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f):
        return None
    return f


def _normalize_pools(pools: PoolsInput) -> List[_Pool]:
    """Coerce the supported input shapes into a list of :class:`_Pool`.

    Mapping form — ``{protocol: {"tvl_usd", "base_apy", "daily_volume_usd"}}``.
    Sequence form — rows ``(protocol, tvl_usd, base_apy)`` or
    ``(protocol, tvl_usd, base_apy, daily_volume_usd)``.

    Never raises on a malformed individual entry — bad rows are skipped.
    """
    out: List[_Pool] = []
    if isinstance(pools, Mapping):
        for protocol, info in pools.items():
            if not isinstance(info, Mapping):
                continue
            name = str(protocol)
            if not name:
                continue
            out.append(
                _Pool(
                    protocol=name,
                    tvl_usd=_as_float(info.get("tvl_usd")),
                    base_apy=_as_float(info.get("base_apy")),
                    daily_volume_usd=_as_float(info.get("daily_volume_usd")),
                )
            )
    else:
        for row in pools:
            try:
                protocol = row[0]
                tvl = row[1] if len(row) > 1 else None
                apy = row[2] if len(row) > 2 else None
                vol = row[3] if len(row) > 3 else None
            except (TypeError, IndexError):
                continue
            name = str(protocol)
            if not name:
                continue
            out.append(
                _Pool(
                    protocol=name,
                    tvl_usd=_as_float(tvl),
                    base_apy=_as_float(apy),
                    daily_volume_usd=_as_float(vol),
                )
            )
    return out


def _normalize_weights(weights: Optional[Mapping[str, Any]]) -> Dict[str, float]:
    """Return {protocol: weight} keeping only positive, finite weights."""
    out: Dict[str, float] = {}
    if not isinstance(weights, Mapping):
        return out
    for protocol, value in weights.items():
        if not isinstance(protocol, str) or not protocol:
            continue
        w = _as_float(value)
        if w is None or w <= 0:
            continue
        out[protocol] = out.get(protocol, 0.0) + w
    return out


# ─── Pure analytic core ───────────────────────────────────────────────────────


def daily_exit_volume_usd(
    pool: _Pool,
    daily_liquidity_fraction: float = DAILY_LIQUIDITY_FRACTION,
) -> Tuple[Optional[float], str]:
    """Resolve a pool's daily exit volume and its provenance.

    Returns ``(volume_usd, source)`` where *source* is ``"provided"`` when the
    pool carried an explicit ``daily_volume_usd``, ``"proxy_from_tvl"`` when we
    fall back to ``TVL * daily_liquidity_fraction``, or ``"unknown"`` when no
    estimate can be formed (no volume and no usable TVL).
    """
    if pool.daily_volume_usd is not None and pool.daily_volume_usd > 0:
        return pool.daily_volume_usd, "provided"
    if pool.tvl_usd is not None and pool.tvl_usd > 0:
        return pool.tvl_usd * daily_liquidity_fraction, "proxy_from_tvl"
    return None, "unknown"


def max_position_usd(
    pool: _Pool,
    max_tvl_share: float = MAX_TVL_SHARE,
    max_daily_volume_share: float = MAX_DAILY_VOLUME_SHARE,
    daily_liquidity_fraction: float = DAILY_LIQUIDITY_FRACTION,
) -> Tuple[Optional[float], str]:
    """Per-pool position cap = ``min(TVL-cap, volume-cap)``. Pure.

    ``TVL-cap    = TVL * max_tvl_share``
    ``volume-cap = daily_exit_volume * max_daily_volume_share``

    Returns ``(cap_usd, volume_source)``. ``cap_usd`` is ``None`` when the pool
    has no usable TVL (and therefore neither cap can be computed).
    """
    vol, vol_source = daily_exit_volume_usd(pool, daily_liquidity_fraction)

    tvl_cap = (
        pool.tvl_usd * max_tvl_share
        if pool.tvl_usd is not None and pool.tvl_usd > 0
        else None
    )
    vol_cap = vol * max_daily_volume_share if vol is not None and vol > 0 else None

    caps = [c for c in (tvl_cap, vol_cap) if c is not None]
    if not caps:
        return None, vol_source
    return min(caps), vol_source


def capacity_adjusted_apy(
    base_apy: Optional[float],
    position_usd: Optional[float],
    cap_usd: Optional[float],
    max_slippage_penalty: float = MAX_SLIPPAGE_PENALTY,
) -> Optional[float]:
    """Slippage-degraded effective APY. Pure.

    ``utilization     = clamp(position_usd / cap_usd, 0, 1)``
    ``slippage_penalty = max_slippage_penalty * utilization``
    ``effective_apy   = base_apy * (1 - slippage_penalty)``

    Returns ``None`` when the base APY is unknown. When the cap is unknown /
    non-positive the utilisation is treated as 0 (no penalty) — we cannot claim
    a haircut we cannot size.
    """
    if base_apy is None:
        return None
    util = utilization(position_usd, cap_usd)
    penalty = max_slippage_penalty * util
    return base_apy * (1.0 - penalty)


def utilization(position_usd: Optional[float], cap_usd: Optional[float]) -> float:
    """``clamp(position_usd / cap_usd, 0, 1)``; 0 when cap is unknown/<=0."""
    pos = position_usd if position_usd is not None else 0.0
    if cap_usd is None or cap_usd <= 0:
        return 0.0
    return max(0.0, min(1.0, pos / cap_usd))


def grade_and_verdict(max_aum_usd: Optional[float]) -> Tuple[Optional[str], str]:
    """Map an achieved AUM ceiling to a grade (A–D) and a verdict string."""
    if max_aum_usd is None or max_aum_usd <= 0:
        return None, "insufficient_data"
    if max_aum_usd >= GRADE_A_MIN_AUM:
        return "A", "scales_to_institutional"
    if max_aum_usd >= GRADE_B_MIN_AUM:
        return "B", "scales_to_midsize"
    if max_aum_usd >= GRADE_C_MIN_AUM:
        return "C", "capacity_constrained"
    return "D", "capacity_constrained"


def compute_capacity_metrics(
    pools: PoolsInput,
    weights: Optional[Mapping[str, Any]] = None,
    current_aum_usd: Optional[float] = None,
    *,
    max_tvl_share: float = MAX_TVL_SHARE,
    max_daily_volume_share: float = MAX_DAILY_VOLUME_SHARE,
    daily_liquidity_fraction: float = DAILY_LIQUIDITY_FRACTION,
    max_slippage_penalty: float = MAX_SLIPPAGE_PENALTY,
) -> Dict[str, Any]:
    """Full per-pool + per-portfolio capacity analysis. Pure / read-only.

    Accepts pools as a Mapping or Sequence (see :data:`PoolsInput`); ``weights``
    is a {protocol: weight} mapping (current target allocation) and
    ``current_aum_usd`` the capital currently being deployed. All three may be
    empty/None; the result is always a stable schema with undefined metrics set
    to ``None`` and never raises.

    Returned keys: ``pools`` (list of per-pool dicts), ``portfolio`` (ceiling /
    blended APY / grade / verdict), ``num_pools``.
    """
    parsed = _normalize_pools(pools)
    norm_weights = _normalize_weights(weights)
    current_aum = _as_float(current_aum_usd)

    # ── Per-pool ─────────────────────────────────────────────────────────────
    pool_reports: List[Dict[str, Any]] = []
    caps_by_protocol: Dict[str, Optional[float]] = {}
    apy_by_protocol: Dict[str, Optional[float]] = {}

    for p in parsed:
        cap, vol_source = max_position_usd(
            p, max_tvl_share, max_daily_volume_share, daily_liquidity_fraction
        )
        vol, _ = daily_exit_volume_usd(p, daily_liquidity_fraction)

        # The current position implied by the portfolio weight & current AUM.
        weight = norm_weights.get(p.protocol)
        position_now = (
            current_aum * weight
            if current_aum is not None and weight is not None
            else None
        )

        adj_apy_now = capacity_adjusted_apy(
            p.base_apy, position_now, cap, max_slippage_penalty
        )
        # APY when this pool sits exactly at its own cap (full utilisation).
        adj_apy_at_cap = capacity_adjusted_apy(
            p.base_apy, cap, cap, max_slippage_penalty
        )

        caps_by_protocol[p.protocol] = cap
        apy_by_protocol[p.protocol] = p.base_apy

        pool_reports.append(
            {
                "protocol": p.protocol,
                "tvl_usd": p.tvl_usd,
                "base_apy": p.base_apy,
                "daily_exit_volume_usd": vol,
                "volume_source": vol_source,
                "max_position_usd": cap,
                "weight": weight,
                "position_usd_at_current_aum": position_now,
                "utilization_at_current_aum": (
                    utilization(position_now, cap) if position_now is not None else None
                ),
                "capacity_adjusted_apy_at_current": adj_apy_now,
                "capacity_adjusted_apy_at_cap": adj_apy_at_cap,
            }
        )

    # ── Portfolio scalability ceiling ─────────────────────────────────────────
    # max_aum = min_i (cap_i / weight_i) over weighted pools with a known cap.
    per_pool_aum: List[Tuple[str, float]] = []
    for protocol, weight in norm_weights.items():
        cap = caps_by_protocol.get(protocol)
        if cap is None or weight <= 0:
            continue
        per_pool_aum.append((protocol, cap / weight))

    if per_pool_aum:
        binding_protocol, max_aum = min(per_pool_aum, key=lambda kv: kv[1])
    else:
        binding_protocol, max_aum = None, None

    total_weight = sum(norm_weights.values())

    blended_at_current = _blended_apy(
        parsed, apy_by_protocol, caps_by_protocol, norm_weights,
        total_weight, current_aum, max_slippage_penalty,
    )
    blended_at_ceiling = _blended_apy(
        parsed, apy_by_protocol, caps_by_protocol, norm_weights,
        total_weight, max_aum, max_slippage_penalty,
    )

    grade, verdict = grade_and_verdict(max_aum)

    portfolio = {
        "current_aum_usd": current_aum,
        "max_aum_usd": max_aum,
        "binding_pool": binding_protocol,
        "num_weighted_pools": len(norm_weights),
        "blended_apy_at_current": blended_at_current,
        "blended_apy_at_ceiling": blended_at_ceiling,
        "grade": grade,
        "verdict": verdict,
    }

    return {
        "num_pools": len(parsed),
        "pools": pool_reports,
        "portfolio": portfolio,
    }


def _blended_apy(
    pools: List[_Pool],
    apy_by_protocol: Dict[str, Optional[float]],
    caps_by_protocol: Dict[str, Optional[float]],
    weights: Dict[str, float],
    total_weight: float,
    aum_usd: Optional[float],
    max_slippage_penalty: float,
) -> Optional[float]:
    """Weight-blended capacity-adjusted APY at a given AUM. Pure.

    Blends over the weighted pools (weights renormalised to the invested
    portion). Returns ``None`` when there are no usable weighted pools with a
    known base APY, or when ``aum_usd`` is unknown.
    """
    if aum_usd is None or total_weight <= 0:
        return None
    numerator = 0.0
    denom = 0.0
    for protocol, weight in weights.items():
        base = apy_by_protocol.get(protocol)
        if base is None:
            continue
        cap = caps_by_protocol.get(protocol)
        position = aum_usd * weight
        eff = capacity_adjusted_apy(base, position, cap, max_slippage_penalty)
        if eff is None:
            continue
        numerator += weight * eff
        denom += weight
    if denom <= 0:
        return None
    return numerator / denom


# ─── File-loading wrapper (thin; mirrors exit_latency_policy split) ──────────────


def _load_json(path: str | Path) -> Optional[dict]:
    """Load a JSON object from *path*; return None on any failure (read-only)."""
    try:
        with Path(path).open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            return data
        log.debug("Source %s is not a JSON object (got %s)", path, type(data).__name__)
        return None
    except FileNotFoundError:
        log.debug("Source not found: %s", path)
        return None
    except (OSError, ValueError) as exc:
        log.debug("Could not read source %s: %s", path, exc)
        return None


def pools_from_status(status: Optional[dict]) -> Dict[str, Dict[str, Optional[float]]]:
    """Extract a {protocol: {tvl_usd, base_apy}} mapping from orchestrator status.

    Reads ``adapters[].protocol``, ``.tvl_usd`` and ``.apy_pct`` (APY in
    PERCENT — divided by 100 here to a decimal fraction). Returns ``{}`` for any
    malformed / empty input (never raises).
    """
    out: Dict[str, Dict[str, Optional[float]]] = {}
    if not isinstance(status, dict):
        return out
    adapters = status.get("adapters")
    if not isinstance(adapters, list):
        return out
    for entry in adapters:
        if not isinstance(entry, dict):
            continue
        protocol = entry.get("protocol")
        if not isinstance(protocol, str) or not protocol:
            continue
        apy_pct = _as_float(entry.get("apy_pct"))
        base_apy = apy_pct / 100.0 if apy_pct is not None else None
        out[protocol] = {
            "tvl_usd": _as_float(entry.get("tvl_usd")),
            "base_apy": base_apy,
        }
    return out


def _weights_and_capital(allocation: Optional[dict]) -> Tuple[Dict[str, Any], Optional[float]]:
    """Extract (target_weights, capital_usd) from a target_allocation doc."""
    if not isinstance(allocation, dict):
        return {}, None
    weights = allocation.get("target_weights")
    weights = weights if isinstance(weights, dict) else {}
    capital = _as_float(allocation.get("capital_usd"))
    return weights, capital


def build_capacity_report(
    status_path: str | Path = DEFAULT_STATUS_PATH,
    allocation_path: str | Path | None = DEFAULT_ALLOCATION_PATH,
) -> dict:
    """Build the full capacity report dict (no I/O beyond reading inputs)."""
    status = _load_json(status_path)
    allocation = _load_json(allocation_path) if allocation_path else None

    pools = pools_from_status(status)
    weights, capital = _weights_and_capital(allocation)

    metrics = compute_capacity_metrics(
        pools=pools,
        weights=weights,
        current_aum_usd=capital,
    )

    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "execution_mode": "read_only_simulation",
        "source": str(status_path),
        "allocation_source": str(allocation_path) if allocation_path else None,
        "assumptions": {
            "max_tvl_share": MAX_TVL_SHARE,
            "max_daily_volume_share": MAX_DAILY_VOLUME_SHARE,
            "daily_liquidity_fraction": DAILY_LIQUIDITY_FRACTION,
            "max_slippage_penalty": MAX_SLIPPAGE_PENALTY,
            "grade_a_min_aum_usd": GRADE_A_MIN_AUM,
            "grade_b_min_aum_usd": GRADE_B_MIN_AUM,
            "grade_c_min_aum_usd": GRADE_C_MIN_AUM,
            "daily_volume_proxy": (
                "When a pool has no explicit daily exit volume, daily exit "
                "volume is approximated as TVL * daily_liquidity_fraction "
                "(volume_source='proxy_from_tvl')."
            ),
            "max_position_model": (
                "max_position_usd = min(TVL * max_tvl_share, "
                "daily_exit_volume * max_daily_volume_share)."
            ),
            "capacity_adjusted_apy_model": (
                "effective_apy = base_apy * (1 - max_slippage_penalty * "
                "utilization), utilization = clamp(position_usd / "
                "max_position_usd, 0, 1)."
            ),
            "apy_units": "base_apy stored as a decimal fraction (apy_pct / 100).",
        },
        "metrics": metrics,
    }
    return report


# ─── Atomic write + orchestration ────────────────────────────────────────────


def _atomic_write_json(obj: dict, out_path: Path) -> None:
    """Write *obj* as pretty JSON to *out_path* atomically (tmp + os.replace)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_name(f".capacity_analytics_{os.getpid()}.tmp")
    try:
        tmp.write_text(
            json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        os.replace(tmp, out_path)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def generate_capacity_report(
    status_path: str | Path = DEFAULT_STATUS_PATH,
    allocation_path: str | Path | None = DEFAULT_ALLOCATION_PATH,
    output_path: str | Path | None = DEFAULT_OUTPUT_PATH,
) -> dict:
    """Build the capacity report and (optionally) persist it atomically.

    Pass ``output_path=None`` to compute only. Write failures are logged, not
    raised, so an analytics report never crashes a caller.
    """
    report = build_capacity_report(status_path, allocation_path)

    if output_path is not None:
        out = Path(output_path)
        try:
            _atomic_write_json(report, out)
            pf = report["metrics"]["portfolio"]
            log.info(
                "capacity report written: %s (max_aum=%s, grade=%s, verdict=%s)",
                out, pf["max_aum_usd"], pf["grade"], pf["verdict"],
            )
        except OSError as exc:
            log.warning("could not write capacity report to %s: %s", output_path, exc)

    return report


# ─── CLI ──────────────────────────────────────────────────────────────────────


def _fmt_usd(v: Optional[float]) -> str:
    return f"${v:,.0f}" if isinstance(v, (int, float)) else "n/a"


def _fmt_pct(v: Optional[float]) -> str:
    return f"{v * 100.0:.2f}%" if isinstance(v, (int, float)) else "n/a"


def _format_summary(report: dict) -> str:
    pf = report["metrics"]["portfolio"]
    n = report["metrics"]["num_pools"]
    line = (
        f"CAPACITY | pools={n} | max_AUM={_fmt_usd(pf['max_aum_usd'])} "
        f"| binding={pf['binding_pool'] or 'n/a'} "
        f"| blended_APY@current={_fmt_pct(pf['blended_apy_at_current'])} "
        f"| blended_APY@ceiling={_fmt_pct(pf['blended_apy_at_ceiling'])} "
        f"| grade={pf['grade'] or 'n/a'} | verdict={pf['verdict']}"
    )
    return line


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Strategy capacity & scalability analytics (SPA-V413, read-only).",
    )
    p.add_argument(
        "--status", default=str(DEFAULT_STATUS_PATH),
        help="path to adapter_orchestrator_status.json "
             "(default: data/adapter_orchestrator_status.json)",
    )
    p.add_argument(
        "--allocation", default=str(DEFAULT_ALLOCATION_PATH),
        help="path to target_allocation.json (default: data/target_allocation.json)",
    )
    p.add_argument(
        "--out", default=str(DEFAULT_OUTPUT_PATH),
        help="output report path (default: data/capacity_analytics.json)",
    )
    p.add_argument(
        "--no-write", action="store_true",
        help="compute and print only; do not write the report file",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    report = generate_capacity_report(
        status_path=args.status,
        allocation_path=args.allocation,
        output_path=None if args.no_write else args.out,
    )
    print(_format_summary(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
