"""
MP-679: CorrelationMatrixBuilder
Build a pairwise Pearson-correlation matrix of adapter APY histories to surface
undiversified positions (highly co-moving yields). Pure stdlib only.
Advisory/read-only. Atomic writes.
"""

from dataclasses import dataclass, field
from typing import List, Optional
import json
import time
import os
from pathlib import Path

DATA_FILE = Path("data/correlation_matrix_log.json")
MAX_ENTRIES = 100

# Correlation relationship thresholds.
HIGH_POS = 0.7
MOD_POS = 0.3
MOD_NEG = -0.3
HIGH_NEG = -0.7

# Diversification score thresholds (score = 1 - mean |correlation|).
DIV_WELL = 0.7
DIV_MODERATE = 0.4


@dataclass
class AdapterSeries:
    adapter_id: str
    apy_history: List[float]


@dataclass
class CorrelationPair:
    adapter_a: str
    adapter_b: str
    correlation: float          # -1..1, rounded 6dp (0.0 if undefined)
    relationship: str           # HIGH_POSITIVE/MODERATE_POSITIVE/WEAK/MODERATE_NEGATIVE/HIGH_NEGATIVE


@dataclass
class CorrelationReport:
    num_adapters: int
    pairs: List[CorrelationPair]
    mean_abs_correlation: float
    most_correlated_pair: Optional[CorrelationPair]
    diversification_score: float     # 0..1, higher = better diversified
    diversification_level: str       # WELL_DIVERSIFIED/MODERATE/POOR/UNKNOWN
    advisory: List[str] = field(default_factory=list)
    generated_at: str = ""


class CorrelationMatrixBuilder:
    """
    Builds pairwise APY correlations across adapters.
    Advisory only — never modifies allocator, risk, or execution domains.
    """

    # ------------------------------------------------------------------
    # Statistics helpers
    # ------------------------------------------------------------------

    @staticmethod
    def pearson(xs: List[float], ys: List[float]) -> float:
        """
        Pearson correlation coefficient over equal-length series, truncated to the
        shorter length. Returns 0.0 when fewer than 2 overlapping points or when
        either series has zero variance. Clamped to [-1, 1], rounded 6dp.
        """
        n = min(len(xs), len(ys))
        if n < 2:
            return 0.0
        xs = xs[:n]
        ys = ys[:n]
        mean_x = sum(xs) / n
        mean_y = sum(ys) / n
        cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
        var_x = sum((x - mean_x) ** 2 for x in xs)
        var_y = sum((y - mean_y) ** 2 for y in ys)
        if var_x <= 0 or var_y <= 0:
            return 0.0
        r = cov / ((var_x ** 0.5) * (var_y ** 0.5))
        r = max(-1.0, min(1.0, r))
        return round(r, 6)

    @staticmethod
    def _relationship(r: float) -> str:
        if r >= HIGH_POS:
            return "HIGH_POSITIVE"
        if r >= MOD_POS:
            return "MODERATE_POSITIVE"
        if r > MOD_NEG:
            return "WEAK"
        if r > HIGH_NEG:
            return "MODERATE_NEGATIVE"
        return "HIGH_NEGATIVE"

    @staticmethod
    def _classify_diversification(score: float) -> str:
        if score >= DIV_WELL:
            return "WELL_DIVERSIFIED"
        if score >= DIV_MODERATE:
            return "MODERATE"
        return "POOR"

    @staticmethod
    def _build_advisory(
        level: str, most_correlated: Optional[CorrelationPair]
    ) -> List[str]:
        out: List[str] = []
        if level == "POOR":
            out.append(
                "POOR diversification — adapter yields move together; a single market "
                "shock could hit the whole portfolio"
            )
        elif level == "MODERATE":
            out.append(
                "Moderate diversification — consider adding uncorrelated yield sources"
            )
        if most_correlated and most_correlated.relationship == "HIGH_POSITIVE":
            out.append(
                f"'{most_correlated.adapter_a}' and '{most_correlated.adapter_b}' are "
                f"highly correlated ({most_correlated.correlation:.2f}) — they offer "
                f"little diversification benefit together"
            )
        return out

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build(self, series_list: List[AdapterSeries]) -> CorrelationReport:
        """Build a CorrelationReport over a list of adapter APY series."""
        generated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        if len(series_list) < 2:
            return CorrelationReport(
                num_adapters=len(series_list),
                pairs=[],
                mean_abs_correlation=0.0,
                most_correlated_pair=None,
                diversification_score=1.0,
                diversification_level="UNKNOWN",
                advisory=["Need at least 2 adapters to compute correlations"],
                generated_at=generated_at,
            )

        pairs: List[CorrelationPair] = []
        for i in range(len(series_list)):
            for j in range(i + 1, len(series_list)):
                a = series_list[i]
                b = series_list[j]
                r = self.pearson(a.apy_history, b.apy_history)
                pairs.append(
                    CorrelationPair(
                        adapter_a=a.adapter_id,
                        adapter_b=b.adapter_id,
                        correlation=r,
                        relationship=self._relationship(r),
                    )
                )

        mean_abs = (
            round(sum(abs(p.correlation) for p in pairs) / len(pairs), 6)
            if pairs
            else 0.0
        )
        most_correlated = max(pairs, key=lambda p: p.correlation) if pairs else None
        score = round(max(0.0, min(1.0, 1.0 - mean_abs)), 6)
        level = self._classify_diversification(score)
        advisory = self._build_advisory(level, most_correlated)

        return CorrelationReport(
            num_adapters=len(series_list),
            pairs=pairs,
            mean_abs_correlation=mean_abs,
            most_correlated_pair=most_correlated,
            diversification_score=score,
            diversification_level=level,
            advisory=advisory,
            generated_at=generated_at,
        )

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save_report(
        self, report: CorrelationReport, data_file: Path = DATA_FILE
    ) -> None:
        """Append a report to a ring-buffer JSON (max MAX_ENTRIES). Atomic write."""
        data_file = Path(data_file)
        existing = self.load_history(data_file)

        mc = report.most_correlated_pair
        entry = {
            "timestamp": report.generated_at
            or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "num_adapters": report.num_adapters,
            "mean_abs_correlation": report.mean_abs_correlation,
            "diversification_score": report.diversification_score,
            "diversification_level": report.diversification_level,
            "most_correlated_pair": (
                {
                    "adapter_a": mc.adapter_a,
                    "adapter_b": mc.adapter_b,
                    "correlation": mc.correlation,
                    "relationship": mc.relationship,
                }
                if mc
                else None
            ),
            "pairs": [
                {
                    "adapter_a": p.adapter_a,
                    "adapter_b": p.adapter_b,
                    "correlation": p.correlation,
                    "relationship": p.relationship,
                }
                for p in report.pairs
            ],
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
    builder = CorrelationMatrixBuilder()
    series = [
        AdapterSeries("aave_usdc", [4.1, 4.3, 4.2, 4.5, 4.4]),
        AdapterSeries("compound_usdc", [4.0, 4.2, 4.1, 4.4, 4.3]),
        AdapterSeries("curve_3pool", [6.0, 5.5, 6.2, 5.1, 5.8]),
    ]
    report = builder.build(series)
    print(f"Adapters:               {report.num_adapters}")
    print(f"Mean |correlation|:     {report.mean_abs_correlation:.3f}")
    print(f"Diversification score:  {report.diversification_score:.3f}")
    print(f"Diversification level:  {report.diversification_level}")
    for p in report.pairs:
        print(f"  {p.adapter_a} ~ {p.adapter_b}: "
              f"{p.correlation:+.3f} ({p.relationship})")
    for line in report.advisory:
        print(f"  - {line}")


if __name__ == "__main__":
    _demo()
