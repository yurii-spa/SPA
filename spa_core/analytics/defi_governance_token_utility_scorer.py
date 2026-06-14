"""
MP-918: DeFi Governance Token Utility Scorer
Evaluates real utility of DeFi governance tokens beyond pure voting power.
Pure stdlib, no external dependencies.
"""

import json
import os
from datetime import datetime, timezone

LOG_CAP = 100
_HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_LOG_PATH = os.path.join(_HERE, "..", "..", "data", "gov_token_utility_log.json")

UTILITY_THRESHOLDS = [
    (80, "HIGH_UTILITY"),
    (60, "GOOD_UTILITY"),
    (40, "MODERATE"),
    (20, "LOW_UTILITY"),
    (0,  "GOVERNANCE_ONLY"),
]


class DeFiGovernanceTokenUtilityScorer:
    """Scores DeFi governance tokens on real utility (cash-flow, staking, VE model, etc.)."""

    def __init__(self, log_path: str = None):
        self.log_path = log_path or DEFAULT_LOG_PATH

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def score(self, tokens: list, config: dict = None) -> dict:
        """
        Score a list of governance tokens.

        Each token dict may contain:
            name (str), protocol (str),
            voting_power (bool), fee_sharing_pct (float, 0-100),
            buyback_monthly_usd (float), staking_apy_pct (float),
            staking_ratio_pct (float, % of supply staked),
            veto_power (bool), protocol_revenue_monthly_usd (float),
            token_market_cap_usd (float), ve_model (bool)

        Returns dict with 'results', 'aggregates', 'timestamp', 'token_count'.
        """
        config = config or {}
        results = [self._score_token(t, config) for t in tokens]
        aggregates = self._compute_aggregates(results)

        output = {
            "results": results,
            "aggregates": aggregates,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "token_count": len(tokens),
        }
        self._append_log(output)
        return output

    # ------------------------------------------------------------------ #
    # Per-token scoring
    # ------------------------------------------------------------------ #

    def _score_token(self, token: dict, config: dict) -> dict:
        name = str(token.get("name", "unknown"))
        protocol = str(token.get("protocol", "unknown"))
        voting_power = bool(token.get("voting_power", False))
        fee_sharing_pct = float(token.get("fee_sharing_pct", 0.0))
        buyback_monthly_usd = float(token.get("buyback_monthly_usd", 0.0))
        staking_apy_pct = float(token.get("staking_apy_pct", 0.0))
        staking_ratio_pct = float(token.get("staking_ratio_pct", 0.0))
        veto_power = bool(token.get("veto_power", False))
        protocol_revenue_monthly_usd = float(token.get("protocol_revenue_monthly_usd", 0.0))
        token_market_cap_usd = float(token.get("token_market_cap_usd", 1.0))
        ve_model = bool(token.get("ve_model", False))

        # Guard against zero / negative market cap
        if token_market_cap_usd <= 0:
            token_market_cap_usd = 1.0

        # --- Cash-flow yield (annualised) ---
        monthly_fee_cash = protocol_revenue_monthly_usd * fee_sharing_pct / 100.0
        monthly_total_cash = buyback_monthly_usd + monthly_fee_cash
        annual_cash = monthly_total_cash * 12.0
        cash_flow_yield_pct = annual_cash / token_market_cap_usd * 100.0

        # --- Value capture ratio ---
        if protocol_revenue_monthly_usd > 0:
            value_capture_ratio = (protocol_revenue_monthly_usd * fee_sharing_pct / 100.0) \
                                  / protocol_revenue_monthly_usd
        else:
            value_capture_ratio = 0.0

        # --- Scores ---
        utility_score = self._utility_score(
            fee_sharing_pct, buyback_monthly_usd, staking_apy_pct,
            staking_ratio_pct, ve_model, veto_power, voting_power,
            cash_flow_yield_pct, token_market_cap_usd,
        )
        staking_attractiveness = self._staking_attractiveness(
            staking_apy_pct, staking_ratio_pct, fee_sharing_pct, ve_model,
        )

        return {
            "name": name,
            "protocol": protocol,
            "cash_flow_yield_pct": round(cash_flow_yield_pct, 4),
            "utility_score": round(utility_score, 2),
            "staking_attractiveness": round(staking_attractiveness, 2),
            "value_capture_ratio": round(value_capture_ratio, 4),
            "utility_label": self._utility_label(utility_score),
            "flags": self._flags(ve_model, fee_sharing_pct, staking_ratio_pct,
                                  buyback_monthly_usd, value_capture_ratio),
        }

    def _utility_score(self, fee_sharing_pct, buyback_monthly_usd,
                        staking_apy_pct, staking_ratio_pct,
                        ve_model, veto_power, voting_power,
                        cash_flow_yield_pct, market_cap) -> float:
        s = 0.0
        # Fee sharing  (max 25)
        s += min(25.0, fee_sharing_pct * 0.5)
        # Buyback yield (max 20)
        if buyback_monthly_usd > 0 and market_cap > 0:
            buyback_yield = (buyback_monthly_usd * 12.0 / market_cap) * 100.0
            s += min(20.0, buyback_yield * 2.0)
        # Staking APY (max 15)
        s += min(15.0, staking_apy_pct * 1.5)
        # Staking ratio (max 10)
        s += min(10.0, staking_ratio_pct * 0.1667)
        # VE model (5)
        if ve_model:
            s += 5.0
        # Veto power (5)
        if veto_power:
            s += 5.0
        # Voting power (2)
        if voting_power:
            s += 2.0
        # Cash-flow yield (max 18)
        s += min(18.0, cash_flow_yield_pct * 1.8)
        return min(100.0, max(0.0, s))

    def _staking_attractiveness(self, staking_apy_pct, staking_ratio_pct,
                                 fee_sharing_pct, ve_model) -> float:
        s = 0.0
        s += min(40.0, staking_apy_pct * 4.0)        # APY (max 40)
        s += min(30.0, staking_ratio_pct * 0.5)      # Ratio (max 30)
        s += min(20.0, fee_sharing_pct * 0.4)         # Fee sharing (max 20)
        if ve_model:
            s += 10.0                                  # VE bonus (10)
        return min(100.0, max(0.0, s))

    def _utility_label(self, score: float) -> str:
        for threshold, label in UTILITY_THRESHOLDS:
            if score >= threshold:
                return label
        return "GOVERNANCE_ONLY"

    def _flags(self, ve_model, fee_sharing_pct, staking_ratio_pct,
                buyback_monthly_usd, value_capture_ratio) -> list:
        flags = []
        if ve_model:
            flags.append("VE_MODEL")
        if fee_sharing_pct > 0:
            flags.append("FEE_SHARING")
        if staking_ratio_pct > 60.0:
            flags.append("HIGH_STAKING_RATIO")
        if buyback_monthly_usd > 0:
            flags.append("BUYBACK_PROGRAM")
        if value_capture_ratio < 0.10:
            flags.append("LOW_REVENUE_CAPTURE")
        return flags

    # ------------------------------------------------------------------ #
    # Aggregates
    # ------------------------------------------------------------------ #

    def _compute_aggregates(self, results: list) -> dict:
        if not results:
            return {
                "highest_utility": None,
                "lowest_utility": None,
                "average_cash_flow_yield": 0.0,
                "average_utility": 0.0,
                "high_utility_count": 0,
            }

        by_score = sorted(results, key=lambda r: r["utility_score"], reverse=True)
        avg_cf = sum(r["cash_flow_yield_pct"] for r in results) / len(results)
        avg_u = sum(r["utility_score"] for r in results) / len(results)
        high_count = sum(
            1 for r in results
            if r["utility_label"] in ("HIGH_UTILITY", "GOOD_UTILITY")
        )
        return {
            "highest_utility": by_score[0]["name"],
            "lowest_utility": by_score[-1]["name"],
            "average_cash_flow_yield": round(avg_cf, 4),
            "average_utility": round(avg_u, 2),
            "high_utility_count": high_count,
        }

    # ------------------------------------------------------------------ #
    # Ring-buffer log
    # ------------------------------------------------------------------ #

    def _append_log(self, output: dict) -> None:
        log_path = self.log_path
        os.makedirs(os.path.dirname(os.path.abspath(log_path)), exist_ok=True)

        log = []
        if os.path.exists(log_path):
            try:
                with open(log_path, "r", encoding="utf-8") as f:
                    log = json.load(f)
                if not isinstance(log, list):
                    log = []
            except (json.JSONDecodeError, OSError):
                log = []

        log.append({
            "timestamp": output["timestamp"],
            "token_count": output["token_count"],
            "aggregates": output["aggregates"],
        })

        if len(log) > LOG_CAP:
            log = log[-LOG_CAP:]

        tmp = log_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(log, f, indent=2)
        os.replace(tmp, log_path)
