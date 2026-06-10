"""
Portfolio concentration & diversification analytics (SPA-V398).

Read-only, advisory analytics layer that analyses the *allocation structure* of
the current portfolio rather than its return path. Where the V379–V397 paper-
trading suite is uniformly return-SERIES analytics (Sharpe / Sortino / drawdown /
tail / Monte-Carlo on the daily equity curve), this module asks a different,
complementary question: **how concentrated is the capital across protocols, and
how many independent "bets" is the book really running?**

Metrics (all over the *actual* invested weights, normalised to sum to 1.0 over
invested capital):

    herfindahl_index        HHI = sum(w_i^2)            range 1/N .. 1
    hhi_normalized          (HHI - 1/N) / (1 - 1/N)     range 0 .. 1  (None if N<2)
    effective_num_positions 1 / HHI  — "effective number of bets"
    max_weight / min_weight  largest / smallest position weight (+ protocol)
    top1_concentration_pct   weight of the single largest position * 100
    top3_concentration_pct   sum of the top-3 weights * 100
    shannon_entropy          -sum(w * ln w)             nats
    entropy_normalized       entropy / ln(N)            range 0 .. 1  (None if N<2)
    gini_coefficient         0 = perfectly equal .. ->1 fully concentrated
    diversification_grade    A/B/C/D from hhi_normalized thresholds (see below)

When ``target_allocation.json`` is present an optional ``cash_buffer_pct`` and a
``concentration_vs_target`` block are added: HHI of actual vs HHI of target and
the classic ``active_share`` = 0.5 * sum(|actual_w - target_w|) over the union of
protocols. Concentration is always measured over INVESTED capital only — the
unallocated cash buffer is reported separately, not diluted into the weights.

Design notes / safety:
  * Pure stdlib (json, math, os, datetime, pathlib, logging, argparse,
    statistics) — mirrors the no-external-dependency style of the sibling
    paper-trading modules. No web3 / numpy / pandas / scipy / network.
  * STRICTLY READ-ONLY and ADVISORY. Reads portfolio_state.json (and optionally
    target_allocation.json) and writes a single derived report JSON. It never
    touches the execution path, risk agents, wallets, money-moving code, or the
    SPA-BL-011-frozen feed-health domain.
  * Defensive: missing / empty / malformed inputs degrade to a stable-schema
    object with ``num_positions: 0`` and None/empty metrics. The module NEVER
    raises on bad data.
  * Single-position portfolios: HHI = 1.0, effective_num = 1.0, gini = 0.0, and
    the size-relative measures (hhi_normalized, entropy_normalized) are None
    because they are undefined for N < 2.

CLI::

    python -m spa_core.paper_trading.concentration_analytics
    python -m spa_core.paper_trading.concentration_analytics \\
        --portfolio-state data/portfolio_state.json \\
        --target-allocation data/target_allocation.json \\
        --out data/concentration_analytics.json --no-write
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("spa.paper_trading.concentration_analytics")

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PORTFOLIO_STATE_PATH = _PROJECT_ROOT / "data" / "portfolio_state.json"
DEFAULT_TARGET_ALLOCATION_PATH = _PROJECT_ROOT / "data" / "target_allocation.json"
DEFAULT_OUTPUT_PATH = _PROJECT_ROOT / "data" / "concentration_analytics.json"

# Diversification grade thresholds on hhi_normalized (0 = equal-weight, 1 = single
# name). Lower normalized HHI == better diversified.
#   A: hhi_normalized <= 0.15   well diversified
#   B: hhi_normalized <= 0.35   moderately diversified
#   C: hhi_normalized <= 0.60   somewhat concentrated
#   D: hhi_normalized  > 0.60   highly concentrated
GRADE_A_MAX = 0.15
GRADE_B_MAX = 0.35
GRADE_C_MAX = 0.60

# How many top positions feed top3_concentration_pct.
TOP_K = 3


# ─── Helpers ────────────────────────────────────────────────────────────────


def _load_json(path: str | Path) -> Optional[dict]:
    """Load a JSON object from *path*; return None on any failure (read-only)."""
    try:
        with Path(path).open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            return data
        log.debug("Source %s is not a JSON object (got %s)", path, type(data).__name__)
        return None
    except FileNotFoundError:
        log.debug("Source not found: %s", path)
        return None
    except (OSError, ValueError) as exc:  # malformed / unreadable
        log.debug("Could not read source %s: %s", path, exc)
        return None


def _as_float(value: Any) -> Optional[float]:
    """Coerce *value* to a finite float, else None (defensive)."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f):
        return None
    return f


def _extract_actual_weights(state: Optional[dict]) -> dict[str, float]:
    """Return {protocol: normalised_actual_weight} over invested capital.

    Prefers each position's ``actual_weight``; falls back to
    ``actual_usd / total_actual_usd`` when the weight field is missing. Drops
    non-positive / unusable positions, then renormalises so the surviving weights
    sum to 1.0. Returns ``{}`` for any malformed / empty input (never raises).
    """
    if not isinstance(state, dict):
        return {}
    positions = state.get("positions")
    if not isinstance(positions, list):
        return {}

    total_actual = _as_float(state.get("total_actual_usd"))

    raw: dict[str, float] = {}
    for pos in positions:
        if not isinstance(pos, dict):
            continue
        protocol = pos.get("protocol")
        if not isinstance(protocol, str) or not protocol:
            continue
        w = _as_float(pos.get("actual_weight"))
        if w is None:
            # Derive from USD exposure when the explicit weight is absent.
            usd = _as_float(pos.get("actual_usd"))
            if usd is not None and total_actual not in (None, 0.0):
                w = usd / total_actual
        if w is None or w <= 0:
            continue
        # Aggregate duplicate protocols defensively.
        raw[protocol] = raw.get(protocol, 0.0) + w

    total = sum(raw.values())
    if total <= 0:
        return {}
    return {p: w / total for p, w in raw.items()}


def _extract_target_weights(
    state: Optional[dict], target: Optional[dict]
) -> dict[str, float]:
    """Return {protocol: normalised_target_weight} over invested target capital.

    Prefers ``target_allocation.json``'s ``target_weights``; falls back to the
    positions' ``target_weight`` / ``target_usd`` in portfolio_state. Renormalised
    to sum to 1.0 over the invested target. Returns ``{}`` if unavailable.
    """
    raw: dict[str, float] = {}

    if isinstance(target, dict):
        tw = target.get("target_weights")
        if isinstance(tw, dict):
            for protocol, value in tw.items():
                w = _as_float(value)
                if isinstance(protocol, str) and protocol and w is not None and w > 0:
                    raw[protocol] = raw.get(protocol, 0.0) + w

    if not raw and isinstance(state, dict):
        positions = state.get("positions")
        total_target = _as_float(state.get("total_target_usd"))
        if isinstance(positions, list):
            for pos in positions:
                if not isinstance(pos, dict):
                    continue
                protocol = pos.get("protocol")
                if not isinstance(protocol, str) or not protocol:
                    continue
                w = _as_float(pos.get("target_weight"))
                if w is None:
                    usd = _as_float(pos.get("target_usd"))
                    if usd is not None and total_target not in (None, 0.0):
                        w = usd / total_target
                if w is None or w <= 0:
                    continue
                raw[protocol] = raw.get(protocol, 0.0) + w

    total = sum(raw.values())
    if total <= 0:
        return {}
    return {p: w / total for p, w in raw.items()}


def _herfindahl(weights: list[float]) -> Optional[float]:
    """HHI = sum(w_i^2); None for an empty book."""
    if not weights:
        return None
    return sum(w * w for w in weights)


def _gini(weights: list[float]) -> Optional[float]:
    """Gini coefficient of the weight distribution (0 equal .. ->1 concentrated).

    Uses the standard mean-absolute-difference form
        G = sum_i sum_j |w_i - w_j| / (2 * n^2 * mean(w)).
    For weights that already sum to 1, mean = 1/n, so the denominator is 2*n.
    A single position (or any perfectly equal book) gives exactly 0.
    """
    n = len(weights)
    if n == 0:
        return None
    if n == 1:
        return 0.0
    mean = sum(weights) / n
    if mean <= 0:
        return 0.0
    total_diff = 0.0
    for i in range(n):
        for j in range(n):
            total_diff += abs(weights[i] - weights[j])
    g = total_diff / (2.0 * n * n * mean)
    # Clamp tiny FP excursions into [0, 1].
    return max(0.0, min(1.0, g))


def _shannon_entropy(weights: list[float]) -> Optional[float]:
    """Shannon entropy -sum(w * ln w) in nats; None for an empty book."""
    if not weights:
        return None
    return -sum(w * math.log(w) for w in weights if w > 0)


def _grade(hhi_normalized: Optional[float]) -> Optional[str]:
    """Letter grade A/B/C/D from normalised HHI; None when undefined (N<2)."""
    if hhi_normalized is None:
        return None
    if hhi_normalized <= GRADE_A_MAX:
        return "A"
    if hhi_normalized <= GRADE_B_MAX:
        return "B"
    if hhi_normalized <= GRADE_C_MAX:
        return "C"
    return "D"


def _rnd(x: Optional[float], places: int = 6) -> Optional[float]:
    return None if x is None else round(x, places)


# ─── Core computation ───────────────────────────────────────────────────────


def _empty_metrics() -> dict:
    """Stable-schema object for an empty / unusable portfolio."""
    return {
        "num_positions": 0,
        "weights": {},
        "herfindahl_index": None,
        "hhi_normalized": None,
        "effective_num_positions": None,
        "max_weight": None,
        "max_weight_protocol": None,
        "min_weight": None,
        "min_weight_protocol": None,
        "top1_concentration_pct": None,
        "top3_concentration_pct": None,
        "shannon_entropy": None,
        "entropy_normalized": None,
        "gini_coefficient": None,
        "diversification_grade": None,
    }


def compute_concentration_metrics(state: Optional[dict]) -> dict:
    """Compute concentration / diversification metrics from portfolio_state.

    Args:
        state: parsed ``portfolio_state.json`` (or None / malformed).

    Returns:
        A stable-schema metrics dict. Empty / unusable input yields
        ``num_positions == 0`` with None/empty metrics — never raises.
    """
    weights_map = _extract_actual_weights(state)
    n = len(weights_map)
    if n == 0:
        return _empty_metrics()

    # Deterministic order: descending weight, then protocol name as a tiebreak.
    items = sorted(weights_map.items(), key=lambda kv: (-kv[1], kv[0]))
    weights = [w for _, w in items]

    hhi = _herfindahl(weights)
    effective_num = (1.0 / hhi) if hhi and hhi > 0 else None

    # hhi_normalized & entropy_normalized are undefined for N < 2.
    if n >= 2 and hhi is not None:
        hhi_norm = (hhi - 1.0 / n) / (1.0 - 1.0 / n)
        # Clamp FP noise into [0, 1].
        hhi_norm = max(0.0, min(1.0, hhi_norm))
    else:
        hhi_norm = None

    max_protocol, max_weight = items[0]
    min_protocol, min_weight = items[-1]

    top1 = weights[0] * 100.0
    top3 = sum(weights[:TOP_K]) * 100.0

    entropy = _shannon_entropy(weights)
    if n >= 2 and entropy is not None:
        ln_n = math.log(n)
        entropy_norm = (entropy / ln_n) if ln_n > 0 else None
        if entropy_norm is not None:
            entropy_norm = max(0.0, min(1.0, entropy_norm))
    else:
        entropy_norm = None

    gini = _gini(weights)
    grade = _grade(hhi_norm)

    return {
        "num_positions": n,
        "weights": {p: round(w, 6) for p, w in items},
        "herfindahl_index": _rnd(hhi),
        "hhi_normalized": _rnd(hhi_norm),
        "effective_num_positions": _rnd(effective_num, 4),
        "max_weight": _rnd(max_weight),
        "max_weight_protocol": max_protocol,
        "min_weight": _rnd(min_weight),
        "min_weight_protocol": min_protocol,
        "top1_concentration_pct": _rnd(top1, 4),
        "top3_concentration_pct": _rnd(top3, 4),
        "shannon_entropy": _rnd(entropy),
        "entropy_normalized": _rnd(entropy_norm),
        "gini_coefficient": _rnd(gini),
        "diversification_grade": grade,
    }


def _active_share(
    actual: dict[str, float], target: dict[str, float]
) -> Optional[float]:
    """Classic active share = 0.5 * sum(|actual_w - target_w|) over the union.

    0 when the actual book exactly matches the target; ->1 as they diverge.
    None when either side is empty.
    """
    if not actual or not target:
        return None
    protocols = set(actual) | set(target)
    s = sum(abs(actual.get(p, 0.0) - target.get(p, 0.0)) for p in protocols)
    return max(0.0, min(1.0, 0.5 * s))


def _concentration_vs_target(
    actual: dict[str, float], target: dict[str, float]
) -> Optional[dict]:
    """HHI(actual) vs HHI(target) plus active_share; None if target unavailable."""
    if not actual or not target:
        return None
    hhi_actual = _herfindahl(list(actual.values()))
    hhi_target = _herfindahl(list(target.values()))
    return {
        "hhi_actual": _rnd(hhi_actual),
        "hhi_target": _rnd(hhi_target),
        "hhi_delta": _rnd(
            (hhi_actual - hhi_target)
            if (hhi_actual is not None and hhi_target is not None)
            else None
        ),
        "active_share": _rnd(_active_share(actual, target), 6),
        "num_actual_protocols": len(actual),
        "num_target_protocols": len(target),
    }


def build_concentration_report(
    portfolio_state_path: str | Path = DEFAULT_PORTFOLIO_STATE_PATH,
    target_allocation_path: str | Path | None = DEFAULT_TARGET_ALLOCATION_PATH,
) -> dict:
    """Build the full concentration report dict (no I/O side effects)."""
    state = _load_json(portfolio_state_path)
    metrics = compute_concentration_metrics(state)

    report: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": str(portfolio_state_path),
        "execution_mode": "read_only_simulation",
        "metrics": metrics,
        "concentration_basis": "invested_capital_only",
    }

    # Optional enrichment from target_allocation.json.
    target = _load_json(target_allocation_path) if target_allocation_path else None
    if isinstance(target, dict):
        report["target_allocation_source"] = str(target_allocation_path)
        unallocated = _as_float(target.get("unallocated_pct"))
        if unallocated is not None:
            report["cash_buffer_pct"] = round(unallocated * 100.0, 4)
        report["note"] = (
            "Concentration is measured over INVESTED capital only; the "
            "unallocated cash buffer is reported separately as cash_buffer_pct."
        )

    # concentration_vs_target whenever both actual and target weights exist.
    actual_weights = _extract_actual_weights(state)
    target_weights = _extract_target_weights(state, target)
    cvt = _concentration_vs_target(actual_weights, target_weights)
    if cvt is not None:
        report["concentration_vs_target"] = cvt

    return report


def _atomic_write_json(obj: dict, out_path: Path) -> None:
    """Write *obj* as pretty JSON to *out_path* atomically (tmp + os.replace)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_name(f".concentration_analytics_{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(tmp, out_path)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def generate_concentration_report(
    portfolio_state_path: str | Path = DEFAULT_PORTFOLIO_STATE_PATH,
    target_allocation_path: str | Path | None = DEFAULT_TARGET_ALLOCATION_PATH,
    output_path: str | Path | None = DEFAULT_OUTPUT_PATH,
) -> dict:
    """Build the concentration report and (optionally) persist it atomically.

    Pass ``output_path=None`` to compute only. Write failures are logged, not
    raised, so an analytics report never crashes a caller.
    """
    report = build_concentration_report(portfolio_state_path, target_allocation_path)

    if output_path is not None:
        out = Path(output_path)
        try:
            _atomic_write_json(report, out)
            m = report["metrics"]
            log.info(
                "concentration report written: %s (N=%s, HHI=%s, grade=%s)",
                out, m["num_positions"], m["herfindahl_index"],
                m["diversification_grade"],
            )
        except OSError as exc:  # never let a write failure crash the pipeline
            log.warning("could not write concentration report to %s: %s", output_path, exc)

    return report


# ─── CLI ────────────────────────────────────────────────────────────────────


def _format_summary(report: dict) -> str:
    """One-line human summary of the headline concentration figures."""
    m = report["metrics"]
    n = m["num_positions"]
    hhi = m["herfindahl_index"]
    eff = m["effective_num_positions"]
    max_w = m["max_weight"]
    grade = m["diversification_grade"]
    hhi_s = f"{hhi:.4f}" if isinstance(hhi, (int, float)) else "n/a"
    eff_s = f"{eff:.2f}" if isinstance(eff, (int, float)) else "n/a"
    max_s = f"{max_w * 100.0:.2f}%" if isinstance(max_w, (int, float)) else "n/a"
    grade_s = grade if grade is not None else "n/a"
    line = f"CONCENTRATION | N={n} | HHI={hhi_s} | eff_N={eff_s} | max_w={max_s} | grade={grade_s}"
    cvt = report.get("concentration_vs_target")
    if isinstance(cvt, dict) and cvt.get("active_share") is not None:
        line += f" | active_share={cvt['active_share']:.4f}"
    return line


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Portfolio concentration & diversification analytics (SPA-V398, read-only).",
    )
    p.add_argument(
        "--portfolio-state", default=str(DEFAULT_PORTFOLIO_STATE_PATH),
        help="path to portfolio_state.json (default: data/portfolio_state.json)",
    )
    p.add_argument(
        "--target-allocation", default=str(DEFAULT_TARGET_ALLOCATION_PATH),
        help="optional target_allocation.json for cash buffer / active share "
             "(default: data/target_allocation.json)",
    )
    p.add_argument(
        "--out", default=str(DEFAULT_OUTPUT_PATH),
        help="output report path (default: data/concentration_analytics.json)",
    )
    p.add_argument(
        "--no-write", action="store_true",
        help="compute and print only; do not write the report file",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    report = generate_concentration_report(
        portfolio_state_path=args.portfolio_state,
        target_allocation_path=args.target_allocation,
        output_path=None if args.no_write else args.out,
    )
    print(_format_summary(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
