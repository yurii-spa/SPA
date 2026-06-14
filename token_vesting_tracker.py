"""
MP-676: TokenVestingTracker
Track token vesting schedules and predict sell pressure from upcoming unlocks.
Pure stdlib only. Advisory/read-only. Atomic writes.
"""

from dataclasses import dataclass, field
from typing import List, Optional
import json
import time
import os
from pathlib import Path

DATA_FILE = Path("data/vesting_tracker_log.json")
MAX_ENTRIES = 100


@dataclass
class VestingSchedule:
    beneficiary_id: str
    beneficiary_type: str       # "TEAM", "INVESTOR", "ADVISOR", "COMMUNITY", "ECOSYSTEM"
    total_tokens: float
    tokens_unlocked: float      # already vested and released
    cliff_days: int             # days before any tokens unlock
    vest_start_timestamp: float # unix timestamp when vesting started
    vest_duration_days: int     # total vesting duration
    current_timestamp: float    # now (injected for testing)


@dataclass
class VestingStatus:
    beneficiary_id: str
    beneficiary_type: str
    tokens_unlocked: float
    tokens_locked: float
    unlock_pct: float               # 0–100
    days_until_next_cliff: int      # 0 if cliff already passed
    days_until_full_vest: int       # 0 if fully vested
    monthly_unlock_rate: float      # tokens unlocked per month going forward
    sell_pressure: str              # LOW / MEDIUM / HIGH / CRITICAL
    is_fully_vested: bool


class TokenVestingTracker:
    """
    Tracks token vesting schedules and predicts sell pressure from upcoming unlocks.
    Advisory only — never modifies allocator, risk, or execution domains.
    """

    # ------------------------------------------------------------------
    # Core calculation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _elapsed_days(schedule: VestingSchedule) -> float:
        """Days elapsed since vesting started."""
        return (schedule.current_timestamp - schedule.vest_start_timestamp) / 86400.0

    @staticmethod
    def _unlockable(schedule: VestingSchedule) -> float:
        """
        Tokens that should be unlocked by now under a linear vesting model.
        - Before cliff: 0.0
        - After full vest: total_tokens
        - Otherwise: proportional linear unlock
        """
        elapsed = (schedule.current_timestamp - schedule.vest_start_timestamp) / 86400.0
        if elapsed < schedule.cliff_days:
            return 0.0
        if elapsed >= schedule.vest_duration_days:
            return schedule.total_tokens
        return schedule.total_tokens * (elapsed / schedule.vest_duration_days)

    @staticmethod
    def _days_until_full_vest(schedule: VestingSchedule) -> int:
        """0 if fully vested; otherwise days remaining."""
        elapsed = (schedule.current_timestamp - schedule.vest_start_timestamp) / 86400.0
        remaining = schedule.vest_duration_days - elapsed
        return max(0, int(remaining))

    @staticmethod
    def _monthly_unlock_rate(schedule: VestingSchedule) -> float:
        """
        Tokens unlocked per month going forward.
        0.0 if fully vested (nothing left to unlock).
        """
        elapsed = (schedule.current_timestamp - schedule.vest_start_timestamp) / 86400.0
        if elapsed >= schedule.vest_duration_days:
            return 0.0
        return schedule.total_tokens / schedule.vest_duration_days * 30.0

    @staticmethod
    def _sell_pressure(
        beneficiary_type: str,
        unlock_pct: float,
        monthly_rate: float,
        total: float,
    ) -> str:
        """
        Classify sell pressure.

        ratio = monthly_rate / total  (fraction of total unlocking each month)

        CRITICAL : ratio > 0.10 AND type in {TEAM, INVESTOR}
        HIGH     : ratio > 0.05 OR (type==TEAM AND unlock_pct>50)
        MEDIUM   : ratio > 0.02
        LOW      : otherwise
        """
        ratio = monthly_rate / total if total > 0 else 0.0
        high_pressure_types = {"TEAM", "INVESTOR"}

        if ratio > 0.10 and beneficiary_type in high_pressure_types:
            return "CRITICAL"
        if ratio > 0.05 or (beneficiary_type == "TEAM" and unlock_pct > 50):
            return "HIGH"
        if ratio > 0.02:
            return "MEDIUM"
        return "LOW"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_status(self, schedule: VestingSchedule) -> VestingStatus:
        """Compute full VestingStatus for a single schedule."""
        elapsed = self._elapsed_days(schedule)
        unlockable = self._unlockable(schedule)
        is_fully_vested = elapsed >= schedule.vest_duration_days
        tokens_locked = max(0.0, schedule.total_tokens - unlockable)
        unlock_pct = (unlockable / schedule.total_tokens * 100.0) if schedule.total_tokens > 0 else 0.0

        # Days until next cliff (0 if cliff already passed)
        if elapsed >= schedule.cliff_days:
            days_until_next_cliff = 0
        else:
            days_until_next_cliff = max(0, int(schedule.cliff_days - elapsed))

        days_until_full = self._days_until_full_vest(schedule)
        monthly_rate = self._monthly_unlock_rate(schedule)
        pressure = self._sell_pressure(
            schedule.beneficiary_type, unlock_pct, monthly_rate, schedule.total_tokens
        )

        return VestingStatus(
            beneficiary_id=schedule.beneficiary_id,
            beneficiary_type=schedule.beneficiary_type,
            tokens_unlocked=unlockable,
            tokens_locked=tokens_locked,
            unlock_pct=round(unlock_pct, 4),
            days_until_next_cliff=days_until_next_cliff,
            days_until_full_vest=days_until_full,
            monthly_unlock_rate=monthly_rate,
            sell_pressure=pressure,
            is_fully_vested=is_fully_vested,
        )

    def get_aggregate_unlock(
        self, schedules: List[VestingSchedule], horizon_days: int
    ) -> float:
        """
        Total tokens that will unlock across all schedules within the next
        `horizon_days` (i.e. by current_timestamp + horizon_days * 86400).
        """
        total = 0.0
        for s in schedules:
            future_ts = s.current_timestamp + horizon_days * 86400.0
            future = VestingSchedule(
                beneficiary_id=s.beneficiary_id,
                beneficiary_type=s.beneficiary_type,
                total_tokens=s.total_tokens,
                tokens_unlocked=s.tokens_unlocked,
                cliff_days=s.cliff_days,
                vest_start_timestamp=s.vest_start_timestamp,
                vest_duration_days=s.vest_duration_days,
                current_timestamp=future_ts,
            )
            now_unlockable = self._unlockable(s)
            future_unlockable = self._unlockable(future)
            total += max(0.0, future_unlockable - now_unlockable)
        return total

    def upcoming_cliffs(
        self, schedules: List[VestingSchedule], within_days: int
    ) -> List[VestingSchedule]:
        """
        Return schedules whose cliff will pass within `within_days`.
        Cliff must NOT have already passed AND cliff_days - elapsed <= within_days.
        """
        result = []
        for s in schedules:
            elapsed = self._elapsed_days(s)
            if elapsed >= s.cliff_days:
                # cliff already passed
                continue
            days_to_cliff = s.cliff_days - elapsed
            if days_to_cliff <= within_days:
                result.append(s)
        return result

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save_results(
        self,
        statuses: List[VestingStatus],
        data_file: Path = DATA_FILE,
    ) -> None:
        """Append statuses to ring-buffer JSON (max MAX_ENTRIES). Atomic write."""
        data_file = Path(data_file)
        existing = self.load_history(data_file)

        new_entries = [
            {
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "beneficiary_id": s.beneficiary_id,
                "beneficiary_type": s.beneficiary_type,
                "tokens_unlocked": s.tokens_unlocked,
                "tokens_locked": s.tokens_locked,
                "unlock_pct": s.unlock_pct,
                "days_until_next_cliff": s.days_until_next_cliff,
                "days_until_full_vest": s.days_until_full_vest,
                "monthly_unlock_rate": s.monthly_unlock_rate,
                "sell_pressure": s.sell_pressure,
                "is_fully_vested": s.is_fully_vested,
            }
            for s in statuses
        ]

        combined = existing + new_entries
        combined = combined[-MAX_ENTRIES:]

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
    tracker = TokenVestingTracker()
    now = time.time()

    demo_schedule = VestingSchedule(
        beneficiary_id="team_founder_1",
        beneficiary_type="TEAM",
        total_tokens=1_000_000.0,
        tokens_unlocked=0.0,
        cliff_days=365,
        vest_start_timestamp=now - 400 * 86400,  # started 400 days ago
        vest_duration_days=1460,                  # 4 years
        current_timestamp=now,
    )

    status = tracker.get_status(demo_schedule)
    print(f"Beneficiary:          {status.beneficiary_id} ({status.beneficiary_type})")
    print(f"Tokens unlocked:      {status.tokens_unlocked:,.0f}")
    print(f"Tokens locked:        {status.tokens_locked:,.0f}")
    print(f"Unlock %:             {status.unlock_pct:.2f}%")
    print(f"Days until full vest: {status.days_until_full_vest}")
    print(f"Monthly unlock rate:  {status.monthly_unlock_rate:,.0f}")
    print(f"Sell pressure:        {status.sell_pressure}")
    print(f"Fully vested:         {status.is_fully_vested}")


if __name__ == "__main__":
    _demo()
