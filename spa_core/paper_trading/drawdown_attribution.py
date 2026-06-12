#!/usr/bin/env python3
"""Drawdown Attribution Analyzer (SPA / MP-127) — read-only / advisory.

Decomposes each drawdown episode in the portfolio equity track by
**per-protocol contribution**, answering the question: *which protocol was
responsible for each loss?*

All five exported functions are **pure** (no I/O, no side-effects) and use
only Python stdlib. This module is advisory-only and never modifies
allocator / risk / execution / cycle state.

Functions
=========
``identify_drawdown_episodes``
    Detect peak → trough → recovery cycles from a raw equity curve
    (``list[{date, equity}]``).

``attribute_drawdown``
    Given one episode + current allocation fractions + per-protocol daily
    returns, compute ``{protocol: contribution_pct}`` (normalised to 100).

``get_worst_drawdown``
    Convenience: return the deepest episode dict from the equity curve.

``drawdown_summary``
    Aggregate statistics over all episodes: avg/max drawdown, avg duration,
    avg recovery time, total episode count.

``protocol_drawdown_contribution_history``
    Roll up a parallel list of attributions into a per-protocol profile:
    count, avg_contribution_pct, max_contribution_pct.

Safety / scope
==============
STRICTLY READ-ONLY (SPA-BL-011). Pure stdlib only — no requests / web3 /
LLM SDK / sockets / network. Never raises (contract: caller gets an empty
or None-heavy result on bad input, not an exception). LLM usage forbidden
(LLM_FORBIDDEN_AGENTS policy).
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sys
import tempfile
from datetime import date as _date
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── reuse-by-import (single source of truth) ──────────────────────────────────
# Drawdown math is reused from drawdown_analytics (NOT re-implemented here for
# the build layer); the content fingerprint is the SAME object as the canonical
# tear_sheet.content_fingerprint (proved in tests via assertIs).
from spa_core.paper_trading.drawdown_analytics import (
    detect_drawdown_episodes as _detect_drawdown_episodes,
    extract_equity_series as _extract_equity_series,
)
from spa_core.reporting.tear_sheet import content_fingerprint

log = logging.getLogger("spa.paper_trading.drawdown_attribution")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"

SCHEMA_VERSION: int = 1
SOURCE_NAME: str = "drawdown_attribution"
STATUS_FILENAME: str = "drawdown_attribution.json"
EQUITY_FILENAME: str = "equity_curve_daily.json"
POSITIONS_FILENAME: str = "current_positions.json"
DISCLAIMER: str = "NOT investment advice"
HISTORY_MAX: int = 500

# Advisory verdict thresholds: share of the WORST drawdown attributable to a
# single protocol. Vynesené v konstanty per spec.
WARN_DOMINANCE_PCT: float = 50.0   # > this share of worst DD by one protocol → warn
FAIL_DOMINANCE_PCT: float = 75.0   # ≥ this share by one protocol → fail

__all__ = [
    "identify_drawdown_episodes",
    "attribute_drawdown",
    "get_worst_drawdown",
    "drawdown_summary",
    "protocol_drawdown_contribution_history",
    "build_drawdown_attribution",
    "content_fingerprint",
    "write_status",
    "main",
    "WARN_DOMINANCE_PCT",
    "FAIL_DOMINANCE_PCT",
]


# ─── Internal helpers ─────────────────────────────────────────────────────────


def _valid_date(value: Any) -> bool:
    """True iff *value* is a parseable ISO ``YYYY-MM-DD`` string (prefix)."""
    if not isinstance(value, str) or len(value) < 10:
        return False
    try:
        _date.fromisoformat(value[:10])
        return True
    except ValueError:
        return False


def _days_between(start: Any, end: Any) -> Optional[int]:
    """Calendar days (end − start) for two ISO date strings, or ``None``."""
    if not _valid_date(start) or not _valid_date(end):
        return None
    try:
        d0 = _date.fromisoformat(str(start)[:10])
        d1 = _date.fromisoformat(str(end)[:10])
    except ValueError:
        return None
    return (d1 - d0).days


def _to_float(value: Any) -> Optional[float]:
    """Finite ``float`` from *value*, or ``None`` (bools are not numbers)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    f = float(value)
    return f if math.isfinite(f) else None


def _parse_series(equity_curve: Any) -> List[tuple]:
    """Validated, sorted ``[(date_str, equity_float), ...]`` from raw input.

    Each bar must be a dict with a valid ``date`` key and a positive finite
    ``equity`` value. Invalid / non-positive bars are silently skipped.
    Never raises.
    """
    if not isinstance(equity_curve, list):
        return []
    out = []
    for bar in equity_curve:
        if not isinstance(bar, dict):
            continue
        dt = bar.get("date")
        eq = _to_float(bar.get("equity"))
        if not _valid_date(dt) or eq is None or eq <= 0:
            continue
        out.append((str(dt)[:10], eq))
    out.sort(key=lambda x: x[0])
    return out


# ─── Public API ───────────────────────────────────────────────────────────────


def identify_drawdown_episodes(
    equity_curve: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Find all drawdown episodes (peak → trough → recovery) in *equity_curve*.

    Parameters
    ----------
    equity_curve:
        ``list[{date: str, equity: float}]``.  Each bar must have a valid
        ISO date and a positive finite equity value; other bars are skipped.

    Returns
    -------
    ``list[dict]`` — one entry per episode, chronological order:

    .. code-block:: text

        {
          start_date:    str   — date of the pre-drawdown peak
          peak_equity:   float — equity at peak
          trough_date:   str   — date of the worst intra-episode equity
          trough_equity: float — equity at trough
          recovery_date: str | None — date equity returned to ≥ peak
                                      (None if not recovered by last bar)
          drawdown_pct:  float — (trough/peak − 1) × 100, always ≤ 0
          duration_days: int | None — calendar days start_date → trough_date
        }

    Returns ``[]`` if the series has fewer than 2 valid bars or is flat /
    always rising.
    """
    series = _parse_series(equity_curve)
    if len(series) < 2:
        return []

    episodes: List[Dict[str, Any]] = []
    peak_date, peak_val = series[0]
    in_dd = False
    ep: Optional[Dict[str, Any]] = None

    for d, eq in series[1:]:
        if not in_dd:
            if eq < peak_val:
                in_dd = True
                ep = {
                    "peak_date": peak_date,
                    "peak_val": peak_val,
                    "trough_date": d,
                    "trough_val": eq,
                }
            else:
                peak_date, peak_val = d, eq  # new high-water mark
        else:
            assert ep is not None
            if eq < ep["trough_val"]:
                ep["trough_val"] = eq
                ep["trough_date"] = d
            if eq >= peak_val:  # recovered
                dd_pct = (ep["trough_val"] / ep["peak_val"] - 1.0) * 100.0
                episodes.append({
                    "start_date": ep["peak_date"],
                    "peak_equity": round(ep["peak_val"], 2),
                    "trough_date": ep["trough_date"],
                    "trough_equity": round(ep["trough_val"], 2),
                    "recovery_date": d,
                    "drawdown_pct": round(dd_pct, 6),
                    "duration_days": _days_between(ep["peak_date"], ep["trough_date"]),
                })
                in_dd = False
                ep = None
                peak_date, peak_val = d, eq

    # Unrecovered / ongoing episode at end of series
    if in_dd and ep is not None:
        dd_pct = (ep["trough_val"] / ep["peak_val"] - 1.0) * 100.0
        episodes.append({
            "start_date": ep["peak_date"],
            "peak_equity": round(ep["peak_val"], 2),
            "trough_date": ep["trough_date"],
            "trough_equity": round(ep["trough_val"], 2),
            "recovery_date": None,
            "drawdown_pct": round(dd_pct, 6),
            "duration_days": _days_between(ep["peak_date"], ep["trough_date"]),
        })

    return episodes


def attribute_drawdown(
    episode: Dict[str, Any],
    positions: Dict[str, float],
    returns_by_protocol: Dict[str, Dict[str, float]],
) -> Dict[str, float]:
    """Attribute a drawdown episode to per-protocol contributions.

    Attribution formula::

        raw[p] = positions[p] × Σ(daily_return[p][date]
                                  for date in [start_date, trough_date])
        contribution_pct[p] = raw[p] / Σ(raw.values()) × 100

    Parameters
    ----------
    episode:
        Episode dict from :func:`identify_drawdown_episodes` (needs at
        least ``start_date`` and ``trough_date``).
    positions:
        ``{protocol: allocation_fraction}`` where fractions are in [0, 1]
        and should sum to ≤ 1 (cash = remainder).  E.g.
        ``{"aave_v3": 0.40, "compound_v3": 0.35, ...}``.
    returns_by_protocol:
        ``{protocol: {date_str: daily_return}}`` where ``daily_return`` is
        a decimal (``-0.01`` = −1 %).  Dates outside the episode window
        ``[start_date, trough_date]`` are ignored.

    Returns
    -------
    ``{protocol: contribution_pct}``

    * Values sum to approximately 100.0 (floating-point tolerance).
    * A **positive** contribution_pct means the protocol caused loss.
    * A **negative** contribution_pct means the protocol had positive
      returns and partially offset the portfolio loss.
    * Protocols with ``positions[p] == 0`` always get ``0.0``.
    * If the summed raw contribution is exactly zero (no returns data),
      all protocols get an equal share of 100 %.
    * Returns ``{}`` on invalid episode or empty positions.
    """
    start = episode.get("start_date")
    trough = episode.get("trough_date")
    if not _valid_date(start) or not _valid_date(trough):
        return {}

    protocols = list(positions.keys())
    if not protocols:
        return {}

    raw: Dict[str, float] = {}
    for protocol in protocols:
        alloc = _to_float(positions.get(protocol))
        if alloc is None or alloc == 0.0:
            raw[protocol] = 0.0
            continue
        daily_rets = returns_by_protocol.get(protocol) or {}
        period_sum = sum(
            float(v)
            for k, v in daily_rets.items()
            if isinstance(k, str)
            and str(start)[:10] <= k[:10] <= str(trough)[:10]
            and isinstance(v, (int, float))
            and not isinstance(v, bool)
            and math.isfinite(float(v))
        )
        raw[protocol] = alloc * period_sum

    total = sum(raw.values())
    if total == 0.0:
        n = len(protocols)
        equal = round(100.0 / n, 4)
        return {p: equal for p in protocols}

    return {p: round(raw[p] / total * 100.0, 4) for p in protocols}


def get_worst_drawdown(equity_curve: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Return the deepest (most negative) drawdown episode.

    Parameters
    ----------
    equity_curve:
        ``list[{date: str, equity: float}]``.

    Returns
    -------
    The episode dict from :func:`identify_drawdown_episodes` with the
    lowest ``drawdown_pct``.  Returns ``{}`` if there are no episodes
    (flat / rising curve or fewer than 2 bars).
    """
    episodes = identify_drawdown_episodes(equity_curve)
    if not episodes:
        return {}
    return min(episodes, key=lambda e: e["drawdown_pct"])


def drawdown_summary(equity_curve: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute aggregate drawdown statistics for the full equity curve.

    Parameters
    ----------
    equity_curve:
        ``list[{date: str, equity: float}]``.

    Returns
    -------
    .. code-block:: text

        {
          total_episodes:     int
          max_drawdown:       float | None  — most-negative drawdown_pct
          avg_drawdown:       float | None  — mean drawdown_pct (≤ 0)
          avg_duration:       float | None  — mean peak→trough calendar days
          avg_recovery_time:  float | None  — mean trough→recovery days
                                             (only recovered episodes)
        }

    All numeric fields are ``None`` when the episode list is empty or the
    relevant sub-set (e.g. recovered episodes for recovery time) is empty.
    """
    episodes = identify_drawdown_episodes(equity_curve)
    if not episodes:
        return {
            "total_episodes": 0,
            "max_drawdown": None,
            "avg_drawdown": None,
            "avg_duration": None,
            "avg_recovery_time": None,
        }

    drawdowns = [e["drawdown_pct"] for e in episodes if e["drawdown_pct"] is not None]
    durations = [e["duration_days"] for e in episodes if e["duration_days"] is not None]

    recovery_times = []
    for e in episodes:
        if e.get("recovery_date") and e.get("trough_date"):
            days = _days_between(e["trough_date"], e["recovery_date"])
            if days is not None:
                recovery_times.append(days)

    return {
        "total_episodes": len(episodes),
        "max_drawdown": round(min(drawdowns), 6) if drawdowns else None,
        "avg_drawdown": (
            round(sum(drawdowns) / len(drawdowns), 6) if drawdowns else None
        ),
        "avg_duration": (
            round(sum(durations) / len(durations), 2) if durations else None
        ),
        "avg_recovery_time": (
            round(sum(recovery_times) / len(recovery_times), 2)
            if recovery_times
            else None
        ),
    }


def protocol_drawdown_contribution_history(
    episodes: List[Dict[str, Any]],
    attribution_history: List[Dict[str, float]],
) -> Dict[str, Dict[str, Any]]:
    """Build a per-protocol contribution profile across all drawdown episodes.

    Parameters
    ----------
    episodes:
        List of episode dicts (from :func:`identify_drawdown_episodes`).
    attribution_history:
        Parallel list of attribution dicts (one per episode, from
        :func:`attribute_drawdown`).  If shorter than ``episodes``, missing
        entries are treated as empty; extra entries are ignored.

    Returns
    -------
    ``{protocol: {count, avg_contribution_pct, max_contribution_pct}}``

    * ``count`` — number of episodes where this protocol had a *positive*
      (loss-causing) contribution_pct.
    * ``avg_contribution_pct`` — mean contribution_pct across all episodes
      where the protocol appeared (positive or negative).
    * ``max_contribution_pct`` — highest single-episode contribution_pct.

    Returns ``{}`` if *episodes* or *attribution_history* is empty.
    """
    if not episodes or not attribution_history:
        return {}

    # Collect all protocol names seen in any attribution
    all_protocols: set = set()
    for attr in attribution_history:
        if isinstance(attr, dict):
            all_protocols.update(attr.keys())

    if not all_protocols:
        return {}

    acc: Dict[str, Dict[str, Any]] = {
        p: {"count": 0, "values": []} for p in all_protocols
    }

    for i, _episode in enumerate(episodes):
        attr = attribution_history[i] if i < len(attribution_history) else {}
        if not isinstance(attr, dict):
            continue
        for protocol, contribution in attr.items():
            val = _to_float(contribution)
            if val is None:
                continue
            if protocol not in acc:
                acc[protocol] = {"count": 0, "values": []}
            acc[protocol]["values"].append(val)
            if val > 0:
                acc[protocol]["count"] += 1

    result: Dict[str, Dict[str, Any]] = {}
    for protocol, data in acc.items():
        vals = data["values"]
        result[protocol] = {
            "count": data["count"],
            "avg_contribution_pct": (
                round(sum(vals) / len(vals), 4) if vals else 0.0
            ),
            "max_contribution_pct": round(max(vals), 4) if vals else 0.0,
        }

    return result


# ──────────────────────────────────────────────────────────────────────────────
# Build layer (I/O) — read-only / advisory.  Reuses drawdown math by import.
# ──────────────────────────────────────────────────────────────────────────────


def _read_json(path: Path) -> Any:
    """Read+parse a JSON file. Never raises → returns ``None`` on any failure."""
    try:
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _is_demo(equity_doc: Any) -> Optional[bool]:
    """Honest demo flag straight from the equity source (or ``None``)."""
    if isinstance(equity_doc, dict) and isinstance(equity_doc.get("is_demo"), bool):
        return equity_doc.get("is_demo")
    return None


def _protocol_value_series(equity_doc: Any) -> Dict[str, Dict[str, float]]:
    """``{protocol: {date: usd_value}}`` from each daily bar's ``positions``.

    Reads the per-bar position breakdown embedded in ``equity_curve_daily.json``.
    Skips bars without a valid date or a dict ``positions`` block, and skips
    non-finite values. Never raises.
    """
    out: Dict[str, Dict[str, float]] = {}
    if not isinstance(equity_doc, dict):
        return out
    daily = equity_doc.get("daily")
    if not isinstance(daily, list):
        return out
    for bar in daily:
        if not isinstance(bar, dict):
            continue
        dt = bar.get("date")
        if not _valid_date(dt):
            continue
        positions = bar.get("positions")
        if not isinstance(positions, dict):
            continue
        date_key = str(dt)[:10]
        for protocol, value in positions.items():
            val = _to_float(value)
            if val is None:
                continue
            out.setdefault(protocol, {})[date_key] = val
    return out


def _returns_by_protocol(
    value_series: Dict[str, Dict[str, float]],
) -> Dict[str, Dict[str, float]]:
    """Per-protocol close-to-close daily returns (decimal) keyed by *end* date.

    For each protocol, sort its dated USD values and compute
    ``ret[date_i] = value[i] / value[i-1] - 1`` (skipping non-positive prev).
    The return is stamped on the later date so it falls inside an episode's
    ``[start_date, trough_date]`` window when that day was down. Never raises.
    """
    out: Dict[str, Dict[str, float]] = {}
    for protocol, dated in value_series.items():
        items = sorted(dated.items(), key=lambda kv: kv[0])
        rets: Dict[str, float] = {}
        for i in range(1, len(items)):
            prev_v = items[i - 1][1]
            cur_v = items[i][1]
            if prev_v > 0:
                r = cur_v / prev_v - 1.0
                if math.isfinite(r):
                    rets[items[i][0]] = r
        if rets:
            out[protocol] = rets
    return out


def _latest_allocation_fractions(
    value_series: Dict[str, Dict[str, float]],
    positions_doc: Any,
) -> Dict[str, float]:
    """``{protocol: fraction}`` summing to ≤ 1 (cash = remainder).

    Prefers the explicit ``current_positions.json`` ``positions`` block; falls
    back to the last dated value per protocol from the equity track. Fractions
    are USD / total-capital; if a ``capital_usd`` is present it is used as the
    denominator (so cash dilutes correctly), else the sum of deployed values.
    Never raises.
    """
    raw: Dict[str, float] = {}
    capital: Optional[float] = None

    if isinstance(positions_doc, dict):
        pos = positions_doc.get("positions")
        if isinstance(pos, dict):
            for protocol, value in pos.items():
                val = _to_float(value)
                if val is not None and val >= 0:
                    raw[protocol] = val
        capital = _to_float(positions_doc.get("capital_usd"))

    if not raw:
        # fall back to the last dated USD value per protocol
        for protocol, dated in value_series.items():
            if not dated:
                continue
            last_date = max(dated.keys())
            val = dated[last_date]
            if val >= 0:
                raw[protocol] = val

    if not raw:
        return {}

    deployed = sum(raw.values())
    denom = capital if (capital is not None and capital > 0) else deployed
    if denom <= 0:
        return {}
    return {p: raw[p] / denom for p in raw}


def _convert_episodes(detected: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Map drawdown_analytics episode dicts → this module's episode schema.

    ``detect_drawdown_episodes`` uses ``peak_value/trough_value/depth_pct``;
    :func:`attribute_drawdown` only needs ``start_date`` + ``trough_date`` but
    we carry through the full headline-friendly view. Never raises.
    """
    out: List[Dict[str, Any]] = []
    for e in detected:
        if not isinstance(e, dict):
            continue
        out.append({
            "start_date": e.get("start_date") or e.get("peak_date"),
            "peak_equity": e.get("peak_value"),
            "trough_date": e.get("trough_date"),
            "trough_equity": e.get("trough_value"),
            "recovery_date": e.get("recovery_date"),
            "drawdown_pct": e.get("depth_pct"),
            "duration_days": e.get("decline_days"),
            "recovery_days": e.get("recovery_days"),
            "recovered": e.get("recovered"),
        })
    return out


def _unavailable(
    reason: str,
    generated_at: str,
    notes: List[str],
    is_demo: Optional[bool] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Stable available:false envelope. Schema-compatible with the happy path."""
    doc: Dict[str, Any] = {
        "available": False,
        "reason": reason,
        "verdict": "ok",
        "verdict_reason": f"no attribution computed: {reason}",
        "notes": notes,
        "meta": {
            "generated_at": generated_at,
            "schema_version": SCHEMA_VERSION,
            "source": SOURCE_NAME,
            "advisory_only": True,
            "disclaimer": DISCLAIMER,
            "source_file": EQUITY_FILENAME,
            "is_demo": is_demo,
        },
    }
    if extra:
        doc.update(extra)
    return doc


def build_drawdown_attribution(
    data_dir: Optional[str | os.PathLike] = None,
) -> Dict[str, Any]:
    """Build the drawdown-attribution document. Stable schema, NEVER raises.

    Reads ``equity_curve_daily.json`` (reusing
    :func:`drawdown_analytics.extract_equity_series` +
    :func:`drawdown_analytics.detect_drawdown_episodes` by import) and the
    per-bar ``positions`` breakdown, derives per-protocol daily returns and
    allocation fractions (preferring ``current_positions.json``), attributes
    every drawdown episode via :func:`attribute_drawdown`, and assembles a
    headline + advisory verdict.

    Advisory verdict (dominance = share of the WORST drawdown attributable to a
    single protocol): **fail** if ≥ :data:`FAIL_DOMINANCE_PCT`, **warn** if >
    :data:`WARN_DOMINANCE_PCT`, else **ok**. ``verdict_reason`` is always set.
    """
    ddir = Path(data_dir) if data_dir is not None else _DEFAULT_DATA_DIR
    generated_at = datetime.now(timezone.utc).isoformat()
    notes: List[str] = []

    try:
        equity_doc = _read_json(ddir / EQUITY_FILENAME)
        is_demo = _is_demo(equity_doc)

        if equity_doc is None:
            notes.append(f"{EQUITY_FILENAME} missing or unreadable")
            return _unavailable("insufficient_data", generated_at, notes, is_demo)

        series = _extract_equity_series(equity_doc)
        if len(series) < 2:
            notes.append("equity series has < 2 valid bars")
            return _unavailable("insufficient_data", generated_at, notes, is_demo)

        detected = _detect_drawdown_episodes(series)
        episodes = _convert_episodes(detected)

        if not episodes:
            notes.append("no drawdown episodes in track (flat / monotonically rising)")
            return _unavailable(
                "no_episodes",
                generated_at,
                notes,
                is_demo,
                extra={
                    "track": {
                        "first_date": series[0][0],
                        "last_date": series[-1][0],
                        "num_bars": len(series),
                    },
                    "headline": _empty_headline(),
                    "episodes": [],
                    "per_protocol_contribution_history": {},
                },
            )

        # ── per-protocol returns + allocation fractions ─────────────────────
        value_series = _protocol_value_series(equity_doc)
        returns_by_protocol = _returns_by_protocol(value_series)
        positions_doc = _read_json(ddir / POSITIONS_FILENAME)
        positions = _latest_allocation_fractions(value_series, positions_doc)

        if not positions:
            notes.append("no per-protocol position breakdown available")
            return _unavailable(
                "insufficient_data",
                generated_at,
                notes,
                is_demo,
                extra={
                    "track": {
                        "first_date": series[0][0],
                        "last_date": series[-1][0],
                        "num_bars": len(series),
                    },
                },
            )

        # ── attribute every episode ─────────────────────────────────────────
        attribution_history: List[Dict[str, float]] = []
        enriched_episodes: List[Dict[str, Any]] = []
        for ep in episodes:
            attr = attribute_drawdown(ep, positions, returns_by_protocol)
            attribution_history.append(attr)
            worst_contrib = _top_contributor(attr)
            enriched_episodes.append({
                **ep,
                "attribution": attr,
                "worst_contributor": worst_contrib[0],
                "worst_contributor_pct": worst_contrib[1],
            })

        per_protocol = protocol_drawdown_contribution_history(
            episodes, attribution_history
        )

        # ── worst (deepest) drawdown + its dominant contributor ─────────────
        worst_idx, worst_ep = _deepest_episode(enriched_episodes)
        worst_attr = attribution_history[worst_idx] if worst_idx is not None else {}
        worst_contributor, worst_contributor_pct = _top_contributor(worst_attr)

        dominance = worst_contributor_pct if worst_contributor_pct is not None else 0.0

        # ── advisory verdict ────────────────────────────────────────────────
        if worst_contributor is not None and dominance >= FAIL_DOMINANCE_PCT:
            verdict = "fail"
            verdict_reason = (
                f"single protocol '{worst_contributor}' caused "
                f"{dominance:.1f}% of the worst drawdown "
                f"(≥ {FAIL_DOMINANCE_PCT:.0f}% — extreme single-protocol dominance)"
            )
        elif worst_contributor is not None and dominance > WARN_DOMINANCE_PCT:
            verdict = "warn"
            verdict_reason = (
                f"single protocol '{worst_contributor}' caused "
                f"{dominance:.1f}% of the worst drawdown "
                f"(> {WARN_DOMINANCE_PCT:.0f}% — concentrated loss attribution)"
            )
        else:
            verdict = "ok"
            verdict_reason = (
                f"no single protocol dominates the worst drawdown "
                f"(top contributor "
                f"{worst_contributor or 'n/a'} at {dominance:.1f}%)"
            )

        # ── recovery metrics across episodes ────────────────────────────────
        rec_days = [
            e["recovery_days"]
            for e in episodes
            if isinstance(e.get("recovery_days"), (int, float))
            and not isinstance(e.get("recovery_days"), bool)
        ]
        num_recovered = sum(1 for e in episodes if e.get("recovered") is True)
        num_ongoing = sum(1 for e in episodes if e.get("recovered") is False)

        depths = [
            e["drawdown_pct"]
            for e in episodes
            if isinstance(e.get("drawdown_pct"), (int, float))
            and not isinstance(e.get("drawdown_pct"), bool)
        ]

        headline = {
            "num_episodes": len(episodes),
            "num_recovered": num_recovered,
            "num_ongoing": num_ongoing,
            "max_drawdown_pct": round(min(depths), 6) if depths else None,
            "avg_drawdown_pct": (
                round(sum(depths) / len(depths), 6) if depths else None
            ),
            "avg_recovery_days": (
                round(sum(rec_days) / len(rec_days), 2) if rec_days else None
            ),
            "worst_episode": {
                "start_date": worst_ep.get("start_date") if worst_ep else None,
                "trough_date": worst_ep.get("trough_date") if worst_ep else None,
                "drawdown_pct": worst_ep.get("drawdown_pct") if worst_ep else None,
            } if worst_ep else None,
            "worst_contributor": worst_contributor,
            "worst_contributor_pct": (
                round(worst_contributor_pct, 4)
                if worst_contributor_pct is not None
                else None
            ),
        }

        return {
            "available": True,
            "verdict": verdict,
            "verdict_reason": verdict_reason,
            "track": {
                "first_date": series[0][0],
                "last_date": series[-1][0],
                "num_bars": len(series),
            },
            "protocols": sorted(positions.keys()),
            "allocation_fractions": {
                p: round(positions[p], 6) for p in sorted(positions.keys())
            },
            "headline": headline,
            "episodes": enriched_episodes,
            "per_protocol_contribution_history": per_protocol,
            "thresholds": {
                "warn_dominance_pct": WARN_DOMINANCE_PCT,
                "fail_dominance_pct": FAIL_DOMINANCE_PCT,
            },
            "notes": notes,
            "meta": {
                "generated_at": generated_at,
                "schema_version": SCHEMA_VERSION,
                "source": SOURCE_NAME,
                "advisory_only": True,
                "disclaimer": DISCLAIMER,
                "source_file": EQUITY_FILENAME,
                "is_demo": is_demo,
            },
        }

    except Exception as exc:  # last-resort guard — honest available:false
        log.exception("unexpected error in build_drawdown_attribution")
        return _unavailable(
            f"unexpected error: {exc}", generated_at, notes, None
        )


def _empty_headline() -> Dict[str, Any]:
    return {
        "num_episodes": 0,
        "num_recovered": 0,
        "num_ongoing": 0,
        "max_drawdown_pct": None,
        "avg_drawdown_pct": None,
        "avg_recovery_days": None,
        "worst_episode": None,
        "worst_contributor": None,
        "worst_contributor_pct": None,
    }


def _top_contributor(attr: Any) -> tuple:
    """``(protocol, contribution_pct)`` for the max positive (loss) contributor.

    Returns ``(None, None)`` if *attr* is empty / not a dict / has no positive
    contribution. Never raises.
    """
    if not isinstance(attr, dict) or not attr:
        return (None, None)
    best_p: Optional[str] = None
    best_v: Optional[float] = None
    for p, v in attr.items():
        val = _to_float(v)
        if val is None:
            continue
        if best_v is None or val > best_v:
            best_v = val
            best_p = p
    if best_p is None or best_v is None or best_v <= 0:
        return (None, None)
    return (best_p, best_v)


def _deepest_episode(episodes: List[Dict[str, Any]]) -> tuple:
    """``(index, episode)`` of the most-negative drawdown_pct, or ``(None, None)``."""
    best_i: Optional[int] = None
    best_v: Optional[float] = None
    for i, e in enumerate(episodes):
        v = _to_float(e.get("drawdown_pct"))
        if v is None:
            continue
        if best_v is None or v < best_v:
            best_v = v
            best_i = i
    if best_i is None:
        return (None, None)
    return (best_i, episodes[best_i])


# ──────────────────────────────────────────────────────────────────────────────
# Atomic persistence (content_fingerprint is imported from tear_sheet)
# ──────────────────────────────────────────────────────────────────────────────


def write_status(
    result: Dict[str, Any],
    data_dir: Optional[str | os.PathLike] = None,
) -> str:
    """Atomically write ``data/drawdown_attribution.json``.

    Returns ``"DATA_WRITTEN"`` | ``"DATA_UNCHANGED"``. Idempotent on unchanged
    content: the fingerprint (imported from :mod:`tear_sheet`) excludes volatile
    ``meta.generated_at`` / top-level ``history``, so a repeated ``--run`` on
    identical inputs is byte-identical and does NOT grow history. Rotation keeps
    at most :data:`HISTORY_MAX` prior entries. Tolerant of a broken previous
    artifact.
    """
    ddir = Path(data_dir) if data_dir is not None else _DEFAULT_DATA_DIR
    ddir.mkdir(parents=True, exist_ok=True)
    out_path = ddir / STATUS_FILENAME

    current_fp = content_fingerprint(result)

    existing: Dict[str, Any] = {}
    if out_path.exists():
        try:
            loaded = json.loads(out_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                existing = loaded
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

    fd, tmp_path = tempfile.mkstemp(dir=ddir, prefix=".tmp_dd_attr_")
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
            f"[drawdown_attribution] available=false "
            f"reason={result.get('reason', '?')} "
            f"verdict={result.get('verdict', '?')}"
        )
        for n in result.get("notes", []):
            print(f"  note: {n}")
        return

    print("[drawdown_attribution] available=true")
    print(f"  verdict       : {result['verdict']} — {result['verdict_reason']}")
    h = result.get("headline", {})
    print(
        f"  episodes      : {h.get('num_episodes')} "
        f"(recovered={h.get('num_recovered')}, ongoing={h.get('num_ongoing')})"
    )
    print(f"  max_drawdown  : {h.get('max_drawdown_pct')}%")
    print(
        f"  worst_contrib : {h.get('worst_contributor')} "
        f"@ {h.get('worst_contributor_pct')}%"
    )
    we = h.get("worst_episode")
    if we:
        print(
            f"  worst_episode : {we.get('start_date')} → {we.get('trough_date')} "
            f"({we.get('drawdown_pct')}%)"
        )


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Drawdown Attribution Analyzer (MP-127) — read-only / advisory",
        add_help=True,
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check",
        action="store_true",
        help="compute and print, no write (default)",
    )
    mode.add_argument(
        "--run",
        action="store_true",
        help="compute, print, and atomically write data/drawdown_attribution.json",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help="override data directory (default: <repo_root>/data)",
    )

    try:
        args, unknown = parser.parse_known_args(argv)
    except SystemExit:
        # argparse tried to exit (e.g. bad usage) — degrade to ERROR, exit 0
        print("ERROR: invalid arguments", file=sys.stderr)
        return 0

    if unknown:
        print(f"ERROR: invalid arguments: {unknown}", file=sys.stderr)
        return 0

    if args.check and args.run:
        print("ERROR: --check and --run are mutually exclusive", file=sys.stderr)
        return 0

    data_dir = Path(args.data_dir) if args.data_dir else _DEFAULT_DATA_DIR

    try:
        result = build_drawdown_attribution(data_dir)
        _print_result(result)
        if args.run:
            status = write_status(result, data_dir)
            print(f"[drawdown_attribution] write_status={status}")
    except Exception as exc:  # never raise out of main
        print(f"ERROR: {exc}", file=sys.stderr)
        return 0

    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    sys.exit(main())
