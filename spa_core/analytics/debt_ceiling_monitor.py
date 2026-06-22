"""
MP-772: DebtCeilingMonitor
Monitors protocol debt ceilings and utilization.
Computes utilization_pct, headroom_usd, days_until_ceiling,
and breach_risk (LOW / MEDIUM / HIGH / IMMINENT).

Advisory/read-only. Pure stdlib only. Atomic JSON writes (tmp + os.replace).
Ring-buffer cap: 100 entries. Output: data/debt_ceiling_log.json.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

DATA_FILE = Path("data/debt_ceiling_log.json")
MAX_ENTRIES = 100

# Days-to-breach risk thresholds
_IMMINENT_DAYS: float = 7.0
_HIGH_DAYS: float = 30.0
_MEDIUM_DAYS: float = 90.0


# ─── Input / output dataclasses ──────────────────────────────────────────────

@dataclass
class ProtocolDebtInput:
    """Input descriptor for a single protocol's debt ceiling data."""
    protocol: str
    current_debt_usd: float
    debt_ceiling_usd: float
    debt_growth_rate_daily_pct: float  # daily debt growth as % of current debt


@dataclass
class ProtocolDebtReport:
    """Per-protocol computed report."""
    protocol: str
    current_debt_usd: float
    debt_ceiling_usd: float
    debt_growth_rate_daily_pct: float
    utilization_pct: float          # current / ceiling * 100
    headroom_usd: float             # max(0, ceiling - current)
    days_until_ceiling: float       # float('inf') when no growth; 0.0 when breached
    breach_risk: str                # LOW / MEDIUM / HIGH / IMMINENT


@dataclass
class DebtCeilingMonitorResult:
    """Aggregate result for one monitoring run."""
    timestamp: float
    protocols: List[ProtocolDebtReport]
    at_risk_protocols: List[str]    # protocols with breach_risk IMMINENT or HIGH
    portfolio_headroom_pct: float   # total_headroom / total_ceiling * 100
    total_current_debt_usd: float
    total_ceiling_usd: float
    total_headroom_usd: float


# ─── Pure computation functions (testable without I/O) ───────────────────────

def compute_utilization_pct(current_debt_usd: float,
                             debt_ceiling_usd: float) -> float:
    """
    utilization_pct = current / ceiling * 100.
    Returns 100.0 if ceiling <= 0 (treat as fully utilized).
    Returns 0.0 if current <= 0.
    """
    if debt_ceiling_usd <= 0:
        return 100.0
    if current_debt_usd <= 0:
        return 0.0
    return current_debt_usd / debt_ceiling_usd * 100.0


def compute_headroom_usd(current_debt_usd: float,
                          debt_ceiling_usd: float) -> float:
    """
    headroom_usd = max(0, ceiling - current).
    Never negative: if already breached, returns 0.0.
    """
    return max(0.0, debt_ceiling_usd - current_debt_usd)


def compute_days_until_ceiling(current_debt_usd: float,
                                debt_ceiling_usd: float,
                                debt_growth_rate_daily_pct: float) -> float:
    """
    days_until_ceiling = (ceiling - current) / (current * daily_growth_rate / 100).

    Special cases:
    - current >= ceiling  → 0.0  (already at or above ceiling)
    - growth_rate <= 0    → float('inf')  (no growth, ceiling never reached)
    - current <= 0        → float('inf')  (no debt, nothing to grow)
    """
    headroom = debt_ceiling_usd - current_debt_usd
    if headroom <= 0.0:
        return 0.0
    if debt_growth_rate_daily_pct <= 0.0 or current_debt_usd <= 0.0:
        return float("inf")
    daily_growth_usd = current_debt_usd * debt_growth_rate_daily_pct / 100.0
    if daily_growth_usd <= 0.0:
        return float("inf")
    return headroom / daily_growth_usd


def compute_breach_risk(days_until_ceiling: float) -> str:
    """
    Classify breach risk from days until ceiling:
      IMMINENT  : days < 7   (or already breached: days == 0)
      HIGH      : 7  <= days < 30
      MEDIUM    : 30 <= days < 90
      LOW       : 90 <= days (or inf — no growth)
    """
    if days_until_ceiling <= 0.0:
        return "IMMINENT"
    if days_until_ceiling < _IMMINENT_DAYS:
        return "IMMINENT"
    if days_until_ceiling < _HIGH_DAYS:
        return "HIGH"
    if days_until_ceiling < _MEDIUM_DAYS:
        return "MEDIUM"
    return "LOW"


def analyze_protocol(p: ProtocolDebtInput) -> ProtocolDebtReport:
    """Compute the full report for a single protocol."""
    util = compute_utilization_pct(p.current_debt_usd, p.debt_ceiling_usd)
    headroom = compute_headroom_usd(p.current_debt_usd, p.debt_ceiling_usd)
    days = compute_days_until_ceiling(
        p.current_debt_usd, p.debt_ceiling_usd, p.debt_growth_rate_daily_pct
    )
    risk = compute_breach_risk(days)
    return ProtocolDebtReport(
        protocol=p.protocol,
        current_debt_usd=p.current_debt_usd,
        debt_ceiling_usd=p.debt_ceiling_usd,
        debt_growth_rate_daily_pct=p.debt_growth_rate_daily_pct,
        utilization_pct=util,
        headroom_usd=headroom,
        days_until_ceiling=days,
        breach_risk=risk,
    )


# ─── Persistence helpers ─────────────────────────────────────────────────────

def _inf_to_none(v: float) -> Optional[float]:
    """Replace float('inf') with None for JSON serialization."""
    return None if v == float("inf") else v


def _result_to_dict(result: DebtCeilingMonitorResult) -> Dict[str, Any]:
    protocols_list = []
    for r in result.protocols:
        d = asdict(r)
        d["days_until_ceiling"] = _inf_to_none(d["days_until_ceiling"])
        protocols_list.append(d)
    return {
        "timestamp": result.timestamp,
        "protocols": protocols_list,
        "at_risk_protocols": result.at_risk_protocols,
        "portfolio_headroom_pct": result.portfolio_headroom_pct,
        "total_current_debt_usd": result.total_current_debt_usd,
        "total_ceiling_usd": result.total_ceiling_usd,
        "total_headroom_usd": result.total_headroom_usd,
    }


def load_history(data_file: Path = DATA_FILE) -> list:
    """Load ring-buffer list from disk; returns [] if file is missing or corrupt."""
    data_file = Path(data_file)
    if not data_file.exists():
        return []
    try:
        text = data_file.read_text().strip()
        if not text:
            return []
        return json.loads(text)
    except (json.JSONDecodeError, OSError):
        return []


def save_result(result: DebtCeilingMonitorResult,
                data_file: Path = DATA_FILE) -> None:
    """Append result to ring-buffer JSON log (capped at MAX_ENTRIES). Atomic write."""
    data_file = Path(data_file)
    data_file.parent.mkdir(parents=True, exist_ok=True)
    history = load_history(data_file)
    history.append(_result_to_dict(result))
    if len(history) > MAX_ENTRIES:
        history = history[-MAX_ENTRIES:]
    tmp = data_file.with_suffix(".tmp")
    tmp.write_text(json.dumps(history, indent=2))
    os.replace(tmp, data_file)


# ─── Main monitor class ───────────────────────────────────────────────────────

class DebtCeilingMonitor:
    """
    MP-772: Monitors protocol debt ceilings and utilization.

    Usage::

        monitor = DebtCeilingMonitor()
        protocols = [
            ProtocolDebtInput("Aave V3", 40_000_000, 100_000_000, 0.5),
            ProtocolDebtInput("Compound V3", 95_000_000, 100_000_000, 2.0),
        ]
        result = monitor.monitor(protocols)
        at_risk = monitor.get_at_risk_protocols()
        headroom = monitor.get_portfolio_headroom_pct()
    """

    def __init__(self, data_file: Path = DATA_FILE):
        self.data_file = Path(data_file)
        self._last_result: Optional[DebtCeilingMonitorResult] = None

    # ── Public API ────────────────────────────────────────────────────────────

    def monitor(self, protocols: List[ProtocolDebtInput]) -> DebtCeilingMonitorResult:
        """
        Analyse all protocol debt ceilings and persist to ring-buffer log.
        Accepts an empty list (returns zero-value result).

        :param protocols: list of ProtocolDebtInput descriptors
        :returns: DebtCeilingMonitorResult with per-protocol reports + aggregates
        """
        reports = [analyze_protocol(p) for p in protocols]

        at_risk = [
            r.protocol for r in reports
            if r.breach_risk in ("IMMINENT", "HIGH")
        ]

        total_current = sum(r.current_debt_usd for r in reports)
        total_ceiling = sum(r.debt_ceiling_usd for r in reports)
        total_headroom = sum(r.headroom_usd for r in reports)

        portfolio_headroom_pct = (
            (total_headroom / total_ceiling * 100.0) if total_ceiling > 0 else 0.0
        )

        result = DebtCeilingMonitorResult(
            timestamp=time.time(),
            protocols=reports,
            at_risk_protocols=at_risk,
            portfolio_headroom_pct=portfolio_headroom_pct,
            total_current_debt_usd=total_current,
            total_ceiling_usd=total_ceiling,
            total_headroom_usd=total_headroom,
        )
        self._last_result = result
        save_result(result, self.data_file)
        return result

    def get_at_risk_protocols(self) -> List[str]:
        """
        Return list of protocol names with breach_risk IMMINENT or HIGH
        from the most recent monitor() call. Returns [] if never called.
        """
        if self._last_result is None:
            return []
        return list(self._last_result.at_risk_protocols)

    def get_portfolio_headroom_pct(self) -> float:
        """
        Return total headroom as % of total ceiling from the most recent
        monitor() call. Returns 0.0 if never called.
        """
        if self._last_result is None:
            return 0.0
        return self._last_result.portfolio_headroom_pct


# ─── CLI entry-point ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="MP-772 DebtCeilingMonitor — run with sample data"
    )
    parser.add_argument("--data-dir", default="data",
                        help="Directory for output JSON (default: data/)")
    args = parser.parse_args()

    data_file = Path(args.data_dir) / "debt_ceiling_log.json"
    mon = DebtCeilingMonitor(data_file=data_file)

    sample = [
        ProtocolDebtInput("Aave V3", 40_000_000, 100_000_000, 0.5),
        ProtocolDebtInput("Compound V3", 95_000_000, 100_000_000, 2.0),
        ProtocolDebtInput("Morpho Blue", 8_000_000, 10_000_000, 5.0),
        ProtocolDebtInput("Euler V2", 500_000, 50_000_000, 0.1),
    ]
    result = mon.monitor(sample)

    print("\n=== Debt Ceiling Monitor (MP-772) ===")
    print(f"Portfolio headroom: {result.portfolio_headroom_pct:.1f}%")
    print(f"At-risk protocols : {result.at_risk_protocols or 'none'}")
    print()
    for r in result.protocols:
        days_str = (
            f"{r.days_until_ceiling:.1f}d"
            if r.days_until_ceiling != float("inf")
            else "∞"
        )
        print(
            f"  {r.protocol:20s}  util={r.utilization_pct:5.1f}%  "
            f"headroom=${r.headroom_usd:>12,.0f}  "
            f"days={days_str:>8}  risk={r.breach_risk}"
        )
    print(f"\nSaved → {data_file}")
