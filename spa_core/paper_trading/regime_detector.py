#!/usr/bin/env python3
"""Market Regime Detection Engine (SPA-V429 / MP-129) — read-only / advisory.

Classifies the current DeFi yield market into one of four regimes — **BULL**,
**BEAR**, **SIDEWAYS**, or **VOLATILE** — by analysing APY time-series data
from ``data/apy_history.json``.  The verdict informs whether the allocator
should lean aggressive, neutral, or defensive (advisory only; the RiskPolicy
gate remains the binding authority).

Regime classification
=====================
Four mutually exclusive regimes, evaluated in priority order:

1. **VOLATILE**: volatility ratio > :data:`VOLATILE_RATIO_THRESHOLD` (2.0),
   regardless of trend.  Highly unstable market — defensive stance.
2. **BULL**: trend ``UP`` + volatility ``NORMAL`` or ``LOW`` + breadth ``BROAD``
   (≥ :data:`BULL_BREADTH_THRESHOLD` = 60 % of protocols trending up).
   Favourable — aggressive stance.
3. **BEAR**: trend ``DOWN`` + breadth ``BROAD`` (≥ 60 % trending down).
   Unfavourable — defensive stance.
4. **SIDEWAYS**: everything else.  Neutral stance.

Signals
=======
:func:`compute_trend` — ordinary least-squares (pure Python; no numpy) on
normalised index ``[0, 1]``.  Returns slope, R², and direction
(``UP`` / ``DOWN`` / ``FLAT``).

:func:`compute_volatility` — rolling std of day-over-day APY changes in a
``window``-day window; compares current window to full-series mean.  Returns
absolute levels, ratio, and categorical level
(``HIGH`` / ``NORMAL`` / ``LOW``).

Confidence
==========
Weighted blend of trend R² and breadth percentage:
``confidence = 0.5 × r_squared + 0.5 × breadth_pct``

Sliding history & transition matrix
====================================
:func:`regime_history` applies a sliding lookback window (step ``step_days``)
to produce a dated list of regimes.  :func:`regime_transition_matrix` counts
how frequently each regime transitions to every other (or same) regime in the
next step, useful for quantifying regime persistence.

Data source
===========
Reads ``data/apy_history.json`` via :func:`load_apy_history`.  Callers may
also pass a pre-built ``apy_history`` list directly (useful for tests and
programmatic use).

CLI (offline, exit 0 always, no tracebacks; junk args → ERROR on stderr)::

    python3 -m spa_core.paper_trading.regime_detector --check      # compute+print, no write (default)
    python3 -m spa_core.paper_trading.regime_detector --run        # + atomic write data/regime_analytics.json
    python3 -m spa_core.paper_trading.regime_detector --run --data-dir <dir>

Scope / safety: STRICTLY READ-ONLY (SPA-BL-011) and advisory only. Pure stdlib
(json/os/math/datetime/argparse/tempfile/logging/pathlib/statistics) — no
requests/web3/LLM SDK/sockets/numpy/pandas/scipy/network. It only READS
``apy_history.json`` and writes its OWN status artifact; it never moves capital
and never touches risk/execution/allocator/cycle_runner.
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from spa_core.utils.atomic import atomic_save

log = logging.getLogger("spa.paper_trading.regime_detector")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"

SCHEMA_VERSION: int = 1
SOURCE_NAME: str = "regime_detector"
STATUS_FILENAME: str = "regime_analytics.json"
APY_HISTORY_FILENAME: str = "apy_history.json"

HISTORY_MAX: int = 500

# ── classification thresholds ────────────────────────────────────────────────
VOLATILE_RATIO_THRESHOLD: float = 2.0   # vol_ratio > this → VOLATILE
BULL_BREADTH_THRESHOLD: float = 0.60    # ≥ 60 % protocols trending up → BROAD (bull)
BEAR_BREADTH_THRESHOLD: float = 0.60    # ≥ 60 % protocols trending down → BROAD (bear)
FLAT_SLOPE_THRESHOLD: float = 0.001     # |slope| < this → FLAT
HIGH_VOL_RATIO: float = 2.0             # ratio > this → HIGH (same as VOLATILE gate)
LOW_VOL_RATIO: float = 0.5              # ratio < this → LOW
VOLATILITY_WINDOW: int = 7             # days for rolling vol window

# ── safe defaults returned on bad / empty input ───────────────────────────────
_SAFE_TREND = {
    "slope": 0.0,
    "r_squared": 0.0,
    "direction": "FLAT",
}
_SAFE_VOL = {
    "current_vol": 0.0,
    "mean_vol": 0.0,
    "ratio": 1.0,
    "level": "NORMAL",
}
_SAFE_REGIME: Dict[str, Any] = {
    "regime": "SIDEWAYS",
    "confidence": 0.0,
    "signals": {
        "trend_direction": "FLAT",
        "trend_strength": 0.0,
        "volatility_level": "NORMAL",
        "volatility_ratio": 1.0,
        "breadth": "NARROW",
        "breadth_pct": 0.0,
    },
    "explanation": "Insufficient data — defaulting to SIDEWAYS / NEUTRAL.",
    "recommended_stance": "NEUTRAL",
}


# ══════════════════════════════════════════════════════════════════════════════
# Pure-math helpers
# ══════════════════════════════════════════════════════════════════════════════

def compute_trend(values: List[float]) -> Dict[str, Any]:
    """Linear regression slope on *values* with x normalised to [0, 1].

    Implements OLS in pure Python (no numpy/scipy).  x_i = i / (n-1) when
    n ≥ 2, so the slope is expressed in units of *values* per unit x-span.

    Returns::

        {
            "slope":     float,   # OLS slope (positive → up)
            "r_squared": float,   # coefficient of determination [0, 1]
            "direction": str,     # "UP" | "DOWN" | "FLAT"
        }

    Edge cases:
        - ``len(values) < 2`` → safe default (slope=0, r²=0, FLAT)
        - All x equal (impossible with normalised index when n≥2) → handled
        - Zero y variance → r²=0, slope may be non-zero if numeric noise
    """
    n = len(values)
    if n < 2:
        return dict(_SAFE_TREND)

    # Normalised x in [0, 1]
    xs = [i / (n - 1) for i in range(n)]
    ys = list(values)

    mean_x = sum(xs) / n
    mean_y = sum(ys) / n

    ss_xx = sum((x - mean_x) ** 2 for x in xs)
    ss_xy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    ss_yy = sum((y - mean_y) ** 2 for y in ys)

    if ss_xx == 0.0:
        return dict(_SAFE_TREND)

    slope = ss_xy / ss_xx

    # R² = SS_reg / SS_tot  (clamped to [0, 1] to absorb fp noise)
    if ss_yy == 0.0:
        # Perfectly flat y — r² is undefined; treat as 1.0 (perfect fit of a
        # constant, but slope=0)
        r_squared = 1.0
    else:
        r_squared = max(0.0, min(1.0, (ss_xy ** 2) / (ss_xx * ss_yy)))

    if abs(slope) < FLAT_SLOPE_THRESHOLD:
        direction = "FLAT"
    elif slope > 0:
        direction = "UP"
    else:
        direction = "DOWN"

    return {
        "slope": slope,
        "r_squared": r_squared,
        "direction": direction,
    }


def compute_volatility(
    values: List[float],
    window: int = VOLATILITY_WINDOW,
) -> Dict[str, Any]:
    """Volatility = std of day-over-day changes.

    Computes day-over-day differences (``values[i] - values[i-1]``), then:

    * **current_vol**: std of the last ``window`` differences (or fewer if the
      series is shorter).
    * **mean_vol**: std of ALL differences.
    * **ratio**: ``current_vol / mean_vol`` (1.0 if mean_vol == 0).
    * **level**: ``"HIGH"`` if ratio > :data:`HIGH_VOL_RATIO`,
      ``"LOW"`` if ratio < :data:`LOW_VOL_RATIO`, else ``"NORMAL"``.

    Returns::

        {
            "current_vol": float,
            "mean_vol":    float,
            "ratio":       float,
            "level":       str,   # "HIGH" | "NORMAL" | "LOW"
        }

    Edge cases:
        - ``len(values) < 2`` → safe default (all zeros, NORMAL)
        - Constant series → current_vol=mean_vol=0, ratio=1.0, NORMAL
    """
    if len(values) < 2:
        return dict(_SAFE_VOL)

    diffs = [values[i] - values[i - 1] for i in range(1, len(values))]

    def _std(seq: List[float]) -> float:
        if len(seq) < 2:
            return 0.0
        m = sum(seq) / len(seq)
        variance = sum((x - m) ** 2 for x in seq) / (len(seq) - 1)
        return math.sqrt(max(0.0, variance))

    # Current window: last `window` diffs
    current_diffs = diffs[-window:] if len(diffs) >= window else diffs
    current_vol = _std(current_diffs)
    mean_vol = _std(diffs)

    if mean_vol == 0.0:
        ratio = 1.0
    else:
        ratio = current_vol / mean_vol

    if ratio > HIGH_VOL_RATIO:
        level = "HIGH"
    elif ratio < LOW_VOL_RATIO:
        level = "LOW"
    else:
        level = "NORMAL"

    return {
        "current_vol": current_vol,
        "mean_vol": mean_vol,
        "ratio": ratio,
        "level": level,
    }


# ══════════════════════════════════════════════════════════════════════════════
# Per-protocol trend extraction
# ══════════════════════════════════════════════════════════════════════════════

def _extract_protocol_apys(
    records: List[Dict[str, Any]],
    cutoff_date: Optional[date] = None,
    lookback_days: int = 30,
) -> List[float]:
    """Return chronologically sorted APY values for a single protocol.

    Accepts records in two shapes:
    * ``{"date": "YYYY-MM-DD", "protocol": str, "apy": float}``
    * ``{"ts": "...", "apy": float}``

    Only numeric APY values within the lookback window are included.
    """
    if cutoff_date is None:
        cutoff_date = date.today()
    start_date = cutoff_date - timedelta(days=lookback_days - 1)

    result: List[Tuple[date, float]] = []
    for r in records:
        if not isinstance(r, dict):
            continue
        apy = r.get("apy")
        if not isinstance(apy, (int, float)) or not math.isfinite(apy):
            continue
        # Parse date from "date" or "ts" field
        raw_date = r.get("date") or r.get("ts") or ""
        try:
            rec_date = date.fromisoformat(str(raw_date)[:10])
        except ValueError:
            continue
        if start_date <= rec_date <= cutoff_date:
            result.append((rec_date, float(apy)))

    result.sort(key=lambda t: t[0])
    return [v for _, v in result]


def _group_by_protocol(
    apy_history: List[Dict[str, Any]],
) -> Dict[str, List[Dict[str, Any]]]:
    """Group flat apy_history records by ``protocol`` field."""
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for r in apy_history:
        if not isinstance(r, dict):
            continue
        proto = r.get("protocol")
        if not proto or not isinstance(proto, str):
            continue
        groups.setdefault(proto, []).append(r)
    return groups


# ══════════════════════════════════════════════════════════════════════════════
# Main detection logic
# ══════════════════════════════════════════════════════════════════════════════

def detect_regime(
    apy_history: List[Dict[str, Any]],
    lookback_days: int = 30,
    _cutoff_date: Optional[date] = None,
) -> Dict[str, Any]:
    """Classify current DeFi yield market regime.

    Parameters
    ----------
    apy_history:
        Flat list of records ``{"date": "YYYY-MM-DD", "protocol": str,
        "apy": float}``.  Records outside the lookback window are ignored.
    lookback_days:
        How many calendar days of history to consider (default 30).
    _cutoff_date:
        Internal/test override for "today".  When ``None``, uses
        ``date.today()``.

    Returns
    -------
    dict with keys:
        ``regime``, ``confidence``, ``signals``, ``explanation``,
        ``recommended_stance``.
    """
    if not apy_history:
        result = dict(_SAFE_REGIME)
        result["explanation"] = "No APY history provided — defaulting to SIDEWAYS / NEUTRAL."
        return result

    cutoff = _cutoff_date or date.today()

    # Group records by protocol
    by_proto = _group_by_protocol(apy_history)
    if not by_proto:
        result = dict(_SAFE_REGIME)
        result["explanation"] = "No valid protocol records — defaulting to SIDEWAYS / NEUTRAL."
        return result

    # Per-protocol trend direction
    proto_directions: List[str] = []
    all_values: List[float] = []

    for proto, records in by_proto.items():
        vals = _extract_protocol_apys(records, cutoff_date=cutoff, lookback_days=lookback_days)
        if len(vals) < 2:
            # Single observation — direction undetermined; treat as FLAT
            proto_directions.append("FLAT")
            all_values.extend(vals)
            continue
        tr = compute_trend(vals)
        proto_directions.append(tr["direction"])
        all_values.extend(vals)

    n_protocols = len(proto_directions)

    # ── Aggregate trend across all APY values ─────────────────────────────────
    # Build a combined chronological APY series (all protocols, sorted by date)
    combined_records: List[Tuple[date, float]] = []
    start_date = cutoff - timedelta(days=lookback_days - 1)
    for r in apy_history:
        if not isinstance(r, dict):
            continue
        apy = r.get("apy")
        if not isinstance(apy, (int, float)) or not math.isfinite(apy):
            continue
        raw_date = r.get("date") or r.get("ts") or ""
        try:
            rec_date = date.fromisoformat(str(raw_date)[:10])
        except ValueError:
            continue
        if start_date <= rec_date <= cutoff:
            combined_records.append((rec_date, float(apy)))

    combined_records.sort(key=lambda t: t[0])
    combined_vals = [v for _, v in combined_records]

    # Aggregate trend (on combined series) — used for overall direction
    agg_trend = compute_trend(combined_vals) if len(combined_vals) >= 2 else dict(_SAFE_TREND)
    trend_direction: str = agg_trend["direction"]
    trend_strength: float = abs(agg_trend["slope"])
    # Normalise trend_strength to [0, 1] using a rough scale:
    # slope is in APY-percentage-points per normalised unit; cap at 20pp → 1.0
    _SLOPE_CAP = 20.0
    trend_strength_norm = min(1.0, trend_strength / _SLOPE_CAP) if _SLOPE_CAP > 0 else 0.0
    r_squared: float = agg_trend["r_squared"]

    # ── Volatility ────────────────────────────────────────────────────────────
    vol = compute_volatility(combined_vals) if len(combined_vals) >= 2 else dict(_SAFE_VOL)
    volatility_level: str = vol["level"]
    volatility_ratio: float = vol["ratio"]

    # ── Breadth ───────────────────────────────────────────────────────────────
    n_up = proto_directions.count("UP")
    n_down = proto_directions.count("DOWN")

    if n_protocols == 0:
        breadth_up_pct = 0.0
        breadth_down_pct = 0.0
    else:
        breadth_up_pct = n_up / n_protocols
        breadth_down_pct = n_down / n_protocols

    # Breadth label depends on the dominant direction for regime context
    if trend_direction == "UP":
        dominant_breadth_pct = breadth_up_pct
    elif trend_direction == "DOWN":
        dominant_breadth_pct = breadth_down_pct
    else:
        dominant_breadth_pct = max(breadth_up_pct, breadth_down_pct)

    breadth_label = "BROAD" if dominant_breadth_pct >= BULL_BREADTH_THRESHOLD else "NARROW"

    # ── Regime classification (priority order) ────────────────────────────────
    if volatility_ratio > VOLATILE_RATIO_THRESHOLD:
        regime = "VOLATILE"
    elif (
        trend_direction == "UP"
        and volatility_level in ("NORMAL", "LOW")
        and breadth_up_pct >= BULL_BREADTH_THRESHOLD
    ):
        regime = "BULL"
    elif trend_direction == "DOWN" and breadth_down_pct >= BEAR_BREADTH_THRESHOLD:
        regime = "BEAR"
    else:
        regime = "SIDEWAYS"

    # ── Confidence: weighted blend of r² and breadth ─────────────────────────
    confidence = max(0.0, min(1.0, 0.5 * r_squared + 0.5 * dominant_breadth_pct))

    # ── Recommended stance ────────────────────────────────────────────────────
    if regime == "BULL":
        stance = "AGGRESSIVE"
    elif regime in ("BEAR", "VOLATILE"):
        stance = "DEFENSIVE"
    else:
        stance = "NEUTRAL"

    # ── Human-readable explanation ────────────────────────────────────────────
    explanation_parts = [
        f"Regime: {regime}.",
        f"Trend: {trend_direction} (R²={r_squared:.2f}, strength={trend_strength_norm:.2f}).",
        f"Volatility: {volatility_level} (ratio={volatility_ratio:.2f}).",
        f"Breadth: {breadth_label} ({dominant_breadth_pct:.0%} of {n_protocols} protocol(s) "
        f"trending {trend_direction if trend_direction != 'FLAT' else 'flat/mixed'}).",
        f"Stance: {stance}.",
    ]
    explanation = "  ".join(explanation_parts)

    return {
        "regime": regime,
        "confidence": round(confidence, 4),
        "signals": {
            "trend_direction": trend_direction,
            "trend_strength": round(trend_strength_norm, 4),
            "volatility_level": volatility_level,
            "volatility_ratio": round(volatility_ratio, 4),
            "breadth": breadth_label,
            "breadth_pct": round(dominant_breadth_pct, 4),
        },
        "explanation": explanation,
        "recommended_stance": stance,
    }


# ══════════════════════════════════════════════════════════════════════════════
# Sliding-window history
# ══════════════════════════════════════════════════════════════════════════════

def regime_history(
    apy_history: List[Dict[str, Any]],
    window_days: int = 30,
    step_days: int = 7,
    _end_date: Optional[date] = None,
) -> List[Dict[str, Any]]:
    """Compute regimes over a sliding window.

    Walks backwards from *_end_date* (default: today) in ``step_days``
    increments, calling :func:`detect_regime` for each window.

    Returns a list of dicts (chronological order)::

        [{"date": "YYYY-MM-DD", "regime": str, "confidence": float}, ...]

    The list covers all windows that have at least one data point.
    """
    if not apy_history:
        return []

    end = _end_date or date.today()

    # Find earliest date in apy_history to bound the walk
    earliest: Optional[date] = None
    for r in apy_history:
        if not isinstance(r, dict):
            continue
        raw = r.get("date") or r.get("ts") or ""
        try:
            d = date.fromisoformat(str(raw)[:10])
            if earliest is None or d < earliest:
                earliest = d
        except ValueError:
            continue

    if earliest is None:
        return []

    steps: List[Dict[str, Any]] = []
    cutoff = end
    while cutoff >= earliest:
        result = detect_regime(apy_history, lookback_days=window_days, _cutoff_date=cutoff)
        steps.append(
            {
                "date": cutoff.isoformat(),
                "regime": result["regime"],
                "confidence": result["confidence"],
            }
        )
        cutoff = cutoff - timedelta(days=step_days)

    steps.reverse()  # chronological order
    return steps


# ══════════════════════════════════════════════════════════════════════════════
# Transition matrix
# ══════════════════════════════════════════════════════════════════════════════

def regime_transition_matrix(
    regime_history_result: List[Dict[str, Any]],
) -> Dict[str, Dict[str, int]]:
    """Count regime-to-regime transitions in a regime history list.

    Parameters
    ----------
    regime_history_result:
        Output of :func:`regime_history` — list of
        ``{"date": str, "regime": str, ...}`` dicts.

    Returns
    -------
    Nested dict ``{from_regime: {to_regime: count}}``.  Only regimes that
    actually appear as ``from`` states are present as outer keys.  An empty
    input or single-element input returns ``{}``.

    Example::

        {
          "BULL":     {"BULL": 3, "SIDEWAYS": 1},
          "SIDEWAYS": {"BEAR": 2},
        }
    """
    matrix: Dict[str, Dict[str, int]] = {}
    for i in range(len(regime_history_result) - 1):
        from_r = regime_history_result[i].get("regime", "SIDEWAYS")
        to_r = regime_history_result[i + 1].get("regime", "SIDEWAYS")
        if from_r not in matrix:
            matrix[from_r] = {}
        matrix[from_r][to_r] = matrix[from_r].get(to_r, 0) + 1
    return matrix


# ══════════════════════════════════════════════════════════════════════════════
# Data I/O
# ══════════════════════════════════════════════════════════════════════════════

def load_apy_history(data_dir: Path) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Load and flatten ``apy_history.json`` into a list of records.

    Accepts two formats:

    1. **Flat list**: ``[{"date": ..., "protocol": ..., "apy": ...}, ...]``
    2. **Dict with protocol_history key**:
       ``{"protocol_history": {"slug": [{"ts": ..., "apy": ...}, ...]}}``

    Returns ``(records, error_note)``; ``error_note`` is ``None`` on success.
    """
    path = data_dir / APY_HISTORY_FILENAME
    if not path.exists():
        return [], f"File not found: {path}"
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        return [], f"Cannot read {path}: {exc}"

    if isinstance(data, list):
        return data, None

    if isinstance(data, dict) and "protocol_history" in data:
        ph = data["protocol_history"]
        if not isinstance(ph, dict):
            return [], "protocol_history is not a dict"
        flat: List[Dict[str, Any]] = []
        for slug, records in ph.items():
            if not isinstance(records, list):
                continue
            for rec in records:
                if isinstance(rec, dict):
                    enriched = dict(rec)
                    enriched["protocol"] = slug
                    # Normalise "ts" → "date"
                    if "ts" in enriched and "date" not in enriched:
                        enriched["date"] = enriched["ts"][:10]
                    flat.append(enriched)
        return flat, None

    return [], "Unrecognised apy_history.json format"


def content_fingerprint(doc: Dict[str, Any]) -> str:
    """Stable MD5 of a JSON document excluding volatile keys."""
    import hashlib

    def _strip(obj: Any) -> Any:
        if isinstance(obj, dict):
            return {
                k: _strip(v)
                for k, v in obj.items()
                if k not in ("generated_at", "history")
            }
        if isinstance(obj, list):
            return [_strip(x) for x in obj]
        return obj

    stable = json.dumps(_strip(doc), sort_keys=True, separators=(",", ":"))
    return hashlib.md5(stable.encode()).hexdigest()


def build_regime_analytics(data_dir: Path) -> Dict[str, Any]:
    """Build the full regime analytics document.  NEVER raises."""
    now_str = datetime.now(timezone.utc).isoformat()
    notes: List[str] = []

    apy_history, err = load_apy_history(data_dir)
    if err:
        notes.append(err)

    regime_result: Dict[str, Any]
    if not apy_history:
        regime_result = dict(_SAFE_REGIME)
        regime_result["explanation"] = (
            notes[0] if notes else "No APY history available."
        )
    else:
        try:
            regime_result = detect_regime(apy_history, lookback_days=30)
        except Exception as exc:  # pragma: no cover
            notes.append(f"detect_regime error: {exc}")
            regime_result = dict(_SAFE_REGIME)
            regime_result["explanation"] = f"Error during detection: {exc}"

    hist: List[Dict[str, Any]] = []
    if apy_history:
        try:
            hist = regime_history(apy_history, window_days=30, step_days=7)
        except Exception as exc:  # pragma: no cover
            notes.append(f"regime_history error: {exc}")

    trans: Dict[str, Any] = {}
    if len(hist) >= 2:
        try:
            trans = regime_transition_matrix(hist)
        except Exception as exc:  # pragma: no cover
            notes.append(f"transition_matrix error: {exc}")

    doc: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "source": SOURCE_NAME,
        "meta": {
            "generated_at": now_str,
            "data_dir": str(data_dir),
        },
        "available": bool(apy_history),
        "current": regime_result,
        "history": hist[-30:] if hist else [],  # last 30 windows
        "transition_matrix": trans,
        "notes": notes,
    }
    return doc


def write_status(doc: Dict[str, Any], data_dir: Path) -> str:
    """Atomically write regime analytics to data_dir.

    Returns ``"DATA_WRITTEN"`` or ``"DATA_UNCHANGED"`` (idempotent).
    Idempotency compares content fingerprints excluding the volatile
    ``meta.generated_at``, ``history``, and ``_run_history`` keys so that
    repeated calls with identical analytic content return DATA_UNCHANGED.
    """
    out_path = data_dir / STATUS_FILENAME

    existing_history: List[Any] = []
    existing_fp: Optional[str] = None

    if out_path.exists():
        try:
            existing_raw = json.loads(out_path.read_text(encoding="utf-8"))
            existing_history = existing_raw.get("_run_history", [])
            # Strip _run_history before fingerprinting so the comparison is
            # based solely on analytic content, not on the run-log boilerplate.
            existing_for_fp = {k: v for k, v in existing_raw.items() if k != "_run_history"}
            existing_fp = content_fingerprint(existing_for_fp)
        except Exception:
            existing_history = []

    new_fp = content_fingerprint(doc)

    if existing_fp == new_fp:
        return "DATA_UNCHANGED"

    # Append a slim history entry (ring-buffer)
    run_entry = {
        "generated_at": doc["meta"]["generated_at"],
        "regime": doc["current"].get("regime", "SIDEWAYS"),
        "fingerprint": new_fp,
    }
    existing_history.append(run_entry)
    if len(existing_history) > HISTORY_MAX:
        existing_history = existing_history[-HISTORY_MAX:]

    doc_to_write = dict(doc)
    doc_to_write["_run_history"] = existing_history

    atomic_save(doc_to_write, str(out_path))
    return "DATA_WRITTEN"


# ══════════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════════

def _main(argv: Optional[List[str]] = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    parser = argparse.ArgumentParser(
        description="Market Regime Detection Engine (MP-129)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="Compute and atomically write data/regime_analytics.json",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Compute and print; do NOT write (default if neither flag given)",
    )
    parser.add_argument(
        "--data-dir",
        default=str(_DEFAULT_DATA_DIR),
        help="Path to data directory (default: %(default)s)",
    )

    try:
        args = parser.parse_args(argv)
    except SystemExit:
        sys.stderr.write("ERROR: invalid arguments\n")
        sys.exit(0)

    data_dir = Path(args.data_dir)

    doc = build_regime_analytics(data_dir)
    print(json.dumps(doc, indent=2, ensure_ascii=False))

    if args.run:
        try:
            result = write_status(doc, data_dir)
            log.info("%s → %s", STATUS_FILENAME, result)
        except Exception as exc:  # pragma: no cover
            sys.stderr.write(f"ERROR: write failed: {exc}\n")


if __name__ == "__main__":
    _main()
