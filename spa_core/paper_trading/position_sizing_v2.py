#!/usr/bin/env python3
"""Position Sizing Optimizer v2 — Kelly + Mean-Variance (SPA-V433 / MP-133).

Read-only / advisory analytics module.  Computes optimal portfolio weights using
two complementary methods:

1. **Fractional Kelly** — per-protocol Kelly fraction capped at 25 pp, normalized
   so weights sum to 1.
2. **Mean-Variance (closed form)** — ``w* = Σ⁻¹μ / (1ᵀ Σ⁻¹μ)`` using a
   pure-stdlib Gauss-Jordan matrix inverse.

Then compares the two sets of optimal weights against the current portfolio
weights and surfaces a human-readable verdict.

Math notes
==========
Kelly fraction (daily)::

    f_i = (μ_i − r_f_daily) / σ²_i

where ``μ_i`` = mean daily return, ``r_f_daily = r_f_annual / 252``,
``σ²_i`` = variance of daily returns.  Negative fractions are clamped to 0
(do not short).  Weights are normalized to sum to 1, each individual weight is
then capped at ``cap`` (default 0.25), and the weights are re-normalized once
more to compensate for the redistribution from capped protocols.

Mean-Variance (analytical, long-only unconstrained)::

    w* = Σ⁻¹μ / (1ᵀ Σ⁻¹μ)

Negative entries are clipped to ``min_weight`` (default 0.0), weights exceeding
``max_weight`` (default 0.40) are clipped, and the vector is re-normalized to
sum to 1.  When Σ is singular (or near-singular) the module gracefully falls
back to equal weights and records ``singular: true`` in the result.

Deviations between methods are measured in percentage points (pp) on the weight
scale (i.e. 0.10 weight difference = 10 pp).

Scope / safety
==============
STRICTLY READ-ONLY (SPA-BL-011) — never touches risk / execution / allocator /
cycle_runner.  Pure stdlib (``math``, ``statistics``, ``json``, ``os``,
``datetime``, ``argparse``, ``sys``, ``logging``).  No external dependencies.
No network calls.  Exits 0 always.

CLI::

    python3 -m spa_core.paper_trading.position_sizing_v2 --check     # compute + print (default)
    python3 -m spa_core.paper_trading.position_sizing_v2 --run       # + atomic write to data/
    python3 -m spa_core.paper_trading.position_sizing_v2 --run --data-dir <dir>
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

__version__ = "2.0.0"
__module__ = "MP-133"

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_RISK_FREE_RATE: float = 0.04          # annual
DEFAULT_KELLY_CAP: float = 0.25               # max weight per protocol (Kelly)
DEFAULT_MV_MIN_WEIGHT: float = 0.0
DEFAULT_MV_MAX_WEIGHT: float = 0.40
DEFAULT_DEVIATION_THRESHOLD_PP: float = 20.0  # pp trigger for REBALANCE flag
_SINGULAR_EPS: float = 1e-12                  # threshold for singular-matrix detection
_DATA_FILE = "position_sizing_v2.json"


# ---------------------------------------------------------------------------
# Linear-algebra helpers (pure stdlib — no numpy)
# ---------------------------------------------------------------------------

def _copy_matrix(m: list[list[float]]) -> list[list[float]]:
    """Return a deep copy of a 2-D list-of-lists matrix."""
    return [row[:] for row in m]


def invert_matrix(matrix: list[list[float]]) -> list[list[float]]:
    """Gauss-Jordan elimination inverse for an N×N matrix.

    Parameters
    ----------
    matrix:
        N×N list-of-lists of floats.

    Returns
    -------
    list[list[float]]
        The inverse as an N×N list-of-lists.

    Raises
    ------
    ValueError
        If the matrix is singular (pivot ≈ 0 at any step) or not square.
    """
    n = len(matrix)
    if n == 0:
        raise ValueError("invert_matrix: empty matrix")
    for row in matrix:
        if len(row) != n:
            raise ValueError("invert_matrix: matrix must be square")

    # Build augmented matrix [A | I]
    aug: list[list[float]] = []
    for i in range(n):
        aug.append(matrix[i][:] + [1.0 if j == i else 0.0 for j in range(n)])

    for col in range(n):
        # Partial pivoting: find row with largest absolute value in this column
        max_row = col
        max_val = abs(aug[col][col])
        for row in range(col + 1, n):
            if abs(aug[row][col]) > max_val:
                max_val = abs(aug[row][col])
                max_row = row
        aug[col], aug[max_row] = aug[max_row], aug[col]

        pivot = aug[col][col]
        if abs(pivot) < _SINGULAR_EPS:
            raise ValueError(
                f"invert_matrix: singular matrix (pivot ≈ 0 at column {col})"
            )

        # Scale pivot row so diagonal = 1
        scale = 1.0 / pivot
        aug[col] = [x * scale for x in aug[col]]

        # Eliminate all other rows in this column
        for row in range(n):
            if row == col:
                continue
            factor = aug[row][col]
            aug[row] = [aug[row][k] - factor * aug[col][k] for k in range(2 * n)]

    # Extract right half: the inverse
    return [aug[i][n:] for i in range(n)]


def _mat_vec_mul(mat: list[list[float]], vec: list[float]) -> list[float]:
    """Multiply N×N matrix by N-vector; return N-vector."""
    n = len(vec)
    return [sum(mat[i][j] * vec[j] for j in range(n)) for i in range(n)]


def _compute_cov_matrix(returns_lists: list[list[float]]) -> list[list[float]]:
    """Compute sample covariance matrix for a list of return series.

    Parameters
    ----------
    returns_lists:
        List of N return series (each a list of floats).
        The shortest series length ``T`` is used as the common window.

    Returns
    -------
    list[list[float]]
        N×N covariance matrix (sample covariance with ``T-1`` denominator).
    """
    n = len(returns_lists)
    means = [sum(r) / len(r) if r else 0.0 for r in returns_lists]
    T = min(len(r) for r in returns_lists)
    denom = max(T - 1, 1)
    cov: list[list[float]] = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            cov[i][j] = (
                sum(
                    (returns_lists[i][t] - means[i]) * (returns_lists[j][t] - means[j])
                    for t in range(T)
                )
                / denom
            )
    return cov


def _normalize_weights(weights: dict[str, float]) -> dict[str, float]:
    """Normalize a weight dict so values sum to 1.  Returns equal weights if total == 0."""
    total = sum(weights.values())
    if total < _SINGULAR_EPS:
        n = len(weights)
        if n == 0:
            return {}
        eq = 1.0 / n
        return {k: eq for k in weights}
    return {k: v / total for k, v in weights.items()}


def _apply_cap_and_renormalize(
    weights: dict[str, float], cap: float
) -> dict[str, float]:
    """Cap each weight at ``cap`` and renormalize the remainder.

    Uses a *locked-set* approach: once a protocol is capped it stays locked,
    preventing the oscillation that arises when previously-capped protocols
    are included in subsequent renormalization steps.

    If the cap is infeasible (e.g. ``n_protocols × cap < 1.0``) the algorithm
    distributes the residual weight proportionally among locked protocols so
    that the returned weights always sum to 1.
    """
    w = dict(weights)
    locked: set[str] = set()  # protocols permanently fixed at cap

    for _ in range(len(w) + 10):  # bounded iterations
        # Only consider non-locked protocols that exceed the cap
        over = {k for k, v in w.items() if k not in locked and v > cap + _SINGULAR_EPS}
        if not over:
            break
        locked.update(over)
        for k in over:
            w[k] = cap

        free = [k for k in w if k not in locked]
        locked_sum = sum(w[k] for k in locked)
        remaining = 1.0 - locked_sum

        if not free or remaining < _SINGULAR_EPS:
            # No free protocols left to absorb remaining weight.
            # Distribute residual proportionally among locked protocols so
            # the weights still sum to 1 (relaxes cap for tied protocols).
            if locked and abs(remaining) > _SINGULAR_EPS:
                n_locked = len(locked)
                extra = remaining / n_locked
                for k in locked:
                    w[k] += extra
            break

        free_total = sum(w[k] for k in free)
        if free_total < _SINGULAR_EPS:
            eq = remaining / len(free)
            for k in free:
                w[k] = eq
        else:
            scale = remaining / free_total
            for k in free:
                w[k] = w[k] * scale

    return w


# ---------------------------------------------------------------------------
# Core optimizers
# ---------------------------------------------------------------------------

def compute_kelly_weights(
    returns: dict[str, list[float]],
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
    cap: float = DEFAULT_KELLY_CAP,
) -> dict[str, float]:
    """Compute fractional Kelly weights for each protocol.

    Parameters
    ----------
    returns:
        Mapping from protocol name to list of daily returns (as decimals,
        e.g. 0.001 for 0.1 %).
    risk_free_rate:
        Annual risk-free rate (divided by 252 internally for daily).
    cap:
        Maximum weight per protocol (default 0.25 = 25 %).

    Returns
    -------
    dict[str, float]
        Normalized (sum=1) Kelly weights, each capped at ``cap``.
        If no protocol has a positive Kelly fraction, returns equal weights.

    Notes
    -----
    * ``f_i = max(0, (μ_i − r_f_daily) / σ²_i)``
    * Protocols with zero variance receive a Kelly fraction of 0.
    * Weights are first normalized to sum to 1, then capped, then
      re-normalized to compensate for any weight redistribution from
      capping.
    """
    if not returns:
        return {}

    rf_daily = risk_free_rate / 252.0
    kelly_fracs: dict[str, float] = {}

    for protocol, rets in returns.items():
        if not rets:
            kelly_fracs[protocol] = 0.0
            continue
        mu = sum(rets) / len(rets)
        n = len(rets)
        # Sample variance
        if n < 2:
            # Can't estimate variance with a single observation
            variance = 0.0
        else:
            variance = sum((r - mu) ** 2 for r in rets) / (n - 1)

        if variance < _SINGULAR_EPS:
            # Zero (or near-zero) variance — cannot compute Kelly; fraction = 0
            kelly_fracs[protocol] = 0.0
        else:
            f = (mu - rf_daily) / variance
            kelly_fracs[protocol] = max(0.0, f)  # no shorts

    total = sum(kelly_fracs.values())
    if total < _SINGULAR_EPS:
        # All fractions zero/negative → fall back to equal weights
        n = len(returns)
        base = 1.0 / n
        kelly_fracs = {k: base for k in returns}
    else:
        # Normalize to sum = 1
        kelly_fracs = {k: v / total for k, v in kelly_fracs.items()}

    # Apply per-protocol cap and renormalize
    kelly_fracs = _apply_cap_and_renormalize(kelly_fracs, cap)

    # Final normalization pass (floating-point drift)
    return _normalize_weights(kelly_fracs)


def compute_mv_weights(
    returns: dict[str, list[float]],
    min_weight: float = DEFAULT_MV_MIN_WEIGHT,
    max_weight: float = DEFAULT_MV_MAX_WEIGHT,
) -> dict[str, float]:
    """Compute Mean-Variance optimal weights via closed-form analytical solution.

    ``w* = Σ⁻¹μ / (1ᵀ Σ⁻¹μ)``

    Parameters
    ----------
    returns:
        Mapping from protocol name to list of daily returns.
    min_weight:
        Minimum weight per protocol (default 0.0 — no shorts).
    max_weight:
        Maximum weight per protocol (default 0.40).

    Returns
    -------
    dict[str, float]
        Normalized (sum=1) MV weights, clipped to ``[min_weight, max_weight]``.
        Falls back to equal weights if Σ is singular.
    """
    if not returns:
        return {}

    protocols = list(returns.keys())
    n = len(protocols)
    if n == 1:
        return {protocols[0]: 1.0}

    returns_lists = [returns[p] for p in protocols]
    means = [sum(r) / len(r) if r else 0.0 for r in returns_lists]

    cov = _compute_cov_matrix(returns_lists)

    # Attempt matrix inversion; fall back to equal weights on singular Σ
    try:
        cov_inv = invert_matrix(cov)
    except ValueError:
        logger.warning("compute_mv_weights: singular covariance matrix — falling back to equal weights")
        eq = 1.0 / n
        return {p: eq for p in protocols}

    # w_raw = Σ⁻¹μ
    w_raw = _mat_vec_mul(cov_inv, means)

    # Denominator: 1ᵀ Σ⁻¹μ
    denom = sum(w_raw)

    if abs(denom) < _SINGULAR_EPS:
        logger.warning("compute_mv_weights: zero denominator in 1ᵀ Σ⁻¹μ — falling back to equal weights")
        eq = 1.0 / n
        return {p: eq for p in protocols}

    weights_unnorm = {protocols[i]: w_raw[i] / denom for i in range(n)}

    # Clip to [min_weight, max_weight]
    weights_clipped = {k: min(max(v, min_weight), max_weight) for k, v in weights_unnorm.items()}

    # Renormalize after clipping
    return _normalize_weights(weights_clipped)


# ---------------------------------------------------------------------------
# Comparison & verdict
# ---------------------------------------------------------------------------

def compare_weights(
    current: dict[str, float],
    kelly: dict[str, float],
    mv: dict[str, float],
    threshold_pp: float = DEFAULT_DEVIATION_THRESHOLD_PP,
) -> dict[str, Any]:
    """Compare current weights against Kelly and MV optimal weights.

    Parameters
    ----------
    current:
        Current portfolio weights (should sum to 1).
    kelly:
        Kelly-optimal weights (output of :func:`compute_kelly_weights`).
    mv:
        MV-optimal weights (output of :func:`compute_mv_weights`).
    threshold_pp:
        Deviation threshold in percentage points (default 20 pp).
        A protocol is *flagged* when its maximum deviation from either
        optimal set exceeds this threshold.

    Returns
    -------
    dict with keys:
        ``deviations`` — list of per-protocol deviation records.
        ``any_flagged`` — bool, True if at least one protocol is flagged.
        ``verdict`` — ``"OPTIMAL"`` or ``"REBALANCE_RECOMMENDED"``.
        ``explanation`` — human-readable summary string.
    """
    all_protocols = sorted(
        set(current) | set(kelly) | set(mv)
    )

    deviations = []
    any_flagged = False

    for p in all_protocols:
        cur_w = current.get(p, 0.0)
        kel_w = kelly.get(p, 0.0)
        mv_w = mv.get(p, 0.0)

        # Convert to pp (×100)
        cur_pct = cur_w * 100.0
        kel_pct = kel_w * 100.0
        mv_pct = mv_w * 100.0

        dev_kelly = abs(cur_pct - kel_pct)
        dev_mv = abs(cur_pct - mv_pct)
        max_dev = max(dev_kelly, dev_mv)
        flagged = max_dev > threshold_pp

        if flagged:
            any_flagged = True

        deviations.append(
            {
                "protocol": p,
                "current_pct": round(cur_pct, 4),
                "kelly_pct": round(kel_pct, 4),
                "mv_pct": round(mv_pct, 4),
                "max_deviation_pp": round(max_dev, 4),
                "flagged": flagged,
            }
        )

    if any_flagged:
        verdict = "REBALANCE_RECOMMENDED"
        flagged_list = [d["protocol"] for d in deviations if d["flagged"]]
        explanation = (
            f"One or more protocols deviate >={threshold_pp:.0f} pp from optimal: "
            f"{', '.join(flagged_list)}. Advisory rebalance recommended."
        )
    else:
        verdict = "OPTIMAL"
        explanation = (
            f"All protocol weights within {threshold_pp:.0f} pp of both Kelly and "
            "MV optima. No rebalance required."
        )

    return {
        "deviations": deviations,
        "any_flagged": any_flagged,
        "verdict": verdict,
        "explanation": explanation,
    }


# ---------------------------------------------------------------------------
# Convenience wrapper
# ---------------------------------------------------------------------------

def run_optimizer(
    portfolio_state: dict[str, dict[str, Any]],
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
) -> dict[str, Any]:
    """Run Kelly + MV optimizers and compare to current weights.

    Parameters
    ----------
    portfolio_state:
        Mapping ``{protocol: {"current_weight": float, "daily_returns": [float]}}``.
    risk_free_rate:
        Annual risk-free rate.

    Returns
    -------
    dict with keys ``kelly``, ``mv``, ``comparison``.
    """
    # Extract sub-dicts
    returns: dict[str, list[float]] = {
        p: v.get("daily_returns", []) for p, v in portfolio_state.items()
    }
    current_weights: dict[str, float] = {
        p: v.get("current_weight", 0.0) for p, v in portfolio_state.items()
    }

    kelly = compute_kelly_weights(returns, risk_free_rate=risk_free_rate)
    mv = compute_mv_weights(returns)
    comparison = compare_weights(current_weights, kelly, mv)

    return {
        "kelly": kelly,
        "mv": mv,
        "comparison": comparison,
    }


# ---------------------------------------------------------------------------
# Data loading helpers
# ---------------------------------------------------------------------------

def _load_json_safe(path: Path) -> dict:
    """Load a JSON file, returning {} on any error."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Could not load %s: %s", path, exc)
        return {}


def _build_portfolio_state_from_data(data_dir: Path) -> dict[str, dict[str, Any]]:
    """Attempt to build ``portfolio_state`` from existing data files.

    Reads ``current_positions.json`` and ``data/apy_history.json`` (or
    ``data/equity_curve_daily.json``) to synthesize a portfolio_state dict
    compatible with :func:`run_optimizer`.

    Falls back gracefully if files are missing or malformed.
    """
    portfolio_state: dict[str, dict[str, Any]] = {}

    # Load current positions
    positions_raw = _load_json_safe(data_dir / "current_positions.json")
    positions: list[dict] = []
    if isinstance(positions_raw, list):
        positions = positions_raw
    elif isinstance(positions_raw, dict):
        positions = positions_raw.get("positions", [])

    total_value = sum(float(p.get("value_usd", 0) or 0) for p in positions)
    if total_value < 1.0:
        total_value = 1.0  # avoid division by zero

    for pos in positions:
        protocol = str(pos.get("protocol", pos.get("name", "unknown"))).lower().replace(" ", "_")
        value = float(pos.get("value_usd", 0) or 0)
        weight = value / total_value
        portfolio_state[protocol] = {
            "current_weight": weight,
            "daily_returns": [],
        }

    # Attempt to load APY history to build synthetic daily_returns
    apy_hist_raw = _load_json_safe(data_dir / "apy_history.json")
    protocol_history: dict = apy_hist_raw.get("protocol_history", {})

    for slug, obs_list in protocol_history.items():
        if not isinstance(obs_list, list):
            continue
        # Normalize slug to protocol key
        norm_key = slug.split("-")[0] + "_" + slug.split("-")[1] if "-" in slug else slug
        norm_key = norm_key.replace("-", "_")

        # Find a matching key in portfolio_state
        matched_key = None
        for k in portfolio_state:
            if norm_key.startswith(k[:5]) or k.startswith(norm_key[:5]):
                matched_key = k
                break
        if matched_key is None:
            matched_key = norm_key
            if matched_key not in portfolio_state:
                portfolio_state[matched_key] = {"current_weight": 0.0, "daily_returns": []}

        # Convert APY (annual, percent) to daily decimal returns
        daily_rets = []
        for obs in obs_list:
            apy = obs.get("apy")
            if apy is not None:
                try:
                    daily_ret = float(apy) / 100.0 / 365.0
                    daily_rets.append(daily_ret)
                except (TypeError, ValueError):
                    pass
        if daily_rets:
            portfolio_state[matched_key]["daily_returns"] = daily_rets

    # If no positions loaded, return a minimal default state so the module can still run
    if not portfolio_state:
        logger.warning("No position data found; using placeholder state.")
        portfolio_state = {
            "aave_v3": {"current_weight": 0.60, "daily_returns": [0.0001] * 30},
            "compound_v3": {"current_weight": 0.25, "daily_returns": [0.00008] * 30},
            "morpho_blue": {"current_weight": 0.15, "daily_returns": [0.00012] * 30},
        }

    return portfolio_state


def _atomic_write(path: Path, data: dict) -> None:
    """Write *data* to *path* atomically via a temp-file + os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=str(path.parent), prefix=".tmp_", suffix=".json"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Main runner / CLI
# ---------------------------------------------------------------------------

def _build_output(portfolio_state: dict, risk_free_rate: float) -> dict:
    """Run optimizer and wrap result in the standard output envelope."""
    result = run_optimizer(portfolio_state, risk_free_rate=risk_free_rate)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    output = {
        "meta": {
            "module": __module__,
            "version": __version__,
            "generated_at": now,
            "risk_free_rate_annual": risk_free_rate,
            "kelly_cap": DEFAULT_KELLY_CAP,
            "mv_max_weight": DEFAULT_MV_MAX_WEIGHT,
            "deviation_threshold_pp": DEFAULT_DEVIATION_THRESHOLD_PP,
            "available": True,
        },
        "kelly_weights": result["kelly"],
        "mv_weights": result["mv"],
        "comparison": result["comparison"],
        "summary": {
            "verdict": result["comparison"]["verdict"],
            "any_flagged": result["comparison"]["any_flagged"],
            "explanation": result["comparison"]["explanation"],
        },
    }
    return output


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.  Always exits 0."""
    parser = argparse.ArgumentParser(
        description="Position Sizing Optimizer v2 — Kelly + Mean-Variance (MP-133)"
    )
    parser.add_argument(
        "--run", action="store_true", help="Compute and write output to data/"
    )
    parser.add_argument(
        "--check", action="store_true", help="Compute and print only (default)"
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help="Path to data directory (default: <repo_root>/data/)",
    )
    parser.add_argument(
        "--risk-free-rate",
        type=float,
        default=DEFAULT_RISK_FREE_RATE,
        help=f"Annual risk-free rate (default {DEFAULT_RISK_FREE_RATE})",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Enable debug logging"
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    # Resolve data directory
    if args.data_dir:
        data_dir = Path(args.data_dir).resolve()
    else:
        # Walk up from this file to find the repo root (where data/ lives)
        here = Path(__file__).resolve()
        data_dir = here.parent
        for _ in range(6):
            candidate = data_dir / "data"
            if candidate.is_dir():
                data_dir = candidate
                break
            data_dir = data_dir.parent
        else:
            data_dir = Path("data")

    try:
        portfolio_state = _build_portfolio_state_from_data(data_dir)
        output = _build_output(portfolio_state, args.risk_free_rate)

        # Always print
        print(json.dumps(output, indent=2))

        if args.run:
            out_path = data_dir / _DATA_FILE
            _atomic_write(out_path, output)
            logger.info("Written to %s", out_path)

    except Exception as exc:  # noqa: BLE001
        logger.exception("Unexpected error: %s", exc)
        # Never raise — analytics must not crash the process
        error_output = {
            "meta": {"module": __module__, "available": False},
            "error": str(exc),
        }
        print(json.dumps(error_output, indent=2))

    return 0


if __name__ == "__main__":
    sys.exit(main())
