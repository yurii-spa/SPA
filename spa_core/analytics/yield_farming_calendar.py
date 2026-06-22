"""
MP-725: YieldFarmingCalendar
Tracks reward emission schedules, cliff dates, vesting unlocks, and program
end dates across DeFi yield farming positions to prevent unexpected yield drops.

Advisory/read-only — never modifies allocator, risk, or execution.
Pure stdlib — zero external dependencies.
Atomic writes: tmp + os.replace.
Ring-buffer cap: 100 entries.
"""

from dataclasses import dataclass, field
from typing import List, Optional
import datetime
import json
import os
import time
from pathlib import Path

DATA_FILE = Path("data/farming_calendar_log.json")
MAX_ENTRIES = 100

# Impact level ordering for comparison
_IMPACT_ORDER = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1, "NONE": 0}


# ---------------------------------------------------------------------------
# Core dataclasses
# ---------------------------------------------------------------------------

@dataclass
class CalendarEvent:
    event_type: str       # "EMISSION_END" | "CLIFF_UNLOCK" | "REWARD_BOOST_EXPIRY" | "LOCK_EXPIRY" | "VESTING_COMPLETE"
    protocol: str
    pool: str
    event_date_iso: str   # ISO date YYYY-MM-DD
    days_until: int       # from today
    impact: str           # "CRITICAL" | "HIGH" | "MEDIUM" | "LOW"
    description: str
    apy_impact_pct: float # estimated APY change when event occurs (negative = APY drops)


@dataclass
class FarmingSchedule:
    protocol: str
    pool: str
    current_apy: float
    emission_start_iso: str
    emission_end_iso: str       # or "" if ongoing
    reward_token: str
    boost_multiplier: float     # current boost (1.0 = no boost)
    boost_expiry_iso: str       # or "" if no boost
    lock_expiry_iso: str        # or "" if no lock
    vesting_end_iso: str        # or "" if no vesting


@dataclass
class CalendarReport:
    schedules: List[FarmingSchedule]
    today_iso: str

    events: List[CalendarEvent]          # all upcoming events sorted by days_until

    # Urgent events
    events_within_7d: List[CalendarEvent]
    events_within_30d: List[CalendarEvent]

    # Summary
    total_at_risk_apy: float    # sum of |apy_impact_pct| for events within 30d
    highest_urgency: str        # "CRITICAL" | "HIGH" | "MEDIUM" | "LOW" | "NONE"

    recommendations: List[str]
    saved_to: str = ""


# ---------------------------------------------------------------------------
# Calendar analyser
# ---------------------------------------------------------------------------

class YieldFarmingCalendar:
    """
    Track reward emission schedules, cliff dates, vesting unlocks, and program
    end dates across DeFi yield farming positions.

    All computations are advisory.  The module never writes to allocator, risk,
    or execution state.
    """

    def __init__(self, data_file: Path = DATA_FILE):
        self.data_file = data_file

    # ------------------------------------------------------------------
    # Pure helpers
    # ------------------------------------------------------------------

    def days_between(self, date_a_iso: str, date_b_iso: str) -> int:
        """
        Parse two YYYY-MM-DD strings and return (b - a).days as int.
        """
        fmt = "%Y-%m-%d"
        a = datetime.datetime.strptime(date_a_iso, fmt).date()
        b = datetime.datetime.strptime(date_b_iso, fmt).date()
        return (b - a).days

    def classify_impact(self, days_until: int, apy_impact_pct: float) -> str:
        """
        Classify urgency based solely on days_until (apy_impact_pct is informational).

        CRITICAL ≤ 3 days
        HIGH     ≤ 14 days
        MEDIUM   ≤ 30 days
        LOW      > 30 days
        """
        if days_until <= 3:
            return "CRITICAL"
        if days_until <= 14:
            return "HIGH"
        if days_until <= 30:
            return "MEDIUM"
        return "LOW"

    # ------------------------------------------------------------------
    # Event builders
    # ------------------------------------------------------------------

    def build_events(self, schedule: FarmingSchedule, today_iso: str) -> List[CalendarEvent]:
        """
        Build all upcoming CalendarEvents for a single FarmingSchedule.
        Only includes events where days_until >= 0 (today or future).
        """
        events: List[CalendarEvent] = []

        # 1. EMISSION_END
        if schedule.emission_end_iso:
            days = self.days_between(today_iso, schedule.emission_end_iso)
            if days >= 0:
                apy_impact = -schedule.current_apy * 0.7
                impact = self.classify_impact(days, apy_impact)
                events.append(CalendarEvent(
                    event_type="EMISSION_END",
                    protocol=schedule.protocol,
                    pool=schedule.pool,
                    event_date_iso=schedule.emission_end_iso,
                    days_until=days,
                    impact=impact,
                    description=(
                        f"{schedule.protocol}/{schedule.pool} reward emissions end "
                        f"({schedule.reward_token}); est. APY impact: "
                        f"{apy_impact:+.2f}%"
                    ),
                    apy_impact_pct=round(apy_impact, 6),
                ))

        # 2. REWARD_BOOST_EXPIRY
        if schedule.boost_expiry_iso:
            days = self.days_between(today_iso, schedule.boost_expiry_iso)
            if days >= 0:
                boost = max(schedule.boost_multiplier, 1.0)
                apy_impact = -schedule.current_apy * (1.0 - 1.0 / boost)
                impact = self.classify_impact(days, apy_impact)
                events.append(CalendarEvent(
                    event_type="REWARD_BOOST_EXPIRY",
                    protocol=schedule.protocol,
                    pool=schedule.pool,
                    event_date_iso=schedule.boost_expiry_iso,
                    days_until=days,
                    impact=impact,
                    description=(
                        f"{schedule.protocol}/{schedule.pool} boost x{boost:.2f} expires; "
                        f"est. APY impact: {apy_impact:+.2f}%"
                    ),
                    apy_impact_pct=round(apy_impact, 6),
                ))

        # 3. LOCK_EXPIRY
        if schedule.lock_expiry_iso:
            days = self.days_between(today_iso, schedule.lock_expiry_iso)
            if days >= 0:
                apy_impact = 0.0
                events.append(CalendarEvent(
                    event_type="LOCK_EXPIRY",
                    protocol=schedule.protocol,
                    pool=schedule.pool,
                    event_date_iso=schedule.lock_expiry_iso,
                    days_until=days,
                    impact="LOW",
                    description=(
                        f"{schedule.protocol}/{schedule.pool} lock period expires; "
                        f"liquidity becomes withdrawable"
                    ),
                    apy_impact_pct=0.0,
                ))

        # 4. VESTING_COMPLETE
        if schedule.vesting_end_iso:
            days = self.days_between(today_iso, schedule.vesting_end_iso)
            if days >= 0:
                apy_impact = schedule.current_apy * 0.1
                impact = self.classify_impact(days, apy_impact)
                events.append(CalendarEvent(
                    event_type="VESTING_COMPLETE",
                    protocol=schedule.protocol,
                    pool=schedule.pool,
                    event_date_iso=schedule.vesting_end_iso,
                    days_until=days,
                    impact=impact,
                    description=(
                        f"{schedule.protocol}/{schedule.pool} vesting complete; "
                        f"est. APY pickup: {apy_impact:+.2f}%"
                    ),
                    apy_impact_pct=round(apy_impact, 6),
                ))

        return events

    # ------------------------------------------------------------------
    # Main analysis
    # ------------------------------------------------------------------

    def analyze(
        self,
        schedules: List[FarmingSchedule],
        today_iso: str,
    ) -> CalendarReport:
        """Compute a CalendarReport from a list of FarmingSchedule objects."""
        all_events: List[CalendarEvent] = []
        for s in schedules:
            all_events.extend(self.build_events(s, today_iso))

        # Sort by days_until ascending
        all_events.sort(key=lambda e: e.days_until)

        events_within_7d = [e for e in all_events if e.days_until <= 7]
        events_within_30d = [e for e in all_events if e.days_until <= 30]

        total_at_risk_apy = round(
            sum(abs(e.apy_impact_pct) for e in events_within_30d), 6
        )

        # Highest urgency across ALL events
        if not all_events:
            highest_urgency = "NONE"
        else:
            urgency_values = [_IMPACT_ORDER.get(e.impact, 0) for e in all_events]
            max_val = max(urgency_values)
            highest_urgency = next(
                k for k, v in _IMPACT_ORDER.items() if v == max_val
            )

        recommendations = self._recommendations(
            all_events, events_within_7d, total_at_risk_apy
        )

        return CalendarReport(
            schedules=schedules,
            today_iso=today_iso,
            events=all_events,
            events_within_7d=events_within_7d,
            events_within_30d=events_within_30d,
            total_at_risk_apy=total_at_risk_apy,
            highest_urgency=highest_urgency,
            recommendations=recommendations,
            saved_to="",
        )

    def _recommendations(
        self,
        all_events: List[CalendarEvent],
        events_within_7d: List[CalendarEvent],
        total_at_risk_apy: float,
    ) -> List[str]:
        recs: List[str] = []
        has_critical = any(e.impact == "CRITICAL" for e in all_events)
        if has_critical:
            recs.append("Review CRITICAL events immediately")
        if total_at_risk_apy > 5.0:
            recs.append("Significant APY risk within 30 days")
        if events_within_7d:
            recs.append("Consider repositioning before upcoming events")
        return recs

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def next_event(self, report: CalendarReport) -> Optional[CalendarEvent]:
        """Return the CalendarEvent with the smallest days_until, or None."""
        if not report.events:
            return None
        return report.events[0]  # already sorted ascending

    # ------------------------------------------------------------------
    # Persistence (ring-buffer, atomic write)
    # ------------------------------------------------------------------

    def _report_to_dict(self, report: CalendarReport) -> dict:
        def event_to_dict(e: CalendarEvent) -> dict:
            return {
                "event_type": e.event_type,
                "protocol": e.protocol,
                "pool": e.pool,
                "event_date_iso": e.event_date_iso,
                "days_until": e.days_until,
                "impact": e.impact,
                "description": e.description,
                "apy_impact_pct": e.apy_impact_pct,
            }

        return {
            "timestamp": time.time(),
            "today_iso": report.today_iso,
            "num_schedules": len(report.schedules),
            "num_events": len(report.events),
            "events_within_7d": len(report.events_within_7d),
            "events_within_30d": len(report.events_within_30d),
            "total_at_risk_apy": report.total_at_risk_apy,
            "highest_urgency": report.highest_urgency,
            "recommendations": report.recommendations,
            "events": [event_to_dict(e) for e in report.events],
        }

    def save_results(self, report: CalendarReport) -> str:
        """
        Append report summary to the ring-buffer JSON log (max MAX_ENTRIES).
        Uses atomic write: tmp + os.replace.
        Returns the path of the data file as a string.
        """
        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            existing = json.loads(self.data_file.read_text())
            if not isinstance(existing, list):
                existing = []
        except Exception:
            existing = []
        existing.append(self._report_to_dict(report))
        existing = existing[-MAX_ENTRIES:]
        tmp = self.data_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(existing, indent=2))
        os.replace(tmp, self.data_file)
        report.saved_to = str(self.data_file)
        return str(self.data_file)

    def load_history(self) -> list:
        """Load saved ring-buffer log; returns [] on any error."""
        try:
            data = json.loads(self.data_file.read_text())
            return data if isinstance(data, list) else []
        except Exception:
            return []


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------

def _today_iso() -> str:
    return datetime.date.today().isoformat()


def _demo_schedules() -> List[FarmingSchedule]:
    today = _today_iso()
    # compute dates relative to today for demo reproducibility
    fmt = "%Y-%m-%d"
    today_dt = datetime.datetime.strptime(today, fmt).date()

    def offset(days: int) -> str:
        return (today_dt + datetime.timedelta(days=days)).isoformat()

    return [
        FarmingSchedule(
            protocol="Aave",
            pool="USDC",
            current_apy=5.0,
            emission_start_iso=offset(-30),
            emission_end_iso=offset(10),    # ends in 10 days
            reward_token="stkAAVE",
            boost_multiplier=2.5,
            boost_expiry_iso=offset(5),     # boost expires in 5 days
            lock_expiry_iso="",
            vesting_end_iso=offset(60),
        ),
        FarmingSchedule(
            protocol="Compound",
            pool="USDC",
            current_apy=4.0,
            emission_start_iso=offset(-60),
            emission_end_iso="",            # ongoing
            reward_token="COMP",
            boost_multiplier=1.0,
            boost_expiry_iso="",
            lock_expiry_iso=offset(2),      # lock expires in 2 days (CRITICAL)
            vesting_end_iso="",
        ),
    ]


def _print_report(report: CalendarReport) -> None:
    print(f"\n{'='*60}")
    print("  YieldFarmingCalendar — MP-725")
    print(f"  Date: {report.today_iso}  Schedules: {len(report.schedules)}")
    print(f"{'='*60}")
    print(f"  Total events      : {len(report.events)}")
    print(f"  Within 7 days     : {len(report.events_within_7d)}")
    print(f"  Within 30 days    : {len(report.events_within_30d)}")
    print(f"  Total at-risk APY : {report.total_at_risk_apy:.2f}%")
    print(f"  Highest urgency   : {report.highest_urgency}")
    if report.recommendations:
        print("\n  Recommendations:")
        for r in report.recommendations:
            print(f"    ➜ {r}")
    if report.events:
        print("\n  Upcoming events:")
        for e in report.events[:10]:
            print(f"    [{e.impact:8s}] D+{e.days_until:3d}  {e.event_type}  "
                  f"{e.protocol}/{e.pool}  APY Δ{e.apy_impact_pct:+.2f}%")
    if report.saved_to:
        print(f"\n  saved_to: {report.saved_to}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    import sys
    run_mode = "--run" in sys.argv

    calendar = YieldFarmingCalendar()
    schedules = _demo_schedules()
    today = _today_iso()
    report = calendar.analyze(schedules, today)

    if run_mode:
        calendar.save_results(report)

    _print_report(report)
    sys.exit(0)
