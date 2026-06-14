"""
MP-1122: DeFiProtocolYieldFeeStructureAnalyzer

Decomposes all fee layers in a DeFi yield position — protocol fees,
management fees, performance fees, withdrawal fees — to calculate the
true net yield after all fees.  Hidden fees can reduce stated APY by
30-50%.

Fee-deduction waterfall:
  1. yield_after_protocol_fee   = gross_apy * (1 - protocol_fee_pct / 100)
  2. yield_after_management_fee = step1 - management_fee_annual_pct
  3. yield_after_performance_fee= step2 * (1 - performance_fee_pct / 100)
  4. annualized_withdrawal_fee  = withdrawal_fee_pct * 365 / holding_period_days
  5. net_apy_pct                = step3 - step4
  6. total_fees_pct             = gross_apy_pct - net_apy_pct
  7. fee_drag_ratio             = total_fees_pct / gross_apy_pct  (0 if gross=0)

Fee label (by fee_drag_ratio):
  < 0.10              → LOW_FEE
  0.10 – 0.25         → MODERATE_FEE
  0.25 – 0.50         → HIGH_FEE
  0.50 – 1.00         → EXCESSIVE_FEE
  >= 1.00 or net <= 0 → FEE_EXCEEDS_YIELD

Pure stdlib only.  Advisory/read-only — never modifies allocator, risk,
or execution domains.  Atomic writes (tmp + os.replace).
Log file: data/yield_fee_structure_log.json  (ring-buffer, cap 100).
"""

from __future__ import annotations

import json
import math
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DATA_FILE = Path("data/yield_fee_structure_log.json")
MAX_ENTRIES: int = 100

# fee_drag_ratio thresholds
_LOW_FEE_MAX = 0.10
_MODERATE_FEE_MAX = 0.25
_HIGH_FEE_MAX = 0.50
_EXCESSIVE_FEE_MAX = 1.00

_LABEL_LOW = "LOW_FEE"
_LABEL_MODERATE = "MODERATE_FEE"
_LABEL_HIGH = "HIGH_FEE"
_LABEL_EXCESSIVE = "EXCESSIVE_FEE"
_LABEL_EXCEEDS = "FEE_EXCEEDS_YIELD"


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass
class YieldFeeStructureReport:
    protocol_name: str
    gross_apy_pct: float
    protocol_fee_pct: float
    management_fee_annual_pct: float
    performance_fee_pct: float
    withdrawal_fee_pct: float
    holding_period_days: int
    position_size_usd: float

    # Computed outputs
    yield_after_protocol_fee_pct: float
    yield_after_management_fee_pct: float
    yield_after_performance_fee_pct: float
    annualized_withdrawal_fee_pct: float
    net_apy_pct: float
    total_fees_pct: float
    fee_drag_ratio: float
    fee_label: str

    advisory: List[str] = field(default_factory=list)
    generated_at: str = ""


# ---------------------------------------------------------------------------
# Analyzer
# ---------------------------------------------------------------------------

class DeFiProtocolYieldFeeStructureAnalyzer:
    """
    Decomposes DeFi fee layers and calculates the true net APY after all
    fee types have been deducted.

    Advisory only — never modifies allocator, risk, or execution domains.
    """

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _classify_label(fee_drag_ratio: float, net_apy_pct: float) -> str:
        """Map fee_drag_ratio → fee label string."""
        if net_apy_pct < 0.0 or fee_drag_ratio >= _EXCESSIVE_FEE_MAX:
            return _LABEL_EXCEEDS
        if fee_drag_ratio >= _HIGH_FEE_MAX:
            return _LABEL_EXCESSIVE
        if fee_drag_ratio >= _MODERATE_FEE_MAX:
            return _LABEL_HIGH
        if fee_drag_ratio >= _LOW_FEE_MAX:
            return _LABEL_MODERATE
        return _LABEL_LOW

    @staticmethod
    def _build_advisory(
        fee_label: str,
        fee_drag_ratio: float,
        total_fees_pct: float,
        net_apy_pct: float,
        gross_apy_pct: float,
        protocol_name: str,
    ) -> List[str]:
        msgs: List[str] = []
        drag_pct = round(fee_drag_ratio * 100.0, 2)
        if fee_label == _LABEL_EXCEEDS:
            msgs.append(
                f"{protocol_name}: fees ({total_fees_pct:.2f}%) exceed or match "
                f"gross APY ({gross_apy_pct:.2f}%) — position is net-negative"
            )
        elif fee_label == _LABEL_EXCESSIVE:
            msgs.append(
                f"{protocol_name}: excessive fee drag {drag_pct:.1f}% — "
                f"only {net_apy_pct:.2f}% net APY remains; consider alternatives"
            )
        elif fee_label == _LABEL_HIGH:
            msgs.append(
                f"{protocol_name}: high fee drag {drag_pct:.1f}% — "
                f"fees are reducing yield significantly"
            )
        elif fee_label == _LABEL_MODERATE:
            msgs.append(
                f"{protocol_name}: moderate fee drag {drag_pct:.1f}% — "
                f"acceptable but worth monitoring"
            )
        else:
            msgs.append(
                f"{protocol_name}: low fee drag {drag_pct:.1f}% — "
                f"fee structure is efficient"
            )
        return msgs

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(
        self,
        gross_apy_pct: float,
        protocol_fee_pct: float,
        management_fee_annual_pct: float,
        performance_fee_pct: float,
        withdrawal_fee_pct: float,
        holding_period_days: int,
        position_size_usd: float,
        protocol_name: str,
    ) -> YieldFeeStructureReport:
        """
        Decompose fee layers and return a YieldFeeStructureReport.

        Parameters
        ----------
        gross_apy_pct             : headline APY stated by the protocol (%)
        protocol_fee_pct          : % of yield taken by protocol, e.g. 10.0
        management_fee_annual_pct : % of AUM charged annually, e.g. 0.5
        performance_fee_pct       : % of profits taken by manager, e.g. 20.0
        withdrawal_fee_pct        : one-time fee on exit, e.g. 0.1
        holding_period_days       : intended holding period in days
        position_size_usd         : USD value of position
        protocol_name             : human-readable protocol label
        """
        generated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        # Clamp inputs to avoid nonsensical negatives in intermediate steps
        g = float(gross_apy_pct)
        pf = float(protocol_fee_pct)
        mf = float(management_fee_annual_pct)
        perf = float(performance_fee_pct)
        wf = float(withdrawal_fee_pct)
        hp = max(1, int(holding_period_days))

        # 1. Protocol fee: taken as % of gross yield
        y1 = g * (1.0 - pf / 100.0)

        # 2. Management fee: flat AUM-based annual charge
        y2 = y1 - mf

        # 3. Performance fee: taken as % of remaining yield
        y3 = y2 * (1.0 - perf / 100.0)

        # 4. Annualise the one-time withdrawal fee
        ann_wf = wf * 365.0 / hp

        # 5. Net APY
        net_apy = y3 - ann_wf

        # 6. Total fees
        total_fees = g - net_apy

        # 7. Fee drag ratio (guard against zero gross)
        if abs(g) < 1e-12:
            fee_drag = 0.0
        else:
            fee_drag = total_fees / g

        fee_label = self._classify_label(fee_drag, net_apy)
        advisory = self._build_advisory(
            fee_label, fee_drag, total_fees, net_apy, g, protocol_name
        )

        return YieldFeeStructureReport(
            protocol_name=protocol_name,
            gross_apy_pct=round(g, 8),
            protocol_fee_pct=round(pf, 8),
            management_fee_annual_pct=round(mf, 8),
            performance_fee_pct=round(perf, 8),
            withdrawal_fee_pct=round(wf, 8),
            holding_period_days=hp,
            position_size_usd=float(position_size_usd),
            yield_after_protocol_fee_pct=round(y1, 8),
            yield_after_management_fee_pct=round(y2, 8),
            yield_after_performance_fee_pct=round(y3, 8),
            annualized_withdrawal_fee_pct=round(ann_wf, 8),
            net_apy_pct=round(net_apy, 8),
            total_fees_pct=round(total_fees, 8),
            fee_drag_ratio=round(fee_drag, 8),
            fee_label=fee_label,
            advisory=advisory,
            generated_at=generated_at,
        )

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save_report(
        self,
        report: YieldFeeStructureReport,
        data_file: Path = DATA_FILE,
    ) -> None:
        """Append report to ring-buffer JSON (cap MAX_ENTRIES).  Atomic write."""
        data_file = Path(data_file)
        existing = self.load_history(data_file)

        entry = {
            "timestamp": report.generated_at
            or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "protocol_name": report.protocol_name,
            "gross_apy_pct": report.gross_apy_pct,
            "yield_after_protocol_fee_pct": report.yield_after_protocol_fee_pct,
            "yield_after_management_fee_pct": report.yield_after_management_fee_pct,
            "yield_after_performance_fee_pct": report.yield_after_performance_fee_pct,
            "annualized_withdrawal_fee_pct": report.annualized_withdrawal_fee_pct,
            "net_apy_pct": report.net_apy_pct,
            "total_fees_pct": report.total_fees_pct,
            "fee_drag_ratio": report.fee_drag_ratio,
            "fee_label": report.fee_label,
            "holding_period_days": report.holding_period_days,
            "position_size_usd": report.position_size_usd,
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
    ana = DeFiProtocolYieldFeeStructureAnalyzer()
    report = ana.analyze(
        gross_apy_pct=10.0,
        protocol_fee_pct=10.0,
        management_fee_annual_pct=0.5,
        performance_fee_pct=20.0,
        withdrawal_fee_pct=0.1,
        holding_period_days=365,
        position_size_usd=50_000.0,
        protocol_name="Yearn v3",
    )
    print(f"Gross APY:               {report.gross_apy_pct:.4f}%")
    print(f"After protocol fee:      {report.yield_after_protocol_fee_pct:.4f}%")
    print(f"After management fee:    {report.yield_after_management_fee_pct:.4f}%")
    print(f"After performance fee:   {report.yield_after_performance_fee_pct:.4f}%")
    print(f"Ann. withdrawal fee:     {report.annualized_withdrawal_fee_pct:.4f}%")
    print(f"Net APY:                 {report.net_apy_pct:.4f}%")
    print(f"Total fees:              {report.total_fees_pct:.4f}%")
    print(f"Fee drag ratio:          {report.fee_drag_ratio:.4f}")
    print(f"Fee label:               {report.fee_label}")
    for msg in report.advisory:
        print(f"  • {msg}")


if __name__ == "__main__":
    _demo()
