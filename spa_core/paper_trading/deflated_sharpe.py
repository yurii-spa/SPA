#!/usr/bin/env python3
"""Deflated Sharpe Ratio (DSR) & Multiple-Testing-Adjusted Performance Analyzer
(SPA-V451 / MP-137) — read-only / advisory.

A yield optimizer that runs several *shadow* strategies (S0..S5) and then keeps
the best one is, by construction, *selecting on a maximum*. The Sharpe ratio of
the winner is therefore biased upward: even if every strategy were pure noise,
the best of ``N`` independent trials would still post a positive Sharpe. The
**Deflated Sharpe Ratio** of Bailey & López de Prado (2014, *The Deflated Sharpe
Ratio: Correcting for Selection Bias, Backtest Overfitting and Non-Normality*)
corrects for exactly this.

How this differs from probabilistic_sharpe.py (MP / SPA-V404)
=============================================================
``probabilistic_sharpe.py`` answers "given the track length and non-normality,
how confident are we the *true* Sharpe beats a fixed benchmark ``SR*`` (default
0)?" — the **Probabilistic Sharpe Ratio (PSR)**.

The **DSR is the very same PSR**, but with ``SR*`` *no longer 0*: instead
``SR* = E[max]`` — the **expected maximum Sharpe under the null hypothesis** of
zero true skill across ``N`` independent trials. As ``N`` grows, ``E[max]``
grows, the bar rises, and the same observed Sharpe deflates toward a lower
probability. DSR < 0.5 means the observed Sharpe is *not* distinguishable from
the best-of-``N`` you would expect from luck alone — a red flag for overfitting.

This module reuses the PSR machinery BY IMPORT (no math duplicated):
``_daily_returns``, ``_norm_cdf``, ``_inv_norm_cdf``, ``_skewness``,
``_excess_kurtosis``, ``_variance_term``, ``_probabilistic_sharpe`` from
``probabilistic_sharpe``; and ``content_fingerprint`` from
``reporting.tear_sheet`` (project convention MP-501).

Data sources (read-only, by import)
===================================
* **Observed track** — ``equity_curve.load_pnl_history`` +
  ``build_daily_equity_curve`` (same as probabilistic_sharpe). From the daily
  return series we take the *per-period (daily)* Sharpe ``SR_obs =
  mean/pstdev``, the count ``n`` of daily returns, and the population skewness /
  excess kurtosis.
* **Trial Sharpes (``N`` trials)** — ``strategy_consolidator.load_strategy_tracks``
  + ``compute_strategy_metrics``. Each usable strategy contributes one
  ``["sharpe"]`` value. ``N`` = number of strategies with usable (non-zero,
  finite) Sharpe metrics. If 0/1 trials → ``N=1`` (no multiple testing): DSR
  gracefully degrades to PSR against ``SR* = 0`` — a valid path, NOT an error.

Scale convention (load-bearing — read carefully)
=================================================
``_probabilistic_sharpe(sr, sr_star, n, skew, exkurt)`` expects a **per-period
(daily, non-annualised)** Sharpe with the matching ``n`` daily observations
(it uses ``√(n-1)``). The observed Sharpe from ``probabilistic_sharpe`` is the
*daily* ``mean/stdev``. The trial Sharpes from ``strategy_consolidator`` are
*annualised* via ``×√252`` (``TRADING_DAYS_PER_YEAR``). To make ``SR_obs``,
``V`` (variance of trial Sharpes) and ``SR* = E[max]`` live on **one common
scale**, every annualised trial Sharpe is converted back to daily by
``/√252`` BEFORE computing ``V`` and ``E[max]``. Thus all three quantities fed
into PSR are *daily*. (For transparency the result also reports the annualised
observed Sharpe and the annualised ``E[max]``.)

DSR math (pure, hand-verifiable)
================================
1. ``V`` = sample variance (ddof=1) of the *daily* trial Sharpes. ``V=0`` when
   ``N<2``.
2. Expected maximum Sharpe under the null (Bailey & López de Prado)::

       E[max] ≈ √V · ( (1 − γ)·Z⁻¹(1 − 1/N) + γ·Z⁻¹(1 − 1/(N·e)) )

   with γ = Euler–Mascheroni constant, ``Z⁻¹`` = inverse-normal-CDF, ``e`` =
   Euler's number. ``E[max] = 0.0`` when ``N≤1`` or ``V≤0`` (no multiple
   testing). ``SR* = E[max]`` is the deflated benchmark.
3. ``DSR = _probabilistic_sharpe(SR_obs_daily, SR*_daily, n, skew, exkurt)`` —
   a probability in ``(0, 1)``.

Advisory verdict
================
* **fail** if ``DSR < 0.5`` — observed Sharpe NOT significant after the
  multiple-testing correction (probable overfitting red-flag).
* **warn** if ``0.5 ≤ DSR < 0.95``.
* **ok**   if ``DSR ≥ 0.95``.
``verdict_reason`` is always present. Insufficient data (``n < MIN_OBS`` or
undefined SR / skew / kurt) → ``available:false``, ``reason:"insufficient_data"``,
``verdict:"ok"`` — schema stays stable.

Output / persistence
====================
:func:`build_deflated_sharpe` returns a stable-schema dict and NEVER raises.
:func:`write_status` atomically (tmp + ``os.replace``) writes
``data/deflated_sharpe.json`` with an in-file ``history`` (rotation ≤
:data:`HISTORY_MAX`). Idempotency via :func:`content_fingerprint`
(REUSED BY IMPORT from :mod:`spa_core.reporting.tear_sheet`, MP-501) over the
doc EXCLUDING the volatile ``meta.generated_at`` / ``history``.

CLI::

    python3 -m spa_core.paper_trading.deflated_sharpe --check    # compute+print, no write (default)
    python3 -m spa_core.paper_trading.deflated_sharpe --run      # + atomic write
    python3 -m spa_core.paper_trading.deflated_sharpe --run --data-dir <dir>

Scope / safety: STRICTLY READ-ONLY (SPA-BL-011) and advisory only. Pure stdlib
(json/os/math/sys/argparse/tempfile/logging/datetime/pathlib/statistics/typing)
— no requests/web3/LLM SDK/sockets/network/subprocess/eval/exec. It only READS
pnl_history.json + shadow-strategy tracks (via the imports above) and writes its
OWN status artifact; it never moves capital and never touches
risk/execution/allocator/cycle_runner/golive_checker.
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import statistics
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ── Math REUSED BY IMPORT from probabilistic_sharpe (do NOT reimplement) ──────
from spa_core.paper_trading.probabilistic_sharpe import (
    _daily_returns,
    _norm_cdf,  # noqa: F401  (re-exported for symmetry / test discoverability)
    _inv_norm_cdf,
    _skewness,
    _excess_kurtosis,
    _variance_term,  # noqa: F401  (re-exported; underlying PSR variance bracket)
    _probabilistic_sharpe,
)

# ── Observed equity track (same source as probabilistic_sharpe) ───────────────
from spa_core.paper_trading.equity_curve import (
    load_pnl_history,
    build_daily_equity_curve,
)

# ── Trial Sharpes from the shadow-strategy consolidator ───────────────────────
from spa_core.paper_trading.strategy_consolidator import (
    load_strategy_tracks,
    compute_strategy_metrics,
    TRADING_DAYS_PER_YEAR,  # the ×√252 annualisation factor used for trial sharpes
)

# ── content_fingerprint REUSED BY IMPORT (project convention, MP-501) ─────────
from spa_core.reporting.tear_sheet import content_fingerprint

log = logging.getLogger("spa.paper_trading.deflated_sharpe")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"

SCHEMA_VERSION: int = 1
SOURCE_NAME: str = "deflated_sharpe"
STATUS_FILENAME: str = "deflated_sharpe.json"
HISTORY_MAX: int = 500

MIN_OBS: int = 5  # minimum daily returns for a usable observed Sharpe

# Euler–Mascheroni constant γ (Bailey & López de Prado E[max] formula).
EULER_MASCHERONI: float = 0.5772156649015329

# Verdict thresholds on the DSR probability.
FAIL_BELOW: float = 0.5
OK_AT_OR_ABOVE: float = 0.95


# ──────────────────────────────────────────────────────────────────────────────
# DSR core math (pure functions, hand-verifiable)
# ──────────────────────────────────────────────────────────────────────────────

def trial_sharpe_variance(trial_sharpes: List[float]) -> float:
    """Sample variance (ddof=1) of the trial Sharpes; 0.0 when ``N < 2``.

    This is ``V`` in the Bailey & López de Prado E[max] formula. The trial
    Sharpes must already be on the same scale as ``SR_obs`` (see module
    docstring — we feed *daily* Sharpes here). Hand-verifiable.
    """
    n = len(trial_sharpes)
    if n < 2:
        return 0.0
    return statistics.variance(trial_sharpes)  # ddof=1 sample variance


def expected_max_sharpe_null(num_trials: int, variance: float) -> float:
    """Expected maximum Sharpe under the null over ``N`` independent trials.

        E[max] ≈ √V · ( (1 − γ)·Z⁻¹(1 − 1/N) + γ·Z⁻¹(1 − 1/(N·e)) )

    γ = Euler–Mascheroni, ``Z⁻¹`` = inverse-normal-CDF (probit), ``e`` =
    Euler's number. Returns ``0.0`` when ``N ≤ 1`` or ``V ≤ 0`` (no multiple
    testing — nothing to deflate against). Pure / hand-verifiable.
    """
    if num_trials <= 1 or variance <= 0.0:
        return 0.0
    sqrt_v = math.sqrt(variance)
    g = EULER_MASCHERONI
    # 1 − 1/N and 1 − 1/(N·e) are both strictly inside (0, 1) for N ≥ 2, so the
    # probit calls are always in-domain.
    z1 = _inv_norm_cdf(1.0 - 1.0 / num_trials)
    z2 = _inv_norm_cdf(1.0 - 1.0 / (num_trials * math.e))
    return sqrt_v * ((1.0 - g) * z1 + g * z2)


# ──────────────────────────────────────────────────────────────────────────────
# Trial-Sharpe gathering (read-only, by import)
# ──────────────────────────────────────────────────────────────────────────────

def _gather_trial_sharpes(data_dir: Path) -> Tuple[List[float], str, int]:
    """Collect annualised trial Sharpes from the shadow-strategy consolidator.

    Returns ``(annualised_sharpes, trials_source, raw_strategy_count)``.

    A trial Sharpe is "usable" when it is a finite, non-zero number (the
    consolidator returns 0.0 for degenerate / flat tracks, which carry no
    information about the spread of the search). ``trials_source`` is
    ``"shadow_strategies"`` when ≥ 2 usable trials were found, else
    ``"single"`` (no multiple testing). Never raises.
    """
    try:
        tracks = load_strategy_tracks(str(data_dir))
    except Exception:  # upstream is tolerant, but stay defensive anyway
        tracks = {}
    if not isinstance(tracks, dict):
        tracks = {}

    raw_count = len(tracks)
    sharpes: List[float] = []
    for _sid in sorted(tracks.keys()):
        try:
            metrics = compute_strategy_metrics(tracks[_sid])
        except Exception:
            continue
        if not isinstance(metrics, dict):
            continue
        s = metrics.get("sharpe")
        if isinstance(s, bool) or not isinstance(s, (int, float)):
            continue
        sval = float(s)
        if not math.isfinite(sval) or sval == 0.0:
            continue
        sharpes.append(sval)

    source = "shadow_strategies" if len(sharpes) >= 2 else "single"
    return sharpes, source, raw_count


def _detect_is_demo(data_dir: Path) -> Optional[bool]:
    """Honest demo flag from the consolidator artifact / shadow source, else None.

    Looks for a top-level / meta ``is_demo`` or ``demo`` boolean in
    ``data/strategy_consolidator.json`` (written by the consolidator) if it
    exists. Never raises; returns ``None`` when unknown.
    """
    p = data_dir / "strategy_consolidator.json"
    if not p.exists():
        return None
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(d, dict):
        return None
    for key in ("is_demo", "demo"):
        v = d.get(key)
        if isinstance(v, bool):
            return v
    meta = d.get("meta")
    if isinstance(meta, dict) and isinstance(meta.get("is_demo"), bool):
        return meta["is_demo"]
    return None


# ──────────────────────────────────────────────────────────────────────────────
# Main builder
# ──────────────────────────────────────────────────────────────────────────────

def _unavailable(
    reason: str,
    generated_at: str,
    notes: List[str],
    is_demo: Optional[bool] = None,
) -> Dict[str, Any]:
    """Stable-schema unavailable result. verdict='ok' (advisory no-op)."""
    return {
        "available": False,
        "reason": reason,
        "verdict": "ok",
        "verdict_reason": f"insufficient data: {reason}",
        "deflated_sharpe_ratio": None,
        "probabilistic_sharpe": None,
        "observed_sharpe": None,
        "observed_sharpe_annualized": None,
        "num_trials": None,
        "trial_sharpe_variance": None,
        "expected_max_sharpe_null": None,
        "expected_max_sharpe_null_annualized": None,
        "n_observations": None,
        "skewness": None,
        "excess_kurtosis": None,
        "trials_source": None,
        "is_demo": is_demo,
        "notes": notes,
        "meta": {
            "generated_at": generated_at,
            "schema_version": SCHEMA_VERSION,
            "source": SOURCE_NAME,
            "min_obs_required": MIN_OBS,
        },
    }


def build_deflated_sharpe(data_dir: Path = _DEFAULT_DATA_DIR) -> Dict[str, Any]:
    """Compute the Deflated Sharpe Ratio. Never raises.

    Returns a stable-schema dict. See module docstring for the scale
    convention: all of ``SR_obs``, ``V`` and ``E[max]`` are computed on the
    *daily* (per-period) scale before being fed into the PSR machinery.
    """
    data_dir = Path(data_dir)
    notes: List[str] = []
    generated_at = datetime.now(timezone.utc).isoformat()
    is_demo: Optional[bool] = None

    try:
        is_demo = _detect_is_demo(data_dir)

        # ── 1. Observed track → daily Sharpe, n, skew, exkurt ─────────────────
        try:
            records = load_pnl_history(data_dir / "pnl_history.json")
            curve = build_daily_equity_curve(records)
            returns = _daily_returns(curve)
        except Exception as exc:
            return _unavailable(f"could not load equity track: {exc}",
                                generated_at, notes, is_demo)

        n = len(returns)
        if n < MIN_OBS:
            return _unavailable(
                f"only {n} daily returns (< {MIN_OBS} required)",
                generated_at, notes, is_demo,
            )

        mean = statistics.fmean(returns)
        stdev = statistics.pstdev(returns)
        if stdev <= 0.0:
            return _unavailable("flat / zero-variance return series",
                                generated_at, notes, is_demo)

        skew = _skewness(returns, mean, stdev)
        exkurt = _excess_kurtosis(returns, mean, stdev)
        if skew is None or exkurt is None:
            return _unavailable("skewness / kurtosis undefined",
                                generated_at, notes, is_demo)

        sr_obs_daily = mean / stdev  # per-period (daily) observed Sharpe

        # ── 2. Trial Sharpes → daily scale → V, E[max] ────────────────────────
        ann_sharpes, trials_source, raw_count = _gather_trial_sharpes(data_dir)
        # Consolidator annualises trial Sharpes by ×√252; bring them back to the
        # daily scale so V / E[max] match SR_obs_daily exactly.
        sqrt_days = math.sqrt(TRADING_DAYS_PER_YEAR)
        daily_trial_sharpes = [s / sqrt_days for s in ann_sharpes]
        num_trials = max(1, len(daily_trial_sharpes))

        if num_trials < 2:
            notes.append(
                f"only {len(daily_trial_sharpes)} usable trial Sharpe(s) "
                f"(raw strategies seen: {raw_count}); no multiple testing — "
                f"DSR degrades to PSR against SR*=0"
            )
            v_daily = 0.0
            sr_star_daily = 0.0
        else:
            v_daily = trial_sharpe_variance(daily_trial_sharpes)
            sr_star_daily = expected_max_sharpe_null(num_trials, v_daily)

        # ── 3. DSR = PSR(SR_obs, SR*=E[max]) and PSR(SR_obs, 0) for comparison ─
        dsr, _v_term_dsr = _probabilistic_sharpe(
            sr_obs_daily, sr_star_daily, n, skew, exkurt
        )
        psr0, _v_term_psr = _probabilistic_sharpe(
            sr_obs_daily, 0.0, n, skew, exkurt
        )

        if dsr is None:
            return _unavailable(
                "DSR undefined (non-positive Sharpe-estimator variance term)",
                generated_at, notes, is_demo,
            )

        # ── Annualised echoes (transparency only; NOT fed into PSR) ───────────
        sr_obs_ann = sr_obs_daily * sqrt_days
        sr_star_ann = sr_star_daily * sqrt_days

        # ── Advisory verdict ──────────────────────────────────────────────────
        if dsr < FAIL_BELOW:
            verdict = "fail"
            verdict_reason = (
                f"DSR={dsr:.3f} < {FAIL_BELOW}: observed Sharpe NOT significant "
                f"after multiple-testing correction over N={num_trials} trial(s) "
                f"(probable overfitting red-flag)"
            )
        elif dsr < OK_AT_OR_ABOVE:
            verdict = "warn"
            verdict_reason = (
                f"DSR={dsr:.3f} in [{FAIL_BELOW}, {OK_AT_OR_ABOVE}): observed "
                f"Sharpe only marginally survives the N={num_trials}-trial "
                f"selection-bias correction"
            )
        else:
            verdict = "ok"
            verdict_reason = (
                f"DSR={dsr:.3f} ≥ {OK_AT_OR_ABOVE}: observed Sharpe remains "
                f"significant after correcting for N={num_trials} trial(s)"
            )

        result: Dict[str, Any] = {
            "available": True,
            "verdict": verdict,
            "verdict_reason": verdict_reason,
            "deflated_sharpe_ratio": round(dsr, 6),
            "probabilistic_sharpe": (round(psr0, 6) if psr0 is not None else None),
            "observed_sharpe": round(sr_obs_daily, 6),
            "observed_sharpe_annualized": round(sr_obs_ann, 6),
            "num_trials": num_trials,
            "trial_sharpe_variance": round(v_daily, 9),
            "expected_max_sharpe_null": round(sr_star_daily, 9),
            "expected_max_sharpe_null_annualized": round(sr_star_ann, 6),
            "n_observations": n,
            "skewness": round(skew, 6),
            "excess_kurtosis": round(exkurt, 6),
            "trials_source": trials_source,
            "trial_sharpes_annualized": [round(s, 6) for s in ann_sharpes],
            "raw_strategy_count": raw_count,
            "annualization_days": TRADING_DAYS_PER_YEAR,
            "is_demo": is_demo,
            "notes": notes,
            "meta": {
                "generated_at": generated_at,
                "schema_version": SCHEMA_VERSION,
                "source": SOURCE_NAME,
                "min_obs_required": MIN_OBS,
            },
        }
        return result

    except Exception as exc:  # last-resort: NEVER raise
        log.exception("unexpected error in build_deflated_sharpe")
        return _unavailable(f"unexpected error: {exc}", generated_at, notes, is_demo)


# ──────────────────────────────────────────────────────────────────────────────
# Atomic persistence (content_fingerprint reused by import — see top of module)
# ──────────────────────────────────────────────────────────────────────────────

def write_status(
    result: Dict[str, Any],
    data_dir: Path = _DEFAULT_DATA_DIR,
) -> str:
    """Atomically write deflated_sharpe.json.

    Returns ``"DATA_WRITTEN"`` | ``"DATA_UNCHANGED"``.
    """
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    out_path = data_dir / STATUS_FILENAME

    current_fp = content_fingerprint(result)

    existing: Dict[str, Any] = {}
    if out_path.exists():
        try:
            existing = json.loads(out_path.read_text(encoding="utf-8"))
            if not isinstance(existing, dict):
                existing = {}
        except Exception:
            existing = {}

    if existing.get("_fingerprint") == current_fp:
        return "DATA_UNCHANGED"

    history: List[Dict[str, Any]] = existing.get("history", [])
    if not isinstance(history, list):
        history = []
    if existing and "_fingerprint" in existing:
        prev_entry = {k: v for k, v in existing.items() if k != "history"}
        history = [prev_entry] + history
        history = history[:HISTORY_MAX]

    doc = dict(result)
    doc["_fingerprint"] = current_fp
    doc["history"] = history

    fd, tmp_path = tempfile.mkstemp(dir=data_dir, prefix=".tmp_deflated_sharpe_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=2)
        os.replace(tmp_path, out_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    return "DATA_WRITTEN"


# ──────────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────────

def _print_result(result: Dict[str, Any]) -> None:
    if not result.get("available"):
        print(
            f"[deflated_sharpe] available=false reason={result.get('reason', '?')}"
        )
        print(f"  verdict       : {result.get('verdict')} — {result.get('verdict_reason')}")
        for n in result.get("notes", []):
            print(f"  note: {n}")
        return

    print("[deflated_sharpe] available=true")
    print(f"  verdict       : {result['verdict']} — {result['verdict_reason']}")
    print(f"  DSR           : {result['deflated_sharpe_ratio']}")
    print(f"  PSR (vs 0)    : {result['probabilistic_sharpe']}")
    print(f"  observed SR   : {result['observed_sharpe']} (daily) "
          f"/ {result['observed_sharpe_annualized']} (annualised)")
    print(f"  num_trials N  : {result['num_trials']} ({result['trials_source']})")
    print(f"  trial var V   : {result['trial_sharpe_variance']} (daily scale)")
    print(f"  E[max] SR*    : {result['expected_max_sharpe_null']} (daily) "
          f"/ {result['expected_max_sharpe_null_annualized']} (annualised)")
    print(f"  n_obs         : {result['n_observations']}")
    print(f"  skew / exkurt : {result['skewness']} / {result['excess_kurtosis']}")
    if result.get("is_demo") is not None:
        print(f"  is_demo       : {result['is_demo']}")
    for n in result.get("notes", []):
        print(f"  note: {n}")


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(
        description="Deflated Sharpe Ratio (DSR) & Multiple-Testing-Adjusted "
                    "Performance Analyzer (MP-137)",
        add_help=True,
    )
    parser.add_argument(
        "--check", action="store_true",
        help="compute and print, no write (default)",
    )
    parser.add_argument(
        "--run", action="store_true",
        help="compute, print, and atomically write to data/deflated_sharpe.json",
    )
    parser.add_argument(
        "--data-dir", default=None,
        help="override data directory (default: <repo_root>/data)",
    )

    args, unknown = parser.parse_known_args(argv)
    if unknown:
        print(f"ERROR: invalid arguments: {unknown}", file=sys.stderr)
        sys.exit(0)

    # --check / --run mutually exclusive; conflict → ERROR to stderr, exit 0.
    if args.check and args.run:
        print("ERROR: --check and --run are mutually exclusive", file=sys.stderr)
        sys.exit(0)

    data_dir = Path(args.data_dir) if args.data_dir else _DEFAULT_DATA_DIR

    result = build_deflated_sharpe(data_dir)
    _print_result(result)

    if args.run:
        status = write_status(result, data_dir)
        print(f"[deflated_sharpe] write_status={status}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    main()
