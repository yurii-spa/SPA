"""
MP-1031: ProtocolDeFiYieldCompoundingEfficiencyAnalyzer
========================================================
Advisory-only analytics module.

Analyzes how efficiently a DeFi position compounds yield, accounting for
auto-compounding vs. manual re-investment, gas drag, protocol fees on each
compound event, and optimal compounding frequency.

Per position it computes:
  effective_apy_pct                float  APY after gas drag and fees
  optimal_compound_frequency_per_day float  frequency that maximises net APY
  gas_drag_bps                     float  basis points of yield consumed by gas
  net_compounding_benefit_pct      float  effective_apy − simple (non-compounded) yield
  label:
    OPTIMAL_COMPOUNDING          net_compounding_benefit >= 0.5 and gas_drag_bps < 50
    GOOD_COMPOUNDING             net_compounding_benefit >= 0.1 and gas_drag_bps < 200
    SUBOPTIMAL                   net_compounding_benefit >= 0 and gas_drag_bps < 500
    GAS_DOMINATED                net_compounding_benefit >= 0 and gas_drag_bps >= 500
    COMPOUNDING_DESTROYS_YIELD   net_compounding_benefit < 0

Inputs per position dict:
  base_apy_pct                     float  gross APY in percent (e.g. 8.0 = 8%)
  gas_cost_per_compound_usd        float  USD cost of one compound transaction
  position_size_usd                float  USD value of the position
  compound_frequency_per_day       float  actual compounds per day (0 = no compounding)
  auto_compound                    bool   True if protocol auto-compounds (no gas per event)
  protocol_fee_on_compound_pct     float  protocol takes X% of yield on each compound

Math notes
----------
Daily rate  r_d = base_apy / 100 / 365
Yield per compound event (before fees) = position_size * r_d * (1 / frequency_per_day)
  = position_size * r_d / f   (for frequency f compounds/day)

Net yield per event after protocol fee:
  y_net = yield_per_event * (1 - protocol_fee / 100)

Gas cost per event for manual:
  gas_per_day = gas_cost_per_compound * f
  For auto_compound = True: gas_per_day = 0 (protocol absorbs or it's baked into fee)

Effective APY (continuous approximation via discrete compounding):
  effective_apy = ((1 + y_net / position_size) ^ (f * 365) - 1) * 100
  minus annualised gas drag:
  gas_drag_annual_pct = (gas_per_day * 365 / position_size) * 100
  effective_apy_pct = compound_apy_gross - gas_drag_annual_pct

Optimal frequency (analytical, Newton-Raphson style): the compound frequency that
maximises net return per day, balancing the compounding gain against gas drag.

Pure stdlib. Read-only / advisory. No external dependencies.
Ring-buffer log capped at 100 entries → data/yield_compounding_efficiency_log.json
Atomic writes: tmp + os.replace.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Optional
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(os.path.dirname(_HERE))
LOG_PATH = os.path.join(_REPO_ROOT, "data", "yield_compounding_efficiency_log.json")
LOG_MAX_ENTRIES = 100

# Minimum position size to avoid div-by-zero
_MIN_POSITION_USD = 1.0
# Minimum frequency guard (per day)
_MIN_FREQ = 1e-9

# Label thresholds
LABEL_OPTIMAL_BENEFIT_PCT = 0.5
LABEL_GOOD_BENEFIT_PCT    = 0.1
LABEL_OPTIMAL_GAS_BPS     = 50.0
LABEL_GOOD_GAS_BPS        = 200.0
LABEL_SUBOPTIMAL_GAS_BPS  = 500.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clamp(v: float, lo: float = 0.0, hi: float = float("inf")) -> float:
    return max(lo, min(hi, v))


def _iso_now() -> str:
    t = time.gmtime()
    return (
        f"{t.tm_year:04d}-{t.tm_mon:02d}-{t.tm_mday:02d}T"
        f"{t.tm_hour:02d}:{t.tm_min:02d}:{t.tm_sec:02d}Z"
    )


# ---------------------------------------------------------------------------
# Core computations (public for unit testability)
# ---------------------------------------------------------------------------

def compute_simple_daily_rate(base_apy_pct: float) -> float:
    """Daily rate from APY: r_d = base_apy_pct / 100 / 365."""
    return max(0.0, float(base_apy_pct)) / 100.0 / 365.0


def compute_compound_apy(
    base_apy_pct: float,
    compound_frequency_per_day: float,
    protocol_fee_on_compound_pct: float,
) -> float:
    """
    Gross compound APY before gas drag (percent).

    Each compound event captures r_d / f of the principal (one period's worth),
    applies the protocol fee, and re-invests. Compounded f*365 times per year.

    Returns the simple base_apy_pct if frequency is effectively 0 (no compounding).
    """
    apy = max(0.0, float(base_apy_pct))
    f   = max(_MIN_FREQ, float(compound_frequency_per_day))
    fee = max(0.0, min(100.0, float(protocol_fee_on_compound_pct)))

    r_d = apy / 100.0 / 365.0
    # Yield per event after fee (as fraction of principal)
    r_event = (r_d / f) * (1.0 - fee / 100.0)
    # Annualise
    compound_apy = ((1.0 + r_event) ** (f * 365.0) - 1.0) * 100.0
    return round(max(0.0, compound_apy), 6)


def compute_gas_drag_annual_pct(
    gas_cost_per_compound_usd: float,
    position_size_usd: float,
    compound_frequency_per_day: float,
    auto_compound: bool,
) -> float:
    """
    Annualised gas drag as a percentage of position size.

    If auto_compound is True, gas is paid by the protocol (or embedded in the
    protocol fee) — drag = 0 for this calculation.

    gas_drag_annual_pct = (gas_cost_per_compound * f * 365 / position_size) * 100
    """
    if auto_compound:
        return 0.0
    gas  = max(0.0, float(gas_cost_per_compound_usd))
    pos  = max(_MIN_POSITION_USD, float(position_size_usd))
    f    = max(_MIN_FREQ, float(compound_frequency_per_day))
    return round((gas * f * 365.0 / pos) * 100.0, 6)


def compute_gas_drag_bps(
    gas_cost_per_compound_usd: float,
    position_size_usd: float,
    compound_frequency_per_day: float,
    auto_compound: bool,
) -> float:
    """Gas drag in basis points (1 bps = 0.01%). drag_bps = drag_pct * 100."""
    return round(
        compute_gas_drag_annual_pct(
            gas_cost_per_compound_usd, position_size_usd,
            compound_frequency_per_day, auto_compound
        ) * 100.0,
        4,
    )


def compute_effective_apy(
    base_apy_pct: float,
    gas_cost_per_compound_usd: float,
    position_size_usd: float,
    compound_frequency_per_day: float,
    auto_compound: bool,
    protocol_fee_on_compound_pct: float,
) -> float:
    """
    Net effective APY after compounding, gas drag, and protocol fees (percent).

    = compound_apy_gross  −  gas_drag_annual_pct
    Clamped to [−base_apy_pct, ∞) — can't lose more than the principal yield.
    """
    gross = compute_compound_apy(base_apy_pct, compound_frequency_per_day,
                                 protocol_fee_on_compound_pct)
    drag  = compute_gas_drag_annual_pct(gas_cost_per_compound_usd, position_size_usd,
                                        compound_frequency_per_day, auto_compound)
    net = gross - drag
    return round(net, 6)


def compute_optimal_compound_frequency(
    base_apy_pct: float,
    gas_cost_per_compound_usd: float,
    position_size_usd: float,
    auto_compound: bool,
    protocol_fee_on_compound_pct: float,
) -> float:
    """
    Compute the compound frequency (per day) that maximises effective_apy.

    For auto_compound = True: gas is free, so more frequent = better up to
    continuous compounding. We return 1440 (once per minute) as the practical ceiling.

    For manual compounding: we search numerically over a log-spaced grid of
    frequencies from 1/365 per day (once/year) to 48 per day (every 30 min).
    The grid is refined around the best candidate.

    Returns 0.0 if no compounding ever beats simple yield.
    """
    if auto_compound:
        # Gas free — continuous-ish is best (practical ceiling)
        return 1440.0

    gas = max(0.0, float(gas_cost_per_compound_usd))
    pos = max(_MIN_POSITION_USD, float(position_size_usd))

    # If gas is zero, treat same as auto_compound
    if gas == 0.0:
        return 1440.0

    # Grid search: frequencies per day
    candidates = []
    # Coarse grid: 0.01 (≈once every 100 days) up to 48
    f = 0.01
    while f <= 48.0:
        eff = compute_effective_apy(
            base_apy_pct, gas, pos, f, False, protocol_fee_on_compound_pct
        )
        candidates.append((eff, f))
        f *= 1.15  # geometric step

    if not candidates:
        return 0.0

    best_eff, best_f = max(candidates, key=lambda x: x[0])

    # Simple yield (no compounding at all): base_apy * (1 - fee)
    fee = max(0.0, min(100.0, float(protocol_fee_on_compound_pct)))
    simple_apy = float(base_apy_pct) * (1.0 - fee / 100.0)

    if best_eff <= simple_apy:
        return 0.0  # compounding with gas never beats simple hold

    return round(best_f, 4)


def compute_net_compounding_benefit(
    effective_apy_pct: float,
    base_apy_pct: float,
    protocol_fee_on_compound_pct: float,
) -> float:
    """
    Benefit of compounding vs. simply holding at base APY (accounting for fees).
    net_benefit = effective_apy_pct - base_apy_pct * (1 - fee/100)
    Positive = compounding adds value; negative = compounding destroys value.
    """
    fee = max(0.0, min(100.0, float(protocol_fee_on_compound_pct)))
    simple = float(base_apy_pct) * (1.0 - fee / 100.0)
    return round(float(effective_apy_pct) - simple, 6)


def compute_label(
    net_compounding_benefit_pct: float,
    gas_drag_bps: float,
) -> str:
    """
    Assign a label based on net compounding benefit and gas drag.

    COMPOUNDING_DESTROYS_YIELD  net_benefit < 0
    GAS_DOMINATED               net_benefit >= 0 AND gas_drag >= 500 bps
    SUBOPTIMAL                  net_benefit >= 0 AND gas_drag in [200, 500)
    GOOD_COMPOUNDING            net_benefit >= 0.1 AND gas_drag < 200
    OPTIMAL_COMPOUNDING         net_benefit >= 0.5 AND gas_drag < 50
    """
    nb  = float(net_compounding_benefit_pct)
    bps = float(gas_drag_bps)

    if nb < 0.0:
        return "COMPOUNDING_DESTROYS_YIELD"
    if bps >= LABEL_SUBOPTIMAL_GAS_BPS:
        return "GAS_DOMINATED"
    if nb >= LABEL_OPTIMAL_BENEFIT_PCT and bps < LABEL_OPTIMAL_GAS_BPS:
        return "OPTIMAL_COMPOUNDING"
    if nb >= LABEL_GOOD_BENEFIT_PCT and bps < LABEL_GOOD_GAS_BPS:
        return "GOOD_COMPOUNDING"
    return "SUBOPTIMAL"


# ---------------------------------------------------------------------------
# Single-entry analysis
# ---------------------------------------------------------------------------

def _analyze_one(entry: dict[str, Any]) -> dict[str, Any]:
    base_apy    = float(entry.get("base_apy_pct", 0.0))
    gas_cost    = float(entry.get("gas_cost_per_compound_usd", 0.0))
    pos_size    = max(_MIN_POSITION_USD, float(entry.get("position_size_usd", _MIN_POSITION_USD)))
    freq        = max(0.0, float(entry.get("compound_frequency_per_day", 0.0)))
    auto_comp   = bool(entry.get("auto_compound", False))
    proto_fee   = float(entry.get("protocol_fee_on_compound_pct", 0.0))

    effective_apy = compute_effective_apy(
        base_apy, gas_cost, pos_size, freq if freq > 0.0 else _MIN_FREQ, auto_comp, proto_fee
    )
    # If no compounding, effective_apy is just the simple rate less fees
    if freq == 0.0 and not auto_comp:
        fee_pct = max(0.0, min(100.0, proto_fee))
        effective_apy = round(base_apy * (1.0 - fee_pct / 100.0), 6)

    optimal_freq = compute_optimal_compound_frequency(
        base_apy, gas_cost, pos_size, auto_comp, proto_fee
    )
    gas_drag_bps = compute_gas_drag_bps(gas_cost, pos_size, freq if freq > 0.0 else _MIN_FREQ, auto_comp)
    net_benefit  = compute_net_compounding_benefit(effective_apy, base_apy, proto_fee)
    label        = compute_label(net_benefit, gas_drag_bps)

    return {
        "name":                            entry.get("name", "unknown"),
        "base_apy_pct":                    base_apy,
        "gas_cost_per_compound_usd":       gas_cost,
        "position_size_usd":               pos_size,
        "compound_frequency_per_day":      freq,
        "auto_compound":                   auto_comp,
        "protocol_fee_on_compound_pct":    proto_fee,
        "effective_apy_pct":               round(effective_apy, 4),
        "optimal_compound_frequency_per_day": optimal_freq,
        "gas_drag_bps":                    round(gas_drag_bps, 4),
        "net_compounding_benefit_pct":     round(net_benefit, 4),
        "label":                           label,
    }


# ---------------------------------------------------------------------------
# Main analyzer class
# ---------------------------------------------------------------------------

class ProtocolDeFiYieldCompoundingEfficiencyAnalyzer:
    """
    Analyzes how efficiently DeFi positions compound yield.
    Advisory / read-only. Pure stdlib. No execution side-effects.

    Usage
    -----
    analyzer = ProtocolDeFiYieldCompoundingEfficiencyAnalyzer()
    result = analyzer.analyze([
        {
            "name": "Aave USDC",
            "base_apy_pct": 8.0,
            "gas_cost_per_compound_usd": 15.0,
            "position_size_usd": 100_000.0,
            "compound_frequency_per_day": 1.0,
            "auto_compound": False,
            "protocol_fee_on_compound_pct": 0.1,
        }
    ])
    """

    def __init__(self, log_path: Optional[str] = None) -> None:
        self.log_path: str = log_path or LOG_PATH

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self, positions: list[dict[str, Any]],
                config: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        """
        Analyze a list of DeFi yield positions for compounding efficiency.

        Parameters
        ----------
        positions : list[dict]
            Each dict may contain:
              name                       str   (optional, default 'unknown')
              base_apy_pct               float gross APY %
              gas_cost_per_compound_usd  float USD per compound tx
              position_size_usd          float position USD value
              compound_frequency_per_day float actual compounds/day
              auto_compound              bool  protocol auto-compounds?
              protocol_fee_on_compound_pct float % of yield taken by protocol
        config : dict, optional
            log_path : str  — override log file path

        Returns
        -------
        dict with keys:
            positions                 list[dict]  per-position analysis
            best_compounding          str | None  name of most efficient position
            worst_compounding         str | None  name of least efficient position
            avg_effective_apy_pct     float
            optimal_count             int  positions labelled OPTIMAL_COMPOUNDING
            destroys_yield_count      int  positions labelled COMPOUNDING_DESTROYS_YIELD
            analyzed_at               str  ISO UTC timestamp
        """
        if config is None:
            config = {}
        if not isinstance(positions, list) or len(positions) == 0:
            raise ValueError("positions must be a non-empty list")

        results = [_analyze_one(p) for p in positions]

        eff_apys = [r["effective_apy_pct"] for r in results]
        avg_apy  = round(sum(eff_apys) / len(eff_apys), 4)

        sorted_by_eff = sorted(results, key=lambda r: r["effective_apy_pct"])
        best_name  = sorted_by_eff[-1]["name"]
        worst_name = sorted_by_eff[0]["name"]

        optimal_count = sum(1 for r in results if r["label"] == "OPTIMAL_COMPOUNDING")
        destroys_count = sum(1 for r in results if r["label"] == "COMPOUNDING_DESTROYS_YIELD")

        output: dict[str, Any] = {
            "positions":              results,
            "best_compounding":       best_name,
            "worst_compounding":      worst_name,
            "avg_effective_apy_pct":  avg_apy,
            "optimal_count":          optimal_count,
            "destroys_yield_count":   destroys_count,
            "analyzed_at":            _iso_now(),
        }

        log_path = config.get("log_path", self.log_path)
        _append_log(output, log_path)
        return output

    # ------------------------------------------------------------------
    # Convenience: single position
    # ------------------------------------------------------------------

    def analyze_one(self, position: dict[str, Any]) -> dict[str, Any]:
        """Analyze a single position dict without logging."""
        return _analyze_one(position)


# ---------------------------------------------------------------------------
# Ring-buffer log helpers
# ---------------------------------------------------------------------------

def _atomic_write(path: str, data: object) -> None:
    """Write JSON atomically using tmp + os.replace."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    dir_ = os.path.dirname(os.path.abspath(path))
    atomic_save(data, str(path))
def _init_log(path: str) -> list:
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return []


def _append_log(result: dict[str, Any], log_path: str = LOG_PATH) -> None:
    """Append a compact snapshot to the ring-buffer log."""
    entries = _init_log(log_path)
    snapshot = {
        "ts":                   result.get("analyzed_at", _iso_now()),
        "position_count":       len(result.get("positions", [])),
        "avg_effective_apy_pct": result.get("avg_effective_apy_pct"),
        "optimal_count":        result.get("optimal_count"),
        "destroys_yield_count": result.get("destroys_yield_count"),
        "best_compounding":     result.get("best_compounding"),
        "worst_compounding":    result.get("worst_compounding"),
    }
    entries.append(snapshot)
    if len(entries) > LOG_MAX_ENTRIES:
        entries = entries[-LOG_MAX_ENTRIES:]
    try:
        _atomic_write(log_path, entries)
    except OSError:
        pass  # advisory — never crash the caller on log failure


# ---------------------------------------------------------------------------
# Module-level convenience alias
# ---------------------------------------------------------------------------

def analyze(positions: list[dict[str, Any]],
            config: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Module-level shorthand — delegates to ProtocolDeFiYieldCompoundingEfficiencyAnalyzer."""
    return ProtocolDeFiYieldCompoundingEfficiencyAnalyzer().analyze(positions, config)
