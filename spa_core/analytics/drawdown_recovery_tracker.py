"""
MP-647: DrawdownRecoveryTracker
Track drawdown episodes and how long they take to recover.

Advisory / read-only analytics module.
Pure stdlib. Atomic writes. Ring-buffer 100 entries.
"""

from dataclasses import dataclass
from typing import List, Optional
import json
import os
from pathlib import Path

DATA_FILE = Path("data/drawdown_recovery_log.json")
MAX_ENTRIES = 100


@dataclass
class DrawdownEpisode:
    strategy_id: str
    peak_apy: float          # APY at peak before drawdown
    trough_apy: float        # lowest APY during drawdown
    drawdown_pct: float      # (peak - trough) / peak
    start_day: int           # day index when drawdown started
    trough_day: int          # day when trough was reached
    recovery_day: Optional[int]   # day when recovered to peak (None if not yet)
    days_to_trough: int      # trough_day - start_day
    days_to_recover: Optional[int]  # recovery_day - trough_day (None if open)
    status: str              # RECOVERING / RECOVERED / DEEP (drawdown_pct > 15%)
    severity: str            # MINOR(<5%) / MODERATE(5-15%) / SEVERE(>15%)


class DrawdownRecoveryTracker:
    def __init__(self, data_file: Path = DATA_FILE):
        self.data_file = data_file

    def _severity(self, drawdown_pct: float) -> str:
        """Classify severity based on drawdown magnitude."""
        if drawdown_pct < 0.05:
            return "MINOR"
        if drawdown_pct < 0.15:
            return "MODERATE"
        return "SEVERE"

    def _status(self, episode: "DrawdownEpisode") -> str:
        """Determine episode status."""
        if episode.recovery_day is not None:
            return "RECOVERED"
        if episode.drawdown_pct > 0.15:
            return "DEEP"
        return "RECOVERING"

    def detect_episodes(
        self, strategy_id: str, apy_series: List[float]
    ) -> List[DrawdownEpisode]:
        """Detect all drawdown episodes in an APY time series."""
        if len(apy_series) < 2:
            return []

        episodes: List[DrawdownEpisode] = []
        peak = apy_series[0]
        peak_idx = 0
        in_drawdown = False
        trough = peak
        trough_idx = 0

        for i, val in enumerate(apy_series[1:], start=1):
            if val > peak:
                # New all-time high — if we were in a drawdown, it has recovered
                if in_drawdown:
                    dd_pct = (peak - trough) / peak if peak > 0 else 0.0
                    ep = DrawdownEpisode(
                        strategy_id=strategy_id,
                        peak_apy=round(peak, 6),
                        trough_apy=round(trough, 6),
                        drawdown_pct=round(dd_pct, 6),
                        start_day=peak_idx,
                        trough_day=trough_idx,
                        recovery_day=i,
                        days_to_trough=trough_idx - peak_idx,
                        days_to_recover=i - trough_idx,
                        status="RECOVERED",
                        severity=self._severity(dd_pct),
                    )
                    episodes.append(ep)
                    in_drawdown = False
                # Update peak
                peak = val
                peak_idx = i
                trough = val
                trough_idx = i
            elif val < peak:
                in_drawdown = True
                if val < trough:
                    trough = val
                    trough_idx = i

        # Check for open drawdown at end of series
        if in_drawdown:
            dd_pct = (peak - trough) / peak if peak > 0 else 0.0
            ep = DrawdownEpisode(
                strategy_id=strategy_id,
                peak_apy=round(peak, 6),
                trough_apy=round(trough, 6),
                drawdown_pct=round(dd_pct, 6),
                start_day=peak_idx,
                trough_day=trough_idx,
                recovery_day=None,
                days_to_trough=trough_idx - peak_idx,
                days_to_recover=None,
                status="DEEP" if dd_pct > 0.15 else "RECOVERING",
                severity=self._severity(dd_pct),
            )
            episodes.append(ep)

        return episodes

    def avg_recovery_days(self, episodes: List[DrawdownEpisode]) -> Optional[float]:
        """Average days to recover for RECOVERED episodes only."""
        recovered = [e for e in episodes if e.days_to_recover is not None]
        if not recovered:
            return None
        return sum(e.days_to_recover for e in recovered) / len(recovered)

    def worst_episode(self, episodes: List[DrawdownEpisode]) -> Optional[DrawdownEpisode]:
        """Return the episode with the highest drawdown_pct."""
        if not episodes:
            return None
        return max(episodes, key=lambda e: e.drawdown_pct)

    def save_episodes(self, episodes: List[DrawdownEpisode]) -> None:
        """Append episodes to ring-buffer JSON (max MAX_ENTRIES), atomic write."""
        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            existing = json.loads(self.data_file.read_text())
        except Exception:
            existing = []
        for ep in episodes:
            existing.append(
                {
                    "strategy_id": ep.strategy_id,
                    "peak_apy": ep.peak_apy,
                    "trough_apy": ep.trough_apy,
                    "drawdown_pct": ep.drawdown_pct,
                    "start_day": ep.start_day,
                    "trough_day": ep.trough_day,
                    "recovery_day": ep.recovery_day,
                    "days_to_trough": ep.days_to_trough,
                    "days_to_recover": ep.days_to_recover,
                    "status": ep.status,
                    "severity": ep.severity,
                }
            )
        # Ring-buffer: keep only latest MAX_ENTRIES
        existing = existing[-MAX_ENTRIES:]
        tmp = self.data_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(existing, indent=2))
        os.replace(tmp, self.data_file)

    def load_history(self) -> List[dict]:
        """Load persisted episode history. Returns [] if file missing/corrupt."""
        try:
            return json.loads(self.data_file.read_text())
        except Exception:
            return []


# ---------------------------------------------------------------------------
# CLI entry point (advisory, read-only)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    import argparse

    parser = argparse.ArgumentParser(description="MP-647 DrawdownRecoveryTracker")
    parser.add_argument("--check", action="store_true", default=True, help="Print stats without writing")
    parser.add_argument("--run", action="store_true", help="Compute and write to data file")
    parser.add_argument("--data-dir", default=None)
    args = parser.parse_args()

    data_file = DATA_FILE
    if args.data_dir:
        data_file = Path(args.data_dir) / "drawdown_recovery_log.json"

    tracker = DrawdownRecoveryTracker(data_file=data_file)
    history = tracker.load_history()
    print(f"MP-647 DrawdownRecoveryTracker — {len(history)} episodes persisted")
    sys.exit(0)
