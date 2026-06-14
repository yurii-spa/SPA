"""
MP-782: WithdrawalQueueRiskAnalyzer
Assess exit-liquidity risk for protocols that gate withdrawals behind a queue
or a cooldown period (e.g. stETH unstake queue, sUSDe cooldown). Estimates how
long a position would take to exit, how much liquidity covers it, and classifies
the exit-liquidity tier.

Tier thresholds (estimated days to fully exit the position):
  IMMEDIATE  est_days <= 1
  FAST       est_days <= 3
  SLOW       est_days <= 14
  CONGESTED  est_days > 14   (anything slower than SLOW)
  FROZEN     daily_processing_usd <= 0 and there is a non-empty queue
             (withdrawals are not draining — exit time is undefined)
  UNKNOWN    position_size_usd <= 0 or otherwise un-analyzable input

Pure stdlib only. Advisory/read-only — never modifies allocator, risk, or
execution domains. Atomic writes.
"""

from dataclasses import dataclass, field
from typing import List, Optional
import json
import time
import os
from pathlib import Path

DATA_FILE = Path("data/withdrawal_queue_risk_log.json")
MAX_ENTRIES = 100

# Exit-liquidity tier thresholds, in estimated days to fully exit the position.
IMMEDIATE_DAYS = 1.0
FAST_DAYS = 3.0
SLOW_DAYS = 14.0
# > SLOW_DAYS => CONGESTED

# Liquidity-coverage advisory threshold: below this the instantly-available
# liquidity does not cover the position one-for-one.
MIN_LIQUIDITY_COVERAGE = 1.0
# Above this many estimated days the exit is flagged as slow in the advisory.
SLOW_EXIT_WARN_DAYS = 14.0


@dataclass
class WithdrawalQueueReport:
    position_size_usd: float
    queue_total_usd: float
    daily_processing_usd: float
    cooldown_days: float
    available_liquidity_usd: float
    queue_ahead_usd: float                       # queue already ahead of position
    days_to_process: Optional[float]             # queue / daily_processing
    estimated_days_to_exit: Optional[float]      # cooldown + days_to_process
    liquidity_coverage_ratio: Optional[float]    # available / position
    position_pct_of_queue: Optional[float]       # position / (queue + position)
    tier: str                                    # IMMEDIATE/FAST/SLOW/CONGESTED/FROZEN/UNKNOWN
    label: str = ""
    advisory: List[str] = field(default_factory=list)
    generated_at: str = ""


class WithdrawalQueueRiskAnalyzer:
    """
    Estimates exit-liquidity risk for queue / cooldown gated withdrawals.
    Advisory only — never modifies allocator, risk, or execution domains.
    """

    # ------------------------------------------------------------------
    # Classification
    # ------------------------------------------------------------------

    @staticmethod
    def _classify(estimated_days_to_exit: Optional[float], frozen: bool) -> str:
        if frozen:
            return "FROZEN"
        if estimated_days_to_exit is None:
            return "UNKNOWN"
        if estimated_days_to_exit <= IMMEDIATE_DAYS:
            return "IMMEDIATE"
        if estimated_days_to_exit <= FAST_DAYS:
            return "FAST"
        if estimated_days_to_exit <= SLOW_DAYS:
            return "SLOW"
        return "CONGESTED"

    @staticmethod
    def _build_advisory(
        tier: str,
        estimated_days_to_exit: Optional[float],
        liquidity_coverage_ratio: Optional[float],
    ) -> List[str]:
        out: List[str] = []
        if tier == "IMMEDIATE":
            out.append("Exit is effectively immediate — minimal queue/cooldown drag")
        elif tier == "FAST":
            out.append("Exit liquidity is fast — position should clear within a few days")
        elif tier == "SLOW":
            out.append("Exit liquidity is slow — plan for up to two weeks to fully exit")
        elif tier == "CONGESTED":
            out.append(
                "Exit queue is congested — fully exiting the position will take longer "
                "than two weeks"
            )
        elif tier == "FROZEN":
            out.append(
                "Withdrawals are frozen — queue is non-empty but nothing is being "
                "processed; exit time is undefined"
            )
        else:
            out.append("Position not analyzable — exit-liquidity tier is unknown")

        if liquidity_coverage_ratio is not None and liquidity_coverage_ratio < MIN_LIQUIDITY_COVERAGE:
            out.append(
                "Instant liquidity does not cover the position "
                f"(coverage {liquidity_coverage_ratio:.2f}x < {MIN_LIQUIDITY_COVERAGE:.2f}x) "
                "— an immediate exit may require accepting slippage"
            )
        if estimated_days_to_exit is not None and estimated_days_to_exit > SLOW_EXIT_WARN_DAYS:
            out.append(
                f"Estimated exit horizon is {estimated_days_to_exit:.1f} days — capital "
                "could be locked for an extended period"
            )
        return out

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(
        self,
        position_size_usd: float,
        queue_total_usd: float,
        daily_processing_usd: float,
        cooldown_days: float = 0.0,
        available_liquidity_usd: float = 0.0,
        label: str = "",
    ) -> WithdrawalQueueReport:
        """Build a WithdrawalQueueReport for a position behind a withdrawal queue."""
        generated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        # Guard: invalid / un-analyzable input -> UNKNOWN, no exception.
        if (
            position_size_usd is None
            or position_size_usd <= 0
            or queue_total_usd is None
            or queue_total_usd < 0
            or daily_processing_usd is None
            or daily_processing_usd < 0
            or cooldown_days is None
            or cooldown_days < 0
        ):
            return WithdrawalQueueReport(
                position_size_usd=float(position_size_usd or 0.0),
                queue_total_usd=float(queue_total_usd or 0.0),
                daily_processing_usd=float(daily_processing_usd or 0.0),
                cooldown_days=float(cooldown_days or 0.0),
                available_liquidity_usd=float(available_liquidity_usd or 0.0),
                queue_ahead_usd=float(queue_total_usd or 0.0),
                days_to_process=None,
                estimated_days_to_exit=None,
                liquidity_coverage_ratio=None,
                position_pct_of_queue=None,
                tier="UNKNOWN",
                label=label,
                advisory=["Invalid input — position must be positive and inputs non-negative"],
                generated_at=generated_at,
            )

        queue_ahead_usd = queue_total_usd

        # Queue drain time. If nothing is processed but there is a queue -> FROZEN.
        frozen = daily_processing_usd <= 0 and queue_total_usd > 0
        if daily_processing_usd > 0:
            days_to_process: Optional[float] = queue_total_usd / daily_processing_usd
        else:
            # No processing. If queue is empty there is no drain delay (0 days);
            # if queue is non-empty the drain time is undefined (frozen).
            days_to_process = None if queue_total_usd > 0 else 0.0

        if frozen:
            estimated_days_to_exit: Optional[float] = None
        else:
            estimated_days_to_exit = cooldown_days + (days_to_process or 0.0)

        # Liquidity coverage. position_size_usd > 0 guaranteed past the guard.
        liquidity_coverage_ratio: Optional[float] = available_liquidity_usd / position_size_usd

        denom = queue_total_usd + position_size_usd
        position_pct_of_queue: Optional[float] = (
            position_size_usd / denom if denom > 0 else None
        )

        tier = self._classify(estimated_days_to_exit, frozen)
        advisory = self._build_advisory(
            tier, estimated_days_to_exit, liquidity_coverage_ratio
        )

        return WithdrawalQueueReport(
            position_size_usd=round(position_size_usd, 2),
            queue_total_usd=round(queue_total_usd, 2),
            daily_processing_usd=round(daily_processing_usd, 2),
            cooldown_days=round(cooldown_days, 4),
            available_liquidity_usd=round(available_liquidity_usd, 2),
            queue_ahead_usd=round(queue_ahead_usd, 2),
            days_to_process=(round(days_to_process, 4) if days_to_process is not None else None),
            estimated_days_to_exit=(
                round(estimated_days_to_exit, 4) if estimated_days_to_exit is not None else None
            ),
            liquidity_coverage_ratio=(
                round(liquidity_coverage_ratio, 6)
                if liquidity_coverage_ratio is not None
                else None
            ),
            position_pct_of_queue=(
                round(position_pct_of_queue, 6) if position_pct_of_queue is not None else None
            ),
            tier=tier,
            label=label,
            advisory=advisory,
            generated_at=generated_at,
        )

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save_report(
        self, report: WithdrawalQueueReport, data_file: Path = DATA_FILE
    ) -> None:
        """Append a report to a ring-buffer JSON (max MAX_ENTRIES). Atomic write."""
        data_file = Path(data_file)
        existing = self.load_history(data_file)

        entry = {
            "timestamp": report.generated_at
            or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "label": report.label,
            "position_size_usd": report.position_size_usd,
            "queue_total_usd": report.queue_total_usd,
            "daily_processing_usd": report.daily_processing_usd,
            "cooldown_days": report.cooldown_days,
            "available_liquidity_usd": report.available_liquidity_usd,
            "queue_ahead_usd": report.queue_ahead_usd,
            "days_to_process": report.days_to_process,
            "estimated_days_to_exit": report.estimated_days_to_exit,
            "liquidity_coverage_ratio": report.liquidity_coverage_ratio,
            "position_pct_of_queue": report.position_pct_of_queue,
            "tier": report.tier,
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
    analyzer = WithdrawalQueueRiskAnalyzer()
    # stETH-style unstake queue: $50k position, $200M queue, $80M/day processed,
    # no extra cooldown, $30k instantly available.
    report = analyzer.analyze(
        position_size_usd=50_000.0,
        queue_total_usd=200_000_000.0,
        daily_processing_usd=80_000_000.0,
        cooldown_days=0.0,
        available_liquidity_usd=30_000.0,
        label="stETH-unstake-demo",
    )
    print(f"Label:                 {report.label}")
    print(f"Position:              ${report.position_size_usd:,.2f}")
    print(f"Queue total:           ${report.queue_total_usd:,.2f}")
    print(f"Daily processing:      ${report.daily_processing_usd:,.2f}")
    print(f"Days to process queue: {report.days_to_process}")
    print(f"Est. days to exit:     {report.estimated_days_to_exit}")
    print(f"Liquidity coverage:    {report.liquidity_coverage_ratio}")
    print(f"Position % of queue:   {report.position_pct_of_queue}")
    print(f"Tier:                  {report.tier}")
    for line in report.advisory:
        print(f"  - {line}")


if __name__ == "__main__":
    _demo()
