"""
MP-767: StrategyCorrelationMatrix
Computes pairwise Pearson correlation between strategy daily-return series
over a rolling window. Reports avg_pairwise_correlation, diversification_score
(0-100, lower correlation = higher score), and highly_correlated_pairs (|r| > 0.8).
Pure stdlib only — no numpy/pandas/scipy. Advisory/read-only. Atomic writes.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
import json
import math
import os
import time
from pathlib import Path

DATA_FILE = Path("data/strategy_correlation_log.json")
MAX_ENTRIES = 100
HIGH_CORR_THRESHOLD = 0.8  # pairs with |r| above this are flagged

_ZERO_EPS = 1e-12


@dataclass
class CorrelationResult:
    """Result of a compute_matrix call."""
    strategy_ids: List[str]
    window: int                                        # rolling window length used
    actual_window: Dict[str, int]                      # actual # returns used per strategy
    correlation_matrix: Dict[str, Dict[str, float]]    # strategy_id → strategy_id → r
    avg_pairwise_correlation: float                    # mean of all off-diagonal r values
    diversification_score: float                       # 0-100 (higher = more diverse)
    highly_correlated_pairs: List[Tuple[str, str, float]]  # (id1, id2, r) where |r| > 0.8
    advisory: List[str] = field(default_factory=list)
    generated_at: str = ""


class StrategyCorrelationMatrix:
    """
    Computes pairwise Pearson correlations between strategy return series.
    Advisory only — never modifies allocator, risk, or execution domains.

    Usage::

        scm = StrategyCorrelationMatrix()
        data = {
            "S0": [0.001, 0.002, -0.001, ...],
            "S1": [0.002, 0.001, -0.002, ...],
        }
        result = scm.compute_matrix(data, window=30)
        print(result.diversification_score, result.highly_correlated_pairs)
    """

    def __init__(self) -> None:
        self._last_result: Optional[CorrelationResult] = None

    # ------------------------------------------------------------------
    # Pure-Python Pearson correlation (stdlib only)
    # ------------------------------------------------------------------

    @staticmethod
    def _pearson(xs: List[float], ys: List[float]) -> float:
        """
        Pearson correlation coefficient between two equal-length lists.
        Uses population (N) denominator for cov and std.
        Returns 0.0 if either series is constant (std ~ 0) or fewer than 2 points.
        """
        n = len(xs)
        if n < 2 or n != len(ys):
            return 0.0
        mx = sum(xs) / n
        my = sum(ys) / n
        cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / n
        var_x = sum((x - mx) ** 2 for x in xs) / n
        var_y = sum((y - my) ** 2 for y in ys) / n
        std_x = math.sqrt(var_x)
        std_y = math.sqrt(var_y)
        if std_x < _ZERO_EPS or std_y < _ZERO_EPS:
            return 0.0  # constant series — correlation undefined, treat as 0
        r = cov / (std_x * std_y)
        # Clamp to [-1, 1] to guard against floating-point overshoot
        return max(-1.0, min(1.0, r))

    # ------------------------------------------------------------------
    # Diversification score
    # ------------------------------------------------------------------

    @staticmethod
    def _diversification_score(avg_pairwise_corr: float) -> float:
        """
        Map average pairwise correlation [-1, 1] to a diversification score [0, 100].
        avg_corr = -1.0  → score = 100  (perfectly negatively correlated, max diversity)
        avg_corr =  0.0  → score =  50
        avg_corr =  1.0  → score =   0  (perfectly correlated, no diversity)
        Formula: score = (1 - avg_corr) / 2 * 100
        """
        raw = (1.0 - avg_pairwise_corr) / 2.0 * 100.0
        return round(max(0.0, min(100.0, raw)), 4)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compute_matrix(
        self,
        returns_data: Dict[str, List[float]],
        window: int = 30,
    ) -> CorrelationResult:
        """
        Compute pairwise Pearson correlation matrix over the last `window` returns.

        Parameters
        ----------
        returns_data : dict mapping strategy_id → list of daily returns (floats).
                       Shorter series are used as-is (no padding).
        window       : number of most-recent returns to use per strategy (>= 2).

        Returns
        -------
        CorrelationResult with matrix, avg_pairwise_correlation, diversification_score,
        and highly_correlated_pairs.
        """
        generated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        safe_window = max(2, int(window))

        # Collect strategy IDs (sorted for deterministic output)
        strategy_ids = sorted(returns_data.keys())

        # Trim each series to last `window` points
        trimmed: Dict[str, List[float]] = {}
        actual_window: Dict[str, int] = {}
        for sid in strategy_ids:
            series = list(returns_data[sid] or [])
            trimmed[sid] = series[-safe_window:]
            actual_window[sid] = len(trimmed[sid])

        # Build N×N correlation matrix
        matrix: Dict[str, Dict[str, float]] = {}
        for sid in strategy_ids:
            matrix[sid] = {}
            for tid in strategy_ids:
                if sid == tid:
                    matrix[sid][tid] = 1.0
                elif tid in matrix and sid in matrix[tid]:
                    # Symmetric — reuse already computed value
                    matrix[sid][tid] = matrix[tid][sid]
                else:
                    xs = trimmed[sid]
                    ys = trimmed[tid]
                    # Align to the shorter of the two (truncate from the left)
                    min_len = min(len(xs), len(ys))
                    if min_len < 2:
                        r = 0.0
                    else:
                        r = self._pearson(xs[-min_len:], ys[-min_len:])
                    matrix[sid][tid] = round(r, 6)

        # Compute average off-diagonal correlation
        off_diagonal: List[float] = []
        highly_correlated_pairs: List[Tuple[str, str, float]] = []

        n = len(strategy_ids)
        for i, sid in enumerate(strategy_ids):
            for j, tid in enumerate(strategy_ids):
                if i >= j:
                    continue  # upper triangle only (avoid double-counting)
                r = matrix[sid][tid]
                off_diagonal.append(r)
                if abs(r) > HIGH_CORR_THRESHOLD:
                    highly_correlated_pairs.append((sid, tid, r))

        if off_diagonal:
            avg_pairwise = sum(off_diagonal) / len(off_diagonal)
        else:
            # 0 or 1 strategy — no pairs to compare
            avg_pairwise = 0.0

        avg_pairwise = round(avg_pairwise, 6)
        div_score = self._diversification_score(avg_pairwise)

        advisory = self._build_advisory(
            n_strategies=n,
            avg_pairwise=avg_pairwise,
            div_score=div_score,
            highly_correlated_pairs=highly_correlated_pairs,
            safe_window=safe_window,
            actual_window=actual_window,
        )

        result = CorrelationResult(
            strategy_ids=strategy_ids,
            window=safe_window,
            actual_window=actual_window,
            correlation_matrix=matrix,
            avg_pairwise_correlation=avg_pairwise,
            diversification_score=div_score,
            highly_correlated_pairs=highly_correlated_pairs,
            advisory=advisory,
            generated_at=generated_at,
        )

        self._last_result = result
        return result

    def get_diversification_score(self) -> float:
        """Return diversification score from the most recent compute_matrix call, or 50.0."""
        if self._last_result is None:
            return 50.0
        return self._last_result.diversification_score

    def get_correlated_pairs(self) -> List[Tuple[str, str, float]]:
        """Return list of highly correlated pairs from the most recent compute_matrix call."""
        if self._last_result is None:
            return []
        return list(self._last_result.highly_correlated_pairs)

    # ------------------------------------------------------------------
    # Advisory
    # ------------------------------------------------------------------

    @staticmethod
    def _build_advisory(
        n_strategies: int,
        avg_pairwise: float,
        div_score: float,
        highly_correlated_pairs: List[Tuple[str, str, float]],
        safe_window: int,
        actual_window: Dict[str, int],
    ) -> List[str]:
        out: List[str] = []

        if n_strategies == 0:
            out.append("No strategies provided — matrix is empty")
            return out
        if n_strategies == 1:
            out.append(
                "Only one strategy — pairwise correlation undefined; "
                "diversification score defaults to 50"
            )
            return out

        out.append(
            f"Analysed {n_strategies} strategies over a {safe_window}-day rolling window"
        )

        if avg_pairwise >= 0.8:
            out.append(
                f"Very high average pairwise correlation ({avg_pairwise:.3f}) — "
                "strategies move almost in lockstep; diversification benefit minimal"
            )
        elif avg_pairwise >= 0.5:
            out.append(
                f"Moderate-to-high correlation ({avg_pairwise:.3f}) — "
                "some diversification benefit but strategies remain positively linked"
            )
        elif avg_pairwise >= 0.2:
            out.append(
                f"Moderate correlation ({avg_pairwise:.3f}) — "
                "reasonable diversification across strategies"
            )
        elif avg_pairwise >= -0.2:
            out.append(
                f"Low correlation ({avg_pairwise:.3f}) — "
                "good diversification; strategies largely independent"
            )
        else:
            out.append(
                f"Negative average correlation ({avg_pairwise:.3f}) — "
                "excellent diversification; strategies often move in opposite directions"
            )

        if div_score >= 75:
            out.append(f"Diversification score {div_score:.1f}/100 — EXCELLENT")
        elif div_score >= 50:
            out.append(f"Diversification score {div_score:.1f}/100 — GOOD")
        elif div_score >= 25:
            out.append(f"Diversification score {div_score:.1f}/100 — MODERATE")
        else:
            out.append(f"Diversification score {div_score:.1f}/100 — POOR")

        if highly_correlated_pairs:
            pair_strs = [
                f"({p[0]}, {p[1]}: r={p[2]:.3f})" for p in highly_correlated_pairs
            ]
            out.append(
                f"Highly correlated pairs (|r| > {HIGH_CORR_THRESHOLD}): "
                + ", ".join(pair_strs)
            )
        else:
            out.append(f"No highly correlated pairs found (threshold |r| > {HIGH_CORR_THRESHOLD})")

        # Warn if any strategy had fewer returns than the requested window
        short_series = [
            sid for sid, n in actual_window.items() if n < safe_window
        ]
        if short_series:
            out.append(
                f"Short return series (fewer than {safe_window} points): "
                + ", ".join(short_series)
                + " — correlation estimates may be less reliable"
            )

        return out

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save_result(self, result: CorrelationResult, data_file: Path = DATA_FILE) -> None:
        """Append result to ring-buffer JSON (max MAX_ENTRIES). Atomic write."""
        data_file = Path(data_file)
        existing = self.load_history(data_file)

        entry = {
            "timestamp": result.generated_at
            or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "strategy_ids": result.strategy_ids,
            "window": result.window,
            "actual_window": result.actual_window,
            "avg_pairwise_correlation": result.avg_pairwise_correlation,
            "diversification_score": result.diversification_score,
            "highly_correlated_pairs": [
                {"id1": p[0], "id2": p[1], "r": p[2]}
                for p in result.highly_correlated_pairs
            ],
            "correlation_matrix": result.correlation_matrix,
            "advisory": result.advisory,
        }

        combined = (existing + [entry])[-MAX_ENTRIES:]

        data_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = data_file.with_suffix(".tmp")
        with open(tmp, "w") as fh:
            json.dump(combined, fh, indent=2)
        os.replace(tmp, data_file)

    def load_history(self, data_file: Path = DATA_FILE) -> list:
        """Load ring-buffer history. Returns [] if missing or corrupt."""
        data_file = Path(data_file)
        if not data_file.exists():
            return []
        try:
            with open(data_file, "r") as fh:
                return json.load(fh)
        except (json.JSONDecodeError, OSError):
            return []


# ---------------------------------------------------------------------------
# CLI / demo
# ---------------------------------------------------------------------------

def _demo() -> None:
    import random
    random.seed(42)

    scm = StrategyCorrelationMatrix()
    # Simulate three strategy return series
    base = [random.gauss(0.001, 0.005) for _ in range(60)]
    returns_data = {
        "S0": [r + random.gauss(0, 0.001) for r in base],
        "S1": [r + random.gauss(0, 0.002) for r in base],   # highly correlated with S0
        "S2": [-r + random.gauss(0, 0.003) for r in base],  # negatively correlated
    }
    result = scm.compute_matrix(returns_data, window=30)
    print(f"Strategies:               {result.strategy_ids}")
    print(f"Window:                   {result.window}")
    print(f"Avg pairwise correlation: {result.avg_pairwise_correlation:.4f}")
    print(f"Diversification score:    {result.diversification_score:.1f}/100")
    print("Correlation matrix:")
    for sid, row in result.correlation_matrix.items():
        row_str = "  ".join(f"{tid}:{v:+.4f}" for tid, v in sorted(row.items()))
        print(f"  {sid}: {row_str}")
    if result.highly_correlated_pairs:
        print("Highly correlated pairs:")
        for p in result.highly_correlated_pairs:
            print(f"  {p[0]} ↔ {p[1]}: r = {p[2]:.4f}")
    for line in result.advisory:
        print(f"  - {line}")
    print()
    print(f"get_diversification_score() → {scm.get_diversification_score():.1f}")
    print(f"get_correlated_pairs()      → {scm.get_correlated_pairs()}")


if __name__ == "__main__":
    _demo()
