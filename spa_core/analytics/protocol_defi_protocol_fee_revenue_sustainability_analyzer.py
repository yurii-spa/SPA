"""
MP-1065 ProtocolDeFiFeeRevenueSustainabilityAnalyzer
-----------------------------------------------------
Analyzes the sustainability of a DeFi protocol's fee revenue model,
examining profit margin, treasury runway, fee competitiveness, and
revenue trend from historical data.

Advisory / read-only.  Pure stdlib.  Atomic ring-buffer JSON log (cap 100).
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
    "fee_revenue_sustainability_log.json"
)
_LOG_CAP = 100

# sustainability_label thresholds
_SELF_SUSTAINING_MARGIN  = 30.0   # profit_margin_pct ≥ this AND runway ≥ below
_SELF_SUSTAINING_RUNWAY  = 24.0   # months
_HEALTHY_MARGIN          = 0.0    # profit_margin_pct ≥ 0
_BREAK_EVEN_MARGIN       = -10.0  # profit_margin_pct ≥ -10
_TREASURY_DEPENDENT_RUNWAY = 6.0  # runway > 6 months but margin < -10

# Infinite-runway sentinel (when protocol is profitable = no burn)
_INFINITE_RUNWAY = 9999.0


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
    fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        os.replace(tmp_path, abs_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _profit_margin_pct(
    fee_revenue_30d_usd: float,
    operational_costs_30d_usd: float,
    token_buyback_30d_usd: float,
) -> float:
    """
    Profit margin after operational costs and token buybacks.

    = (fee_revenue - operational_costs - token_buyback) / fee_revenue * 100

    Returns 0.0 when all inputs are zero.
    Returns -100.0 when revenue is 0 but there are costs/buybacks.
    """
    total_out = operational_costs_30d_usd + token_buyback_30d_usd
    if fee_revenue_30d_usd <= 0.0:
        return -100.0 if total_out > 0.0 else 0.0
    profit = fee_revenue_30d_usd - total_out
    return round(profit / fee_revenue_30d_usd * 100.0, 4)


def _runway_months(
    treasury_usd: float,
    fee_revenue_30d_usd: float,
    operational_costs_30d_usd: float,
) -> float:
    """
    Treasury runway in months.

    monthly_burn = max(0, operational_costs - fee_revenue).
    If monthly_burn == 0 (protocol is profitable), returns _INFINITE_RUNWAY.
    If treasury == 0 and there is a burn, returns 0.0.
    """
    monthly_burn = max(0.0, operational_costs_30d_usd - fee_revenue_30d_usd)
    if monthly_burn <= 0.0:
        return _INFINITE_RUNWAY
    if treasury_usd <= 0.0:
        return 0.0
    return round(treasury_usd / monthly_burn, 2)


def _fee_competitiveness_score(
    own_fee_rate_bps: float,
    competitor_fee_rate_bps: float,
) -> float:
    """
    0–100 score. Lower own fee relative to competitor = more competitive = higher score.

    Formula: score = clamp(0, 100, (1 - ratio) * 50 + 50)
    where ratio = own_bps / competitor_bps.

    Special cases:
      both 0      → 50 (neutral)
      own 0       → 100 (free beats any competitor)
      competitor 0, own > 0 → 0 (charging while competitor is free)
    """
    if own_fee_rate_bps <= 0.0 and competitor_fee_rate_bps <= 0.0:
        return 50.0
    if own_fee_rate_bps <= 0.0:
        return 100.0
    if competitor_fee_rate_bps <= 0.0:
        return 0.0
    ratio = own_fee_rate_bps / competitor_fee_rate_bps
    score = (1.0 - ratio) * 50.0 + 50.0
    return round(max(0.0, min(100.0, score)), 2)


def _revenue_trend_pct(fee_revenue_history: list) -> float:
    """
    Month-over-month revenue trend from the last two entries of *fee_revenue_history*.

    Returns 0.0 when:
      - history is empty or has fewer than 2 entries
      - previous month revenue is 0
    """
    if not fee_revenue_history or len(fee_revenue_history) < 2:
        return 0.0
    prev = float(fee_revenue_history[-2])
    curr = float(fee_revenue_history[-1])
    if prev <= 0.0:
        return 0.0
    return round((curr - prev) / prev * 100.0, 4)


def _sustainability_label(profit_margin: float, runway: float) -> str:
    """
    Map (profit_margin_pct, runway_months) → sustainability label.

    Labels (in priority order):
      SELF_SUSTAINING    : margin ≥ 30 % AND runway ≥ 24 months
      HEALTHY            : margin ≥ 0 %
      BREAK_EVEN         : margin ≥ -10 %
      TREASURY_DEPENDENT : margin < -10 % but runway > 6 months
      INSOLVENT_TRAJECTORY: margin < -10 % and runway ≤ 6 months
    """
    if profit_margin >= _SELF_SUSTAINING_MARGIN and runway >= _SELF_SUSTAINING_RUNWAY:
        return "SELF_SUSTAINING"
    if profit_margin >= _HEALTHY_MARGIN:
        return "HEALTHY"
    if profit_margin >= _BREAK_EVEN_MARGIN:
        return "BREAK_EVEN"
    if runway > _TREASURY_DEPENDENT_RUNWAY:
        return "TREASURY_DEPENDENT"
    return "INSOLVENT_TRAJECTORY"


# ---------------------------------------------------------------------------
# Main analyzer class
# ---------------------------------------------------------------------------

class ProtocolDeFiFeeRevenueSustainabilityAnalyzer:
    """
    Analyzes fee revenue sustainability for a single DeFi protocol.

    Advisory / read-only — never modifies positions, risk policy, or trades.

    Usage
    -----
    analyzer = ProtocolDeFiFeeRevenueSustainabilityAnalyzer()
    result   = analyzer.analyze(data)
    """

    def analyze(self, data: dict, config: dict | None = None) -> dict:
        """
        Analyze fee revenue sustainability.

        Parameters
        ----------
        data : dict
            protocol_name            : str
            fee_revenue_30d_usd      : float — 30-day fee revenue (USD)
            operational_costs_30d_usd: float — 30-day operating costs (USD)
            token_buyback_30d_usd    : float — 30-day token buybacks (USD)
            treasury_usd             : float — current treasury size (USD)
            tvl_usd                  : float — total value locked (USD)
            monthly_active_users     : float — MAU count
            fee_revenue_history      : list[float] — last 6 months of monthly revenue
            competitor_fee_rate_bps  : float — competitor fee rate (basis points)
            own_fee_rate_bps         : float — protocol's own fee rate (basis points)

        config : dict, optional
            log_path  : str   — override default log file path
            write_log : bool  — write to log (default True)

        Returns
        -------
        dict
            protocol_name, profit_margin_pct, runway_months,
            fee_competitiveness_score, revenue_trend_pct,
            sustainability_label, tvl_usd, monthly_active_users, timestamp
        """
        cfg = config or {}
        log_path  = cfg.get("log_path", _LOG_PATH)
        write_log = cfg.get("write_log", True)

        name         = str(data.get("protocol_name", "UNKNOWN"))
        fee_rev      = float(data.get("fee_revenue_30d_usd", 0.0))
        op_costs     = float(data.get("operational_costs_30d_usd", 0.0))
        buyback      = float(data.get("token_buyback_30d_usd", 0.0))
        treasury     = float(data.get("treasury_usd", 0.0))
        tvl          = float(data.get("tvl_usd", 0.0))
        mau          = float(data.get("monthly_active_users", 0.0))
        history      = list(data.get("fee_revenue_history", []))
        comp_bps     = float(data.get("competitor_fee_rate_bps", 0.0))
        own_bps      = float(data.get("own_fee_rate_bps", 0.0))

        margin       = _profit_margin_pct(fee_rev, op_costs, buyback)
        runway       = _runway_months(treasury, fee_rev, op_costs)
        fee_score    = _fee_competitiveness_score(own_bps, comp_bps)
        trend        = _revenue_trend_pct(history)
        label        = _sustainability_label(margin, runway)

        ts: str = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        result: dict[str, Any] = {
            "protocol_name":           name,
            "profit_margin_pct":       margin,
            "runway_months":           runway,
            "fee_competitiveness_score": fee_score,
            "revenue_trend_pct":       trend,
            "sustainability_label":    label,
            "tvl_usd":                 tvl,
            "monthly_active_users":    mau,
            "timestamp":               ts,
        }

        if write_log:
            _atomic_log(log_path, {
                "timestamp":               ts,
                "protocol_name":           name,
                "profit_margin_pct":       margin,
                "runway_months":           runway,
                "fee_competitiveness_score": fee_score,
                "revenue_trend_pct":       trend,
                "sustainability_label":    label,
            })

        return result


# ---------------------------------------------------------------------------
# Module-level convenience function
# ---------------------------------------------------------------------------

def analyze(data: dict, config: dict | None = None) -> dict:
    """Module-level convenience wrapper around ProtocolDeFiFeeRevenueSustainabilityAnalyzer."""
    return ProtocolDeFiFeeRevenueSustainabilityAnalyzer().analyze(data, config)
