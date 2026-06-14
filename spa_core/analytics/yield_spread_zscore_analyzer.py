"""
MP-745: YieldSpreadZScoreAnalyzer
Given a historical series of a yield spread (e.g. APY_a - APY_b in percent),
compute the z-score of the latest value versus its own history to flag
mean-reversion opportunities. A very negative z-score means the spread is
unusually low relative to history (a reversion upward is expected); a very
positive z-score means the spread is unusually wide. Pure stdlib only.
Advisory/read-only. Atomic writes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional
import json
import math
import time
import os
from pathlib import Path

DATA_FILE = Path("data/yield_spread_zscore_log.json")
MAX_ENTRIES = 100

# Default z-score magnitude treated as an entry-worthy extreme.
DEFAULT_ENTRY_Z = 2.0

# Boundary between LEAN and NEUTRAL bands (in z units).
_LEAN_Z = 1.0

# Below this stdev the spread is effectively constant — z-score is undefined,
# reported as 0.0 (guards against floating-point dust on a flat series).
_ZERO_EPS = 1e-12


@dataclass
class SpreadZReport:
    label: str
    samples: int
    current_spread: Optional[float]
    mean_spread: float
    stdev_spread: float                  # sample (n-1) stdev
    zscore: float                        # (current-mean)/stdev; 0.0 if stdev<=eps
    min_spread: Optional[float]
    max_spread: Optional[float]
    spread_range: float                  # max - min
    percentile_of_current: float         # fraction of samples <= current (0..1)
    entry_z: float
    signal_tier: str                     # STRONG_LONG/LEAN_LONG/NEUTRAL/LEAN_SHORT/STRONG_SHORT/UNKNOWN
    advisory: str = ""
    generated_at: str = ""


class YieldSpreadZScoreAnalyzer:
    """
    Computes a z-score of the latest yield spread versus its history.
    Advisory only — never modifies allocator, risk, or execution domains.
    """

    # ------------------------------------------------------------------
    # Calculation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _mean(xs: List[float]) -> float:
        return sum(xs) / len(xs) if xs else 0.0

    @staticmethod
    def _sample_stdev(xs: List[float], mean: float) -> float:
        """Sample (n-1) standard deviation. 0.0 for fewer than 2 points."""
        if len(xs) < 2:
            return 0.0
        var = sum((x - mean) ** 2 for x in xs) / (len(xs) - 1)
        return math.sqrt(var)

    @staticmethod
    def _percentile_of(xs: List[float], value: float) -> float:
        """Fraction of samples <= *value* (0..1)."""
        if not xs:
            return 0.0
        return sum(1 for x in xs if x <= value) / len(xs)

    @staticmethod
    def _classify(zscore: float, entry_z: float) -> str:
        """
        Map a z-score to a mean-reversion signal tier.

        A very negative z (spread unusually low) implies the spread is likely to
        revert upward => STRONG_LONG. A very positive z => STRONG_SHORT.
        """
        if zscore <= -entry_z:
            return "STRONG_LONG"
        if zscore <= -_LEAN_Z:
            return "LEAN_LONG"
        if zscore < _LEAN_Z:
            return "NEUTRAL"
        if zscore < entry_z:
            return "LEAN_SHORT"
        return "STRONG_SHORT"

    @staticmethod
    def _build_advisory(tier: str, label: str, zscore: float) -> str:
        if tier == "STRONG_LONG":
            return (
                f"{label} spread unusually low (z={zscore:.2f}); mean-reversion up "
                f"expected — possible long entry"
            )
        if tier == "LEAN_LONG":
            return (
                f"{label} spread modestly below mean (z={zscore:.2f}); mild upward "
                f"reversion bias"
            )
        if tier == "NEUTRAL":
            return (
                f"{label} spread near its historical mean (z={zscore:.2f}); no "
                f"reversion edge"
            )
        if tier == "LEAN_SHORT":
            return (
                f"{label} spread modestly above mean (z={zscore:.2f}); mild downward "
                f"reversion bias"
            )
        return (
            f"{label} spread unusually wide (z={zscore:.2f}); mean-reversion down "
            f"expected — possible short entry"
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(
        self,
        spreads: List[float],
        entry_z: float = DEFAULT_ENTRY_Z,
        label: str = "spread",
    ) -> SpreadZReport:
        """Compute a SpreadZReport from a historical spread series."""
        generated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        if len(spreads) < 2:
            current = spreads[-1] if spreads else None
            return SpreadZReport(
                label=label,
                samples=len(spreads),
                current_spread=round(current, 6) if current is not None else None,
                mean_spread=round(self._mean(spreads), 6),
                stdev_spread=0.0,
                zscore=0.0,
                min_spread=round(min(spreads), 6) if spreads else None,
                max_spread=round(max(spreads), 6) if spreads else None,
                spread_range=0.0,
                percentile_of_current=(
                    self._percentile_of(spreads, current) if current is not None else 0.0
                ),
                entry_z=entry_z,
                signal_tier="UNKNOWN",
                advisory=f"Need at least 2 samples to z-score {label}",
                generated_at=generated_at,
            )

        current = spreads[-1]
        mean = self._mean(spreads)
        stdev = self._sample_stdev(spreads, mean)

        if stdev <= _ZERO_EPS:
            zscore = 0.0
        else:
            zscore = (current - mean) / stdev

        lo = min(spreads)
        hi = max(spreads)
        percentile = self._percentile_of(spreads, current)

        tier = self._classify(zscore, entry_z)
        advisory = self._build_advisory(tier, label, zscore)

        return SpreadZReport(
            label=label,
            samples=len(spreads),
            current_spread=round(current, 6),
            mean_spread=round(mean, 6),
            stdev_spread=round(stdev, 6),
            zscore=round(zscore, 6),
            min_spread=round(lo, 6),
            max_spread=round(hi, 6),
            spread_range=round(hi - lo, 6),
            percentile_of_current=round(percentile, 6),
            entry_z=entry_z,
            signal_tier=tier,
            advisory=advisory,
            generated_at=generated_at,
        )

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save_report(self, report: SpreadZReport, data_file: Path = DATA_FILE) -> None:
        """Append a report to a ring-buffer JSON (max MAX_ENTRIES). Atomic write."""
        data_file = Path(data_file)
        existing = self.load_history(data_file)

        entry = {
            "timestamp": report.generated_at
            or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "label": report.label,
            "samples": report.samples,
            "current_spread": report.current_spread,
            "mean_spread": report.mean_spread,
            "stdev_spread": report.stdev_spread,
            "zscore": report.zscore,
            "min_spread": report.min_spread,
            "max_spread": report.max_spread,
            "spread_range": report.spread_range,
            "percentile_of_current": report.percentile_of_current,
            "entry_z": report.entry_z,
            "signal_tier": report.signal_tier,
            "advisory": report.advisory,
        }

        combined = (existing + [entry])[-MAX_ENTRIES:]

        data_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = data_file.with_suffix(".tmp")
        with open(tmp, "w") as fh:
            json.dump(combined, fh, indent=2)
        os.replace(tmp, data_file)

    def load_history(self, data_file: Path = DATA_FILE) -> list:
        """Load history from ring-buffer JSON. Returns [] if missing or corrupt."""
        data_file = Path(data_file)
        if not data_file.exists():
            return []
        try:
            with open(data_file, "r") as fh:
                return json.load(fh)
        except (json.JSONDecodeError, OSError):
            return []


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _demo() -> None:
    analyzer = YieldSpreadZScoreAnalyzer()
    # APY_a - APY_b spread history (percent); latest value is unusually low.
    spreads = [1.2, 1.3, 1.1, 1.4, 1.25, 1.35, 1.15, 1.3, 0.4]
    report = analyzer.analyze(spreads, entry_z=2.0, label="aave-compound")
    print(f"Label:                {report.label}")
    print(f"Samples:              {report.samples}")
    print(f"Current spread:       {report.current_spread}")
    print(f"Mean spread:          {report.mean_spread}")
    print(f"Stdev spread:         {report.stdev_spread}")
    print(f"Z-score:              {report.zscore}")
    print(f"Min / Max spread:     {report.min_spread} / {report.max_spread}")
    print(f"Spread range:         {report.spread_range}")
    print(f"Percentile of current:{report.percentile_of_current}")
    print(f"Signal tier:          {report.signal_tier}")
    print(f"Advisory:             {report.advisory}")


if __name__ == "__main__":
    _demo()
