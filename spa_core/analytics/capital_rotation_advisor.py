"""
MP-646: CapitalRotationAdvisor
Advisory recommendations for rotating capital between adapters.
Pure stdlib, read-only advisory module — never touches allocator/risk/execution.
"""
from dataclasses import dataclass
from typing import List, Optional
import json
import time
import os
from pathlib import Path

DATA_FILE = Path("data/capital_rotation_advice.json")
MAX_ENTRIES = 100

# Thresholds
MIN_APY_GAIN_BPS = 25       # minimum net gain to recommend rotation
ROTATION_COST_BPS = 10      # assumed gas + slippage cost (bps)
MIN_DAYS_BEFORE_ROTATE = 7  # avoid rotating too frequently


@dataclass
class AdapterSnapshot:
    adapter_id: str
    current_apy: float              # current observed APY (decimal)
    expected_apy: float             # target/expected APY (decimal)
    current_allocation_usd: float   # USD currently allocated
    tier: str                       # T1 / T2 / T3
    lock_days_remaining: int        # 0 if liquid
    protocol_risk_score: float      # 0–100 (lower = safer)
    days_in_position: int           # days since position was opened


@dataclass
class RotationAction:
    from_adapter: str
    to_adapter: str
    amount_usd: float
    reason: str
    apy_gain_bps: float     # expected APY improvement in bps (net of costs)
    urgency: str            # IMMEDIATE / SOON / OPTIONAL
    blocked_by_lock: bool   # True if from_adapter has remaining lock


@dataclass
class RotationReport:
    timestamp: float
    total_capital_usd: float
    actions: List[RotationAction]
    estimated_annual_gain_usd: float
    verdict: str                    # ROTATE_NOW / ROTATE_SOON / HOLD / LOCKED
    top_opportunity: Optional[str]  # adapter_id to rotate INTO


class CapitalRotationAdvisor:
    def __init__(self, data_file: Path = DATA_FILE):
        self.data_file = data_file

    def analyze(
        self,
        current: List[AdapterSnapshot],
        candidates: List[AdapterSnapshot],
    ) -> RotationReport:
        """
        Analyse current positions and produce rotation recommendations.

        Parameters
        ----------
        current    : positions currently held
        candidates : adapters available to rotate into (not currently held
                     or underweight)
        """
        total_capital = sum(a.current_allocation_usd for a in current)
        actions: List[RotationAction] = []

        for pos in current:
            if pos.lock_days_remaining > 0:
                # Blocked by lock — flag if gain is meaningful, but don't act
                best = self._find_best(candidates, pos)
                if best and self._gross_gain_bps(pos, best) > MIN_APY_GAIN_BPS:
                    actions.append(
                        RotationAction(
                            from_adapter=pos.adapter_id,
                            to_adapter=best.adapter_id,
                            amount_usd=pos.current_allocation_usd,
                            reason=f"Lock-blocked: {pos.lock_days_remaining}d remaining",
                            apy_gain_bps=self._gross_gain_bps(pos, best),
                            urgency="SOON",
                            blocked_by_lock=True,
                        )
                    )
                continue

            if pos.days_in_position < MIN_DAYS_BEFORE_ROTATE:
                continue  # too recent to rotate

            best = self._find_best(candidates, pos)
            if not best:
                continue

            net_gain_bps = self._apy_gain_bps(pos, best)   # already net of cost
            if net_gain_bps >= MIN_APY_GAIN_BPS:
                urgency = "IMMEDIATE" if net_gain_bps >= 50 else "SOON"
                actions.append(
                    RotationAction(
                        from_adapter=pos.adapter_id,
                        to_adapter=best.adapter_id,
                        amount_usd=pos.current_allocation_usd,
                        reason=f"+{net_gain_bps:.0f}bps net after costs",
                        apy_gain_bps=net_gain_bps,
                        urgency=urgency,
                        blocked_by_lock=False,
                    )
                )

        # Sort by gain descending
        actions.sort(key=lambda a: a.apy_gain_bps, reverse=True)

        # Estimated annual gain (only unlocked actions)
        annual_gain = sum(
            a.amount_usd * a.apy_gain_bps / 10000
            for a in actions
            if not a.blocked_by_lock
        )

        locked_actions = [a for a in actions if a.blocked_by_lock]
        free_actions = [a for a in actions if not a.blocked_by_lock]

        if free_actions and free_actions[0].urgency == "IMMEDIATE":
            verdict = "ROTATE_NOW"
        elif free_actions:
            verdict = "ROTATE_SOON"
        elif locked_actions:
            verdict = "LOCKED"
        else:
            verdict = "HOLD"

        top = actions[0].to_adapter if actions else None

        return RotationReport(
            timestamp=time.time(),
            total_capital_usd=round(total_capital, 2),
            actions=actions,
            estimated_annual_gain_usd=round(annual_gain, 2),
            verdict=verdict,
            top_opportunity=top,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _gross_gain_bps(
        self, current: AdapterSnapshot, candidate: AdapterSnapshot
    ) -> float:
        """Raw APY gain in bps (without subtracting rotation cost)."""
        return round((candidate.current_apy - current.current_apy) * 10000, 6)

    def _apy_gain_bps(
        self, current: AdapterSnapshot, candidate: AdapterSnapshot
    ) -> float:
        """Net APY gain in bps after deducting rotation cost."""
        return self._gross_gain_bps(current, candidate) - ROTATION_COST_BPS

    def _find_best(
        self,
        candidates: List[AdapterSnapshot],
        current: AdapterSnapshot,
    ) -> Optional[AdapterSnapshot]:
        """
        Find best candidate: higher APY than current, not same adapter.
        Score = current_apy - protocol_risk_score * 0.001  (risk-penalised).
        """
        eligible = [
            c
            for c in candidates
            if c.adapter_id != current.adapter_id
            and c.current_apy > current.current_apy
        ]
        if not eligible:
            return None
        return max(eligible, key=lambda c: c.current_apy - c.protocol_risk_score * 0.001)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save_report(self, report: RotationReport) -> None:
        """Atomically append report summary to the ring-buffer JSON file."""
        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            existing = json.loads(self.data_file.read_text())
        except Exception:
            existing = []
        entry = {
            "timestamp": report.timestamp,
            "total_capital_usd": report.total_capital_usd,
            "action_count": len(report.actions),
            "estimated_annual_gain_usd": report.estimated_annual_gain_usd,
            "verdict": report.verdict,
            "top_opportunity": report.top_opportunity,
        }
        existing.append(entry)
        existing = existing[-MAX_ENTRIES:]
        tmp = self.data_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(existing, indent=2))
        os.replace(tmp, self.data_file)

    def load_history(self) -> List[dict]:
        """Load saved report history; returns [] if file missing/invalid."""
        try:
            return json.loads(self.data_file.read_text())
        except Exception:
            return []

    def get_immediate_actions(self, report: RotationReport) -> List[RotationAction]:
        """Return only IMMEDIATE, non-locked rotation actions."""
        return [
            a
            for a in report.actions
            if a.urgency == "IMMEDIATE" and not a.blocked_by_lock
        ]


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="MP-646 CapitalRotationAdvisor")
    parser.add_argument("--run", action="store_true", help="Compute + save to data file")
    parser.add_argument("--check", action="store_true", help="Compute + print, no save (default)")
    parser.add_argument("--data-dir", default=None, help="Override data directory")
    args = parser.parse_args()

    data_file = DATA_FILE
    if args.data_dir:
        data_file = Path(args.data_dir) / "capital_rotation_advice.json"

    advisor = CapitalRotationAdvisor(data_file=data_file)

    # Demo scenario
    current = [
        AdapterSnapshot("aave_v3", 0.035, 0.035, 40000.0, "T1", 0, 10.0, 20),
        AdapterSnapshot("compound_v3", 0.048, 0.048, 35000.0, "T1", 0, 12.0, 15),
        AdapterSnapshot("morpho_steakhouse", 0.065, 0.065, 25000.0, "T1", 0, 15.0, 10),
    ]
    candidates = [
        AdapterSnapshot("euler_v2", 0.072, 0.072, 0.0, "T2", 0, 20.0, 0),
        AdapterSnapshot("yearn_v3", 0.058, 0.058, 0.0, "T2", 0, 18.0, 0),
    ]

    report = advisor.analyze(current, candidates)

    print(f"Verdict              : {report.verdict}")
    print(f"Total capital USD    : ${report.total_capital_usd:,.2f}")
    print(f"Est. annual gain USD : ${report.estimated_annual_gain_usd:,.2f}")
    print(f"Top opportunity      : {report.top_opportunity}")
    print(f"Actions ({len(report.actions)}):")
    for a in report.actions:
        lock_tag = " [LOCKED]" if a.blocked_by_lock else ""
        print(f"  {a.from_adapter} → {a.to_adapter}: +{a.apy_gain_bps:.0f}bps "
              f"[{a.urgency}]{lock_tag} | {a.reason}")

    if args.run:
        advisor.save_report(report)
        print(f"Saved → {data_file}")
