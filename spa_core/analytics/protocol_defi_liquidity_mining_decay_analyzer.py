"""
MP-1123: ProtocolDeFiLiquidityMiningDecayAnalyzer

Models the decay of liquidity-mining rewards over time.  Many protocols
start with high emission rates that halve periodically.  This module
calculates the forward-looking APY trajectory and warns when mining
rewards will drop below the threshold that justifies staying in the
protocol.

Key calculations
----------------
current_mining_apy_pct
    = (my_stake_usd / total_staked_usd)  -- my share of the pool
      * current_emission_rate_usd_per_day -- total daily USD rewards
      * 365                               -- annualise
      / my_stake_usd                      -- APY denominator
      * 100
    Simplifies to:
      = current_emission_rate_usd_per_day * 365 / total_staked_usd * 100

current_total_apy_pct
    = current_mining_apy_pct + base_protocol_apy_pct

days_to_next_halving
    = halving_period_days - days_since_last_halving

apy_after_next_halving_pct
    = current_mining_apy_pct / 2 + base_protocol_apy_pct

apy_after_two_halvings_pct
    = current_mining_apy_pct / 4 + base_protocol_apy_pct

days_until_below_min_apy
    Find the smallest integer n (number of halvings) such that:
      current_mining_apy / 2^n + base_apy < min_acceptable_apy
    If base_apy >= min_acceptable_apy → -1 (never drops below).
    If already below → 0.
    Days = days_to_next_halving + (n - 1) * halving_period_days.

Decay labels (evaluated in priority order — first match wins):
    EMISSION_EXHAUSTED   current_total_apy <= min_acceptable_apy
    POST_HALVING_DECAY   current_total_apy <  min_acceptable_apy * 1.5
    APPROACHING_HALVING  days_to_next_halving <= halving_period * 0.25
    HEALTHY_EMISSION     days_to_next_halving <= halving_period * 0.75
    EARLY_EMISSION       days_to_next_halving >  halving_period * 0.75

Pure stdlib only.  Advisory/read-only.  Atomic writes (tmp + os.replace).
Log file: data/liquidity_mining_decay_log.json  (ring-buffer, cap 100).
"""

from __future__ import annotations

import json
import math
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DATA_FILE = Path("data/liquidity_mining_decay_log.json")
MAX_ENTRIES: int = 100

_LABEL_EARLY = "EARLY_EMISSION"
_LABEL_HEALTHY = "HEALTHY_EMISSION"
_LABEL_APPROACHING = "APPROACHING_HALVING"
_LABEL_POST = "POST_HALVING_DECAY"
_LABEL_EXHAUSTED = "EMISSION_EXHAUSTED"

_ZERO_EPS = 1e-12


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass
class LiquidityMiningDecayReport:
    protocol_name: str
    current_emission_rate_usd_per_day: float
    halving_period_days: int
    days_since_last_halving: int
    total_staked_usd: float
    my_stake_usd: float
    base_protocol_apy_pct: float
    min_acceptable_apy_pct: float

    # Computed outputs
    current_mining_apy_pct: float
    current_total_apy_pct: float
    days_to_next_halving: int
    apy_after_next_halving_pct: float
    apy_after_two_halvings_pct: float
    days_until_below_min_apy: int      # -1 if never
    decay_label: str

    advisory: List[str] = field(default_factory=list)
    generated_at: str = ""


# ---------------------------------------------------------------------------
# Analyzer
# ---------------------------------------------------------------------------

class ProtocolDeFiLiquidityMiningDecayAnalyzer:
    """
    Models liquidity-mining reward decay and APY trajectory over successive
    halvings.  Advisory only — never modifies allocator, risk, or execution
    domains.
    """

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_mining_apy(
        emission_usd_per_day: float, total_staked_usd: float
    ) -> float:
        """Annual mining APY as a percentage (independent of my_stake size)."""
        if total_staked_usd <= _ZERO_EPS:
            return 0.0
        return emission_usd_per_day * 365.0 / total_staked_usd * 100.0

    @staticmethod
    def _days_until_below_min(
        current_mining_apy: float,
        base_apy: float,
        min_apy: float,
        halving_period_days: int,
        days_to_next_halving: int,
    ) -> int:
        """
        Returns the number of days from now until total APY drops below
        min_apy, or -1 if it never does.

        We iterate halvings: after n halvings total APY =
            current_mining_apy / 2^n + base_apy

        If base_apy >= min_apy → -1 (base alone keeps us above threshold).
        If already at or below threshold → 0.
        """
        # If base yield alone already meets the minimum, APY never drops below.
        if base_apy >= min_apy - _ZERO_EPS:
            return -1

        # Already at or below threshold right now?
        current_total = current_mining_apy + base_apy
        if current_total <= min_apy + _ZERO_EPS:
            return 0

        # Minimum mining APY required to stay above threshold.
        min_mining = min_apy - base_apy
        if min_mining <= _ZERO_EPS:
            return -1

        # Find smallest n such that current_mining / 2^n < min_mining.
        ratio = current_mining_apy / min_mining
        if ratio <= 1.0 + _ZERO_EPS:
            # Already barely above; 0 halvings needed — but we checked total above.
            return days_to_next_halving

        n = math.floor(math.log2(ratio)) + 1  # smallest n with 2^n > ratio

        if n <= 0:
            return 0
        if n == 1:
            return days_to_next_halving
        return days_to_next_halving + (n - 1) * halving_period_days

    @staticmethod
    def _classify_label(
        current_total_apy: float,
        min_apy: float,
        halving_period_days: int,
        days_to_next_halving: int,
    ) -> str:
        """Priority-ordered label assignment."""
        # Highest severity first
        if current_total_apy <= min_apy + _ZERO_EPS:
            return _LABEL_EXHAUSTED
        if current_total_apy < min_apy * 1.5 - _ZERO_EPS:
            return _LABEL_POST
        # Position-based
        if days_to_next_halving <= halving_period_days * 0.25:
            return _LABEL_APPROACHING
        if days_to_next_halving <= halving_period_days * 0.75:
            return _LABEL_HEALTHY
        return _LABEL_EARLY

    @staticmethod
    def _build_advisory(
        decay_label: str,
        current_total_apy: float,
        min_apy: float,
        days_to_next_halving: int,
        apy_after_next_halving: float,
        days_until_below: int,
        protocol_name: str,
    ) -> List[str]:
        msgs: List[str] = []
        if decay_label == _LABEL_EXHAUSTED:
            msgs.append(
                f"{protocol_name}: APY ({current_total_apy:.2f}%) is at or below "
                f"minimum acceptable ({min_apy:.2f}%) — consider exiting"
            )
        elif decay_label == _LABEL_POST:
            msgs.append(
                f"{protocol_name}: APY ({current_total_apy:.2f}%) is dangerously "
                f"close to minimum ({min_apy:.2f}%) — post-halving decay in effect"
            )
        elif decay_label == _LABEL_APPROACHING:
            msgs.append(
                f"{protocol_name}: {days_to_next_halving}d to halving — "
                f"APY will drop to ~{apy_after_next_halving:.2f}% after next halving"
            )
        elif decay_label == _LABEL_HEALTHY:
            msgs.append(
                f"{protocol_name}: healthy emission phase — "
                f"next halving in {days_to_next_halving}d, "
                f"APY post-halving ~{apy_after_next_halving:.2f}%"
            )
        else:
            msgs.append(
                f"{protocol_name}: early emission phase — "
                f"next halving in {days_to_next_halving}d"
            )

        if days_until_below == -1:
            msgs.append(
                "Base protocol APY alone meets minimum threshold — "
                "emissions are a bonus, not a requirement"
            )
        elif days_until_below == 0:
            msgs.append(
                "APY already at or below minimum — immediate review recommended"
            )
        else:
            msgs.append(
                f"Expected to drop below minimum APY in ~{days_until_below} days"
            )
        return msgs

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(
        self,
        current_emission_rate_usd_per_day: float,
        halving_period_days: int,
        days_since_last_halving: int,
        total_staked_usd: float,
        my_stake_usd: float,
        base_protocol_apy_pct: float,
        min_acceptable_apy_pct: float,
        protocol_name: str,
    ) -> LiquidityMiningDecayReport:
        """
        Compute the mining-decay report for a given protocol/position.

        Parameters
        ----------
        current_emission_rate_usd_per_day : total daily token rewards (USD)
        halving_period_days               : how often emissions halve
        days_since_last_halving           : days elapsed since the last halving
        total_staked_usd                  : total USD staked in the protocol
        my_stake_usd                      : caller's own stake in USD
        base_protocol_apy_pct             : APY from protocol fees (no emissions)
        min_acceptable_apy_pct            : exit threshold APY
        protocol_name                     : human-readable label
        """
        generated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        hp = max(1, int(halving_period_days))
        dslh = max(0, int(days_since_last_halving))
        dslh = min(dslh, hp - 1)  # can't exceed one full period
        days_to_next = hp - dslh

        mining_apy = self._compute_mining_apy(
            float(current_emission_rate_usd_per_day),
            float(total_staked_usd),
        )
        total_apy = mining_apy + float(base_protocol_apy_pct)
        apy_next = mining_apy / 2.0 + float(base_protocol_apy_pct)
        apy_two = mining_apy / 4.0 + float(base_protocol_apy_pct)

        days_until_below = self._days_until_below_min(
            mining_apy,
            float(base_protocol_apy_pct),
            float(min_acceptable_apy_pct),
            hp,
            days_to_next,
        )

        decay_label = self._classify_label(
            total_apy,
            float(min_acceptable_apy_pct),
            hp,
            days_to_next,
        )
        advisory = self._build_advisory(
            decay_label,
            total_apy,
            float(min_acceptable_apy_pct),
            days_to_next,
            apy_next,
            days_until_below,
            protocol_name,
        )

        return LiquidityMiningDecayReport(
            protocol_name=protocol_name,
            current_emission_rate_usd_per_day=float(current_emission_rate_usd_per_day),
            halving_period_days=hp,
            days_since_last_halving=dslh,
            total_staked_usd=float(total_staked_usd),
            my_stake_usd=float(my_stake_usd),
            base_protocol_apy_pct=round(float(base_protocol_apy_pct), 8),
            min_acceptable_apy_pct=round(float(min_acceptable_apy_pct), 8),
            current_mining_apy_pct=round(mining_apy, 8),
            current_total_apy_pct=round(total_apy, 8),
            days_to_next_halving=days_to_next,
            apy_after_next_halving_pct=round(apy_next, 8),
            apy_after_two_halvings_pct=round(apy_two, 8),
            days_until_below_min_apy=days_until_below,
            decay_label=decay_label,
            advisory=advisory,
            generated_at=generated_at,
        )

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save_report(
        self,
        report: LiquidityMiningDecayReport,
        data_file: Path = DATA_FILE,
    ) -> None:
        """Append report to ring-buffer JSON (cap MAX_ENTRIES).  Atomic write."""
        data_file = Path(data_file)
        existing = self.load_history(data_file)

        entry = {
            "timestamp": report.generated_at
            or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "protocol_name": report.protocol_name,
            "current_emission_rate_usd_per_day": report.current_emission_rate_usd_per_day,
            "halving_period_days": report.halving_period_days,
            "days_since_last_halving": report.days_since_last_halving,
            "total_staked_usd": report.total_staked_usd,
            "my_stake_usd": report.my_stake_usd,
            "base_protocol_apy_pct": report.base_protocol_apy_pct,
            "min_acceptable_apy_pct": report.min_acceptable_apy_pct,
            "current_mining_apy_pct": report.current_mining_apy_pct,
            "current_total_apy_pct": report.current_total_apy_pct,
            "days_to_next_halving": report.days_to_next_halving,
            "apy_after_next_halving_pct": report.apy_after_next_halving_pct,
            "apy_after_two_halvings_pct": report.apy_after_two_halvings_pct,
            "days_until_below_min_apy": report.days_until_below_min_apy,
            "decay_label": report.decay_label,
            "advisory": report.advisory,
        }

        combined = (existing + [entry])[-MAX_ENTRIES:]

        data_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = data_file.with_suffix(".tmp")
        with open(tmp, "w") as fh:
            json.dump(combined, fh, indent=2)
        os.replace(tmp, data_file)

    def load_history(self, data_file: Path = DATA_FILE) -> list:
        """Load ring-buffer JSON.  Returns [] on missing / corrupt file."""
        data_file = Path(data_file)
        if not data_file.exists():
            return []
        try:
            with open(data_file, "r") as fh:
                return json.load(fh)
        except (json.JSONDecodeError, OSError):
            return []


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _demo() -> None:
    ana = ProtocolDeFiLiquidityMiningDecayAnalyzer()
    report = ana.analyze(
        current_emission_rate_usd_per_day=10_000.0,
        halving_period_days=180,
        days_since_last_halving=45,
        total_staked_usd=5_000_000.0,
        my_stake_usd=50_000.0,
        base_protocol_apy_pct=3.0,
        min_acceptable_apy_pct=5.0,
        protocol_name="SushiSwap",
    )
    print(f"Protocol:              {report.protocol_name}")
    print(f"Mining APY:            {report.current_mining_apy_pct:.4f}%")
    print(f"Total APY:             {report.current_total_apy_pct:.4f}%")
    print(f"Days to next halving:  {report.days_to_next_halving}")
    print(f"APY after 1 halving:   {report.apy_after_next_halving_pct:.4f}%")
    print(f"APY after 2 halvings:  {report.apy_after_two_halvings_pct:.4f}%")
    print(f"Days until < min APY:  {report.days_until_below_min_apy}")
    print(f"Decay label:           {report.decay_label}")
    for msg in report.advisory:
        print(f"  • {msg}")


if __name__ == "__main__":
    _demo()
