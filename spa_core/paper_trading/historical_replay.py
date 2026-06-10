"""
Historical portfolio replay — counterfactual yield simulation (SPA-V385).

Read-only analytics layer that complements the live paper-trading equity curve
(:mod:`spa_core.paper_trading.equity_curve`, SPA-V379) with a *counterfactual
historical* curve: "what would a given allocation strategy have earned if it
had been run over the local historical APY series?".

It does NOT place trades, does NOT read or touch live trading state, and does
NOT consult the execution path, risk policy, wallets or money-moving code. It
is a deterministic, offline simulation over ``data/historical_apy.json`` for the
reporting / dashboard layer only.

Source data shape (``data/historical_apy.json``)::

    {"generated_at": ..., "data_source": "synthetic", "days": 90,
     "protocols": {"<protocol-id>": [{"date": "YYYY-MM-DD",
                                      "apy": <float pct>,
                                      "tvl_usd": <float>}, ...], ...}}

``apy`` is an annual percentage (e.g. ``6.05`` == 6.05 %/yr). A daily growth
factor is derived as ``(1 + apy/100) ** (1/365)`` and compounded day by day.

Strategies replayed (all on the set of dates common across protocols, so the
curves are aligned):
  * ``equal_weight``       — capital split equally across all protocols every
    day (rebalanced daily). Portfolio daily factor = mean of per-protocol
    daily factors.
  * ``best_apy``           — each day allocate 100 % to the protocol with the
    highest APY that day ("chase the best rate"). No switching / gas cost is
    modeled (documented assumption).
  * ``buy_and_hold_best``  — pick the single protocol with the highest MEAN apy
    over the whole window and hold it the entire period.

Design notes / safety:
  * Pure stdlib (json, math, statistics, datetime, pathlib, logging, argparse).
    No web3, no pandas/numpy/scipy, no network/urllib. Runs fully offline.
  * STRICTLY READ-ONLY w.r.t. trading state. Never touches the execution path,
    the risk policy, wallets, or any money-moving code. NOT feed-health
    (SPA-BL-011 freeze respected). It only reads historical_apy.json and writes
    a derived report JSON.
  * Defensive: a missing / empty / malformed source yields an empty-but-valid
    report (stable schema, ``num_days`` 0, empty strategies / per_protocol).
    Functions never raise on bad data — callers always get a dict. Malformed
    records are skipped (logged at DEBUG).

CLI::

    python -m spa_core.paper_trading.historical_replay
    python -m spa_core.paper_trading.historical_replay \\
        --history data/historical_apy.json --out data/historical_replay.json \\
        --capital 10000
"""
from __future__ import annotations

import argparse
import json
import logging
import statistics
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("spa.paper_trading.historical_replay")

# Default I/O locations relative to the project root (two levels up from this
# file: spa_core/paper_trading/historical_replay.py -> project root).
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_HISTORY_PATH = _PROJECT_ROOT / "data" / "historical_apy.json"
DEFAULT_OUTPUT_PATH = _PROJECT_ROOT / "data" / "historical_replay.json"

DEFAULT_STARTING_CAPITAL = 10_000.0

# Days per year used to convert an annual APY into a daily growth factor.
_DAYS_PER_YEAR = 365.0


def _now_iso_z() -> str:
    """Current UTC time as an ISO-8601 string with a trailing ``Z``."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _is_number(value: object) -> bool:
    """True for a real int/float (booleans are rejected)."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def load_historical_apy(path: str | Path = DEFAULT_HISTORY_PATH) -> dict:
    """Load and defensively parse the historical APY file.

    Returns a dict ``{"data_source": <str>, "protocols": {<id>: {<date>: apy}}}``
    where each protocol maps a ``YYYY-MM-DD`` date string to a float APY. A
    missing / empty / malformed file (or malformed sub-records) degrades
    gracefully: the result is always a dict, never raises, and bad records are
    skipped (logged at DEBUG).
    """
    result = {"data_source": None, "protocols": {}}
    p = Path(path)
    if not p.exists():
        log.warning("historical_apy not found at %s — empty replay", p)
        return result
    try:
        raw = json.loads(p.read_text(encoding="utf-8") or "{}")
    except (ValueError, OSError) as exc:
        log.warning("historical_apy unreadable (%s) — empty replay", exc)
        return result
    if not isinstance(raw, dict):
        log.warning("historical_apy is not a JSON object (%s) — empty replay", type(raw))
        return result

    result["data_source"] = raw.get("data_source")
    protocols = raw.get("protocols")
    if not isinstance(protocols, dict):
        log.debug("historical_apy has no 'protocols' object — empty replay")
        return result

    for proto_id, series in protocols.items():
        if not isinstance(proto_id, str) or not isinstance(series, list):
            log.debug("skip protocol with bad id/series: %r", proto_id)
            continue
        date_map: dict[str, float] = {}
        for rec in series:
            if not isinstance(rec, dict):
                log.debug("skip non-dict record in %s: %r", proto_id, rec)
                continue
            d = rec.get("date")
            apy = rec.get("apy")
            if not isinstance(d, str) or not d:
                log.debug("skip record with bad date in %s: %r", proto_id, d)
                continue
            if not _is_number(apy):
                log.debug("skip record with bad apy in %s@%s: %r", proto_id, d, apy)
                continue
            date_map[d] = float(apy)
        if date_map:
            result["protocols"][proto_id] = date_map
        else:
            log.debug("protocol %s yielded no usable records — dropped", proto_id)
    return result


def _daily_factor(apy: float) -> float:
    """Convert an annual APY percentage into a daily compounding factor.

    ``daily_factor = (1 + apy/100) ** (1/365)``. ``apy == 0`` -> ``1.0``;
    positive apy -> ``> 1.0``. Guards against a pathological ``apy <= -100``
    (which would make the base non-positive) by flooring the base just above 0.
    """
    base = 1.0 + apy / 100.0
    if base <= 0.0:
        # APY of -100% or worse would wipe capital; floor to keep math finite.
        base = 1e-12
    return base ** (1.0 / _DAYS_PER_YEAR)


def _aligned_dates(protocols: dict[str, dict[str, float]]) -> list[str]:
    """Sorted list of dates present in *every* protocol (intersection).

    Empty protocol set -> empty list. Aligning on the intersection guarantees
    each strategy replays on exactly the same dates.
    """
    if not protocols:
        return []
    common: set[str] | None = None
    for date_map in protocols.values():
        keys = set(date_map.keys())
        common = keys if common is None else (common & keys)
    if not common:
        return []
    return sorted(common)


def compute_protocol_summary(series_map: dict[str, dict[str, float]]) -> dict:
    """Per-protocol APY statistics + own period (compounded) return.

    Args:
        series_map: ``{protocol_id: {date: apy}}`` (as built by
            :func:`load_historical_apy`).

    Returns:
        ``{protocol_id: {mean_apy, min_apy, max_apy, apy_volatility,
        num_points, period_return_pct}}``. ``period_return_pct`` compounds the
        protocol's own daily factors across the aligned dates. Empty input ->
        empty dict.
    """
    dates = _aligned_dates(series_map)
    out: dict[str, dict] = {}
    for proto_id in sorted(series_map):
        date_map = series_map[proto_id]
        apys = [date_map[d] for d in sorted(date_map)]
        if not apys:
            continue
        vol = round(statistics.pstdev(apys), 6) if len(apys) >= 2 else 0.0
        # Period return compounds the protocol's own daily factors over the
        # aligned (common) dates so it is comparable across protocols.
        factor = 1.0
        for d in dates:
            if d in date_map:
                factor *= _daily_factor(date_map[d])
        out[proto_id] = {
            "mean_apy":          round(statistics.fmean(apys), 6),
            "min_apy":           round(min(apys), 6),
            "max_apy":           round(max(apys), 6),
            "apy_volatility":    vol,
            "num_points":        len(apys),
            "period_return_pct": round((factor - 1.0) * 100.0, 6),
        }
    return out


def _build_curve(dates: list[str], factors: list[float], starting_capital: float) -> list[dict]:
    """Compound ``factors`` day by day from ``starting_capital`` into a curve.

    Each curve bar::

        {date, equity, daily_return_pct, cumulative_return_pct}

    ``len(dates) == len(factors)`` is assumed (callers build them in lockstep).
    """
    curve: list[dict] = []
    equity = float(starting_capital)
    start = float(starting_capital)
    for d, f in zip(dates, factors):
        daily_return_pct = (f - 1.0) * 100.0
        equity *= f
        cumulative_return_pct = (
            0.0 if start == 0 else (equity / start - 1.0) * 100.0
        )
        curve.append({
            "date":                  d,
            "equity":                round(equity, 4),
            "daily_return_pct":      round(daily_return_pct, 6),
            "cumulative_return_pct": round(cumulative_return_pct, 6),
        })
    return curve


def replay_equal_weight(
    protocols: dict[str, dict[str, float]],
    dates: list[str],
    starting_capital: float = DEFAULT_STARTING_CAPITAL,
) -> list[dict]:
    """Equal-weight, daily-rebalanced replay.

    Each day the portfolio daily factor is the arithmetic mean of every
    protocol's daily factor (capital split equally and rebalanced daily).
    """
    if not protocols or not dates:
        return []
    proto_ids = sorted(protocols)
    factors: list[float] = []
    for d in dates:
        day_factors = [
            _daily_factor(protocols[pid][d])
            for pid in proto_ids
            if d in protocols[pid]
        ]
        factors.append(statistics.fmean(day_factors) if day_factors else 1.0)
    return _build_curve(dates, factors, starting_capital)


def replay_best_apy(
    protocols: dict[str, dict[str, float]],
    dates: list[str],
    starting_capital: float = DEFAULT_STARTING_CAPITAL,
) -> list[dict]:
    """"Chase the best rate" replay.

    Each day allocate 100 % to the protocol with the highest APY *that day*.
    Assumption: switching is frictionless — no gas / slippage / rebalance cost
    is modeled, so this is an idealized upper-ish bound on naive rate-chasing.
    """
    if not protocols or not dates:
        return []
    proto_ids = sorted(protocols)
    factors: list[float] = []
    for d in dates:
        best_apy: float | None = None
        for pid in proto_ids:
            if d in protocols[pid]:
                apy = protocols[pid][d]
                if best_apy is None or apy > best_apy:
                    best_apy = apy
        factors.append(_daily_factor(best_apy) if best_apy is not None else 1.0)
    return _build_curve(dates, factors, starting_capital)


def _highest_mean_protocol(protocols: dict[str, dict[str, float]], dates: list[str]) -> str | None:
    """Protocol id with the highest MEAN apy over the aligned dates (or None)."""
    best_id: str | None = None
    best_mean: float | None = None
    for pid in sorted(protocols):
        date_map = protocols[pid]
        apys = [date_map[d] for d in dates if d in date_map]
        if not apys:
            continue
        m = statistics.fmean(apys)
        if best_mean is None or m > best_mean:
            best_mean = m
            best_id = pid
    return best_id


def replay_buy_and_hold_best(
    protocols: dict[str, dict[str, float]],
    dates: list[str],
    starting_capital: float = DEFAULT_STARTING_CAPITAL,
) -> tuple[list[dict], str | None]:
    """Buy-and-hold the single highest-mean-APY protocol for the whole window.

    Returns ``(curve, selected_protocol_id)``. If no protocol is usable the
    curve is empty and the selected id is None.
    """
    if not protocols or not dates:
        return [], None
    selected = _highest_mean_protocol(protocols, dates)
    if selected is None:
        return [], None
    date_map = protocols[selected]
    factors = [_daily_factor(date_map[d]) if d in date_map else 1.0 for d in dates]
    return _build_curve(dates, factors, starting_capital), selected


def compute_strategy_summary(curve: list[dict]) -> dict:
    """Roll a single strategy curve up into headline performance metrics.

    Returns a stable schema (zeroed / None fields when ``curve`` is empty)::

        {start_equity, end_equity, total_return_pct, annualized_apy_pct,
         num_days, mean_daily_return_pct, daily_volatility_pct,
         best_day, worst_day, max_drawdown_pct}

    ``annualized_apy_pct`` = ``((end/start)**(365/num_days) - 1) * 100``.
    ``max_drawdown_pct`` is <= 0 (worst equity vs running peak).
    """
    if not curve:
        return {
            "start_equity":          None,
            "end_equity":            None,
            "total_return_pct":      0.0,
            "annualized_apy_pct":    0.0,
            "num_days":              0,
            "mean_daily_return_pct": 0.0,
            "daily_volatility_pct":  0.0,
            "best_day":              None,
            "worst_day":             None,
            "max_drawdown_pct":      0.0,
        }

    num_days = len(curve)
    daily_returns = [bar["daily_return_pct"] for bar in curve]
    end_equity = curve[-1]["equity"]
    # Starting capital = equity before the first day's growth was applied.
    first_factor = 1.0 + daily_returns[0] / 100.0
    start_equity = round(curve[0]["equity"] / first_factor, 4) if first_factor else None

    total_return_pct = (
        0.0 if not start_equity else (end_equity / start_equity - 1.0) * 100.0
    )
    annualized_apy_pct = 0.0
    if start_equity and num_days > 0 and end_equity > 0:
        annualized_apy_pct = (
            (end_equity / start_equity) ** (_DAYS_PER_YEAR / num_days) - 1.0
        ) * 100.0

    best = max(curve, key=lambda b: b["daily_return_pct"])
    worst = min(curve, key=lambda b: b["daily_return_pct"])

    # Max drawdown vs running peak equity (<= 0).
    peak = curve[0]["equity"]
    max_dd = 0.0
    for bar in curve:
        eq = bar["equity"]
        if eq > peak:
            peak = eq
        dd = 0.0 if peak == 0 else (eq / peak - 1.0) * 100.0
        if dd < max_dd:
            max_dd = dd

    vol = round(statistics.pstdev(daily_returns), 6) if num_days >= 2 else 0.0

    return {
        "start_equity":          start_equity,
        "end_equity":            end_equity,
        "total_return_pct":      round(total_return_pct, 6),
        "annualized_apy_pct":    round(annualized_apy_pct, 6),
        "num_days":              num_days,
        "mean_daily_return_pct": round(statistics.fmean(daily_returns), 6),
        "daily_volatility_pct":  vol,
        "best_day":              {"date": best["date"],
                                  "daily_return_pct": best["daily_return_pct"]},
        "worst_day":             {"date": worst["date"],
                                  "daily_return_pct": worst["daily_return_pct"]},
        "max_drawdown_pct":      round(max_dd, 6),
    }


def generate_historical_replay_report(
    path: str | Path = DEFAULT_HISTORY_PATH,
    starting_capital: float = DEFAULT_STARTING_CAPITAL,
    output_path: str | Path | None = None,
) -> dict:
    """Build the full historical-replay report and (optionally) persist it.

    Args:
        path: source historical_apy.json.
        starting_capital: simulated starting capital in USD.
        output_path: where to write the report JSON. ``None`` -> compute-only.

    Returns the top-level report dict (stable schema; empty-but-valid on
    missing / empty input — never raises).
    """
    loaded = load_historical_apy(path)
    protocols = loaded["protocols"]
    dates = _aligned_dates(protocols)
    num_days = len(dates)

    per_protocol = compute_protocol_summary(protocols)

    report = {
        "generated_at":         _now_iso_z(),
        "source":               str(path),
        "data_source":          loaded["data_source"],
        "start_date":           dates[0] if dates else None,
        "end_date":             dates[-1] if dates else None,
        "num_days":             num_days,
        "num_protocols":        len(protocols),
        "starting_capital_usd": round(float(starting_capital), 4),
        "strategies":           {},
        "best_strategy":        None,
        "per_protocol":         per_protocol,
    }

    if not protocols or not dates:
        return _maybe_write(report, output_path)

    eq_curve = replay_equal_weight(protocols, dates, starting_capital)
    ba_curve = replay_best_apy(protocols, dates, starting_capital)
    bh_curve, bh_selected = replay_buy_and_hold_best(protocols, dates, starting_capital)

    eq_summary = compute_strategy_summary(eq_curve)
    ba_summary = compute_strategy_summary(ba_curve)
    bh_summary = compute_strategy_summary(bh_curve)

    report["strategies"] = {
        "equal_weight":      {**eq_summary, "curve": eq_curve},
        "best_apy":          {**ba_summary, "curve": ba_curve},
        "buy_and_hold_best": {**bh_summary,
                              "selected_protocol": bh_selected,
                              "curve": bh_curve},
    }

    # Best strategy by total_return.
    best_name = max(
        report["strategies"],
        key=lambda n: report["strategies"][n]["total_return_pct"],
    )
    report["best_strategy"] = {
        "name":             best_name,
        "total_return_pct": report["strategies"][best_name]["total_return_pct"],
    }

    return _maybe_write(report, output_path)


def _maybe_write(report: dict, output_path: str | Path | None) -> dict:
    """Write ``report`` to ``output_path`` (JSON, indent=2) if requested.

    A write failure is logged but never raised — the report dict is always
    returned to the caller.
    """
    if output_path is None:
        return report
    out = Path(output_path)
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        log.info(
            "historical replay report written: %s (%d days, %d protocols)",
            out, report["num_days"], report["num_protocols"],
        )
    except OSError as exc:  # never let a write failure crash the pipeline
        log.warning("could not write historical replay report to %s: %s", out, exc)
    return report


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Historical portfolio replay over local APY history (read-only).",
    )
    p.add_argument(
        "--history", default=str(DEFAULT_HISTORY_PATH),
        help="path to historical_apy.json (default: data/historical_apy.json)",
    )
    p.add_argument(
        "--out", default=str(DEFAULT_OUTPUT_PATH),
        help="output report path (default: data/historical_replay.json)",
    )
    p.add_argument(
        "--capital", type=float, default=DEFAULT_STARTING_CAPITAL,
        help="starting capital in USD (default: 10000)",
    )
    p.add_argument(
        "--no-write", action="store_true",
        help="compute and print only; do not write the report file",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    report = generate_historical_replay_report(
        path=args.history,
        starting_capital=args.capital,
        output_path=None if args.no_write else args.out,
    )
    # Compact, human-readable summary (no per-day curves).
    lines = [
        f"historical replay: {report['num_protocols']} protocols, "
        f"{report['num_days']} aligned days "
        f"({report['start_date']} .. {report['end_date']})",
        f"starting capital: ${report['starting_capital_usd']:,.2f}",
    ]
    for name, strat in report["strategies"].items():
        extra = ""
        if name == "buy_and_hold_best":
            extra = f"  [{strat.get('selected_protocol')}]"
        lines.append(
            f"  {name:18s} total {strat['total_return_pct']:+.4f}%  "
            f"annualized {strat['annualized_apy_pct']:+.4f}%  "
            f"maxDD {strat['max_drawdown_pct']:.4f}%{extra}"
        )
    if report["best_strategy"]:
        lines.append(
            f"best strategy: {report['best_strategy']['name']} "
            f"({report['best_strategy']['total_return_pct']:+.4f}%)"
        )
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
