"""
Live APY Covariance Estimator (FEAT-007 Phase 1)
=================================================

Pure-Python rolling-window estimator for per-protocol APY volatility,
covariance and correlation, computed from the JSON store written by
spa_core.analytics.apy_tracker.APYTracker.

Phase 1 (this module) is a SCAFFOLD: it exposes a self-contained
``CovarianceEstimator`` class but is NOT yet wired into the production
allocation pipeline.  Existing call-sites (Markowitz, Kelly sizing) keep
their synthetic CV=10% covariance assumption — guaranteeing byte-identical
behaviour for the v3.x execution stack.

Phase 2 will plug ``CovarianceEstimator.compute_covariance_matrix()`` into
``optimization/markowitz.py`` behind an env flag (SPA_LIVE_COVARIANCE=1).
Phase 3 will wire ``compute_volatility()`` into a new ``dynamic_kelly()``
helper that replaces the static volatility_pct param of ``kelly_fraction``.

Design constraints
------------------
* Pure stdlib (json, math, statistics, datetime) — no numpy/scipy.
* Read-only over ``data/apy_history.json`` — never mutates the tracker store.
* Production-safe fallbacks: insufficient data → return SYNTHETIC proxy
  (same value the existing Markowitz code uses) so the pipeline never
  crashes when a protocol is first added.
* Deterministic: identical input series → identical output values.
* Annualised standard deviations are expressed in PERCENTAGE POINTS
  (e.g. an APY series fluctuating between 4.0% and 6.0% over the window
  yields σ ≈ 0.5pp), matching how Markowitz already interprets σ_i.

Mathematical notes
------------------
Variance is computed with Bessel's correction (sample variance, divisor
n-1) to match standard statistical practice; the existing synthetic proxy
is ``σ_i = apy_i * 0.10`` (10% CV), which we use as the fallback bound.

Correlation is the Pearson coefficient on the daily APY series after
optional time-alignment (intersection of timestamps).  We do NOT use rank
correlation — DeFi yields are roughly log-normal and the linear estimator
is the right input for Markowitz mean-variance.

The covariance entry between protocols i and j is reconstructed as
σ_i * σ_j * ρ_ij so consumers can rebuild the matrix without re-walking
the raw history.

Public API
----------
``CovarianceEstimator(history_file: str = APY_HISTORY_FILE)``

Methods:
    - ``protocols() -> list[str]``
    - ``compute_volatility(protocol_key: str, window_days: int = 90) -> float``
    - ``compute_correlation(key_i: str, key_j: str, window_days: int = 90) -> float``
    - ``compute_covariance_matrix(window_days: int = 90, protocols: list[str] | None = None) -> dict[str, dict[str, float]]``
    - ``compute_correlation_matrix(window_days: int = 90, protocols: list[str] | None = None) -> dict[str, dict[str, float]]``
    - ``summary(window_days: int = 90) -> dict``  (for JSON export / dashboard)

All methods are O(window_days * n_protocols^2) at worst and run in a few
milliseconds even with the full 7-protocol whitelist over 90 days.
"""
from __future__ import annotations

import json
import math
import statistics
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

# ──────────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────────

APY_HISTORY_FILE = "data/apy_history.json"

# Default rolling window — matches APYTracker.MAX_HISTORY_DAYS so the
# longest meaningful window is the full retained history.
DEFAULT_WINDOW_DAYS = 90

# Minimum number of observations required before we trust the live
# estimator; below this threshold the synthetic CV proxy is returned.
# Two weeks is the smallest window where daily noise averages out.
MIN_OBSERVATIONS = 7

# Synthetic fallback CV — kept in lock-step with markowitz._APY_CV so a
# Phase-2 cutover changes only the *source* of σ, never its magnitude on
# day one.
SYNTHETIC_APY_CV = 0.10

# Fallback correlation values mirror markowitz._SAME_TIER_CORR and
# _CROSS_TIER_CORR.  They are returned when ρ cannot be estimated (e.g.
# series do not overlap by at least MIN_OBSERVATIONS points).
SYNTHETIC_SAME_TIER_CORR = 0.6
SYNTHETIC_CROSS_TIER_CORR = 0.2


# ──────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────


def _parse_iso(ts: str) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp; return None if the string is malformed."""
    if not isinstance(ts, str):
        return None
    try:
        # ``datetime.fromisoformat`` doesn't accept the trailing ``Z`` in
        # 3.9 / 3.10; normalise so existing APYTracker entries (which
        # always carry timezone offsets) parse cleanly.
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        return datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return None


def _entries_within_window(
    entries: list[dict], cutoff: datetime
) -> list[dict]:
    """Return only entries whose timestamp is ≥ cutoff."""
    out: list[dict] = []
    for e in entries:
        ts = _parse_iso(e.get("ts", ""))
        if ts is None:
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if ts >= cutoff:
            out.append({"ts": ts, "apy": float(e.get("apy", 0.0))})
    return out


def _align_series(
    series_a: list[dict], series_b: list[dict]
) -> tuple[list[float], list[float]]:
    """
    Time-align two APY series on identical timestamps.

    Returns parallel arrays (a_apys, b_apys) with len(a_apys) == len(b_apys).
    Entries that don't have a matching timestamp on the other side are
    dropped — this is the conservative choice: better to drop than to
    interpolate noise.
    """
    by_ts_a = {e["ts"]: e["apy"] for e in series_a}
    by_ts_b = {e["ts"]: e["apy"] for e in series_b}
    common = sorted(set(by_ts_a.keys()) & set(by_ts_b.keys()))
    return (
        [by_ts_a[t] for t in common],
        [by_ts_b[t] for t in common],
    )


def _safe_stdev(values: list[float]) -> float:
    """
    Sample standard deviation with Bessel's correction.

    Returns 0.0 if fewer than 2 observations are supplied (matches the
    behaviour of statistics.pstdev for the n=1 case while still using the
    unbiased estimator when we have enough data).
    """
    if len(values) < 2:
        return 0.0
    try:
        return statistics.stdev(values)
    except statistics.StatisticsError:
        return 0.0


def _safe_pearson(xs: list[float], ys: list[float]) -> float:
    """
    Pearson correlation coefficient — pure stdlib.

    Returns 0.0 when:
      * either series has fewer than MIN_OBSERVATIONS points
      * either series has zero variance (constant series)

    Result is clamped to [-1.0, 1.0] to guard against tiny float drift.
    """
    n = len(xs)
    if n < MIN_OBSERVATIONS or n != len(ys):
        return 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    num = 0.0
    sxx = 0.0
    syy = 0.0
    for x, y in zip(xs, ys):
        dx = x - mx
        dy = y - my
        num += dx * dy
        sxx += dx * dx
        syy += dy * dy
    denom = math.sqrt(sxx * syy)
    if denom == 0.0:
        return 0.0
    rho = num / denom
    return max(-1.0, min(1.0, rho))


# ──────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────


class CovarianceEstimator:
    """
    Rolling-window APY covariance estimator over APYTracker history.

    The estimator is stateless w.r.t. its inputs: each call re-reads (or
    re-uses, see ``preloaded``) the snapshot it was constructed with.
    This makes it safe to instantiate per-cycle in the export pipeline.

    Parameters
    ----------
    history_file : str
        Path to the APYTracker JSON store.  Defaults to data/apy_history.json.

    preloaded : dict | None
        Pre-parsed history payload (same schema as APYTracker._data).  If
        supplied, ``history_file`` is ignored.  This lets unit tests inject
        synthetic series without touching disk.
    """

    def __init__(
        self,
        history_file: str = APY_HISTORY_FILE,
        preloaded: Optional[dict] = None,
    ):
        if preloaded is not None:
            self._data = preloaded
        else:
            self._data = self._load(history_file)

    # ── loader ────────────────────────────────────────────────────────

    @staticmethod
    def _load(history_file: str) -> dict:
        p = Path(history_file)
        if not p.exists():
            return {"protocol_history": {}, "last_updated": None}
        try:
            return json.loads(p.read_text())
        except (json.JSONDecodeError, OSError):
            return {"protocol_history": {}, "last_updated": None}

    # ── basic accessors ───────────────────────────────────────────────

    def protocols(self) -> list[str]:
        """Return the list of protocol keys present in the history store."""
        return sorted(self._data.get("protocol_history", {}).keys())

    def _series(self, protocol_key: str) -> list[dict]:
        """Raw (un-parsed) entries for a single protocol key."""
        return self._data.get("protocol_history", {}).get(protocol_key, [])

    def _window_series(
        self, protocol_key: str, window_days: int
    ) -> list[dict]:
        """
        Parse + filter a protocol's series to the rolling window.

        Returns a list of {ts: datetime, apy: float} sorted ascending.
        """
        raw = self._series(protocol_key)
        if not raw:
            return []
        cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)
        parsed = _entries_within_window(raw, cutoff)
        parsed.sort(key=lambda e: e["ts"])
        return parsed

    # ── core estimators ───────────────────────────────────────────────

    def compute_volatility(
        self,
        protocol_key: str,
        window_days: int = DEFAULT_WINDOW_DAYS,
        synthetic_apy: Optional[float] = None,
    ) -> float:
        """
        Sample APY standard deviation in PERCENTAGE POINTS over the rolling
        window.

        Falls back to ``synthetic_apy * SYNTHETIC_APY_CV`` (the existing
        markowitz proxy) when fewer than MIN_OBSERVATIONS data points
        are available.  If ``synthetic_apy`` is None and the live estimate
        cannot be produced, returns 0.0 — callers MUST treat 0.0 as "no
        estimate available" and apply their own fallback.
        """
        series = self._window_series(protocol_key, window_days)
        if len(series) >= MIN_OBSERVATIONS:
            apys = [e["apy"] for e in series]
            return _safe_stdev(apys)

        # Fallback to the synthetic proxy
        if synthetic_apy is not None and synthetic_apy > 0:
            return float(synthetic_apy) * SYNTHETIC_APY_CV
        return 0.0

    def compute_correlation(
        self,
        key_i: str,
        key_j: str,
        window_days: int = DEFAULT_WINDOW_DAYS,
        same_tier: Optional[bool] = None,
    ) -> float:
        """
        Pearson correlation between two protocols' APY series in the window.

        Self-correlation always returns 1.0 exactly.  When fewer than
        MIN_OBSERVATIONS overlapping data points exist, falls back to the
        synthetic tier-based correlation (0.6 same-tier, 0.2 cross-tier).
        Pass ``same_tier=None`` if no tier context is available and a
        neutral 0.0 fallback should be used instead.
        """
        if key_i == key_j:
            return 1.0

        series_i = self._window_series(key_i, window_days)
        series_j = self._window_series(key_j, window_days)

        xs, ys = _align_series(series_i, series_j)
        if len(xs) >= MIN_OBSERVATIONS:
            return _safe_pearson(xs, ys)

        # Synthetic fallback
        if same_tier is True:
            return SYNTHETIC_SAME_TIER_CORR
        if same_tier is False:
            return SYNTHETIC_CROSS_TIER_CORR
        return 0.0

    def compute_covariance_matrix(
        self,
        window_days: int = DEFAULT_WINDOW_DAYS,
        protocols: Optional[list[str]] = None,
        tiers: Optional[dict[str, str]] = None,
        synthetic_apys: Optional[dict[str, float]] = None,
    ) -> dict[str, dict[str, float]]:
        """
        Full covariance matrix Cov[i][j] = σ_i * σ_j * ρ_ij.

        Parameters
        ----------
        window_days : rolling window length (default 90).
        protocols   : restrict to this subset; defaults to every protocol
                      with at least one observation in the store.
        tiers       : optional {protocol_key: 'T1'|'T2'} mapping used by
                      the correlation fallback when overlap < MIN_OBSERVATIONS.
        synthetic_apys : optional {protocol_key: current_apy_pct} mapping
                      used by the volatility fallback when the protocol's
                      history is shorter than MIN_OBSERVATIONS.

        Returns
        -------
        nested dict suitable for JSON serialisation.  Symmetric:
        matrix[i][j] == matrix[j][i].
        """
        keys = sorted(protocols) if protocols else self.protocols()
        tiers = tiers or {}
        synthetic_apys = synthetic_apys or {}

        # Pre-compute volatilities once per protocol
        sigmas = {
            k: self.compute_volatility(
                k, window_days, synthetic_apy=synthetic_apys.get(k)
            )
            for k in keys
        }

        out: dict[str, dict[str, float]] = {}
        for i, k_i in enumerate(keys):
            row: dict[str, float] = {}
            for j, k_j in enumerate(keys):
                if k_i == k_j:
                    row[k_j] = sigmas[k_i] ** 2  # variance on diagonal
                    continue
                if j < i:
                    # Symmetry — reuse the upper triangle we just built
                    row[k_j] = out[k_j][k_i]
                    continue
                t_i = tiers.get(k_i)
                t_j = tiers.get(k_j)
                same_tier = (t_i == t_j) if (t_i and t_j) else None
                rho = self.compute_correlation(
                    k_i, k_j, window_days, same_tier=same_tier
                )
                row[k_j] = sigmas[k_i] * sigmas[k_j] * rho
            out[k_i] = row
        return out

    def compute_correlation_matrix(
        self,
        window_days: int = DEFAULT_WINDOW_DAYS,
        protocols: Optional[list[str]] = None,
        tiers: Optional[dict[str, str]] = None,
    ) -> dict[str, dict[str, float]]:
        """
        Pearson correlation matrix.  Diagonal is exactly 1.0.

        ``tiers`` enables the same synthetic-fallback behaviour as
        ``compute_correlation``.
        """
        keys = sorted(protocols) if protocols else self.protocols()
        tiers = tiers or {}
        out: dict[str, dict[str, float]] = {}
        for i, k_i in enumerate(keys):
            row: dict[str, float] = {}
            for j, k_j in enumerate(keys):
                if k_i == k_j:
                    row[k_j] = 1.0
                    continue
                if j < i:
                    row[k_j] = out[k_j][k_i]
                    continue
                t_i = tiers.get(k_i)
                t_j = tiers.get(k_j)
                same_tier = (t_i == t_j) if (t_i and t_j) else None
                row[k_j] = self.compute_correlation(
                    k_i, k_j, window_days, same_tier=same_tier
                )
            out[k_i] = row
        return out

    # ── exporter ──────────────────────────────────────────────────────

    def summary(
        self,
        window_days: int = DEFAULT_WINDOW_DAYS,
        protocols: Optional[list[str]] = None,
    ) -> dict:
        """
        Lightweight JSON-ready summary for dashboards.

        Returns:
            {
                "window_days": 90,
                "computed_at": "<utc-iso>",
                "min_observations": 7,
                "protocols": {
                    "<key>": {
                        "n_obs": int,
                        "mean_apy": float,
                        "volatility_pp": float,
                        "fallback": bool,   # True if synthetic was used
                    }, ...
                }
            }
        """
        keys = sorted(protocols) if protocols else self.protocols()
        out_protos: dict[str, dict] = {}
        for k in keys:
            series = self._window_series(k, window_days)
            n = len(series)
            apys = [e["apy"] for e in series]
            mean_apy = sum(apys) / n if n else 0.0
            vol = _safe_stdev(apys) if n >= MIN_OBSERVATIONS else 0.0
            out_protos[k] = {
                "n_obs": n,
                "mean_apy": round(mean_apy, 4),
                "volatility_pp": round(vol, 4),
                "fallback": n < MIN_OBSERVATIONS,
            }
        return {
            "window_days": window_days,
            "computed_at": datetime.now(timezone.utc).isoformat(),
            "min_observations": MIN_OBSERVATIONS,
            "protocols": out_protos,
        }
