"""
MP-735: CapitalDeploymentPacer
Advise how to phase total capital into a target position across tranches to reduce
single-entry timing risk (DCA-style pacing). Given a total amount, a tranche count,
a weighting schedule and an inter-tranche interval, it produces per-tranche weights
and USD amounts, cumulative-deployed percentages, the deployment span in days, a
concentration metric (max weight) and an HHI, and classifies the spread as
WELL_SPREAD / MODERATE / CONCENTRATED / SINGLE_SHOT / UNKNOWN.
Pure stdlib only. Advisory/read-only. Atomic writes.
"""

from dataclasses import dataclass, field
from typing import List
import json
import time
import os
from pathlib import Path

DATA_FILE = Path("data/capital_deployment_log.json")
MAX_ENTRIES = 100

# Supported weighting schedules.
SCHEDULE_EQUAL = "equal"
SCHEDULE_FRONT_LOADED = "front_loaded"
SCHEDULE_BACK_LOADED = "back_loaded"
SCHEDULE_LINEAR_RAMP = "linear_ramp"
VALID_SCHEDULES = (
    SCHEDULE_EQUAL,
    SCHEDULE_FRONT_LOADED,
    SCHEDULE_BACK_LOADED,
    SCHEDULE_LINEAR_RAMP,
)

DEFAULT_SCHEDULE = SCHEDULE_EQUAL
DEFAULT_INTERVAL_DAYS = 1.0

# Risk-spread HHI thresholds. HHI ranges from 1/n (perfectly even) to 1.0 (one shot).
# Lower HHI => better spread. Thresholds are absolute on the HHI value.
HHI_WELL_SPREAD = 0.20      # HHI <= 0.20 => WELL_SPREAD
HHI_MODERATE = 0.40         # HHI <= 0.40 => MODERATE; else CONCENTRATED


@dataclass
class DeploymentReport:
    total_capital_usd: float
    num_tranches: int
    schedule: str
    interval_days: float
    tranches: List[dict]             # [{index, weight, usd, cumulative_pct}, ...]
    total_deployment_span_days: float
    max_tranche_weight: float        # concentration metric
    hhi: float                       # sum of squared weights
    risk_spread_tier: str            # WELL_SPREAD/MODERATE/CONCENTRATED/SINGLE_SHOT/UNKNOWN
    advisory: List[str] = field(default_factory=list)
    generated_at: str = ""


class CapitalDeploymentPacer:
    """
    Builds a DCA-style deployment schedule and reports its concentration profile.
    Advisory only — never modifies allocator, risk, or execution domains.
    """

    # ------------------------------------------------------------------
    # Calculation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _raw_weights(num_tranches: int, schedule: str) -> List[float]:
        """
        Deterministic, normalized weights summing to 1.0:
          - equal:        every tranche = 1/n.
          - linear_ramp:  weights proportional to 1, 2, ..., n (ascending ramp up).
          - back_loaded:  same ascending shape as linear_ramp (more capital later).
          - front_loaded: descending — weights proportional to n, n-1, ..., 1.
        front_loaded is the exact reverse of back_loaded/linear_ramp.
        """
        n = num_tranches
        if schedule == SCHEDULE_EQUAL:
            return [1.0 / n] * n
        if schedule in (SCHEDULE_LINEAR_RAMP, SCHEDULE_BACK_LOADED):
            raw = [float(i) for i in range(1, n + 1)]
        elif schedule == SCHEDULE_FRONT_LOADED:
            raw = [float(i) for i in range(n, 0, -1)]
        else:
            # Unknown schedule string: fall back to equal weighting.
            return [1.0 / n] * n
        total = sum(raw)
        return [w / total for w in raw]

    @staticmethod
    def _hhi(weights: List[float]) -> float:
        """Herfindahl-Hirschman Index: sum of squared weights."""
        return sum(w * w for w in weights)

    @staticmethod
    def _build_tranches(
        weights: List[float], total_capital_usd: float
    ) -> List[dict]:
        """
        Build per-tranche dicts with USD amounts (rounded 6dp) and cumulative %.
        Any rounding residual is added to the last tranche so USD sums to total.
        """
        usd_amounts = [round(w * total_capital_usd, 6) for w in weights]
        residual = round(total_capital_usd - sum(usd_amounts), 6)
        if usd_amounts:
            usd_amounts[-1] = round(usd_amounts[-1] + residual, 6)

        tranches: List[dict] = []
        cumulative_usd = 0.0
        for i, (w, usd) in enumerate(zip(weights, usd_amounts)):
            cumulative_usd += usd
            cumulative_pct = (
                (cumulative_usd / total_capital_usd) * 100.0
                if total_capital_usd > 0
                else 0.0
            )
            tranches.append(
                {
                    "index": i,
                    "weight": round(w, 6),
                    "usd": round(usd, 6),
                    "cumulative_pct": round(cumulative_pct, 6),
                }
            )
        return tranches

    @staticmethod
    def _classify(num_tranches: int, hhi: float) -> str:
        """Tier the deployment by its HHI concentration."""
        if num_tranches <= 1:
            return "SINGLE_SHOT"
        if hhi <= HHI_WELL_SPREAD:
            return "WELL_SPREAD"
        if hhi <= HHI_MODERATE:
            return "MODERATE"
        return "CONCENTRATED"

    @staticmethod
    def _build_advisory(
        tier: str,
        schedule: str,
        num_tranches: int,
        span_days: float,
        max_weight: float,
    ) -> List[str]:
        out: List[str] = []
        if tier == "SINGLE_SHOT":
            out.append(
                "Single-shot deployment — all capital enters at once, maximizing "
                "single-entry timing risk. Consider splitting into multiple tranches"
            )
        elif tier == "WELL_SPREAD":
            out.append(
                f"Well spread across {num_tranches} tranches (HHI low) — single-entry "
                "timing risk is well diversified"
            )
        elif tier == "MODERATE":
            out.append(
                f"Moderately spread across {num_tranches} tranches — some concentration "
                f"remains (largest tranche {max_weight * 100:.2f}% of capital)"
            )
        else:
            out.append(
                f"Concentrated despite {num_tranches} tranches — largest tranche is "
                f"{max_weight * 100:.2f}% of capital; timing risk is poorly diversified"
            )
        if num_tranches > 1:
            out.append(
                f"Deployment spans {span_days:.2f} days "
                f"({num_tranches} tranches at the given interval)"
            )
        if schedule == SCHEDULE_FRONT_LOADED:
            out.append(
                "Front-loaded: more capital deploys early — faster exposure but less "
                "averaging benefit if price falls after entry"
            )
        elif schedule in (SCHEDULE_BACK_LOADED, SCHEDULE_LINEAR_RAMP):
            out.append(
                "Back-loaded ramp: more capital deploys later — better averaging if "
                "price keeps falling, but slower to reach full exposure"
            )
        return out

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(
        self,
        total_capital_usd: float = 10000.0,
        num_tranches: int = 4,
        schedule: str = DEFAULT_SCHEDULE,
        interval_days: float = DEFAULT_INTERVAL_DAYS,
    ) -> DeploymentReport:
        """Build a DeploymentReport: tranche schedule plus concentration profile."""
        generated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        # Guard degenerate inputs.
        if num_tranches < 1 or total_capital_usd <= 0.0:
            msg = (
                "num_tranches must be >= 1 and total_capital_usd must be positive "
                "to build a deployment schedule"
            )
            return DeploymentReport(
                total_capital_usd=round(total_capital_usd, 6),
                num_tranches=num_tranches,
                schedule=schedule,
                interval_days=round(interval_days, 6),
                tranches=[],
                total_deployment_span_days=0.0,
                max_tranche_weight=0.0,
                hhi=0.0,
                risk_spread_tier="UNKNOWN",
                advisory=[msg],
                generated_at=generated_at,
            )

        normalized_schedule = schedule if schedule in VALID_SCHEDULES else SCHEDULE_EQUAL

        weights = self._raw_weights(num_tranches, normalized_schedule)
        tranches = self._build_tranches(weights, total_capital_usd)
        hhi = self._hhi(weights)
        max_weight = max(weights)
        span_days = (num_tranches - 1) * interval_days

        tier = self._classify(num_tranches, hhi)
        advisory = self._build_advisory(
            tier, normalized_schedule, num_tranches, span_days, max_weight
        )
        if schedule not in VALID_SCHEDULES:
            advisory.append(
                f"Unrecognized schedule '{schedule}' — fell back to equal weighting"
            )

        return DeploymentReport(
            total_capital_usd=round(total_capital_usd, 6),
            num_tranches=num_tranches,
            schedule=normalized_schedule,
            interval_days=round(interval_days, 6),
            tranches=tranches,
            total_deployment_span_days=round(span_days, 6),
            max_tranche_weight=round(max_weight, 6),
            hhi=round(hhi, 6),
            risk_spread_tier=tier,
            advisory=advisory,
            generated_at=generated_at,
        )

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save_report(self, report: DeploymentReport, data_file: Path = DATA_FILE) -> None:
        """Append a report to a ring-buffer JSON (max MAX_ENTRIES). Atomic write."""
        data_file = Path(data_file)
        existing = self.load_history(data_file)

        entry = {
            "timestamp": report.generated_at
            or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "total_capital_usd": report.total_capital_usd,
            "num_tranches": report.num_tranches,
            "schedule": report.schedule,
            "interval_days": report.interval_days,
            "tranches": report.tranches,
            "total_deployment_span_days": report.total_deployment_span_days,
            "max_tranche_weight": report.max_tranche_weight,
            "hhi": report.hhi,
            "risk_spread_tier": report.risk_spread_tier,
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
    pacer = CapitalDeploymentPacer()
    report = pacer.analyze(
        total_capital_usd=20000.0,
        num_tranches=5,
        schedule=SCHEDULE_FRONT_LOADED,
        interval_days=2.0,
    )
    print(f"Total capital:        ${report.total_capital_usd:,.2f}")
    print(f"Tranches:             {report.num_tranches}")
    print(f"Schedule:             {report.schedule}")
    print(f"Span:                 {report.total_deployment_span_days:.2f} days")
    print(f"Max tranche weight:   {report.max_tranche_weight * 100:.3f}%")
    print(f"HHI:                  {report.hhi:.6f}")
    print(f"Risk-spread tier:     {report.risk_spread_tier}")
    print("Tranches:")
    for t in report.tranches:
        print(
            f"  #{t['index']}: weight {t['weight'] * 100:6.3f}%  "
            f"${t['usd']:>10,.2f}  cumulative {t['cumulative_pct']:6.2f}%"
        )
    for line in report.advisory:
        print(f"  - {line}")


if __name__ == "__main__":
    _demo()
