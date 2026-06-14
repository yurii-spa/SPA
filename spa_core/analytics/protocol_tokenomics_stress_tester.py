"""
MP-929 — ProtocolTokenomicsStressTester
Stress-tests DeFi protocol tokenomics under extreme market conditions.
Pure stdlib, read-only/advisory, atomic ring-buffer log.
"""

from __future__ import annotations

import json
import math
import os
import tempfile
import time
from typing import Any

_LOG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "tokenomics_stress_log.json"
)
_LOG_CAP = 100

# --------------------------------------------------------------------------- #
# Stress labels
# --------------------------------------------------------------------------- #
LABEL_ANTIFRAGILE = "ANTIFRAGILE"
LABEL_RESILIENT = "RESILIENT"
LABEL_VULNERABLE = "VULNERABLE"
LABEL_CRITICAL = "CRITICAL"
LABEL_TERMINAL = "TERMINAL"

# Flags
FLAG_DEATH_SPIRAL_RISK = "DEATH_SPIRAL_RISK"
FLAG_TREASURY_RUNWAY_SHORT = "TREASURY_RUNWAY_SHORT"
FLAG_DEPENDENT_PROTOCOLS_AT_RISK = "DEPENDENT_PROTOCOLS_AT_RISK"
FLAG_BUYBACK_COVERS = "BUYBACK_COVERS"


# --------------------------------------------------------------------------- #
# Main class
# --------------------------------------------------------------------------- #
class ProtocolTokenomicsStressTester:
    """
    Stress-tests protocol tokenomics under a configurable price shock scenario.

    Usage::

        tester = ProtocolTokenomicsStressTester()
        result = tester.test(scenarios, config)
    """

    _DEFAULTS: dict[str, Any] = {
        "death_spiral_buyback_coverage_threshold": 1.0,   # emissions > buyback+revenue → risk
        "staking_collapse_threshold_pct": 20.0,           # staking_ratio drops below this → collapse
        "treasury_runway_short_months": 6,                # flag TREASURY_RUNWAY_SHORT below this
        "dependent_protocols_at_risk_count": 5,           # above this count + CRITICAL → flag
        "buyback_covers_threshold_pct": 50.0,             # buyback > 50% sell_pressure → flag
        "viability_antifragile_min": 80.0,
        "viability_resilient_min": 60.0,
        "viability_vulnerable_min": 40.0,
        "viability_critical_min": 20.0,
    }

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def test(
        self,
        scenarios: list[dict],
        config: dict | None = None,
    ) -> dict:
        """
        Run stress tests on a list of tokenomics scenarios.

        Each scenario dict may contain:
            protocol                    (str)
            token_price_usd             (float) — baseline price
            token_price_shock_pct       (float) — e.g. -80 for -80% shock
            circulating_supply          (float)
            staking_ratio_pct           (float) — % of supply staked
            protocol_revenue_usd_monthly (float)
            token_emissions_monthly     (float) — tokens emitted per month
            buyback_usd_monthly         (float) — USD spent on buybacks
            treasury_usd                (float)
            protocol_dependents_count   (int)   — other protocols depending on this one

        Returns a dict with per-scenario results and portfolio aggregates.
        """
        cfg = {**self._DEFAULTS, **(config or {})}

        tested: list[dict] = []
        for sc in scenarios:
            tested.append(self._test_one(sc, cfg))

        agg = self._aggregate(tested, cfg)

        result = {
            "scenarios": tested,
            "aggregates": agg,
            "tested_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "scenario_count": len(tested),
        }
        self._append_log(result)
        return result

    # ------------------------------------------------------------------ #
    # Per-scenario stress test
    # ------------------------------------------------------------------ #
    def _test_one(self, sc: dict, cfg: dict) -> dict:
        protocol = str(sc.get("protocol", "unknown"))
        price = float(sc.get("token_price_usd", 1.0))
        shock_pct = float(sc.get("token_price_shock_pct", 0.0))
        circ_supply = float(sc.get("circulating_supply", 0.0))
        staking_ratio = float(sc.get("staking_ratio_pct", 0.0))
        revenue_monthly = float(sc.get("protocol_revenue_usd_monthly", 0.0))
        emissions_monthly = float(sc.get("token_emissions_monthly", 0.0))
        buyback_monthly = float(sc.get("buyback_usd_monthly", 0.0))
        treasury = float(sc.get("treasury_usd", 0.0))
        dependents = int(sc.get("protocol_dependents_count", 0))

        # Apply price shock
        shocked_price = price * (1.0 + shock_pct / 100.0)
        shocked_price = max(shocked_price, 0.0)

        # Post-shock market cap
        post_shock_mcap = shocked_price * circ_supply

        # Emission sell pressure (monthly emissions converted to USD at shocked price)
        emission_sell_pressure = emissions_monthly * shocked_price

        # Buyback coverage ratio (buyback / sell_pressure)
        if emission_sell_pressure > 0:
            buyback_coverage_ratio = buyback_monthly / emission_sell_pressure
        else:
            buyback_coverage_ratio = float("inf") if buyback_monthly > 0 else 1.0

        # Treasury runway (months) at net monthly burn
        # net_monthly_burn = revenue consumed by operations approx (assume emissions_cost - revenue)
        net_monthly_burn = max(
            emission_sell_pressure - revenue_monthly - buyback_monthly, 0.0
        )
        if net_monthly_burn > 0:
            treasury_runway_months = treasury / net_monthly_burn
        else:
            treasury_runway_months = float("inf")

        # Staking sustainability: staking rewards in USD at shocked price
        staking_rewards_usd = emissions_monthly * (staking_ratio / 100.0) * shocked_price

        # Post-shock effective staking ratio (collapses if rewards fall significantly)
        staking_sustainability = self._staking_sustainability_score(
            staking_rewards_usd, revenue_monthly, shocked_price, price
        )

        # Viability score 0-100
        viability_score = self._viability_score(
            shock_pct=shock_pct,
            buyback_coverage_ratio=buyback_coverage_ratio,
            treasury_runway_months=treasury_runway_months,
            staking_sustainability=staking_sustainability,
            revenue_monthly=revenue_monthly,
            emission_sell_pressure=emission_sell_pressure,
            cfg=cfg,
        )

        # Stress label
        label = self._stress_label(viability_score, cfg)

        # Flags
        flags = self._flags(
            shock_pct=shock_pct,
            emissions_monthly=emissions_monthly,
            buyback_monthly=buyback_monthly,
            revenue_monthly=revenue_monthly,
            emission_sell_pressure=emission_sell_pressure,
            staking_ratio=staking_ratio,
            treasury_runway_months=treasury_runway_months,
            dependents=dependents,
            label=label,
            buyback_coverage_ratio=buyback_coverage_ratio,
            cfg=cfg,
        )

        return {
            "protocol": protocol,
            "token_price_usd": price,
            "token_price_shock_pct": shock_pct,
            "shocked_price_usd": round(shocked_price, 6),
            "post_shock_mcap_usd": round(post_shock_mcap, 2),
            "emission_sell_pressure_usd": round(emission_sell_pressure, 2),
            "buyback_coverage_ratio": round(
                min(buyback_coverage_ratio, 1e9), 4
            ) if math.isfinite(buyback_coverage_ratio) else None,
            "treasury_runway_months": round(
                min(treasury_runway_months, 1e6), 2
            ) if math.isfinite(treasury_runway_months) else None,
            "staking_sustainability_score": round(staking_sustainability, 2),
            "protocol_viability_score": round(viability_score, 2),
            "stress_label": label,
            "flags": flags,
        }

    # ------------------------------------------------------------------ #
    # Aggregation
    # ------------------------------------------------------------------ #
    def _aggregate(self, scenarios: list[dict], cfg: dict) -> dict:
        if not scenarios:
            return {
                "most_resilient": None,
                "most_vulnerable": None,
                "terminal_count": 0,
                "average_viability": 0.0,
                "total_treasury_at_risk_usd": 0.0,
                "label_counts": {},
                "flag_counts": {},
            }

        sorted_by_viability = sorted(
            scenarios, key=lambda s: s["protocol_viability_score"]
        )
        most_resilient = sorted_by_viability[-1]["protocol"]
        most_vulnerable = sorted_by_viability[0]["protocol"]

        terminal_count = sum(
            1 for s in scenarios if s["stress_label"] == LABEL_TERMINAL
        )
        avg_viability = (
            sum(s["protocol_viability_score"] for s in scenarios) / len(scenarios)
        )

        # Treasury at risk: treasury of CRITICAL + TERMINAL protocols
        total_treasury_at_risk = 0.0
        for s in scenarios:
            if s["stress_label"] in (LABEL_CRITICAL, LABEL_TERMINAL):
                # Approximate: post_shock_mcap correlates with treasury risk
                total_treasury_at_risk += s["post_shock_mcap_usd"]

        label_counts: dict[str, int] = {}
        for s in scenarios:
            lbl = s["stress_label"]
            label_counts[lbl] = label_counts.get(lbl, 0) + 1

        flag_counts: dict[str, int] = {}
        for s in scenarios:
            for f in s["flags"]:
                flag_counts[f] = flag_counts.get(f, 0) + 1

        return {
            "most_resilient": most_resilient,
            "most_vulnerable": most_vulnerable,
            "terminal_count": terminal_count,
            "average_viability": round(avg_viability, 2),
            "total_treasury_at_risk_usd": round(total_treasury_at_risk, 2),
            "label_counts": label_counts,
            "flag_counts": flag_counts,
        }

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _staking_sustainability_score(
        staking_rewards_usd: float,
        revenue_monthly: float,
        shocked_price: float,
        original_price: float,
    ) -> float:
        """
        0-100 score:
        - If rewards remain > revenue, staking is self-sustaining → high score
        - Collapses proportionally to price shock magnitude
        """
        if original_price <= 0:
            return 0.0
        price_ratio = shocked_price / original_price
        # Base sustainability from rewards vs revenue coverage
        if revenue_monthly > 0:
            coverage = min(staking_rewards_usd / revenue_monthly, 2.0)
        else:
            coverage = 1.0 if staking_rewards_usd > 0 else 0.0
        score = coverage * price_ratio * 50.0
        return min(max(score, 0.0), 100.0)

    @staticmethod
    def _viability_score(
        shock_pct: float,
        buyback_coverage_ratio: float,
        treasury_runway_months: float,
        staking_sustainability: float,
        revenue_monthly: float,
        emission_sell_pressure: float,
        cfg: dict,
    ) -> float:
        """
        Composite viability score 0-100.
        Four components (25 pts each):
        1. Shock survivability (less negative shock = better)
        2. Buyback coverage
        3. Treasury runway
        4. Revenue vs emissions
        """
        # 1. Shock component: -100% shock → 0 pts, 0% shock → 25 pts
        shock_component = max(0.0, 25.0 * (1.0 + shock_pct / 100.0))
        shock_component = min(shock_component, 25.0)

        # 2. Buyback coverage: capped at 25 pts, 1.0 ratio → 12.5 pts
        if math.isinf(buyback_coverage_ratio) or buyback_coverage_ratio > 4.0:
            buyback_component = 25.0
        else:
            buyback_component = min(buyback_coverage_ratio / 4.0 * 25.0, 25.0)

        # 3. Treasury runway: 12 months → 12.5 pts, 24+ months → 25 pts
        if math.isinf(treasury_runway_months) or treasury_runway_months >= 24:
            runway_component = 25.0
        else:
            runway_component = min(treasury_runway_months / 24.0 * 25.0, 25.0)

        # 4. Revenue health: revenue covers more than emission sell pressure → full pts
        if emission_sell_pressure > 0:
            rev_ratio = min(revenue_monthly / emission_sell_pressure, 1.0)
        else:
            rev_ratio = 1.0
        revenue_component = rev_ratio * 25.0

        total = shock_component + buyback_component + runway_component + revenue_component
        return min(max(total, 0.0), 100.0)

    def _stress_label(self, viability_score: float, cfg: dict) -> str:
        if viability_score >= cfg["viability_antifragile_min"]:
            return LABEL_ANTIFRAGILE
        if viability_score >= cfg["viability_resilient_min"]:
            return LABEL_RESILIENT
        if viability_score >= cfg["viability_vulnerable_min"]:
            return LABEL_VULNERABLE
        if viability_score >= cfg["viability_critical_min"]:
            return LABEL_CRITICAL
        return LABEL_TERMINAL

    def _flags(
        self,
        shock_pct: float,
        emissions_monthly: float,
        buyback_monthly: float,
        revenue_monthly: float,
        emission_sell_pressure: float,
        staking_ratio: float,
        treasury_runway_months: float,
        dependents: int,
        label: str,
        buyback_coverage_ratio: float,
        cfg: dict,
    ) -> list[str]:
        flags: list[str] = []

        # DEATH_SPIRAL_RISK: emissions > (buyback + revenue) AND staking below collapse threshold
        total_counterforce = buyback_monthly + revenue_monthly
        emissions_cost = emission_sell_pressure  # already in USD
        staking_collapsed = staking_ratio < cfg["staking_collapse_threshold_pct"]
        if emissions_cost > total_counterforce and staking_collapsed:
            flags.append(FLAG_DEATH_SPIRAL_RISK)

        # TREASURY_RUNWAY_SHORT: runway < threshold post-shock
        if (
            not math.isinf(treasury_runway_months)
            and treasury_runway_months < cfg["treasury_runway_short_months"]
        ):
            flags.append(FLAG_TREASURY_RUNWAY_SHORT)

        # DEPENDENT_PROTOCOLS_AT_RISK: many dependents AND label is CRITICAL/TERMINAL
        if (
            dependents > cfg["dependent_protocols_at_risk_count"]
            and label in (LABEL_CRITICAL, LABEL_TERMINAL)
        ):
            flags.append(FLAG_DEPENDENT_PROTOCOLS_AT_RISK)

        # BUYBACK_COVERS: buyback covers > threshold% of sell pressure
        if emission_sell_pressure > 0:
            buyback_pct = (buyback_monthly / emission_sell_pressure) * 100.0
        else:
            buyback_pct = 100.0
        if buyback_pct >= cfg["buyback_covers_threshold_pct"]:
            flags.append(FLAG_BUYBACK_COVERS)

        return flags

    # ------------------------------------------------------------------ #
    # Ring-buffer log (cap 100, atomic write)
    # ------------------------------------------------------------------ #
    def _append_log(self, result: dict) -> None:
        log_path = os.path.abspath(_LOG_PATH)
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        try:
            with open(log_path, "r", encoding="utf-8") as fh:
                entries: list = json.load(fh)
        except (FileNotFoundError, json.JSONDecodeError):
            entries = []

        entry = {
            "ts": result["tested_at"],
            "scenario_count": result["scenario_count"],
            "aggregates": result["aggregates"],
        }
        entries.append(entry)
        if len(entries) > _LOG_CAP:
            entries = entries[-_LOG_CAP:]

        tmp_fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(log_path))
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as fh:
                json.dump(entries, fh, indent=2)
            os.replace(tmp_path, log_path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
