#!/usr/bin/env python3
"""Yield optimization engine for SPA portfolio (MP-579).

Optimizes allocation weights to maximise risk-adjusted yield across adapters,
using an iterative projected-gradient algorithm (stdlib + math only — no
scipy / numpy).

Key classes
===========
* ``OptimizationResult`` — dataclass: weights, expected_apy, risk_score,
  tier_breakdown, warnings.
* ``YieldOptimizer`` — main engine:
  - ``optimize()``               — max-yield allocation (risk_aversion = 0).
  - ``compute_efficient_frontier()`` — Pareto frontier over risk/return.
  - ``get_sharpe_optimal()``     — frontier point maximising Sharpe ratio.
  - ``apply_constraints()``      — project weights onto the feasible set.
  - ``save_result()``            — atomic ring-buffer persistence.

Algorithm
=========
Score for each adapter: ``score_i = APY_i − λ × risk_i × RISK_SCALE``
(λ = risk_aversion; λ = 0 → pure yield; λ → ∞ → min-risk).

Iteration:
  1. Build proportional initial weights from positive scores.
  2. Project onto feasible set via ``apply_constraints``.
  3. Redistribute remaining budget (headroom) to active adapters ∝ score.
  4. Repeat until Δweight < CONVERGENCE_EPS or max_iter reached.

Efficient frontier
==================
``compute_efficient_frontier()`` sweeps λ ∈ [0, 5] over *n_points*
log-spaced values, producing one ``OptimizationResult`` per point.

Sharpe-optimal
==============
``get_sharpe_optimal()`` evaluates a dense frontier and returns the point
with maximum (portfolio_APY/100 − risk_free_rate) / risk_score.

Design rules
============
* **Stdlib + math only** — no external deps (no requests, web3, LLM SDK).
* **Atomic writes** — tmp file + os.replace on every JSON update.
* **LLM-FORBIDDEN** — pure deterministic arithmetic; no AI/LLM calls.
* **Read-only wrt capital** — does NOT import execution/, does NOT touch
  trades.json, current_positions.json, or any capital-state file.

Usage example
=============
::

    from spa_core.paper_trading.yield_optimizer import YieldOptimizer

    opt = YieldOptimizer()
    adapters = {
        "aave_v3":   {"apy": 3.5, "tvl": 9e9, "risk_score": 0.20, "tier": "T1"},
        "yearn_v3":  {"apy": 5.2, "tvl": 3e8, "risk_score": 0.40, "tier": "T2"},
    }
    result  = opt.optimize(adapters, 100_000.0, {"max_risk": 0.6})
    frontier = opt.compute_efficient_frontier(adapters, 100_000.0, n_points=10)
    best    = opt.get_sharpe_optimal(adapters, 100_000.0, risk_free_rate=0.04)

CLI (offline, exit 0 always)::

    python3 -m spa_core.paper_trading.yield_optimizer --check
    python3 -m spa_core.paper_trading.yield_optimizer --run
    python3 -m spa_core.paper_trading.yield_optimizer --run --data-dir data
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from spa_core.utils.atomic import atomic_save

log = logging.getLogger("spa.paper_trading.yield_optimizer")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = str(_REPO_ROOT / "data")

RESULTS_FILENAME = "yield_optimizer_results.json"
RESULTS_HISTORY_MAX = 365  # ring-buffer cap

# ── Tier caps (per-protocol) ──────────────────────────────────────────────────
T1_CAP_PER_PROTOCOL: float = 0.40   # RiskPolicy v1.0: T1 ≤ 40 % per adapter
T2_CAP_PER_PROTOCOL: float = 0.20   # T2 ≤ 20 % per adapter
T3_CAP_PER_PROTOCOL: float = 0.10   # T3 ≤ 10 % per adapter

# ── Aggregate tier caps ───────────────────────────────────────────────────────
T2_CAP_TOTAL: float = 0.50          # ADR-019: all T2 combined ≤ 50 %
T3_CAP_TOTAL: float = 0.15          # ADR-020: all T3 combined ≤ 15 %

# ── Allocation limits ─────────────────────────────────────────────────────────
MIN_ALLOCATION: float = 0.02        # minimum non-zero weight (snapped to 0 if below)
MAX_SINGLE: float = 0.40            # absolute per-adapter cap (any tier)
MIN_CASH_BUFFER: float = 0.05       # minimum unallocated fraction

# ── Eligibility filters ───────────────────────────────────────────────────────
MIN_ELIGIBLE_APY: float = 1.0       # % — individual adapter APY floor
MAX_ELIGIBLE_APY: float = 30.0      # % — individual adapter APY ceiling
MIN_ELIGIBLE_TVL: float = 5_000_000.0  # $5 M TVL floor

# ── Optimizer parameters ──────────────────────────────────────────────────────
MAX_ITER: int = 200                 # maximum convergence iterations
CONVERGENCE_EPS: float = 1e-8      # delta-weight threshold for convergence
RISK_SCALE: float = 10.0           # risk_score → APY-equivalent scale factor
LAMBDA_MAX: float = 5.0            # upper bound for risk-aversion sweep


# ── Module-level helpers ──────────────────────────────────────────────────────

def _safe_float(value: Any, default: float = 0.0) -> float:
    """Convert *value* to float; return *default* on any failure."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, lo: float, hi: float) -> float:
    """Clamp *value* to [lo, hi]."""
    return max(lo, min(hi, value))


def _get_tier(adapters: Dict[str, Dict[str, Any]], adapter_id: str) -> str:
    """Return tier string for *adapter_id*; defaults to ``'T1'`` when absent."""
    if adapter_id not in adapters:
        return "T1"
    return str(adapters[adapter_id].get("tier", "T1"))


# ── OptimizationResult ────────────────────────────────────────────────────────

@dataclass
class OptimizationResult:
    """Result of one yield-optimizer run.

    Attributes
    ----------
    weights:
        ``{adapter_id: weight_fraction}`` — values in [0, 1], sum ≤ 1.
    expected_apy:
        Portfolio weighted-average APY in percent (e.g. ``5.0`` = 5 %).
    risk_score:
        Composite risk in [0, 1]: 0 = lowest risk, 1 = highest.
        Composed of 70 % weighted protocol risk + 30 % HHI concentration.
    tier_breakdown:
        ``{tier: aggregate_weight}`` — keys always present: T1, T2, T3, cash.
    warnings:
        Advisory messages (constraint violations, fallback situations, etc.).
    """

    weights: Dict[str, float]
    expected_apy: float
    risk_score: float
    tier_breakdown: Dict[str, float]
    warnings: List[str]

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a plain JSON-safe dict."""
        return {
            "weights": dict(self.weights),
            "expected_apy": self.expected_apy,
            "risk_score": self.risk_score,
            "tier_breakdown": dict(self.tier_breakdown),
            "warnings": list(self.warnings),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "OptimizationResult":
        """Deserialise from a plain dict (inverse of :meth:`to_dict`)."""
        return cls(
            weights=dict(d.get("weights") or {}),
            expected_apy=_safe_float(d.get("expected_apy"), 0.0),
            risk_score=_safe_float(d.get("risk_score"), 0.0),
            tier_breakdown=dict(d.get("tier_breakdown") or {}),
            warnings=list(d.get("warnings") or []),
        )


# ── YieldOptimizer ────────────────────────────────────────────────────────────

class YieldOptimizer:
    """Iterative yield-optimization engine.

    Uses a score-reweighting / projected-gradient inner loop with convergence
    detection.  Pure stdlib + math; no external numeric libraries.

    Parameters
    ----------
    min_cash_buffer:
        Minimum unallocated portfolio fraction.  Default: ``0.05`` (5 %).
    max_iter:
        Maximum iterations for the convergence loop.  Default: ``200``.
    """

    def __init__(
        self,
        min_cash_buffer: float = MIN_CASH_BUFFER,
        max_iter: int = MAX_ITER,
    ) -> None:
        self._min_cash_buffer = float(min_cash_buffer)
        self._max_iter = int(max_iter)

    # ── Core public API ────────────────────────────────────────────────────────

    def optimize(
        self,
        adapters: Dict[str, Dict[str, Any]],
        portfolio_value: float,
        constraints: Optional[Dict[str, Any]] = None,
    ) -> OptimizationResult:
        """Maximise yield subject to structural constraints (risk_aversion = 0).

        Parameters
        ----------
        adapters:
            ``{adapter_id: {apy, tvl, risk_score, tier, …}}``
            *apy* in percent; *tvl* in USD; *risk_score* in [0, 1]; *tier* one
            of ``"T1"``, ``"T2"``, ``"T3"``.
        portfolio_value:
            Total portfolio value in USD.  Used for reporting only — weights
            are fractions, not dollar amounts.
        constraints:
            Optional dict with any of:

            - ``max_risk`` *(float)*:            per-adapter risk_score ceiling.
            - ``min_apy``  *(float)*:            desired portfolio APY floor (%; advisory).
            - ``max_t2_pct`` *(float)*:          T2 aggregate weight cap (default 0.50).
            - ``excluded_adapters`` *(list)*:    adapter IDs to zero out.

        Returns
        -------
        OptimizationResult
        """
        return self._optimize_with_lambda(
            adapters, float(portfolio_value), constraints or {}, risk_aversion=0.0
        )

    def compute_efficient_frontier(
        self,
        adapters: Dict[str, Dict[str, Any]],
        portfolio_value: float,
        n_points: int = 20,
        constraints: Optional[Dict[str, Any]] = None,
    ) -> List[OptimizationResult]:
        """Compute the risk/return efficient frontier.

        Sweeps the risk-aversion parameter λ from 0 (maximum yield) to
        ``LAMBDA_MAX`` (minimum risk) over *n_points* log-spaced values.
        The first point always corresponds to λ = 0 (pure yield optimisation).

        Parameters
        ----------
        adapters:
            Same schema as :meth:`optimize`.
        portfolio_value:
            Total portfolio value in USD.
        n_points:
            Number of frontier samples.  Default: 20.
        constraints:
            Same as :meth:`optimize`.

        Returns
        -------
        list[OptimizationResult]  of length *n_points*.
        """
        cns = constraints or {}
        n = max(1, int(n_points))

        # Build λ sequence: 0 (pure yield) followed by log-spaced [0.001, 5.0]
        if n == 1:
            lambdas: List[float] = [0.0]
        elif n == 2:
            lambdas = [0.0, LAMBDA_MAX]
        else:
            log_lo = math.log(0.001)
            log_hi = math.log(LAMBDA_MAX)
            lambdas = [0.0] + [
                math.exp(log_lo + (i / (n - 2)) * (log_hi - log_lo))
                for i in range(n - 1)
            ]

        return [
            self._optimize_with_lambda(adapters, float(portfolio_value), cns, lam)
            for lam in lambdas
        ]

    def get_sharpe_optimal(
        self,
        adapters: Dict[str, Dict[str, Any]],
        portfolio_value: float,
        risk_free_rate: float = 0.04,
        constraints: Optional[Dict[str, Any]] = None,
    ) -> OptimizationResult:
        """Return the efficient-frontier point with the highest Sharpe ratio.

        Sharpe = (portfolio_APY / 100 − risk_free_rate) / risk_score

        A dense frontier of 50 points is computed internally; the point with
        the maximum Sharpe ratio is returned.

        Parameters
        ----------
        adapters:
            Same schema as :meth:`optimize`.
        portfolio_value:
            Total portfolio value in USD.
        risk_free_rate:
            Annualised risk-free rate in decimal (e.g. ``0.04`` = 4 %).
        constraints:
            Same as :meth:`optimize`.

        Returns
        -------
        OptimizationResult with maximum Sharpe ratio.
        """
        cns = constraints or {}
        frontier = self.compute_efficient_frontier(
            adapters, float(portfolio_value), n_points=50, constraints=cns
        )

        best: Optional[OptimizationResult] = None
        best_sharpe = -math.inf

        for pt in frontier:
            if pt.risk_score < 1e-9:
                # Zero-risk → effectively infinite Sharpe; return immediately.
                return pt
            apy_dec = pt.expected_apy / 100.0
            sharpe = (apy_dec - float(risk_free_rate)) / pt.risk_score
            if sharpe > best_sharpe:
                best_sharpe = sharpe
                best = pt

        # Fallback if frontier is empty (edge case: no eligible adapters)
        if best is None:
            best = self._optimize_with_lambda(adapters, float(portfolio_value), cns, 0.0)

        return best

    def apply_constraints(
        self,
        weights: Dict[str, float],
        adapters: Dict[str, Dict[str, Any]],
        constraints: Dict[str, Any],
    ) -> Dict[str, float]:
        """Project *weights* onto the feasible constraint set.

        Applies, in order:

        1. **Zero out excluded adapters** (``excluded_adapters`` key).
        2. **Per-protocol tier caps**: T1 ≤ ``max_single`` (default 0.40);
           T2 ≤ min(max_single, 0.20); T3 ≤ min(max_single, 0.10).
        3. **T2 aggregate cap** (``max_t2_pct``, default 0.50; ADR-019) —
           pro-rata trim when total T2 exceeds the cap.
        4. **T3 aggregate cap** (0.15; ADR-020) — pro-rata trim.
        5. **min_allocation = 0.02**: weights in (0, 0.02) are snapped to 0.
        6. **Cash buffer**: total weight clamped to ``1 − min_cash_buffer``.

        Parameters
        ----------
        weights:
            ``{adapter_id: weight_fraction}`` — input; not mutated.
        adapters:
            ``{adapter_id: {tier, …}}`` — used for tier lookup.
        constraints:
            Dict with optional keys ``excluded_adapters``, ``max_t2_pct``,
            ``max_single``.

        Returns
        -------
        dict[str, float]  — constrained weights (same keys as *weights*).
        """
        result: Dict[str, float] = {k: _safe_float(v, 0.0) for k, v in weights.items()}

        excluded = set(constraints.get("excluded_adapters") or [])
        max_t2_pct = _safe_float(constraints.get("max_t2_pct"), T2_CAP_TOTAL)
        max_single = _safe_float(constraints.get("max_single"), MAX_SINGLE)

        # Step 1: zero excluded adapters
        for aid in excluded:
            if aid in result:
                result[aid] = 0.0

        # Step 2: per-protocol tier caps
        for aid in result:
            w = result[aid]
            if w <= 0.0:
                continue
            tier = _get_tier(adapters, aid)
            if tier == "T2":
                proto_cap = min(max_single, T2_CAP_PER_PROTOCOL)
            elif tier == "T3":
                proto_cap = min(max_single, T3_CAP_PER_PROTOCOL)
            else:  # T1 or unknown
                proto_cap = max_single
            result[aid] = min(w, proto_cap)

        # Step 3: T2 aggregate cap — pro-rata trim
        t2_ids = [k for k in result if _get_tier(adapters, k) == "T2" and result[k] > 0.0]
        t2_total = sum(result[k] for k in t2_ids)
        if t2_total > max_t2_pct + 1e-9:
            scale = max_t2_pct / t2_total
            for k in t2_ids:
                result[k] = round(result[k] * scale, 8)

        # Step 4: T3 aggregate cap — pro-rata trim
        t3_ids = [k for k in result if _get_tier(adapters, k) == "T3" and result[k] > 0.0]
        t3_total = sum(result[k] for k in t3_ids)
        if t3_total > T3_CAP_TOTAL + 1e-9:
            scale = T3_CAP_TOTAL / t3_total
            for k in t3_ids:
                result[k] = round(result[k] * scale, 8)

        # Step 5: min_allocation enforcement (snap tiny positions to zero)
        for aid in list(result.keys()):
            if 0.0 < result[aid] < MIN_ALLOCATION:
                result[aid] = 0.0

        # Step 6: enforce cash buffer ceiling
        total = sum(result.values())
        max_investable = 1.0 - self._min_cash_buffer
        if total > max_investable + 1e-9:
            scale = max_investable / total
            result = {k: round(v * scale, 8) for k, v in result.items()}

        return result

    # ── Persistence ────────────────────────────────────────────────────────────

    def save_result(
        self,
        result: OptimizationResult,
        data_dir: str = _DEFAULT_DATA_DIR,
        label: Optional[str] = None,
    ) -> None:
        """Atomically persist *result* to ``data/yield_optimizer_results.json``.

        Ring-buffer of :data:`RESULTS_HISTORY_MAX` entries (oldest pruned).

        Parameters
        ----------
        result:
            The :class:`OptimizationResult` to persist.
        data_dir:
            Target directory.  Defaults to repo ``data/``.
        label:
            Optional human-readable tag stored alongside the result.
        """
        data_path = Path(data_dir)
        data_path.mkdir(parents=True, exist_ok=True)
        target = data_path / RESULTS_FILENAME

        history: List[Dict[str, Any]] = []
        if target.exists():
            try:
                raw = json.loads(target.read_text(encoding="utf-8"))
                if isinstance(raw, list):
                    history = raw
            except (json.JSONDecodeError, OSError) as exc:
                log.warning(
                    "yield_optimizer_results.json unreadable — starting fresh: %s", exc
                )

        entry: Dict[str, Any] = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "label": label or "optimize",
        }
        entry.update(result.to_dict())
        history.append(entry)
        if len(history) > RESULTS_HISTORY_MAX:
            history = history[-RESULTS_HISTORY_MAX:]

        atomic_save(history, str(target))
    # ── Private helpers ────────────────────────────────────────────────────────

    def _optimize_with_lambda(
        self,
        adapters: Dict[str, Dict[str, Any]],
        portfolio_value: float,
        constraints: Dict[str, Any],
        risk_aversion: float,
    ) -> OptimizationResult:
        """Core solver: maximise Σ w_i × (APY_i − λ × risk_i × RISK_SCALE)."""
        warnings_out: List[str] = []
        excluded = set(constraints.get("excluded_adapters") or [])
        max_risk = _safe_float(constraints.get("max_risk"), 1.0)

        # ── Eligibility pass ──────────────────────────────────────────────────
        eligible_scores: Dict[str, float] = {}
        for aid, info in adapters.items():
            if aid in excluded:
                continue
            apy = _safe_float(info.get("apy"), 0.0)
            tvl = _safe_float(info.get("tvl"), 0.0)
            risk = _clamp(_safe_float(info.get("risk_score"), 0.5), 0.0, 1.0)

            if apy < MIN_ELIGIBLE_APY or apy > MAX_ELIGIBLE_APY:
                continue
            if tvl < MIN_ELIGIBLE_TVL:
                continue
            if risk > max_risk + 1e-9:
                continue

            score = apy - risk_aversion * risk * RISK_SCALE
            if score > 0.0:
                eligible_scores[aid] = score

        # ── No eligible adapters ──────────────────────────────────────────────
        if not eligible_scores:
            warnings_out.append("No eligible adapters after applying constraints.")
            all_zero: Dict[str, float] = {aid: 0.0 for aid in adapters}
            return OptimizationResult(
                weights=all_zero,
                expected_apy=0.0,
                risk_score=0.0,
                tier_breakdown={"T1": 0.0, "T2": 0.0, "T3": 0.0, "cash": 1.0},
                warnings=warnings_out,
            )

        # ── Initial weights ∝ score ───────────────────────────────────────────
        total_score = sum(eligible_scores.values())
        max_investable = 1.0 - self._min_cash_buffer
        weights: Dict[str, float] = {
            aid: (s / total_score) * max_investable
            for aid, s in eligible_scores.items()
        }
        for aid in adapters:
            if aid not in weights:
                weights[aid] = 0.0

        # ── Iterative projection loop ─────────────────────────────────────────
        prev: Optional[Dict[str, float]] = None
        for _ in range(self._max_iter):
            constrained = self.apply_constraints(weights, adapters, constraints)

            # Convergence check
            if prev is not None:
                delta = max(
                    abs(constrained.get(k, 0.0) - prev.get(k, 0.0))
                    for k in set(constrained) | set(prev)
                )
                if delta < CONVERGENCE_EPS:
                    weights = constrained
                    break

            prev = constrained

            # Redistribute headroom to active eligible adapters
            active_scores = {
                k: eligible_scores[k]
                for k in constrained
                if constrained[k] > 0.0 and k in eligible_scores
            }
            if not active_scores:
                weights = constrained
                break

            active_total = sum(active_scores.values())
            allocated = sum(constrained.values())
            headroom = max_investable - allocated

            if headroom > 1e-9:
                new_weights = dict(constrained)
                for k, s in active_scores.items():
                    new_weights[k] = constrained[k] + (s / active_total) * headroom
                weights = new_weights
            else:
                weights = constrained
                break
        else:
            # Max iterations reached — apply constraints one final time
            weights = self.apply_constraints(weights, adapters, constraints)

        # ── Compute result metrics ────────────────────────────────────────────
        expected_apy = self._compute_expected_apy(weights, adapters)
        risk_score = self._compute_risk_score(weights, adapters)
        tier_breakdown = self._compute_tier_breakdown(weights, adapters)

        # Advisory: warn if portfolio APY falls below min_apy constraint
        min_apy_req = _safe_float(constraints.get("min_apy"), 0.0)
        if min_apy_req > MIN_ELIGIBLE_APY and expected_apy < min_apy_req - 1e-9:
            warnings_out.append(
                f"Portfolio APY {expected_apy:.4f}% is below "
                f"min_apy constraint {min_apy_req:.4f}%."
            )

        return OptimizationResult(
            weights={k: round(v, 8) for k, v in weights.items()},
            expected_apy=round(expected_apy, 6),
            risk_score=round(risk_score, 6),
            tier_breakdown={k: round(v, 8) for k, v in tier_breakdown.items()},
            warnings=warnings_out,
        )

    def _compute_expected_apy(
        self,
        weights: Dict[str, float],
        adapters: Dict[str, Dict[str, Any]],
    ) -> float:
        """Weighted-average APY (%) across active positions."""
        total = 0.0
        for aid, w in weights.items():
            if w <= 0.0 or aid not in adapters:
                continue
            total += w * _safe_float(adapters[aid].get("apy"), 0.0)
        return total

    def _compute_risk_score(
        self,
        weights: Dict[str, float],
        adapters: Dict[str, Dict[str, Any]],
    ) -> float:
        """Composite risk in [0, 1].

        70 % weighted-average protocol risk_score (over invested fraction).
        30 % HHI concentration of invested weights.
        """
        invested = sum(v for v in weights.values() if v > 0.0)
        if invested < 1e-9:
            return 0.0  # all-cash → zero protocol risk

        weighted_risk = sum(
            w * _clamp(_safe_float(adapters.get(aid, {}).get("risk_score"), 0.5), 0.0, 1.0)
            for aid, w in weights.items()
            if w > 0.0
        )
        avg_risk = weighted_risk / invested  # normalised to [0, 1]

        # HHI on invested weights (= concentration measure in [1/n, 1])
        hhi = sum((w / invested) ** 2 for w in weights.values() if w > 0.0)

        composite = 0.70 * avg_risk + 0.30 * hhi
        return _clamp(composite, 0.0, 1.0)

    def _compute_tier_breakdown(
        self,
        weights: Dict[str, float],
        adapters: Dict[str, Dict[str, Any]],
    ) -> Dict[str, float]:
        """Aggregate weights by tier; always returns T1/T2/T3/cash keys."""
        breakdown: Dict[str, float] = {"T1": 0.0, "T2": 0.0, "T3": 0.0}
        for aid, w in weights.items():
            if w <= 0.0:
                continue
            tier = _get_tier(adapters, aid)
            if tier in breakdown:
                breakdown[tier] += w
            else:
                breakdown["T1"] += w  # unknown tier treated as T1
        invested = sum(breakdown.values())
        breakdown["cash"] = max(0.0, round(1.0 - invested, 8))
        return breakdown


# ── CLI entry-point ───────────────────────────────────────────────────────────

def _main(argv: Optional[List[str]] = None) -> int:  # noqa: C901
    parser = argparse.ArgumentParser(
        description="SPA YieldOptimizer — compute and optionally record optimised weights."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        default=False,
        help="Compute and print without writing to disk (default).",
    )
    parser.add_argument(
        "--run",
        action="store_true",
        default=False,
        help="Compute and atomically write to data/yield_optimizer_results.json.",
    )
    parser.add_argument(
        "--data-dir",
        default=_DEFAULT_DATA_DIR,
        help="Data directory for yield_optimizer_results.json.",
    )
    args = parser.parse_args(argv)
    if not args.run:
        args.check = True

    optimizer = YieldOptimizer()

    # Illustrative adapters for self-test (mirrors position_sizer CLI)
    adapters: Dict[str, Any] = {
        "aave_v3":           {"apy": 3.5,  "tvl": 9_000_000_000, "risk_score": 0.20, "tier": "T1"},
        "compound_v3":       {"apy": 4.8,  "tvl": 2_000_000_000, "risk_score": 0.22, "tier": "T1"},
        "morpho_steakhouse": {"apy": 6.5,  "tvl": 800_000_000,   "risk_score": 0.30, "tier": "T1"},
        "yearn_v3":          {"apy": 5.2,  "tvl": 300_000_000,   "risk_score": 0.40, "tier": "T2"},
        "euler_v2":          {"apy": 4.1,  "tvl": 150_000_000,   "risk_score": 0.45, "tier": "T2"},
    }
    portfolio_value = 100_000.0
    constraints: Dict[str, Any] = {"max_risk": 0.9, "min_apy": 2.0, "max_t2_pct": 0.50}

    result = optimizer.optimize(adapters, portfolio_value, constraints)

    print(f"=== YieldOptimizer self-test  (portfolio ${portfolio_value:,.0f}) ===")
    print(f"Expected APY : {result.expected_apy:.4f} %")
    print(f"Risk score   : {result.risk_score:.4f}")
    print()
    print("Weights:")
    for aid, w in sorted(result.weights.items(), key=lambda x: -x[1]):
        if w > 0.0:
            tier = adapters[aid].get("tier", "??")
            print(f"  [{tier}] {aid:25s}  {w:6.2%}")
    print()
    print("Tier breakdown:")
    for tier, w in result.tier_breakdown.items():
        print(f"  {tier}: {w:.2%}")
    if result.warnings:
        print("\nWarnings:")
        for msg in result.warnings:
            print(f"  ⚠  {msg}")

    # Efficient frontier (5 points)
    frontier = optimizer.compute_efficient_frontier(
        adapters, portfolio_value, n_points=5, constraints=constraints
    )
    print(f"\nEfficient frontier ({len(frontier)} points):")
    for i, pt in enumerate(frontier):
        print(f"  [{i}] APY={pt.expected_apy:.4f}%  risk={pt.risk_score:.4f}")

    # Sharpe-optimal
    sharpe_opt = optimizer.get_sharpe_optimal(
        adapters, portfolio_value, risk_free_rate=0.04, constraints=constraints
    )
    print(
        f"\nSharpe-optimal: APY={sharpe_opt.expected_apy:.4f}%  "
        f"risk={sharpe_opt.risk_score:.4f}"
    )

    if args.run:
        optimizer.save_result(result, data_dir=args.data_dir, label="cli_self_test")
        print(f"\nResult saved → {args.data_dir}/{RESULTS_FILENAME}")

    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sys.exit(_main())
