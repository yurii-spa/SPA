"""
MP-1049 ProtocolDeFiLiquidityMiningDilutionAnalyzer
----------------------------------------------------
Analyzes whether a DeFi protocol's liquidity mining rewards create
unsustainable token dilution relative to actual protocol revenue (real yield).

Computes:
  - real_yield_pct              : annualized on-chain revenue / TVL × 100
  - dilution_yield_pct          : annualized token emissions / TVL × 100
  - total_yield_pct             : real + dilution combined (headline APY)
  - dilution_ratio              : dilution_yield / max(real_yield, ε)
  - fdv_to_revenue_ratio        : FDV / annual protocol revenue
  - emission_sustainability_score : 0-100 (100 = fully sustainable)
  - label                       : SUSTAINABLE_EMISSIONS / MANAGEABLE /
                                  HIGH_DILUTION / HYPERINFLATIONARY /
                                  DEATH_SPIRAL_EMISSIONS

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
    "liquidity_mining_dilution_log.json"
)
_LOG_CAP = 100
_DAYS_PER_YEAR: float = 365.0
_EPSILON: float = 1e-9   # guard against division by zero


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _atomic_log(log_path: str, entry: dict) -> None:
    """Append *entry* to ring-buffer JSON array (cap=100), atomic write."""
    abs_path = os.path.abspath(log_path)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)

    try:
        with open(abs_path, "r", encoding="utf-8") as f:
            data: list = json.load(f)
        if not isinstance(data, list):
            data = []
    except (FileNotFoundError, json.JSONDecodeError):
        data = []

    data.append(entry)
    if len(data) > _LOG_CAP:
        data = data[-_LOG_CAP:]

    dir_name = os.path.dirname(abs_path)
    fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, abs_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _real_yield_pct(protocol_revenue_daily_usd: float, total_tvl_usd: float) -> float:
    """Annualized real protocol revenue as % of TVL."""
    if total_tvl_usd <= 0:
        return 0.0
    annual_revenue = max(0.0, protocol_revenue_daily_usd) * _DAYS_PER_YEAR
    return annual_revenue / total_tvl_usd * 100.0


def _dilution_yield_pct(
    native_token_emission_rate_per_day: float,
    native_token_price_usd: float,
    total_tvl_usd: float,
) -> float:
    """Annualized token emission value as % of TVL (the 'dilution' APY)."""
    if total_tvl_usd <= 0:
        return 0.0
    daily_emission_usd = max(0.0, native_token_emission_rate_per_day) * max(0.0, native_token_price_usd)
    annual_emission_usd = daily_emission_usd * _DAYS_PER_YEAR
    return annual_emission_usd / total_tvl_usd * 100.0


def _fdv_to_revenue_ratio(
    token_fully_diluted_valuation_usd: float,
    protocol_revenue_daily_usd: float,
) -> float:
    """FDV / annual protocol revenue (P/E-like multiple).  0 if no revenue."""
    annual_revenue = max(0.0, protocol_revenue_daily_usd) * _DAYS_PER_YEAR
    if annual_revenue <= 0:
        return float("inf") if token_fully_diluted_valuation_usd > 0 else 0.0
    return max(0.0, token_fully_diluted_valuation_usd) / annual_revenue


def _dilution_ratio(dilution_yield: float, real_yield: float) -> float:
    """Ratio of dilution APY to real yield APY (higher → more dilution-driven)."""
    return dilution_yield / max(real_yield, _EPSILON)


def _dilution_base_score(ratio: float) -> float:
    """
    0-100 base score derived from the dilution ratio.

    ratio ≤ 0.5  → 90-100  (emissions well-backed by real yield)
    0.5–1.0      → 75-90   (sustainable with room to improve)
    1.0–3.0      → 50-75   (manageable dilution)
    3.0–10.0     → 25-50   (high dilution)
    10.0–50.0    → 5-25    (hyperinflationary)
    > 50.0       → 0-5     (death spiral territory)
    """
    if ratio <= 0.0:
        return 100.0
    elif ratio <= 0.5:
        return 100.0 - ratio * 20.0            # 100 → 90
    elif ratio <= 1.0:
        return 90.0 - (ratio - 0.5) * 30.0    # 90 → 75
    elif ratio <= 3.0:
        return 75.0 - (ratio - 1.0) / 2.0 * 25.0  # 75 → 50
    elif ratio <= 10.0:
        return 50.0 - (ratio - 3.0) / 7.0 * 25.0  # 50 → 25
    elif ratio <= 50.0:
        return 25.0 - (ratio - 10.0) / 40.0 * 20.0  # 25 → 5
    else:
        return max(0.0, 5.0 - (ratio - 50.0) * 0.1)  # 5 → 0


def _fdv_penalty(fdv_ratio: float) -> float:
    """
    Penalty score (0-30) based on the FDV-to-revenue multiple.

    Protocols with very high multiples are less likely to sustain emissions.
    """
    if fdv_ratio <= 0 or fdv_ratio != fdv_ratio:  # 0 or NaN
        return 0.0
    if fdv_ratio == float("inf") or fdv_ratio > 1000.0:
        return 30.0
    elif fdv_ratio > 500.0:
        return 25.0 + (fdv_ratio - 500.0) / 500.0 * 5.0
    elif fdv_ratio > 200.0:
        return 20.0 + (fdv_ratio - 200.0) / 300.0 * 5.0
    elif fdv_ratio > 100.0:
        return 15.0 + (fdv_ratio - 100.0) / 100.0 * 5.0
    elif fdv_ratio > 50.0:
        return 10.0 + (fdv_ratio - 50.0) / 50.0 * 5.0
    elif fdv_ratio > 20.0:
        return 5.0 + (fdv_ratio - 20.0) / 30.0 * 5.0
    else:
        return 0.0


def _schedule_modifier(
    dilution_ratio: float,
    emission_schedule_years_remaining: float,
) -> float:
    """
    Adjust score for remaining emission schedule.

    Short schedules reduce dilution risk (emissions end soon); very long
    schedules with high dilution amplify risk.
    """
    years = max(0.0, emission_schedule_years_remaining)
    if dilution_ratio <= 1.0 or years <= 0:
        return 0.0  # no adjustment needed when emissions are sustainable
    if years < 1.0:
        return 5.0  # small bonus: emissions nearly done
    elif years < 2.0:
        return 2.0
    elif years > 10.0:
        return -10.0  # long-tail high dilution is worse
    elif years > 5.0:
        return -5.0
    return 0.0


def _emission_sustainability_score(
    dilution_ratio: float,
    fdv_ratio: float,
    emission_schedule_years_remaining: float,
) -> float:
    """Return 0-100 emission sustainability score."""
    base = _dilution_base_score(dilution_ratio)
    penalty = _fdv_penalty(fdv_ratio)
    modifier = _schedule_modifier(dilution_ratio, emission_schedule_years_remaining)
    score = base - penalty + modifier
    return max(0.0, min(100.0, score))


def _label(score: float, dilution_ratio: float) -> str:
    """
    Classify the liquidity mining dilution state.

    Labels (in order):
      DEATH_SPIRAL_EMISSIONS – score < 10 or dilution_ratio > 50
      HYPERINFLATIONARY      – score < 25
      HIGH_DILUTION          – score < 50
      MANAGEABLE             – score < 75
      SUSTAINABLE_EMISSIONS  – score ≥ 75
    """
    if dilution_ratio > 50.0 or score < 10.0:
        return "DEATH_SPIRAL_EMISSIONS"
    if score < 25.0:
        return "HYPERINFLATIONARY"
    if score < 50.0:
        return "HIGH_DILUTION"
    if score < 75.0:
        return "MANAGEABLE"
    return "SUSTAINABLE_EMISSIONS"


def _build_recommendations(
    label: str,
    real_yield: float,
    dilution_yield: float,
    dilution_ratio: float,
    fdv_ratio: float,
    emission_schedule_years_remaining: float,
    protocol_name: str,
) -> list[str]:
    """Return advisory recommendations based on the dilution verdict."""
    recs: list[str] = []

    if label == "DEATH_SPIRAL_EMISSIONS":
        recs.append(
            f"{protocol_name}: Token emissions ({dilution_yield:.1f}% dilution APY) "
            f"are catastrophically unsustainable vs real yield ({real_yield:.2f}%). "
            f"Avoid or exit positions — death spiral risk is high."
        )
    elif label == "HYPERINFLATIONARY":
        recs.append(
            f"{protocol_name}: Severe dilution ({dilution_yield:.1f}% APY) "
            f"vastly exceeds real yield ({real_yield:.2f}%). "
            f"Token price likely to collapse without strong demand catalyst."
        )
    elif label == "HIGH_DILUTION":
        recs.append(
            f"{protocol_name}: High dilution rate ({dilution_yield:.1f}% APY) "
            f"relative to real yield ({real_yield:.2f}%). "
            f"Monitor token price trajectory carefully."
        )
    elif label == "MANAGEABLE":
        recs.append(
            f"{protocol_name}: Manageable emissions ({dilution_yield:.1f}% APY). "
            f"Real yield ({real_yield:.2f}%) partially covers dilution. "
            f"Watch FDV/revenue ratio."
        )
    else:  # SUSTAINABLE_EMISSIONS
        recs.append(
            f"{protocol_name}: Emissions are sustainable. "
            f"Real yield ({real_yield:.2f}%) backs dilution ({dilution_yield:.1f}%). "
            f"Strong fundamental backing."
        )

    if fdv_ratio != float("inf") and fdv_ratio > 100.0:
        recs.append(
            f"High FDV/revenue ratio ({fdv_ratio:.1f}x) suggests token is "
            f"priced for substantial future growth — revisit if growth stalls."
        )

    if emission_schedule_years_remaining > 0 and emission_schedule_years_remaining < 1.0:
        recs.append(
            f"Emissions end in < 1 year; real yield importance increases soon."
        )
    elif emission_schedule_years_remaining > 8.0 and dilution_ratio > 2.0:
        recs.append(
            f"Long emission schedule ({emission_schedule_years_remaining:.0f} years) "
            f"with high dilution — sustained sell pressure expected."
        )

    return recs


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class ProtocolDeFiLiquidityMiningDilutionAnalyzer:
    """
    Analyzes liquidity mining dilution vs real yield for DeFi protocols.

    Usage
    -----
    analyzer = ProtocolDeFiLiquidityMiningDilutionAnalyzer()
    result   = analyzer.analyze(protocol_data)
    """

    def __init__(self, config: dict | None = None) -> None:
        cfg = config or {}
        self._log_path: str = cfg.get("log_path", _LOG_PATH)

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def analyze(self, protocol_data: dict) -> dict[str, Any]:
        """
        Analyze liquidity mining dilution for a protocol.

        Parameters
        ----------
        protocol_data : dict
            - protocol_name                    : str
            - native_token_emission_rate_per_day: float (tokens/day emitted as rewards)
            - native_token_price_usd            : float (current token price in USD)
            - total_tvl_usd                     : float (total value locked)
            - protocol_revenue_daily_usd        : float (daily on-chain revenue to protocol)
            - token_fully_diluted_valuation_usd : float (FDV of native token)
            - emission_schedule_years_remaining : float (years until emissions end)

        Returns
        -------
        dict with full dilution analysis including score, label, recommendations.
        """
        protocol_name = protocol_data.get("protocol_name", "UNKNOWN")
        emission_rate   = float(protocol_data.get("native_token_emission_rate_per_day", 0.0))
        token_price     = float(protocol_data.get("native_token_price_usd", 0.0))
        tvl             = float(protocol_data.get("total_tvl_usd", 0.0))
        revenue_daily   = float(protocol_data.get("protocol_revenue_daily_usd", 0.0))
        fdv             = float(protocol_data.get("token_fully_diluted_valuation_usd", 0.0))
        schedule_years  = float(protocol_data.get("emission_schedule_years_remaining", 0.0))

        # Clamp
        emission_rate  = max(0.0, emission_rate)
        token_price    = max(0.0, token_price)
        tvl            = max(0.0, tvl)
        revenue_daily  = max(0.0, revenue_daily)
        fdv            = max(0.0, fdv)
        schedule_years = max(0.0, schedule_years)

        # Core metrics
        real_yield    = _real_yield_pct(revenue_daily, tvl)
        dilution      = _dilution_yield_pct(emission_rate, token_price, tvl)
        total_yield   = real_yield + dilution
        dil_ratio     = _dilution_ratio(dilution, real_yield)
        fdv_ratio     = _fdv_to_revenue_ratio(fdv, revenue_daily)

        # FDV ratio for JSON serialization (inf → very large sentinel)
        fdv_ratio_serializable = fdv_ratio if fdv_ratio != float("inf") else 9_999_999.0

        score         = _emission_sustainability_score(dil_ratio, fdv_ratio, schedule_years)
        lbl           = _label(score, dil_ratio)
        recs          = _build_recommendations(
            lbl, real_yield, dilution, dil_ratio,
            fdv_ratio, schedule_years, protocol_name
        )

        ts = time.time()
        result: dict[str, Any] = {
            "protocol_name": protocol_name,
            "native_token_emission_rate_per_day": emission_rate,
            "native_token_price_usd": token_price,
            "total_tvl_usd": tvl,
            "protocol_revenue_daily_usd": revenue_daily,
            "token_fully_diluted_valuation_usd": fdv,
            "emission_schedule_years_remaining": schedule_years,
            "real_yield_pct": round(real_yield, 4),
            "dilution_yield_pct": round(dilution, 4),
            "total_yield_pct": round(total_yield, 4),
            "dilution_ratio": round(dil_ratio, 4),
            "fdv_to_revenue_ratio": round(fdv_ratio_serializable, 2),
            "emission_sustainability_score": round(score, 4),
            "label": lbl,
            "recommendations": recs,
            "timestamp": ts,
        }

        try:
            _atomic_log(self._log_path, result)
        except Exception:
            pass  # advisory: never crash caller

        return result


# ---------------------------------------------------------------------------
# Module-level convenience wrapper
# ---------------------------------------------------------------------------

def analyze(protocol_data: dict, config: dict | None = None) -> dict:
    """Module-level shortcut for ProtocolDeFiLiquidityMiningDilutionAnalyzer.analyze."""
    return ProtocolDeFiLiquidityMiningDilutionAnalyzer(config).analyze(protocol_data)


# ---------------------------------------------------------------------------
# CLI demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    _demo = {
        "protocol_name": "CurveFinance",
        "native_token_emission_rate_per_day": 500_000.0,   # CRV/day
        "native_token_price_usd": 0.35,
        "total_tvl_usd": 1_500_000_000.0,
        "protocol_revenue_daily_usd": 200_000.0,
        "token_fully_diluted_valuation_usd": 1_200_000_000.0,
        "emission_schedule_years_remaining": 4.0,
    }

    r = analyze(_demo)
    print(json.dumps(r, indent=2, default=str))
    sys.exit(0)
