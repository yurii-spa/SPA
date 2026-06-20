"""
MP-763: PositionSizingEngine
Computes optimal position sizes for DeFi yield strategies using risk-based
sizing methods: fixed fractional, Kelly criterion, volatility-adjusted sizing,
and max drawdown constraints.

Advisory/read-only — never modifies allocator, risk, or execution.
Pure stdlib — zero external dependencies.
Atomic writes: tmp + os.replace.
Ring-buffer cap: 100 entries.

CLI
---
  python3 -m spa_core.analytics.position_sizing_engine --check   (default)
  python3 -m spa_core.analytics.position_sizing_engine --run
  python3 -m spa_core.analytics.position_sizing_engine --run --data-dir PATH
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Paths & constants
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _PROJECT_ROOT / "data"
_LOG_FILENAME = "position_sizing_log.json"
_RING_BUFFER_MAX = 100

_FIXED_FRACTION_PCT = 2.0          # always 2% risk per trade
_VOL_TARGET_PCT = 10.0             # target 10% portfolio vol contribution
_VOL_MAX_FRACTION = 0.30           # vol-adjusted cap at 30% of portfolio
_KELLY_MAX = 0.25                  # quarter-Kelly ceiling
_MAX_ALLOWED_LOSS_PCT = 5.0        # 5% total portfolio at risk from drawdown method


# ---------------------------------------------------------------------------
# Core computation functions
# ---------------------------------------------------------------------------

def kelly_fraction(
    win_rate: float,
    avg_win_pct: float,
    avg_loss_pct: float,
) -> float:
    """
    Kelly criterion fraction, clamped to [0, 0.25].

    f = win_rate - (1 - win_rate) / b
    where b = avg_win_pct / avg_loss_pct

    Returns 0.0 if avg_loss_pct <= 0 (undefined or zero-loss edge-case).
    """
    if avg_loss_pct <= 0:
        return 0.0
    b = avg_win_pct / avg_loss_pct
    f = win_rate - (1.0 - win_rate) / b
    return min(_KELLY_MAX, max(0.0, f))


def vol_adjusted_position(portfolio_value_usd: float, vol_pct: float) -> float:
    """
    Volatility-adjusted position size targeting 10% portfolio vol contribution.

    raw = portfolio * (10 / vol_pct)
    Clamped to [0, portfolio * 0.30].
    If vol_pct <= 0, returns portfolio * 0.10.
    """
    if vol_pct <= 0:
        return portfolio_value_usd * 0.10
    raw = portfolio_value_usd * (_VOL_TARGET_PCT / vol_pct)
    return min(raw, portfolio_value_usd * _VOL_MAX_FRACTION)


def max_dd_position(
    portfolio_value_usd: float,
    max_drawdown_pct: float,
    max_allowed_loss_pct: float = _MAX_ALLOWED_LOSS_PCT,
) -> float:
    """
    Max drawdown constraint position size.

    position = portfolio * (max_allowed_loss_pct / max_drawdown_pct)
    If max_drawdown_pct <= 0, returns portfolio * 0.05.
    """
    if max_drawdown_pct <= 0:
        return portfolio_value_usd * 0.05
    return portfolio_value_usd * (max_allowed_loss_pct / max_drawdown_pct)


def get_sizing_label(rec_fraction_pct: float) -> str:
    """AGGRESSIVE (>20%) | MODERATE (10-20%) | CONSERVATIVE (<10%)"""
    if rec_fraction_pct > 20.0:
        return "AGGRESSIVE"
    elif rec_fraction_pct >= 10.0:
        return "MODERATE"
    else:
        return "CONSERVATIVE"


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class SizingInput:
    strategy_name: str
    portfolio_value_usd: float
    strategy_apy_pct: float
    strategy_volatility_pct: float   # annualized APY volatility
    max_drawdown_pct: float          # historical max drawdown
    win_rate: float                  # 0-1: fraction of periods with positive return
    avg_win_pct: float               # avg positive period return %
    avg_loss_pct: float              # avg negative period return % (positive number)


@dataclass
class SizingResult:
    strategy_name: str
    portfolio_value_usd: float

    # Method 1: Fixed fractional (2% risk per trade)
    fixed_fraction_pct: float          # always 2.0%
    fixed_fraction_usd: float          # portfolio * 2%

    # Method 2: Kelly criterion
    kelly_fraction: float              # clamped [0, 0.25]
    kelly_position_usd: float          # portfolio * kelly_fraction

    # Method 3: Volatility-adjusted (target 10% portfolio vol contribution)
    vol_adjusted_fraction_pct: float   # vol_adjusted_usd / portfolio * 100
    vol_adjusted_usd: float

    # Method 4: Max drawdown constraint
    max_dd_fraction_pct: float         # max_dd_usd / portfolio * 100
    max_dd_usd: float

    # Recommended: minimum of all four methods (most conservative)
    recommended_position_usd: float
    recommended_fraction_pct: float

    # Risk metrics at recommended size
    expected_annual_yield_usd: float   # recommended * apy_pct/100
    expected_annual_risk_usd: float    # recommended * volatility_pct/100

    sizing_label: str   # "AGGRESSIVE" | "MODERATE" | "CONSERVATIVE"
    recommendation: str


@dataclass
class PortfolioSizingResult:
    sizings: List[SizingResult]

    total_recommended_usd: float       # sum of all recommended positions
    total_recommended_pct: float       # total / portfolio * 100
    remaining_cash_usd: float          # portfolio - total_recommended

    over_allocated: bool               # total_recommended > portfolio * 0.90

    recommendation_summary: str
    saved_to: str = ""


# ---------------------------------------------------------------------------
# Sizing logic
# ---------------------------------------------------------------------------

def size_position(inp: SizingInput) -> SizingResult:
    """Compute all four sizing methods and return the most conservative."""
    pv = inp.portfolio_value_usd

    # Method 1: Fixed fractional
    ff_pct = _FIXED_FRACTION_PCT
    ff_usd = pv * ff_pct / 100.0

    # Method 2: Kelly
    kf = kelly_fraction(inp.win_rate, inp.avg_win_pct, inp.avg_loss_pct)
    kelly_usd = pv * kf

    # Method 3: Volatility-adjusted
    va_usd = vol_adjusted_position(pv, inp.strategy_volatility_pct)
    va_pct = va_usd / pv * 100.0 if pv > 0 else 0.0

    # Method 4: Max drawdown
    md_usd = max_dd_position(pv, inp.max_drawdown_pct)
    md_pct = md_usd / pv * 100.0 if pv > 0 else 0.0

    # Recommended: minimum (most conservative)
    rec_usd = min(ff_usd, kelly_usd, va_usd, md_usd)
    rec_pct = rec_usd / pv * 100.0 if pv > 0 else 0.0

    # Risk metrics
    yield_usd = rec_usd * inp.strategy_apy_pct / 100.0
    risk_usd = rec_usd * inp.strategy_volatility_pct / 100.0

    label = get_sizing_label(rec_pct)

    if label == "AGGRESSIVE":
        rec_text = "Position size is aggressive. Consider reducing exposure."
    elif label == "MODERATE":
        rec_text = "Position size is moderate. Acceptable risk level."
    else:
        rec_text = "Position size is conservative. Low risk exposure."

    return SizingResult(
        strategy_name=inp.strategy_name,
        portfolio_value_usd=pv,
        fixed_fraction_pct=ff_pct,
        fixed_fraction_usd=ff_usd,
        kelly_fraction=kf,
        kelly_position_usd=kelly_usd,
        vol_adjusted_fraction_pct=va_pct,
        vol_adjusted_usd=va_usd,
        max_dd_fraction_pct=md_pct,
        max_dd_usd=md_usd,
        recommended_position_usd=rec_usd,
        recommended_fraction_pct=rec_pct,
        expected_annual_yield_usd=yield_usd,
        expected_annual_risk_usd=risk_usd,
        sizing_label=label,
        recommendation=rec_text,
    )


def size_portfolio(strategies_data: List[Dict[str, Any]]) -> PortfolioSizingResult:
    """
    Compute position sizes for multiple strategies sharing the same portfolio.

    strategies_data: List[dict] with all SizingInput fields as keys.
    """
    inputs = [
        SizingInput(
            strategy_name=d["strategy_name"],
            portfolio_value_usd=float(d["portfolio_value_usd"]),
            strategy_apy_pct=float(d["strategy_apy_pct"]),
            strategy_volatility_pct=float(d["strategy_volatility_pct"]),
            max_drawdown_pct=float(d["max_drawdown_pct"]),
            win_rate=float(d["win_rate"]),
            avg_win_pct=float(d["avg_win_pct"]),
            avg_loss_pct=float(d["avg_loss_pct"]),
        )
        for d in strategies_data
    ]

    sizings = [size_position(inp) for inp in inputs]

    # Assume same portfolio_value_usd for all (use first)
    pv = inputs[0].portfolio_value_usd if inputs else 0.0

    total_rec = sum(s.recommended_position_usd for s in sizings)
    total_pct = total_rec / pv * 100.0 if pv > 0 else 0.0
    remaining = pv - total_rec
    over = total_rec > pv * 0.90

    if over:
        rec_summary = (
            "Total allocation exceeds 90% of portfolio. "
            "Reduce position sizes."
        )
    else:
        rec_summary = (
            f"Total allocation {total_pct:.1f}%. "
            f"{remaining:.0f} USD remaining as cash buffer."
        )

    return PortfolioSizingResult(
        sizings=sizings,
        total_recommended_usd=total_rec,
        total_recommended_pct=total_pct,
        remaining_cash_usd=remaining,
        over_allocated=over,
        recommendation_summary=rec_summary,
        saved_to="",
    )


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _sizing_to_dict(s: SizingResult) -> Dict[str, Any]:
    return {
        "strategy_name": s.strategy_name,
        "portfolio_value_usd": s.portfolio_value_usd,
        "fixed_fraction_pct": s.fixed_fraction_pct,
        "fixed_fraction_usd": s.fixed_fraction_usd,
        "kelly_fraction": s.kelly_fraction,
        "kelly_position_usd": s.kelly_position_usd,
        "vol_adjusted_fraction_pct": s.vol_adjusted_fraction_pct,
        "vol_adjusted_usd": s.vol_adjusted_usd,
        "max_dd_fraction_pct": s.max_dd_fraction_pct,
        "max_dd_usd": s.max_dd_usd,
        "recommended_position_usd": s.recommended_position_usd,
        "recommended_fraction_pct": s.recommended_fraction_pct,
        "expected_annual_yield_usd": s.expected_annual_yield_usd,
        "expected_annual_risk_usd": s.expected_annual_risk_usd,
        "sizing_label": s.sizing_label,
        "recommendation": s.recommendation,
    }


def _portfolio_result_to_dict(result: PortfolioSizingResult) -> Dict[str, Any]:
    return {
        "sizings": [_sizing_to_dict(s) for s in result.sizings],
        "total_recommended_usd": result.total_recommended_usd,
        "total_recommended_pct": result.total_recommended_pct,
        "remaining_cash_usd": result.remaining_cash_usd,
        "over_allocated": result.over_allocated,
        "recommendation_summary": result.recommendation_summary,
        "saved_to": result.saved_to,
    }


def save_results(
    result: PortfolioSizingResult,
    data_dir: Optional[Path] = None,
) -> PortfolioSizingResult:
    """Append result to ring-buffer JSON (max _RING_BUFFER_MAX entries)."""
    if data_dir is None:
        data_dir = _DEFAULT_DATA_DIR
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    log_file = data_dir / _LOG_FILENAME

    history = load_history(data_dir)
    entry = _portfolio_result_to_dict(result)
    entry["saved_at"] = datetime.now(timezone.utc).isoformat()
    history.append(entry)

    # Ring-buffer trim
    if len(history) > _RING_BUFFER_MAX:
        history = history[-_RING_BUFFER_MAX:]

    # Atomic write via tmp + os.replace
    atomic_save(history, str(log_file))
    result.saved_to = str(log_file)
    return result


def load_history(data_dir: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Load persisted history list from ring-buffer JSON."""
    if data_dir is None:
        data_dir = _DEFAULT_DATA_DIR
    log_file = Path(data_dir) / _LOG_FILENAME
    if not log_file.exists():
        return []
    try:
        with open(log_file) as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError, ValueError):
        return []


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _sample_strategies() -> List[Dict[str, Any]]:
    return [
        {
            "strategy_name": "Aave V3 USDC",
            "portfolio_value_usd": 100_000.0,
            "strategy_apy_pct": 3.5,
            "strategy_volatility_pct": 8.0,
            "max_drawdown_pct": 5.0,
            "win_rate": 0.65,
            "avg_win_pct": 0.30,
            "avg_loss_pct": 0.15,
        },
        {
            "strategy_name": "Morpho Steakhouse",
            "portfolio_value_usd": 100_000.0,
            "strategy_apy_pct": 6.5,
            "strategy_volatility_pct": 15.0,
            "max_drawdown_pct": 8.0,
            "win_rate": 0.60,
            "avg_win_pct": 0.55,
            "avg_loss_pct": 0.30,
        },
        {
            "strategy_name": "Delta-Neutral sUSDe",
            "portfolio_value_usd": 100_000.0,
            "strategy_apy_pct": 27.5,
            "strategy_volatility_pct": 35.0,
            "max_drawdown_pct": 15.0,
            "win_rate": 0.55,
            "avg_win_pct": 2.50,
            "avg_loss_pct": 1.20,
        },
    ]


def main(argv: Optional[List[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="MP-763 PositionSizingEngine")
    parser.add_argument("--check", action="store_true",
                        help="Compute and print (no write). Default mode.")
    parser.add_argument("--run", action="store_true",
                        help="Compute and save to data/")
    parser.add_argument("--data-dir", default=None,
                        help="Override data directory path")
    args = parser.parse_args(argv)

    data_dir = Path(args.data_dir) if args.data_dir else None
    result = size_portfolio(_sample_strategies())

    print(f"Total recommended : ${result.total_recommended_usd:>12,.0f}  "
          f"({result.total_recommended_pct:.1f}%)")
    print(f"Remaining cash    : ${result.remaining_cash_usd:>12,.0f}")
    print(f"Over-allocated    : {result.over_allocated}")
    print(f"Summary: {result.recommendation_summary}")
    print()
    for s in result.sizings:
        print(
            f"  {s.strategy_name:30s}  {s.sizing_label:12s}  "
            f"rec=${s.recommended_position_usd:>9,.0f}  "
            f"({s.recommended_fraction_pct:.1f}%)  "
            f"yield=${s.expected_annual_yield_usd:>7,.0f}/yr"
        )

    if args.run:
        save_results(result, data_dir)
        print(f"\nSaved to: {result.saved_to}")
    else:
        print("\n[--check mode] No data written. Use --run to persist.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
