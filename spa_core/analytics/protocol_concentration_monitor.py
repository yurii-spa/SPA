"""
MP-678: ProtocolConcentrationMonitor
Monitor portfolio concentration risk across DeFi protocols. Computes per-protocol
exposure, the Herfindahl-Hirschman Index (HHI), the effective number of protocols,
and flags single-protocol cap breaches.
Pure stdlib only. Advisory/read-only. Atomic writes.
"""

from dataclasses import dataclass, field
from typing import List, Optional
import json
import time
import os
from pathlib import Path

DATA_FILE = Path("data/protocol_concentration_log.json")
MAX_ENTRIES = 100

# Default single-protocol exposure cap (% of portfolio).
DEFAULT_SINGLE_PROTOCOL_CAP_PCT = 25.0

# HHI thresholds (market shares expressed as percentages, so HHI range 0..10000).
HHI_DIVERSIFIED = 1500.0
HHI_MODERATE = 2500.0
HHI_CONCENTRATED = 5000.0


@dataclass
class PositionExposure:
    protocol: str
    value_usd: float


@dataclass
class ConcentrationReport:
    total_value_usd: float
    num_protocols: int
    hhi: float                       # 0..10000
    effective_protocols: float       # 1 / sum(weight_fraction^2)
    max_exposure_protocol: Optional[str]
    max_exposure_pct: float          # 0..100
    concentration_level: str         # DIVERSIFIED/MODERATE/CONCENTRATED/CRITICAL/UNKNOWN
    breaches: List[str]              # protocols exceeding the cap
    advisory: List[str] = field(default_factory=list)
    generated_at: str = ""


class ProtocolConcentrationMonitor:
    """
    Computes concentration metrics for a basket of protocol positions.
    Advisory only — never modifies allocator, risk, or execution domains.
    """

    # ------------------------------------------------------------------
    # Calculation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _aggregate(exposures: List[PositionExposure]) -> dict:
        """Sum positive value per protocol. Non-positive values are ignored."""
        agg: dict = {}
        for e in exposures:
            if e.value_usd <= 0:
                continue
            agg[e.protocol] = agg.get(e.protocol, 0.0) + e.value_usd
        return agg

    @staticmethod
    def _hhi(weights_pct: List[float]) -> float:
        """HHI = sum of squared percentage shares. Rounded to 6dp."""
        return round(sum(w * w for w in weights_pct), 6)

    @staticmethod
    def _effective_protocols(weights_frac: List[float]) -> float:
        """Effective number of protocols = 1 / sum(fraction^2). Rounded to 6dp."""
        denom = sum(w * w for w in weights_frac)
        if denom <= 0:
            return 0.0
        return round(1.0 / denom, 6)

    @staticmethod
    def _classify(hhi: float) -> str:
        if hhi < HHI_DIVERSIFIED:
            return "DIVERSIFIED"
        if hhi < HHI_MODERATE:
            return "MODERATE"
        if hhi < HHI_CONCENTRATED:
            return "CONCENTRATED"
        return "CRITICAL"

    @staticmethod
    def _build_advisory(
        level: str,
        breaches: List[str],
        max_protocol: Optional[str],
        max_pct: float,
        cap_pct: float,
    ) -> List[str]:
        out: List[str] = []
        if level == "CRITICAL":
            out.append(
                "CRITICAL concentration — portfolio dominated by too few protocols; "
                "diversify to reduce single-point-of-failure risk"
            )
        elif level == "CONCENTRATED":
            out.append(
                "Portfolio is concentrated — consider spreading capital across more protocols"
            )
        for p in breaches:
            out.append(
                f"Protocol '{p}' exceeds the {cap_pct:.0f}% single-protocol cap"
            )
        if max_protocol and not breaches and level in ("DIVERSIFIED", "MODERATE"):
            out.append(
                f"Largest exposure '{max_protocol}' at {max_pct:.1f}% is within the "
                f"{cap_pct:.0f}% cap"
            )
        return out

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(
        self,
        exposures: List[PositionExposure],
        single_protocol_cap_pct: float = DEFAULT_SINGLE_PROTOCOL_CAP_PCT,
    ) -> ConcentrationReport:
        """Compute a ConcentrationReport for a basket of protocol exposures."""
        agg = self._aggregate(exposures)
        total = sum(agg.values())
        generated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        if not agg or total <= 0:
            return ConcentrationReport(
                total_value_usd=0.0,
                num_protocols=0,
                hhi=0.0,
                effective_protocols=0.0,
                max_exposure_protocol=None,
                max_exposure_pct=0.0,
                concentration_level="UNKNOWN",
                breaches=[],
                advisory=["No positive exposures to analyze"],
                generated_at=generated_at,
            )

        pct_map = {p: (v / total) * 100.0 for p, v in agg.items()}
        frac_list = [v / total for v in agg.values()]
        pct_list = list(pct_map.values())

        hhi = self._hhi(pct_list)
        effective = self._effective_protocols(frac_list)
        max_protocol = max(pct_map, key=lambda p: pct_map[p])
        max_pct = round(pct_map[max_protocol], 6)
        level = self._classify(hhi)
        breaches = sorted(
            [p for p, pct in pct_map.items() if pct > single_protocol_cap_pct]
        )
        advisory = self._build_advisory(
            level, breaches, max_protocol, max_pct, single_protocol_cap_pct
        )

        return ConcentrationReport(
            total_value_usd=round(total, 6),
            num_protocols=len(agg),
            hhi=hhi,
            effective_protocols=effective,
            max_exposure_protocol=max_protocol,
            max_exposure_pct=max_pct,
            concentration_level=level,
            breaches=breaches,
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
            "total_value_usd": report.total_value_usd,
            "num_protocols": report.num_protocols,
            "hhi": report.hhi,
            "effective_protocols": report.effective_protocols,
            "max_exposure_protocol": report.max_exposure_protocol,
            "max_exposure_pct": report.max_exposure_pct,
            "concentration_level": report.concentration_level,
            "breaches": report.breaches,
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
    monitor = ProtocolConcentrationMonitor()
    exposures = [
        PositionExposure("aave_v3", 60_000.0),
        PositionExposure("compound_v3", 20_000.0),
        PositionExposure("curve", 15_000.0),
        PositionExposure("morpho", 5_000.0),
    ]
    report = monitor.analyze(exposures)
    print(f"Total value:          ${report.total_value_usd:,.0f}")
    print(f"Protocols:            {report.num_protocols}")
    print(f"HHI:                  {report.hhi:.1f}")
    print(f"Effective protocols:  {report.effective_protocols:.2f}")
    print(f"Max exposure:         {report.max_exposure_protocol} "
          f"({report.max_exposure_pct:.1f}%)")
    print(f"Concentration level:  {report.concentration_level}")
    print(f"Breaches:             {report.breaches}")
    for line in report.advisory:
        print(f"  - {line}")


if __name__ == "__main__":
    _demo()
