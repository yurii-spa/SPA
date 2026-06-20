"""
Adapter Correlation Matrix (MP-612).
=====================================

Вычисляет корреляцию Пирсона между APY рядами адаптеров (pure stdlib).
Используется для нахождения некоррелированных пар для диверсификации.

Data source:
  - data/watchdog_history.json  (ring-buffer snapshots from AdapterWatchdog)

Output: data/correlation_matrix.json (ring-buffer 10 entries)

Design constraints
------------------
* Pure stdlib + math only — no numpy / scipy / requests / web3 / pandas.
* Read-only over history file; writes only data/correlation_matrix.json.
* Atomic writes: tmp + os.replace (POSIX-atomic, fail-safe cleanup).
* Never raises on the happy path; missing / malformed data degrades gracefully.
* NOT imported from risk/, execution/, monitoring/ (LLM_FORBIDDEN_AGENTS).
* Deterministic: identical input → identical output.

Correlation thresholds:
  STRONGLY_CORRELATED   r >= 0.8
  CORRELATED            0.5 <= r < 0.8
  WEAKLY_CORRELATED     0.2 <= r < 0.5
  UNCORRELATED         -0.2 < r < 0.2
  NEGATIVELY_CORRELATED r <= -0.2

is_diversifying: correlation < 0.5

CLI
---
  python3 -m spa_core.analytics.adapter_correlation_matrix --check   (default, no write)
  python3 -m spa_core.analytics.adapter_correlation_matrix --run     (+ atomic save)
  python3 -m spa_core.analytics.adapter_correlation_matrix --run --data-dir PATH
"""
from __future__ import annotations

import json
import math
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Default paths
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _PROJECT_ROOT / "data"
_WATCHDOG_HISTORY_FILE = "watchdog_history.json"
_CORRELATION_MATRIX_FILE = "correlation_matrix.json"
_RING_BUFFER_MAX = 10


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_ts_unix(ts_str: str) -> float:
    """Parse ISO-8601 UTC string → unix timestamp float. Returns 0.0 on error."""
    if not isinstance(ts_str, str):
        return 0.0
    try:
        s = ts_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        return dt.timestamp()
    except Exception:
        return 0.0


def _atomic_write_json(path: Path, payload: object) -> None:
    """Atomic JSON write via centralized atomic_save (MP-1453)."""
    atomic_save(payload, str(path))
class CorrelationPair:
    """Pearson correlation result for one adapter pair."""
    adapter_a: str
    adapter_b: str
    correlation: float          # [-1.0, 1.0]
    relationship: str           # "STRONGLY_CORRELATED" / "CORRELATED" /
                                # "WEAKLY_CORRELATED" / "UNCORRELATED" /
                                # "NEGATIVELY_CORRELATED"
    data_points: int            # number of aligned data points used
    is_diversifying: bool       # correlation < 0.5

    def to_dict(self) -> dict:
        return {
            "adapter_a": self.adapter_a,
            "adapter_b": self.adapter_b,
            "correlation": round(self.correlation, 6),
            "relationship": self.relationship,
            "data_points": self.data_points,
            "is_diversifying": self.is_diversifying,
        }


@dataclass
class CorrelationMatrix:
    """Full correlation matrix across all adapters with enough APY history."""
    generated_at: str
    adapters: List[str]                         # adapters included
    pairs: List[CorrelationPair]                # all computed pairs
    best_diversifying_pairs: List[CorrelationPair]  # top-5 lowest correlation
    most_correlated_pairs: List[CorrelationPair]    # top-5 highest correlation
    avg_correlation: float                      # mean r across all pairs
    min_data_points: int                        # min data_points among pairs
    low_data_warning: bool                      # True if min_data_points < 5

    def to_dict(self) -> dict:
        return {
            "generated_at": self.generated_at,
            "adapters": self.adapters,
            "pairs": [p.to_dict() for p in self.pairs],
            "best_diversifying_pairs": [p.to_dict() for p in self.best_diversifying_pairs],
            "most_correlated_pairs": [p.to_dict() for p in self.most_correlated_pairs],
            "avg_correlation": round(self.avg_correlation, 6),
            "min_data_points": self.min_data_points,
            "low_data_warning": self.low_data_warning,
        }


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class AdapterCorrelationMatrix:
    """
    Compute Pearson correlation between APY time-series of adapters.

    Parameters
    ----------
    data_path : str | None
        Path to the data/ directory (or a file inside it).
        Defaults to the project's data/.
    """

    MIN_DATA_POINTS: int = 3       # minimum aligned points for a valid correlation
    LOW_DATA_THRESHOLD: int = 5    # below this → low_data_warning in matrix

    def __init__(self, data_path: Optional[str] = None) -> None:
        if data_path is None:
            self._data_dir = _DEFAULT_DATA_DIR
        else:
            p = Path(data_path)
            self._data_dir = p if p.is_dir() else p.parent
        self._watchdog_path = self._data_dir / _WATCHDOG_HISTORY_FILE
        self._output_path = self._data_dir / _CORRELATION_MATRIX_FILE

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def load_apy_series(self) -> Dict[str, List[float]]:
        """
        Read data/watchdog_history.json and extract APY time-series per adapter.

        Returns a dict mapping adapter_key → list[float] of apy_pct values,
        in chronological order (oldest first).

        Returns {} if the file doesn't exist or is malformed.
        """
        try:
            if not self._watchdog_path.exists():
                return {}
            raw = self._watchdog_path.read_text(encoding="utf-8")
            wh = json.loads(raw)
        except Exception:
            return {}

        if not isinstance(wh, dict):
            return {}

        snapshots = wh.get("snapshots", [])
        if not isinstance(snapshots, list):
            return {}

        # Each snapshot has "generated_at" + "adapter_statuses" list.
        # Sort snapshots chronologically by generated_at to build series in order.
        ts_snapshots: List[Tuple[float, dict]] = []
        for snap in snapshots:
            if not isinstance(snap, dict):
                continue
            ts_str = snap.get("generated_at", "")
            ts_unix = _parse_ts_unix(ts_str)
            if ts_unix <= 0:
                continue
            ts_snapshots.append((ts_unix, snap))

        ts_snapshots.sort(key=lambda x: x[0])

        series: Dict[str, List[float]] = {}
        for _ts, snap in ts_snapshots:
            statuses = snap.get("adapter_statuses", [])
            if not isinstance(statuses, list):
                continue
            for entry in statuses:
                if not isinstance(entry, dict):
                    continue
                key = entry.get("adapter_id") or entry.get("adapter_key") or entry.get("protocol_key")
                if not isinstance(key, str) or not key:
                    continue
                apy = entry.get("apy_pct")
                if (
                    isinstance(apy, (int, float))
                    and not isinstance(apy, bool)
                    and not math.isnan(float(apy))
                ):
                    series.setdefault(key, []).append(float(apy))

        return series

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    def pearson_correlation(self, xs: List[float], ys: List[float]) -> float:
        """
        Compute Pearson r between two aligned series (pure stdlib, no numpy).

        Formula:
            r = (n·Σxy − Σx·Σy) / sqrt((n·Σx² − (Σx)²) · (n·Σy² − (Σy)²))

        Returns 0.0 if:
          - lengths differ
          - fewer than MIN_DATA_POINTS points
          - denominator is 0 (constant series)
        """
        n = len(xs)
        if n != len(ys) or n < self.MIN_DATA_POINTS:
            return 0.0

        sum_x = 0.0
        sum_y = 0.0
        sum_xy = 0.0
        sum_x2 = 0.0
        sum_y2 = 0.0

        for x, y in zip(xs, ys):
            sum_x += x
            sum_y += y
            sum_xy += x * y
            sum_x2 += x * x
            sum_y2 += y * y

        denom_sq = (n * sum_x2 - sum_x * sum_x) * (n * sum_y2 - sum_y * sum_y)
        if denom_sq <= 0.0:
            return 0.0

        numer = n * sum_xy - sum_x * sum_y
        return numer / math.sqrt(denom_sq)

    def align_series(
        self,
        series_a: List[float],
        series_b: List[float],
    ) -> Tuple[List[float], List[float]]:
        """
        Align two time-series by truncating both to the same length.

        Takes the last min(len(a), len(b)) elements from each series
        (most recent observations).

        Returns ([], []) if either series is empty.
        """
        if not series_a or not series_b:
            return [], []
        n = min(len(series_a), len(series_b))
        return list(series_a[-n:]), list(series_b[-n:])

    def classify_relationship(self, r: float) -> str:
        """
        Classify Pearson r into a human-readable relationship string.

        Thresholds:
          r >= 0.8              → "STRONGLY_CORRELATED"
          0.5 <= r < 0.8        → "CORRELATED"
          0.2 <= r < 0.5        → "WEAKLY_CORRELATED"
          -0.2 < r < 0.2        → "UNCORRELATED"
          r <= -0.2             → "NEGATIVELY_CORRELATED"
        """
        if r >= 0.8:
            return "STRONGLY_CORRELATED"
        if r >= 0.5:
            return "CORRELATED"
        if r >= 0.2:
            return "WEAKLY_CORRELATED"
        if r > -0.2:
            return "UNCORRELATED"
        return "NEGATIVELY_CORRELATED"

    # ------------------------------------------------------------------
    # Pair computation
    # ------------------------------------------------------------------

    def compute_pair(
        self,
        a: str,
        b: str,
        series: Dict[str, List[float]],
    ) -> Optional[CorrelationPair]:
        """
        Compute a CorrelationPair for adapters a and b.

        Returns None if either adapter is missing from series or if
        aligned data_points < MIN_DATA_POINTS after alignment.
        """
        if a not in series or b not in series:
            return None

        xs, ys = self.align_series(series[a], series[b])
        data_points = len(xs)
        if data_points < self.MIN_DATA_POINTS:
            return None

        r = self.pearson_correlation(xs, ys)
        # Clamp to [-1, 1] to guard against floating-point drift
        r = max(-1.0, min(1.0, r))

        relationship = self.classify_relationship(r)
        is_diversifying = r < 0.5

        return CorrelationPair(
            adapter_a=a,
            adapter_b=b,
            correlation=round(r, 6),
            relationship=relationship,
            data_points=data_points,
            is_diversifying=is_diversifying,
        )

    # ------------------------------------------------------------------
    # Matrix generation
    # ------------------------------------------------------------------

    def generate_matrix(self) -> CorrelationMatrix:
        """
        Load APY series, compute all unique pairs (a < b), and build CorrelationMatrix.

        - best_diversifying_pairs: top-5 pairs sorted by correlation ascending
        - most_correlated_pairs:   top-5 pairs sorted by correlation descending
        - avg_correlation: mean r across all computed pairs (0.0 if no pairs)
        - low_data_warning: True if min_data_points < LOW_DATA_THRESHOLD
          or if no pairs could be computed
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        series = self.load_apy_series()

        adapters = sorted(series.keys())
        pairs: List[CorrelationPair] = []

        for i in range(len(adapters)):
            for j in range(i + 1, len(adapters)):
                pair = self.compute_pair(adapters[i], adapters[j], series)
                if pair is not None:
                    pairs.append(pair)

        # Summaries
        if pairs:
            avg_correlation = sum(p.correlation for p in pairs) / len(pairs)
            min_data_points = min(p.data_points for p in pairs)
        else:
            avg_correlation = 0.0
            min_data_points = 0

        low_data_warning = min_data_points < self.LOW_DATA_THRESHOLD

        # Top-5 best diversifying (lowest r first)
        best_diversifying = sorted(pairs, key=lambda p: p.correlation)[:5]
        # Top-5 most correlated (highest r first)
        most_correlated = sorted(pairs, key=lambda p: p.correlation, reverse=True)[:5]

        # Collect adapters that appear in at least one computed pair
        seen_adapters: List[str] = []
        if pairs:
            seen = set()
            for p in pairs:
                seen.add(p.adapter_a)
                seen.add(p.adapter_b)
            seen_adapters = sorted(seen)
        else:
            seen_adapters = []

        return CorrelationMatrix(
            generated_at=now_iso,
            adapters=seen_adapters,
            pairs=pairs,
            best_diversifying_pairs=best_diversifying,
            most_correlated_pairs=most_correlated,
            avg_correlation=round(avg_correlation, 6),
            min_data_points=min_data_points,
            low_data_warning=low_data_warning,
        )

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save_matrix(self, matrix: Optional[CorrelationMatrix] = None) -> str:
        """
        Atomically save the CorrelationMatrix to data/correlation_matrix.json.

        Maintains a ring-buffer of at most 10 entries.
        Generates a fresh matrix if none is supplied.

        Returns the absolute path of the saved file.
        """
        if matrix is None:
            matrix = self.generate_matrix()

        matrix_dict = matrix.to_dict()

        # Load existing ring-buffer
        existing: List[dict] = []
        try:
            if self._output_path.exists():
                raw = self._output_path.read_text(encoding="utf-8")
                payload = json.loads(raw)
                if isinstance(payload, dict):
                    existing = payload.get("reports", [])
                    if not isinstance(existing, list):
                        existing = []
        except Exception:
            existing = []

        existing.append(matrix_dict)
        if len(existing) > _RING_BUFFER_MAX:
            existing = existing[-_RING_BUFFER_MAX:]

        new_payload = {
            "schema_version": 1,
            "ring_buffer_max": _RING_BUFFER_MAX,
            "snapshot_count": len(existing),
            "updated_at": matrix.generated_at,
            "latest": matrix_dict,
            "reports": existing,
        }
        _atomic_write_json(self._output_path, new_payload)
        return str(self._output_path)

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self, matrix: Optional[CorrelationMatrix] = None) -> dict:
        """Return the matrix as a JSON-serialisable dict."""
        if matrix is None:
            matrix = self.generate_matrix()
        return matrix.to_dict()

    # ------------------------------------------------------------------
    # Telegram formatting
    # ------------------------------------------------------------------

    def format_telegram_message(self, matrix: Optional[CorrelationMatrix] = None) -> str:
        """
        Build a Telegram-ready correlation summary (≤ 1500 characters).

        Format:
            🔗 Correlation Matrix — N adapters, M pairs
            ⚠️ Low data warning  (if applicable)
            Avg correlation: 0.42

            Best diversifying pairs:
              spark_susds↔aave_v3_polygon: -0.12 (UNCORRELATED) ✅

            Most correlated:
              aave_v3_base↔aave_v3_optimism: 0.92 (STRONGLY_CORRELATED) ⚠️
        """
        if matrix is None:
            matrix = self.generate_matrix()

        n_adapters = len(matrix.adapters)
        n_pairs = len(matrix.pairs)

        lines: List[str] = []
        lines.append(f"🔗 *Correlation Matrix* — {n_adapters} adapters, {n_pairs} pairs")

        if matrix.low_data_warning:
            lines.append("⚠️ Low data warning (min data points < 5)")

        lines.append(f"Avg correlation: {matrix.avg_correlation:.2f}")

        if matrix.best_diversifying_pairs:
            lines.append("\n*Best diversifying pairs:*")
            for p in matrix.best_diversifying_pairs:
                marker = "✅" if p.is_diversifying else ""
                lines.append(
                    f"  {p.adapter_a}↔{p.adapter_b}: "
                    f"{p.correlation:.2f} ({p.relationship}) {marker}".rstrip()
                )

        if matrix.most_correlated_pairs:
            lines.append("\n*Most correlated:*")
            for p in matrix.most_correlated_pairs:
                marker = "⚠️" if not p.is_diversifying else ""
                lines.append(
                    f"  {p.adapter_a}↔{p.adapter_b}: "
                    f"{p.correlation:.2f} ({p.relationship}) {marker}".rstrip()
                )

        msg = "\n".join(lines)
        if len(msg) > 1500:
            msg = msg[:1497] + "…"
        return msg


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _run_cli(argv: Optional[List[str]] = None) -> None:  # pragma: no cover
    import argparse

    parser = argparse.ArgumentParser(
        description="Adapter Correlation Matrix (MP-612) — Pearson APY correlation"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        default=False,
        help="Compute and print matrix (no write). Default mode.",
    )
    parser.add_argument(
        "--run",
        action="store_true",
        default=False,
        help="Compute matrix and atomically save data/correlation_matrix.json.",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        metavar="PATH",
        help="Path to the data/ directory (default: project data/).",
    )
    args = parser.parse_args(argv)

    analyzer = AdapterCorrelationMatrix(data_path=args.data_dir)
    matrix = analyzer.generate_matrix()

    print(
        f"=== Adapter Correlation Matrix (MP-612) — "
        f"{len(matrix.adapters)} adapters, {len(matrix.pairs)} pairs ==="
    )
    print(f"  Avg correlation:  {matrix.avg_correlation:.4f}")
    print(f"  Min data points:  {matrix.min_data_points}")
    if matrix.low_data_warning:
        print("  ⚠️  Low data warning (min data points < 5)")
    print()

    if matrix.best_diversifying_pairs:
        print("  Best diversifying pairs:")
        for p in matrix.best_diversifying_pairs:
            print(
                f"    ✅ {p.adapter_a} ↔ {p.adapter_b}: "
                f"r={p.correlation:.4f} ({p.relationship}, pts={p.data_points})"
            )

    if matrix.most_correlated_pairs:
        print("  Most correlated pairs:")
        for p in matrix.most_correlated_pairs:
            print(
                f"    ⚠️  {p.adapter_a} ↔ {p.adapter_b}: "
                f"r={p.correlation:.4f} ({p.relationship}, pts={p.data_points})"
            )

    if args.run:
        path = analyzer.save_matrix(matrix)
        print(f"\nSaved → {path}")
    else:
        print("\n(--check mode: not saved. Use --run to persist.)")

    sys.exit(0)


if __name__ == "__main__":  # pragma: no cover
    _run_cli()
