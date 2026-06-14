"""
MP-762: ConcentrationRiskAnalyzer
Measure portfolio concentration across positions (e.g. protocols/chains) using the
Herfindahl-Hirschman Index (HHI), effective number of positions, and top-N weight
shares. Classifies a concentration tier and emits advisory guidance.
Pure stdlib only. Advisory/read-only. Atomic writes.
"""

from dataclasses import dataclass, field
from typing import List, Optional
import json
import time
import os
from pathlib import Path

DATA_FILE = Path("data/concentration_risk_log.json")
MAX_ENTRIES = 100

# HHI concentration tiers.
HHI_WELL_DIVERSIFIED = 0.15
HHI_MODERATE = 0.25
HHI_CONCENTRATED = 0.40
# >= 0.40 => HIGHLY_CONCENTRATED

# A single position dominating more than this share triggers a warning.
TOP1_WARN_THRESHOLD = 0.50


@dataclass
class ConcentrationReport:
    num_positions: int
    total: float
    hhi: float                              # sum of squared weights, 1/n .. 1.0
    effective_number_of_positions: float    # 1 / HHI
    max_weight: float
    top_position_label: str
    top1_pct: float                         # largest single weight
    top3_pct: float                         # sum of three largest weights
    concentration_tier: str                 # WELL_DIVERSIFIED/MODERATE/...
    advisory: List[str] = field(default_factory=list)
    generated_at: str = ""


class ConcentrationRiskAnalyzer:
    """
    Computes portfolio concentration metrics from a set of position sizes.
    Advisory only — never modifies allocator, risk, or execution domains.
    """

    # ------------------------------------------------------------------
    # Calculation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _hhi(weights: List[float]) -> float:
        """Herfindahl-Hirschman Index: sum of squared normalized weights."""
        return sum(w * w for w in weights)

    @staticmethod
    def _effective_n(hhi: float) -> float:
        """Effective number of positions = 1 / HHI. Guards HHI<=0."""
        if hhi <= 0:
            return 0.0
        return 1.0 / hhi

    @staticmethod
    def _top_n_sum(weights: List[float], n: int) -> float:
        """Sum of the n largest weights (or all if fewer than n)."""
        if not weights:
            return 0.0
        ordered = sorted(weights, reverse=True)
        return sum(ordered[:n])

    @staticmethod
    def _classify(hhi: float, num_positions: int) -> str:
        if num_positions == 1:
            return "SINGLE_POSITION"
        if hhi < HHI_WELL_DIVERSIFIED:
            return "WELL_DIVERSIFIED"
        if hhi < HHI_MODERATE:
            return "MODERATE"
        if hhi < HHI_CONCENTRATED:
            return "CONCENTRATED"
        return "HIGHLY_CONCENTRATED"

    @staticmethod
    def _build_advisory(
        tier: str,
        top1_pct: float,
        effective_n: float,
        num_positions: int,
    ) -> List[str]:
        out: List[str] = []
        if tier == "SINGLE_POSITION":
            out.append(
                "Single position — portfolio is entirely concentrated in one holding"
            )
        elif tier == "WELL_DIVERSIFIED":
            out.append(
                "Well diversified — concentration risk is low across positions"
            )
        elif tier == "MODERATE":
            out.append(
                "Moderate concentration — exposure is reasonably spread but watch the "
                "largest holdings"
            )
        elif tier == "CONCENTRATED":
            out.append(
                "Concentrated — a few positions dominate the portfolio"
            )
        else:
            out.append(
                "Highly concentrated — portfolio risk is dominated by a small number "
                "of positions"
            )
        if top1_pct > TOP1_WARN_THRESHOLD:
            out.append(
                f"Largest single position exceeds 50% of portfolio "
                f"({top1_pct * 100:.2f}%)"
            )
        out.append(
            f"Effective number of positions: {effective_n:.2f} "
            f"(of {num_positions} held)"
        )
        return out

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(
        self,
        positions: List[float],
        labels: Optional[List[str]] = None,
    ) -> ConcentrationReport:
        """Compute a ConcentrationReport from a list of position sizes (USD or weights)."""
        generated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        total = sum(positions) if positions else 0.0
        has_negative = any(p < 0 for p in positions)

        if not positions or total <= 0 or has_negative:
            if not positions:
                reason = "No positions supplied"
            elif has_negative:
                reason = "Negative position value supplied — cannot compute weights"
            else:
                reason = "Total portfolio value is non-positive — cannot compute weights"
            return ConcentrationReport(
                num_positions=len(positions),
                total=round(total, 6),
                hhi=0.0,
                effective_number_of_positions=0.0,
                max_weight=0.0,
                top_position_label="",
                top1_pct=0.0,
                top3_pct=0.0,
                concentration_tier="UNKNOWN",
                advisory=[reason],
                generated_at=generated_at,
            )

        n = len(positions)
        weights = [p / total for p in positions]
        hhi = self._hhi(weights)
        effective_n = self._effective_n(hhi)

        max_weight = max(weights)
        max_index = weights.index(max_weight)
        if labels is not None and max_index < len(labels):
            top_position_label = str(labels[max_index])
        else:
            top_position_label = str(max_index)

        top1_pct = max_weight
        top3_pct = self._top_n_sum(weights, 3)

        tier = self._classify(hhi, n)
        advisory = self._build_advisory(tier, top1_pct, effective_n, n)

        return ConcentrationReport(
            num_positions=n,
            total=round(total, 6),
            hhi=round(hhi, 6),
            effective_number_of_positions=round(effective_n, 6),
            max_weight=round(max_weight, 6),
            top_position_label=top_position_label,
            top1_pct=round(top1_pct, 6),
            top3_pct=round(top3_pct, 6),
            concentration_tier=tier,
            advisory=advisory,
            generated_at=generated_at,
        )

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save_report(
        self, report: ConcentrationReport, data_file: Path = DATA_FILE
    ) -> None:
        """Append a report to a ring-buffer JSON (max MAX_ENTRIES). Atomic write."""
        data_file = Path(data_file)
        existing = self.load_history(data_file)

        entry = {
            "timestamp": report.generated_at
            or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "num_positions": report.num_positions,
            "total": report.total,
            "hhi": report.hhi,
            "effective_number_of_positions": report.effective_number_of_positions,
            "max_weight": report.max_weight,
            "top_position_label": report.top_position_label,
            "top1_pct": report.top1_pct,
            "top3_pct": report.top3_pct,
            "concentration_tier": report.concentration_tier,
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
    analyzer = ConcentrationRiskAnalyzer()
    positions = [45000.0, 30000.0, 15000.0, 7000.0, 3000.0]
    labels = ["Aave", "Compound", "Pendle", "Curve", "Morpho"]
    report = analyzer.analyze(positions, labels=labels)
    print(f"Positions:            {report.num_positions}")
    print(f"Total:                ${report.total:,.2f}")
    print(f"HHI:                  {report.hhi:.6f}")
    print(f"Effective positions:  {report.effective_number_of_positions:.3f}")
    print(f"Top position:         {report.top_position_label}")
    print(f"Top1 share:           {report.top1_pct * 100:.2f}%")
    print(f"Top3 share:           {report.top3_pct * 100:.2f}%")
    print(f"Concentration tier:   {report.concentration_tier}")
    for line in report.advisory:
        print(f"  - {line}")


if __name__ == "__main__":
    _demo()
