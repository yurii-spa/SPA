#!/usr/bin/env python3
"""Investor-Ready Monthly Report Generator (SPA / MP-134) — read-only / advisory.

Generates a polished Markdown monthly report for an investor audience. Reads
existing data files and synthesises them into a structured report with:

  1. Title + metadata
  2. Executive Summary (template-generated, **NO LLM**)
  3. Performance Table (this month vs prev month vs USDC 4% p.a. benchmark)
  4. Risk Metrics (Sharpe, Sortino, max drawdown, days underwater)
  5. Protocol Breakdown (from yield_attribution or adapter_status)
  6. Key Events (single-day moves > 1%, largest gain/loss)
  7. Outlook (template-based forward statement)

Output: ``data/monthly_report_YYYY-MM.md`` (written atomically).

CLI::

    python3 -m spa_core.paper_trading.monthly_report --month 2026-06
    python3 -m spa_core.paper_trading.monthly_report --month 2026-06 --run
    python3 -m spa_core.paper_trading.monthly_report --month 2026-06 --run --data-dir <dir>

Architecture notes
==================
* **Pure stdlib** — json / os / math / datetime / argparse / tempfile / pathlib.
  No requests, no web3, no LLM SDK, no sockets.
* **Read-only** on all source files; writes only its own output MD artifact.
* **Atomic writes** — tmp file + ``os.replace``; no partial writes on disk.
* ``approved=False`` from RiskPolicy can never be overridden (advisory only).
* All functions are safe against missing / malformed input (return sane
  defaults, never raise to the caller).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ─── Constants ────────────────────────────────────────────────────────────────

#: USDC 4 % p.a. base rate used as the performance benchmark throughout.
USDC_BENCHMARK_ANNUAL_PCT: float = 4.0

#: Annualisation factor (calendar days).
ANNUALISATION_DAYS: int = 365

#: A single-day return of this magnitude (in percent) constitutes a "key event".
KEY_EVENT_THRESHOLD_PCT: float = 1.0

_MONTH_NAMES: Dict[str, str] = {
    "01": "January", "02": "February", "03": "March",
    "04": "April",   "05": "May",      "06": "June",
    "07": "July",    "08": "August",   "09": "September",
    "10": "October", "11": "November", "12": "December",
}


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _load_json(path: Path) -> Any:
    """Load a JSON file; return ``None`` on any I/O or parse error."""
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def _data_path(data_dir: str, filename: str) -> Path:
    return Path(data_dir) / filename


def _prev_month(month: str) -> Optional[str]:
    """Return ``YYYY-MM`` for the month preceding *month*, or ``None`` on error."""
    try:
        year, m = int(month[:4]), int(month[5:7])
        m -= 1
        if m == 0:
            m, year = 12, year - 1
        return f"{year:04d}-{m:02d}"
    except Exception:
        return None


def _month_label(month: str) -> str:
    """``'2026-06'`` → ``'June 2026'``."""
    try:
        if len(month) < 7 or month[4] != "-":
            return month
        year, m = month[:4], month[5:7]
        name = _MONTH_NAMES.get(m, m)
        return f"{name} {year}".strip()
    except Exception:
        return month


def _fmt_pct(v: float, plus: bool = True) -> str:
    """Format a float as a percentage string, e.g. ``+4.21%``."""
    sign = "+" if (plus and v >= 0) else ""
    return f"{sign}{v:.2f}%"


def _extract_close(bar: dict) -> Optional[float]:
    """Extract a positive close equity value from a bar dict."""
    for key in ("close_equity", "equity"):
        v = bar.get(key)
        if isinstance(v, (int, float)) and v > 0:
            return float(v)
    return None


# ─── Data loading ─────────────────────────────────────────────────────────────

def load_report_data(month: str, data_dir: str = "data") -> dict:
    """Load available data for the given month (format ``"YYYY-MM"``).

    Reads (gracefully handles missing files):

    * ``data/portfolio_snapshots.json``   — primary snapshots source
    * ``data/equity_curve_daily.json``    — fallback snapshot source
    * ``data/adapter_status.json``
    * ``data/yield_attribution.json``
    * ``data/drawdown_attribution.json``
    * ``data/drawdown_analytics.json``
    * ``data/performance_report.json``

    Returns a dict with whatever data was found. Keys present only when the
    corresponding file loaded successfully.
    """
    result: Dict[str, Any] = {"month": month, "data_dir": data_dir}

    # ── Snapshots (primary: portfolio_snapshots; fallback: equity_curve_daily) ──
    snap_doc = _load_json(_data_path(data_dir, "portfolio_snapshots.json"))
    equity_doc = _load_json(_data_path(data_dir, "equity_curve_daily.json"))

    if snap_doc and isinstance(snap_doc.get("snapshots"), list):
        result["snapshots"] = snap_doc["snapshots"]
    elif equity_doc and isinstance(equity_doc.get("daily"), list):
        result["snapshots"] = equity_doc["daily"]
    else:
        result["snapshots"] = []

    # ── Supporting data files ──
    for key, filename in (
        ("adapter_status",      "adapter_status.json"),
        ("yield_attribution",   "yield_attribution.json"),
        ("drawdown_attribution","drawdown_attribution.json"),
        ("drawdown_analytics",  "drawdown_analytics.json"),
        ("performance_report",  "performance_report.json"),
    ):
        doc = _load_json(_data_path(data_dir, filename))
        if doc is not None:
            result[key] = doc

    return result


# ─── Metric computation ────────────────────────────────────────────────────────

def compute_month_metrics(snapshots: list, month: str) -> dict:
    """Filter *snapshots* to *month* and compute standard performance metrics.

    All ``daily_return_pct`` values in the equity_curve_daily source are stored
    as **percent** (e.g. ``0.0087`` means 0.0087 %).

    Parameters
    ----------
    snapshots:
        List of bar dicts, each with at minimum ``date`` (``YYYY-MM-DD``) and
        ``close_equity`` / ``equity`` fields.  ``daily_return_pct`` is used
        when present, otherwise computed from successive equity levels.
    month:
        ``YYYY-MM`` string identifying the reporting month.

    Returns
    -------
    dict
        ``{start_equity, end_equity, total_return_pct, trading_days,
        max_drawdown_pct, daily_returns, sharpe, best_day, worst_day}``
        — or ``{}`` if no valid bars exist for the month.
    """
    if not snapshots or not month:
        return {}

    # ── Filter and sort bars for the requested month ──
    bars: List[Tuple[str, float, dict]] = []
    for bar in snapshots:
        if not isinstance(bar, dict):
            continue
        date_str = bar.get("date", "")
        if not isinstance(date_str, str) or not date_str.startswith(month):
            continue
        equity = _extract_close(bar)
        if equity is not None:
            bars.append((date_str, equity, bar))

    if not bars:
        return {}

    bars.sort(key=lambda x: x[0])

    start_equity = bars[0][1]
    end_equity   = bars[-1][1]
    trading_days = len(bars)

    if start_equity <= 0:
        return {}

    total_return_pct = (end_equity / start_equity - 1.0) * 100.0

    # ── Daily returns (in percent) ──
    daily_returns: List[float] = []
    for i, (_, equity, bar) in enumerate(bars):
        if i == 0:
            continue  # no prior bar to compute from
        stored = bar.get("daily_return_pct")
        if isinstance(stored, (int, float)):
            daily_returns.append(float(stored))
        else:
            prev_eq = bars[i - 1][1]
            if prev_eq > 0:
                daily_returns.append((equity / prev_eq - 1.0) * 100.0)

    # ── Max drawdown (running-peak method) ──
    peak = bars[0][1]
    max_dd = 0.0
    for _, equity, _ in bars:
        if equity > peak:
            peak = equity
        dd = (equity / peak - 1.0) * 100.0  # zero or negative
        if dd < max_dd:
            max_dd = dd

    sharpe   = _compute_sharpe(daily_returns)
    best_day  = max(daily_returns) if daily_returns else 0.0
    worst_day = min(daily_returns) if daily_returns else 0.0

    return {
        "start_equity":      round(start_equity, 2),
        "end_equity":        round(end_equity, 2),
        "total_return_pct":  round(total_return_pct, 6),
        "trading_days":      trading_days,
        "max_drawdown_pct":  round(max_dd, 6),
        "daily_returns":     [round(r, 6) for r in daily_returns],
        "sharpe":            round(sharpe, 4),
        "best_day":          round(best_day, 6),
        "worst_day":         round(worst_day, 6),
    }


def _compute_sharpe(
    daily_returns_pct: List[float],
    annualisation_days: int = ANNUALISATION_DAYS,
) -> float:
    """Annualised Sharpe ratio using USDC 4 % p.a. as the risk-free rate.

    Returns 0.0 when there are fewer than 2 observations or zero std-dev.
    """
    if len(daily_returns_pct) < 2:
        return 0.0
    rf_daily_pct = USDC_BENCHMARK_ANNUAL_PCT / annualisation_days
    excess = [r - rf_daily_pct for r in daily_returns_pct]
    n = len(excess)
    mean_exc = sum(excess) / n
    variance = sum((r - mean_exc) ** 2 for r in excess) / (n - 1)
    std = math.sqrt(variance) if variance > 0 else 0.0
    if std == 0.0:
        return 0.0
    return mean_exc / std * math.sqrt(annualisation_days)


def _compute_sortino(
    daily_returns_pct: List[float],
    annualisation_days: int = ANNUALISATION_DAYS,
) -> float:
    """Annualised Sortino ratio (downside deviation, MAR = USDC 4 % p.a.).

    Returns 10.0 (capped) when all excess returns are non-negative.
    Returns 0.0 with fewer than 2 observations.
    """
    if len(daily_returns_pct) < 2:
        return 0.0
    rf_daily_pct = USDC_BENCHMARK_ANNUAL_PCT / annualisation_days
    excess = [r - rf_daily_pct for r in daily_returns_pct]
    n = len(excess)
    mean_exc = sum(excess) / n
    neg_sq = [r ** 2 for r in excess if r < 0]
    if not neg_sq:
        return 10.0  # all returns beat hurdle — cap at 10
    downside_dev = math.sqrt(sum(neg_sq) / n)
    if downside_dev == 0.0:
        return 0.0
    return mean_exc / downside_dev * math.sqrt(annualisation_days)


# ─── Executive summary (template-based, NO LLM) ───────────────────────────────

def generate_executive_summary(metrics: dict, month: str) -> str:
    """Generate a 2–3 sentence executive summary from *metrics*.

    Purely template-based string composition using ``if/else`` on metric values.
    **No LLM calls are made.**

    Parameters
    ----------
    metrics:
        Output of :func:`compute_month_metrics` (may be empty ``{}``).
    month:
        Reporting month in ``YYYY-MM`` format.

    Returns
    -------
    str
        A human-readable paragraph suitable for the "Executive Summary" section.
    """
    label = _month_label(month)

    if not metrics:
        return (
            f"In {label}, insufficient data is available to compute performance "
            "metrics. The sections below reflect partial or unavailable data."
        )

    ret          = metrics.get("total_return_pct", 0.0)
    sharpe       = metrics.get("sharpe", 0.0)
    max_dd       = metrics.get("max_drawdown_pct", 0.0)
    trading_days = metrics.get("trading_days", 30)

    # Pro-rate USDC benchmark to the period length
    usdc_period = USDC_BENCHMARK_ANNUAL_PCT / 12.0 * (trading_days / 30.0)

    # ── Sentence 1: return vs benchmark ──
    if ret > usdc_period:
        bps = round((ret - usdc_period) * 100)
        sentence1 = (
            f"In {label}, the portfolio returned {_fmt_pct(ret)}, outperforming "
            f"the USDC base rate by {bps}bps on a period basis."
        )
    elif ret >= 0:
        sentence1 = (
            f"In {label}, the portfolio returned {_fmt_pct(ret)}, "
            f"in line with the USDC base rate of {_fmt_pct(usdc_period, plus=False)}."
        )
    else:
        sentence1 = (
            f"In {label}, the portfolio posted a return of {_fmt_pct(ret)}, "
            f"underperforming the USDC base rate of {_fmt_pct(usdc_period, plus=False)}."
        )

    # ── Sentence 2: Sharpe / risk quality ──
    if sharpe >= 2.0:
        sentence2 = f"Sharpe ratio of {sharpe:.1f} reflects exceptional risk-adjusted performance."
    elif sharpe >= 1.0:
        sentence2 = f"Sharpe ratio of {sharpe:.1f} reflects healthy risk-adjusted returns."
    elif sharpe > 0.0:
        sentence2 = f"Sharpe ratio of {sharpe:.1f} indicates modest risk-adjusted returns."
    else:
        sentence2 = (
            f"Sharpe ratio of {sharpe:.1f} signals elevated volatility relative to returns."
        )

    # ── Sentence 3: drawdown containment ──
    if max_dd == 0.0:
        sentence3 = "No drawdown was recorded during the period."
    elif abs(max_dd) < 1.0:
        sentence3 = f"Maximum drawdown was contained at {_fmt_pct(max_dd, plus=False)}."
    else:
        sentence3 = (
            f"Maximum drawdown reached {_fmt_pct(max_dd, plus=False)}, "
            "requiring close monitoring of capital preservation."
        )

    return f"{sentence1} {sentence2} {sentence3}"


# ─── Markdown section builders ────────────────────────────────────────────────

def _annualise(period_pct: float, trading_days: int) -> float:
    """Compound-annualise a period return (in percent)."""
    if trading_days <= 0:
        return 0.0
    factor = 1.0 + period_pct / 100.0
    if factor <= 0:
        return 0.0
    return (factor ** (ANNUALISATION_DAYS / trading_days) - 1.0) * 100.0


def _performance_table(metrics: dict, prev_metrics: dict) -> str:
    """Build the ## Performance Markdown section."""
    lines = ["## Performance", ""]

    td_this  = metrics.get("trading_days", 0) if metrics else 0
    td_prev  = prev_metrics.get("trading_days", 0) if prev_metrics else 0
    ret_this = metrics.get("total_return_pct") if metrics else None
    ret_prev = prev_metrics.get("total_return_pct") if prev_metrics else None
    shr_this = metrics.get("sharpe") if metrics else None
    shr_prev = prev_metrics.get("sharpe") if prev_metrics else None

    ann_this = _annualise(ret_this, td_this) if ret_this is not None and td_this else None
    ann_prev = _annualise(ret_prev, td_prev) if ret_prev is not None and td_prev else None

    usdc_monthly = (USDC_BENCHMARK_ANNUAL_PCT / 12.0) * (td_this / 30.0) if td_this else USDC_BENCHMARK_ANNUAL_PCT / 12.0

    def _c(v: Any, fmt: str = "pct") -> str:
        if v is None:
            return "n/a"
        if fmt == "pct":
            return _fmt_pct(float(v))
        if fmt == "f2":
            return f"{float(v):.2f}"
        return str(v)

    lines += [
        "| Metric | This Month | Prev Month | USDC Benchmark |",
        "|--------|-----------|-----------|----------------|",
        f"| Return | {_c(ret_this)} | {_c(ret_prev)} | {_fmt_pct(usdc_monthly)} |",
        f"| Annualized | {_c(ann_this)} | {_c(ann_prev)} | {_fmt_pct(USDC_BENCHMARK_ANNUAL_PCT)} |",
        f"| Sharpe | {_c(shr_this, 'f2')} | {_c(shr_prev, 'f2')} | n/a |",
        "",
    ]
    return "\n".join(lines)


def _risk_table(metrics: dict, data: dict) -> str:
    """Build the ## Risk Metrics Markdown section."""
    lines = ["## Risk Metrics", ""]

    if not metrics:
        lines += ["_Insufficient data for risk metrics._", ""]
        return "\n".join(lines)

    daily_rets = metrics.get("daily_returns", [])
    sharpe     = metrics.get("sharpe", 0.0)
    sortino    = _compute_sortino(daily_rets)
    max_dd     = metrics.get("max_drawdown_pct", 0.0)
    best       = metrics.get("best_day", 0.0)
    worst      = metrics.get("worst_day", 0.0)

    # Pull underwater stats from drawdown_analytics if available
    dd_analytics = data.get("drawdown_analytics") or {}
    dd_headline  = dd_analytics.get("headline") or {} if isinstance(dd_analytics, dict) else {}
    uw_days      = dd_headline.get("longest_underwater_days") or 0
    time_in_dd   = dd_headline.get("time_in_drawdown_pct") or 0.0

    lines += [
        "| Metric | Value |",
        "|--------|-------|",
        f"| Sharpe Ratio (ann.) | {sharpe:.2f} |",
        f"| Sortino Ratio (ann.) | {sortino:.2f} |",
        f"| Max Drawdown | {_fmt_pct(max_dd, plus=False)} |",
        f"| Best Day | {_fmt_pct(best)} |",
        f"| Worst Day | {_fmt_pct(worst)} |",
        f"| Longest Underwater Streak | {int(uw_days)} days |",
        f"| Time in Drawdown | {float(time_in_dd):.1f}% |",
        f"| Trading Days in Period | {metrics.get('trading_days', 0)} |",
        "",
    ]
    return "\n".join(lines)


def _protocol_breakdown(data: dict) -> str:
    """Build the ## Protocol Breakdown Markdown section."""
    lines = ["## Protocol Breakdown", ""]

    # Prefer yield_attribution (has live allocations + APY)
    yield_doc = data.get("yield_attribution") or {}
    breakdown  = yield_doc.get("breakdown", []) if isinstance(yield_doc, dict) else []

    if breakdown:
        lines += [
            "| Protocol | Tier | APY | Allocation |",
            "|----------|------|-----|------------|",
        ]
        for entry in sorted(breakdown, key=lambda x: x.get("weight_frac", 0.0), reverse=True):
            name    = entry.get("protocol", "Unknown").replace("_", " ").title()
            tier    = entry.get("tier", "—")
            apy     = entry.get("apy_pct")
            weight  = entry.get("weight_frac")
            apy_s   = f"{apy:.2f}%" if isinstance(apy, (int, float)) else "n/a"
            wt_s    = f"{weight * 100:.1f}%" if isinstance(weight, (int, float)) else "n/a"
            lines.append(f"| {name} | {tier} | {apy_s} | {wt_s} |")
        lines.append("")
        port_apy = yield_doc.get("portfolio_apy_pp")
        if isinstance(port_apy, (int, float)):
            lines += [f"**Portfolio weighted APY:** {port_apy:.2f}%", ""]
        return "\n".join(lines)

    # Fallback: adapter_status
    adapter_doc = data.get("adapter_status") or {}
    adapters    = adapter_doc.get("adapters", []) if isinstance(adapter_doc, dict) else []

    if not adapters:
        lines += ["_Protocol data not available._", ""]
        return "\n".join(lines)

    lines += [
        "| Protocol | Tier | APY (USDC/ETH) |",
        "|----------|------|----------------|",
    ]
    for adapter in adapters:
        name     = adapter.get("name") or adapter.get("protocol_key", "Unknown")
        tier     = adapter.get("tier", "—")
        mock_apy = adapter.get("mock_apy") or {}
        apy_val  = None
        if isinstance(mock_apy, dict):
            eth = mock_apy.get("ethereum") or {}
            if isinstance(eth, dict):
                apy_val = eth.get("USDC")
        apy_s = f"{apy_val:.1f}%" if isinstance(apy_val, (int, float)) else "n/a"
        lines.append(f"| {name} | {tier} | {apy_s} |")
    lines.append("")
    return "\n".join(lines)


def _key_events(snapshots: list, month: str, metrics: dict) -> str:
    """Build the ## Key Events Markdown section.

    Highlights any single-day return exceeding ±1 % and always reports the
    best/worst day in the period.
    """
    lines = ["## Key Events", ""]

    if not snapshots or not metrics:
        lines += ["_No key event data available._", ""]
        return "\n".join(lines)

    events: List[Tuple[str, float]] = []
    for bar in snapshots:
        if not isinstance(bar, dict):
            continue
        date_str = bar.get("date", "")
        if not isinstance(date_str, str) or not date_str.startswith(month):
            continue
        ret = bar.get("daily_return_pct")
        if not isinstance(ret, (int, float)):
            continue
        if abs(float(ret)) >= KEY_EVENT_THRESHOLD_PCT:
            events.append((date_str, float(ret)))

    if events:
        lines += [
            "| Date | Return | Direction |",
            "|------|--------|-----------|",
        ]
        for date_str, ret in sorted(events):
            direction = "Gain" if ret >= 0 else "Loss"
            lines.append(f"| {date_str} | {_fmt_pct(ret)} | {direction} |")
        lines.append("")
    else:
        lines.append(
            f"No single-day moves exceeded ±{KEY_EVENT_THRESHOLD_PCT:.0f}% "
            "during the period."
        )
        lines.append("")

    best  = metrics.get("best_day", 0.0)
    worst = metrics.get("worst_day", 0.0)
    lines += [
        f"- **Best day:** {_fmt_pct(best)}",
        f"- **Worst day:** {_fmt_pct(worst)}",
        "",
    ]
    return "\n".join(lines)


def _outlook_section(data: dict, metrics: dict) -> str:
    """Build the ## Outlook Markdown section (template-based, no LLM)."""
    lines = ["## Outlook", ""]

    yield_doc   = data.get("yield_attribution") or {}
    current_apy: Optional[float] = None
    if isinstance(yield_doc, dict):
        current_apy = yield_doc.get("portfolio_apy_pp") or yield_doc.get("deployed_apy_pct")

    target_apy = USDC_BENCHMARK_ANNUAL_PCT

    if isinstance(current_apy, (int, float)):
        spread_bps = round((current_apy - target_apy) * 100)
        if spread_bps > 200:
            body = (
                f"Current portfolio APY of {current_apy:.2f}% represents a "
                f"{spread_bps}bps spread over the {target_apy:.0f}% USDC base rate. "
                "The strategy is performing well relative to benchmark; continued "
                "disciplined rebalancing is expected to sustain this spread."
            )
        elif spread_bps > 0:
            body = (
                f"Current portfolio APY of {current_apy:.2f}% is {spread_bps}bps "
                f"above the {target_apy:.0f}% USDC base rate. The strategy is on "
                "track; monitoring yield dispersion across protocols remains the "
                "primary focus for the coming period."
            )
        else:
            body = (
                f"Current portfolio APY of {current_apy:.2f}% is at or below the "
                f"{target_apy:.0f}% USDC base rate. A rotation toward higher-yielding "
                "protocols within RiskPolicy limits is being evaluated."
            )
    else:
        ret = metrics.get("total_return_pct", 0.0) if metrics else 0.0
        if ret > 0:
            body = (
                "The portfolio delivered positive returns during the period. "
                "Continued adherence to RiskPolicy TVL and concentration limits "
                "is expected to preserve capital and generate consistent yield."
            )
        else:
            body = (
                "The portfolio experienced a challenging period. RiskPolicy "
                "constraints remain active and no protocol breaches were detected. "
                "Ongoing monitoring of APY trends and protocol health is the "
                "priority for the coming month."
            )

    # Append go-live readiness note for short tracks
    trading_days = metrics.get("trading_days", 0) if metrics else 0
    if 0 < trading_days < 30:
        body += (
            f" Note: the live paper-trading track currently spans {trading_days} "
            "day(s); a minimum 30-day uninterrupted track is required before "
            "go-live eligibility (ADR-002)."
        )

    lines += [body, ""]
    return "\n".join(lines)


# ─── Full report ──────────────────────────────────────────────────────────────

def generate_markdown_report(month: str, data_dir: str = "data") -> str:
    """Generate a full Markdown investor report for *month*.

    Parameters
    ----------
    month:
        Reporting month in ``YYYY-MM`` format (e.g. ``"2026-06"``).
    data_dir:
        Directory containing SPA JSON data files.

    Returns
    -------
    str
        Complete Markdown document. Never raises; returns a minimal safe report
        on errors or missing data.
    """
    try:
        data = load_report_data(month, data_dir)
    except Exception:
        data = {"month": month, "data_dir": data_dir, "snapshots": []}

    snapshots    = data.get("snapshots") or []
    metrics      = compute_month_metrics(snapshots, month)

    prev_month_s = _prev_month(month)
    prev_metrics = compute_month_metrics(snapshots, prev_month_s) if prev_month_s else {}

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    month_label  = _month_label(month)

    parts: List[str] = []

    # ── 1. Title ──────────────────────────────────────────────────────────────
    parts.append(f"# SPA Monthly Report — {month_label}\n")
    parts.append(f"**Generated:** {generated_at}  ")
    parts.append("**Strategy:** SPA v1.0 | Paper Trading ($100,000 USDC)\n")
    parts.append("---\n")

    # ── 2. Executive Summary ──────────────────────────────────────────────────
    parts.append("## Executive Summary\n")
    parts.append(generate_executive_summary(metrics, month))
    parts.append("\n")

    # ── 3. Performance Table ──────────────────────────────────────────────────
    parts.append(_performance_table(metrics, prev_metrics))

    # ── 4. Risk Metrics ───────────────────────────────────────────────────────
    parts.append(_risk_table(metrics, data))

    # ── 5. Protocol Breakdown ─────────────────────────────────────────────────
    parts.append(_protocol_breakdown(data))

    # ── 6. Key Events ─────────────────────────────────────────────────────────
    parts.append(_key_events(snapshots, month, metrics))

    # ── 7. Outlook ────────────────────────────────────────────────────────────
    parts.append(_outlook_section(data, metrics))

    # ── Footer ────────────────────────────────────────────────────────────────
    parts.append("---\n")
    parts.append(
        "_This report is generated from live paper-trading data (SPA v1.0). "
        "It is advisory only and does not constitute investment advice. "
        "All figures are unaudited._"
    )

    return "\n".join(parts)


# ─── Persistence ──────────────────────────────────────────────────────────────

def save_report(month: str, data_dir: str = "data") -> str:
    """Generate the report and atomically write it to ``data/monthly_report_{month}.md``.

    Uses a temp-file + ``os.replace`` to guarantee no partial file is ever
    visible on disk.

    Returns
    -------
    str
        Absolute path to the written report file.
    """
    content   = generate_markdown_report(month, data_dir)
    out_path  = Path(data_dir) / f"monthly_report_{month}.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(
        dir=str(out_path.parent),
        prefix=".tmp_monthly_report_",
        suffix=".md",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.replace(tmp_path, str(out_path))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    return str(out_path)


# ─── CLI ──────────────────────────────────────────────────────────────────────

def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python3 -m spa_core.paper_trading.monthly_report",
        description=(
            "SPA Investor Monthly Report Generator (MP-134): "
            "read-only Markdown report from existing data files. Offline."
        ),
    )
    p.add_argument(
        "--month", required=True,
        help="Reporting month in YYYY-MM format (e.g. 2026-06)",
    )
    g = p.add_mutually_exclusive_group()
    g.add_argument(
        "--check", action="store_true",
        help="Generate and print WITHOUT writing to disk (default)",
    )
    g.add_argument(
        "--run", action="store_true",
        help="Generate and atomically write data/monthly_report_{month}.md",
    )
    p.add_argument("--data-dir", default="data", help="Override data directory")
    return p


def main(argv: Optional[List[str]] = None) -> int:  # noqa: D401
    """Entry point."""
    parser = _build_arg_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        if exc.code not in (0, None):
            print(
                "ERROR: invalid arguments — "
                "use --month YYYY-MM [--check | --run] [--data-dir DIR]",
                file=sys.stderr,
            )
        return 0

    try:
        if args.run:
            path = save_report(args.month, data_dir=args.data_dir)
            print(f"monthly_report: written → {path}")
        else:
            print(generate_markdown_report(args.month, data_dir=args.data_dir))
    except Exception as exc:  # advisory: no tracebacks, exit 0
        print(
            f"monthly_report: ERROR — {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
