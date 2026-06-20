"""
MP-1118 DeFiProtocolRealYieldSustainabilityRater
-------------------------------------------------
Rates the sustainability of "real yield" claims. Real yield = protocol revenue
distributed to stakers/LPs, not token emissions. Verifies that claimed real
yield is backed by actual fee revenue.

Advisory / read-only.  Pure stdlib.  Atomic ring-buffer JSON log (cap 100).
"""

from __future__ import annotations

import json
import os
import time
from typing import Any
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_LOG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data",
    "real_yield_sustainability_log.json"
)
_LOG_CAP = 100

# Sustainability label thresholds (by real_yield_ratio)
_FULLY_REAL_THRESHOLD      = 0.9
_MOSTLY_REAL_THRESHOLD     = 0.7
_MIXED_THRESHOLD           = 0.4
_MOSTLY_EMISSION_THRESHOLD = 0.1

# Score component max points
_RATIO_MAX_PTS   = 60
_GROWTH_MAX_PTS  = 25
_EXPENSE_MAX_PTS = 15


# ---------------------------------------------------------------------------
# Internal helpers (module-level for direct unit testing)
# ---------------------------------------------------------------------------

def _atomic_log(log_path: str, entry: dict) -> None:
    """Append *entry* to ring-buffer JSON array (cap=_LOG_CAP), atomic write."""
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
    atomic_save(data, str(abs_path))
def _annualized_revenue_usd(protocol_revenue_7d_usd: float) -> float:
    """Annualize 7-day revenue: revenue_7d * 52 (52 weeks/year).

    Returns 0.0 for zero or negative input.
    """
    return round(float(protocol_revenue_7d_usd) * 52.0, 6)


def _real_yield_apy_pct(
    protocol_revenue_7d_usd: float,
    protocol_expenses_7d_usd: float,
    total_staked_usd: float,
) -> float:
    """Annualized real yield APY: (revenue - expenses) * 52 / staked * 100.

    Net 7-day revenue is floored at 0.0 so expenses cannot produce negative yield.
    Returns 0.0 when total_staked_usd <= 0.
    """
    if total_staked_usd <= 0.0:
        return 0.0
    net_7d = max(0.0, float(protocol_revenue_7d_usd) - float(protocol_expenses_7d_usd))
    return round(net_7d * 52.0 / float(total_staked_usd) * 100.0, 6)


def _emission_yield_apy_pct(
    token_emission_7d_usd: float,
    total_staked_usd: float,
) -> float:
    """Annualized emission yield APY: emission_7d * 52 / staked * 100.

    Returns 0.0 when total_staked_usd <= 0.
    """
    if total_staked_usd <= 0.0:
        return 0.0
    return round(float(token_emission_7d_usd) * 52.0 / float(total_staked_usd) * 100.0, 6)


def _real_yield_ratio(real_yield_apy_pct: float, claimed_apy_pct: float) -> float:
    """Ratio of real yield to claimed APY.  1.0 = fully backed.

    Can exceed 1.0 when real yield > claimed (over-backed).
    When claimed_apy_pct <= 0 and real_yield > 0  → returns 1.0.
    When both ≤ 0                                  → returns 0.0.
    Rounded to 6 decimal places.
    """
    if claimed_apy_pct <= 0.0:
        return 1.0 if real_yield_apy_pct > 0.0 else 0.0
    return round(float(real_yield_apy_pct) / float(claimed_apy_pct), 6)


def _revenue_yield_gap_pct(claimed_apy_pct: float, real_yield_apy_pct: float) -> float:
    """Inflated portion of claimed yield: claimed - real_yield.

    Positive  → claimed > real (emission-inflated).
    Negative  → real yield exceeds claimed (over-backed).
    """
    return round(float(claimed_apy_pct) - float(real_yield_apy_pct), 6)


def _sustainability_label(real_yield_ratio: float) -> str:
    """Map real_yield_ratio → sustainability label (one of five categories)."""
    if real_yield_ratio >= _FULLY_REAL_THRESHOLD:
        return "FULLY_REAL_YIELD"
    if real_yield_ratio >= _MOSTLY_REAL_THRESHOLD:
        return "MOSTLY_REAL"
    if real_yield_ratio >= _MIXED_THRESHOLD:
        return "MIXED_REAL_EMISSION"
    if real_yield_ratio >= _MOSTLY_EMISSION_THRESHOLD:
        return "MOSTLY_EMISSION"
    return "PURE_PONZI"


def _growth_score(revenue_growth_30d_pct: float) -> float:
    """Revenue growth contribution to sustainability score (0–25 pts).

    Growing revenue signals a sustainable, expanding fee base.

    Growth ≥ 30 %  → 25 pts
    Growth ≥ 15 %  → 20 pts
    Growth ≥  5 %  → 15 pts
    Growth ≥  0 %  → 10 pts
    Growth ≥ -10 % →  5 pts
    Growth <  -10% →  0 pts
    """
    g = float(revenue_growth_30d_pct)
    if g >= 30.0:
        return 25.0
    if g >= 15.0:
        return 20.0
    if g >= 5.0:
        return 15.0
    if g >= 0.0:
        return 10.0
    if g >= -10.0:
        return 5.0
    return 0.0


def _expense_score(
    protocol_revenue_7d_usd: float,
    protocol_expenses_7d_usd: float,
) -> float:
    """Expense-efficiency contribution to sustainability score (0–15 pts).

    Lower expense-to-revenue ratio means more revenue flows to stakers.
    Returns neutral 15 pts when revenue or expenses are zero/unknown.

    expense_ratio ≤ 0.10 → 15 pts
    expense_ratio ≤ 0.30 → 10 pts
    expense_ratio ≤ 0.50 →  5 pts
    expense_ratio  > 0.50 →  0 pts
    """
    rev = float(protocol_revenue_7d_usd)
    exp = float(protocol_expenses_7d_usd)
    if rev <= 0.0 or exp <= 0.0:
        return 15.0  # neutral / unknown
    ratio = exp / rev
    if ratio <= 0.10:
        return 15.0
    if ratio <= 0.30:
        return 10.0
    if ratio <= 0.50:
        return 5.0
    return 0.0


def _sustainability_score(
    real_yield_ratio: float,
    revenue_growth_30d_pct: float,
    protocol_revenue_7d_usd: float,
    protocol_expenses_7d_usd: float,
) -> int:
    """Composite sustainability score 0–100 (int).

    Components
    ----------
    Real yield ratio  (0–60): higher real-yield backing → more sustainable.
    Revenue growth    (0–25): positive growth → growing fee base.
    Expense efficiency(0–15): low expense ratio → more revenue to stakers.
    """
    ratio_clamped = min(1.0, max(0.0, float(real_yield_ratio)))
    ratio_pts   = ratio_clamped * _RATIO_MAX_PTS
    growth_pts  = _growth_score(revenue_growth_30d_pct)
    expense_pts = _expense_score(protocol_revenue_7d_usd, protocol_expenses_7d_usd)
    total = ratio_pts + growth_pts + expense_pts
    return int(min(100, max(0, round(total))))


# ---------------------------------------------------------------------------
# Main analyzer class
# ---------------------------------------------------------------------------

class DeFiProtocolRealYieldSustainabilityRater:
    """
    Rates the sustainability of 'real yield' claims for DeFi protocols.

    Real yield = protocol revenue distributed to stakers/LPs, not token emissions.
    Verifies that the claimed APY is backed by actual fee revenue.

    Advisory / read-only — never modifies positions, risk policy, or trades.

    Usage
    -----
    rater  = DeFiProtocolRealYieldSustainabilityRater()
    result = rater.rate(data)
    """

    def rate(self, data: dict, config: dict | None = None) -> dict:
        """
        Rate real yield sustainability for a single protocol.

        Parameters
        ----------
        data : dict
            protocol_name             : str
            claimed_apy_pct           : float — protocol's advertised APY (%)
            protocol_revenue_7d_usd   : float — actual fee revenue last 7 days (USD)
            token_emission_7d_usd     : float — value of tokens emitted last 7 days (USD)
            total_staked_usd          : float — total value staked / deposited (USD)
            protocol_expenses_7d_usd  : float — team / ops costs last 7 days (0 if unknown)
            revenue_growth_30d_pct    : float — MoM revenue growth (%)

        config : dict, optional
            log_path  : str  — override default log file path
            write_log : bool — write to log (default True)

        Returns
        -------
        dict
            protocol_name, claimed_apy_pct, annualized_revenue_usd,
            real_yield_apy_pct, emission_yield_apy_pct, real_yield_ratio,
            revenue_yield_gap_pct, sustainability_score, sustainability_label,
            timestamp
        """
        cfg       = config or {}
        log_path  = cfg.get("log_path", _LOG_PATH)
        write_log = cfg.get("write_log", True)

        name         = str(data.get("protocol_name", "UNKNOWN"))
        claimed_apy  = float(data.get("claimed_apy_pct", 0.0))
        revenue_7d   = float(data.get("protocol_revenue_7d_usd", 0.0))
        emission_7d  = float(data.get("token_emission_7d_usd", 0.0))
        staked       = float(data.get("total_staked_usd", 0.0))
        expenses_7d  = float(data.get("protocol_expenses_7d_usd", 0.0))
        growth_30d   = float(data.get("revenue_growth_30d_pct", 0.0))

        ann_revenue  = _annualized_revenue_usd(revenue_7d)
        real_apy     = _real_yield_apy_pct(revenue_7d, expenses_7d, staked)
        emission_apy = _emission_yield_apy_pct(emission_7d, staked)
        ratio        = _real_yield_ratio(real_apy, claimed_apy)
        gap_pct      = _revenue_yield_gap_pct(claimed_apy, real_apy)
        score        = _sustainability_score(ratio, growth_30d, revenue_7d, expenses_7d)
        label        = _sustainability_label(ratio)

        ts: str = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        result: dict[str, Any] = {
            "protocol_name":          name,
            "claimed_apy_pct":        claimed_apy,
            "annualized_revenue_usd": ann_revenue,
            "real_yield_apy_pct":     real_apy,
            "emission_yield_apy_pct": emission_apy,
            "real_yield_ratio":       ratio,
            "revenue_yield_gap_pct":  gap_pct,
            "sustainability_score":   score,
            "sustainability_label":   label,
            "timestamp":              ts,
        }

        if write_log:
            _atomic_log(log_path, {
                "timestamp":            ts,
                "protocol_name":        name,
                "real_yield_ratio":     ratio,
                "sustainability_score": score,
                "sustainability_label": label,
            })

        return result


# ---------------------------------------------------------------------------
# Module-level convenience function
# ---------------------------------------------------------------------------

def rate(data: dict, config: dict | None = None) -> dict:
    """Module-level convenience wrapper around DeFiProtocolRealYieldSustainabilityRater."""
    return DeFiProtocolRealYieldSustainabilityRater().rate(data, config)
