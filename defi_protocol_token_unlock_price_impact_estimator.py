"""
MP-1068: DeFi Protocol Token Unlock Price Impact Estimator
Estimates the price impact of upcoming token unlock events.
Pure stdlib, no external dependencies. Read-only / advisory.
"""
import json
import os
import datetime
from typing import Optional

# ---------------------------------------------------------------------------
# Defaults & constants
# ---------------------------------------------------------------------------

LOG_PATH_DEFAULT = "data/token_unlock_price_impact_log.json"
LOG_CAP_DEFAULT = 100

# Fraction of unlocked tokens that each recipient type is expected to sell.
SELL_PRESSURE_BY_RECIPIENT = {
    "team": 0.60,
    "investor": 0.70,
    "community": 0.20,
    "ecosystem": 0.25,
    "treasury": 0.10,
    "advisor": 0.65,
    "public": 0.15,
}
_DEFAULT_SELL_PRESSURE = 0.50  # fallback for unknown recipient types

# Risk label thresholds (price_impact_pct, ascending)
_LABEL_THRESHOLDS = [
    (1.0,  "NEGLIGIBLE_IMPACT"),
    (5.0,  "LOW_IMPACT"),
    (15.0, "MODERATE_IMPACT"),
    (30.0, "SIGNIFICANT_DROP_RISK"),
]
_LABEL_EXTREME = "EXTREME_SELL_PRESSURE"

VALID_LABELS = frozenset([
    "NEGLIGIBLE_IMPACT",
    "LOW_IMPACT",
    "MODERATE_IMPACT",
    "SIGNIFICANT_DROP_RISK",
    "EXTREME_SELL_PRESSURE",
])


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, float(value)))


def _safe_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class DeFiProtocolTokenUnlockPriceImpactEstimator:
    """
    Estimates the expected price impact of a DeFi protocol token unlock event.

    Input fields (all in the *payload* dict passed to ``estimate``):
        token_name              str   – human-readable token / protocol name
        current_price_usd       float – current token price in USD
        current_market_cap_usd  float – current market cap (USD)
        unlock_amount_tokens    float – number of tokens being unlocked
        unlock_date_days_from_now int  – days until unlock occurs
        avg_daily_volume_usd    float – 30-day average daily trading volume (USD)
        recipient_type          str   – one of team/investor/community/ecosystem/treasury/advisor/public
        vesting_cliff_months    int   – remaining cliff (0 = immediate)
        protocol_revenue_usd_per_month float – monthly on-chain revenue (0 if unknown)
        staking_locked_pct      float – % of total supply that is staked/locked (0–100)

    Output keys:
        token_name              str
        unlock_value_usd        float – market value of unlocked tokens (at current price)
        volume_ratio            float – unlock_value_usd / (30 × avg_daily_volume_usd)
        estimated_sell_pressure_pct float – fraction expected to sell (0–1)
        price_impact_pct        float – estimated downside price impact (positive number, %)
        unlock_risk_label       str   – one of the VALID_LABELS
    """

    def __init__(self, log_path: Optional[str] = None, log_cap: int = LOG_CAP_DEFAULT):
        self._log_path = log_path or LOG_PATH_DEFAULT
        self._log_cap = max(1, int(log_cap))

    # ------------------------------------------------------------------
    # Core computation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _sell_pressure_for_recipient(recipient_type: str) -> float:
        """Return fraction (0–1) of unlocked tokens expected to be sold."""
        rt = (recipient_type or "").strip().lower()
        return SELL_PRESSURE_BY_RECIPIENT.get(rt, _DEFAULT_SELL_PRESSURE)

    @staticmethod
    def _staking_absorption_factor(staking_locked_pct: float) -> float:
        """
        Higher staking absorption means fewer tokens circulate immediately.
        Returns a multiplier in (0, 1] that reduces effective sell pressure.
        staking_locked_pct in [0, 100].
        """
        pct = _clamp(staking_locked_pct, 0.0, 100.0)
        # linear: 0% staking → factor 1.0 (no reduction), 100% → factor 0.5
        return 1.0 - (pct / 200.0)

    @staticmethod
    def _cliff_multiplier(vesting_cliff_months: int) -> float:
        """
        Immediate cliff unlocks (cliff=0) are sold faster.
        Longer cliffs give time to absorb; multiplier tapers to 0.7 for 24+ months.
        """
        m = max(0, int(vesting_cliff_months))
        if m == 0:
            return 1.0
        if m <= 3:
            return 0.90
        if m <= 6:
            return 0.85
        if m <= 12:
            return 0.80
        return 0.70

    def _compute_unlock_value_usd(self, payload: dict) -> float:
        price = _safe_float(payload.get("current_price_usd", 0.0))
        amount = _safe_float(payload.get("unlock_amount_tokens", 0.0))
        return max(0.0, price * amount)

    def _compute_volume_ratio(self, unlock_value_usd: float, avg_daily_volume_usd: float) -> float:
        """
        volume_ratio = unlock_value_usd / 30-day_cumulative_volume.
        30d cumulative = avg_daily_volume_usd × 30.
        Returns 0 when volume is zero to avoid division errors.
        """
        monthly_volume = _safe_float(avg_daily_volume_usd) * 30.0
        if monthly_volume <= 0:
            return 0.0
        return unlock_value_usd / monthly_volume

    def _compute_estimated_sell_pressure_pct(self, payload: dict) -> float:
        """
        Combine recipient type base rate, cliff multiplier, and staking absorption.
        Returns fraction in [0, 1].
        """
        base = self._sell_pressure_for_recipient(payload.get("recipient_type", ""))
        cliff_m = self._cliff_multiplier(
            int(_safe_float(payload.get("vesting_cliff_months", 0), 0))
        )
        staking_factor = self._staking_absorption_factor(
            _safe_float(payload.get("staking_locked_pct", 0.0))
        )
        raw = base * cliff_m * staking_factor
        return _clamp(raw, 0.0, 1.0)

    def _compute_price_impact_pct(
        self,
        unlock_value_usd: float,
        estimated_sell_pressure_pct: float,
        payload: dict,
    ) -> float:
        """
        Simplified Amihud-inspired linear price-impact model:

            sell_usd        = unlock_value_usd × estimated_sell_pressure_pct
            market_cap      = current_market_cap_usd  (clamped ≥ 1)
            base_impact_pct = (sell_usd / market_cap) × 100 × depth_multiplier

        depth_multiplier accounts for thinness of order book vs volume ratio:
            depth_multiplier = 1 + volume_ratio  (capped at 5)

        Revenue credit: profitable protocols (revenue > 0) enjoy a modest
        demand cushion, reducing impact by up to 10%.

        Returns a positive percentage (price drop estimate).
        """
        market_cap = max(_safe_float(payload.get("current_market_cap_usd", 1.0)), 1.0)
        avg_daily_volume = max(_safe_float(payload.get("avg_daily_volume_usd", 1.0)), 1.0)

        sell_usd = unlock_value_usd * estimated_sell_pressure_pct
        volume_ratio = self._compute_volume_ratio(unlock_value_usd, avg_daily_volume)

        depth_multiplier = min(1.0 + volume_ratio, 5.0)
        base_impact = (sell_usd / market_cap) * 100.0 * depth_multiplier

        # Revenue credit (−10% of base impact at most)
        revenue_per_month = _safe_float(payload.get("protocol_revenue_usd_per_month", 0.0))
        if revenue_per_month > 0 and market_cap > 0:
            # P/E-proxy: cap credit at 10% of base impact
            ps_ratio = market_cap / max(revenue_per_month * 12.0, 1.0)
            # lower P/S → stronger fundamental support → bigger credit
            credit_factor = _clamp(10.0 / max(ps_ratio, 1.0), 0.0, 10.0) / 100.0
            base_impact = base_impact * (1.0 - credit_factor)

        return round(_clamp(base_impact, 0.0, 100.0), 4)

    @staticmethod
    def _assign_label(price_impact_pct: float) -> str:
        for threshold, label in _LABEL_THRESHOLDS:
            if price_impact_pct < threshold:
                return label
        return _LABEL_EXTREME

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    def _append_log(self, entry: dict) -> None:
        """Atomically append *entry* to ring-buffer log (capped at log_cap)."""
        entries: list = []
        log_path = self._log_path
        if os.path.exists(log_path):
            try:
                with open(log_path, "r") as fh:
                    data = json.load(fh)
                    if isinstance(data, list):
                        entries = data
            except (json.JSONDecodeError, OSError):
                entries = []

        entries.append(entry)
        entries = entries[-self._log_cap:]

        dir_path = os.path.dirname(log_path) or "."
        os.makedirs(dir_path, exist_ok=True)
        tmp_path = log_path + ".tmp"
        with open(tmp_path, "w") as fh:
            json.dump(entries, fh, indent=2)
        os.replace(tmp_path, log_path)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def estimate(self, payload: dict) -> dict:
        """
        Estimate price impact for a single token unlock event.

        Parameters
        ----------
        payload : dict
            Must include the input fields documented in the class docstring.

        Returns
        -------
        dict with keys: token_name, unlock_value_usd, volume_ratio,
            estimated_sell_pressure_pct, price_impact_pct, unlock_risk_label.
        """
        unlock_value_usd = self._compute_unlock_value_usd(payload)
        avg_daily_volume = _safe_float(payload.get("avg_daily_volume_usd", 0.0))
        volume_ratio = self._compute_volume_ratio(unlock_value_usd, avg_daily_volume)
        sell_pct = self._compute_estimated_sell_pressure_pct(payload)
        price_impact_pct = self._compute_price_impact_pct(unlock_value_usd, sell_pct, payload)
        label = self._assign_label(price_impact_pct)

        result = {
            "token_name": payload.get("token_name", ""),
            "unlock_value_usd": round(unlock_value_usd, 4),
            "volume_ratio": round(volume_ratio, 6),
            "estimated_sell_pressure_pct": round(sell_pct, 6),
            "price_impact_pct": price_impact_pct,
            "unlock_risk_label": label,
        }

        log_entry = {
            "ts": datetime.datetime.utcnow().isoformat() + "Z",
            "token_name": result["token_name"],
            "unlock_value_usd": result["unlock_value_usd"],
            "price_impact_pct": result["price_impact_pct"],
            "unlock_risk_label": result["unlock_risk_label"],
        }
        self._append_log(log_entry)
        return result

    def estimate_batch(self, payloads: list) -> list:
        """Estimate price impact for a list of token unlock payloads."""
        return [self.estimate(p) for p in (payloads or [])]
