"""Risk Budget Manager (MP-582).

Manages portfolio risk-budget allocation: tracks how much of the portfolio's
aggregate risk budget is consumed by each adapter, flags WARNING / BREACH
conditions, and reports parametric VaR estimates.

Design constraints
------------------
* Pure stdlib + math — no numpy / scipy / requests / web3 / pandas.
* Advisory only — never touches allocator / risk / execution.
* Strictly read-only except :meth:`save_report` which writes atomically
  (tmp + ``os.replace``) to ``data/risk_budget_report.json``.
* LLM_FORBIDDEN domain: NOT imported from risk / execution / monitoring.

Risk Contribution
-----------------
Given adapter weights ``w_i`` (non-negative, any scale) and risk scores
``rs_i`` ∈ [0, 1]::

    portfolio_risk  = Σ w_i · rs_i          (weighted sum of raw risk scores)
    contribution_i  = (w_i · rs_i / portfolio_risk) · 100    [percent]

Parametric VaR (normal, independence assumption)
-------------------------------------------------
Treating ``risk_scores`` as volatility proxies σ_i (fraction of AUM
per unit of weight)::

    portfolio_vol = √(Σ (w̃_i · σ_i)²)      where w̃_i = w_i / Σ w_j
    VaR(c)        = z(c) · portfolio_vol    [fraction of AUM, c ∈ (0, 1)]

z(c) is the standard-normal quantile at confidence c (Φ⁻¹(c)).

Diversification Ratio
---------------------
::
    DR = Σ(w̃_i · σ_i) / portfolio_vol   (≥ 1; higher → more benefit)

Budget Status Thresholds
------------------------
* ``OK``      — contribution_pct  <  0.9 × limit
* ``WARNING`` — 0.9 × limit  ≤  contribution_pct  ≤  limit
* ``BREACH``  — contribution_pct  >  limit

Public API
----------
``RiskBudgetManager(data_dir="data")``

Methods:

    compute_risk_contribution(weights, risk_scores) → dict
    get_budget_status(weights, risk_scores, budget_limits) → dict
    suggest_reductions(weights, risk_scores, budget_limits) → list[dict]
    compute_portfolio_var(weights, risk_scores, confidence=0.95) → float
    get_risk_report(adapters, weights) → dict
    save_report(report) → None
"""
from __future__ import annotations

import json
import math
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Budget status labels
STATUS_OK = "OK"
STATUS_WARNING = "WARNING"
STATUS_BREACH = "BREACH"

# WARNING starts when allocation reaches this fraction of limit
_WARNING_THRESHOLD_FRAC: float = 0.90

# Atomic ring-buffer depth for save_report
_REPORT_HISTORY_MAX: int = 90

# Default output file (relative to data_dir)
_REPORT_FILE: str = "risk_budget_report.json"

# Standard confidence levels often requested
_CONFIDENCE_95: float = 0.95
_CONFIDENCE_99: float = 0.99


# ---------------------------------------------------------------------------
# Internal math helpers
# ---------------------------------------------------------------------------

def _norm_ppf(p: float) -> float:
    """Percent-point function (inverse CDF) of the standard normal distribution.

    Uses the Peter Acklam rational-polynomial approximation (2002).
    Maximum absolute error < 1.15 × 10⁻⁹.

    Parameters
    ----------
    p:
        Probability in (0, 1).

    Returns
    -------
    float
        x such that Φ(x) = p.
    """
    if p <= 0.0:
        return float("-inf")
    if p >= 1.0:
        return float("inf")

    # Coefficients (Acklam 2002)
    a = [
        -3.969683028665376e01,
         2.209460984245205e02,
        -2.759285104469687e02,
         1.383577518672690e02,
        -3.066479806614716e01,
         2.506628277459239e00,
    ]
    b = [
        -5.447609879822406e01,
         1.615858368580409e02,
        -1.556989798598866e02,
         6.680131188771972e01,
        -1.328068155288572e01,
    ]
    c = [
        -7.784894002430293e-03,
        -3.223964580411365e-01,
        -2.400758277161838e00,
        -2.549732539343734e00,
         4.374664141464968e00,
         2.938163982698783e00,
    ]
    d = [
         7.784695709041462e-03,
         3.224671290700398e-01,
         2.445134137142996e00,
         3.754408661907416e00,
    ]

    p_lo = 0.02425
    p_hi = 1.0 - p_lo

    if p < p_lo:
        q = math.sqrt(-2.0 * math.log(p))
        return (
            (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5])
            / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)
        )

    if p <= p_hi:
        q = p - 0.5
        r = q * q
        return (
            (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q
            / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0)
        )

    # p > p_hi
    q = math.sqrt(-2.0 * math.log(1.0 - p))
    return -(
        (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5])
        / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)
    )


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Coerce *value* to float; return *default* on failure."""
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalise_weights(
    weights: Dict[str, float],
) -> Dict[str, float]:
    """Return normalised weights (sum → 1.0); skip non-positive values."""
    pos = {k: v for k, v in weights.items() if isinstance(v, (int, float)) and float(v) > 0.0}
    total = sum(pos.values())
    if total <= 0.0:
        return {}
    return {k: v / total for k, v in pos.items()}


# ---------------------------------------------------------------------------
# RiskBudgetManager
# ---------------------------------------------------------------------------

class RiskBudgetManager:
    """Deterministic, advisory risk-budget manager for SPA portfolio adapters.

    All computation is pure (no IO except :meth:`save_report`).
    No external dependencies — stdlib + math only.

    Parameters
    ----------
    data_dir:
        Directory containing ``risk_budget_report.json`` (write target for
        :meth:`save_report`).  Defaults to ``"data"`` relative to CWD.
    """

    def __init__(self, data_dir: str = "data") -> None:
        self._data_dir = Path(data_dir)

    # ------------------------------------------------------------------
    # 1. compute_risk_contribution
    # ------------------------------------------------------------------

    def compute_risk_contribution(
        self,
        weights: Dict[str, float],
        risk_scores: Dict[str, float],
    ) -> Dict[str, float]:
        """Compute each adapter's percentage share of total portfolio risk.

        Formula (per adapter *i*)::

            portfolio_risk  = Σ w_i · rs_i   (over common keys)
            contribution_i  = (w_i · rs_i / portfolio_risk) · 100

        Only adapters present in BOTH ``weights`` and ``risk_scores`` are
        included.  Non-positive weights and negative risk scores are silently
        treated as zero contribution.

        Parameters
        ----------
        weights:
            ``{adapter_id: weight}`` — non-negative numeric weights
            (absolute USD amounts or fractions; raw scale is fine).
        risk_scores:
            ``{adapter_id: risk_score}`` — normalised risk proxy ∈ [0, 1].

        Returns
        -------
        dict
            ``{adapter_id: contribution_pct}`` — floats in [0, 100].
            Empty dict if portfolio risk is zero.
        """
        weights = {k: _safe_float(v) for k, v in (weights or {}).items()}
        risk_scores = {k: _safe_float(v) for k, v in (risk_scores or {}).items()}

        common = set(weights.keys()) & set(risk_scores.keys())
        raw: Dict[str, float] = {}
        for adapter_id in common:
            w = max(weights[adapter_id], 0.0)
            rs = max(risk_scores[adapter_id], 0.0)
            raw[adapter_id] = w * rs

        portfolio_risk = sum(raw.values())
        if portfolio_risk <= 0.0:
            return {k: 0.0 for k in raw}

        return {
            adapter_id: round(v / portfolio_risk * 100.0, 6)
            for adapter_id, v in raw.items()
        }

    # ------------------------------------------------------------------
    # 2. get_budget_status
    # ------------------------------------------------------------------

    def get_budget_status(
        self,
        weights: Dict[str, float],
        risk_scores: Dict[str, float],
        budget_limits: Dict[str, float],
    ) -> Dict[str, Dict[str, Any]]:
        """Check each adapter's risk allocation against its budget limit.

        Status logic (all values in % of total portfolio risk)::

            OK      — contribution  <  0.9 × limit
            WARNING — 0.9 × limit  ≤  contribution  ≤  limit
            BREACH  — contribution  >  limit

        Adapters not in ``budget_limits`` receive status ``OK`` with
        ``limit=None``.

        Parameters
        ----------
        weights:
            ``{adapter_id: weight}``
        risk_scores:
            ``{adapter_id: risk_score}``
        budget_limits:
            ``{adapter_id: limit_pct}`` — maximum allowed contribution (%).

        Returns
        -------
        dict
            ``{adapter_id: {allocated, limit, status}}``
        """
        contributions = self.compute_risk_contribution(weights, risk_scores)
        result: Dict[str, Dict[str, Any]] = {}

        all_ids = set(contributions.keys()) | set((budget_limits or {}).keys())

        for adapter_id in all_ids:
            allocated = contributions.get(adapter_id, 0.0)
            limit = _safe_float(
                (budget_limits or {}).get(adapter_id, None), default=float("nan")
            )
            has_limit = adapter_id in (budget_limits or {}) and not math.isnan(limit)

            if not has_limit:
                status = STATUS_OK
                limit_val: Optional[float] = None
            else:
                warn_floor = _WARNING_THRESHOLD_FRAC * limit
                if allocated > limit:
                    status = STATUS_BREACH
                elif allocated >= warn_floor:
                    status = STATUS_WARNING
                else:
                    status = STATUS_OK
                limit_val = round(limit, 6)

            result[adapter_id] = {
                "allocated": round(allocated, 6),
                "limit": limit_val,
                "status": status,
            }

        return result

    # ------------------------------------------------------------------
    # 3. suggest_reductions
    # ------------------------------------------------------------------

    def suggest_reductions(
        self,
        weights: Dict[str, float],
        risk_scores: Dict[str, float],
        budget_limits: Dict[str, float],
    ) -> List[Dict[str, Any]]:
        """Return reduction suggestions for adapters in BREACH.

        Only adapters with ``status == BREACH`` are included.
        Results are sorted by ``excess_pct`` descending (worst breach first).

        Parameters
        ----------
        weights:
            ``{adapter_id: weight}``
        risk_scores:
            ``{adapter_id: risk_score}``
        budget_limits:
            ``{adapter_id: limit_pct}``

        Returns
        -------
        list[dict]
            Each item::

                {
                  "adapter_id": str,
                  "allocated":  float,   # current contribution (%)
                  "limit":      float,   # budget limit (%)
                  "excess_pct": float,   # allocated − limit (%)
                  "suggested_weight_reduction_pct": float,  # fraction [0,1]
                  "message":    str,
                }

            Sorted by ``excess_pct`` descending.
        """
        status_map = self.get_budget_status(weights, risk_scores, budget_limits)
        breaches: List[Dict[str, Any]] = []

        for adapter_id, entry in status_map.items():
            if entry["status"] != STATUS_BREACH:
                continue

            allocated = entry["allocated"]
            limit = entry["limit"] or 0.0
            excess = allocated - limit

            # Suggested weight reduction to bring contribution back to limit.
            # Since contribution_i ∝ w_i, the required weight scale factor is:
            #   new_w_i = w_i × (limit / allocated)  → reduce by (1 - limit/allocated)
            if allocated > 0.0:
                suggested_reduction = max(1.0 - (limit / allocated), 0.0)
            else:
                suggested_reduction = 0.0

            breaches.append(
                {
                    "adapter_id": adapter_id,
                    "allocated": round(allocated, 6),
                    "limit": round(limit, 6),
                    "excess_pct": round(excess, 6),
                    "suggested_weight_reduction_pct": round(suggested_reduction, 6),
                    "message": (
                        f"{adapter_id}: risk contribution {allocated:.2f}% "
                        f"exceeds budget limit {limit:.2f}% "
                        f"(excess {excess:.2f}%); "
                        f"reduce weight by ~{suggested_reduction * 100:.1f}%"
                    ),
                }
            )

        breaches.sort(key=lambda x: x["excess_pct"], reverse=True)
        return breaches

    # ------------------------------------------------------------------
    # 4. compute_portfolio_var
    # ------------------------------------------------------------------

    def compute_portfolio_var(
        self,
        weights: Dict[str, float],
        risk_scores: Dict[str, float],
        confidence: float = 0.95,
    ) -> float:
        """Compute parametric portfolio VaR under the normal distribution.

        Treats ``risk_scores`` as volatility proxies σ_i (fraction of AUM
        per unit of normalised weight).  Independence assumption — no
        covariance terms::

            portfolio_vol = √(Σ (w̃_i · σ_i)²)     w̃_i are normalised weights
            VaR(c)        = z(c) · portfolio_vol   [fraction of AUM, 0..1]

        where z(c) = Φ⁻¹(c) (standard normal quantile).

        Parameters
        ----------
        weights:
            ``{adapter_id: weight}`` — non-negative.
        risk_scores:
            ``{adapter_id: risk_score}`` — volatility proxies ∈ [0, 1].
        confidence:
            Confidence level ∈ (0, 1).  Default 0.95.

        Returns
        -------
        float
            VaR as a fraction of AUM ∈ [0, ∞).  Returns 0.0 for empty /
            all-zero portfolios.

        Raises
        ------
        ValueError
            If ``confidence`` is not in (0, 1).
        """
        if not (0.0 < confidence < 1.0):
            raise ValueError(
                f"confidence must be in (0, 1), got {confidence!r}"
            )

        weights = {k: _safe_float(v) for k, v in (weights or {}).items()}
        risk_scores = {k: _safe_float(v) for k, v in (risk_scores or {}).items()}

        norm_w = _normalise_weights(weights)
        if not norm_w:
            return 0.0

        variance = 0.0
        for adapter_id, w in norm_w.items():
            sigma = max(risk_scores.get(adapter_id, 0.0), 0.0)
            variance += (w * sigma) ** 2

        portfolio_vol = math.sqrt(variance)
        z = _norm_ppf(confidence)
        return round(portfolio_vol * z, 8)

    # ------------------------------------------------------------------
    # 5. get_risk_report
    # ------------------------------------------------------------------

    def get_risk_report(
        self,
        adapters: Sequence[Any],
        weights: Sequence[float],
    ) -> Dict[str, Any]:
        """Generate a full risk-budget report for the portfolio.

        Parameters
        ----------
        adapters:
            Sequence of adapter dicts (or objects).  Each must expose:

            * ``id`` / ``adapter_id`` / ``protocol`` — string identifier
            * ``risk_score`` — numeric ∈ [0, 1]

            Missing fields use safe defaults (``id`` → ``"adapter_N"``,
            ``risk_score`` → ``0.0``).
        weights:
            Sequence of non-negative numeric weights corresponding to
            *adapters* (same length required).

        Returns
        -------
        dict with keys::

            generated_at       str    — ISO-8601 UTC timestamp
            n_adapters         int    — number of adapters processed
            contributions      dict   — {adapter_id: contribution_pct}
            var_95             float  — VaR at 95 % confidence
            var_99             float  — VaR at 99 % confidence
            portfolio_vol      float  — portfolio volatility (fraction of AUM)
            diversification_ratio  float  — DR ≥ 1 (or 1.0 if no dispersion)
            warnings           list[str]
            adapter_details    list[dict]  — per-adapter breakdown

        Raises
        ------
        ValueError
            If ``len(adapters) != len(weights)``.
        """
        if len(adapters) != len(weights):
            raise ValueError(
                f"adapters ({len(adapters)}) and weights ({len(weights)}) "
                "must have equal length"
            )

        # ---- build weight and risk_score dicts ----
        weight_dict: Dict[str, float] = {}
        risk_score_dict: Dict[str, float] = {}
        adapter_details: List[Dict[str, Any]] = []

        for i, (adapter, w) in enumerate(zip(adapters, weights)):
            # Resolve adapter_id
            if isinstance(adapter, dict):
                adapter_id = (
                    adapter.get("id")
                    or adapter.get("adapter_id")
                    or adapter.get("protocol")
                    or f"adapter_{i}"
                )
                risk_score = _safe_float(adapter.get("risk_score", 0.0))
            else:
                adapter_id = (
                    getattr(adapter, "id", None)
                    or getattr(adapter, "adapter_id", None)
                    or getattr(adapter, "protocol", None)
                    or f"adapter_{i}"
                )
                risk_score = _safe_float(getattr(adapter, "risk_score", 0.0))

            adapter_id = str(adapter_id)
            w_float = max(_safe_float(w), 0.0)
            risk_score = max(min(risk_score, 1.0), 0.0)

            weight_dict[adapter_id] = weight_dict.get(adapter_id, 0.0) + w_float
            risk_score_dict[adapter_id] = risk_score

            adapter_details.append(
                {
                    "adapter_id": adapter_id,
                    "weight": w_float,
                    "risk_score": risk_score,
                }
            )

        # ---- contributions ----
        contributions = self.compute_risk_contribution(weight_dict, risk_score_dict)

        # ---- VaR metrics ----
        var_95 = self.compute_portfolio_var(weight_dict, risk_score_dict, confidence=0.95)
        var_99 = self.compute_portfolio_var(weight_dict, risk_score_dict, confidence=0.99)

        # ---- portfolio volatility and diversification ratio ----
        norm_w = _normalise_weights(weight_dict)
        portfolio_vol = 0.0
        weighted_avg_vol = 0.0

        if norm_w:
            variance = 0.0
            for aid, w in norm_w.items():
                sigma = max(risk_score_dict.get(aid, 0.0), 0.0)
                variance += (w * sigma) ** 2
                weighted_avg_vol += w * sigma
            portfolio_vol = math.sqrt(variance)

        if portfolio_vol > 0.0:
            diversification_ratio = round(weighted_avg_vol / portfolio_vol, 6)
        else:
            diversification_ratio = 1.0

        # ---- warnings ----
        warnings: List[str] = []

        # High concentration: single adapter > 50% contribution
        for aid, contrib in contributions.items():
            if contrib > 50.0:
                warnings.append(
                    f"{aid}: dominates risk budget at {contrib:.1f}% contribution"
                )

        # Very low diversification ratio
        if diversification_ratio < 1.05 and len(weight_dict) > 1:
            warnings.append(
                f"Low diversification ratio ({diversification_ratio:.3f}): "
                "adapters are highly risk-correlated"
            )

        # High VaR
        if var_95 > 0.30:
            warnings.append(
                f"High portfolio VaR-95: {var_95:.3f} (>{0.30:.0%} of AUM)"
            )

        # Zero risk-score adapters with non-zero weight
        for aid, w in weight_dict.items():
            if w > 0 and risk_score_dict.get(aid, 0.0) == 0.0:
                warnings.append(
                    f"{aid}: weight {w:.2f} but risk_score=0 — "
                    "risk may be unmodelled"
                )

        # Enrich adapter_details with contribution
        for detail in adapter_details:
            aid = detail["adapter_id"]
            detail["contribution_pct"] = contributions.get(aid, 0.0)

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "n_adapters": len(adapters),
            "contributions": contributions,
            "var_95": var_95,
            "var_99": var_99,
            "portfolio_vol": round(portfolio_vol, 8),
            "diversification_ratio": diversification_ratio,
            "warnings": warnings,
            "adapter_details": adapter_details,
        }

    # ------------------------------------------------------------------
    # 6. save_report
    # ------------------------------------------------------------------

    def save_report(self, report: Dict[str, Any]) -> None:
        """Atomically save *report* to ``<data_dir>/risk_budget_report.json``.

        Maintains a ``history`` ring-buffer of the last
        :data:`_REPORT_HISTORY_MAX` reports inside the file.
        Uses ``tmp-file + os.replace`` for crash safety.

        Parameters
        ----------
        report:
            The dict returned by :meth:`get_risk_report` (or any valid
            risk-budget report dict).
        """
        self._data_dir.mkdir(parents=True, exist_ok=True)
        out_path = self._data_dir / _REPORT_FILE

        # Load existing history
        history: List[Dict[str, Any]] = []
        if out_path.exists():
            try:
                with open(out_path, "r", encoding="utf-8") as fh:
                    existing = json.load(fh)
                history = existing.get("history", [])
                if not isinstance(history, list):
                    history = []
            except (json.JSONDecodeError, OSError):
                history = []

        history.append(report)
        if len(history) > _REPORT_HISTORY_MAX:
            history = history[-_REPORT_HISTORY_MAX:]

        doc = {
            "schema_version": "1.0",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "latest": report,
            "history": history,
            "history_depth": len(history),
        }

        # Atomic write: tmp → os.replace
        tmp_fd, tmp_path = tempfile.mkstemp(
            dir=self._data_dir, prefix=".risk_budget_report_tmp_"
        )
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as fh:
                json.dump(doc, fh, indent=2)
            os.replace(tmp_path, out_path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise


# ---------------------------------------------------------------------------
# Module-level convenience exports
# ---------------------------------------------------------------------------

__all__ = [
    "RiskBudgetManager",
    "STATUS_OK",
    "STATUS_WARNING",
    "STATUS_BREACH",
    "_norm_ppf",
    "_safe_float",
    "_normalise_weights",
    "_WARNING_THRESHOLD_FRAC",
    "_REPORT_HISTORY_MAX",
]
