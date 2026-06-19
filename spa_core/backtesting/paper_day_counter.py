"""
spa_core/backtesting/paper_day_counter.py

MP-1356 (v9.72) — Tracks paper trading day count and evidence accumulation progress.

Reads:
  data/paper/paper_state.json       — start_date, status
  data/paper/evidence_v2.json       — accumulated evidence points (PaperEvidenceTrackerV2)

All file reads are defensive: missing / malformed files → sensible defaults, no raise.

Evidence scoring (from PaperEvidenceTrackerV2 v2.0):
  - extreme market regime               → 1.5 pts/day
  - CLEAN sources, drift ≤ 2%           → 1.0 pts/day  (full evidence)
  - high drift (drift_pct > 2%)         → 0.5 pts/day
  - any non-CLEAN source present        → 0.3 pts/day (minimum)

  Required for live eligibility: 30.0 pts

Display example::

  Paper Trading Status
  ────────────────────
  Started:      2026-06-20
  Today:        2026-06-20
  Day:          1 / 30+ (minimum)

  Evidence Points
  ────────────────────
  Accumulated:  0.3 pts  (Day 1, 17% CLEAN sources)
  Required:     30.0 pts
  Progress:     1.0%
  ETA:          2026-07-28 (at current source mix)

  Milestones:
  ⏳ 5 pts  — Early confidence    (ETA: 2026-07-03)
  ⏳ 15 pts — Mid-point           (ETA: 2026-07-14)
  ✅ 30 pts — Live eligibility    (achieved: 2026-07-28)

Rules:
  - stdlib only, no external dependencies
  - read-only module — never writes state files
  - LLM_FORBIDDEN (pure deterministic)
"""

from __future__ import annotations

import json
import math
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional


# ── Constants ─────────────────────────────────────────────────────────────────

_DEFAULT_STATE_PATH    = "data/paper/paper_state.json"
_DEFAULT_EVIDENCE_PATH = "data/paper/evidence_v2.json"

# Evidence points needed before live trading is allowed
EVIDENCE_REQUIRED = 30.0

# Minimum calendar days for the paper track (informational, not enforced here)
MIN_DAYS = 30

# Default pts/day rate when no evidence data is available
# 17 % CLEAN → 0.17 * 1.0 pts/day (rest contribute 0)
_DEFAULT_PTS_PER_DAY = 0.17 * 1.0  # ≈ 0.17 pts/day


# ── Milestones ────────────────────────────────────────────────────────────────

class PaperDayCounter:
    """
    Tracks paper trading day count and evidence accumulation progress.

    Usage::

        counter = PaperDayCounter()

        if counter.not_started():
            print("Paper trading not yet started.")
        else:
            print(counter.render())

    Args:
        paper_state_path:  Path to data/paper/paper_state.json.
        evidence_path:     Path to data/paper/evidence_v2.json
                           (written by PaperEvidenceTrackerV2).
        today:             Override today's date (for testing); defaults to date.today().
    """

    EVIDENCE_REQUIRED = EVIDENCE_REQUIRED

    MILESTONES: List[tuple] = [
        (5.0,  "Early confidence"),
        (10.0, "Quarter way"),
        (15.0, "Mid-point"),
        (20.0, "Three-quarters"),
        (25.0, "Almost ready"),
        (30.0, "Live eligibility"),
    ]

    def __init__(
        self,
        paper_state_path: str = _DEFAULT_STATE_PATH,
        evidence_path: str = _DEFAULT_EVIDENCE_PATH,
        today: Optional[date] = None,
    ) -> None:
        self.paper_state_path = Path(paper_state_path)
        self.evidence_path = Path(evidence_path)
        self._today = today  # None → use real date.today()

    # ── Internal ──────────────────────────────────────────────────────────────

    def _today_date(self) -> date:
        return self._today if self._today is not None else date.today()

    def _read_json(self, path: Path) -> Optional[dict]:
        """Read JSON file. Returns None on any error."""
        try:
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, json.JSONDecodeError, ValueError):
            return None

    def _pts_per_day(self) -> float:
        """
        Compute the observed pts/day rate from evidence_v2.json.
        Falls back to _DEFAULT_PTS_PER_DAY if evidence data is unavailable.
        """
        data = self._read_json(self.evidence_path)
        if data is None:
            return _DEFAULT_PTS_PER_DAY
        days_list = data.get("days", [])
        if not days_list:
            # Try total_points / days_elapsed for a simple estimate
            total = float(data.get("total_points", 0.0))
            elapsed = max(self.days_elapsed(), 1)
            if total > 0.0:
                return total / elapsed
            return _DEFAULT_PTS_PER_DAY
        # Compute from the recorded days
        total_pts = sum(float(d.get("score", 0.0)) for d in days_list)
        n = len(days_list)
        return total_pts / n if n > 0 else _DEFAULT_PTS_PER_DAY

    # ── Public API ────────────────────────────────────────────────────────────

    def load_state(self) -> Optional[dict]:
        """Return paper_state dict or None if not started / unreadable."""
        return self._read_json(self.paper_state_path)

    def not_started(self) -> bool:
        """True if paper trading hasn't started yet (paper_state.json absent/invalid)."""
        state = self.load_state()
        if state is None:
            return True
        # If the status field explicitly says "not_started"
        if state.get("status") == "not_started":
            return True
        # Must have a start_date to be considered started
        return not bool(state.get("start_date"))

    def days_elapsed(self) -> int:
        """
        Calendar days since paper trading started (inclusive of start day = day 1).
        Returns 0 if not started.
        """
        state = self.load_state()
        if state is None:
            return 0
        start_raw = state.get("start_date")
        if not start_raw:
            return 0
        try:
            start = date.fromisoformat(str(start_raw))
        except ValueError:
            return 0
        delta = (self._today_date() - start).days
        # day 1 on start_date → delta 0 → 1; day 0 if it hasn't started
        return max(delta + 1, 0)

    def evidence_accumulated(self) -> float:
        """
        Evidence points accumulated so far.

        Reads from data/paper/evidence_v2.json (``total_points`` field) if available.
        Falls back to 0.0 if the file doesn't exist or is malformed.
        """
        data = self._read_json(self.evidence_path)
        if data is None:
            return 0.0
        # PaperEvidenceTrackerV2 stores total in "total_points"
        val = data.get("total_points", 0.0)
        try:
            return float(val)
        except (TypeError, ValueError):
            return 0.0

    def evidence_progress_pct(self) -> float:
        """
        Percentage of required evidence accumulated.
        Returns a value in [0.0, 100.0].
        """
        accumulated = self.evidence_accumulated()
        pct = (accumulated / self.EVIDENCE_REQUIRED) * 100.0
        return min(max(pct, 0.0), 100.0)

    def eta_live(self, clean_pct: float = 0.17) -> Optional[str]:
        """
        Estimate the ISO date when 30 evidence points will be reached.

        Args:
            clean_pct: Fraction of days that produce CLEAN evidence (1.0 pts/day).
                       Ignored if observed pts/day rate is available from evidence data.

        Returns:
            ISO date string (YYYY-MM-DD) or None if not started.
        """
        if self.not_started():
            return None

        accumulated = self.evidence_accumulated()
        remaining = self.EVIDENCE_REQUIRED - accumulated
        if remaining <= 0.0:
            # Already reached — return today
            return self._today_date().isoformat()

        rate = self._pts_per_day()
        if rate <= 0.0:
            # Use clean_pct as fallback
            rate = clean_pct * 1.0
        if rate <= 0.0:
            return None

        days_needed = math.ceil(remaining / rate)
        eta = self._today_date() + timedelta(days=days_needed)
        return eta.isoformat()

    def milestones_status(self) -> List[dict]:
        """
        Return a list of 6 milestone dicts, one per MILESTONES entry.

        Each dict:
            pts        float
            label      str
            achieved   bool
            eta_date   str | None  (ISO date, None if not started)
        """
        accumulated = self.evidence_accumulated()
        today = self._today_date()
        rate = self._pts_per_day() if not self.not_started() else _DEFAULT_PTS_PER_DAY
        result = []

        for pts, label in self.MILESTONES:
            achieved = accumulated >= pts
            if achieved:
                eta_date = None  # already done
            elif self.not_started():
                eta_date = None
            else:
                remaining = pts - accumulated
                if rate > 0.0:
                    days_needed = math.ceil(remaining / rate)
                    eta_date = (today + timedelta(days=days_needed)).isoformat()
                else:
                    eta_date = None

            result.append(
                {
                    "pts": pts,
                    "label": label,
                    "achieved": achieved,
                    "eta_date": eta_date,
                }
            )
        return result

    def render(self) -> str:
        """Human-readable status display string."""
        today_str = self._today_date().isoformat()
        state = self.load_state()

        lines: List[str] = []
        lines.append("Paper Trading Status")
        lines.append("────────────────────")

        if self.not_started():
            lines.append("Status:       Not started")
            lines.append("")
            lines.append("Evidence Points")
            lines.append("────────────────────")
            lines.append(f"Accumulated:  0.0 pts")
            lines.append(f"Required:     {self.EVIDENCE_REQUIRED:.1f} pts")
            lines.append(f"Progress:     0.0%")
            lines.append(f"ETA:          N/A (not started)")
            return "\n".join(lines)

        start_date = state.get("start_date", "?") if state else "?"  # type: ignore[union-attr]
        elapsed = self.days_elapsed()
        accumulated = self.evidence_accumulated()
        progress = self.evidence_progress_pct()
        eta = self.eta_live()
        rate = self._pts_per_day()
        # Clean percentage approximation from rate
        clean_approx_pct = int(round(rate * 100))

        lines.append(f"Started:      {start_date}")
        lines.append(f"Today:        {today_str}")
        lines.append(f"Day:          {elapsed} / {MIN_DAYS}+ (minimum)")
        lines.append("")
        lines.append("Evidence Points")
        lines.append("────────────────────")
        lines.append(
            f"Accumulated:  {accumulated:.1f} pts  "
            f"(Day {elapsed}, ~{clean_approx_pct}% CLEAN sources)"
        )
        lines.append(f"Required:     {self.EVIDENCE_REQUIRED:.1f} pts")
        lines.append(f"Progress:     {progress:.1f}%")
        eta_note = eta if eta else "N/A"
        lines.append(f"ETA:          {eta_note} (at current source mix)")
        lines.append("")
        lines.append("Milestones:")
        for m in self.milestones_status():
            if m["achieved"]:
                icon = "✅"
                date_note = ""
            else:
                icon = "⏳"
                date_note = f"  (ETA: {m['eta_date']})" if m["eta_date"] else ""
            lines.append(
                f"  {icon} {m['pts']:.0f} pts  — {m['label']}{date_note}"
            )

        return "\n".join(lines)

    def to_dict(self) -> dict:
        """JSON-serializable summary of the current paper trading progress."""
        state = self.load_state()
        return {
            "not_started": self.not_started(),
            "start_date": state.get("start_date") if state else None,
            "today": self._today_date().isoformat(),
            "days_elapsed": self.days_elapsed(),
            "min_days_required": MIN_DAYS,
            "evidence_accumulated": self.evidence_accumulated(),
            "evidence_required": self.EVIDENCE_REQUIRED,
            "evidence_progress_pct": self.evidence_progress_pct(),
            "eta_live": self.eta_live(),
            "milestones": self.milestones_status(),
        }


# ── CLI ───────────────────────────────────────────────────────────────────────

def _main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="MP-1356: Paper Day Counter — show paper trading progress",
    )
    parser.add_argument(
        "--state", default=_DEFAULT_STATE_PATH,
        help=f"Path to paper_state.json (default: {_DEFAULT_STATE_PATH})",
    )
    parser.add_argument(
        "--evidence", default=_DEFAULT_EVIDENCE_PATH,
        help=f"Path to evidence_v2.json (default: {_DEFAULT_EVIDENCE_PATH})",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output JSON instead of human-readable display",
    )
    args = parser.parse_args(argv)

    counter = PaperDayCounter(
        paper_state_path=args.state,
        evidence_path=args.evidence,
    )

    if args.json:
        import json as _json
        print(_json.dumps(counter.to_dict(), indent=2))
    else:
        print(counter.render())

    return 0


if __name__ == "__main__":
    sys.exit(_main())
