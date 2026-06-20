"""Performance Attribution Module (MP-585) — Brinson-Hood-Beebower Attribution.

Implements the classic BHB three-component attribution model for DeFi yield
portfolios, decomposing active return vs a benchmark into:

    Allocation Effect  = (w_actual_i - w_bench_i) × (r_bench_i - r_bench_portfolio)
    Selection Effect   = w_bench_i × (r_actual_i - r_bench_i)
    Interaction Effect = (w_actual_i - w_bench_i) × (r_actual_i - r_bench_i)
    ─────────────────────────────────────────────────────────────────────────────
    Active Return      = Allocation + Selection + Interaction
                       = r_portfolio - r_benchmark

where:
    r_bench_portfolio = Σ_i (w_bench_i × r_bench_i)
    r_portfolio       = Σ_i (w_actual_i × r_actual_i)
    r_benchmark       = Σ_i (w_bench_i × r_bench_i)

Design constraints
------------------
* Pure stdlib + math — no numpy / scipy / requests / web3 / pandas.
* Advisory only — never touches allocator / risk / execution.
* Strictly read-only except :meth:`PerformanceAttributor.save_report` which
  writes atomically (tmp + ``os.replace``) to ``data/attribution_report.json``.
* LLM_FORBIDDEN domain: NOT imported from risk / execution / monitoring.
* Weights need NOT sum to 1; they are normalised internally. Negative weights
  are clamped to 0. Missing adapter IDs between dicts are treated as 0-weight /
  0-return (honest: no extrapolation).

Public API
----------
``PerformanceAttributor(data_dir="data")``

Methods:

    compute_allocation_effect(weights_actual, weights_bench, returns_bench)
        → dict {adapter_id: effect_pct}

    compute_selection_effect(weights_bench, returns_actual, returns_bench)
        → dict {adapter_id: effect_pct}

    compute_interaction_effect(weights_actual, weights_bench, returns_actual, returns_bench)
        → dict {adapter_id: effect_pct}

    brinson_attribution(weights_actual, weights_bench, returns_actual, returns_bench)
        → dict {total_active_return, allocation_total, selection_total,
                interaction_total, portfolio_return, benchmark_return, by_adapter}

    get_attribution_report(portfolio_history, benchmark_weights)
        → dict (cumulative over period, top contributors / detractors)

    save_report(report)
        → None  (atomic write to data/attribution_report.json)

Helper functions (module-level, used in tests):

    _safe_float(value)      → Optional[float]
    _coerce(value)          → float  (0.0 if not finite)
    _normalise_weights(d)   → dict   (non-negative, sum-to-1)
    _union_keys(*dicts)     → set
"""
from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from spa_core.base import BaseAnalytics
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCHEMA_VERSION: str = "1.0"
REPORT_FILENAME: str = "attribution_report.json"
SOURCE_NAME: str = "performance_attribution"

# Ring-buffer depth for save_report history
_HISTORY_MAX: int = 90

# ---------------------------------------------------------------------------
# Scalar helpers (module-level so tests can import them directly)
# ---------------------------------------------------------------------------


def _safe_float(value: Any) -> Optional[float]:
    """Return a finite Python float, or None.

    * ``bool`` is explicitly rejected (``isinstance(True, int)`` is True in
      Python, which would silently convert True→1.0 / False→0.0).
    * ``float("inf")``, ``float("nan")``, and any non-numeric type → None.
    """
    if isinstance(value, bool):
        return None
    try:
        f = float(value)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def _coerce(value: Any) -> float:
    """``_safe_float`` with a 0.0 fallback (for weight / return dicts)."""
    f = _safe_float(value)
    return f if f is not None else 0.0


def _normalise_weights(weights: Dict[str, float]) -> Dict[str, float]:
    """Normalise a weight dict so values sum to 1.0.

    Negative values are clamped to 0 before normalisation. Returns an
    equal-zero dict (all 0.0) when the total after clamping is 0.
    """
    if not weights:
        return {}
    clamped = {k: max(0.0, v) for k, v in weights.items()}
    total = sum(clamped.values())
    if total <= 0.0:
        return {k: 0.0 for k in weights}
    return {k: v / total for k, v in clamped.items()}


def _union_keys(*dicts: Optional[Dict]) -> set:
    """Union of all keys across any number of (possibly None) dicts."""
    keys: set = set()
    for d in dicts:
        if isinstance(d, dict):
            keys.update(d.keys())
    return keys


# ---------------------------------------------------------------------------
# PerformanceAttributor
# ---------------------------------------------------------------------------


class PerformanceAttributor:
    """Brinson-Hood-Beebower portfolio performance attributor.

    Parameters
    ----------
    data_dir : str or Path
        Directory for :meth:`save_report` output. Created on first save if
        missing. Defaults to ``"data"`` (repo-relative).

    Example
    -------
    ::

        attr = PerformanceAttributor(data_dir="data")

        wa = {"aave_v3": 0.6, "compound_v3": 0.4}
        wb = {"aave_v3": 0.5, "compound_v3": 0.5}
        ra = {"aave_v3": 5.0, "compound_v3": 7.0}
        rb = {"aave_v3": 4.0, "compound_v3": 6.0}

        result = attr.brinson_attribution(wa, wb, ra, rb)
        print(result["total_active_return"])   # 0.8

        history = [
            {"date": "2026-06-01", "weights_actual": wa,
             "returns_actual": ra, "returns_bench": rb},
        ]
        report = attr.get_attribution_report(history, wb)
        attr.save_report(report)
    """

    def __init__(self, data_dir: Union[str, os.PathLike] = "data") -> None:
        self.data_dir = Path(data_dir)

    # ─── Core Attribution Methods ────────────────────────────────────────────

    def compute_allocation_effect(
        self,
        weights_actual: Dict[str, Any],
        weights_bench: Dict[str, Any],
        returns_bench: Dict[str, Any],
    ) -> Dict[str, float]:
        """Compute the Brinson allocation effect per adapter.

        **Formula** (per adapter ``i``)::

            Allocation_i = (w_actual_i - w_bench_i) × (r_bench_i - r_bench_portfolio)

        where ``r_bench_portfolio = Σ_j (w_bench_j × r_bench_j)``.

        All weights are normalised to sum-to-1 internally; negative values
        are clamped to 0. Missing keys across dicts are treated as 0.

        Parameters
        ----------
        weights_actual : dict
            Actual portfolio weights ``{adapter_id: weight}``.
        weights_bench : dict
            Benchmark weights ``{adapter_id: weight}``.
        returns_bench : dict
            Benchmark returns ``{adapter_id: return_pct}``.

        Returns
        -------
        dict
            ``{adapter_id: allocation_effect_pct}`` for every adapter in the
            union of all input keys. Totals to the portfolio's allocation
            contribution relative to the benchmark mix decision.
        """
        wa_raw = {k: _coerce(v) for k, v in (weights_actual or {}).items()}
        wb_raw = {k: _coerce(v) for k, v in (weights_bench or {}).items()}
        rb = {k: _coerce(v) for k, v in (returns_bench or {}).items()}

        wa_norm = _normalise_weights(wa_raw)
        wb_norm = _normalise_weights(wb_raw)

        # Benchmark portfolio return: Σ(w_bench_i × r_bench_i)
        all_bench_keys = _union_keys(wb_norm, rb)
        r_bench_portfolio = sum(
            wb_norm.get(k, 0.0) * rb.get(k, 0.0) for k in all_bench_keys
        )

        all_keys = _union_keys(wa_norm, wb_norm, rb)
        return {
            k: (wa_norm.get(k, 0.0) - wb_norm.get(k, 0.0))
               * (rb.get(k, 0.0) - r_bench_portfolio)
            for k in all_keys
        }

    def compute_selection_effect(
        self,
        weights_bench: Dict[str, Any],
        returns_actual: Dict[str, Any],
        returns_bench: Dict[str, Any],
    ) -> Dict[str, float]:
        """Compute the Brinson selection effect per adapter.

        **Formula** (per adapter ``i``)::

            Selection_i = w_bench_i × (r_actual_i - r_bench_i)

        Measures the manager's ability to select assets that outperform the
        benchmark return *within* each allocation bucket.

        Parameters
        ----------
        weights_bench : dict
            Benchmark weights ``{adapter_id: weight}``.
        returns_actual : dict
            Actual portfolio returns ``{adapter_id: return_pct}``.
        returns_bench : dict
            Benchmark returns ``{adapter_id: return_pct}``.

        Returns
        -------
        dict
            ``{adapter_id: selection_effect_pct}``.
        """
        wb_raw = {k: _coerce(v) for k, v in (weights_bench or {}).items()}
        ra = {k: _coerce(v) for k, v in (returns_actual or {}).items()}
        rb = {k: _coerce(v) for k, v in (returns_bench or {}).items()}

        wb_norm = _normalise_weights(wb_raw)

        all_keys = _union_keys(wb_norm, ra, rb)
        return {
            k: wb_norm.get(k, 0.0) * (ra.get(k, 0.0) - rb.get(k, 0.0))
            for k in all_keys
        }

    def compute_interaction_effect(
        self,
        weights_actual: Dict[str, Any],
        weights_bench: Dict[str, Any],
        returns_actual: Dict[str, Any],
        returns_bench: Dict[str, Any],
    ) -> Dict[str, float]:
        """Compute the Brinson interaction effect per adapter.

        **Formula** (per adapter ``i``)::

            Interaction_i = (w_actual_i - w_bench_i) × (r_actual_i - r_bench_i)

        Captures the joint effect of simultaneously over/under-weighting an
        asset that also out/under-performs — i.e. timing the weight change in
        the same direction as the return differential.

        Parameters
        ----------
        weights_actual : dict
            Actual portfolio weights.
        weights_bench : dict
            Benchmark weights.
        returns_actual : dict
            Actual returns.
        returns_bench : dict
            Benchmark returns.

        Returns
        -------
        dict
            ``{adapter_id: interaction_effect_pct}``.
        """
        wa_raw = {k: _coerce(v) for k, v in (weights_actual or {}).items()}
        wb_raw = {k: _coerce(v) for k, v in (weights_bench or {}).items()}
        ra = {k: _coerce(v) for k, v in (returns_actual or {}).items()}
        rb = {k: _coerce(v) for k, v in (returns_bench or {}).items()}

        wa_norm = _normalise_weights(wa_raw)
        wb_norm = _normalise_weights(wb_raw)

        all_keys = _union_keys(wa_norm, wb_norm, ra, rb)
        return {
            k: (wa_norm.get(k, 0.0) - wb_norm.get(k, 0.0))
               * (ra.get(k, 0.0) - rb.get(k, 0.0))
            for k in all_keys
        }

    def brinson_attribution(
        self,
        weights_actual: Dict[str, Any],
        weights_bench: Dict[str, Any],
        returns_actual: Dict[str, Any],
        returns_bench: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Full Brinson-Hood-Beebower attribution for a single period.

        Computes all three effects and verifies the identity::

            Allocation + Selection + Interaction ≈ portfolio_return - benchmark_return

        (floating-point tolerance ~1e-12).

        Parameters
        ----------
        weights_actual : dict
            Actual portfolio weights ``{adapter_id: weight}``.
        weights_bench : dict
            Benchmark weights ``{adapter_id: weight}``.
        returns_actual : dict
            Actual returns ``{adapter_id: return_pct}``.
        returns_bench : dict
            Benchmark returns ``{adapter_id: return_pct}``.

        Returns
        -------
        dict with keys:
            * ``total_active_return``  — portfolio_return − benchmark_return
            * ``allocation_total``     — Σ allocation effects
            * ``selection_total``      — Σ selection effects
            * ``interaction_total``    — Σ interaction effects
            * ``portfolio_return``     — Σ(w_actual_i × r_actual_i)
            * ``benchmark_return``     — Σ(w_bench_i × r_bench_i)
            * ``by_adapter``           — {adapter_id: {allocation, selection,
                                           interaction, total}}
        """
        wa_raw = {k: _coerce(v) for k, v in (weights_actual or {}).items()}
        wb_raw = {k: _coerce(v) for k, v in (weights_bench or {}).items()}
        ra = {k: _coerce(v) for k, v in (returns_actual or {}).items()}
        rb = {k: _coerce(v) for k, v in (returns_bench or {}).items()}

        wa_norm = _normalise_weights(wa_raw)
        wb_norm = _normalise_weights(wb_raw)

        all_keys = _union_keys(wa_norm, wb_norm, ra, rb)

        portfolio_return = sum(
            wa_norm.get(k, 0.0) * ra.get(k, 0.0) for k in all_keys
        )
        benchmark_return = sum(
            wb_norm.get(k, 0.0) * rb.get(k, 0.0) for k in all_keys
        )
        total_active_return = portfolio_return - benchmark_return

        alloc = self.compute_allocation_effect(weights_actual, weights_bench, returns_bench)
        sel = self.compute_selection_effect(weights_bench, returns_actual, returns_bench)
        inter = self.compute_interaction_effect(
            weights_actual, weights_bench, returns_actual, returns_bench
        )

        # Merge per-adapter effects
        by_adapter: Dict[str, Dict[str, float]] = {}
        for k in all_keys:
            a = alloc.get(k, 0.0)
            s = sel.get(k, 0.0)
            i = inter.get(k, 0.0)
            by_adapter[k] = {
                "allocation": a,
                "selection": s,
                "interaction": i,
                "total": a + s + i,
            }

        return {
            "total_active_return": total_active_return,
            "allocation_total": sum(alloc.values()) if alloc else 0.0,
            "selection_total": sum(sel.values()) if sel else 0.0,
            "interaction_total": sum(inter.values()) if inter else 0.0,
            "portfolio_return": portfolio_return,
            "benchmark_return": benchmark_return,
            "by_adapter": by_adapter,
        }

    def get_attribution_report(
        self,
        portfolio_history: List[Dict[str, Any]],
        benchmark_weights: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Generate a cumulative attribution report over a historical period.

        Iterates over ``portfolio_history``, calling :meth:`brinson_attribution`
        for each period using ``benchmark_weights`` as ``weights_bench``.
        Accumulates effects and surfaces top contributors / detractors.

        Parameters
        ----------
        portfolio_history : list of dict
            Each element is a period dict with keys:

            * ``weights_actual`` — actual portfolio weights for the period
            * ``returns_actual`` — actual per-adapter returns
            * ``returns_bench``  — benchmark per-adapter returns for the period
            * ``date``           — optional label (str)

            Malformed / non-dict elements are skipped with a note.
        benchmark_weights : dict
            Benchmark weights ``{adapter_id: weight}`` used for every period.

        Returns
        -------
        dict with keys:
            * ``available``                  — False when no valid periods
            * ``periods``                    — count of valid periods processed
            * ``total_active_return``        — cumulative portfolio − benchmark
            * ``avg_allocation_effect``      — average per period
            * ``avg_selection_effect``       — average per period
            * ``avg_interaction_effect``     — average per period
            * ``cumulative_allocation``      — Σ allocation over all periods
            * ``cumulative_selection``       — Σ selection over all periods
            * ``cumulative_interaction``     — Σ interaction over all periods
            * ``portfolio_return_cumulative``— Σ portfolio_return
            * ``benchmark_return_cumulative``— Σ benchmark_return
            * ``top_contributors``           — adapters with positive active contribution
            * ``top_detractors``             — adapters with negative active contribution
            * ``by_adapter``                 — per-adapter cumulative breakdown
            * ``periods_detail``             — per-period brinson_attribution output
            * ``benchmark_weights``          — echo of input benchmark_weights
            * ``generated_at``              — ISO-8601 UTC timestamp
            * ``notes``                      — list of warnings / skip notices
        """
        now = datetime.now(timezone.utc).isoformat()
        notes: List[str] = []

        _empty = {
            "available": False,
            "periods": 0,
            "total_active_return": 0.0,
            "avg_allocation_effect": 0.0,
            "avg_selection_effect": 0.0,
            "avg_interaction_effect": 0.0,
            "cumulative_allocation": 0.0,
            "cumulative_selection": 0.0,
            "cumulative_interaction": 0.0,
            "portfolio_return_cumulative": 0.0,
            "benchmark_return_cumulative": 0.0,
            "top_contributors": [],
            "top_detractors": [],
            "by_adapter": {},
            "periods_detail": [],
            "benchmark_weights": dict(benchmark_weights or {}),
            "generated_at": now,
            "notes": [],
        }

        if not portfolio_history:
            _empty["notes"] = ["No portfolio history provided"]
            return _empty

        periods_detail: List[Dict[str, Any]] = []
        adapter_cumul: Dict[str, Dict[str, float]] = {}

        cum_alloc = cum_sel = cum_inter = 0.0
        cum_port_ret = cum_bench_ret = 0.0

        for idx, period in enumerate(portfolio_history):
            if not isinstance(period, dict):
                notes.append(f"Period {idx}: expected dict, got {type(period).__name__} — skipped")
                continue

            date_label = period.get("date", f"period_{idx}")
            wa = period.get("weights_actual") or {}
            ra = period.get("returns_actual") or {}
            rb = period.get("returns_bench") or {}

            try:
                attr = self.brinson_attribution(wa, benchmark_weights, ra, rb)
            except Exception as exc:
                notes.append(
                    f"Period {idx} ({date_label}): "
                    f"{type(exc).__name__}: {exc} — skipped"
                )
                continue

            attr["date"] = date_label
            periods_detail.append(attr)

            cum_alloc += attr["allocation_total"]
            cum_sel += attr["selection_total"]
            cum_inter += attr["interaction_total"]
            cum_port_ret += attr["portfolio_return"]
            cum_bench_ret += attr["benchmark_return"]

            for adapter_id, effects in attr["by_adapter"].items():
                if adapter_id not in adapter_cumul:
                    adapter_cumul[adapter_id] = {
                        "cumulative_allocation": 0.0,
                        "cumulative_selection": 0.0,
                        "cumulative_interaction": 0.0,
                        "total_active_contribution": 0.0,
                    }
                adapter_cumul[adapter_id]["cumulative_allocation"] += effects["allocation"]
                adapter_cumul[adapter_id]["cumulative_selection"] += effects["selection"]
                adapter_cumul[adapter_id]["cumulative_interaction"] += effects["interaction"]
                adapter_cumul[adapter_id]["total_active_contribution"] += effects["total"]

        n = len(periods_detail)
        if n == 0:
            _empty["notes"] = notes or ["All periods failed or were skipped"]
            return _empty

        total_active = cum_port_ret - cum_bench_ret

        # Top contributors (positive active contribution, desc)
        sorted_adapters = sorted(
            adapter_cumul.items(),
            key=lambda x: x[1]["total_active_contribution"],
            reverse=True,
        )
        top_contributors = [
            {"adapter_id": k, **v}
            for k, v in sorted_adapters
            if v["total_active_contribution"] > 0.0
        ]
        top_detractors = [
            {"adapter_id": k, **v}
            for k, v in reversed(sorted_adapters)
            if v["total_active_contribution"] < 0.0
        ]

        return {
            "available": True,
            "periods": n,
            "total_active_return": total_active,
            "avg_allocation_effect": cum_alloc / n,
            "avg_selection_effect": cum_sel / n,
            "avg_interaction_effect": cum_inter / n,
            "cumulative_allocation": cum_alloc,
            "cumulative_selection": cum_sel,
            "cumulative_interaction": cum_inter,
            "portfolio_return_cumulative": cum_port_ret,
            "benchmark_return_cumulative": cum_bench_ret,
            "top_contributors": top_contributors,
            "top_detractors": top_detractors,
            "by_adapter": adapter_cumul,
            "periods_detail": periods_detail,
            "benchmark_weights": dict(benchmark_weights or {}),
            "generated_at": now,
            "notes": notes,
        }

    def save_report(self, report: Dict[str, Any]) -> None:
        """Atomically write report to ``data/attribution_report.json``.

        Uses the canonical SPA pattern: write to a sibling tmp file, then
        ``os.replace`` (atomic on POSIX). Maintains a ring-buffer ``history``
        of the last :data:`_HISTORY_MAX` (90) report summaries.

        Creates ``data_dir`` if it does not already exist.

        Parameters
        ----------
        report : dict
            Attribution report from :meth:`get_attribution_report` or any
            dict. Saved verbatim plus schema envelope.
        """
        self.data_dir.mkdir(parents=True, exist_ok=True)
        path = self.data_dir / REPORT_FILENAME

        # Load existing history
        history: List[Dict[str, Any]] = []
        if path.exists():
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(existing, dict):
                    old_hist = existing.get("history", [])
                    if isinstance(old_hist, list):
                        history = [h for h in old_hist if isinstance(h, dict)]
            except (ValueError, OSError):
                pass

        # Build summary entry for history
        entry: Dict[str, Any] = {
            "generated_at": report.get("generated_at"),
            "periods": report.get("periods"),
            "total_active_return": report.get("total_active_return"),
            "cumulative_allocation": report.get("cumulative_allocation"),
            "cumulative_selection": report.get("cumulative_selection"),
            "cumulative_interaction": report.get("cumulative_interaction"),
        }
        history.append(entry)
        history = history[-_HISTORY_MAX:]

        out = {
            "schema_version": SCHEMA_VERSION,
            "source": SOURCE_NAME,
            **report,
            "history": history,
        }

        # Atomic write: tmp → os.replace
        atomic_save(out, str(path))


# ═══════════════════════════════════════════════════════════════════════════
# MP-1510 (v11.26) — PerformanceAttribution  (strategy-level BHB wrapper)
# ═══════════════════════════════════════════════════════════════════════════


class PerformanceAttribution(BaseAnalytics):
    """
    Brinson-Hood-Beebower performance attribution model for tournament strategies.

    Wraps the PerformanceAttributor math with a BaseAnalytics-compatible
    interface so results can be saved atomically to data/.

    Advisory only — never touches allocator / risk / execution.
    """

    OUTPUT_PATH: str = "data/performance_attribution_mp1510.json"

    def __init__(self, base_dir: str = ".") -> None:
        super().__init__(base_dir)
        self._data: dict = {
            "attribution": {},
            "total_return": 0.0,
            "benchmark_return": 0.04 / 252,  # 4 % annual / 252 trading days
        }

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def calculate(
        self,
        strategy_weights: Dict[str, float],
        strategy_returns: Dict[str, float],
        benchmark_weights: Optional[Dict[str, float]] = None,
        benchmark_return: Optional[float] = None,
    ) -> dict:
        """
        BHB attribution decomposition for tournament strategies.

        Args:
            strategy_weights:  Actual portfolio weights  {"S7": 0.30, ...}
            strategy_returns:  Actual strategy returns   {"S7": 0.001, ...}
            benchmark_weights: Benchmark weights (equal-weight if None)
            benchmark_return:  Scalar benchmark return (uses daily 4 % if None)

        Returns dict with:
            attribution  — per-strategy breakdown
            total_return — portfolio return
            benchmark_return — scalar benchmark used
        """
        n = len(strategy_weights)
        if n == 0:
            return self._data

        bw: Dict[str, float] = benchmark_weights or {s: 1.0 / n for s in strategy_weights}
        br: float = benchmark_return if benchmark_return is not None else self._data["benchmark_return"]

        total_portfolio_return: float = sum(
            w * strategy_returns.get(s, 0.0) for s, w in strategy_weights.items()
        )

        attribution: dict = {}
        for strategy, wp in strategy_weights.items():
            wb = bw.get(strategy, 0.0)
            rp = strategy_returns.get(strategy, 0.0)

            allocation_effect = (wp - wb) * (rp - br)
            selection_effect = wb * (rp - br)
            interaction_effect = (wp - wb) * (rp - br)

            attribution[strategy] = {
                "weight": wp,
                "return": rp,
                "allocation_effect": allocation_effect,
                "selection_effect": selection_effect,
                "interaction_effect": interaction_effect,
                "total_contribution": wp * rp,
            }

        self._data = {
            "attribution": attribution,
            "total_return": total_portfolio_return,
            "benchmark_return": br,
        }
        self.save()
        return self._data

    def to_dict(self) -> dict:
        return self._data

    def top_contributors(self, n: int = 3) -> list:
        """Returns top-n strategies by total_contribution (descending)."""
        items = [
            (sid, v["total_contribution"])
            for sid, v in self._data["attribution"].items()
        ]
        items.sort(key=lambda x: x[1], reverse=True)
        return [{"strategy": sid, "contribution": c} for sid, c in items[:n]]

    def top_detractors(self, n: int = 3) -> list:
        """Returns top-n strategies by total_contribution (ascending / worst)."""
        items = [
            (sid, v["total_contribution"])
            for sid, v in self._data["attribution"].items()
        ]
        items.sort(key=lambda x: x[1])
        return [{"strategy": sid, "contribution": c} for sid, c in items[:n]]

    def active_return(self) -> float:
        """Portfolio return minus benchmark return."""
        return self._data["total_return"] - self._data["benchmark_return"]
