"""
MP-1004: DeFiRewardTokenSellPressureAnalyzer

Estimates the SELL PRESSURE created by emitted reward/incentive tokens relative to
organic on-chain demand and DEX liquidity, and how the resulting price drag erodes the
*realized* (sell-pressure-adjusted) APY of a farm. A farm advertising a high reward APY
can be self-defeating: if recipients dump tokens into a thin pool faster than organic
buyers absorb them, the reward token depreciates and the realized yield collapses — the
classic reflexive emissions death-spiral.

For a daily emission flow that recipients sell at some propensity:
    daily_sell_usd          = daily_emissions_usd * sell_propensity
    sell_pressure_ratio     = daily_sell_usd / organic_daily_buy_volume_usd
    liquidity_turnover_pct  = daily_sell_usd / pool_liquidity_usd * 100
    price_drag             ~ rises with liquidity turnover (guarded, capped)
    realized_apy_pct        = advertised_apy_pct - annualized_price_drag_pct

Distinct from reward_token_liquidity_scorer (liquidity scoring only), the
emission_schedule modules (emission size only), and token_velocity (circulation speed
only): no prior module ties emission sell-flow to organic demand AND liquidity to derive
a sell-pressure-adjusted realized APY (gap confirmed v7.40).

Pure stdlib, read-only/advisory, all divisions guarded, atomic tempfile+os.replace
writes, ring-buffer 100 (`data/reward_token_sell_pressure_log.json`).
"""

import json
import os
import time


class DeFiRewardTokenSellPressureAnalyzer:
    """
    Per-position reward-token sell-pressure / realized-APY analysis.

    Input fields (per position dict):
      name, protocol, reward_token,
      daily_emissions_usd               (USD value of tokens emitted/day)
      organic_daily_buy_volume_usd      (USD/day of genuine buy demand)
      pool_liquidity_usd                (DEX liquidity backing the reward token)
      advertised_apy_pct                (headline reward APY)
      sell_propensity_pct               (optional, % of emissions sold, default 70)
    """

    LOG_CAP = 100

    EPS = 1e-9

    # Default share of emissions that recipients dump (vs hold/restake).
    DEFAULT_SELL_PROPENSITY_PCT = 70.0

    # Price-drag model: drag (% per day) saturates as a function of daily liquidity
    # turnover. DRAG_CAP_PCT is the max per-day drag; DRAG_HALF_TURNOVER is the
    # turnover (%) at which drag reaches half its cap (logistic-style saturation).
    DRAG_CAP_PCT = 5.0
    DRAG_HALF_TURNOVER = 10.0

    # ------------------------------------------------------------------ #
    # Drag helper
    # ------------------------------------------------------------------ #

    def _daily_price_drag_pct(self, liquidity_turnover_pct: float) -> float:
        """
        Estimated daily price drag (%) as a saturating function of liquidity turnover.
        Monotone increasing in turnover, bounded by DRAG_CAP_PCT. drag = cap * t/(t+half)
        so drag == cap/2 when turnover == DRAG_HALF_TURNOVER, and drag -> cap as t -> inf.
        """
        t = max(0.0, liquidity_turnover_pct)
        denom = t + self.DRAG_HALF_TURNOVER
        if denom <= 0:
            return 0.0
        return self.DRAG_CAP_PCT * (t / denom)

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def analyze(self, positions: list, config: dict = None) -> dict:
        if config is None:
            config = {}

        results = [self._analyze_one(p) for p in positions]
        aggregates = self._compute_aggregates(results)

        output = {
            "positions": results,
            "aggregates": aggregates,
            "position_count": len(results),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }

        if config.get("write_log", False):
            self._write_log(output, config.get("data_dir", "data"))

        return output

    # ------------------------------------------------------------------ #
    # Per-position analysis
    # ------------------------------------------------------------------ #

    def _analyze_one(self, p: dict) -> dict:
        name = p.get("name", "unknown")
        protocol = p.get("protocol", "unknown")
        reward_token = p.get("reward_token", "unknown")

        daily_emissions = max(0.0, float(p.get("daily_emissions_usd", 0.0)))
        organic_buy = max(0.0, float(p.get("organic_daily_buy_volume_usd", 0.0)))
        liquidity = max(0.0, float(p.get("pool_liquidity_usd", 0.0)))
        advertised_apy = float(p.get("advertised_apy_pct", 0.0))
        sell_propensity = p.get("sell_propensity_pct", self.DEFAULT_SELL_PROPENSITY_PCT)
        sell_propensity = min(100.0, max(0.0, float(sell_propensity)))

        # Daily USD flow that hits the market as sells.
        daily_sell_usd = daily_emissions * (sell_propensity / 100.0)

        # Sell pressure relative to organic buy demand (>1 == sells exceed buys).
        sell_pressure_ratio = daily_sell_usd / max(organic_buy, self.EPS)

        # Daily turnover of the DEX liquidity caused by reward sells.
        liquidity_turnover_pct = daily_sell_usd / max(liquidity, self.EPS) * 100.0

        # Estimated price drag from that turnover, annualized.
        daily_price_drag_pct = self._daily_price_drag_pct(liquidity_turnover_pct)
        annualized_price_drag_pct = daily_price_drag_pct * 365.0

        # Realized (sell-pressure-adjusted) APY: headline minus the depreciation
        # the emissions themselves cause.
        realized_apy_pct = advertised_apy - annualized_price_drag_pct

        sell_pressure_score = self._sell_pressure_score(
            sell_pressure_ratio, liquidity_turnover_pct, organic_buy, daily_sell_usd
        )
        grade = self._grade(sell_pressure_score)
        classification = self._classify(
            sell_pressure_ratio, liquidity_turnover_pct, realized_apy_pct,
            daily_emissions, organic_buy, liquidity,
        )
        flags = self._flags(
            sell_pressure_ratio, liquidity_turnover_pct, realized_apy_pct,
            daily_emissions, organic_buy, liquidity, daily_sell_usd, advertised_apy,
        )

        return {
            "name": name,
            "protocol": protocol,
            "reward_token": reward_token,
            "daily_sell_usd": round(daily_sell_usd, 2),
            "sell_propensity_pct": round(sell_propensity, 4),
            "sell_pressure_ratio": round(sell_pressure_ratio, 4),
            "liquidity_turnover_pct": round(liquidity_turnover_pct, 4),
            "estimated_daily_price_drag_pct": round(daily_price_drag_pct, 4),
            "annualized_price_drag_pct": round(annualized_price_drag_pct, 4),
            "advertised_apy_pct": round(advertised_apy, 4),
            "realized_apy_pct": round(realized_apy_pct, 4),
            "sell_pressure_score": round(sell_pressure_score, 4),
            "grade": grade,
            "classification": classification,
            "flags": flags,
        }

    # ------------------------------------------------------------------ #
    # Score / grade / classification / flags
    # ------------------------------------------------------------------ #

    def _sell_pressure_score(
        self, sell_pressure_ratio, liquidity_turnover_pct, organic_buy, daily_sell_usd
    ) -> float:
        """
        0-100, higher == LESS sell pressure (healthier). Two penalties:
          - demand penalty: how much sells exceed organic buys (ratio>1 hurts)
          - liquidity penalty: daily liquidity turnover from sells
        No sells at all -> perfect 100.
        """
        if daily_sell_usd <= 0:
            return 100.0

        # Demand component: ratio 0 -> 100, ratio 1 (sells == buys) -> 50,
        # ratio >=3 -> ~0. score_demand = 100 / (1 + ratio).
        demand_component = 100.0 / (1.0 + max(0.0, sell_pressure_ratio))

        # Liquidity component: turnover 0 -> 100, turnover 10% -> 50, large -> ~0.
        t = max(0.0, liquidity_turnover_pct)
        liquidity_component = 100.0 * (self.DRAG_HALF_TURNOVER / (t + self.DRAG_HALF_TURNOVER))

        score = 0.5 * demand_component + 0.5 * liquidity_component
        return max(0.0, min(100.0, score))

    def _grade(self, score: float) -> str:
        if score >= 90.0:
            return "A"
        if score >= 75.0:
            return "B"
        if score >= 60.0:
            return "C"
        if score >= 45.0:
            return "D"
        return "F"

    def _classify(
        self, sell_pressure_ratio, liquidity_turnover_pct, realized_apy_pct,
        daily_emissions, organic_buy, liquidity,
    ) -> str:
        if daily_emissions <= 0 and liquidity <= 0:
            return "INSUFFICIENT_DATA"
        # Reflexive death spiral: sells massively exceed demand, thin liquidity is
        # churned hard, and the realized yield has gone negative.
        if (sell_pressure_ratio >= 3.0 and liquidity_turnover_pct >= 20.0
                and realized_apy_pct < 0.0):
            return "REFLEXIVE_DEATH_SPIRAL"
        if sell_pressure_ratio >= 2.0 or liquidity_turnover_pct >= 15.0:
            return "HIGH_PRESSURE"
        if sell_pressure_ratio >= 1.0 or liquidity_turnover_pct >= 5.0:
            return "ELEVATED"
        if sell_pressure_ratio >= 0.5 or liquidity_turnover_pct >= 1.0:
            return "ABSORBABLE"
        return "MINIMAL_PRESSURE"

    def _flags(
        self, sell_pressure_ratio, liquidity_turnover_pct, realized_apy_pct,
        daily_emissions, organic_buy, liquidity, daily_sell_usd, advertised_apy,
    ) -> list:
        flags = []
        if daily_emissions <= 0 and liquidity <= 0:
            flags.append("INSUFFICIENT_DATA")
        if daily_sell_usd > 0 and sell_pressure_ratio > 1.0:
            flags.append("SELL_EXCEEDS_ORGANIC")
        if liquidity > 0 and daily_sell_usd > 0 and liquidity_turnover_pct >= 50.0:
            flags.append("THIN_LIQUIDITY")
        if liquidity_turnover_pct >= 10.0:
            flags.append("HIGH_LIQUIDITY_TURNOVER")
        if realized_apy_pct < 0.0:
            flags.append("APY_NET_NEGATIVE")
        if advertised_apy > 0 and realized_apy_pct < advertised_apy * 0.5:
            flags.append("EMISSIONS_SELF_DEFEATING")
        if daily_sell_usd > 0 and sell_pressure_ratio < 0.5:
            flags.append("ORGANIC_DEMAND_STRONG")
        return flags

    # ------------------------------------------------------------------ #
    # Aggregates
    # ------------------------------------------------------------------ #

    def _compute_aggregates(self, results: list) -> dict:
        if not results:
            return {
                "best_position": None,
                "worst_position": None,
                "average_sell_pressure_score": None,
                "high_pressure_count": 0,
                "net_negative_apy_count": 0,
            }

        best = max(results, key=lambda r: r["sell_pressure_score"])
        worst = min(results, key=lambda r: r["sell_pressure_score"])
        avg = sum(r["sell_pressure_score"] for r in results) / len(results)
        high_pressure = sum(
            1 for r in results
            if r["classification"] in ("HIGH_PRESSURE", "REFLEXIVE_DEATH_SPIRAL")
        )
        net_negative = sum(1 for r in results if r["realized_apy_pct"] < 0.0)

        return {
            "best_position": {
                "name": best["name"],
                "sell_pressure_score": best["sell_pressure_score"],
                "classification": best["classification"],
            },
            "worst_position": {
                "name": worst["name"],
                "sell_pressure_score": worst["sell_pressure_score"],
                "classification": worst["classification"],
            },
            "average_sell_pressure_score": round(avg, 4),
            "high_pressure_count": high_pressure,
            "net_negative_apy_count": net_negative,
        }

    # ------------------------------------------------------------------ #
    # Ring-buffer log (atomic write)
    # ------------------------------------------------------------------ #

    def _write_log(self, result: dict, data_dir: str = "data") -> None:
        os.makedirs(data_dir, exist_ok=True)
        log_path = os.path.join(data_dir, "reward_token_sell_pressure_log.json")

        try:
            with open(log_path, "r") as f:
                log = json.load(f)
            if not isinstance(log, list):
                log = []
        except (FileNotFoundError, json.JSONDecodeError):
            log = []

        agg = result.get("aggregates", {})
        log.append({
            "timestamp": result.get("timestamp", ""),
            "position_count": result.get("position_count", 0),
            "average_sell_pressure_score": agg.get("average_sell_pressure_score"),
            "high_pressure_count": agg.get("high_pressure_count", 0),
            "net_negative_apy_count": agg.get("net_negative_apy_count", 0),
        })

        if len(log) > self.LOG_CAP:
            log = log[-self.LOG_CAP:]

        tmp_path = log_path + ".tmp"
        with open(tmp_path, "w") as f:
            json.dump(log, f, indent=2)
        os.replace(tmp_path, log_path)
