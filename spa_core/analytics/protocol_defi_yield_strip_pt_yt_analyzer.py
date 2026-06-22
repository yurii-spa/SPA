"""
MP-1009: ProtocolDeFiYieldStripPtYtAnalyzer
Analyzes PT/YT yield-stripping positions (Pendle-style).
Pure stdlib, read-only analytics, atomic ring-buffer log.
"""

from __future__ import annotations

import json
import os
import time
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
LOG_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "data", "yield_strip_log.json")
LOG_CAP = 100

POSITION_LABELS = {
    "ATTRACTIVE_FIXED_RATE": "Attractive fixed rate — lock in above-market yield",
    "FAIR_VALUE": "Fair value — position priced in line with market",
    "OVERPRICED_PT": "Overpriced PT — carry too thin, better alternatives exist",
    "SPECULATIVE_YT_BULL": "Speculative YT — high leverage bet on rising rates",
    "YT_TIME_DECAY_RISK": "YT time-decay risk — near expiry, theta eating value",
    "NEAR_EXPIRY_ARBITRAGE": "Near-expiry arbitrage — PT close to face value",
}

FLAGS = {
    "HIGH_YT_LEVERAGE": "YT leverage factor exceeds 10×",
    "FIXED_RATE_ADVANTAGE": "PT fixed rate exceeds underlying APY by ≥ 2 pp",
    "EXPIRY_RISK": "YT position with maturity < 30 days",
    "ILLIQUID_EXIT": "Slippage to exit exceeds 100 bps",
    "STRONG_CARRY": "Carry (fixed rate – risk-free) exceeds 4 pp",
    "BREAK_EVEN_ACHIEVABLE": "YT break-even APY is within 1.2× of current underlying APY",
}


class ProtocolDeFiYieldStripPtYtAnalyzer:
    """Analyze Pendle-style PT/YT yield-stripping positions."""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self, positions: list[dict], config: dict) -> dict:
        """
        Parameters
        ----------
        positions:
            List of position dicts. Required keys per position:
              name, protocol, underlying_asset, maturity_date_days,
              pt_price_usd, yt_price_usd, underlying_apy_pct,
              implied_apy_pct, yt_leverage_factor, pt_face_value_usd,
              position_type ("pt_hold"/"yt_speculation"/"lp_pt_yt"/"fixed_rate_lock"),
              capital_usd, slippage_to_exit_bps
        config:
            Optional overrides, e.g. risk_free_rate_pct (default 4.0),
            attractive_carry_threshold (default 3.0),
            write_log (bool, default False).

        Returns
        -------
        dict  with keys: positions (list of analyzed results), aggregates
        """
        if not isinstance(positions, list):
            raise TypeError("positions must be a list")
        if not isinstance(config, dict):
            raise TypeError("config must be a dict")

        risk_free_rate = float(config.get("risk_free_rate_pct", 4.0))
        attractive_carry = float(config.get("attractive_carry_threshold", 3.0))
        write_log = bool(config.get("write_log", False))

        analyzed: list[dict] = []
        for pos in positions:
            analyzed.append(self._analyze_position(pos, risk_free_rate, attractive_carry))

        aggregates = self._aggregate(analyzed)
        result = {"positions": analyzed, "aggregates": aggregates}

        if write_log:
            self._write_log(result)

        return result

    # ------------------------------------------------------------------
    # Internal per-position analysis
    # ------------------------------------------------------------------

    def _analyze_position(self, pos: dict, risk_free_rate: float, attractive_carry: float) -> dict:
        name = str(pos.get("name", "unknown"))
        protocol = str(pos.get("protocol", "unknown"))
        underlying_asset = str(pos.get("underlying_asset", "unknown"))
        maturity_days = float(pos.get("maturity_date_days", 365))
        pt_price = float(pos.get("pt_price_usd", 0.95))
        yt_price = float(pos.get("yt_price_usd", 0.05))
        underlying_apy = float(pos.get("underlying_apy_pct", 5.0))
        implied_apy = float(pos.get("implied_apy_pct", 0.0))
        yt_leverage = float(pos.get("yt_leverage_factor", 0.0))
        pt_face_value = float(pos.get("pt_face_value_usd", 1.0))
        position_type = str(pos.get("position_type", "pt_hold"))
        capital_usd = float(pos.get("capital_usd", 0.0))
        slippage_bps = float(pos.get("slippage_to_exit_bps", 0.0))

        # ---- derived metrics -------------------------------------------

        # pt_fixed_rate_pct: annualised fixed return locked by buying PT at discount
        if pt_price > 0 and maturity_days > 0:
            pt_fixed_rate_pct = ((pt_face_value / pt_price) - 1.0) * (365.0 / maturity_days) * 100.0
        else:
            pt_fixed_rate_pct = 0.0

        # If implied_apy was not supplied, fall back to pt_fixed_rate_pct
        if implied_apy == 0.0:
            implied_apy = pt_fixed_rate_pct

        # yt_break_even_apy_pct: underlying APY needed for YT to break-even
        # YT pays (underlying_apy - implied_apy) * leverage; break-even when payout = yt_price * face
        # Simplified: break_even = implied_apy_pct (the market's embedded expectation)
        yt_break_even_apy_pct = implied_apy

        # yt_profit_loss_pct if current underlying_apy holds:
        # yt_pl = yt_leverage × (underlying_apy – break_even_apy)  (percentage points)
        if yt_leverage > 0:
            yt_profit_loss_pct = yt_leverage * (underlying_apy - yt_break_even_apy_pct)
        else:
            yt_profit_loss_pct = 0.0

        # time_value_decay_per_day: linear theta for YT (YT price / maturity_days remaining)
        if maturity_days > 0 and yt_price > 0:
            time_value_decay_per_day = yt_price / maturity_days
        else:
            time_value_decay_per_day = 0.0

        # carry_pct: spread over risk-free rate
        carry_pct = pt_fixed_rate_pct - risk_free_rate

        # ---- label -------------------------------------------------------
        label = self._compute_label(
            position_type=position_type,
            carry_pct=carry_pct,
            pt_price=pt_price,
            pt_face_value=pt_face_value,
            yt_leverage=yt_leverage,
            underlying_apy=underlying_apy,
            maturity_days=maturity_days,
            attractive_carry=attractive_carry,
        )

        # ---- flags -------------------------------------------------------
        flags: list[str] = []

        if yt_leverage > 10:
            flags.append("HIGH_YT_LEVERAGE")

        if pt_fixed_rate_pct > underlying_apy + 2.0:
            flags.append("FIXED_RATE_ADVANTAGE")

        if position_type in ("yt_speculation",) and maturity_days < 30:
            flags.append("EXPIRY_RISK")

        if slippage_bps > 100:
            flags.append("ILLIQUID_EXIT")

        if carry_pct > 4.0:
            flags.append("STRONG_CARRY")

        # BREAK_EVEN_ACHIEVABLE: break-even APY is reachable (≤ underlying * 1.2)
        if yt_break_even_apy_pct > 0 and underlying_apy > 0:
            if yt_break_even_apy_pct <= underlying_apy * 1.2:
                flags.append("BREAK_EVEN_ACHIEVABLE")

        return {
            "name": name,
            "protocol": protocol,
            "underlying_asset": underlying_asset,
            "maturity_date_days": maturity_days,
            "pt_fixed_rate_pct": round(pt_fixed_rate_pct, 4),
            "yt_break_even_apy_pct": round(yt_break_even_apy_pct, 4),
            "yt_profit_loss_pct": round(yt_profit_loss_pct, 4),
            "time_value_decay_per_day": round(time_value_decay_per_day, 6),
            "carry_pct": round(carry_pct, 4),
            "position_type": position_type,
            "capital_usd": capital_usd,
            "label": label,
            "flags": flags,
            # pass-through for aggregates
            "pt_price_usd": pt_price,
            "slippage_to_exit_bps": slippage_bps,
            "yt_leverage_factor": yt_leverage,
            "underlying_apy_pct": underlying_apy,
        }

    @staticmethod
    def _compute_label(
        position_type: str,
        carry_pct: float,
        pt_price: float,
        pt_face_value: float,
        yt_leverage: float,
        underlying_apy: float,
        maturity_days: float,
        attractive_carry: float,
    ) -> str:
        pt_discount_pct = ((pt_face_value - pt_price) / pt_face_value) * 100.0 if pt_face_value > 0 else 0.0

        # NEAR_EXPIRY_ARBITRAGE: PT very close to face value, short maturity
        if maturity_days < 7 and abs(pt_price - pt_face_value) < 0.01:
            return "NEAR_EXPIRY_ARBITRAGE"

        # YT_TIME_DECAY_RISK: YT position near expiry
        if position_type == "yt_speculation" and maturity_days < 30:
            return "YT_TIME_DECAY_RISK"

        # SPECULATIVE_YT_BULL: high leverage YT
        if position_type == "yt_speculation" and yt_leverage > 5 and underlying_apy > 0:
            return "SPECULATIVE_YT_BULL"

        # ATTRACTIVE_FIXED_RATE: carry > threshold AND PT discount > 5%
        if carry_pct >= attractive_carry and pt_discount_pct > 5.0:
            return "ATTRACTIVE_FIXED_RATE"

        # OVERPRICED_PT: carry too thin
        if carry_pct < 1.0 and position_type in ("pt_hold", "fixed_rate_lock"):
            return "OVERPRICED_PT"

        return "FAIR_VALUE"

    # ------------------------------------------------------------------
    # Aggregates
    # ------------------------------------------------------------------

    @staticmethod
    def _aggregate(analyzed: list[dict]) -> dict:
        if not analyzed:
            return {
                "best_fixed_rate": None,
                "worst_value": None,
                "avg_carry_pct": 0.0,
                "near_expiry_count": 0,
                "attractive_count": 0,
                "total_positions": 0,
            }

        best = max(analyzed, key=lambda x: x["pt_fixed_rate_pct"])
        worst = min(analyzed, key=lambda x: x["carry_pct"])

        avg_carry = sum(p["carry_pct"] for p in analyzed) / len(analyzed)
        near_expiry_count = sum(1 for p in analyzed if p["maturity_date_days"] < 30)
        attractive_count = sum(1 for p in analyzed if p["label"] == "ATTRACTIVE_FIXED_RATE")

        return {
            "best_fixed_rate": best["name"],
            "worst_value": worst["name"],
            "avg_carry_pct": round(avg_carry, 4),
            "near_expiry_count": near_expiry_count,
            "attractive_count": attractive_count,
            "total_positions": len(analyzed),
        }

    # ------------------------------------------------------------------
    # Ring-buffer log
    # ------------------------------------------------------------------

    def _write_log(self, result: dict) -> None:
        log_path = os.path.abspath(LOG_FILE)
        os.makedirs(os.path.dirname(log_path), exist_ok=True)

        entries: list[dict] = []
        if os.path.exists(log_path):
            try:
                with open(log_path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                    entries = data if isinstance(data, list) else []
            except (json.JSONDecodeError, OSError):
                entries = []

        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
            "total_positions": result["aggregates"]["total_positions"],
            "attractive_count": result["aggregates"]["attractive_count"],
            "near_expiry_count": result["aggregates"]["near_expiry_count"],
            "avg_carry_pct": result["aggregates"]["avg_carry_pct"],
            "best_fixed_rate": result["aggregates"]["best_fixed_rate"],
        }
        entries.append(entry)

        if len(entries) > LOG_CAP:
            entries = entries[-LOG_CAP:]

        dir_path = os.path.dirname(log_path)
        atomic_save(entries, str(log_path))
