"""
spa_core/analytics/paper_evidence_tracker_v2.py

MP-1326: Paper Evidence Tracker v2 — CPA Quality Scoring

Tracks evidence accumulation during paper trading period.
Each paper day is evidence. Quality of evidence depends on:
  - Market regime (bull / bear / neutral / extreme)
  - Protocols used (CLEAN_INCLUDED vs PENDING / RESEARCH_ONLY / SOURCE_NEEDED)
  - Drift between planned and executed allocation (drift_pct)
  - Whether the day constitutes a stress test (extreme market)

Evidence score per day:
  - extreme market regime         → 1.5 pts  (stress-test evidence, highest value)
  - CLEAN sources, drift <= 2%   → 1.0 pts  (full evidence)
  - high drift (drift_pct > 2%)  → 0.5 pts  (weak evidence — allocation deviated)
  - any non-CLEAN source present → 0.3 pts  (model-based, not verifiable)

Priority (highest wins):
  extreme > high_drift > non_clean > default

To reach PAPER_SUFFICIENT:
  Need >= 30.0 total evidence points.
  Ring-buffer cap: 100 days (oldest dropped when exceeded).

Output file: data/paper/evidence_v2.json
Atomic writes: mkstemp + os.replace, stdlib only.

CLI:
    python3 -m spa_core.analytics.paper_evidence_tracker_v2 --check
    python3 -m spa_core.analytics.paper_evidence_tracker_v2 --run
    python3 -m spa_core.analytics.paper_evidence_tracker_v2 --run --data-dir data/paper
"""

from __future__ import annotations

import json
import math
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional

from spa_core.base import BaseAnalytics

# ─── Constants ────────────────────────────────────────────────────────────────

DEFAULT_PATH = "data/paper/evidence_v2.json"
SCHEMA_VERSION = "2.0"

# Source quality states — only CLEAN_INCLUDED gives full evidence
CLEAN_SOURCE = "CLEAN_INCLUDED"

# Evidence scoring thresholds
SCORE_EXTREME = 1.5      # stress-test day (extreme market)
SCORE_CLEAN = 1.0        # clean sources, normal/bull/bear regime, low drift
SCORE_HIGH_DRIFT = 0.5   # drift > HIGH_DRIFT_THRESHOLD — allocation deviated
SCORE_RESEARCH = 0.3     # any non-CLEAN source present

HIGH_DRIFT_THRESHOLD = 2.0   # percent


# ─── EvidenceDay ──────────────────────────────────────────────────────────────

class EvidenceDay:
    """
    A single day of paper trading, annotated with CPA quality metadata.

    Attributes:
        date          ISO-8601 date string (YYYY-MM-DD)
        nav           Net Asset Value at end of day
        allocations   dict[protocol_name -> weight_pct]  (0–100 scale)
        sources_used  list of source quality states for active protocols
        market_regime "bull" | "bear" | "neutral" | "extreme"
        drift_pct     abs(planned_weight - actual_weight) averaged across positions
    """

    def __init__(
        self,
        date: str,
        nav: float,
        allocations: Dict[str, float],
        sources_used: List[str],
        market_regime: str,
        drift_pct: float,
    ) -> None:
        self.date = date
        self.nav = float(nav)
        self.allocations = dict(allocations)
        self.sources_used = list(sources_used)
        self.market_regime = market_regime
        self.drift_pct = float(drift_pct)

    # ── Scoring ───────────────────────────────────────────────────────────────

    def evidence_score(self) -> float:
        """
        Return evidence quality score for this day.

        Priority (highest wins):
          1. extreme regime → 1.5  (stress-test evidence)
          2. drift > 2%    → 0.5  (weak: allocation deviated from plan)
          3. any non-CLEAN → 0.3  (model-based, not verifiable on-chain)
          4. default        → 1.0  (CLEAN sources, normal/bull/bear, low drift)
        """
        if self.market_regime == "extreme":
            return SCORE_EXTREME
        if self.drift_pct > HIGH_DRIFT_THRESHOLD:
            return SCORE_HIGH_DRIFT
        if not self._all_clean():
            return SCORE_RESEARCH
        return SCORE_CLEAN

    def _all_clean(self) -> bool:
        """True if sources_used is non-empty and every entry is CLEAN_INCLUDED."""
        return bool(self.sources_used) and all(
            s == CLEAN_SOURCE for s in self.sources_used
        )

    # ── Serialisation ─────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "date": self.date,
            "nav": self.nav,
            "allocations": self.allocations,
            "sources_used": self.sources_used,
            "market_regime": self.market_regime,
            "drift_pct": self.drift_pct,
            "evidence_score": self.evidence_score(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "EvidenceDay":
        return cls(
            date=d["date"],
            nav=d["nav"],
            allocations=d.get("allocations", {}),
            sources_used=d.get("sources_used", []),
            market_regime=d.get("market_regime", "neutral"),
            drift_pct=d.get("drift_pct", 0.0),
        )

    def __repr__(self) -> str:
        return (
            f"EvidenceDay({self.date!r}, nav={self.nav:.2f}, "
            f"regime={self.market_regime!r}, drift={self.drift_pct:.2f}%, "
            f"score={self.evidence_score():.1f})"
        )


# ─── PaperEvidenceTrackerV2 ───────────────────────────────────────────────────

class PaperEvidenceTrackerV2(BaseAnalytics):
    """
    Accumulates EvidenceDay records and measures CPA evidence sufficiency.

    Ring-buffer: maximum 100 days stored; oldest discarded when exceeded.
    Atomic persistence: mkstemp + os.replace on every save().
    Stdlib only — no external dependencies.
    """

    OUTPUT_PATH = "data/paper/evidence_v2.json"

    SUFFICIENT_EVIDENCE_POINTS: float = 30.0
    RING_BUFFER_CAP: int = 100

    def __init__(self, path: str = DEFAULT_PATH) -> None:
        super().__init__()
        self.path = path
        self._days: List[EvidenceDay] = []
        self._load()

    def to_dict(self) -> dict:
        """Returns accumulated evidence days as JSON-serializable dict."""
        return {
            "schema_version": SCHEMA_VERSION,
            "sufficient_threshold": self.SUFFICIENT_EVIDENCE_POINTS,
            "ring_buffer_cap": self.RING_BUFFER_CAP,
            "days": [d.to_dict() for d in self._days],
        }

    # ── Record ────────────────────────────────────────────────────────────────

    def record_day(self, day: EvidenceDay) -> None:
        """
        Append a new evidence day.

        Enforces ring-buffer cap: if len exceeds RING_BUFFER_CAP after
        appending, the oldest entry is dropped.
        """
        self._days.append(day)
        if len(self._days) > self.RING_BUFFER_CAP:
            self._days = self._days[-self.RING_BUFFER_CAP:]

    # ── Scoring ───────────────────────────────────────────────────────────────

    def total_evidence_points(self) -> float:
        """Sum of evidence_score() across all recorded days."""
        return sum(d.evidence_score() for d in self._days)

    def clean_evidence_points(self) -> float:
        """
        Evidence points from CLEAN_INCLUDED-only days.

        A day contributes to this total only when every source in
        sources_used is CLEAN_INCLUDED (and sources_used is non-empty).
        """
        return sum(
            d.evidence_score()
            for d in self._days
            if d._all_clean()
        )

    def is_evidence_sufficient(self) -> bool:
        """True if total evidence points >= SUFFICIENT_EVIDENCE_POINTS (30.0)."""
        return self.total_evidence_points() >= self.SUFFICIENT_EVIDENCE_POINTS

    def days_until_sufficient(self) -> int:
        """
        Estimated trading days remaining to reach sufficiency.

        Assumes each future day will score SCORE_CLEAN (1.0).
        Returns 0 if already sufficient.
        """
        if self.is_evidence_sufficient():
            return 0
        remaining = self.SUFFICIENT_EVIDENCE_POINTS - self.total_evidence_points()
        return math.ceil(remaining)

    # ── Report ────────────────────────────────────────────────────────────────

    def evidence_report(self) -> dict:
        """
        Full evidence accumulation report.

        Returns:
            {
              "total_points":     float,
              "clean_points":     float,
              "days_recorded":    int,
              "sufficient":       bool,
              "days_remaining":   int,
              "completion_pct":   float,   # 0–100
              "regimes_covered":  {"bull": N, "bear": N, "neutral": N, "extreme": N},
              "avg_drift_pct":    float,
            }
        """
        total = self.total_evidence_points()
        clean = self.clean_evidence_points()
        n = len(self._days)
        sufficient = self.is_evidence_sufficient()
        remaining = self.days_until_sufficient()
        completion = min(100.0, total / self.SUFFICIENT_EVIDENCE_POINTS * 100.0)

        regimes: Dict[str, int] = {"bull": 0, "bear": 0, "neutral": 0, "extreme": 0}
        total_drift = 0.0
        for d in self._days:
            regime = d.market_regime
            regimes[regime] = regimes.get(regime, 0) + 1
            total_drift += d.drift_pct

        avg_drift = (total_drift / n) if n > 0 else 0.0

        return {
            "total_points": round(total, 4),
            "clean_points": round(clean, 4),
            "days_recorded": n,
            "sufficient": sufficient,
            "days_remaining": remaining,
            "completion_pct": round(completion, 2),
            "regimes_covered": regimes,
            "avg_drift_pct": round(avg_drift, 4),
        }

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load(self) -> None:
        """
        Load state from JSON file.

        Graceful on missing or malformed file (starts empty).
        """
        try:
            with open(self.path) as fh:
                raw = json.load(fh)
            self._days = [EvidenceDay.from_dict(d) for d in raw.get("days", [])]
        except (FileNotFoundError, json.JSONDecodeError, KeyError):
            self._days = []

    def save(self) -> None:
        """
        Persist state atomically via mkstemp + os.replace.

        Creates parent directories if needed.
        """
        path = Path(self.path)
        path.parent.mkdir(parents=True, exist_ok=True)

        payload = {
            "schema_version": SCHEMA_VERSION,
            "sufficient_threshold": self.SUFFICIENT_EVIDENCE_POINTS,
            "ring_buffer_cap": self.RING_BUFFER_CAP,
            "days": [d.to_dict() for d in self._days],
        }

        from spa_core.utils.atomic import atomic_save
        atomic_save(payload, str(path))

    # ── Helpers ───────────────────────────────────────────────────────────────

    def __len__(self) -> int:
        return len(self._days)

    def __repr__(self) -> str:
        pts = self.total_evidence_points()
        return (
            f"PaperEvidenceTrackerV2(days={len(self._days)}, "
            f"points={pts:.1f}/{self.SUFFICIENT_EVIDENCE_POINTS}, "
            f"sufficient={self.is_evidence_sufficient()})"
        )


# ─── CLI ──────────────────────────────────────────────────────────────────────

def _print_report(report: dict) -> None:
    """Human-readable CLI output."""
    print("=" * 60)
    print("MP-1326 Paper Evidence Tracker v2 — CPA Quality Scoring")
    print("=" * 60)
    print(f"Days recorded:   {report['days_recorded']}")
    print(f"Total points:    {report['total_points']:.2f} / {PaperEvidenceTrackerV2.SUFFICIENT_EVIDENCE_POINTS:.1f}")
    print(f"Clean points:    {report['clean_points']:.2f}")
    print(f"Completion:      {report['completion_pct']:.1f}%")
    print(f"Sufficient:      {'YES' if report['sufficient'] else 'NO'}")
    print(f"Days remaining:  {report['days_remaining']}")
    print(f"Avg drift:       {report['avg_drift_pct']:.2f}%")
    print()
    print("Regimes covered:")
    for regime, count in report["regimes_covered"].items():
        print(f"  {regime:10s}: {count}")
    print("=" * 60)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="MP-1326 Paper Evidence Tracker v2 — CPA quality scoring"
    )
    parser.add_argument("--check", action="store_true", default=True,
                        help="Print report without saving (default)")
    parser.add_argument("--run", action="store_true",
                        help="Print report and save to disk")
    parser.add_argument("--data-dir", default=None,
                        help="Override data directory (default: data/paper)")
    args = parser.parse_args()

    path = DEFAULT_PATH
    if args.data_dir:
        path = os.path.join(args.data_dir.rstrip("/"), "evidence_v2.json")

    tracker = PaperEvidenceTrackerV2(path=path)
    report = tracker.evidence_report()
    _print_report(report)

    if args.run:
        tracker.save()
        print(f"\nSaved → {path}")

    sys.exit(0)


if __name__ == "__main__":
    main()
