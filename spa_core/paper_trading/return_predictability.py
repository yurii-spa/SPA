"""
Paper-trading return predictability & complexity diagnostics (SPA-V407).

Read-only analytics layer that sits *on top of* the daily equity curve from
``equity_curve.py`` (SPA-V379), operating on the realised daily-return series.

How this differs from its analytics siblings (the NEW angle):
    The existing siblings already cover *linear* dependence and *distributional*
    shape exhaustively:

        serial_dependence.py     ACF, variance-ratio, Hurst, runs test,
                                 Ljung-Box — i.e. *linear* autocorrelation and
                                 long-memory.
        return_distribution.py   empirical moments, percentiles, histogram,
                                 historical VaR/CVaR.
        distribution_normality.py  Jarque-Bera normality + Cornish-Fisher
                                 parametric tails.
        probabilistic_sharpe.py  Sharpe-ratio statistical significance.
        linearity_analytics.py   OLS log-equity trend / R-squared.

    Every one of those measures *linear* structure or *distribution shape*.
    None of them asks the **information-theoretic** question: *how much
    structure / nonlinear predictability actually lives in the daily-return
    sequence, and how complex is it?* That is this module's exclusive angle.

    Concretely, all from scratch (no library implements these here):

        shannon_entropy        histogram (binned) Shannon entropy of the return
                               *values* — how spread vs concentrated the
                               magnitudes are.
        sign_entropy           entropy of the up/down/flat directional symbols —
                               directional balance.
        permutation_entropy    Bandt-Pompe ordinal-pattern entropy (embedding
                               dimension m) — nonlinear *temporal* complexity
                               that ACF cannot see; a monotone run collapses to
                               one ordinal pattern (PE≈0), white noise → PE≈1.
        sample_entropy         SampEn(m=2, r) — regularity / self-similarity of
                               the sequence; low = regular/predictable.
        approximate_entropy    ApEn(m=2, r) — the classic (biased, self-match
                               inclusive) regularity statistic.
        predictability_score   1 - normalized permutation entropy, in [0,1],
                               with an A/B/C/D grade and a short verdict.

    None of these reduce to an autocorrelation or a moment, so this report does
    not overlap with any sibling — it is the nonlinear / complexity complement.

Design notes / safety:
  * Pure stdlib (json, math, os, statistics, datetime, pathlib, logging,
    argparse) — mirrors the no-external-dependency style of
    distribution_normality.py / return_distribution.py. **No numpy / scipy /
    pandas / web3 / requests, no network.** Every entropy is implemented from
    scratch on Python lists.
  * STRICTLY READ-ONLY w.r.t. trading state. Never touches the execution path,
    risk policy, wallets, or any money-moving code. It only reads
    pnl_history.json (via equity_curve.build_daily_equity_curve) and writes a
    derived report JSON.
  * NOT a feed-health monitor — does not touch the SPA-BL-011 frozen
    feed-health domain. Pure portfolio-performance analytics.
  * Returns series is ``curve[1:]`` (the seed day's 0.0 return is excluded),
    matching distribution_normality.py / return_distribution.py exactly.
  * Defensive: degenerate inputs (0/1 day, flat / zero-variance series, too few
    embedding windows) never raise — undefined statistics return ``None`` and
    the schema stays stable.

Interpretation:
    High normalized entropy  ≈ unpredictable / random-walk-like.
    Low  normalized entropy  ≈ concentrated / structured / predictable.
    predictability_score = 1 - permutation_entropy_normalized, so a higher
    score means a more *structured* (less random) return sequence.

CLI::

    python -m spa_core.paper_trading.return_predictability
    python -m spa_core.paper_trading.return_predictability --history data/pnl_history.json \\
        --out data/return_predictability.json --embed-dim 3
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import statistics
from datetime import datetime, timezone
from pathlib import Path

from spa_core.paper_trading.equity_curve import (
    DEFAULT_HISTORY_PATH,
    build_daily_equity_curve,
    load_pnl_history,
)
from spa_core.utils.atomic import atomic_save

log = logging.getLogger("spa.paper_trading.return_predictability")

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_PATH = _PROJECT_ROOT / "data" / "return_predictability.json"

# Defaults for the embedding-based statistics.
DEFAULT_EMBED_DIM = 3   # permutation-entropy ordinal-pattern length
SAMPEN_M = 2            # SampEn / ApEn template length
SAMPEN_R_FACTOR = 0.2   # tolerance r = factor * population stdev


# ─── Daily-return series (identical convention to distribution_normality.py) ──

def _daily_returns(curve: list[dict]) -> list[float]:
    """Realised daily returns (%) — every bar after the seed day 1.

    Day 1's ``daily_return_pct`` is a 0.0 seed (no prior close), so it is
    excluded to avoid biasing the series toward zero — matching
    distribution_normality.py / return_distribution.py exactly.
    """
    return [bar["daily_return_pct"] for bar in curve[1:]]


# ─── Shannon entropy of a probability distribution ────────────────────────────

def _entropy_from_counts(counts: list[int]) -> tuple[float, int]:
    """Shannon entropy (bits) of a list of non-negative counts.

    Returns ``(H, num_nonempty)`` where ``H = -sum p*log2(p)`` taken over the
    bins with a positive count and ``num_nonempty`` is how many bins were
    populated. Empty input → ``(0.0, 0)``.
    """
    total = sum(counts)
    if total <= 0:
        return 0.0, 0
    h = 0.0
    nonempty = 0
    for c in counts:
        if c > 0:
            nonempty += 1
            p = c / total
            h -= p * math.log2(p)
    return h, nonempty


def _shannon_entropy(values: list[float], num_bins: int | None = None) -> dict:
    """Histogram (binned) Shannon entropy of the return *values*.

    The returns are histogrammed into ``num_bins`` equal-width bins spanning
    ``[min, max]`` (default bins = ``max(2, min(10, round(sqrt(n))))``). Returns
    a dict with the entropy in bits, the count of non-empty bins, the bin count
    used and the normalized entropy ``H / log2(num_nonempty_bins)`` in [0, 1]
    (``None`` when fewer than 2 non-empty bins, i.e. normalization undefined).

    Degenerate-safe: empty series → all-None; a flat (zero-range) series falls
    into a single bin → entropy 0, normalized None.
    """
    base = {
        "bits": None,
        "normalized": None,
        "num_bins": None,
        "num_nonempty_bins": None,
    }
    n = len(values)
    if n == 0:
        return base
    if num_bins is None:
        num_bins = max(2, min(10, round(math.sqrt(n))))
    lo = min(values)
    hi = max(values)
    if hi <= lo:
        # Flat / single-valued series: one occupied bin, no spread.
        return {
            "bits": 0.0,
            "normalized": None,
            "num_bins": num_bins,
            "num_nonempty_bins": 1,
        }
    width = (hi - lo) / num_bins
    counts = [0] * num_bins
    for v in values:
        idx = int((v - lo) / width)
        if idx >= num_bins:  # the maximum lands exactly on the upper edge
            idx = num_bins - 1
        counts[idx] += 1
    h, nonempty = _entropy_from_counts(counts)
    normalized = h / math.log2(nonempty) if nonempty >= 2 else None
    return {
        "bits": round(h, 6),
        "normalized": None if normalized is None else round(normalized, 6),
        "num_bins": num_bins,
        "num_nonempty_bins": nonempty,
    }


# ─── Sign (directional) entropy ───────────────────────────────────────────────

def _sign_entropy(values: list[float]) -> dict:
    """Entropy over the {up, down, flat} directional symbols.

    Each return is classified as up (>0), down (<0) or flat (==0); the Shannon
    entropy (bits) is taken over those class counts and normalized by
    ``log2(num distinct classes present)`` (``None`` when <2 classes present).
    Measures directional balance: 50/50 up/down → normalized ≈ 1.
    """
    base = {
        "bits": None,
        "normalized": None,
        "up": 0,
        "down": 0,
        "flat": 0,
    }
    n = len(values)
    if n == 0:
        return base
    up = sum(1 for v in values if v > 0)
    down = sum(1 for v in values if v < 0)
    flat = sum(1 for v in values if v == 0)
    counts = [c for c in (up, down, flat) if c > 0]
    h, nonempty = _entropy_from_counts(counts)
    normalized = h / math.log2(nonempty) if nonempty >= 2 else None
    return {
        "bits": round(h, 6),
        "normalized": None if normalized is None else round(normalized, 6),
        "up": up,
        "down": down,
        "flat": flat,
    }


# ─── Permutation entropy (Bandt-Pompe) ────────────────────────────────────────

def _permutation_entropy(values: list[float], embed_dim: int = DEFAULT_EMBED_DIM) -> dict:
    """Bandt-Pompe permutation entropy with embedding dimension ``m``.

    For each window of ``m`` consecutive returns (unit time delay) the ordinal
    pattern — the tuple of argsort ranks — is the symbol. The permutation
    entropy is the Shannon entropy (bits) over the distribution of the ``m!``
    possible ordinal patterns; normalized = ``PE / log2(m!)`` in [0, 1].

    A monotone-increasing (or decreasing) run produces a single ordinal pattern
    → PE ≈ 0; a random series visits all patterns near-uniformly → PE ≈ 1.

    Requires at least 2 windows for a meaningful distribution (``n >= m + 1``);
    fewer → ``None`` fields (schema stable). ``embed_dim`` is clamped to >= 2.
    """
    m = max(2, int(embed_dim))
    base = {
        "bits": None,
        "normalized": None,
        "embed_dim": m,
        "num_windows": 0,
    }
    n = len(values)
    num_windows = n - m + 1
    if num_windows < 2:
        return base

    pattern_counts: dict[tuple[int, ...], int] = {}
    for i in range(num_windows):
        window = values[i:i + m]
        # Ordinal pattern = argsort ranks (ties broken by original index, the
        # standard Bandt-Pompe convention).
        order = tuple(sorted(range(m), key=lambda k: (window[k], k)))
        pattern_counts[order] = pattern_counts.get(order, 0) + 1

    h, _nonempty = _entropy_from_counts(list(pattern_counts.values()))
    max_h = math.log2(math.factorial(m))
    normalized = h / max_h if max_h > 0 else None
    return {
        "bits": round(h, 6),
        "normalized": None if normalized is None else round(normalized, 6),
        "embed_dim": m,
        "num_windows": num_windows,
    }


# ─── Sample entropy (SampEn) ──────────────────────────────────────────────────

def _chebyshev_within(a: list[float], b: list[float], r: float) -> bool:
    """True if the Chebyshev (max-abs) distance between vectors a, b is <= r."""
    for x, y in zip(a, b):
        if abs(x - y) > r:
            return False
    return True


def _count_template_matches(values: list[float], m: int, r: float) -> int:
    """Count ordered template-pair matches of length ``m`` within tolerance r.

    Self-matches (i == j) are excluded and each unordered pair is counted once
    per ordered direction's i<j convention here (i < j), i.e. the raw match
    count B (or A for length m+1) used in the SampEn ratio.
    """
    templates = [values[i:i + m] for i in range(len(values) - m + 1)]
    count = 0
    n_t = len(templates)
    for i in range(n_t):
        ti = templates[i]
        for j in range(i + 1, n_t):
            if _chebyshev_within(ti, templates[j], r):
                count += 1
    return count


def _sample_entropy(values: list[float], m: int = SAMPEN_M,
                    r: float | None = None) -> dict:
    """Sample entropy SampEn(m, r) = -ln(A / B).

    B = number of template-pair matches of length ``m`` within Chebyshev
    tolerance ``r``; A = the same for length ``m + 1``; self-matches excluded.
    ``r`` defaults to ``0.2 * pstdev(returns)``. Lower SampEn = more
    regular/predictable, higher = more random.

    Returns ``value = None`` (with the other fields populated where possible)
    when undefined: too few points, zero tolerance (flat series), or
    ``A == 0``/``B == 0`` (ratio undefined). Never raises.
    """
    n = len(values)
    if r is None:
        sd = statistics.pstdev(values) if n >= 1 else 0.0
        r = SAMPEN_R_FACTOR * sd
    base = {
        "value": None,
        "m": m,
        "r": round(r, 6),
        "B": None,
        "A": None,
    }
    # Need at least m+2 points so there are >= 2 templates of length m+1.
    if n < m + 2 or r <= 0:
        return base
    b = _count_template_matches(values, m, r)
    a = _count_template_matches(values, m + 1, r)
    base["B"] = b
    base["A"] = a
    if b == 0 or a == 0:
        return base
    base["value"] = round(-math.log(a / b), 6)
    return base


# ─── Approximate entropy (ApEn) ───────────────────────────────────────────────

def _phi(values: list[float], m: int, r: float) -> float | None:
    """Phi_m for ApEn: mean over templates of ln(fraction of matches).

    Self-matches ARE included (the canonical ApEn definition), so every
    template matches at least itself and the log is always finite. Returns
    ``None`` if there are no templates of length ``m``.
    """
    templates = [values[i:i + m] for i in range(len(values) - m + 1)]
    n_t = len(templates)
    if n_t <= 0:
        return None
    total = 0.0
    for i in range(n_t):
        matches = 0
        ti = templates[i]
        for j in range(n_t):
            if _chebyshev_within(ti, templates[j], r):
                matches += 1
        total += math.log(matches / n_t)
    return total / n_t


def _approx_entropy(values: list[float], m: int = SAMPEN_M,
                    r: float | None = None) -> dict:
    """Approximate entropy ApEn(m, r) = Phi_m - Phi_{m+1}.

    Canonical (Pincus) definition with self-matches included. ``r`` defaults to
    ``0.2 * pstdev(returns)``. Lower ApEn = more regular; returns
    ``value = None`` when undefined (too few points, zero tolerance). Never
    raises.
    """
    n = len(values)
    if r is None:
        sd = statistics.pstdev(values) if n >= 1 else 0.0
        r = SAMPEN_R_FACTOR * sd
    base = {
        "value": None,
        "m": m,
        "r": round(r, 6),
    }
    # Need at least m+1 points so Phi_{m+1} has >= 1 template.
    if n < m + 1 or r <= 0:
        return base
    phi_m = _phi(values, m, r)
    phi_m1 = _phi(values, m + 1, r)
    if phi_m is None or phi_m1 is None:
        return base
    base["value"] = round(phi_m - phi_m1, 6)
    return base


# ─── Predictability grade & verdict heuristics ────────────────────────────────

def _predictability_grade(score: float | None) -> str | None:
    """A/B/C/D grade from the predictability score in [0, 1].

    The score is ``1 - normalized permutation entropy``: higher = more
    structured / predictable, lower = more random-walk-like. Thresholds:
        A : score >= 0.66  (highly structured / predictable)
        B : score >= 0.40  (moderately structured)
        C : score >= 0.20  (weakly structured)
        D : score <  0.20  (random-walk-like)
    Returns ``None`` when the score is undefined.
    """
    if score is None:
        return None
    if score >= 0.66:
        return "A"
    if score >= 0.40:
        return "B"
    if score >= 0.20:
        return "C"
    return "D"


def _verdict(score: float | None) -> str:
    """Short human label summarising the predictability diagnosis.

    "insufficient_data"  → score undefined (too little / degenerate data).
    "structured"         → score >= 0.66 (grade A).
    "weakly_structured"  → 0.20 <= score < 0.66 (grades B/C).
    "random_walk_like"   → score < 0.20 (grade D).
    """
    if score is None:
        return "insufficient_data"
    if score >= 0.66:
        return "structured"
    if score >= 0.20:
        return "weakly_structured"
    return "random_walk_like"


# ─── Top-level compute ────────────────────────────────────────────────────────

def compute_predictability(curve: list[dict], embed_dim: int = DEFAULT_EMBED_DIM) -> dict:
    """Compute information-theoretic predictability metrics from a daily curve.

    Args:
        curve: list of daily bars as produced by
            ``equity_curve.build_daily_equity_curve``.
        embed_dim: permutation-entropy embedding dimension m (>= 2).

    Returns:
        A stable-schema metrics dict. Statistics that are undefined for the
        given data (too few days, zero variance, too few windows) are ``None``;
        the function never raises.
    """
    m = max(2, int(embed_dim))

    base = {
        "count":                          0,
        "num_days":                       0,
        "first_date":                     None,
        "last_date":                      None,
        "mean_pct":                       None,
        "stdev_pct":                      None,
        "embed_dim":                      m,
        "sampen_m":                       SAMPEN_M,
        "sampen_r":                       None,
        "shannon_entropy_bits":           None,
        "shannon_entropy_normalized":     None,
        "sign_entropy_bits":              None,
        "sign_entropy_normalized":        None,
        "permutation_entropy":            None,
        "permutation_entropy_normalized": None,
        "sample_entropy":                 None,
        "approximate_entropy":            None,
        "predictability_score":           None,
        "predictability_grade":           None,
        "verdict":                        "insufficient_data",
        "execution_mode":                 "read_only_simulation",
    }

    returns = _daily_returns(curve)
    n = len(returns)
    if n == 0:
        return base

    dates = [bar.get("date") for bar in curve if bar.get("date") is not None]
    first_date = dates[0] if dates else None
    last_date = dates[-1] if dates else None

    mean = statistics.fmean(returns)
    stdev = statistics.pstdev(returns) if n >= 1 else 0.0
    sampen_r = SAMPEN_R_FACTOR * stdev

    shannon = _shannon_entropy(returns)
    sign = _sign_entropy(returns)
    perm = _permutation_entropy(returns, embed_dim=m)
    sampen = _sample_entropy(returns, m=SAMPEN_M, r=sampen_r)
    apen = _approx_entropy(returns, m=SAMPEN_M, r=sampen_r)

    perm_norm = perm["normalized"]
    if perm_norm is not None:
        score = 1.0 - perm_norm
        # Numerical guard so the score stays inside [0, 1].
        score = max(0.0, min(1.0, score))
        score = round(score, 6)
    else:
        score = None

    return {
        "count":                          n,
        "num_days":                       len(curve),
        "first_date":                     first_date,
        "last_date":                      last_date,
        "mean_pct":                       round(mean, 6),
        "stdev_pct":                      round(stdev, 6),
        "embed_dim":                      m,
        "sampen_m":                       SAMPEN_M,
        "sampen_r":                       round(sampen_r, 6),
        "shannon_entropy_bits":           shannon["bits"],
        "shannon_entropy_normalized":     shannon["normalized"],
        "sign_entropy_bits":              sign["bits"],
        "sign_entropy_normalized":        sign["normalized"],
        "permutation_entropy":            perm["bits"],
        "permutation_entropy_normalized": perm_norm,
        "sample_entropy":                 sampen["value"],
        "approximate_entropy":            apen["value"],
        "predictability_score":           score,
        "predictability_grade":           _predictability_grade(score),
        "verdict":                        _verdict(score),
        "execution_mode":                 "read_only_simulation",
    }


def generate_predictability_report(
    history_path: str | Path = DEFAULT_HISTORY_PATH,
    output_path: str | Path | None = DEFAULT_OUTPUT_PATH,
    embed_dim: int = DEFAULT_EMBED_DIM,
) -> dict:
    """Build the full predictability report and (optionally) persist it.

    Args:
        history_path: source pnl_history.json.
        output_path: where to write the report JSON. Pass ``None`` to skip
            writing (compute-only).
        embed_dim: permutation-entropy embedding dimension m (>= 2).

    Returns:
        ``{"generated_at", "source", "metrics"}``.
    """
    records = load_pnl_history(history_path)
    curve = build_daily_equity_curve(records)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source":       str(history_path),
        "metrics":      compute_predictability(curve, embed_dim=embed_dim),
    }

    if output_path is not None:
        out = Path(output_path)
        try:
            # Atomic write via the canonical atomic_save (P3-9). Byte-identical
            # (indent=2; atomic_save adds default=str for serializable payloads).
            atomic_save(report, str(out))
            log.info(
                "predictability report written: %s (%d days, verdict=%s, grade=%s)",
                out, report["metrics"]["count"],
                report["metrics"]["verdict"],
                report["metrics"]["predictability_grade"],
            )
        except OSError as exc:  # never let a write failure crash the pipeline
            log.warning("could not write predictability report to %s: %s", out, exc)

    return report


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Compute information-theoretic return predictability & "
                    "complexity (Shannon / sign / permutation / sample / "
                    "approximate entropy) from paper-trading P&L history.",
    )
    p.add_argument(
        "--history", default=str(DEFAULT_HISTORY_PATH),
        help="path to pnl_history.json (default: data/pnl_history.json)",
    )
    p.add_argument(
        "--out", default=str(DEFAULT_OUTPUT_PATH),
        help="output report path (default: data/return_predictability.json)",
    )
    p.add_argument(
        "--embed-dim", type=int, default=DEFAULT_EMBED_DIM,
        help="permutation-entropy embedding dimension m (>= 2, default: 3)",
    )
    p.add_argument(
        "--no-write", action="store_true",
        help="compute and print only; do not write the report file",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    report = generate_predictability_report(
        history_path=args.history,
        output_path=None if args.no_write else args.out,
        embed_dim=args.embed_dim,
    )
    print(json.dumps(report["metrics"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
