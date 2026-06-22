"""
MP-645: YieldCurveBuilder
Build a yield curve across adapters sorted by maturity/lock-period.
Pure stdlib, read-only advisory module.
"""
from dataclasses import dataclass
from typing import List, Optional
import json
import time
import os
from pathlib import Path

DATA_FILE = Path("data/yield_curve.json")
MAX_ENTRIES = 100


@dataclass
class CurvePoint:
    adapter_id: str
    protocol: str
    lock_days: int      # 0 = liquid, 7 = weekly, 30 = monthly, 90 = quarterly
    apy: float          # current APY (decimal, e.g. 0.05 = 5%)
    tier: str           # T1 / T2 / T3
    is_liquid: bool     # True if lock_days == 0


@dataclass
class YieldCurveSnapshot:
    timestamp: float
    points: List[CurvePoint]    # sorted by lock_days ascending
    # Curve shape analysis
    slope_0_30: float           # APY difference between 0-day and 30-day points (bps)
    slope_30_90: float          # APY difference between 30-day and 90-day points (bps)
    curve_shape: str            # NORMAL / INVERTED / FLAT / HUMPED
    best_liquid_apy: float      # highest APY with lock_days == 0
    best_overall_apy: float     # highest APY regardless of lock
    optimal_point: str          # adapter_id of best risk-adjusted point (highest APY / lock_days+1)


class YieldCurveBuilder:
    def __init__(self, data_file: Path = DATA_FILE):
        self.data_file = data_file

    def build_curve(self, points: List[CurvePoint]) -> YieldCurveSnapshot:
        """Build a YieldCurveSnapshot from a list of CurvePoints."""
        if not points:
            return YieldCurveSnapshot(
                timestamp=time.time(),
                points=[],
                slope_0_30=0.0,
                slope_30_90=0.0,
                curve_shape="FLAT",
                best_liquid_apy=0.0,
                best_overall_apy=0.0,
                optimal_point="none",
            )

        sorted_points = sorted(points, key=lambda p: (p.lock_days, -p.apy))

        # Compute slopes in bps
        apy_at_0 = self._apy_at_lock(sorted_points, 0)
        apy_at_30 = self._apy_at_lock(sorted_points, 30)
        apy_at_90 = self._apy_at_lock(sorted_points, 90)

        slope_0_30 = (apy_at_30 - apy_at_0) * 10000   # bps
        slope_30_90 = (apy_at_90 - apy_at_30) * 10000

        curve_shape = self._classify_shape(slope_0_30, slope_30_90, sorted_points)

        liquid = [p for p in sorted_points if p.is_liquid]
        best_liquid = max((p.apy for p in liquid), default=0.0)
        best_overall = max((p.apy for p in sorted_points), default=0.0)

        # Optimal: maximize apy / (lock_days + 1) → reward per day of lock
        def score(p: CurvePoint) -> float:
            return p.apy / (p.lock_days + 1)

        optimal = max(sorted_points, key=score) if sorted_points else None

        return YieldCurveSnapshot(
            timestamp=time.time(),
            points=sorted_points,
            slope_0_30=round(slope_0_30, 2),
            slope_30_90=round(slope_30_90, 2),
            curve_shape=curve_shape,
            best_liquid_apy=round(best_liquid, 6),
            best_overall_apy=round(best_overall, 6),
            optimal_point=optimal.adapter_id if optimal else "none",
        )

    def _apy_at_lock(self, sorted_points: List[CurvePoint], target_days: int) -> float:
        """Return APY of closest point to target_days, or interpolate."""
        if not sorted_points:
            return 0.0
        exact = [p for p in sorted_points if p.lock_days == target_days]
        if exact:
            return max(p.apy for p in exact)
        # Find nearest point by absolute distance; tie-break: lower lock_days wins
        nearest = min(sorted_points, key=lambda p: abs(p.lock_days - target_days))
        return nearest.apy

    def _classify_shape(
        self,
        slope_0_30: float,
        slope_30_90: float,
        points: List[CurvePoint],
    ) -> str:
        """Classify the yield curve shape: NORMAL / INVERTED / FLAT / HUMPED."""
        FLAT_THRESHOLD = 5.0  # bps

        if abs(slope_0_30) < FLAT_THRESHOLD and abs(slope_30_90) < FLAT_THRESHOLD:
            return "FLAT"
        if slope_0_30 > FLAT_THRESHOLD and slope_30_90 < -FLAT_THRESHOLD:
            return "HUMPED"
        if slope_0_30 > FLAT_THRESHOLD or slope_30_90 > FLAT_THRESHOLD:
            return "NORMAL"
        return "INVERTED"

    def save_snapshot(self, snapshot: YieldCurveSnapshot) -> None:
        """Atomically append snapshot summary to the ring-buffer JSON file."""
        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            existing = json.loads(self.data_file.read_text())
        except Exception:
            existing = []
        entry = {
            "timestamp": snapshot.timestamp,
            "point_count": len(snapshot.points),
            "slope_0_30": snapshot.slope_0_30,
            "slope_30_90": snapshot.slope_30_90,
            "curve_shape": snapshot.curve_shape,
            "best_liquid_apy": snapshot.best_liquid_apy,
            "best_overall_apy": snapshot.best_overall_apy,
            "optimal_point": snapshot.optimal_point,
        }
        existing.append(entry)
        existing = existing[-MAX_ENTRIES:]
        tmp = self.data_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(existing, indent=2))
        os.replace(tmp, self.data_file)

    def load_history(self) -> List[dict]:
        """Load saved snapshot history; returns [] if file missing/invalid."""
        try:
            return json.loads(self.data_file.read_text())
        except Exception:
            return []

    def get_inversion_alert(self, snapshot: YieldCurveSnapshot) -> Optional[str]:
        """Return warning if curve is inverted (unusual in DeFi, may signal risk)."""
        if snapshot.curve_shape == "INVERTED":
            return (
                f"⚠️ Yield curve INVERTED: short-term rates "
                f"({snapshot.best_liquid_apy:.1%}) exceed long-term. "
                f"Possible liquidity stress."
            )
        return None


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

def _demo_points() -> List[CurvePoint]:
    """Return a minimal demo set of CurvePoints for smoke-testing."""
    return [
        CurvePoint("aave_v3", "Aave V3", 0, 0.035, "T1", True),
        CurvePoint("compound_v3", "Compound V3", 7, 0.048, "T1", False),
        CurvePoint("morpho_steakhouse", "Morpho Steakhouse", 30, 0.065, "T1", False),
        CurvePoint("euler_v2", "Euler V2", 90, 0.072, "T2", False),
        CurvePoint("pendle_pt", "Pendle PT", 180, 0.12, "T3", False),
    ]


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="MP-645 YieldCurveBuilder")
    parser.add_argument("--run", action="store_true", help="Compute + save to data file")
    parser.add_argument("--check", action="store_true", help="Compute + print, no save (default)")
    parser.add_argument("--data-dir", default=None, help="Override data directory")
    args = parser.parse_args()

    data_file = DATA_FILE
    if args.data_dir:
        data_file = Path(args.data_dir) / "yield_curve.json"

    builder = YieldCurveBuilder(data_file=data_file)
    points = _demo_points()
    snapshot = builder.build_curve(points)

    print(f"Curve shape : {snapshot.curve_shape}")
    print(f"slope_0_30  : {snapshot.slope_0_30:.2f} bps")
    print(f"slope_30_90 : {snapshot.slope_30_90:.2f} bps")
    print(f"Best liquid : {snapshot.best_liquid_apy:.2%}")
    print(f"Best overall: {snapshot.best_overall_apy:.2%}")
    print(f"Optimal pt  : {snapshot.optimal_point}")
    alert = builder.get_inversion_alert(snapshot)
    if alert:
        print(alert)

    if args.run:
        builder.save_snapshot(snapshot)
        print(f"Saved → {data_file}")
