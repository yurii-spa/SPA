"""
MP-747: ProtocolFeeAnalyzer
Analyzes DeFi protocol fee structures — entry/exit fees, management fees,
performance fees — to compute true net yield after all costs and compare
protocols on a fee-adjusted basis.
Advisory/read-only. Pure stdlib. Atomic JSON writes.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import List

# ── Data directory (repo-relative) ──────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(os.path.dirname(_HERE))
_DATA_DIR = os.path.join(_REPO_ROOT, "data")
_LOG_FILE = os.path.join(_DATA_DIR, "protocol_fee_log.json")

_RING_BUFFER_CAP = 100


# ── Core dataclasses ─────────────────────────────────────────────────────────

@dataclass
class FeeStructure:
    protocol: str
    asset: str

    gross_apy_pct: float            # advertised APY before fees

    # Fee types (all in %)
    entry_fee_pct: float            # one-time cost on deposit
    exit_fee_pct: float             # one-time cost on withdrawal
    management_fee_pct: float       # annual % of AUM
    performance_fee_pct: float      # % of profits above hurdle

    hurdle_rate_pct: float          # minimum return before performance fee applies

    # Computed
    effective_performance_fee_pct: float   # actual performance fee charged on profits
    amortized_entry_exit_pct: float        # (entry_fee + exit_fee) / 100

    net_apy_pct: float              # final net APY after all fees
    total_fee_drag_pct: float       # gross_apy - net_apy
    fee_efficiency_pct: float       # net_apy / gross_apy * 100 if gross > 0 else 0

    fee_label: str                  # "LOW_FEE" | "MODERATE_FEE" | "HIGH_FEE"
    recommendation: str


@dataclass
class FeeAnalysisResult:
    protocols: List[FeeStructure]

    # Rankings
    lowest_fee_protocol: str        # min total_fee_drag_pct
    highest_net_apy_protocol: str   # max net_apy_pct

    avg_gross_apy_pct: float
    avg_net_apy_pct: float
    avg_fee_drag_pct: float

    low_fee_count: int              # protocols with fee_label=LOW_FEE

    market_fee_label: str           # "EFFICIENT" | "MODERATE" | "COSTLY"

    recommendation_summary: str
    saved_to: str


# ── Pure calculation functions ────────────────────────────────────────────────

def compute_performance_fee(
    gross_apy: float,
    hurdle_rate: float,
    perf_fee_pct: float,
) -> float:
    """
    Performance fee applied only when gross_apy > hurdle_rate.
    Returns (gross_apy - hurdle_rate) * perf_fee_pct / 100, else 0.
    """
    if gross_apy > hurdle_rate:
        return (gross_apy - hurdle_rate) * perf_fee_pct / 100.0
    return 0.0


def compute_amortized_entry_exit(entry_fee: float, exit_fee: float) -> float:
    """(entry_fee + exit_fee) / 100 — amortized over 1 year."""
    return (entry_fee + exit_fee) / 100.0


def compute_net_apy(
    gross: float,
    management_fee: float,
    eff_perf_fee: float,
    entry_fee: float,
    exit_fee: float,
) -> float:
    """
    net_apy = gross - management_fee - eff_perf_fee - (entry_fee + exit_fee)/100
    """
    return gross - management_fee - eff_perf_fee - compute_amortized_entry_exit(entry_fee, exit_fee)


def fee_label(drag: float) -> str:
    """Classify total fee drag."""
    if drag < 0.5:
        return "LOW_FEE"
    if drag <= 2.0:
        return "MODERATE_FEE"
    return "HIGH_FEE"


def fee_efficiency(net_apy: float, gross_apy: float) -> float:
    """net_apy / gross_apy * 100 if gross_apy > 0 else 0."""
    if gross_apy <= 0.0:
        return 0.0
    return net_apy / gross_apy * 100.0


def _build_recommendation(label: str) -> str:
    if label == "HIGH_FEE":
        return "High fee drag. Verify net yield meets your return targets."
    if label == "LOW_FEE":
        return "Efficient fee structure. Good value."
    return "Moderate fees. Compare against net APY."


def analyze_protocol(
    protocol: str,
    asset: str,
    gross_apy: float,
    entry_fee: float,
    exit_fee: float,
    management_fee: float,
    performance_fee: float,
    hurdle_rate: float,
) -> FeeStructure:
    """Analyze fee structure for a single protocol."""
    eff_perf = compute_performance_fee(gross_apy, hurdle_rate, performance_fee)
    amortized = compute_amortized_entry_exit(entry_fee, exit_fee)
    net = compute_net_apy(gross_apy, management_fee, eff_perf, entry_fee, exit_fee)
    drag = gross_apy - net
    efficiency = fee_efficiency(net, gross_apy)
    label = fee_label(drag)
    rec = _build_recommendation(label)

    return FeeStructure(
        protocol=protocol,
        asset=asset,
        gross_apy_pct=gross_apy,
        entry_fee_pct=entry_fee,
        exit_fee_pct=exit_fee,
        management_fee_pct=management_fee,
        performance_fee_pct=performance_fee,
        hurdle_rate_pct=hurdle_rate,
        effective_performance_fee_pct=eff_perf,
        amortized_entry_exit_pct=amortized,
        net_apy_pct=net,
        total_fee_drag_pct=drag,
        fee_efficiency_pct=efficiency,
        fee_label=label,
        recommendation=rec,
    )


def analyze_market(protocols_data: List[dict]) -> FeeAnalysisResult:
    """
    Analyze fee structures across multiple protocols.

    Each dict must have: protocol, asset, gross_apy_pct, entry_fee_pct,
    exit_fee_pct, management_fee_pct, performance_fee_pct, hurdle_rate_pct.
    """
    if not protocols_data:
        raise ValueError("protocols_data must not be empty")

    structs = [
        analyze_protocol(
            protocol=d["protocol"],
            asset=d["asset"],
            gross_apy=d["gross_apy_pct"],
            entry_fee=d["entry_fee_pct"],
            exit_fee=d["exit_fee_pct"],
            management_fee=d["management_fee_pct"],
            performance_fee=d["performance_fee_pct"],
            hurdle_rate=d["hurdle_rate_pct"],
        )
        for d in protocols_data
    ]

    lowest_fee_s = min(structs, key=lambda s: s.total_fee_drag_pct)
    highest_net_s = max(structs, key=lambda s: s.net_apy_pct)

    avg_gross = sum(s.gross_apy_pct for s in structs) / len(structs)
    avg_net = sum(s.net_apy_pct for s in structs) / len(structs)
    avg_drag = sum(s.total_fee_drag_pct for s in structs) / len(structs)
    low_fee_n = sum(1 for s in structs if s.fee_label == "LOW_FEE")

    if avg_drag < 0.5:
        mkt_label = "EFFICIENT"
    elif avg_drag <= 2.0:
        mkt_label = "MODERATE"
    else:
        mkt_label = "COSTLY"

    if low_fee_n == len(structs):
        summary = (
            f"All {len(structs)} protocols have efficient fee structures. "
            f"Best net APY at {highest_net_s.protocol} ({highest_net_s.net_apy_pct:.2f}%)."
        )
    elif low_fee_n == 0:
        summary = (
            f"No low-fee protocols found. "
            f"Lowest drag at {lowest_fee_s.protocol} "
            f"({lowest_fee_s.total_fee_drag_pct:.2f}% drag)."
        )
    else:
        summary = (
            f"{low_fee_n}/{len(structs)} protocols are low-fee. "
            f"Best net APY at {highest_net_s.protocol} ({highest_net_s.net_apy_pct:.2f}%). "
            f"Lowest fee drag at {lowest_fee_s.protocol} "
            f"({lowest_fee_s.total_fee_drag_pct:.2f}%)."
        )

    return FeeAnalysisResult(
        protocols=structs,
        lowest_fee_protocol=lowest_fee_s.protocol,
        highest_net_apy_protocol=highest_net_s.protocol,
        avg_gross_apy_pct=avg_gross,
        avg_net_apy_pct=avg_net,
        avg_fee_drag_pct=avg_drag,
        low_fee_count=low_fee_n,
        market_fee_label=mkt_label,
        recommendation_summary=summary,
        saved_to="",
    )


# ── Persistence ───────────────────────────────────────────────────────────────

def _result_to_dict(result: FeeAnalysisResult) -> dict:
    d = asdict(result)
    d["timestamp"] = datetime.now(timezone.utc).isoformat()
    return d


def load_history(log_file: str = _LOG_FILE) -> list:
    """Load historical fee analysis log."""
    if not os.path.exists(log_file):
        return []
    with open(log_file, "r", encoding="utf-8") as fh:
        return json.load(fh)


def save_results(result: FeeAnalysisResult, log_file: str = _LOG_FILE) -> str:
    """
    Append result to ring-buffer log (cap=100). Atomic write via tmp+replace.
    Returns the log file path.
    """
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    history = load_history(log_file)
    history.append(_result_to_dict(result))
    if len(history) > _RING_BUFFER_CAP:
        history = history[-_RING_BUFFER_CAP:]

    dir_ = os.path.dirname(log_file)
    fd, tmp_path = tempfile.mkstemp(dir=dir_, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(history, fh, indent=2)
        os.replace(tmp_path, log_file)
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise

    return log_file


# ── CLI ───────────────────────────────────────────────────────────────────────

def _demo_run() -> None:  # pragma: no cover
    """Quick smoke-test with hard-coded sample data."""
    sample = [
        {
            "protocol": "Aave V3", "asset": "USDC",
            "gross_apy_pct": 5.0, "entry_fee_pct": 0.0, "exit_fee_pct": 0.0,
            "management_fee_pct": 0.0, "performance_fee_pct": 0.0, "hurdle_rate_pct": 0.0,
        },
        {
            "protocol": "Yearn V3", "asset": "USDC",
            "gross_apy_pct": 8.0, "entry_fee_pct": 0.0, "exit_fee_pct": 0.0,
            "management_fee_pct": 0.5, "performance_fee_pct": 10.0, "hurdle_rate_pct": 3.0,
        },
        {
            "protocol": "Convex", "asset": "USDC",
            "gross_apy_pct": 12.0, "entry_fee_pct": 0.1, "exit_fee_pct": 0.1,
            "management_fee_pct": 1.0, "performance_fee_pct": 20.0, "hurdle_rate_pct": 5.0,
        },
    ]
    result = analyze_market(sample)
    print("=== ProtocolFeeAnalyzer Demo ===")
    print(f"Market label   : {result.market_fee_label}")
    print(f"Lowest fee     : {result.lowest_fee_protocol}")
    print(f"Best net APY   : {result.highest_net_apy_protocol}")
    print(f"Avg fee drag   : {result.avg_fee_drag_pct:.2f}%")
    print(f"Summary        : {result.recommendation_summary}")
    for p in result.protocols:
        print(f"  {p.protocol:12s} gross={p.gross_apy_pct:.1f}% net={p.net_apy_pct:.2f}%"
              f" drag={p.total_fee_drag_pct:.2f}% [{p.fee_label}]")


if __name__ == "__main__":
    import sys
    if "--check" in sys.argv or len(sys.argv) == 1:
        _demo_run()
