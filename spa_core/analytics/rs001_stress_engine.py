"""
spa_core/analytics/rs001_stress_engine.py

Stress test engine for RS-001 Anti-Crisis strategy.

Scenarios:
  1. BTC Crash -80% (2022 style)
  2. BTC Crash -50% (medium bear)
  3. GMX v2 exploit (smart contract risk)
  4. IL extreme (all LP positions out of range)
  5. DeFiLlama feed down (all sources → fallback APY)
  6. Multi-protocol contagion (3 protocols fail simultaneously)
  7. Stablecoin depeg (USDC/DAI -3%)

For each scenario:
  - portfolio_apy: expected APY during scenario
  - max_drawdown: max NAV loss (negative, e.g. -0.15 = -15%)
  - recovery_days: estimated recovery time
  - survivable: bool (does portfolio survive?)

Slot weights mirror RS-001 research allocation:
  gmx_btc_perp    20%
  gmx_eth_perp    20%
  btc_stable_pool 15%
  eth_aggressive  15%
  gold_proxy      15%
  stablecoin_t1   15%
  (remaining 10% cash drag — earns 0%, not listed as a slot)

RESEARCH_ONLY — does NOT affect allocator / risk / execution.
Pure stdlib. No external dependencies. LLM FORBIDDEN.
Atomic writes: mkstemp + os.replace.

Sprint v9.77 — MP-1361
Date: 2026-06-19
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

from spa_core.base import BaseAnalytics

# ── Scenario registry ───────────────────────────────────────────────────────────

SCENARIOS: List[str] = [
    "btc_crash_80",
    "btc_crash_50",
    "gmx_exploit",
    "il_extreme",
    "feed_down",
    "multi_contagion",
    "stablecoin_depeg",
]


# ── Result dataclass (stdlib-compatible) ────────────────────────────────────────

class StressResult:
    """Immutable result object for one stress scenario."""

    __slots__ = [
        "scenario",
        "portfolio_apy",
        "max_drawdown",
        "recovery_days",
        "survivable",
        "details",
    ]

    def __init__(
        self,
        scenario: str,
        portfolio_apy: float,
        max_drawdown: float,
        recovery_days: int,
        survivable: bool,
        details: dict,
    ) -> None:
        self.scenario: str = scenario
        self.portfolio_apy: float = portfolio_apy
        self.max_drawdown: float = max_drawdown   # negative, e.g. -0.15 = -15%
        self.recovery_days: int = recovery_days
        self.survivable: bool = survivable
        self.details: dict = details

    def to_dict(self) -> dict:
        return {
            "scenario":      self.scenario,
            "portfolio_apy": self.portfolio_apy,
            "max_drawdown":  self.max_drawdown,
            "recovery_days": self.recovery_days,
            "survivable":    self.survivable,
            "details":       self.details,
        }

    def __repr__(self) -> str:
        return (
            f"StressResult(scenario={self.scenario!r}, "
            f"portfolio_apy={self.portfolio_apy:.2f}%, "
            f"max_drawdown={self.max_drawdown:.1%}, "
            f"recovery={self.recovery_days}d, "
            f"survivable={self.survivable})"
        )


# ── Engine ──────────────────────────────────────────────────────────────────────

class RS001StressEngine(BaseAnalytics):
    """
    Stress test engine for RS-001 Anti-Crisis Research Strategy.

    Simulates 7 worst-case scenarios and returns StressResult per scenario.
    All scenario logic is deterministic — no external I/O required.

    Usage:
        engine = RS001StressEngine()
        result = engine.run_scenario("btc_crash_80")
        all_results = engine.run_all()
        print(engine.summary_table())
    """

    OUTPUT_PATH = "data/rs001_stress_results.json"

    # RS-001 slot weights (hardcoded for RESEARCH_ONLY phase)
    SLOT_WEIGHTS: Dict[str, float] = {
        "gmx_btc_perp":    0.20,
        "gmx_eth_perp":    0.20,
        "btc_stable_pool": 0.15,
        "eth_aggressive":  0.15,
        "gold_proxy":      0.15,
        "stablecoin_t1":   0.15,
        # Note: remaining 10% is implicit cash drag (0% APY, not a named slot)
    }

    # Fallback APYs used when live data unavailable
    FALLBACK_APYS: Dict[str, float] = {
        "gmx_btc_perp":    15.0,
        "gmx_eth_perp":    15.0,
        "btc_stable_pool":  8.0,
        "eth_aggressive":  12.0,
        "gold_proxy":       8.0,
        "stablecoin_t1":    6.0,
    }

    # Slots that can suffer impermanent loss (concentrated LP positions)
    _LP_SLOTS = frozenset({"gmx_btc_perp", "gmx_eth_perp", "btc_stable_pool", "eth_aggressive"})

    # ── Scenario implementations ────────────────────────────────────────────────

    def _scenario_btc_crash_80(self) -> StressResult:
        """
        BTC Crash -80% (2022-style bear market).

        GMX perp slots → FALLBACK_APY (perp fees still accrue but at research estimate).
        Concentrated LP slots (btc_stable_pool, eth_aggressive) → 0% APY:
          positions fully out of range due to extreme price move; fees stop.
        Max drawdown -20% from IL on LP legs and unrealised losses.
        """
        slot_apys = dict(self.FALLBACK_APYS)
        slot_apys["btc_stable_pool"] = 0.0   # extreme IL, out of range
        slot_apys["eth_aggressive"]  = 0.0   # extreme IL, out of range
        apy = self._blended_apy(slot_apys)
        return StressResult(
            scenario="btc_crash_80",
            portfolio_apy=round(apy, 4),
            max_drawdown=-0.20,
            recovery_days=180,
            survivable=True,
            details={
                "slot_apys": slot_apys,
                "trigger":   "BTC price -80% (2022 bear market style)",
                "mechanism": (
                    "GMX perps keep fallback fee APY; "
                    "conc LP slots (btc_stable_pool/eth_aggressive) fully out of range → 0% + IL"
                ),
                "note": "Stablecoin T1 + gold hedge legs intact; GMX perp fees partially persist",
            },
        )

    def _scenario_btc_crash_50(self) -> StressResult:
        """
        BTC Crash -50% (medium bear).

        GMX perp slots → FALLBACK_APY.
        LP slots partially out of range → 50% of fallback APY.
        Max drawdown -10% (less severe than -80% scenario).
        """
        slot_apys = dict(self.FALLBACK_APYS)
        slot_apys["btc_stable_pool"] = self.FALLBACK_APYS["btc_stable_pool"] * 0.50
        slot_apys["eth_aggressive"]  = self.FALLBACK_APYS["eth_aggressive"] * 0.50
        apy = self._blended_apy(slot_apys)
        return StressResult(
            scenario="btc_crash_50",
            portfolio_apy=round(apy, 4),
            max_drawdown=-0.10,
            recovery_days=90,
            survivable=True,
            details={
                "slot_apys": slot_apys,
                "trigger":   "BTC price -50% (medium bear)",
                "mechanism": (
                    "GMX perps at fallback; LP slots partially out of range → 50% APY"
                ),
                "note": "Ranges partially in play; less severe than -80%",
            },
        )

    def _scenario_gmx_exploit(self) -> StressResult:
        """
        GMX v2 smart-contract exploit.

        GMX slots (40% total) → APY = 0 (funds locked or lost in exploit).
        Remaining 60% (btc_stable_pool, eth_aggressive, gold_proxy, stablecoin_t1) intact.
        Max drawdown -40% (full capital loss on GMX exposure).
        Portfolio technically survivable: 60% intact.
        """
        slot_apys = dict(self.FALLBACK_APYS)
        slot_apys["gmx_btc_perp"] = 0.0
        slot_apys["gmx_eth_perp"] = 0.0
        apy = self._blended_apy(slot_apys)
        return StressResult(
            scenario="gmx_exploit",
            portfolio_apy=round(apy, 4),
            max_drawdown=-0.40,
            recovery_days=365,
            survivable=True,
            details={
                "slot_apys":       slot_apys,
                "trigger":         "GMX v2 smart-contract exploit",
                "mechanism":       "gmx_btc_perp + gmx_eth_perp (40%) → APY=0; remaining 60% intact",
                "failed_slots":    ["gmx_btc_perp", "gmx_eth_perp"],
                "failed_weight":   0.40,
                "note": "Capital loss limited to GMX exposure; non-GMX legs unaffected",
            },
        )

    def _scenario_il_extreme(self) -> StressResult:
        """
        IL extreme: ALL LP positions simultaneously out of range.

        All LP slots (gmx_btc_perp, gmx_eth_perp, btc_stable_pool, eth_aggressive) → 0% APY.
        Only gold_proxy and stablecoin_t1 continue earning.
        Max drawdown -15% from unrealised IL across LP legs.
        """
        slot_apys: Dict[str, float] = {k: 0.0 for k in self.FALLBACK_APYS}
        slot_apys["gold_proxy"]    = self.FALLBACK_APYS["gold_proxy"]
        slot_apys["stablecoin_t1"] = self.FALLBACK_APYS["stablecoin_t1"]
        apy = self._blended_apy(slot_apys)
        return StressResult(
            scenario="il_extreme",
            portfolio_apy=round(apy, 4),
            max_drawdown=-0.15,
            recovery_days=60,
            survivable=True,
            details={
                "slot_apys":   slot_apys,
                "trigger":     "All LP positions simultaneously out of range",
                "mechanism":   (
                    "gmx_btc_perp / gmx_eth_perp / btc_stable_pool / eth_aggressive → 0%; "
                    "gold_proxy + stablecoin_t1 earn normally"
                ),
                "lp_slots_affected": sorted(self._LP_SLOTS),
                "note": "Temporary; ranges readjust as market stabilises (est. 60 days)",
            },
        )

    def _scenario_feed_down(self) -> StressResult:
        """
        DeFiLlama feed down (all data sources unavailable).

        All slots → FALLBACK_APYS (hardcoded research estimates).
        Minimal NAV impact: portfolio continues operating on stale/fallback data.
        Max drawdown -1% (risk of mis-allocation only; no capital loss).
        """
        slot_apys = dict(self.FALLBACK_APYS)
        apy = self._blended_apy(slot_apys)
        return StressResult(
            scenario="feed_down",
            portfolio_apy=round(apy, 4),
            max_drawdown=-0.01,
            recovery_days=7,
            survivable=True,
            details={
                "slot_apys": slot_apys,
                "trigger":   "DeFiLlama API + all data sources unavailable",
                "mechanism": "System falls back to FALLBACK_APYS; portfolio continues at research estimates",
                "note": "Minimal NAV impact; primary risk is stale data causing sub-optimal allocation",
            },
        )

    def _scenario_multi_contagion(self) -> StressResult:
        """
        Multi-protocol contagion: 3 protocols fail simultaneously.

        Top-3 by weight: gmx_btc_perp (20%) + gmx_eth_perp (20%) + btc_stable_pool (15%) = 55%.
        Max drawdown = -55% (capital loss on all three failing protocols).
        NOT survivable: >50% portfolio loss breaches survival threshold.
        """
        failed_slots = ["gmx_btc_perp", "gmx_eth_perp", "btc_stable_pool"]
        slot_apys = dict(self.FALLBACK_APYS)
        failed_weight = 0.0
        for slot in failed_slots:
            slot_apys[slot] = 0.0
            failed_weight += self.SLOT_WEIGHTS[slot]

        apy = self._blended_apy(slot_apys)
        max_drawdown = -round(failed_weight, 4)   # -0.55

        return StressResult(
            scenario="multi_contagion",
            portfolio_apy=round(apy, 4),
            max_drawdown=max_drawdown,
            recovery_days=730,
            survivable=False,   # >50% loss → not survivable
            details={
                "slot_apys":          slot_apys,
                "trigger":            "3-protocol simultaneous failure (contagion event)",
                "failed_slots":       failed_slots,
                "failed_weight_pct":  round(failed_weight * 100, 1),
                "mechanism": (
                    f"Top-3 by weight ({', '.join(failed_slots)}) → 0; "
                    f"drawdown = {failed_weight:.0%}"
                ),
                "note": "Drawdown >50% → portfolio not survivable under institutional risk rules",
            },
        )

    def _scenario_stablecoin_depeg(self) -> StressResult:
        """
        Stablecoin depeg (USDC/DAI -3%).

        stablecoin_t1 slot → 0% APY during depeg event; -3% NAV impact on that slot.
        Portfolio-level max drawdown = -3% (stablecoin_t1 weight × depeg magnitude).
        Survivable: depeg typically resolves within days.
        """
        slot_apys = dict(self.FALLBACK_APYS)
        slot_apys["stablecoin_t1"] = 0.0   # yield stops during depeg
        apy = self._blended_apy(slot_apys)
        return StressResult(
            scenario="stablecoin_depeg",
            portfolio_apy=round(apy, 4),
            max_drawdown=-0.03,
            recovery_days=14,
            survivable=True,
            details={
                "slot_apys":    slot_apys,
                "trigger":      "Stablecoin depeg (USDC/DAI -3%)",
                "mechanism":    "stablecoin_t1 slot NAV -3%; yield → 0 during depeg",
                "depeg_pct":    0.03,
                "slot_weight":  self.SLOT_WEIGHTS["stablecoin_t1"],
                "note": (
                    "Portfolio NAV impact = 15% × 3% = 0.45%; survivable. "
                    "Depeg typically resolves within 2 weeks."
                ),
            },
        )

    # ── Dispatch ────────────────────────────────────────────────────────────────

    _DISPATCH: Dict[str, str] = {
        "btc_crash_80":     "_scenario_btc_crash_80",
        "btc_crash_50":     "_scenario_btc_crash_50",
        "gmx_exploit":      "_scenario_gmx_exploit",
        "il_extreme":       "_scenario_il_extreme",
        "feed_down":        "_scenario_feed_down",
        "multi_contagion":  "_scenario_multi_contagion",
        "stablecoin_depeg": "_scenario_stablecoin_depeg",
    }

    # ── BaseAnalytics interface ─────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """Returns all scenario results as JSON-serializable dict."""
        results = self.run_all()
        return {
            "generated_at":        datetime.now(timezone.utc).isoformat(),
            "strategy":            "RS-001 Anti-Crisis",
            "module":              "spa_core/analytics/rs001_stress_engine.py",
            "scenario_count":      len(results),
            "all_survivable":      self.all_survivable(),
            "worst_case_scenario": self.worst_case().scenario,
            "scenarios":           [r.to_dict() for r in results],
        }

    # ── Public API ──────────────────────────────────────────────────────────────

    def run_scenario(self, scenario: str) -> StressResult:
        """
        Run a single named stress scenario.

        Args:
            scenario: one of SCENARIOS

        Returns:
            StressResult

        Raises:
            ValueError: if scenario name is not recognised
        """
        if scenario not in self._DISPATCH:
            raise ValueError(
                f"Unknown scenario {scenario!r}. Valid: {sorted(self._DISPATCH)}"
            )
        method = getattr(self, self._DISPATCH[scenario])
        return method()

    def run_all(self) -> List[StressResult]:
        """
        Run all 7 scenarios in SCENARIOS order.

        Returns:
            list of StressResult (length == 7)
        """
        return [self.run_scenario(s) for s in SCENARIOS]

    def worst_case(self) -> StressResult:
        """
        Return the scenario with the lowest portfolio_apy.

        In practice this is 'il_extreme' (2.1% APY when all LP positions out of range).
        """
        results = self.run_all()
        return min(results, key=lambda r: r.portfolio_apy)

    def all_survivable(self) -> bool:
        """
        True if the portfolio survives ALL 7 scenarios.

        Returns False because multi_contagion.survivable == False (55% loss).
        """
        return all(r.survivable for r in self.run_all())

    def summary_table(self) -> str:
        """
        Markdown table of all 7 scenarios.

        Columns: Scenario | Portfolio APY (%) | Max Drawdown | Recovery (days) | Survivable
        """
        results = self.run_all()
        lines = [
            "| Scenario | Portfolio APY (%) | Max Drawdown | Recovery (days) | Survivable |",
            "|---|---|---|---|---|",
        ]
        for r in results:
            survivable_mark = "✓" if r.survivable else "✗"
            lines.append(
                f"| {r.scenario} "
                f"| {r.portfolio_apy:.2f}% "
                f"| {r.max_drawdown:.1%} "
                f"| {r.recovery_days} "
                f"| {survivable_mark} |"
            )
        return "\n".join(lines) + "\n"

    def save(self, data_dir: str = "data") -> str:
        """
        Atomically save all scenario results to data/rs001_stress_results.json.

        Returns the path written.
        """
        results = self.run_all()
        payload = {
            "generated_at":       datetime.now(timezone.utc).isoformat(),
            "strategy":           "RS-001 Anti-Crisis",
            "module":             "spa_core/analytics/rs001_stress_engine.py",
            "scenario_count":     len(results),
            "all_survivable":     self.all_survivable(),
            "worst_case_scenario": self.worst_case().scenario,
            "scenarios":          [r.to_dict() for r in results],
        }
        out_dir = Path(data_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "rs001_stress_results.json"
        from spa_core.utils.atomic import atomic_save
        atomic_save(payload, str(out_path))
        return str(out_path)

    # ── Internal helpers ────────────────────────────────────────────────────────

    def _blended_apy(self, slot_apys: Dict[str, float]) -> float:
        """Weighted blended APY (%) across all SLOT_WEIGHTS slots."""
        total = 0.0
        for slot, weight in self.SLOT_WEIGHTS.items():
            total += weight * slot_apys.get(slot, 0.0)
        return total
