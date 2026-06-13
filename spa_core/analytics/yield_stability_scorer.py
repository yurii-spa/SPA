"""
Yield Stability Scorer (SPA-V526 / MP-602)
==========================================

Advisory, READ-ONLY analytics module that scores each adapter by the
STABILITY / PERSISTENCE of its APY over time.

This is DISTINCT from ``apy_momentum.py`` (which detects trend DIRECTION:
rising / falling / stable). Stability here means *how consistent / low-variance*
the historical yield has been: a steady 5% beats an erratic 8% for a passive
yield fund. We quantify this with the coefficient of variation (CV = stddev /
|mean|), an APY drawdown metric, and a 0..100 stability score.

Data sources (all read-only, all fail-safe)
-------------------------------------------
1. ``data/apy_history.json`` — PRIMARY. Shape::

       {"protocol_history": {"<key>": [{"ts": ISO, "apy": float,
                                        "tvl_usd": float}, ...], ...},
        "last_updated": ...}

   Each entry is a time-ordered list of points.
2. ``data/watchdog_history.json`` — supplementary ring-buffer snapshots
   (keys: schema_version, latest, snapshots). Optional.
3. ``data/adapter_status.json`` — current snapshot for the adapter universe
   and current APY (keys include an ``adapters`` list + top-level protocol
   keys). Used to know which adapters exist.

Output: ``data/yield_stability_report.json`` (ring-buffer, last 30 reports).

Design constraints (SPA-BL-011 — non-negotiable)
------------------------------------------------
* Pure stdlib + ``math`` only — NO numpy/scipy/pandas/requests/web3/openai.
* READ-ONLY over history/status files; the ONLY file written is
  ``data/yield_stability_report.json``.
* Atomic writes: tmp file + ``os.replace``; tmp cleaned up on failure; never
  leaves ``.tmp`` litter.
* Never raises on the happy path; missing / malformed / empty data degrades
  gracefully (empty / UNKNOWN, never crash).
* Deterministic: identical input → identical output.
* NOT imported from risk/, execution/, monitoring/, allocator/. Does NOT move
  money or call execution / risk / monitoring agents.

Confidence levels (driven by available history points)
------------------------------------------------------

========  ==================
Level     Data points
========  ==================
HIGH      >= 7  (MIN_POINTS_HIGH)
MEDIUM    3-6   (MIN_POINTS_MEDIUM)
LOW       1-2
UNKNOWN   0
========  ==================

Grades (driven by coefficient of variation)
-------------------------------------------

=====  ====================
Grade  CV cutoff
=====  ====================
A      cv <= CV_EXCELLENT (0.05)
B      cv <= CV_GOOD      (0.15)
C      cv <= CV_FAIR      (0.30)
D      cv >  CV_FAIR
=====  ====================

CLI
---
``python3 -m spa_core.analytics.yield_stability_scorer --check``  (default, no write)
``python3 -m spa_core.analytics.yield_stability_scorer --run``    (+ atomic save)
``python3 -m spa_core.analytics.yield_stability_scorer --data-dir PATH``
"""
from __future__ import annotations

import json
import math
import os
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# Default paths
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _PROJECT_ROOT / "data"
_APY_HISTORY_FILE = "apy_history.json"
_WATCHDOG_HISTORY_FILE = "watchdog_history.json"
_ADAPTER_STATUS_FILE = "adapter_status.json"
_STABILITY_REPORT_FILE = "yield_stability_report.json"
_RING_BUFFER_MAX = 30

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Risk-free baseline (T-bill yield, %) used for excess_yield_pct.
RISK_FREE_PCT: float = 4.0

# Confidence thresholds (number of historical data points).
MIN_POINTS_HIGH: int = 7
MIN_POINTS_MEDIUM: int = 3

# Coefficient-of-variation cutoffs for grades A / B / C / D.
CV_EXCELLENT: float = 0.05   # grade A boundary (<=)
CV_GOOD: float = 0.15        # grade B boundary (<=)
CV_FAIR: float = 0.30        # grade C boundary (<=); above → grade D

# Guard against division by ~0 (mean APY near zero, etc.).
EPS: float = 1e-9

# Top-level adapter_status.json keys that are NOT adapters.
_SKIP_KEYS = frozenset({
    "generated_at", "schema_version", "execution_mode",
    "live_apy_enabled", "mev_protection", "adapters",
    "base_gas_monitor", "last_updated",
})


# ---------------------------------------------------------------------------
# Pure helper functions (module-level, testable)
# ---------------------------------------------------------------------------

def _is_number(val: object) -> bool:
    """True if *val* is a real int/float (NOT bool) and finite."""
    if isinstance(val, bool):
        return False
    if not isinstance(val, (int, float)):
        return False
    try:
        return not (math.isnan(float(val)) or math.isinf(float(val)))
    except (TypeError, ValueError):
        return False


def _mean(values: List[float]) -> float:
    """Arithmetic mean of *values*. Returns 0.0 for an empty list."""
    if not values:
        return 0.0
    return sum(float(v) for v in values) / len(values)


def _stddev(values: List[float]) -> float:
    """Population standard deviation of *values*.

    Returns 0.0 if fewer than 2 points are supplied.
    """
    n = len(values)
    if n < 2:
        return 0.0
    mu = _mean(values)
    variance = sum((float(v) - mu) ** 2 for v in values) / n
    if variance < 0.0:  # guard against tiny negative float artefacts
        variance = 0.0
    return math.sqrt(variance)


def _coefficient_of_variation(values: List[float]) -> float:
    """Coefficient of variation = stddev / |mean|, EPS-guarded.

    Returns 0.0 if the list is empty or the mean is approximately 0.
    """
    if not values:
        return 0.0
    mu = _mean(values)
    if abs(mu) < EPS:
        return 0.0
    return _stddev(values) / abs(mu)


def _apy_drawdown_pct(series: List[float]) -> float:
    """Maximum peak-to-trough APY decline across the ordered *series*.

    Expressed in absolute percentage points (e.g. peak 8.0 → later trough
    5.0 yields 3.0). Returns 0.0 for empty / single-point series or when APY
    only ever rises.
    """
    if len(series) < 2:
        return 0.0
    peak = float(series[0])
    max_dd = 0.0
    for v in series:
        fv = float(v)
        if fv > peak:
            peak = fv
        dd = peak - fv
        if dd > max_dd:
            max_dd = dd
    return max_dd


def _extract_apy_series(points: List[dict]) -> List[float]:
    """Pull ``apy`` floats (in order) from a list of point dicts.

    Skips non-numeric / bool values and dicts missing the ``apy`` key.
    Returns ``[]`` for non-list input.
    """
    if not isinstance(points, list):
        return []
    out: List[float] = []
    for pt in points:
        if not isinstance(pt, dict):
            continue
        val = pt.get("apy")
        if _is_number(val):
            out.append(float(val))
    return out


def _stability_score(cv: float) -> float:
    """Map coefficient of variation → stability score in [0, 100].

    Higher = more stable. We use a linear ramp anchored at the grade-D
    boundary (``CV_FAIR``): ``100 * (1 - cv / CV_FAIR)`` clamped to [0, 100].
    A perfectly flat series (cv == 0) scores 100; cv >= CV_FAIR scores 0.
    Monotonically decreasing in cv. Negative cv inputs clamp to 100.
    """
    if cv <= 0.0:
        return 100.0
    raw = 100.0 * (1.0 - (cv / CV_FAIR))
    if raw < 0.0:
        return 0.0
    if raw > 100.0:
        return 100.0
    return raw


def _grade(cv: float) -> str:
    """Letter grade from coefficient of variation.

    "A" if cv <= CV_EXCELLENT, "B" if cv <= CV_GOOD, "C" if cv <= CV_FAIR,
    else "D".
    """
    if cv <= CV_EXCELLENT:
        return "A"
    if cv <= CV_GOOD:
        return "B"
    if cv <= CV_FAIR:
        return "C"
    return "D"


def _confidence(n_points: int) -> str:
    """Confidence label from the number of historical data points.

    "HIGH" >= 7, "MEDIUM" 3-6, "LOW" 1-2, "UNKNOWN" 0.
    """
    if n_points >= MIN_POINTS_HIGH:
        return "HIGH"
    if n_points >= MIN_POINTS_MEDIUM:
        return "MEDIUM"
    if n_points >= 1:
        return "LOW"
    return "UNKNOWN"


def _atomic_write_json(path: Path, payload: object) -> None:
    """Atomic JSON write: tmp file + ``os.replace``. Creates parent dirs.

    The tmp file is always removed on failure, so no ``.tmp`` litter is left.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    finally:
        try:
            if os.path.exists(tmp_name):
                os.remove(tmp_name)
        except OSError:
            pass


def _extract_current_apy(entry: dict) -> Optional[float]:
    """Extract a current APY (%) from an adapter_status entry.

    Resolution order: ``apy_pct`` → ``apy`` → ``mock_apy.ethereum.USDC`` →
    first available mock value. Returns ``None`` if nothing usable is found.
    """
    if not isinstance(entry, dict):
        return None
    for key in ("apy_pct", "apy"):
        val = entry.get(key)
        if _is_number(val):
            return float(val)
    mock = entry.get("mock_apy")
    if isinstance(mock, dict):
        chain_order = ["ethereum"] + [k for k in mock.keys() if k != "ethereum"]
        for chain_key in chain_order:
            chain_data = mock.get(chain_key)
            if isinstance(chain_data, dict):
                asset_order = ["USDC", "USDT"] + [
                    k for k in chain_data.keys() if k not in ("USDC", "USDT")
                ]
                for asset_key in asset_order:
                    val = chain_data.get(asset_key)
                    if _is_number(val):
                        return float(val)
    return None


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class AdapterStability:
    """Stability metrics for a single adapter."""
    adapter_key: str
    n_points: int
    mean_apy_pct: float
    std_apy_pct: float
    cv: float
    apy_drawdown_pct: float
    stability_score: float
    grade: str
    confidence: str
    latest_apy_pct: float
    excess_yield_pct: float           # mean_apy_pct - RISK_FREE_PCT
    rank: Optional[int] = None        # 1..N once ranked; None until then

    def to_dict(self) -> dict:
        """Return a JSON-serialisable dict of this record."""
        return {
            "adapter_key": self.adapter_key,
            "n_points": self.n_points,
            "mean_apy_pct": round(self.mean_apy_pct, 6),
            "std_apy_pct": round(self.std_apy_pct, 6),
            "cv": round(self.cv, 6),
            "apy_drawdown_pct": round(self.apy_drawdown_pct, 6),
            "stability_score": round(self.stability_score, 4),
            "grade": self.grade,
            "confidence": self.confidence,
            "latest_apy_pct": round(self.latest_apy_pct, 6),
            "excess_yield_pct": round(self.excess_yield_pct, 6),
            "rank": self.rank,
        }


@dataclass
class StabilityReport:
    """Aggregated stability report across all adapters."""
    generated_at: str
    total_adapters: int
    scored_count: int                 # adapters with >= 1 data point
    most_stable: Optional[str]
    least_stable: Optional[str]
    avg_stability_score: float
    grade_distribution: Dict[str, int]
    adapters: List[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Return a JSON-serialisable dict of the report."""
        return {
            "generated_at": self.generated_at,
            "total_adapters": self.total_adapters,
            "scored_count": self.scored_count,
            "most_stable": self.most_stable,
            "least_stable": self.least_stable,
            "avg_stability_score": round(self.avg_stability_score, 4),
            "grade_distribution": dict(self.grade_distribution),
            "adapters": list(self.adapters),
        }


# ---------------------------------------------------------------------------
# YieldStabilityScorer
# ---------------------------------------------------------------------------

class YieldStabilityScorer:
    """Score DeFi adapters by APY stability / persistence over time.

    Advisory / read-only: reads ``data/apy_history.json`` (primary),
    ``data/watchdog_history.json`` (supplementary) and
    ``data/adapter_status.json`` (adapter universe + current APY). The only
    file it writes is ``data/yield_stability_report.json``.

    Parameters
    ----------
    data_path : str
        Path to the ``data/`` directory. Defaults to the project's ``data/``.
        A path to a file inside the directory is also accepted (its parent is
        used).
    """

    def __init__(self, data_path: str = "data") -> None:
        if data_path is None:
            self._data_dir = _DEFAULT_DATA_DIR
        else:
            p = Path(data_path)
            self._data_dir = p if (p.is_dir() or not p.suffix) else p.parent
        self._apy_history_path = self._data_dir / _APY_HISTORY_FILE
        self._watchdog_path = self._data_dir / _WATCHDOG_HISTORY_FILE
        self._adapter_status_path = self._data_dir / _ADAPTER_STATUS_FILE
        self._report_path = self._data_dir / _STABILITY_REPORT_FILE

    # ------------------------------------------------------------------
    # Data loading (all fail-safe → {})
    # ------------------------------------------------------------------

    def _load_json_dict(self, path: Path) -> dict:
        """Load a JSON file → dict. Returns {} on any error / non-dict."""
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def load_apy_history(self) -> dict:
        """Load ``apy_history.json``. Returns {} on any error / non-dict."""
        return self._load_json_dict(self._apy_history_path)

    def load_watchdog_history(self) -> dict:
        """Load ``watchdog_history.json``. Returns {} on any error / non-dict."""
        return self._load_json_dict(self._watchdog_path)

    def load_adapter_status(self) -> dict:
        """Load ``adapter_status.json``. Returns {} on any error / non-dict."""
        return self._load_json_dict(self._adapter_status_path)

    # ------------------------------------------------------------------
    # Series collection
    # ------------------------------------------------------------------

    def _collect_series(self) -> Dict[str, List[float]]:
        """Build ``{adapter_key: apy_series}`` from the data sources.

        Primary source is ``apy_history.json``'s ``protocol_history`` (a full
        time-ordered APY series per key). For adapters present in
        ``adapter_status.json`` but absent from history, a single-point series
        is seeded from the current APY (so the universe is fully covered).

        Service / ``_meta`` keys and non-dict entries are skipped.
        """
        series: Dict[str, List[float]] = {}

        # ── Primary: protocol_history ─────────────────────────────────────
        history = self.load_apy_history()
        proto = history.get("protocol_history", {})
        if isinstance(proto, dict):
            for key, points in proto.items():
                if not isinstance(key, str) or not key:
                    continue
                if key in _SKIP_KEYS or key.startswith("_"):
                    continue
                vals = _extract_apy_series(points)
                if vals:
                    series[key] = vals

        # ── Supplementary: watchdog_history snapshots ─────────────────────
        wh = self.load_watchdog_history()
        snapshots = wh.get("snapshots", [])
        if isinstance(snapshots, list):
            # collect per-adapter values in snapshot order
            wd_series: Dict[str, List[float]] = {}
            for snap in snapshots:
                if not isinstance(snap, dict):
                    continue
                statuses = snap.get("adapter_statuses", [])
                if not isinstance(statuses, list):
                    continue
                for entry in statuses:
                    if not isinstance(entry, dict):
                        continue
                    aid = entry.get("adapter_id")
                    apy = entry.get("apy_pct")
                    if isinstance(aid, str) and aid and _is_number(apy):
                        if aid in _SKIP_KEYS or aid.startswith("_"):
                            continue
                        wd_series.setdefault(aid, []).append(float(apy))
            # only use watchdog series for adapters with NO history series
            for aid, vals in wd_series.items():
                if aid not in series and vals:
                    series[aid] = vals

        # ── Universe completion: adapter_status current APY ───────────────
        status = self.load_adapter_status()
        for key in self._status_adapter_keys(status):
            if key not in series:
                cur = self._current_apy_for_key(status, key)
                series[key] = [cur] if cur is not None else []

        return series

    def _status_adapter_keys(self, status: dict) -> List[str]:
        """Return the ordered list of adapter keys from adapter_status.json.

        Combines the ``adapters[]`` list (``protocol_key``) and protocol-level
        top-level dict keys, skipping service keys. Deterministic order:
        adapters-list keys first (in file order), then top-level keys.
        """
        keys: List[str] = []
        seen: set = set()

        adapters_list = status.get("adapters", [])
        if isinstance(adapters_list, list):
            for entry in adapters_list:
                if not isinstance(entry, dict):
                    continue
                key = (
                    entry.get("protocol_key")
                    or entry.get("adapter_id")
                    or entry.get("id")
                    or entry.get("name")
                )
                if isinstance(key, str) and key and key not in seen:
                    keys.append(key)
                    seen.add(key)

        for key, val in status.items():
            if not isinstance(key, str):
                continue
            if key in _SKIP_KEYS or key.startswith("_"):
                continue
            if not isinstance(val, dict):
                continue
            if key not in seen:
                keys.append(key)
                seen.add(key)

        return keys

    def _current_apy_for_key(self, status: dict, key: str) -> Optional[float]:
        """Best-effort current APY for *key* from adapter_status.json."""
        # protocol-level top-level entry
        entry = status.get(key)
        if isinstance(entry, dict):
            apy = _extract_current_apy(entry)
            if apy is not None:
                return apy
        # adapters[] list match
        adapters_list = status.get("adapters", [])
        if isinstance(adapters_list, list):
            for adapter in adapters_list:
                if not isinstance(adapter, dict):
                    continue
                akey = (
                    adapter.get("protocol_key")
                    or adapter.get("adapter_id")
                    or adapter.get("id")
                    or adapter.get("name")
                )
                if akey == key:
                    return _extract_current_apy(adapter)
        return None

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def score_adapter(self, key: str, series: List[float]) -> AdapterStability:
        """Compute an :class:`AdapterStability` for *key* given its APY *series*."""
        if not isinstance(series, list):
            series = []
        clean = [float(v) for v in series if _is_number(v)]
        n = len(clean)

        mean_apy = _mean(clean)
        std_apy = _stddev(clean)
        cv = _coefficient_of_variation(clean)
        drawdown = _apy_drawdown_pct(clean)
        score = _stability_score(cv) if n >= 1 else 0.0
        grade = _grade(cv) if n >= 1 else "D"
        confidence = _confidence(n)
        latest = clean[-1] if clean else 0.0
        excess = mean_apy - RISK_FREE_PCT

        return AdapterStability(
            adapter_key=str(key),
            n_points=n,
            mean_apy_pct=mean_apy,
            std_apy_pct=std_apy,
            cv=cv,
            apy_drawdown_pct=drawdown,
            stability_score=score,
            grade=grade,
            confidence=confidence,
            latest_apy_pct=latest,
            excess_yield_pct=excess,
            rank=None,
        )

    def score_all(self) -> List[AdapterStability]:
        """Score every collected adapter and assign deterministic ranks.

        Ranking is by stability_score DESC, tie-broken by cv ASC, then
        excess_yield_pct DESC, then adapter_key ASC. Ranks are 1..N.
        Zero-point adapters (UNKNOWN, score 0) sort to the bottom.
        """
        collected = self._collect_series()
        scored = [self.score_adapter(k, v) for k, v in collected.items()]
        scored.sort(
            key=lambda a: (
                -a.stability_score,
                a.cv,
                -a.excess_yield_pct,
                a.adapter_key,
            )
        )
        for idx, adapter in enumerate(scored, start=1):
            adapter.rank = idx
        return scored

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_top_n(self, n: int) -> List[AdapterStability]:
        """Return the top-*n* ranked adapters. ``n <= 0`` → ``[]``."""
        if n <= 0:
            return []
        return self.score_all()[:n]

    def get_by_grade(self, grade: str) -> List[AdapterStability]:
        """Return ranked adapters of the given letter *grade* (case-insensitive).

        Unknown grades return ``[]``.
        """
        if not isinstance(grade, str):
            return []
        target = grade.strip().upper()
        if target not in {"A", "B", "C", "D"}:
            return []
        return [a for a in self.score_all() if a.grade == target]

    # ------------------------------------------------------------------
    # Report
    # ------------------------------------------------------------------

    def get_report(self) -> StabilityReport:
        """Build a :class:`StabilityReport`. No side effects, no file writes."""
        now_iso = datetime.now(timezone.utc).isoformat()
        scored = self.score_all()

        total = len(scored)
        with_points = [a for a in scored if a.n_points >= 1]
        scored_count = len(with_points)

        # most/least stable considering only adapters with data points.
        most_stable: Optional[str] = None
        least_stable: Optional[str] = None
        if with_points:
            most_stable = with_points[0].adapter_key  # already rank-sorted
            least_stable = with_points[-1].adapter_key

        if with_points:
            avg_score = _mean([a.stability_score for a in with_points])
        else:
            avg_score = 0.0

        grade_dist: Dict[str, int] = {"A": 0, "B": 0, "C": 0, "D": 0}
        for a in with_points:
            grade_dist[a.grade] = grade_dist.get(a.grade, 0) + 1

        return StabilityReport(
            generated_at=now_iso,
            total_adapters=total,
            scored_count=scored_count,
            most_stable=most_stable,
            least_stable=least_stable,
            avg_stability_score=avg_score,
            grade_distribution=grade_dist,
            adapters=[a.to_dict() for a in scored],
        )

    def to_dict(self) -> dict:
        """Return the current report as a JSON-serialisable dict."""
        return self.get_report().to_dict()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save_report(self, output_path: Optional[str] = None) -> str:
        """Atomically save the report to ``data/yield_stability_report.json``.

        Keeps a ring-buffer of the last 30 reports under
        ``{"latest": {...}, "snapshots": [...]}``. Uses tmp + ``os.replace``;
        no ``.tmp`` litter is left on failure. Returns the written path.
        """
        dest = Path(output_path) if output_path else self._report_path

        snapshot = self.to_dict()

        # Load existing ring-buffer (fail-safe).
        snapshots: List[dict] = []
        try:
            if dest.exists():
                with open(dest, encoding="utf-8") as fh:
                    existing = json.load(fh)
                if isinstance(existing, dict):
                    raw = existing.get("snapshots", [])
                    if isinstance(raw, list):
                        snapshots = raw
                elif isinstance(existing, list):
                    snapshots = existing
        except Exception:
            snapshots = []

        snapshots.append(snapshot)
        if len(snapshots) > _RING_BUFFER_MAX:
            snapshots = snapshots[-_RING_BUFFER_MAX:]

        payload = {
            "schema_version": 1,
            "source": "yield_stability_scorer",
            "ring_buffer_max": _RING_BUFFER_MAX,
            "snapshot_count": len(snapshots),
            "updated_at": snapshot["generated_at"],
            "latest": snapshot,
            "snapshots": snapshots,
        }
        _atomic_write_json(dest, payload)
        return str(dest)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _run_cli(argv: Optional[List[str]] = None) -> int:  # pragma: no cover
    import argparse

    parser = argparse.ArgumentParser(
        description="Yield Stability Scorer (SPA-V526 / MP-602) — "
                    "APY stability / persistence scoring."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        default=False,
        help="Compute and print summary (no write). Default mode.",
    )
    parser.add_argument(
        "--run",
        action="store_true",
        default=False,
        help="Compute report and atomically save "
             "data/yield_stability_report.json.",
    )
    parser.add_argument(
        "--data-dir",
        default="data",
        metavar="PATH",
        help="Path to the data/ directory (default: project data/).",
    )
    args = parser.parse_args(argv)

    scorer = YieldStabilityScorer(data_path=args.data_dir)
    report = scorer.get_report()

    print("=== Yield Stability Scorer (MP-602) ===")
    print(f"Generated: {report.generated_at}")
    print(
        f"Total adapters: {report.total_adapters}  "
        f"(scored: {report.scored_count})"
    )
    print(
        f"Most stable: {report.most_stable}   "
        f"Least stable: {report.least_stable}"
    )
    print(f"Avg stability score: {report.avg_stability_score:.2f}")
    gd = report.grade_distribution
    print(
        f"Grade distribution: A={gd.get('A', 0)} B={gd.get('B', 0)} "
        f"C={gd.get('C', 0)} D={gd.get('D', 0)}"
    )
    print()
    print("Ranking (stability_score desc; higher = steadier APY):")
    for a in report.adapters:
        print(
            f"  #{a['rank']:<2d} {a['adapter_key']:28s} "
            f"score={a['stability_score']:6.2f}  "
            f"grade={a['grade']}  "
            f"cv={a['cv']:.4f}  "
            f"mean={a['mean_apy_pct']:6.2f}%  "
            f"dd={a['apy_drawdown_pct']:5.2f}pp  "
            f"[{a['confidence']}]  pts={a['n_points']}"
        )

    if args.run:
        path = scorer.save_report()
        print(f"\nSaved -> {path}")
    else:
        print("\n(--check mode: not saved. Use --run to persist.)")

    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(_run_cli())
