#!/usr/bin/env python3
"""Alpha Persistence & Decay Curve (SPA-V430 / MP-130) — read-only / advisory.

Measures how long "alpha" persists after entering a protocol: does the high APY
last 1 day? 7 days? 30 days? This informs the strategy how often to rebalance
by computing a decay_curve (median decay_ratio per lag), interpolating a
half_life_days (where median decay_ratio drops to 0.5), and recommending a
rebalance check frequency.

Input shapes
============
``apy_history``: list of dicts ``[{date: str, protocol: str, apy: float}, ...]``
  — the raw APY time series, one record per (date, protocol) observation.

``entry_events``: list of dicts ``[{date: str, protocol: str, entry_apy: float}, ...]``
  — moments when the strategy entered (or increased exposure to) a protocol, with
  the APY observed at entry (t+0 benchmark).

Public API
==========
- :func:`compute_decay_curve`           — aggregate decay across all protocols
- :func:`analyze_protocol_alpha_persistence` — per-protocol decay
- :func:`compute_rebalance_frequency_recommendation` — actionable check interval

Verdicts
========
- ``half_life > 14 d`` → ``"STABLE"``
- ``7 ≤ half_life ≤ 14 d`` → ``"MODERATE_DECAY"``
- ``half_life < 7 d`` → ``"FAST_DECAY"``
- No usable data → ``"INSUFFICIENT_DATA"``
- Never reaches 0.5 → ``"STABLE"`` (half_life returned as ``None``)

Scope / safety: STRICTLY READ-ONLY (SPA-BL-011) and advisory only. Pure stdlib
(json/os/math/datetime/argparse/tempfile/logging/pathlib) — no
requests/web3/LLM SDK/numpy/pandas/scipy/sockets/network. Never moves capital;
never touches risk/execution/allocator/cycle_runner.
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from spa_core.utils.atomic import atomic_save

log = logging.getLogger("spa.analytics_lab.alpha_decay")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"

SCHEMA_VERSION: int = 1
SOURCE_NAME: str = "alpha_decay"
STATUS_FILENAME: str = "alpha_decay.json"
APY_HISTORY_FILENAME: str = "apy_history.json"
TRADES_FILENAME: str = "trades.json"

HISTORY_MAX: int = 500
DEFAULT_LAGS: List[int] = [1, 7, 14, 30]

# Verdict thresholds (half_life in days)
HALF_LIFE_STABLE_THRESHOLD: float = 14.0      # > 14 → STABLE
HALF_LIFE_MODERATE_THRESHOLD: float = 7.0     # 7..14 → MODERATE_DECAY; < 7 → FAST_DECAY

DISCLAIMER = "NOT investment advice"
REAL_TRACK_START = "2026-06-10"


# ─── Tolerant helpers ─────────────────────────────────────────────────────────


def _num(value: Any) -> Optional[float]:
    """Finite float or None. bool is not a number; NaN/inf are not data."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    f = float(value)
    if not math.isfinite(f):
        return None
    return f


def _valid_date(value: Any) -> bool:
    """True iff value is an ISO YYYY-MM-DD (prefix) date string."""
    if not isinstance(value, str) or len(value) < 10:
        return False
    try:
        from datetime import date
        date.fromisoformat(value[:10])
        return True
    except ValueError:
        return False


def _date_str(value: Any) -> Optional[str]:
    """Return the YYYY-MM-DD prefix of a valid date string, else None."""
    if not _valid_date(value):
        return None
    return str(value)[:10]


def _round(value: Optional[float], ndigits: int = 6) -> Optional[float]:
    return None if value is None else round(value, ndigits)


def _read_json(path: Path) -> Any:
    """Read JSON tolerantly: missing/broken file → None, never raises."""
    path = Path(path)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def _atomic_write_json(path: Path, obj: Any) -> None:
    """Atomic JSON write via centralized atomic_save (MP-1453)."""
    atomic_save(obj, str(path))
def _build_apy_index(
    apy_history: List[Dict[str, Any]]
) -> Dict[Tuple[str, str], float]:
    """Build a (date, protocol) → apy lookup dict from apy_history.

    Invalid records (missing date, protocol, or apy) are silently skipped.
    """
    index: Dict[Tuple[str, str], float] = {}
    if not isinstance(apy_history, list):
        return index
    for record in apy_history:
        if not isinstance(record, dict):
            continue
        d = _date_str(record.get("date"))
        protocol = record.get("protocol")
        apy = _num(record.get("apy"))
        if d is None or not isinstance(protocol, str) or not protocol or apy is None:
            continue
        index[(d, protocol)] = apy
    return index


def _dates_sorted(apy_index: Dict[Tuple[str, str], float]) -> List[str]:
    """Return sorted unique date strings from the APY index."""
    return sorted({d for d, _ in apy_index})


def _date_offset(date_str: str, lag_days: int, all_dates: List[str]) -> Optional[str]:
    """Return the closest date in all_dates that is exactly lag_days after date_str.

    We do a simple ISO string comparison after computing the target date.
    Returns None if no matching date exists in all_dates.
    """
    from datetime import date, timedelta
    try:
        d0 = date.fromisoformat(date_str)
    except ValueError:
        return None
    target = (d0 + timedelta(days=lag_days)).isoformat()
    if target in all_dates:
        return target
    return None


# ─── Core analytics ───────────────────────────────────────────────────────────


def _median(values: List[float]) -> Optional[float]:
    """Pure-stdlib median. Returns None for empty list."""
    if not values:
        return None
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2 == 1:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2.0


def _interpolate_half_life(
    decay_curve: List[Dict[str, Any]]
) -> Optional[float]:
    """Interpolate lag where median_decay_ratio = 0.5.

    Uses linear interpolation between the two adjacent lags bracketing 0.5.
    Returns None if the ratio never drops to 0.5 (STABLE case).
    Returns 0.0 if ratio is already ≤ 0.5 at the first lag.
    """
    # Filter to valid points
    pts = [
        (p["lag_days"], p["median_decay_ratio"])
        for p in decay_curve
        if p.get("median_decay_ratio") is not None
    ]
    if not pts:
        return None
    pts.sort(key=lambda x: x[0])

    # Add implicit t=0, ratio=1.0 as anchor
    augmented = [(0, 1.0)] + pts

    for i in range(1, len(augmented)):
        lag_prev, ratio_prev = augmented[i - 1]
        lag_curr, ratio_curr = augmented[i]
        if ratio_curr <= 0.5:
            # Linear interpolation
            if ratio_prev == ratio_curr:
                return float(lag_prev)
            t = (0.5 - ratio_prev) / (ratio_curr - ratio_prev)
            return lag_prev + t * (lag_curr - lag_prev)
    # Never reached 0.5
    return None


def _verdict_from_half_life(half_life: Optional[float]) -> str:
    """Map half_life_days to a verdict string."""
    if half_life is None:
        return "STABLE"
    if half_life > HALF_LIFE_STABLE_THRESHOLD:
        return "STABLE"
    if half_life >= HALF_LIFE_MODERATE_THRESHOLD:
        return "MODERATE_DECAY"
    return "FAST_DECAY"


def _explanation_from_verdict(verdict: str, half_life: Optional[float]) -> str:
    """Human-readable explanation for a verdict."""
    if verdict == "INSUFFICIENT_DATA":
        return (
            "Not enough entry events to compute alpha decay. "
            "Collect more trade history before drawing conclusions."
        )
    if verdict == "STABLE":
        if half_life is None:
            return (
                "Alpha does not decay to 50% within the observed lags. "
                "APY advantage appears durable; daily rebalancing is not critical."
            )
        return (
            f"Alpha half-life is {half_life:.1f} days (>14 d). "
            "APY advantage is durable; rebalancing every ~7 days or less is sufficient."
        )
    if verdict == "MODERATE_DECAY":
        return (
            f"Alpha half-life is {half_life:.1f} days (7–14 d). "
            "APY advantage degrades at a moderate pace; weekly rebalancing checks are advisable."
        )
    # FAST_DECAY
    return (
        f"Alpha half-life is {half_life:.1f} days (<7 d). "
        "APY advantage decays quickly; frequent rebalancing (every 1–3 days) is needed "
        "to capture the full yield premium."
    )


def compute_decay_curve(
    apy_history: List[Dict[str, Any]],
    entry_events: List[Dict[str, Any]],
    lags: Optional[List[int]] = None,
) -> Dict[str, Any]:
    """Compute the alpha persistence decay curve across all protocols.

    For each entry event, compute APY at t+lag vs APY at t+0.
        decay_ratio = APY[t+lag] / APY[t+0]   (capped at [0, 2])

    Parameters
    ----------
    apy_history:
        List of ``{date: str, protocol: str, apy: float}`` records.
    entry_events:
        List of ``{date: str, protocol: str, entry_apy: float}`` records.
    lags:
        Lag offsets in days (default: [1, 7, 14, 30]).

    Returns
    -------
    dict with keys:
        - ``decay_curve``: list of ``{lag_days, median_decay_ratio, n_samples}``
        - ``half_life_days``: float or None (where median_decay_ratio = 0.5)
        - ``verdict``: ``"STABLE"`` | ``"MODERATE_DECAY"`` | ``"FAST_DECAY"``
          | ``"INSUFFICIENT_DATA"``
        - ``explanation``: human-readable advisory string
    """
    if lags is None:
        lags = DEFAULT_LAGS

    apy_index = _build_apy_index(apy_history)
    all_dates_set = {d for d, _ in apy_index}

    # Validate entry events
    valid_entries = []
    if isinstance(entry_events, list):
        for ev in entry_events:
            if not isinstance(ev, dict):
                continue
            d = _date_str(ev.get("date"))
            protocol = ev.get("protocol")
            entry_apy = _num(ev.get("entry_apy"))
            if d is None or not isinstance(protocol, str) or not protocol:
                continue
            if entry_apy is None or entry_apy == 0.0:
                continue  # can't compute ratio if t+0 APY is zero
            valid_entries.append((d, protocol, entry_apy))

    if not valid_entries:
        return {
            "decay_curve": [],
            "half_life_days": None,
            "verdict": "INSUFFICIENT_DATA",
            "explanation": _explanation_from_verdict("INSUFFICIENT_DATA", None),
        }

    # Compute per-lag ratios
    lag_ratios: Dict[int, List[float]] = {lag: [] for lag in lags}
    all_dates_list = sorted(all_dates_set)

    for entry_date, protocol, entry_apy in valid_entries:
        for lag in lags:
            lag_date = _date_offset(entry_date, lag, all_dates_list)
            if lag_date is None:
                continue  # lag exceeds available history — skip
            lag_apy = apy_index.get((lag_date, protocol))
            if lag_apy is None:
                continue  # no data for this protocol at lag date
            ratio = lag_apy / entry_apy
            ratio = max(0.0, min(2.0, ratio))  # cap at [0, 2]
            lag_ratios[lag].append(ratio)

    # Build decay_curve
    decay_curve = []
    for lag in sorted(lags):
        ratios = lag_ratios[lag]
        median_ratio = _median(ratios)
        decay_curve.append({
            "lag_days": lag,
            "median_decay_ratio": _round(median_ratio, 6) if median_ratio is not None else None,
            "n_samples": len(ratios),
        })

    half_life = _interpolate_half_life(decay_curve)
    verdict = _verdict_from_half_life(half_life)

    # Check if we actually had no usable samples at any lag
    total_samples = sum(p["n_samples"] for p in decay_curve)
    if total_samples == 0:
        return {
            "decay_curve": decay_curve,
            "half_life_days": None,
            "verdict": "INSUFFICIENT_DATA",
            "explanation": _explanation_from_verdict("INSUFFICIENT_DATA", None),
        }

    return {
        "decay_curve": decay_curve,
        "half_life_days": _round(half_life, 4) if half_life is not None else None,
        "verdict": verdict,
        "explanation": _explanation_from_verdict(verdict, half_life),
    }


def analyze_protocol_alpha_persistence(
    apy_history: List[Dict[str, Any]],
    entry_events: List[Dict[str, Any]],
    protocol: str,
    lags: Optional[List[int]] = None,
) -> Dict[str, Any]:
    """Compute alpha decay curve for a single protocol.

    Filters apy_history and entry_events to the specified protocol, then
    delegates to :func:`compute_decay_curve`.

    Returns the same schema as :func:`compute_decay_curve` plus ``n_entries``
    (number of entry events for this protocol before APY zero-filtering).
    """
    if lags is None:
        lags = DEFAULT_LAGS

    # Filter to this protocol
    proto_apy = [
        r for r in (apy_history or [])
        if isinstance(r, dict) and r.get("protocol") == protocol
    ]
    proto_entries = [
        e for e in (entry_events or [])
        if isinstance(e, dict) and e.get("protocol") == protocol
    ]
    n_entries = len(proto_entries)

    result = compute_decay_curve(proto_apy, proto_entries, lags=lags)
    result["n_entries"] = n_entries
    return result


def compute_rebalance_frequency_recommendation(
    decay_results: Dict[str, Any],
) -> Dict[str, Any]:
    """Recommend a rebalance check interval based on alpha half-life.

    Parameters
    ----------
    decay_results:
        Output of :func:`compute_decay_curve` or
        :func:`analyze_protocol_alpha_persistence`.

    Returns
    -------
    dict with keys:
        - ``recommended_check_days``: int in [1, 30]
          (half_life / 2, clamped; defaults to 7 for INSUFFICIENT_DATA/STABLE-no-half-life)
        - ``reasoning``: human-readable explanation
    """
    verdict = decay_results.get("verdict", "INSUFFICIENT_DATA")
    half_life = decay_results.get("half_life_days")

    if verdict == "INSUFFICIENT_DATA" or half_life is None:
        # Conservative default: weekly check
        check_days = 7
        reasoning = (
            "No reliable half-life estimate available. "
            "Defaulting to a weekly rebalance check as a conservative baseline."
        )
    else:
        raw = half_life / 2.0
        check_days = max(1, min(30, int(math.ceil(raw))))
        reasoning = (
            f"Alpha half-life is {half_life:.1f} days ({verdict}). "
            f"Recommended check interval is half_life / 2 = {raw:.1f} d → "
            f"{check_days} day(s), clamped to [1, 30]."
        )

    return {
        "recommended_check_days": check_days,
        "reasoning": reasoning,
    }


# ─── Top-level build (file-backed, CLI-facing) ────────────────────────────────


def build_alpha_decay(
    data_dir: Optional[str] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Build the alpha-decay analytics document from disk. Stable schema, never raises."""
    ddir = Path(data_dir) if data_dir is not None else _DEFAULT_DATA_DIR
    now = now or datetime.now(timezone.utc)
    notes: List[str] = []

    apy_doc = _read_json(ddir / APY_HISTORY_FILENAME)
    if apy_doc is None:
        notes.append(f"{APY_HISTORY_FILENAME} missing or unreadable")
        apy_history: List[Dict[str, Any]] = []
    else:
        raw = apy_doc if isinstance(apy_doc, list) else apy_doc.get("protocol_history", {})
        if isinstance(raw, dict):
            # Flatten {slug: [{ts, apy}, ...]} into [{date, protocol, apy}, ...]
            apy_history = []
            for slug, series in raw.items():
                if not isinstance(series, list):
                    continue
                for rec in series:
                    if not isinstance(rec, dict):
                        continue
                    ts = rec.get("ts") or rec.get("date")
                    apy = _num(rec.get("apy"))
                    if ts and apy is not None:
                        apy_history.append({
                            "date": str(ts)[:10],
                            "protocol": slug,
                            "apy": apy,
                        })
        elif isinstance(raw, list):
            apy_history = raw
        else:
            apy_history = []

    # Build entry_events from trades.json
    trades_doc = _read_json(ddir / TRADES_FILENAME)
    entry_events: List[Dict[str, Any]] = []
    if isinstance(trades_doc, list):
        for trade in trades_doc:
            if not isinstance(trade, dict):
                continue
            if trade.get("action") not in ("buy", "enter", "increase", "rebalance"):
                continue
            d = _date_str(trade.get("date") or trade.get("timestamp"))
            protocol = trade.get("protocol")
            apy = _num(trade.get("apy") or trade.get("entry_apy"))
            if d and protocol and apy and apy != 0.0:
                entry_events.append({"date": d, "protocol": protocol, "entry_apy": apy})
    elif trades_doc is None:
        notes.append(f"{TRADES_FILENAME} missing or unreadable")

    meta = {
        "source": SOURCE_NAME,
        "schema_version": SCHEMA_VERSION,
        "generated_at": now.isoformat(),
        "advisory_only": True,
        "disclaimer": DISCLAIMER,
        "real_track_start": REAL_TRACK_START,
        "notes": notes,
    }

    result = compute_decay_curve(apy_history, entry_events)
    rebalance_rec = compute_rebalance_frequency_recommendation(result)

    # Per-protocol breakdown
    protocols: List[str] = sorted({
        r.get("protocol", "") for r in apy_history
        if isinstance(r, dict) and r.get("protocol")
    })
    per_protocol = {}
    for p in protocols:
        per_protocol[p] = analyze_protocol_alpha_persistence(apy_history, entry_events, p)

    return {
        "meta": meta,
        "aggregate": result,
        "rebalance_recommendation": rebalance_rec,
        "per_protocol": per_protocol,
    }


# ─── Persist (idempotent) ─────────────────────────────────────────────────────


def content_fingerprint(doc: Any) -> str:
    """Canonical fingerprint of the status CONTENT (volatile fields excluded)."""
    if not isinstance(doc, dict):
        return "<invalid>"
    core = {k: v for k, v in doc.items() if k != "history"}
    meta = core.get("meta")
    if isinstance(meta, dict):
        core["meta"] = {k: v for k, v in meta.items() if k != "generated_at"}
    return json.dumps(core, sort_keys=True, ensure_ascii=False)


def write_status(
    doc: Dict[str, Any],
    data_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Atomically write data/alpha_decay.json (tmp + os.replace).

    Idempotency: if :func:`content_fingerprint` is unchanged relative to the
    persisted status, the file is NOT rewritten.
    """
    ddir = Path(data_dir) if data_dir is not None else _DEFAULT_DATA_DIR
    path = ddir / STATUS_FILENAME
    prev = _read_json(path)
    if isinstance(prev, dict) and content_fingerprint(prev) == content_fingerprint(doc):
        log.info("alpha_decay analytics unchanged: %s", path)
        return {"path": str(path), "changed": False}

    history: List[Dict[str, Any]] = []
    if isinstance(prev, dict) and isinstance(prev.get("history"), list):
        history = [h for h in prev["history"] if isinstance(h, dict)]

    agg = doc.get("aggregate") or {}
    history.append({
        "generated_at": (doc.get("meta") or {}).get("generated_at"),
        "verdict": agg.get("verdict"),
        "half_life_days": agg.get("half_life_days"),
    })

    out = dict(doc)
    out["history"] = history[-HISTORY_MAX:]
    _atomic_write_json(path, out)
    log.info("alpha_decay analytics written: %s", path)
    return {"path": str(path), "changed": True}


# ─── CLI ──────────────────────────────────────────────────────────────────────


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python3 -m spa_core.analytics_lab.alpha_decay",
        description=(
            "Alpha Persistence & Decay Curve (SPA-V430 / MP-130): "
            "read-only / advisory. Measures how long APY alpha persists "
            "after entry. Offline."
        ),
        add_help=True,
    )
    group = p.add_mutually_exclusive_group()
    group.add_argument(
        "--check", action="store_true",
        help="compute and print the JSON analytics WITHOUT writing (default)",
    )
    group.add_argument(
        "--run", action="store_true",
        help="compute and atomically write data/alpha_decay.json",
    )
    p.add_argument("--data-dir", default=None, help="override data directory")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_arg_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        if exc.code not in (0, None):
            print(
                "ERROR: invalid arguments — use --check | --run [--data-dir DIR]",
                file=sys.stderr,
            )
        return 0

    try:
        doc = build_alpha_decay(data_dir=args.data_dir)
        if args.run:
            outcome = write_status(doc, data_dir=args.data_dir)
            agg = doc.get("aggregate") or {}
            rec = doc.get("rebalance_recommendation") or {}
            print(
                f"alpha_decay: verdict={agg.get('verdict')} "
                f"half_life={agg.get('half_life_days')}d "
                f"check_every={rec.get('recommended_check_days')}d — "
                f"{'written' if outcome['changed'] else 'unchanged (idempotent)'} "
                f"{outcome['path']}"
            )
        else:
            print(json.dumps(doc, ensure_ascii=False, indent=2))
    except Exception as exc:  # advisory: no tracebacks, exit 0
        print(
            f"alpha_decay: ERROR — {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
