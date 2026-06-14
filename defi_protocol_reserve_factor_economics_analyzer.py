"""
MP-1045  DeFiProtocolReserveFactorEconomicsAnalyzer
----------------------------------------------------
Analyse the reserve-factor economics of a DeFi lending market.

The "reserve factor" is the share of borrow interest a protocol diverts to its
reserves / treasury instead of paying it out to suppliers.  This module
quantifies:

  (a) how much yield the reserve factor costs suppliers (supplier APY drag),
  (b) how much protocol income the reserve factor generates, and
  (c) whether accumulated reserves form an adequate buffer against bad debt.

Genuine gap: existing lending modules cover utilisation and rate spreads, but
none focus on reserve-factor economics or reserve adequacy.

The module returns:
- reserve_income_annual_usd     – annual income diverted to reserves
- supplier_apy_drag_pct         – APY removed from suppliers by the factor
- reserve_to_borrows_pct        – buffer size relative to outstanding debt
- bad_debt_coverage_ratio       – reserves / bad debt (capped sentinel if none)
- reserve_adequacy_score        – 0-100, higher = better capitalised
- classification                – advisory band
- grade                         – A-F letter grade
- flags / recommendations       – advisory verdicts

Advisory / read-only.  Pure stdlib.  Atomic ring-buffer JSON log (100 entries).
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_LOG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data",
    "reserve_factor_economics_log.json",
)
_LOG_CAP = 100

# Sentinel coverage ratio used when there is no bad debt (fully covered).
_NO_BAD_DEBT_COVERAGE = 999.0

# Classification bands
CLASS_UNDERFUNDED = "UNDERFUNDED"
CLASS_THIN = "THIN"
CLASS_ADEQUATE = "ADEQUATE"
CLASS_WELL_CAPITALIZED = "WELL_CAPITALIZED"
CLASS_OVERCAPITALIZED = "OVERCAPITALIZED"

ALL_CLASSIFICATIONS = (
    CLASS_UNDERFUNDED,
    CLASS_THIN,
    CLASS_ADEQUATE,
    CLASS_WELL_CAPITALIZED,
    CLASS_OVERCAPITALIZED,
)

# Flags
FLAG_NO_RESERVE_FACTOR = "NO_RESERVE_FACTOR"
FLAG_EXCESSIVE_RESERVE_FACTOR = "EXCESSIVE_RESERVE_FACTOR"
FLAG_HIGH_SUPPLIER_DRAG = "HIGH_SUPPLIER_DRAG"
FLAG_THIN_RESERVES = "THIN_RESERVES"
FLAG_UNCOVERED_BAD_DEBT = "UNCOVERED_BAD_DEBT"
FLAG_NO_BAD_DEBT = "NO_BAD_DEBT"
FLAG_STRONG_BUFFER = "STRONG_BUFFER"
FLAG_OVERCAPITALIZED = "OVERCAPITALIZED"
FLAG_INSUFFICIENT_DATA = "INSUFFICIENT_DATA"

ALL_FLAGS = (
    FLAG_NO_RESERVE_FACTOR,
    FLAG_EXCESSIVE_RESERVE_FACTOR,
    FLAG_HIGH_SUPPLIER_DRAG,
    FLAG_THIN_RESERVES,
    FLAG_UNCOVERED_BAD_DEBT,
    FLAG_NO_BAD_DEBT,
    FLAG_STRONG_BUFFER,
    FLAG_OVERCAPITALIZED,
    FLAG_INSUFFICIENT_DATA,
)

# Thresholds
_EXCESSIVE_RESERVE_FACTOR_PCT = 30.0   # > 30 % share to reserves is high
_HIGH_SUPPLIER_DRAG_PCT = 1.0          # > 1 % APY drag is meaningful
_THIN_RESERVES_PCT = 1.0               # reserves < 1 % of borrows is thin
_STRONG_BUFFER_PCT = 5.0               # reserves >= 5 % of borrows is strong
_OVERCAPITALIZED_PCT = 25.0            # reserves >= 25 % of borrows is excessive


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _atomic_log(log_path: str, entry: dict) -> None:
    """Append *entry* to ring-buffer JSON array (cap=100), atomic write."""
    abs_path = os.path.abspath(log_path)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    try:
        with open(abs_path, "r", encoding="utf-8") as fh:
            data: list = json.load(fh)
        if not isinstance(data, list):
            data = []
    except (FileNotFoundError, json.JSONDecodeError):
        data = []

    data.append(entry)
    if len(data) > _LOG_CAP:
        data = data[-_LOG_CAP:]

    dir_name = os.path.dirname(abs_path)
    fd, tmp = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        os.replace(tmp, abs_path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Coerce *value* to float, returning *default* on failure."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, lo: float, hi: float) -> float:
    """Clamp *value* to the inclusive range [lo, hi]."""
    return max(lo, min(hi, value))


# ---------------------------------------------------------------------------
# Sub-calculators (defensive division everywhere)
# ---------------------------------------------------------------------------

def _reserve_income_annual_usd(
    total_borrows_usd: float,
    borrow_apr_pct: float,
    reserve_factor_pct: float,
) -> float:
    """
    Annual income diverted to reserves.

    income = total_borrows * borrow_apr% * reserve_factor%
    """
    return (
        max(0.0, total_borrows_usd)
        * borrow_apr_pct / 100.0
        * reserve_factor_pct / 100.0
    )


def _supplier_apy_drag_pct(
    borrow_apr_pct: float,
    utilization_pct: float,
    reserve_factor_pct: float,
) -> float:
    """
    APY (in pct) removed from suppliers by the reserve factor.

    drag = borrow_apr% * utilization% * reserve_factor%

    Suppliers only earn interest on the utilised portion of their deposits, and
    the reserve factor skims a share of that interest.
    """
    return (
        borrow_apr_pct
        * utilization_pct / 100.0
        * reserve_factor_pct / 100.0
    )


def _reserve_to_borrows_pct(
    current_reserves_usd: float,
    total_borrows_usd: float,
) -> float:
    """
    Buffer size relative to outstanding debt, in pct.

    Returns 0.0 when there are no borrows (avoids div-by-zero).
    """
    if total_borrows_usd <= 0:
        return 0.0
    return current_reserves_usd / total_borrows_usd * 100.0


def _bad_debt_coverage_ratio(
    current_reserves_usd: float,
    bad_debt_usd: float,
) -> tuple[float, bool]:
    """
    Reserves relative to bad debt.

    Returns ``(ratio, no_bad_debt)``.

    When there is no bad debt the market is effectively fully covered; we return
    a large capped sentinel (999.0) and ``no_bad_debt=True`` to avoid the
    division-by-zero and avoid ``float('inf')``.
    """
    if bad_debt_usd <= 0:
        return _NO_BAD_DEBT_COVERAGE, True
    return current_reserves_usd / bad_debt_usd, False


def _reserve_adequacy_score(
    reserve_to_borrows_pct: float,
    bad_debt_coverage_ratio: float,
    no_bad_debt: bool,
    has_data: bool,
) -> float:
    """
    Blend buffer size and bad-debt coverage into a 0-100 adequacy score.

    Higher = better capitalised.  Uncovered bad debt is penalised heavily.

    - Buffer component (0-60): reserve_to_borrows_pct scaled, saturating at
      the STRONG_BUFFER threshold (a strong buffer earns full marks).
    - Coverage component (0-40): full marks when no bad debt or coverage >= 1;
      a hard penalty when coverage < 1 (uncovered bad debt).

    When there is no usable data the score is 0.
    """
    if not has_data:
        return 0.0

    # Buffer component, 0-60, saturating at the strong-buffer threshold.
    buffer_frac = _clamp(
        reserve_to_borrows_pct / _STRONG_BUFFER_PCT, 0.0, 1.0
    )
    buffer_component = buffer_frac * 60.0

    # Coverage component, 0-40.
    if no_bad_debt:
        coverage_component = 40.0
    elif bad_debt_coverage_ratio >= 1.0:
        coverage_component = 40.0
    else:
        # Uncovered bad debt: scale linearly with how much is covered, then
        # apply a heavy penalty for being uncovered.
        coverage_component = _clamp(bad_debt_coverage_ratio, 0.0, 1.0) * 40.0
        coverage_component *= 0.5  # heavy penalty for uncovered bad debt
        # Also dampen the buffer component when there is uncovered bad debt.
        buffer_component *= 0.5

    return _clamp(buffer_component + coverage_component, 0.0, 100.0)


def _classify(
    reserve_adequacy_score: float,
    reserve_to_borrows_pct: float,
    no_bad_debt: bool,
    bad_debt_coverage_ratio: float,
    has_data: bool,
) -> str:
    """
    Assign an advisory classification band.

    Priority (highest to lowest):
    1. UNDERFUNDED      – uncovered bad debt OR very low adequacy score
    2. OVERCAPITALIZED  – buffer far exceeds the overcapitalised threshold
    3. WELL_CAPITALIZED – strong buffer and good adequacy
    4. ADEQUATE         – moderate adequacy
    5. THIN             – low buffer

    No data falls back to UNDERFUNDED (cannot demonstrate adequacy).
    """
    if not has_data:
        return CLASS_UNDERFUNDED

    uncovered_bad_debt = (not no_bad_debt) and bad_debt_coverage_ratio < 1.0

    if uncovered_bad_debt or reserve_adequacy_score < 25.0:
        return CLASS_UNDERFUNDED

    if reserve_to_borrows_pct >= _OVERCAPITALIZED_PCT:
        return CLASS_OVERCAPITALIZED

    if reserve_to_borrows_pct >= _STRONG_BUFFER_PCT and reserve_adequacy_score >= 75.0:
        return CLASS_WELL_CAPITALIZED

    if reserve_to_borrows_pct < _THIN_RESERVES_PCT or reserve_adequacy_score < 50.0:
        return CLASS_THIN

    return CLASS_ADEQUATE


def _grade(reserve_adequacy_score: float) -> str:
    """Map a 0-100 adequacy score to an A-F letter grade."""
    s = reserve_adequacy_score
    if s >= 90.0:
        return "A"
    if s >= 75.0:
        return "B"
    if s >= 60.0:
        return "C"
    if s >= 40.0:
        return "D"
    return "F"


def _flags(
    reserve_factor_pct: float,
    supplier_apy_drag_pct: float,
    reserve_to_borrows_pct: float,
    bad_debt_usd: float,
    bad_debt_coverage_ratio: float,
    no_bad_debt: bool,
    has_data: bool,
) -> list:
    """Return only the relevant advisory flags."""
    flags: list[str] = []

    if not has_data:
        flags.append(FLAG_INSUFFICIENT_DATA)
        return flags

    if reserve_factor_pct <= 0:
        flags.append(FLAG_NO_RESERVE_FACTOR)
    elif reserve_factor_pct > _EXCESSIVE_RESERVE_FACTOR_PCT:
        flags.append(FLAG_EXCESSIVE_RESERVE_FACTOR)

    if supplier_apy_drag_pct > _HIGH_SUPPLIER_DRAG_PCT:
        flags.append(FLAG_HIGH_SUPPLIER_DRAG)

    if reserve_to_borrows_pct < _THIN_RESERVES_PCT:
        flags.append(FLAG_THIN_RESERVES)
    elif reserve_to_borrows_pct >= _STRONG_BUFFER_PCT:
        flags.append(FLAG_STRONG_BUFFER)

    if reserve_to_borrows_pct >= _OVERCAPITALIZED_PCT:
        flags.append(FLAG_OVERCAPITALIZED)

    if no_bad_debt:
        flags.append(FLAG_NO_BAD_DEBT)
    elif bad_debt_usd > 0 and bad_debt_coverage_ratio < 1.0:
        flags.append(FLAG_UNCOVERED_BAD_DEBT)

    return flags


def _recommendations(
    classification: str,
    flags: list,
    reserve_factor_pct: float,
    supplier_apy_drag_pct: float,
    reserve_to_borrows_pct: float,
    bad_debt_coverage_ratio: float,
    no_bad_debt: bool,
    reserve_income_annual_usd: float,
    has_data: bool,
) -> list:
    """Return advisory recommendation strings based on the verdict."""
    recs: list[str] = []

    if not has_data:
        recs.append(
            "Insufficient data: total_borrows_usd <= 0. "
            "Cannot assess reserve-factor economics for this market."
        )
        return recs

    if FLAG_UNCOVERED_BAD_DEBT in flags:
        recs.append(
            f"CRITICAL: bad-debt coverage ratio {bad_debt_coverage_ratio:.2f} "
            "is below 1.0 — reserves do not fully cover outstanding bad debt. "
            "Prioritise replenishing reserves or socialising the loss."
        )

    if classification == CLASS_UNDERFUNDED:
        recs.append(
            f"Reserves are underfunded ({reserve_to_borrows_pct:.2f}% of borrows). "
            "Consider raising the reserve factor or topping up reserves."
        )
    elif classification == CLASS_THIN:
        recs.append(
            f"Reserve buffer is thin ({reserve_to_borrows_pct:.2f}% of borrows). "
            "Build reserves toward at least a 5% buffer for resilience."
        )
    elif classification == CLASS_ADEQUATE:
        recs.append(
            f"Reserve buffer is adequate ({reserve_to_borrows_pct:.2f}% of borrows). "
            "Maintain the current reserve factor and monitor utilisation."
        )
    elif classification == CLASS_WELL_CAPITALIZED:
        recs.append(
            f"Reserves are well capitalised ({reserve_to_borrows_pct:.2f}% of borrows). "
            "The market carries a healthy buffer against bad debt."
        )
    elif classification == CLASS_OVERCAPITALIZED:
        recs.append(
            f"Reserves are overcapitalised ({reserve_to_borrows_pct:.2f}% of borrows). "
            "Consider lowering the reserve factor to improve supplier APY."
        )

    if FLAG_NO_RESERVE_FACTOR in flags:
        recs.append(
            "Reserve factor is 0%: the protocol earns no reserve income and "
            "builds no buffer from this market. Suppliers keep all interest."
        )
    elif FLAG_EXCESSIVE_RESERVE_FACTOR in flags:
        recs.append(
            f"Reserve factor {reserve_factor_pct:.0f}% exceeds 30% and meaningfully "
            "suppresses supplier APY. Verify it is justified by the risk profile."
        )

    if FLAG_HIGH_SUPPLIER_DRAG in flags:
        recs.append(
            f"Supplier APY drag is high ({supplier_apy_drag_pct:.2f}%): the reserve "
            "factor removes significant yield from suppliers, hurting competitiveness."
        )

    if no_bad_debt and FLAG_OVERCAPITALIZED not in flags and classification not in (
        CLASS_UNDERFUNDED, CLASS_THIN,
    ):
        recs.append(
            "No recorded bad debt: the reserve buffer currently faces no claims."
        )

    if reserve_income_annual_usd > 0:
        recs.append(
            f"Reserve factor generates ~${reserve_income_annual_usd:,.0f} of protocol "
            "income per year at current borrow levels."
        )

    return recs


# ---------------------------------------------------------------------------
# Public analyse function
# ---------------------------------------------------------------------------

def analyze(market: dict, config: dict | None = None) -> dict:
    """
    Analyse the reserve-factor economics of a single DeFi lending market.

    Parameters
    ----------
    market : dict
        Keys (all with safe defaults):
        - name                 : str
        - reserve_factor_pct   : float  (0-100, share of borrow interest to reserves)
        - borrow_apr_pct       : float
        - utilization_pct      : float  (0-100)
        - total_borrows_usd    : float  (>= 0)
        - current_reserves_usd : float  (>= 0)
        - bad_debt_usd         : float  (>= 0, default 0)
        - supply_apy_pct       : float  (optional, default 0)
    config : dict, optional
        - log_path : str  (override default log path)

    Returns
    -------
    dict
        Full analysis result.  Never raises to the caller.
    """
    cfg = config or {}
    log_path = cfg.get("log_path", _LOG_PATH)

    name = str(market.get("name", "UNKNOWN"))
    reserve_factor_pct = _clamp(
        _safe_float(market.get("reserve_factor_pct", 0.0)), 0.0, 100.0
    )
    borrow_apr_pct = max(0.0, _safe_float(market.get("borrow_apr_pct", 0.0)))
    utilization_pct = _clamp(
        _safe_float(market.get("utilization_pct", 0.0)), 0.0, 100.0
    )
    total_borrows_usd = max(0.0, _safe_float(market.get("total_borrows_usd", 0.0)))
    current_reserves_usd = max(
        0.0, _safe_float(market.get("current_reserves_usd", 0.0))
    )
    bad_debt_usd = max(0.0, _safe_float(market.get("bad_debt_usd", 0.0)))
    supply_apy_pct = max(0.0, _safe_float(market.get("supply_apy_pct", 0.0)))

    has_data = total_borrows_usd > 0

    reserve_income = _reserve_income_annual_usd(
        total_borrows_usd, borrow_apr_pct, reserve_factor_pct
    )
    supplier_drag = _supplier_apy_drag_pct(
        borrow_apr_pct, utilization_pct, reserve_factor_pct
    )
    reserve_to_borrows = _reserve_to_borrows_pct(
        current_reserves_usd, total_borrows_usd
    )
    coverage_ratio, no_bad_debt = _bad_debt_coverage_ratio(
        current_reserves_usd, bad_debt_usd
    )
    adequacy = _reserve_adequacy_score(
        reserve_to_borrows, coverage_ratio, no_bad_debt, has_data
    )
    classification = _classify(
        adequacy, reserve_to_borrows, no_bad_debt, coverage_ratio, has_data
    )
    grade = _grade(adequacy)
    flags = _flags(
        reserve_factor_pct,
        supplier_drag,
        reserve_to_borrows,
        bad_debt_usd,
        coverage_ratio,
        no_bad_debt,
        has_data,
    )
    recs = _recommendations(
        classification,
        flags,
        reserve_factor_pct,
        supplier_drag,
        reserve_to_borrows,
        coverage_ratio,
        no_bad_debt,
        reserve_income,
        has_data,
    )

    result: dict[str, Any] = {
        "name": name,
        "reserve_factor_pct": reserve_factor_pct,
        "borrow_apr_pct": borrow_apr_pct,
        "utilization_pct": utilization_pct,
        "total_borrows_usd": total_borrows_usd,
        "current_reserves_usd": current_reserves_usd,
        "bad_debt_usd": bad_debt_usd,
        "supply_apy_pct": supply_apy_pct,
        "reserve_income_annual_usd": reserve_income,
        "supplier_apy_drag_pct": supplier_drag,
        "reserve_to_borrows_pct": reserve_to_borrows,
        "bad_debt_coverage_ratio": coverage_ratio,
        "no_bad_debt": no_bad_debt,
        "reserve_adequacy_score": adequacy,
        "classification": classification,
        "grade": grade,
        "flags": flags,
        "recommendations": recs,
        "timestamp": time.time(),
    }

    try:
        _atomic_log(log_path, result)
    except Exception:
        pass  # advisory: never crash caller

    return result


# ---------------------------------------------------------------------------
# Public batch analyse function
# ---------------------------------------------------------------------------

def analyze_portfolio(markets: list, config: dict | None = None) -> dict:
    """
    Analyse a portfolio of lending markets and produce a batch summary.

    Parameters
    ----------
    markets : list[dict]
        A list of market dicts (see :func:`analyze`).
    config : dict, optional
        Forwarded to :func:`analyze`.

    Returns
    -------
    dict
        Summary with keys:
        - total_markets
        - results                  – list of per-market analyses
        - safest_market            – name of highest-adequacy market (or None)
        - riskiest_market          – name of lowest-adequacy market (or None)
        - avg_reserve_adequacy_score
        - underfunded_count
    """
    if not isinstance(markets, list):
        markets = []

    results: list[dict] = [analyze(m if isinstance(m, dict) else {}, config=config)
                           for m in markets]

    total_markets = len(results)

    if total_markets == 0:
        return {
            "total_markets": 0,
            "results": [],
            "safest_market": None,
            "riskiest_market": None,
            "avg_reserve_adequacy_score": 0.0,
            "underfunded_count": 0,
        }

    safest = max(results, key=lambda r: r["reserve_adequacy_score"])
    riskiest = min(results, key=lambda r: r["reserve_adequacy_score"])
    avg_score = sum(r["reserve_adequacy_score"] for r in results) / total_markets
    underfunded_count = sum(
        1 for r in results if r["classification"] == CLASS_UNDERFUNDED
    )

    return {
        "total_markets": total_markets,
        "results": results,
        "safest_market": safest["name"],
        "riskiest_market": riskiest["name"],
        "avg_reserve_adequacy_score": avg_score,
        "underfunded_count": underfunded_count,
    }


# ---------------------------------------------------------------------------
# Class wrapper
# ---------------------------------------------------------------------------

class DeFiProtocolReserveFactorEconomicsAnalyzer:
    """
    Object-oriented wrapper around the functional ``analyze`` /
    ``analyze_portfolio`` functions.

    >>> a = DeFiProtocolReserveFactorEconomicsAnalyzer()
    >>> r = a.analyze({"name": "USDC", "reserve_factor_pct": 10.0, ...})
    """

    def __init__(self, config: dict | None = None) -> None:
        self._config = config or {}

    def analyze(self, market: dict) -> dict:
        """Delegate to module-level ``analyze``."""
        return analyze(market, config=self._config)

    def analyze_portfolio(self, markets: list) -> dict:
        """Delegate to module-level ``analyze_portfolio``."""
        return analyze_portfolio(markets, config=self._config)


# ---------------------------------------------------------------------------
# CLI demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    _demo_markets = [
        {
            "name": "USDC (well capitalised)",
            "reserve_factor_pct": 10.0,
            "borrow_apr_pct": 6.0,
            "utilization_pct": 80.0,
            "total_borrows_usd": 1_000_000_000.0,
            "current_reserves_usd": 70_000_000.0,
            "bad_debt_usd": 0.0,
            "supply_apy_pct": 4.3,
        },
        {
            "name": "Long-tail token (underfunded)",
            "reserve_factor_pct": 35.0,
            "borrow_apr_pct": 25.0,
            "utilization_pct": 90.0,
            "total_borrows_usd": 50_000_000.0,
            "current_reserves_usd": 200_000.0,
            "bad_debt_usd": 1_000_000.0,
            "supply_apy_pct": 14.6,
        },
        {
            "name": "No reserve factor market",
            "reserve_factor_pct": 0.0,
            "borrow_apr_pct": 5.0,
            "utilization_pct": 60.0,
            "total_borrows_usd": 200_000_000.0,
            "current_reserves_usd": 0.0,
            "bad_debt_usd": 0.0,
        },
    ]

    import json as _json
    print(_json.dumps(analyze(_demo_markets[0]), indent=2, default=str))
    print("---- portfolio ----")
    summary = analyze_portfolio(_demo_markets)
    summary_view = {k: v for k, v in summary.items() if k != "results"}
    print(_json.dumps(summary_view, indent=2, default=str))
    sys.exit(0)
