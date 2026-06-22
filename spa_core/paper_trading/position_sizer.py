#!/usr/bin/env python3
"""Position sizing engine for SPA portfolio (MP-576).

Computes target weights and dollar allocations for each adapter based on
current portfolio state, risk limits, and tier caps.  Produces a full sizing
report that cycle_runner (or any downstream tool) can consume directly.

Design rules (project-wide)
============================
* **Stdlib only** — no external deps (no requests, web3, LLM SDK).
* **Atomic writes** — tmp file + os.replace on every JSON update.
* **LLM-FORBIDDEN** — no AI/LLM calls here; pure deterministic arithmetic.
* **Read-only wrt capital** — does NOT import execution/, does NOT touch
  trades.json, current_positions.json, or any other capital-state file.

Tier cap defaults (aligned with RiskPolicy v1.0 + ADR-019/020)
===============================================================
* T1 — max 60 % of portfolio (single T1 ≤ 40 %)
* T2 — max 25 % per protocol; T2 total ≤ 50 %  (ADR-019)
* T3 — max 10 % per protocol; T3 total ≤ 15 %  (ADR-020)
* Cash (any adapter not in T1/T2/T3) — treated like T1 for sizing purposes.

Concentration limit
===================
No single adapter may exceed ``max_single`` (default 40 %) regardless of tier.

Usage example
=============
::

    from spa_core.paper_trading.position_sizer import PositionSizer

    sizer = PositionSizer()
    adapters = {"aave_v3": {"apy": 3.5, "tvl": 1e9}, "compound_v3": {"apy": 4.8, "tvl": 5e8}}
    adapter_tiers = {"aave_v3": "T1", "compound_v3": "T1"}
    risk_limits = {"max_single": 0.40, "min_cash_buffer": 0.05}
    weights = sizer.compute_target_weights(adapters, 100_000.0, risk_limits)
    allocs  = sizer.compute_dollar_allocations(weights, 100_000.0)
    report  = sizer.get_sizing_report(adapters, 100_000.0, risk_limits)

CLI (offline, exit 0 always)::

    python3 -m spa_core.paper_trading.position_sizer --check
    python3 -m spa_core.paper_trading.position_sizer --run
    python3 -m spa_core.paper_trading.position_sizer --run --data-dir data
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

log = logging.getLogger("spa.paper_trading.position_sizer")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = str(_REPO_ROOT / "data")

REPORT_FILENAME = "position_sizing_report.json"
REPORT_HISTORY_MAX = 365  # ring-buffer for history snapshots

# ─── Tier cap constants ───────────────────────────────────────────────────────

# Per-protocol caps (fraction of portfolio)
TIER_CAP_T1_PER_PROTOCOL: float = 0.60   # single T1 ≤ 60% (applied via apply_tier_caps)
TIER_CAP_T2_PER_PROTOCOL: float = 0.25   # single T2 ≤ 25%
TIER_CAP_T3_PER_PROTOCOL: float = 0.10   # single T3 ≤ 10%

# Aggregate tier caps (total portfolio share, applied separately)
TIER_CAP_T1_TOTAL: float = 0.60   # all T1 combined ≤ 60%
TIER_CAP_T2_TOTAL: float = 0.50   # all T2 combined ≤ 50%  (ADR-019)
TIER_CAP_T3_TOTAL: float = 0.15   # all T3 combined ≤ 15%  (ADR-020)

# Default concentration limit
DEFAULT_MAX_SINGLE: float = 0.40  # absolute per-adapter cap (any tier)

# Minimum APY to be included in sizing (below → excluded)
MIN_ELIGIBLE_APY: float = 1.0   # %
MAX_ELIGIBLE_APY: float = 30.0  # %

# Minimum TVL to be included
MIN_ELIGIBLE_TVL: float = 5_000_000.0  # $5 M

# Minimum cash buffer (residual unallocated weight)
MIN_CASH_BUFFER: float = 0.05  # 5%

# ─── Helpers ──────────────────────────────────────────────────────────────────

def _safe_float(value: Any, default: float = 0.0) -> float:
    """Convert *value* to float; return *default* on failure."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalise_weights(weights: Dict[str, float]) -> Dict[str, float]:
    """Proportionally rescale weights so they sum to at most 1.0.

    If the total is 0 the dict is returned unchanged (all zeros).
    """
    total = sum(weights.values())
    if total <= 0.0:
        return dict(weights)
    return {k: v / total for k, v in weights.items()}


def _clamp(value: float, lo: float, hi: float) -> float:
    """Clamp *value* to [lo, hi]."""
    return max(lo, min(hi, value))


# ─── PositionSizer ────────────────────────────────────────────────────────────

class PositionSizer:
    """Deterministic position sizing engine.

    All cap values are expressed as **fractions** in [0, 1] (e.g. 0.40 = 40 %).

    Parameters
    ----------
    tier_caps_per_protocol:
        ``{tier: cap_fraction}`` overrides for per-protocol caps.
        Defaults: T1=0.60, T2=0.25, T3=0.10.
    tier_caps_total:
        ``{tier: cap_fraction}`` overrides for aggregate tier caps.
        Defaults: T1=0.60, T2=0.50, T3=0.15.
    min_cash_buffer:
        Minimum unallocated fraction (cash buffer).  Default: 0.05.
    """

    def __init__(
        self,
        tier_caps_per_protocol: Optional[Dict[str, float]] = None,
        tier_caps_total: Optional[Dict[str, float]] = None,
        min_cash_buffer: float = MIN_CASH_BUFFER,
    ) -> None:
        self._per_proto_caps: Dict[str, float] = {
            "T1": TIER_CAP_T1_PER_PROTOCOL,
            "T2": TIER_CAP_T2_PER_PROTOCOL,
            "T3": TIER_CAP_T3_PER_PROTOCOL,
        }
        if tier_caps_per_protocol:
            self._per_proto_caps.update(tier_caps_per_protocol)

        self._total_caps: Dict[str, float] = {
            "T1": TIER_CAP_T1_TOTAL,
            "T2": TIER_CAP_T2_TOTAL,
            "T3": TIER_CAP_T3_TOTAL,
        }
        if tier_caps_total:
            self._total_caps.update(tier_caps_total)

        self._min_cash_buffer = float(min_cash_buffer)

    # ──────────────────────────────────────────────────────────────────────────
    # Core public API
    # ──────────────────────────────────────────────────────────────────────────

    def compute_target_weights(
        self,
        adapters: Dict[str, Dict[str, Any]],
        portfolio_value: float,
        risk_limits: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, float]:
        """Compute raw target weights proportional to eligible APY.

        Adapters that fail eligibility (APY out of range, TVL below floor,
        or explicitly excluded via risk_limits) receive a weight of 0.

        The resulting weights are **normalised** so they sum to at most
        ``1 - min_cash_buffer``.  If no adapters are eligible all weights
        are 0 (the entire portfolio sits in cash).

        Parameters
        ----------
        adapters:
            ``{adapter_id: {apy: float_pct, tvl: float_usd, …}}``
        portfolio_value:
            Total portfolio value in USD.
        risk_limits:
            Optional overrides (keys: ``max_single``, ``min_cash_buffer``,
            ``min_apy``, ``max_apy``, ``min_tvl``, ``excluded``).

        Returns
        -------
        dict[str, float]
            ``{adapter_id: weight}`` — fractions in [0, 1], sum ≤ 1.
        """
        rl = risk_limits or {}
        min_apy   = _safe_float(rl.get("min_apy"),   MIN_ELIGIBLE_APY)
        max_apy   = _safe_float(rl.get("max_apy"),   MAX_ELIGIBLE_APY)
        min_tvl   = _safe_float(rl.get("min_tvl"),   MIN_ELIGIBLE_TVL)
        max_single = _safe_float(rl.get("max_single"), DEFAULT_MAX_SINGLE)
        cash_buf  = _safe_float(rl.get("min_cash_buffer"), self._min_cash_buffer)
        excluded  = set(rl.get("excluded") or [])

        max_investable = max(0.0, 1.0 - cash_buf)

        # Score each adapter by its APY (only eligible ones get a positive score)
        scores: Dict[str, float] = {}
        for adapter_id, info in adapters.items():
            if adapter_id in excluded:
                scores[adapter_id] = 0.0
                continue
            apy = _safe_float(info.get("apy"), 0.0)
            tvl = _safe_float(info.get("tvl"), 0.0)
            if apy < min_apy or apy > max_apy:
                scores[adapter_id] = 0.0
                continue
            if tvl < min_tvl:
                scores[adapter_id] = 0.0
                continue
            scores[adapter_id] = apy  # weight ∝ APY (greedy yield maximiser)

        total_score = sum(scores.values())
        if total_score <= 0.0:
            return {aid: 0.0 for aid in adapters}

        # Proportional weights, capped at max_single, then rescaled to max_investable
        raw: Dict[str, float] = {
            k: (v / total_score) * max_investable for k, v in scores.items()
        }
        # Apply per-adapter concentration limit
        raw = self.apply_concentration_limit(raw, max_single=max_single)
        # Renormalise after capping
        capped_total = sum(raw.values())
        if capped_total > 0.0:
            scale = min(max_investable, capped_total) / capped_total
            raw = {k: round(v * scale, 8) for k, v in raw.items()}

        return raw

    def compute_dollar_allocations(
        self,
        weights: Dict[str, float],
        portfolio_value: float,
    ) -> Dict[str, float]:
        """Convert weights to dollar amounts.

        Parameters
        ----------
        weights:
            ``{adapter_id: weight_fraction}`` in [0, 1].
        portfolio_value:
            Total portfolio value in USD.

        Returns
        -------
        dict[str, float]
            ``{adapter_id: dollar_amount}``
        """
        pv = float(portfolio_value)
        return {k: round(v * pv, 6) for k, v in weights.items()}

    def apply_tier_caps(
        self,
        weights: Dict[str, float],
        adapter_tiers: Dict[str, str],
    ) -> Dict[str, float]:
        """Apply per-protocol tier caps and aggregate tier caps.

        Per-protocol caps
        -----------------
        * T1: 60 %   T2: 25 %   T3: 10 %

        Aggregate caps (applied after per-protocol clamp, iteratively)
        ---------------------------------------------------------------
        * All T1 combined ≤ 60 %
        * All T2 combined ≤ 50 %
        * All T3 combined ≤ 15 %

        Any adapter whose tier is not in T1/T2/T3 is treated as T1 for
        per-protocol capping purposes.

        The result is NOT renormalised — excess weight is simply clipped
        (it will become implicit cash buffer).  Caller is responsible for
        re-normalising if needed.

        Parameters
        ----------
        weights:
            ``{adapter_id: weight_fraction}`` — will not be mutated.
        adapter_tiers:
            ``{adapter_id: tier_string}`` — e.g. ``{"aave_v3": "T1"}``.
            Adapters not in this dict are treated as T1.

        Returns
        -------
        dict[str, float]
            Tier-capped weights (same keys as input).
        """
        result = dict(weights)

        # Step 1: per-protocol cap
        for aid, w in result.items():
            tier = adapter_tiers.get(aid, "T1")
            cap = self._per_proto_caps.get(tier, TIER_CAP_T1_PER_PROTOCOL)
            result[aid] = min(w, cap)

        # Step 2: aggregate tier cap — iterate tiers, pro-rata trim if over
        for tier, total_cap in self._total_caps.items():
            tier_ids = [k for k, v in result.items()
                        if adapter_tiers.get(k, "T1") == tier and v > 0.0]
            if not tier_ids:
                continue
            tier_total = sum(result[k] for k in tier_ids)
            if tier_total > total_cap + 1e-9:
                # Pro-rata reduction
                scale = total_cap / tier_total
                for k in tier_ids:
                    result[k] = round(result[k] * scale, 8)

        return result

    def apply_concentration_limit(
        self,
        weights: Dict[str, float],
        max_single: float = DEFAULT_MAX_SINGLE,
    ) -> Dict[str, float]:
        """Clamp every adapter weight to ``max_single``.

        Excess weight is clipped (not redistributed).  The result may sum
        to less than the input total.

        Parameters
        ----------
        weights:
            ``{adapter_id: weight_fraction}`` — will not be mutated.
        max_single:
            Maximum weight for any single adapter.  Default: 0.40.

        Returns
        -------
        dict[str, float]
            Concentration-limited weights (same keys as input).
        """
        cap = float(max_single)
        return {k: round(min(v, cap), 8) for k, v in weights.items()}

    def get_sizing_report(
        self,
        adapters: Dict[str, Dict[str, Any]],
        portfolio_value: float,
        risk_limits: Optional[Dict[str, Any]] = None,
        adapter_tiers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Produce a comprehensive position sizing report.

        Applies the full pipeline:
        1. compute_target_weights
        2. apply_tier_caps  (if adapter_tiers provided)
        3. apply_concentration_limit
        4. compute_dollar_allocations

        Parameters
        ----------
        adapters:
            ``{adapter_id: {apy, tvl, …}}``
        portfolio_value:
            Total portfolio value in USD.
        risk_limits:
            Optional risk limit overrides (see compute_target_weights).
        adapter_tiers:
            ``{adapter_id: tier}`` — if omitted, tier caps are skipped.

        Returns
        -------
        dict with keys:
            ``generated_at``, ``portfolio_value``, ``weights_raw``,
            ``weights_after_tier_caps``, ``weights_final``,
            ``dollar_allocations``, ``cash_buffer_usd``, ``cash_buffer_pct``,
            ``adapter_count``, ``eligible_count``, ``tier_summary``,
            ``risk_limits_applied``, ``warnings``.
        """
        rl = risk_limits or {}
        tiers = adapter_tiers or {}
        pv = float(portfolio_value)
        warnings: List[str] = []

        # Step 1: raw weights (APY-proportional, eligibility filtered)
        weights_raw = self.compute_target_weights(adapters, pv, rl)

        # Step 2: tier caps
        if tiers:
            weights_tier = self.apply_tier_caps(weights_raw, tiers)
        else:
            weights_tier = dict(weights_raw)

        # Step 3: concentration limit
        max_single = _safe_float(rl.get("max_single"), DEFAULT_MAX_SINGLE)
        weights_final = self.apply_concentration_limit(weights_tier, max_single)

        # Step 4: dollar allocations
        dollar_allocations = self.compute_dollar_allocations(weights_final, pv)

        # Derived stats
        allocated_total = sum(weights_final.values())
        cash_buffer_pct = max(0.0, 1.0 - allocated_total)
        cash_buffer_usd = round(cash_buffer_pct * pv, 6)

        eligible_count = sum(
            1 for aid, w in weights_raw.items() if w > 0.0
        )

        # Tier summary
        tier_summary: Dict[str, Dict[str, Any]] = {}
        for tier in ("T1", "T2", "T3"):
            tier_ids = [k for k in weights_final if tiers.get(k, "T1") == tier]
            total_w  = sum(weights_final[k] for k in tier_ids)
            tier_summary[tier] = {
                "adapter_count": len(tier_ids),
                "total_weight":  round(total_w, 8),
                "total_usd":     round(total_w * pv, 6),
            }

        # Warnings
        if cash_buffer_pct < 0.05 - 1e-9:
            warnings.append(
                f"Cash buffer {cash_buffer_pct:.2%} < 5% minimum — check risk limits."
            )
        if eligible_count == 0:
            warnings.append(
                "No adapters passed eligibility filters — portfolio is 100% cash."
            )
        for aid, w in weights_final.items():
            if w > max_single + 1e-9:
                warnings.append(
                    f"Adapter {aid!r} weight {w:.4f} exceeds max_single={max_single:.4f}."
                )

        report: Dict[str, Any] = {
            "generated_at":       datetime.now(timezone.utc).isoformat(),
            "portfolio_value":    round(pv, 6),
            "weights_raw":        {k: round(v, 8) for k, v in weights_raw.items()},
            "weights_after_tier_caps": {k: round(v, 8) for k, v in weights_tier.items()},
            "weights_final":      {k: round(v, 8) for k, v in weights_final.items()},
            "dollar_allocations": dollar_allocations,
            "cash_buffer_usd":    cash_buffer_usd,
            "cash_buffer_pct":    round(cash_buffer_pct, 8),
            "adapter_count":      len(adapters),
            "eligible_count":     eligible_count,
            "tier_summary":       tier_summary,
            "risk_limits_applied": {
                "max_single":      max_single,
                "min_cash_buffer": _safe_float(rl.get("min_cash_buffer"), self._min_cash_buffer),
                "min_apy":         _safe_float(rl.get("min_apy"), MIN_ELIGIBLE_APY),
                "max_apy":         _safe_float(rl.get("max_apy"), MAX_ELIGIBLE_APY),
                "min_tvl":         _safe_float(rl.get("min_tvl"), MIN_ELIGIBLE_TVL),
            },
            "warnings": warnings,
        }
        return report

    # ──────────────────────────────────────────────────────────────────────────
    # Persistence
    # ──────────────────────────────────────────────────────────────────────────

    def save_report(
        self,
        report: Dict[str, Any],
        data_dir: str = _DEFAULT_DATA_DIR,
    ) -> None:
        """Atomically persist *report* to ``data/position_sizing_report.json``.

        The file is created if it does not exist.  Entries are stored in a
        ring-buffer of :data:`REPORT_HISTORY_MAX` records.

        Parameters
        ----------
        report:
            Dict produced by :meth:`get_sizing_report`.
        data_dir:
            Target directory.  Defaults to repo ``data/``.
        """
        data_path = Path(data_dir)
        data_path.mkdir(parents=True, exist_ok=True)
        target = data_path / REPORT_FILENAME

        history: List[Dict[str, Any]] = []
        if target.exists():
            try:
                raw = json.loads(target.read_text(encoding="utf-8"))
                if isinstance(raw, list):
                    history = raw
            except (json.JSONDecodeError, OSError) as exc:
                log.warning("position_sizing_report.json unreadable — starting fresh: %s", exc)

        history.append(report)
        if len(history) > REPORT_HISTORY_MAX:
            history = history[-REPORT_HISTORY_MAX:]

        atomic_save(history, str(target))
# ─── CLI entry-point ──────────────────────────────────────────────────────────

def _main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="SPA PositionSizer — compute and optionally record sizing report."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        default=False,
        help="Compute and print results without writing to disk (default behaviour).",
    )
    parser.add_argument(
        "--run",
        action="store_true",
        default=False,
        help="Compute and atomically write to data/position_sizing_report.json.",
    )
    parser.add_argument(
        "--data-dir",
        default=_DEFAULT_DATA_DIR,
        help="Data directory for position_sizing_report.json.",
    )
    args = parser.parse_args(argv)

    # If neither flag is set, default to --check
    if not args.run:
        args.check = True

    sizer = PositionSizer()

    # Illustrative adapters for self-test
    adapters: Dict[str, Dict[str, Any]] = {
        "aave_v3":         {"apy": 3.5,  "tvl": 9_000_000_000},
        "compound_v3":     {"apy": 4.8,  "tvl": 2_000_000_000},
        "morpho_steakhouse": {"apy": 6.5, "tvl": 800_000_000},
        "yearn_v3":        {"apy": 5.2,  "tvl": 300_000_000},
        "euler_v2":        {"apy": 4.1,  "tvl": 150_000_000},
    }
    adapter_tiers: Dict[str, str] = {
        "aave_v3":           "T1",
        "compound_v3":       "T1",
        "morpho_steakhouse": "T1",
        "yearn_v3":          "T2",
        "euler_v2":          "T2",
    }
    portfolio_value: float = 100_000.0
    risk_limits: Dict[str, Any] = {
        "max_single":       0.40,
        "min_cash_buffer":  0.05,
        "min_apy":          1.0,
        "max_apy":          30.0,
        "min_tvl":          5_000_000.0,
    }

    report = sizer.get_sizing_report(
        adapters, portfolio_value, risk_limits, adapter_tiers
    )

    print(f"Portfolio value:   ${report['portfolio_value']:,.2f}")
    print(f"Eligible adapters: {report['eligible_count']}/{report['adapter_count']}")
    print(f"Cash buffer:       {report['cash_buffer_pct']:.2%}  (${report['cash_buffer_usd']:,.2f})")
    print()
    print("Final weights & allocations:")
    for aid, w in sorted(report["weights_final"].items(), key=lambda x: -x[1]):
        usd = report["dollar_allocations"][aid]
        tier = adapter_tiers.get(aid, "??")
        print(f"  [{tier}] {aid:25s}  {w:6.2%}  ${usd:>12,.2f}")
    print()
    print("Tier summary:")
    for tier, info in report["tier_summary"].items():
        print(f"  {tier}: {info['adapter_count']} adapters, "
              f"{info['total_weight']:.2%} (${info['total_usd']:,.2f})")
    if report["warnings"]:
        print("\nWarnings:")
        for w in report["warnings"]:
            print(f"  ⚠  {w}")

    if args.run:
        sizer.save_report(report, data_dir=args.data_dir)
        print(f"\nReport saved → {args.data_dir}/{REPORT_FILENAME}")

    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sys.exit(_main())
