"""
MP-704: DrawdownTracker
Track portfolio drawdown over a NAV (net asset value) series. Computes the current
drawdown from the running peak, the maximum drawdown, the longest underwater
duration, a recovery factor and a Calmar-style return/max-drawdown ratio, and
classifies overall drawdown severity.
Pure stdlib only. Advisory/read-only. Atomic writes.
"""

from dataclasses import dataclass, field
from typing import List
import json
import time
import os
from pathlib import Path

DATA_FILE = Path("data/drawdown_log.json")
MAX_ENTRIES = 100

# Max-drawdown severity thresholds (as positive fraction of peak, 0..1).
DD_SHALLOW = 0.05    # < 5%
DD_MODERATE = 0.15   # < 15%
DD_SEVERE = 0.30     # < 30%
# >= 30% => CRITICAL


@dataclass
class NavPoint:
    timestamp: str
    value_usd: float


@dataclass
class DrawdownReport:
    num_points: int
    start_value_usd: float
    end_value_usd: float
    peak_value_usd: float
    trough_value_usd: float
    current_drawdown_pct: float      # 0..100, positive = below peak
    max_drawdown_pct: float          # 0..100
    max_drawdown_peak_usd: float
    max_drawdown_trough_usd: float
    underwater_now: bool
    longest_underwater_points: int   # longest run strictly below a prior peak
    total_return_pct: float          # end vs start, can be negative
    recovery_factor: float           # total_return_frac / max_drawdown_frac
    calmar_ratio: float              # alias of recovery_factor here (period-agnostic)
    severity: str                    # SHALLOW/MODERATE/SEVERE/CRITICAL/NONE/UNKNOWN
    advisory: List[str] = field(default_factory=list)
    generated_at: str = ""


class DrawdownTracker:
    """
    Computes drawdown statistics for a NAV time series.
    Advisory only — never modifies allocator, risk, or execution domains.
    """

    # ------------------------------------------------------------------
    # Calculation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _values(points: List[NavPoint]) -> List[float]:
        """Extract NAV values, ignoring non-positive points."""
        return [p.value_usd for p in points if p.value_usd > 0]

    @staticmethod
    def _classify(max_dd_frac: float) -> str:
        """Classify severity from the maximum drawdown fraction (0..1)."""
        if max_dd_frac <= 0:
            return "NONE"
        if max_dd_frac < DD_SHALLOW:
            return "SHALLOW"
        if max_dd_frac < DD_MODERATE:
            return "MODERATE"
        if max_dd_frac < DD_SEVERE:
            return "SEVERE"
        return "CRITICAL"

    @staticmethod
    def _build_advisory(
        severity: str,
        current_dd_pct: float,
        underwater_now: bool,
        recovery_factor: float,
    ) -> List[str]:
        out: List[str] = []
        if severity == "CRITICAL":
            out.append(
                "CRITICAL drawdown — portfolio fell 30%+ from peak; review risk "
                "sizing and protocol exposure"
            )
        elif severity == "SEVERE":
            out.append(
                "Severe drawdown (15-30% from peak) — consider de-risking until recovery"
            )
        elif severity == "MODERATE":
            out.append("Moderate drawdown (5-15%) — within normal yield-strategy variance")
        if underwater_now and current_dd_pct > 0:
            out.append(
                f"Currently underwater {current_dd_pct:.1f}% below the running peak"
            )
        if not underwater_now and severity not in ("UNKNOWN", "NONE"):
            out.append("Back at or above prior peak — fully recovered")
        if recovery_factor != 0.0 and recovery_factor < 1.0:
            out.append(
                "Recovery factor below 1.0 — cumulative return has not yet covered "
                "the worst peak-to-trough loss"
            )
        return out

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self, points: List[NavPoint]) -> DrawdownReport:
        """Compute a DrawdownReport for a NAV time series."""
        generated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        values = self._values(points)

        if len(values) < 2:
            return DrawdownReport(
                num_points=len(values),
                start_value_usd=round(values[0], 6) if values else 0.0,
                end_value_usd=round(values[-1], 6) if values else 0.0,
                peak_value_usd=round(values[0], 6) if values else 0.0,
                trough_value_usd=round(values[0], 6) if values else 0.0,
                current_drawdown_pct=0.0,
                max_drawdown_pct=0.0,
                max_drawdown_peak_usd=round(values[0], 6) if values else 0.0,
                max_drawdown_trough_usd=round(values[0], 6) if values else 0.0,
                underwater_now=False,
                longest_underwater_points=0,
                total_return_pct=0.0,
                recovery_factor=0.0,
                calmar_ratio=0.0,
                severity="UNKNOWN",
                advisory=["Need at least 2 positive NAV points to compute drawdown"],
                generated_at=generated_at,
            )

        peak = values[0]
        max_dd_frac = 0.0
        max_dd_peak = values[0]
        max_dd_trough = values[0]
        longest_uw = 0
        current_uw_run = 0

        for v in values:
            if v > peak:
                peak = v
            dd = (peak - v) / peak if peak > 0 else 0.0
            if v < peak:
                current_uw_run += 1
            else:
                current_uw_run = 0
            longest_uw = max(longest_uw, current_uw_run)
            if dd > max_dd_frac:
                max_dd_frac = dd
                max_dd_peak = peak
                max_dd_trough = v

        start_v = values[0]
        end_v = values[-1]
        running_peak = max(values)
        current_dd_frac = (running_peak - end_v) / running_peak if running_peak > 0 else 0.0
        underwater_now = end_v < running_peak

        total_return_frac = (end_v - start_v) / start_v if start_v > 0 else 0.0
        recovery_factor = round(total_return_frac / max_dd_frac, 6) if max_dd_frac > 0 else 0.0

        severity = self._classify(max_dd_frac)
        current_dd_pct = round(current_dd_frac * 100.0, 6)
        max_dd_pct = round(max_dd_frac * 100.0, 6)

        advisory = self._build_advisory(
            severity, current_dd_pct, underwater_now, recovery_factor
        )

        return DrawdownReport(
            num_points=len(values),
            start_value_usd=round(start_v, 6),
            end_value_usd=round(end_v, 6),
            peak_value_usd=round(running_peak, 6),
            trough_value_usd=round(min(values), 6),
            current_drawdown_pct=current_dd_pct,
            max_drawdown_pct=max_dd_pct,
            max_drawdown_peak_usd=round(max_dd_peak, 6),
            max_drawdown_trough_usd=round(max_dd_trough, 6),
            underwater_now=underwater_now,
            longest_underwater_points=longest_uw,
            total_return_pct=round(total_return_frac * 100.0, 6),
            recovery_factor=recovery_factor,
            calmar_ratio=recovery_factor,
            severity=severity,
            advisory=advisory,
            generated_at=generated_at,
        )

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save_report(self, report: DrawdownReport, data_file: Path = DATA_FILE) -> None:
        """Append a report to a ring-buffer JSON (max MAX_ENTRIES). Atomic write."""
        data_file = Path(data_file)
        existing = self.load_history(data_file)

        entry = {
            "timestamp": report.generated_at
            or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "num_points": report.num_points,
            "peak_value_usd": report.peak_value_usd,
            "current_drawdown_pct": report.current_drawdown_pct,
            "max_drawdown_pct": report.max_drawdown_pct,
            "underwater_now": report.underwater_now,
            "longest_underwater_points": report.longest_underwater_points,
            "total_return_pct": report.total_return_pct,
            "recovery_factor": report.recovery_factor,
            "severity": report.severity,
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
    tracker = DrawdownTracker()
    points = [
        NavPoint("2026-01-01", 100_000.0),
        NavPoint("2026-02-01", 108_000.0),
        NavPoint("2026-03-01", 95_000.0),
        NavPoint("2026-04-01", 88_000.0),
        NavPoint("2026-05-01", 101_000.0),
        NavPoint("2026-06-01", 112_000.0),
    ]
    report = tracker.analyze(points)
    print(f"Points:               {report.num_points}")
    print(f"Peak value:           ${report.peak_value_usd:,.0f}")
    print(f"Current drawdown:     {report.current_drawdown_pct:.2f}%")
    print(f"Max drawdown:         {report.max_drawdown_pct:.2f}%")
    print(f"Longest underwater:   {report.longest_underwater_points} points")
    print(f"Total return:         {report.total_return_pct:.2f}%")
    print(f"Recovery factor:      {report.recovery_factor:.2f}")
    print(f"Severity:             {report.severity}")
    for line in report.advisory:
        print(f"  - {line}")


if __name__ == "__main__":
    _demo()
