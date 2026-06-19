#!/usr/bin/env python3
"""Net-of-Cost Performance & Cost-Drag Analyzer (SPA-V445 / MP-123) — read-only / advisory.

Answers the institutional due-diligence question the existing analytics leave
open: *"after the cost of actually running the strategy (rebalancing slippage +
gas), what is the NET return, and how much of the gross yield do trading costs
eat?"*. The yield-attribution analyzer (MP-117) reports the portfolio's GROSS
weighted APY; the turnover analyzer (MP-121) reports how much the book churns.
This module **composes** the two — gross yield minus an explicit, transparent
cost model driven by realised turnover — into a single net-of-cost picture.

Composition (reuse-by-import — zero duplicated math)
====================================================
Nothing is recomputed here that another module owns:

* GROSS portfolio APY and AUM come from
  :func:`spa_core.paper_trading.yield_attribution.build_yield_attribution`
  (MP-117 — ``portfolio_apy_pp`` over the full AUM incl. cash drag, ``aum_usd``).
* Rebalancing activity (``annualized_turnover``, ``num_rebalance_days``,
  ``num_observations``) comes from
  :func:`spa_core.paper_trading.turnover_analytics.build_turnover_analytics`
  (MP-121).
* The idempotency :func:`content_fingerprint` is **reused by import** from
  :mod:`spa_core.reporting.tear_sheet` (MP-501 — single source of truth).

Cost model (explicit, transparent, overridable assumptions)
===========================================================
Two honest, clearly-labelled cost components, both expressed as an annual drag
in percentage points (pp) of AUM:

* **Variable (turnover) cost** — every unit of one-way turnover moves notional
  through swaps/deposits that pay slippage + protocol/DEX fees::

      turnover_cost_bps = annualized_turnover · COST_PER_TURNOVER_BPS
      turnover_cost_pp  = turnover_cost_bps / 100

* **Fixed (gas) cost** — each rebalance day pays a roughly fixed on-chain gas
  bill, annualised by the observed rebalance frequency::

      rebalances_per_year = (num_rebalance_days / num_observations) · 365
      gas_cost_annual_usd = rebalances_per_year · GAS_PER_REBALANCE_USD
      gas_drag_pp         = gas_cost_annual_usd / aum · 100   (None if aum ≤ 0)

Net result::

      total_cost_drag_pp = turnover_cost_pp + gas_drag_pp
      net_apy_pct        = gross_apy_pp − total_cost_drag_pp
      cost_ratio         = total_cost_drag_pp / gross_apy_pp   (gross > 0; else None)

Low-sample honesty
==================
Annualising a rebalance count from a very short track is statistically weak.
When ``num_observations < `` :data:`MIN_RELIABLE_OBS` the result carries
``low_sample: true`` + a note, and the advisory verdict is **capped at "warn"**
(a tiny-sample annualization must never produce a confident "fail").

Verdict (advisory only — never blocks anything)
==============================================
* ``fail`` — net APY ≤ 0 (costs exceed gross yield), OR ``cost_ratio`` exceeds
  :data:`HIGH_COST_RATIO` (trading cost eats too much of the gross yield);
* ``warn`` — ``cost_ratio`` exceeds :data:`MODERATE_COST_RATIO`, OR gross yield
  is unknown / non-positive, OR the estimate is low-sample;
* ``ok`` — otherwise.

Output / persistence
====================
:func:`build_cost_drag` returns a stable-schema dict and NEVER raises (an
unavailable gross-yield or turnover input → honest ``available: false`` +
``reason`` + notes). :func:`write_status` atomically (tmp + ``os.replace``)
writes ``data/cost_drag_analytics.json`` with an in-file ``history`` of runs
(rotation ≤ :data:`HISTORY_MAX`). Idempotency: the imported
:func:`content_fingerprint` excludes the volatile ``meta.generated_at`` /
``history``, so a repeated ``--run`` on unchanged inputs is byte-identical and
does not grow history.

CLI (offline, exit 0 always, no tracebacks; junk args → clear ERROR on stderr)::

    python3 -m spa_core.paper_trading.cost_drag_analytics --check   # compute+print, no write (default)
    python3 -m spa_core.paper_trading.cost_drag_analytics --run     # + atomic write
    python3 -m spa_core.paper_trading.cost_drag_analytics --run --data-dir <dir>

Scope / safety: STRICTLY READ-ONLY (SPA-BL-011) and advisory only. Pure stdlib
(json/os/math/datetime/argparse/tempfile/logging/pathlib/typing) — no
requests/web3/LLM SDK/sockets/network/pandas/numpy. It only consumes the OUTPUT
of two sibling read-only analyzers (which themselves only read data files) and
writes its OWN status artifact; it never moves capital and never touches
risk/execution/allocator/cycle_runner.
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
from typing import Any, Dict, List, Optional

# REUSE BY IMPORT — gross portfolio APY + AUM (MP-117) and realised rebalancing
# activity (MP-121). We do NOT recompute either; we compose their outputs.
from spa_core.paper_trading.yield_attribution import build_yield_attribution
from spa_core.paper_trading.turnover_analytics import build_turnover_analytics

# REUSE BY IMPORT — single source of truth for the idempotency fingerprint
# (MP-501). We do NOT reimplement content_fingerprint here.
from spa_core.reporting.tear_sheet import content_fingerprint
from spa_core.utils.atomic import atomic_save

log = logging.getLogger("spa.paper_trading.cost_drag_analytics")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"

SCHEMA_VERSION = 1
SOURCE_NAME = "cost_drag_analytics"
STATUS_FILENAME = "cost_drag_analytics.json"
HISTORY_MAX = 500  # run-history rotation (pattern: turnover_analytics / tear_sheet)

# ── Cost-model assumptions (transparent, advisory, overridable per call). ──────
# Variable cost charged per unit of one-way turnover, in basis points of the
# notional moved. ~10 bps is a conservative stablecoin swap+slippage estimate.
COST_PER_TURNOVER_BPS = 10.0
# Roughly-fixed on-chain gas bill paid per rebalance day, in USD.
GAS_PER_REBALANCE_USD = 15.0

# Below this many turnover observations the annualised gas estimate is
# low-confidence; the verdict is capped at "warn".
MIN_RELIABLE_OBS = 20
ANNUALIZATION_DAYS = 365  # convention shared with turnover_analytics / risk_metrics

# Advisory verdict thresholds on cost_ratio (= total cost drag / gross yield).
MODERATE_COST_RATIO = 0.10  # > 10% of gross yield lost to cost → warn
HIGH_COST_RATIO = 0.30      # > 30% of gross yield lost to cost → fail

BPS_PER_PCT = 100.0
DISCLAIMER = "NOT investment advice"
SOURCE_MODULES = ["yield_attribution (MP-117)", "turnover_analytics (MP-121)"]


# ─── Tolerant IO helpers (pattern: turnover_analytics / yield_attribution) ─────


def _read_json(path: Path) -> Any:
    """Read JSON tolerantly: missing/broken file → None, never raises."""
    path = Path(path)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def _atomic_write_json(path: Path, obj: Any) -> None:
    """Shim — delegates to spa_core.utils.atomic.atomic_save."""
    atomic_save(obj, path)
def _round(value: Optional[float], ndigits: int = 6) -> Optional[float]:
    return None if value is None else round(value, ndigits)


# ─── Pure cost-model computation ───────────────────────────────────────────────


def compute_cost_components(
    annualized_turnover: float,
    num_rebalance_days: int,
    num_observations: int,
    aum_usd: Optional[float],
    *,
    cost_per_turnover_bps: float = COST_PER_TURNOVER_BPS,
    gas_per_rebalance_usd: float = GAS_PER_REBALANCE_USD,
) -> Dict[str, Optional[float]]:
    """Pure cost model → variable (turnover) and fixed (gas) annual drag in pp.

    ``turnover_cost_pp`` is always computable from ``annualized_turnover``.
    ``gas_drag_pp`` needs a positive AUM and at least one observation to
    annualise the rebalance frequency; otherwise it is ``None`` (honestly not
    computable) and contributes 0 to the total. Pure function; never raises.
    """
    turnover_cost_bps = max(0.0, annualized_turnover) * cost_per_turnover_bps
    turnover_cost_pp = turnover_cost_bps / BPS_PER_PCT

    rebalances_per_year: Optional[float] = None
    gas_cost_annual_usd: Optional[float] = None
    gas_drag_pp: Optional[float] = None
    if num_observations > 0:
        rebalances_per_year = (
            max(0, num_rebalance_days) / num_observations
        ) * ANNUALIZATION_DAYS
        gas_cost_annual_usd = rebalances_per_year * gas_per_rebalance_usd
        if aum_usd is not None and aum_usd > 0:
            gas_drag_pp = gas_cost_annual_usd / aum_usd * BPS_PER_PCT

    total = turnover_cost_pp + (gas_drag_pp or 0.0)
    return {
        "turnover_cost_bps": turnover_cost_bps,
        "turnover_cost_pp": turnover_cost_pp,
        "rebalances_per_year": rebalances_per_year,
        "gas_cost_annual_usd": gas_cost_annual_usd,
        "gas_drag_pp": gas_drag_pp,
        "total_cost_drag_pp": total,
    }


def _unavailable(
    meta: Dict[str, Any], reason: str
) -> Dict[str, Any]:
    return {
        "meta": meta,
        "available": False,
        "reason": reason,
        "low_sample": None,
        "gross_apy_pct": None,
        "net_apy_pct": None,
        "total_cost_drag_pp": None,
        "turnover_cost_pp": None,
        "gas_drag_pp": None,
        "cost_ratio": None,
        "cost_drag_bps": None,
        "aum_usd": None,
        "annualized_turnover": None,
        "num_rebalance_days": None,
        "num_observations": 0,
        "rebalances_per_year": None,
        "gas_cost_annual_usd": None,
        "verdict": None,
        "verdict_reason": None,
    }


def build_cost_drag(
    data_dir: Optional[str | os.PathLike] = None,
    now: Optional[datetime] = None,
    *,
    cost_per_turnover_bps: float = COST_PER_TURNOVER_BPS,
    gas_per_rebalance_usd: float = GAS_PER_REBALANCE_USD,
) -> Dict[str, Any]:
    """Build the net-of-cost / cost-drag document. Stable schema, never raises.

    Composes :func:`build_yield_attribution` (gross APY + AUM) and
    :func:`build_turnover_analytics` (annualised turnover + rebalance frequency)
    through the transparent cost model in :func:`compute_cost_components`, then
    derives net APY, the cost ratio and an advisory verdict. If either upstream
    analyzer is unavailable, returns an honest ``available: false`` result.
    """
    try:
        ddir = Path(data_dir) if data_dir is not None else _DEFAULT_DATA_DIR
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        notes: List[str] = []

        yld = build_yield_attribution(ddir)
        turn = build_turnover_analytics(ddir)

        # is_demo: any upstream that honestly declares demo wins.
        is_demo: Optional[bool] = None
        y_demo = yld.get("is_demo") if isinstance(yld, dict) else None
        t_demo = (
            (turn.get("meta") or {}).get("is_demo")
            if isinstance(turn, dict) else None
        )
        for flag in (y_demo, t_demo):
            if isinstance(flag, bool):
                is_demo = is_demo or flag
                if is_demo:
                    break

        meta = {
            "source": SOURCE_NAME,
            "schema_version": SCHEMA_VERSION,
            "generated_at": now.isoformat(),
            "advisory_only": True,
            "disclaimer": DISCLAIMER,
            "source_modules": list(SOURCE_MODULES),
            "is_demo": is_demo,
            "cost_per_turnover_bps": cost_per_turnover_bps,
            "gas_per_rebalance_usd": gas_per_rebalance_usd,
            "min_reliable_obs": MIN_RELIABLE_OBS,
            "moderate_cost_ratio": MODERATE_COST_RATIO,
            "high_cost_ratio": HIGH_COST_RATIO,
            "annualization_days": ANNUALIZATION_DAYS,
            "notes": notes,
        }

        if not (isinstance(yld, dict) and yld.get("available")):
            notes.append("yield_attribution (MP-117) unavailable — no gross APY")
            return _unavailable(meta, "gross_yield_unavailable")
        if not (isinstance(turn, dict) and turn.get("available")):
            notes.append("turnover_analytics (MP-121) unavailable — no turnover")
            return _unavailable(meta, "turnover_unavailable")

        gross_apy = _num(yld.get("portfolio_apy_pp"))
        aum = _num(yld.get("aum_usd"))
        head = turn.get("headline") or {}
        annualized_turnover = _num(head.get("annualized_turnover")) or 0.0
        num_rebalance = head.get("num_rebalance_days")
        num_rebalance = int(num_rebalance) if isinstance(num_rebalance, int) else 0
        num_obs = head.get("num_observations")
        num_obs = int(num_obs) if isinstance(num_obs, int) else 0

        if gross_apy is None:
            notes.append("portfolio_apy_pp missing from yield_attribution")
            return _unavailable(meta, "gross_yield_unavailable")

        comp = compute_cost_components(
            annualized_turnover,
            num_rebalance,
            num_obs,
            aum,
            cost_per_turnover_bps=cost_per_turnover_bps,
            gas_per_rebalance_usd=gas_per_rebalance_usd,
        )
        total_cost = comp["total_cost_drag_pp"] or 0.0
        net_apy = gross_apy - total_cost
        cost_ratio = (total_cost / gross_apy) if gross_apy > 0 else None

        low_sample = num_obs < MIN_RELIABLE_OBS
        if low_sample:
            notes.append(
                f"low_sample: only {num_obs} turnover observation(s) "
                f"(< {MIN_RELIABLE_OBS}) — annualised gas estimate is "
                "low-confidence; verdict capped at 'warn'"
            )
        if comp["gas_drag_pp"] is None:
            notes.append(
                "gas_drag not computable (AUM ≤ 0 or no observations) — "
                "treated as 0 in the total"
            )

        # ── Advisory verdict. ─────────────────────────────────────────────────
        if net_apy <= 0:
            base_verdict = "fail"
            reason = (
                f"net APY {net_apy:.4f}pp ≤ 0 — estimated trading cost "
                f"({total_cost:.4f}pp) exceeds gross yield ({gross_apy:.4f}pp)"
            )
        elif cost_ratio is None:
            base_verdict = "warn"
            reason = (
                "gross yield is non-positive / unknown — cost ratio undefined; "
                "net-of-cost return cannot be qualified"
            )
        elif cost_ratio > HIGH_COST_RATIO:
            base_verdict = "fail"
            reason = (
                f"cost ratio {cost_ratio:.3f} > {HIGH_COST_RATIO} — trading cost "
                f"consumes more than {HIGH_COST_RATIO:.0%} of gross yield"
            )
        elif cost_ratio > MODERATE_COST_RATIO:
            base_verdict = "warn"
            reason = (
                f"cost ratio {cost_ratio:.3f} > {MODERATE_COST_RATIO} — a "
                "material share of gross yield is lost to trading cost"
            )
        else:
            base_verdict = "ok"
            reason = (
                f"cost ratio {cost_ratio:.3f} ≤ {MODERATE_COST_RATIO} — net "
                f"APY {net_apy:.4f}pp retains most of the gross yield"
            )

        verdict = base_verdict
        if low_sample and base_verdict == "fail":
            verdict = "warn"
            reason = "[low-sample, capped from fail] " + reason

        meta["notes"] = notes
        return {
            "meta": meta,
            "available": True,
            "reason": None,
            "low_sample": low_sample,
            "gross_apy_pct": _round(gross_apy, 9),
            "net_apy_pct": _round(net_apy, 9),
            "total_cost_drag_pp": _round(total_cost, 9),
            "turnover_cost_pp": _round(comp["turnover_cost_pp"], 9),
            "gas_drag_pp": _round(comp["gas_drag_pp"], 9),
            "cost_ratio": _round(cost_ratio, 9),
            "cost_drag_bps": _round(total_cost * BPS_PER_PCT, 6),
            "aum_usd": _round(aum, 2),
            "annualized_turnover": _round(annualized_turnover, 6),
            "num_rebalance_days": num_rebalance,
            "num_observations": num_obs,
            "rebalances_per_year": _round(comp["rebalances_per_year"], 6),
            "gas_cost_annual_usd": _round(comp["gas_cost_annual_usd"], 2),
            "verdict": verdict,
            "verdict_reason": reason,
        }
    except Exception as exc:  # last resort: even a junk data_dir never raises
        log.warning("build_cost_drag degraded: %s", exc)
        meta = {
            "source": SOURCE_NAME,
            "schema_version": SCHEMA_VERSION,
            "generated_at": (now or datetime.now(timezone.utc)).isoformat()
            if isinstance(now, datetime) else datetime.now(timezone.utc).isoformat(),
            "advisory_only": True,
            "disclaimer": DISCLAIMER,
            "source_modules": list(SOURCE_MODULES),
            "is_demo": None,
            "notes": [f"internal error: {type(exc).__name__}: {exc}"],
        }
        return _unavailable(meta, "internal_error")


# ─── Persist (idempotent, pattern: turnover_analytics / tear_sheet) ───────────
# content_fingerprint is REUSED BY IMPORT from tear_sheet (see module header):
# it excludes volatile meta.generated_at / history, so a repeated --run on
# unchanged inputs is byte-identical and does not grow history.


def _history_entry(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Short run-history record for cost_drag_analytics.json."""
    meta = doc.get("meta") or {}
    return {
        "generated_at": meta.get("generated_at"),
        "gross_apy_pct": doc.get("gross_apy_pct"),
        "net_apy_pct": doc.get("net_apy_pct"),
        "total_cost_drag_pp": doc.get("total_cost_drag_pp"),
        "cost_ratio": doc.get("cost_ratio"),
        "verdict": doc.get("verdict"),
    }


def write_status(
    doc: Dict[str, Any], data_dir: Optional[str | os.PathLike] = None
) -> Dict[str, Any]:
    """Atomically write data/cost_drag_analytics.json (tmp + os.replace).

    Idempotency: if :func:`content_fingerprint` (reused from tear_sheet) is
    unchanged relative to the persisted status, the file is NOT rewritten (a
    repeated ``--run`` is byte-identical and history does not grow). On a
    content change a short record is appended to ``history`` (rotation ≤
    :data:`HISTORY_MAX`). A broken/absent existing status file is tolerated as
    fresh. Returns {"path", "changed"}.
    """
    ddir = Path(data_dir) if data_dir is not None else _DEFAULT_DATA_DIR
    path = ddir / STATUS_FILENAME
    prev = _read_json(path)
    if isinstance(prev, dict) and content_fingerprint(prev) == content_fingerprint(doc):
        log.info("cost drag analytics unchanged: %s", path)
        return {"path": str(path), "changed": False}

    history: List[Dict[str, Any]] = []
    if isinstance(prev, dict) and isinstance(prev.get("history"), list):
        history = [h for h in prev["history"] if isinstance(h, dict)]
    history.append(_history_entry(doc))
    out = dict(doc)
    out["history"] = history[-HISTORY_MAX:]
    _atomic_write_json(path, out)
    log.info("cost drag analytics written: %s", path)
    return {"path": str(path), "changed": True}


# ─── CLI (offline, advisory, exit 0, no tracebacks) ──────────────────────────


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python3 -m spa_core.paper_trading.cost_drag_analytics",
        description=(
            "Net-of-Cost Performance & Cost-Drag Analyzer (SPA-V445 / MP-123): "
            "read-only / advisory composition of gross yield (MP-117) and "
            "realised turnover (MP-121) into net-of-cost APY + cost ratio. "
            "Offline."
        ),
        add_help=True,
    )
    group = p.add_mutually_exclusive_group()
    group.add_argument(
        "--check", action="store_true",
        help="compute and print the JSON analytics WITHOUT writing (default)",
    )
    group.add_argument(
        "--run", action="store_true",
        help="compute and atomically write data/cost_drag_analytics.json",
    )
    p.add_argument("--data-dir", default=None, help="override data directory")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_arg_parser()
    # Custom error handling: argparse normally prints to stderr and exits 2 on a
    # junk arg; this advisory CLI must always exit 0 with a clear ERROR and no
    # traceback (pattern: turnover_analytics.py).
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        if exc.code not in (0, None):
            print(
                "ERROR: invalid arguments — use --check | --run [--data-dir DIR]",
                file=sys.stderr,
            )
        return 0

    try:
        doc = build_cost_drag(data_dir=args.data_dir)
        if args.run:
            outcome = write_status(doc, data_dir=args.data_dir)
            state = "DATA_WRITTEN" if outcome["changed"] else "DATA_UNCHANGED"
            print(
                f"cost_drag_analytics: available={doc.get('available')} "
                f"verdict={doc.get('verdict')} "
                f"gross={doc.get('gross_apy_pct')} "
                f"net={doc.get('net_apy_pct')} "
                f"cost_drag_pp={doc.get('total_cost_drag_pp')} "
                f"cost_ratio={doc.get('cost_ratio')} — "
                f"{state} {outcome['path']}"
            )
        else:
            print(json.dumps(doc, ensure_ascii=False, indent=2))
    except Exception as exc:  # advisory: no tracebacks, exit 0
        print(
            f"cost_drag_analytics: ERROR — {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
