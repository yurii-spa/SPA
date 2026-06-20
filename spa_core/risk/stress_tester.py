"""
spa_core/risk/stress_tester.py

Scenario-based stress testing for the SPA stablecoin DeFi portfolio — v2.

Applies five deterministic shock scenarios to the live position book
(``data/current_positions.json``) and estimates the dollar and percent
impact of each on portfolio NAV:

  1. "USDC Depeg 2023"   — USDC trades at $0.87 (SVB, March 2023). Mark down
                           USDC lending positions (Aave / Compound family).
  2. "DeFi Contagion"    — one T2 protocol loses 50% TVL; the largest
                           Morpho / Euler / Yearn position is written to 0.
  3. "Yield Collapse"    — all APYs fall to 0.5% (bear 2022); 30-day revenue
                           shortfall vs the current blended APY.
  4. "Smart Contract Hack" — the single largest position is fully lost.
  5. "Liquidity Crisis"  — positions frozen 7 days: exit slippage + foregone
                           yield opportunity cost.

Output: ``data/stress_test_results.json`` (atomic write).

Constraints: stdlib only, atomic writes, deterministic, LLM FORBIDDEN.

CLI:
    python3 -m spa_core.risk.stress_tester --check
    python3 -m spa_core.risk.stress_tester --run
    python3 -m spa_core.risk.stress_tester --run --data-dir data
"""
from __future__ import annotations

import json
import os
import sys
from typing import Optional

__all__ = ["StressTester", "SCENARIO_NAMES"]

# ── Scenario parameters (documented assumptions) ─────────────────────────────
USDC_DEPEG_PRICE = 0.87           # USDC spot during the SVB depeg low
T2_TVL_LOSS_FRACTION = 0.50       # contagion: 50% TVL evaporates
YIELD_COLLAPSE_APY = 0.005        # all yields compress to 0.5%
YIELD_COLLAPSE_DAYS = 30
LIQUIDITY_FREEZE_DAYS = 7
LIQUIDITY_SLIPPAGE_PCT = 0.02     # 2% forced-exit price impact
DEFAULT_CAPITAL = 100_000.0
DEFAULT_BLENDED_APY = 0.048       # fallback blended APY if none on file

SCENARIO_NAMES = [
    "USDC Depeg 2023",
    "DeFi Contagion",
    "Yield Collapse",
    "Smart Contract Hack",
    "Liquidity Crisis",
]

# Protocol classification by name substring (lowercase match).
USDC_LENDING_KEYS = ("aave", "compound")          # USDC money markets
T2_CONTAGION_KEYS = ("morpho", "euler", "yearn")  # T2 vault protocols


def _atomic_write_json(path: str, payload: dict) -> None:
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    tmp = f"{path}.tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    os.replace(tmp, path)


class StressTester:
    """Runs the five-scenario stress suite against a position book."""

    def __init__(self, positions: dict, capital: float = DEFAULT_CAPITAL,
                 blended_apy: float = DEFAULT_BLENDED_APY) -> None:
        # positions: {protocol_key: usd_value}
        self.positions = {k: float(v) for k, v in (positions or {}).items()
                          if isinstance(v, (int, float)) and v > 0}
        self.capital = float(capital)
        self.blended_apy = float(blended_apy)

    # -- loaders ---------------------------------------------------------------

    @classmethod
    def from_data(cls, data_dir: str = "data") -> "StressTester":
        positions, capital = _load_positions(data_dir)
        blended = _load_blended_apy(data_dir)
        return cls(positions=positions, capital=capital, blended_apy=blended)

    # -- helpers ---------------------------------------------------------------

    @property
    def deployed_usd(self) -> float:
        return sum(self.positions.values())

    def _matching(self, keys: tuple) -> dict:
        return {p: v for p, v in self.positions.items()
                if any(k in p.lower() for k in keys)}

    def _pct(self, loss_usd: float) -> float:
        if self.capital <= 0:
            return 0.0
        return round(loss_usd / self.capital * 100.0, 4)

    # -- scenarios -------------------------------------------------------------

    def scenario_usdc_depeg(self) -> dict:
        affected = self._matching(USDC_LENDING_KEYS)
        drop = 1.0 - USDC_DEPEG_PRICE
        loss = sum(affected.values()) * drop
        return {
            "scenario": "USDC Depeg 2023",
            "description": (
                f"USDC trades at ${USDC_DEPEG_PRICE:.2f} (SVB Mar-2023). "
                f"Mark down {len(affected)} USDC lending positions by "
                f"{drop:.0%}."
            ),
            "assumptions": {
                "usdc_price": USDC_DEPEG_PRICE,
                "markdown_pct": round(drop * 100, 2),
                "affected_protocols": sorted(affected.keys()),
            },
            "impact_usd": round(loss, 2),
            "impact_pct": self._pct(loss),
        }

    def scenario_defi_contagion(self) -> dict:
        t2 = self._matching(T2_CONTAGION_KEYS)
        if t2:
            worst = max(t2, key=t2.get)
            loss = t2[worst] * 1.0  # position drops to 0
        else:
            worst, loss = None, 0.0
        return {
            "scenario": "DeFi Contagion",
            "description": (
                "A single T2 protocol suffers a 50% TVL collapse; its largest "
                "position (Morpho/Euler/Yearn) is written down to zero."
            ),
            "assumptions": {
                "tvl_loss_fraction": T2_TVL_LOSS_FRACTION,
                "wiped_protocol": worst,
                "t2_candidates": sorted(t2.keys()),
            },
            "impact_usd": round(loss, 2),
            "impact_pct": self._pct(loss),
        }

    def scenario_yield_collapse(self) -> dict:
        # Revenue shortfall over 30 days vs current blended APY.
        delta_apy = max(0.0, self.blended_apy - YIELD_COLLAPSE_APY)
        loss = self.deployed_usd * delta_apy * (YIELD_COLLAPSE_DAYS / 365.0)
        return {
            "scenario": "Yield Collapse",
            "description": (
                f"All APYs compress to {YIELD_COLLAPSE_APY:.1%} (bear-2022). "
                f"Revenue shortfall over {YIELD_COLLAPSE_DAYS} days vs the "
                f"current blended {self.blended_apy:.2%} APY."
            ),
            "assumptions": {
                "collapsed_apy": YIELD_COLLAPSE_APY,
                "current_blended_apy": round(self.blended_apy, 4),
                "horizon_days": YIELD_COLLAPSE_DAYS,
                "deployed_usd": round(self.deployed_usd, 2),
            },
            "impact_usd": round(loss, 2),
            "impact_pct": self._pct(loss),
        }

    def scenario_smart_contract_hack(self) -> dict:
        if self.positions:
            largest = max(self.positions, key=self.positions.get)
            loss = self.positions[largest]
        else:
            largest, loss = None, 0.0
        return {
            "scenario": "Smart Contract Hack",
            "description": (
                "The single largest position is exploited and fully lost "
                "(100% drawdown of that protocol exposure)."
            ),
            "assumptions": {
                "hacked_protocol": largest,
                "position_usd": round(loss, 2),
            },
            "impact_usd": round(loss, 2),
            "impact_pct": self._pct(loss),
        }

    def scenario_liquidity_crisis(self) -> dict:
        # Forced 7-day freeze: exit slippage + foregone yield opportunity cost.
        slippage = self.deployed_usd * LIQUIDITY_SLIPPAGE_PCT
        opportunity = self.deployed_usd * self.blended_apy * (LIQUIDITY_FREEZE_DAYS / 365.0)
        loss = slippage + opportunity
        return {
            "scenario": "Liquidity Crisis",
            "description": (
                f"Positions cannot be exited for {LIQUIDITY_FREEZE_DAYS} days: "
                f"{LIQUIDITY_SLIPPAGE_PCT:.0%} forced-exit price impact plus "
                f"foregone yield opportunity cost."
            ),
            "assumptions": {
                "freeze_days": LIQUIDITY_FREEZE_DAYS,
                "slippage_pct": round(LIQUIDITY_SLIPPAGE_PCT * 100, 2),
                "slippage_usd": round(slippage, 2),
                "opportunity_cost_usd": round(opportunity, 2),
            },
            "impact_usd": round(loss, 2),
            "impact_pct": self._pct(loss),
        }

    # -- aggregate -------------------------------------------------------------

    def analyze(self) -> dict:
        scenarios = [
            self.scenario_usdc_depeg(),
            self.scenario_defi_contagion(),
            self.scenario_yield_collapse(),
            self.scenario_smart_contract_hack(),
            self.scenario_liquidity_crisis(),
        ]
        worst = max(scenarios, key=lambda s: s["impact_usd"]) if scenarios else None
        return {
            "module": "stress_tester_v2",
            "is_demo": False,
            "capital_usd": round(self.capital, 2),
            "deployed_usd": round(self.deployed_usd, 2),
            "num_positions": len(self.positions),
            "worst_case_scenario": worst["scenario"] if worst else None,
            "worst_case_impact_usd": worst["impact_usd"] if worst else 0.0,
            "worst_case_impact_pct": worst["impact_pct"] if worst else 0.0,
            "scenarios": scenarios,
        }


# ─── Data loading ────────────────────────────────────────────────────────────

def _load_positions(data_dir: str) -> tuple:
    path = os.path.join(data_dir, "current_positions.json")
    if not os.path.exists(path):
        return {}, DEFAULT_CAPITAL
    try:
        with open(path, "r", encoding="utf-8") as fh:
            doc = json.load(fh)
    except Exception:
        return {}, DEFAULT_CAPITAL
    positions = doc.get("positions", {}) if isinstance(doc, dict) else {}
    capital = doc.get("capital_usd", DEFAULT_CAPITAL) if isinstance(doc, dict) else DEFAULT_CAPITAL
    if not isinstance(capital, (int, float)) or capital <= 0:
        capital = DEFAULT_CAPITAL
    return positions, float(capital)


def _load_blended_apy(data_dir: str) -> float:
    """Read the latest blended APY (apy_today) from the equity curve."""
    path = os.path.join(data_dir, "equity_curve_daily.json")
    if not os.path.exists(path):
        return DEFAULT_BLENDED_APY
    try:
        with open(path, "r", encoding="utf-8") as fh:
            doc = json.load(fh)
        daily = doc.get("daily", []) if isinstance(doc, dict) else doc
        for entry in reversed(daily):
            if isinstance(entry, dict) and isinstance(entry.get("apy_today"), (int, float)):
                return float(entry["apy_today"]) / 100.0  # apy_today is in percent
    except Exception:
        pass
    return DEFAULT_BLENDED_APY


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main(argv: Optional[list] = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    run_mode = "--run" in args
    data_dir = "data"
    for i, a in enumerate(args):
        if a == "--data-dir" and i + 1 < len(args):
            data_dir = args[i + 1]

    tester = StressTester.from_data(data_dir)
    result = tester.analyze()

    print(f"[stress_tester] capital ${result['capital_usd']:,.0f}, "
          f"deployed ${result['deployed_usd']:,.0f}, "
          f"{result['num_positions']} positions")
    for sc in result["scenarios"]:
        print(f"  {sc['scenario']:<22} loss ${sc['impact_usd']:>12,.2f}  "
              f"({sc['impact_pct']:.4f}% of NAV)")
    print(f"  → worst case: {result['worst_case_scenario']} "
          f"(${result['worst_case_impact_usd']:,.2f})")

    if run_mode:
        out = os.path.join(data_dir, "stress_test_results.json")
        _atomic_write_json(out, result)
        print(f"[stress_tester] saved → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
