"""
spa_core.analytics.honest_metrics — confidence-aware performance metrics.

Sprint B / v3.91 — "Honest Metrics".

Raw Sharpe on a handful of paper-trading points is dangerously misleading: a
20-point series can show a wildly negative (or positive) Sharpe that is pure
noise. This module replaces bare point-estimates with metrics that *carry their
own uncertainty*:

  - :func:`compute_sortino`        — downside-only deviation, with a confidence
                                     label and an explicit ``None`` when there is
                                     no downside / not enough data to judge.
  - :func:`compute_sharpe_with_ci` — bootstrap confidence interval around Sharpe
                                     plus a ``low_sample_warning`` flag.
  - :func:`compute_calmar`         — annualised return over max drawdown.
  - :func:`min_sample_check`       — human-readable "not enough points" warning.
  - :func:`label_metric`           — one-line labelled value with ✓ / ⚠ flag.

Confidence is driven purely by sample size ``n``:

    n < 15   -> "low"
    15 <= n <= 30 -> "medium"
    n > 30   -> "high"

Stdlib only (``math`` + ``random``). No I/O, no network, no imports of
execution / feed_health / risk agents — this is a pure numeric helper.
"""
from __future__ import annotations

import math
import random

#: Below this many points a metric is flagged LOW CONFIDENCE.
MIN_RELIABLE_SAMPLES = 30

#: Bootstrap resample count for the Sharpe confidence interval.
BOOTSTRAP_ITERS = 1000

#: Minimum points required before a bootstrap CI is attempted.
BOOTSTRAP_MIN_N = 10

#: Minimum points before Sortino is even computed.
SORTINO_MIN_PERIODS = 5


# --------------------------------------------------------------------------- #
# internal helpers                                                            #
# --------------------------------------------------------------------------- #
def _confidence(n: int) -> str:
    """Map a sample size to a confidence label.

    ``n < 15`` -> ``"low"``; ``15 <= n <= 30`` -> ``"medium"``; ``n > 30`` ->
    ``"high"``.
    """
    if n < 15:
        return "low"
    if n <= 30:
        return "medium"
    return "high"


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _pop_std(values: list[float]) -> float:
    """Population standard deviation (0.0 for <2 points or zero variance)."""
    if len(values) < 2:
        return 0.0
    mu = _mean(values)
    var = sum((v - mu) ** 2 for v in values) / len(values)
    return math.sqrt(var) if var > 0 else 0.0


def _sharpe_point(returns: list[float], rf: float) -> float | None:
    """Plain Sharpe point-estimate: ``(mean - rf) / std``; ``None`` if std==0."""
    if len(returns) < 2:
        return None
    sd = _pop_std(returns)
    if sd <= 0:
        return None
    return (_mean(returns) - rf) / sd


def _percentile(sorted_vals: list[float], pct: float) -> float:
    """Linear-interpolation percentile of an already-sorted list."""
    if not sorted_vals:
        return float("nan")
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    rank = (pct / 100.0) * (len(sorted_vals) - 1)
    lo = math.floor(rank)
    hi = math.ceil(rank)
    if lo == hi:
        return sorted_vals[int(rank)]
    frac = rank - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


def _equity_values(equity_curve: list) -> list[float]:
    """Extract a numeric equity series from a curve of dicts or raw numbers."""
    out: list[float] = []
    for pt in equity_curve or []:
        if isinstance(pt, dict):
            val = pt.get("equity")
        else:
            val = pt
        try:
            if val is not None:
                out.append(float(val))
        except (TypeError, ValueError):
            continue
    return out


def _max_drawdown_frac(equity_values: list[float]) -> float:
    """Largest peak-to-trough decline as a positive fraction (0.05 == 5%)."""
    peak = None
    max_dd = 0.0
    for eq in equity_values:
        if peak is None or eq > peak:
            peak = eq
        if peak and peak > 0:
            dd = (peak - eq) / peak
            if dd > max_dd:
                max_dd = dd
    return max_dd


# --------------------------------------------------------------------------- #
# public metrics                                                              #
# --------------------------------------------------------------------------- #
def compute_sortino(returns: list[float], rf: float = 0.0, min_periods: int = SORTINO_MIN_PERIODS) -> dict:
    """Sortino ratio using *downside-only* deviation.

    ``Sortino = (mean(returns) - rf) / downside_deviation`` where
    ``downside_deviation`` is the standard deviation of the strictly-negative
    returns only.

    Returns ``{"value", "confidence", "n"}``:

    - ``len(returns) < min_periods`` -> ``value=None``,
      ``confidence="insufficient_data"``.
    - no negative returns at all -> ``value=None`` (nothing to penalise; not
      enough information to compute a meaningful downside-risk ratio).
    - otherwise the float ratio, with a sample-size confidence label.
    """
    returns = list(returns or [])
    n = len(returns)
    if n < min_periods:
        return {"value": None, "confidence": "insufficient_data", "n": n}

    downside = [r for r in returns if r < 0]
    if not downside:
        return {"value": None, "confidence": _confidence(n), "n": n}

    dd = _pop_std(downside)
    if dd <= 0:
        # A single negative point (or all-equal negatives) -> no usable spread.
        return {"value": None, "confidence": _confidence(n), "n": n}

    value = (_mean(returns) - rf) / dd
    return {"value": value, "confidence": _confidence(n), "n": n}


def compute_sharpe_with_ci(returns: list[float], rf: float = 0.0) -> dict:
    """Sharpe ratio with a bootstrap confidence interval.

    Returns ``{"value", "ci_lower", "ci_upper", "confidence", "n"}`` and, when
    ``n < 30``, an extra ``"low_sample_warning": True`` flag.

    - ``n < BOOTSTRAP_MIN_N`` (10) -> ``value=None`` and ``ci_*=None`` (too few
      points to bootstrap anything trustworthy).
    - otherwise the point Sharpe plus a 95% percentile-bootstrap CI computed
      over :data:`BOOTSTRAP_ITERS` resamples (with replacement).

    The bootstrap uses the stdlib :mod:`random` module. Seed externally for
    reproducible intervals.
    """
    returns = list(returns or [])
    n = len(returns)
    low_warn = n < MIN_RELIABLE_SAMPLES

    if n < BOOTSTRAP_MIN_N:
        out = {
            "value": None,
            "ci_lower": None,
            "ci_upper": None,
            "confidence": _confidence(n),
            "n": n,
        }
        if low_warn:
            out["low_sample_warning"] = True
        return out

    point = _sharpe_point(returns, rf)

    samples: list[float] = []
    for _ in range(BOOTSTRAP_ITERS):
        resample = [random.choice(returns) for _ in range(n)]
        s = _sharpe_point(resample, rf)
        if s is not None:
            samples.append(s)

    if samples:
        samples.sort()
        ci_lower = _percentile(samples, 2.5)
        ci_upper = _percentile(samples, 97.5)
    else:
        ci_lower = ci_upper = None

    out = {
        "value": point,
        "ci_lower": ci_lower,
        "ci_upper": ci_upper,
        "confidence": _confidence(n),
        "n": n,
    }
    if low_warn:
        out["low_sample_warning"] = True
    return out


def compute_calmar(equity_curve: list, period_days: float) -> dict:
    """Calmar ratio: annualised return divided by absolute max drawdown.

    ``equity_curve`` may be a list of ``{"equity": ...}`` dicts or raw numbers.
    ``period_days`` is the calendar span the curve covers (used to annualise).

    Returns ``{"value", "confidence", "n", "max_drawdown_pct",
    "annualized_return_pct"}``. ``value=None`` when the drawdown is zero (the
    ratio is undefined) or when the curve is too short to measure a return.
    """
    values = _equity_values(equity_curve)
    n = len(values)
    if n < 2 or values[0] <= 0 or not period_days or period_days <= 0:
        return {
            "value": None,
            "confidence": _confidence(n),
            "n": n,
            "max_drawdown_pct": None,
            "annualized_return_pct": None,
        }

    total_return = values[-1] / values[0] - 1.0
    annualized_return = (1.0 + total_return) ** (365.0 / period_days) - 1.0

    max_dd = _max_drawdown_frac(values)
    if max_dd <= 0:
        return {
            "value": None,
            "confidence": _confidence(n),
            "n": n,
            "max_drawdown_pct": 0.0,
            "annualized_return_pct": annualized_return * 100.0,
        }

    return {
        "value": annualized_return / max_dd,
        "confidence": _confidence(n),
        "n": n,
        "max_drawdown_pct": max_dd * 100.0,
        "annualized_return_pct": annualized_return * 100.0,
    }


def min_sample_check(n: int, metric_name: str) -> str:
    """Return a LOW CONFIDENCE warning string when ``n < 30``, else ``""``.

    Example::

        >>> min_sample_check(20, "Sharpe")
        'Sharpe (n=20): LOW CONFIDENCE — нужно ≥30 точек для надёжной оценки'
    """
    if n < MIN_RELIABLE_SAMPLES:
        return (
            f"{metric_name} (n={n}): LOW CONFIDENCE — "
            f"нужно ≥{MIN_RELIABLE_SAMPLES} точек для надёжной оценки"
        )
    return ""


def label_metric(value, metric_name: str) -> str:
    """One-line labelled metric with a ✓ (trustworthy) or ⚠ (low-confidence) flag.

    ``value`` may be a bare float or one of the metric dicts returned by the
    functions above (in which case ``n`` and any ``low_sample_warning`` are read
    from it). Examples::

        label_metric({"value": 1.23, "n": 40}, "Sortino")
            -> 'Sortino: 1.23 ✓'
        label_metric({"value": -5.38, "n": 20}, "Sharpe")
            -> 'Sharpe: -5.38 ⚠ (LOW CONFIDENCE, n=20)'
        label_metric(None, "Sortino")
            -> 'Sortino: N/A (insufficient data)'
    """
    n: int | None = None
    low_warn = False
    val = value
    if isinstance(value, dict):
        val = value.get("value")
        n = value.get("n")
        conf = value.get("confidence")
        low_warn = bool(value.get("low_sample_warning")) or conf in ("low", "insufficient_data")
        if isinstance(n, int) and n < MIN_RELIABLE_SAMPLES:
            low_warn = True

    if val is None:
        return f"{metric_name}: N/A (insufficient data)"

    try:
        num = f"{float(val):.2f}"
    except (TypeError, ValueError):
        return f"{metric_name}: N/A (insufficient data)"

    if low_warn:
        suffix = f" ⚠ (LOW CONFIDENCE, n={n})" if n is not None else " ⚠ (LOW CONFIDENCE)"
        return f"{metric_name}: {num}{suffix}"
    return f"{metric_name}: {num} ✓"
