"""
MP-744: StablecoinDepegMonitor
Monitor a stablecoin price series (list of floats clustered around a peg, e.g. 1.0)
for depeg risk. Reports current deviation, max/min deviation, dispersion, the
fraction of time the series spent beyond a depeg threshold, the longest consecutive
depeg run, and a severity tier based on the current absolute deviation in basis
points. Pure stdlib only. Advisory/read-only. Atomic writes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional
import json
import math
import time
import os
from pathlib import Path

DATA_FILE = Path("data/stablecoin_depeg_log.json")
MAX_ENTRIES = 100

# Default peg target for USD stablecoins.
DEFAULT_PEG = 1.0
# Default depeg threshold in basis points (50 bps == 0.5%).
DEFAULT_DEPEG_THRESHOLD_BPS = 50.0

# Severity tiers, keyed on the current ABSOLUTE deviation in basis points.
SEVERITY_STABLE_BPS = 25.0      # < 25 bps  => STABLE
SEVERITY_MINOR_BPS = 50.0       # < 50 bps  => MINOR
SEVERITY_MODERATE_BPS = 200.0   # < 200 bps => MODERATE
SEVERITY_SEVERE_BPS = 500.0     # < 500 bps => SEVERE
# >= 500 bps => CRITICAL

# One basis point == 1/100th of a percent.
_BPS_PER_PCT = 100.0


@dataclass
class DepegReport:
    symbol: str
    peg: float
    samples: int
    current_price: Optional[float]
    current_deviation_pct: float          # signed, (current-peg)/peg*100
    current_deviation_bps: float          # abs deviation, basis points
    max_deviation_pct: float              # signed value at point of largest |dev|
    min_price: Optional[float]
    max_price: Optional[float]
    mean_price: float
    stdev_price: float                    # sample (n-1) stdev; 0 if <2 samples
    depeg_threshold_bps: float
    samples_below_threshold: int          # count beyond threshold
    pct_time_depegged: float              # fraction (0..1) beyond threshold
    longest_depeg_run: int                # longest consecutive run beyond threshold
    severity_tier: str                    # STABLE/MINOR/MODERATE/SEVERE/CRITICAL/UNKNOWN
    advisory: str = ""
    generated_at: str = ""


class StablecoinDepegMonitor:
    """
    Monitors a stablecoin price series for depeg risk.
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
    def _deviation_pct(price: float, peg: float) -> float:
        """Signed percentage deviation of *price* from *peg*."""
        if peg == 0:
            return 0.0
        return (price - peg) / peg * 100.0

    @classmethod
    def _deviation_bps(cls, price: float, peg: float) -> float:
        """Absolute deviation of *price* from *peg* in basis points."""
        return abs(cls._deviation_pct(price, peg)) * _BPS_PER_PCT

    @staticmethod
    def _longest_run(flags: List[bool]) -> int:
        """Longest consecutive run of True values in *flags*."""
        longest = 0
        current = 0
        for f in flags:
            if f:
                current += 1
                if current > longest:
                    longest = current
            else:
                current = 0
        return longest

    @staticmethod
    def _classify(current_deviation_bps: float) -> str:
        if current_deviation_bps < SEVERITY_STABLE_BPS:
            return "STABLE"
        if current_deviation_bps < SEVERITY_MINOR_BPS:
            return "MINOR"
        if current_deviation_bps < SEVERITY_MODERATE_BPS:
            return "MODERATE"
        if current_deviation_bps < SEVERITY_SEVERE_BPS:
            return "SEVERE"
        return "CRITICAL"

    @staticmethod
    def _build_advisory(
        tier: str,
        symbol: str,
        current_deviation_bps: float,
        pct_time_depegged: float,
        longest_depeg_run: int,
    ) -> str:
        pct = pct_time_depegged * 100.0
        if tier == "STABLE":
            return (
                f"{symbol} holding peg (current deviation {current_deviation_bps:.1f} "
                f"bps); no action needed"
            )
        if tier == "MINOR":
            return (
                f"{symbol} minor wobble ({current_deviation_bps:.1f} bps off peg); "
                f"monitor — spent {pct:.1f}% of samples beyond threshold"
            )
        if tier == "MODERATE":
            return (
                f"{symbol} moderate depeg ({current_deviation_bps:.1f} bps off peg, "
                f"longest run {longest_depeg_run}); review exposure"
            )
        if tier == "SEVERE":
            return (
                f"{symbol} severe depeg ({current_deviation_bps:.1f} bps off peg); "
                f"consider reducing exposure"
            )
        return (
            f"{symbol} CRITICAL depeg ({current_deviation_bps:.1f} bps off peg); "
            f"peg likely broken — advisory only, verify before acting"
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(
        self,
        prices: List[float],
        peg: float = DEFAULT_PEG,
        symbol: str = "STABLE",
        depeg_threshold_bps: float = DEFAULT_DEPEG_THRESHOLD_BPS,
    ) -> DepegReport:
        """Compute a DepegReport from a price series clustered around *peg*."""
        generated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        if not prices:
            return DepegReport(
                symbol=symbol,
                peg=peg,
                samples=0,
                current_price=None,
                current_deviation_pct=0.0,
                current_deviation_bps=0.0,
                max_deviation_pct=0.0,
                min_price=None,
                max_price=None,
                mean_price=0.0,
                stdev_price=0.0,
                depeg_threshold_bps=depeg_threshold_bps,
                samples_below_threshold=0,
                pct_time_depegged=0.0,
                longest_depeg_run=0,
                severity_tier="UNKNOWN",
                advisory=f"No price samples for {symbol} — cannot assess peg",
                generated_at=generated_at,
            )

        n = len(prices)
        current_price = prices[-1]
        current_dev_pct = self._deviation_pct(current_price, peg)
        current_dev_bps = abs(current_dev_pct) * _BPS_PER_PCT

        # Largest-absolute-deviation point, reported as its SIGNED percentage.
        max_dev_pct = max(
            (self._deviation_pct(p, peg) for p in prices),
            key=lambda d: abs(d),
        )

        mean_price = self._mean(prices)
        stdev_price = self._sample_stdev(prices, mean_price)

        # Threshold breach flags (abs deviation in bps strictly above threshold).
        flags = [self._deviation_bps(p, peg) > depeg_threshold_bps for p in prices]
        samples_below = sum(1 for f in flags if f)
        pct_time_depegged = samples_below / n
        longest_run = self._longest_run(flags)

        tier = self._classify(current_dev_bps)
        advisory = self._build_advisory(
            tier, symbol, current_dev_bps, pct_time_depegged, longest_run
        )

        return DepegReport(
            symbol=symbol,
            peg=peg,
            samples=n,
            current_price=round(current_price, 6),
            current_deviation_pct=round(current_dev_pct, 6),
            current_deviation_bps=round(current_dev_bps, 6),
            max_deviation_pct=round(max_dev_pct, 6),
            min_price=round(min(prices), 6),
            max_price=round(max(prices), 6),
            mean_price=round(mean_price, 6),
            stdev_price=round(stdev_price, 6),
            depeg_threshold_bps=depeg_threshold_bps,
            samples_below_threshold=samples_below,
            pct_time_depegged=round(pct_time_depegged, 6),
            longest_depeg_run=longest_run,
            severity_tier=tier,
            advisory=advisory,
            generated_at=generated_at,
        )

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save_report(self, report: DepegReport, data_file: Path = DATA_FILE) -> None:
        """Append a report to a ring-buffer JSON (max MAX_ENTRIES). Atomic write."""
        data_file = Path(data_file)
        existing = self.load_history(data_file)

        entry = {
            "timestamp": report.generated_at
            or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "symbol": report.symbol,
            "peg": report.peg,
            "samples": report.samples,
            "current_price": report.current_price,
            "current_deviation_pct": report.current_deviation_pct,
            "current_deviation_bps": report.current_deviation_bps,
            "max_deviation_pct": report.max_deviation_pct,
            "min_price": report.min_price,
            "max_price": report.max_price,
            "mean_price": report.mean_price,
            "stdev_price": report.stdev_price,
            "depeg_threshold_bps": report.depeg_threshold_bps,
            "samples_below_threshold": report.samples_below_threshold,
            "pct_time_depegged": report.pct_time_depegged,
            "longest_depeg_run": report.longest_depeg_run,
            "severity_tier": report.severity_tier,
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
    monitor = StablecoinDepegMonitor()
    # A series that drifts slightly off the $1.00 peg then partially recovers.
    prices = [1.0001, 0.9998, 0.9995, 0.9990, 0.9982, 0.9975, 0.9988, 0.9993]
    report = monitor.analyze(prices, peg=1.0, symbol="USDC")
    print(f"Symbol:               {report.symbol}")
    print(f"Samples:              {report.samples}")
    print(f"Current price:        {report.current_price}")
    print(f"Current deviation:    {report.current_deviation_pct:.4f}% "
          f"({report.current_deviation_bps:.2f} bps)")
    print(f"Max deviation:        {report.max_deviation_pct:.4f}%")
    print(f"Min / Max price:      {report.min_price} / {report.max_price}")
    print(f"Mean price:           {report.mean_price}")
    print(f"Stdev price:          {report.stdev_price}")
    print(f"Samples beyond thr:   {report.samples_below_threshold}")
    print(f"Pct time depegged:    {report.pct_time_depegged * 100:.2f}%")
    print(f"Longest depeg run:    {report.longest_depeg_run}")
    print(f"Severity tier:        {report.severity_tier}")
    print(f"Advisory:             {report.advisory}")


if __name__ == "__main__":
    _demo()
