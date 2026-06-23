"""
spa_core/analytics/evidence_auto_calculator.py

MP-1409 (v10.25): Automatically calculates and accumulates paper trading
evidence points.

Evidence Point System (30 pts total needed):
  Daily Cycles (15 pts max):
    - 1 pt per completed daily cycle (max 15 cycles = 15 pts)
  APY Tracking (8 pts max):
    - 1 pt per day T1 APY data is verified (max 8 days)
    - Bonus: +2 pts if APY verified for 7 consecutive days
  Risk Policy (7 pts max):
    - 1 pt per day risk policy checks pass (max 7 days counted)
    - Bonus: +3 pts if 0 policy violations for 14 consecutive days

Target: 30 pts = eligible for Pre-Paper review

Output: data/paper_evidence_history.json
Atomic writes: tmp + os.replace, stdlib only, LLM FORBIDDEN.

CLI:
    python3 -m spa_core.analytics.evidence_auto_calculator --check
    python3 -m spa_core.analytics.evidence_auto_calculator --run
"""

from __future__ import annotations

import datetime
import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import List, Optional

from spa_core.base import BaseAnalytics

# ─── Constants ────────────────────────────────────────────────────────────────

SCHEMA_VERSION = "1.0"
DEFAULT_DATA_FILE = "data/paper_evidence_history.json"

# Point caps
MAX_CYCLE_PTS = 15
MAX_APY_PTS = 8
MAX_RISK_PTS = 7

# Bonus thresholds
APY_STREAK_THRESHOLD = 7    # consecutive days → +2 bonus pts
APY_STREAK_BONUS = 2
RISK_STREAK_THRESHOLD = 14  # consecutive days → +3 bonus pts
RISK_STREAK_BONUS = 3

TARGET_PTS = 30


# ─── Dataclasses ──────────────────────────────────────────────────────────────

@dataclass
class EvidenceDay:
    """A single paper trading day's evidence record."""
    date: str
    cycle_completed: bool = False
    apy_verified: bool = False
    risk_policy_passed: bool = False
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "date": self.date,
            "cycle_completed": self.cycle_completed,
            "apy_verified": self.apy_verified,
            "risk_policy_passed": self.risk_policy_passed,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "EvidenceDay":
        return cls(
            date=d.get("date", ""),
            cycle_completed=bool(d.get("cycle_completed", False)),
            apy_verified=bool(d.get("apy_verified", False)),
            risk_policy_passed=bool(d.get("risk_policy_passed", False)),
            notes=str(d.get("notes", "")),
        )


@dataclass
class EvidenceScore:
    """Calculated evidence score snapshot."""
    daily_cycles_pts: int = 0
    apy_tracking_pts: int = 0
    risk_policy_pts: int = 0
    bonus_pts: int = 0
    total: int = 0
    target: int = TARGET_PTS
    is_eligible: bool = False
    days_history: List[EvidenceDay] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "daily_cycles_pts": self.daily_cycles_pts,
            "apy_tracking_pts": self.apy_tracking_pts,
            "risk_policy_pts": self.risk_policy_pts,
            "bonus_pts": self.bonus_pts,
            "total": self.total,
            "target": self.target,
            "is_eligible": self.is_eligible,
            "days_count": len(self.days_history),
        }


# ─── EvidenceAutoCalculator ───────────────────────────────────────────────────

class EvidenceAutoCalculator(BaseAnalytics):
    """
    Accumulates and scores paper trading evidence.

    Thread-safety: single-process only (launchd serial context).
    Atomic saves via mkstemp + os.replace.
    """

    OUTPUT_PATH = "data/paper_evidence_history.json"

    TARGET_PTS = TARGET_PTS
    MAX_CYCLE_PTS = MAX_CYCLE_PTS
    MAX_APY_PTS = MAX_APY_PTS
    MAX_RISK_PTS = MAX_RISK_PTS

    def __init__(self, base_dir: str = ".") -> None:
        super().__init__(base_dir)
        self._base_dir = Path(base_dir)
        self._data_file = self._base_dir / DEFAULT_DATA_FILE
        self._history: List[EvidenceDay] = []

    def to_dict(self) -> dict:
        """Returns evidence history as JSON-serializable dict."""
        return {
            "schema_version": SCHEMA_VERSION,
            "days_count": len(self._history),
            "history": [d.to_dict() for d in self._history],
        }

    # ── Public API ────────────────────────────────────────────────────────────

    def record_day(
        self,
        date: str,
        cycle_completed: bool,
        apy_verified: bool,
        risk_policy_passed: bool,
        notes: str = "",
    ) -> EvidenceDay:
        """
        Record a paper trading day's results.

        Deduplicates by date — if date already exists, updates in-place.
        Returns the recorded EvidenceDay.
        """
        # Update existing entry if present
        for i, day in enumerate(self._history):
            if day.date == date:
                self._history[i] = EvidenceDay(
                    date=date,
                    cycle_completed=cycle_completed,
                    apy_verified=apy_verified,
                    risk_policy_passed=risk_policy_passed,
                    notes=notes,
                )
                return self._history[i]

        new_day = EvidenceDay(
            date=date,
            cycle_completed=cycle_completed,
            apy_verified=apy_verified,
            risk_policy_passed=risk_policy_passed,
            notes=notes,
        )
        self._history.append(new_day)
        # Keep sorted by date
        self._history.sort(key=lambda d: d.date)
        return new_day

    def calculate_score(self) -> EvidenceScore:
        """
        Calculate current evidence score from history.

        Applies streak bonuses on top of base category caps.
        Total = min(cycles, 15) + min(apy_base, 8) + min(risk_base, 7)
                + apy_bonus + risk_bonus
        """
        # Base category points (capped)
        cycles_base = sum(1 for d in self._history if d.cycle_completed)
        apy_base = sum(1 for d in self._history if d.apy_verified)
        risk_base = sum(1 for d in self._history if d.risk_policy_passed)

        cycles_pts = min(cycles_base, self.MAX_CYCLE_PTS)
        apy_pts = min(apy_base, self.MAX_APY_PTS)
        risk_pts = min(risk_base, self.MAX_RISK_PTS)

        # Streak bonuses
        bonus_pts = 0
        apy_streak = self._apy_streak()
        if apy_streak >= APY_STREAK_THRESHOLD:
            bonus_pts += APY_STREAK_BONUS

        risk_streak = self._risk_streak()
        if risk_streak >= RISK_STREAK_THRESHOLD:
            bonus_pts += RISK_STREAK_BONUS

        total = cycles_pts + apy_pts + risk_pts + bonus_pts

        return EvidenceScore(
            daily_cycles_pts=cycles_pts,
            apy_tracking_pts=apy_pts,
            risk_policy_pts=risk_pts,
            bonus_pts=bonus_pts,
            total=total,
            target=self.TARGET_PTS,
            is_eligible=(total >= self.TARGET_PTS),
            days_history=list(self._history),
        )

    def _apy_streak(self) -> int:
        """Return count of consecutive days (most recent) where APY was verified."""
        streak = 0
        for day in reversed(self._history):
            if day.apy_verified:
                streak += 1
            else:
                break
        return streak

    def _risk_streak(self) -> int:
        """Return count of consecutive days (most recent) where risk policy passed."""
        streak = 0
        for day in reversed(self._history):
            if day.risk_policy_passed:
                streak += 1
            else:
                break
        return streak

    def days_to_target(self, score: EvidenceScore) -> int:
        """
        Estimate days needed to reach 30 pts at current pace.

        Pessimistic: assumes 1 pt/day for remaining gap.
        Returns 0 if already eligible.
        """
        if score.is_eligible:
            return 0
        gap = score.target - score.total
        # gap is always >= 1 here
        return max(1, gap)

    def save(self) -> None:
        """Atomically save history to data/paper_evidence_history.json."""
        # Ensure parent directory exists
        self._data_file.parent.mkdir(parents=True, exist_ok=True)

        _days = [d.to_dict() for d in self._history]
        payload = {
            "schema_version": SCHEMA_VERSION,
            "saved_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "days_count": len(self._history),
            # Canonical key consumed by golive_readiness_report / tests is "days".
            # "history" retained for backward-compatibility with older readers.
            "days": _days,
            "history": _days,
        }

        from spa_core.utils.atomic import atomic_save
        atomic_save(payload, str(self._data_file))

    def load(self) -> None:
        """Load history from data/paper_evidence_history.json (silent if missing)."""
        if not self._data_file.exists():
            self._history = []
            return
        try:
            with open(self._data_file, encoding="utf-8") as fh:
                data = json.load(fh)
            raw_list = data.get("days") or data.get("history", [])
            self._history = [EvidenceDay.from_dict(d) for d in raw_list]
            # Keep sorted by date
            self._history.sort(key=lambda d: d.date)
        except Exception:  # noqa: BLE001
            # Corrupt file → start fresh (never crash the cycle)
            self._history = []

    def to_markdown(self, score: EvidenceScore) -> str:
        """Return a human-readable Markdown evidence report."""
        lines = [
            "# Evidence Score Report",
            "",
            f"**Total: {score.total} / {score.target} pts**  "
            f"{'✓ ELIGIBLE' if score.is_eligible else '✗ Not yet eligible'}",
            "",
            "## Breakdown",
            "",
            f"| Category        | Points | Cap |",
            f"|:----------------|-------:|----:|",
            f"| Daily Cycles    | {score.daily_cycles_pts:>6} | {self.MAX_CYCLE_PTS:>3} |",
            f"| APY Tracking    | {score.apy_tracking_pts:>6} | {self.MAX_APY_PTS:>3} |",
            f"| Risk Policy     | {score.risk_policy_pts:>6} | {self.MAX_RISK_PTS:>3} |",
            f"| Bonus           | {score.bonus_pts:>6} |   — |",
            f"| **Total**       | **{score.total:>4}** | **{score.target}** |",
            "",
        ]

        days_to_go = self.days_to_target(score)
        if score.is_eligible:
            lines.append("**Status:** Ready for Pre-Paper review.")
        else:
            lines.append(f"**Days to target (pessimistic):** {days_to_go}")

        apy_s = self._apy_streak()
        risk_s = self._risk_streak()
        lines += [
            "",
            "## Streaks",
            "",
            f"- APY verified streak: **{apy_s}** day(s)"
            f" (bonus at {APY_STREAK_THRESHOLD}+: +{APY_STREAK_BONUS} pts)",
            f"- Risk policy streak : **{risk_s}** day(s)"
            f" (bonus at {RISK_STREAK_THRESHOLD}+: +{RISK_STREAK_BONUS} pts)",
            "",
            f"## History ({len(self._history)} day(s))",
            "",
            "| Date       | Cycle | APY | Risk |",
            "|:-----------|:-----:|:---:|:----:|",
        ]
        for d in self._history[-10:]:  # last 10 rows
            lines.append(
                f"| {d.date} "
                f"| {'✓' if d.cycle_completed else '✗'} "
                f"| {'✓' if d.apy_verified else '✗'} "
                f"| {'✓' if d.risk_policy_passed else '✗'} |"
            )
        return "\n".join(lines)


# ─── CLI ──────────────────────────────────────────────────────────────────────

def _usage() -> None:
    print(
        "Usage:\n"
        "  python3 -m spa_core.analytics.evidence_auto_calculator --check\n"
        "  python3 -m spa_core.analytics.evidence_auto_calculator --run\n"
        "  python3 -m spa_core.analytics.evidence_auto_calculator --run --data-dir <dir>\n"
        "\n"
        "  --check  Compute and print score; no writes.\n"
        "  --run    Compute, print, and write data/paper_evidence_history.json.\n"
    )


def main() -> None:  # pragma: no cover
    args = sys.argv[1:]
    if not args:
        _usage()
        sys.exit(0)

    write = "--run" in args
    data_dir_idx = args.index("--data-dir") if "--data-dir" in args else -1
    base_dir = args[data_dir_idx + 1] if data_dir_idx >= 0 else "."

    calc = EvidenceAutoCalculator(base_dir=base_dir)
    calc.load()
    score = calc.calculate_score()
    print(calc.to_markdown(score))

    if write:
        calc.save()
        print(f"\n✓ Saved → {calc._data_file}")

    sys.exit(0)


if __name__ == "__main__":
    main()
