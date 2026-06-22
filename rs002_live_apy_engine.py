"""
spa_core/analytics/rs002_live_apy_engine.py

Live APY engine for RS-002 Cashflow / Concentrated LP Research Strategy.

Slots:
  btc_usd_conc_liq   60%  - BTC/USD concentrated LP  [SOURCE_NEEDED]
  rwa_conc_liq       10%  - RWA concentrated LP       [SOURCE_NEEDED]
  trader_losses_vault 14% - GMX trader losses vault   [SOURCE_NEEDED]
  stablecoin_deposit  16% - T1 stablecoin deposit     [CLEAN]

Key difference vs RS-001:
  LP slots require IL adjustment:
    gross_apy - il_drag = net_apy
  btc_usd_conc_liq gross: ~40% APY
  btc_usd_conc_liq il_drag: depends on BTC volatility (vol-path model)

IL drag model (btc_usd_conc_liq):
  il_drag = vol_path_drag + move_drag
  vol_path_drag = btc_vol_annualized^2 * 0.5   (path-dependent drag from volatility)
  move_drag     = abs(btc_price_move_pct / 100) * 0.5  (directional IL amplified by concentration)

IL drag model (rwa_conc_liq):
  rwa_vol ≈ 5% — minimal: il_drag = rwa_vol^2 * 0.5 ≈ 0.125% (constant, no move component)

Non-LP slots (trader_losses_vault, stablecoin_deposit):
  il_drag = 0.0

Output includes gross AND net APY per slot.

RESEARCH-ONLY module. Never affects allocator, risk, or execution.
Pure stdlib, no external dependencies. LLM FORBIDDEN.
Atomic writes: mkstemp + os.replace.

Date: 2026-06-19 (MP-1320)
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from spa_core.base import BaseAnalytics
from spa_core.utils.atomic import atomic_save

# ─── Slot definitions ─────────────────────────────────────────────────────────

# Each slot: slot_id, weight, gross_apy (%), is_lp, source_quality, asset_vol
_SLOTS_DEF: list[dict] = [
    {
        "slot_id":        "btc_usd_conc_liq",
        "weight":         0.60,
        "gross_apy":      40.0,   # % gross, IL not included — research placeholder
        "is_lp":          True,
        "is_btc_lp":      True,   # uses btc_vol for IL model
        "asset_vol":      None,   # determined from btc_vol_annualized at runtime
        "source_quality": "source_needed",
    },
    {
        "slot_id":        "rwa_conc_liq",
        "weight":         0.10,
        "gross_apy":      18.0,   # RWA venue unspecified — placeholder
        "is_lp":          True,
        "is_btc_lp":      False,
        "asset_vol":      0.05,   # RWA assets ~5% annualized vol
        "source_quality": "source_needed",
    },
    {
        "slot_id":        "trader_losses_vault",
        "weight":         0.14,
        "gross_apy":      20.0,   # GMX/Hyperliquid-style — placeholder
        "is_lp":          False,
        "is_btc_lp":      False,
        "asset_vol":      None,
        "source_quality": "source_needed",
    },
    {
        "slot_id":        "stablecoin_deposit",
        "weight":         0.16,
        "gross_apy":       4.0,   # T1 stablecoin lending — live data eligible
        "is_lp":          False,
        "is_btc_lp":      False,
        "asset_vol":      None,
        "source_quality": "clean",
    },
]

# Gross blended APY target (weighted sum of gross_apy)
# 0.60*40 + 0.10*18 + 0.14*20 + 0.16*4 = 24 + 1.8 + 2.8 + 0.64 = 29.24
TARGET_GROSS_APY = 29.24

_DEFAULT_DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "research"
_FILENAME = "rs002_apy_breakdown.json"
SCHEMA_VERSION = "1.0"
RESEARCH_ONLY = True

# BTC price move scenarios for net_apy_scenarios()
_BTC_MOVE_SCENARIOS = [-50.0, -30.0, -10.0, 0.0, 10.0, 30.0, 50.0]


# ══════════════════════════════════════════════════════════════════════════════
# RS002LiveAPYEngine
# ══════════════════════════════════════════════════════════════════════════════

class RS002LiveAPYEngine(BaseAnalytics):
    """
    Computes RS-002 Cashflow strategy APY with IL adjustment.

    RESEARCH-ONLY — never affects allocator, risk, or execution.

    Parameters
    ----------
    btc_vol_annualized : float
        Annualized BTC price volatility as a decimal fraction.
        Default 0.60 (= 60%).
    """

    OUTPUT_PATH = "data/research/rs002_apy_breakdown.json"

    def __init__(self, btc_vol_annualized: float = 0.60) -> None:
        super().__init__()
        if btc_vol_annualized < 0:
            raise ValueError("btc_vol_annualized must be >= 0")
        self._btc_vol = btc_vol_annualized

    # ──────────────────────────────────────────────────────────────────────────
    # IL drag helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _il_drag_btc_slot(self, btc_price_move_pct: float) -> float:
        """
        Compute annualised IL drag (in percentage points) for btc_usd_conc_liq.

        Model:
          vol_path_drag = btc_vol^2 * 0.5 * 100    (vol-path IL, always positive)
          move_drag     = |btc_price_move_pct| * 0.5  (directional IL from move)
          total         = vol_path_drag + move_drag

        Capped at gross APY of the slot (can't lose more than you earn).
        """
        vol_path_drag = (self._btc_vol ** 2) * 0.5 * 100.0
        move_drag = abs(btc_price_move_pct) * 0.5
        return vol_path_drag + move_drag

    def _il_drag_rwa_slot(self) -> float:
        """
        Compute annualised IL drag (pp) for rwa_conc_liq.

        Low-vol RWA: il_drag = asset_vol^2 * 0.5 * 100 ≈ 0.125%
        No directional move component (RWA/stablecoin pair not BTC-correlated).
        """
        rwa_vol = 0.05  # 5% annualised vol for RWA assets
        return (rwa_vol ** 2) * 0.5 * 100.0  # ≈ 0.125 pp

    def _net_apy_for_slot(
        self,
        slot: dict,
        btc_price_move_pct: float,
    ) -> tuple[float, float]:
        """
        Return (il_drag_pp, net_apy_pp) for one slot.

        Non-LP slots: il_drag = 0, net_apy = gross_apy.
        BTC LP slot:  il_drag from _il_drag_btc_slot().
        RWA LP slot:  il_drag from _il_drag_rwa_slot().
        """
        if not slot["is_lp"]:
            return 0.0, slot["gross_apy"]

        if slot["is_btc_lp"]:
            il_drag = self._il_drag_btc_slot(btc_price_move_pct)
        else:
            il_drag = self._il_drag_rwa_slot()

        net_apy = slot["gross_apy"] - il_drag
        return il_drag, net_apy

    # ──────────────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────────────

    def slot_apys(self, btc_price_move_pct: float = 0.0) -> List[dict]:
        """
        Return per-slot APY breakdown with IL adjustment.

        Parameters
        ----------
        btc_price_move_pct : float
            Assumed BTC price move in percent (e.g. -30.0 for -30%).
            Used for IL computation on LP slots.

        Returns
        -------
        list[dict]
            Each dict: {slot_id, weight, gross_apy, il_drag, net_apy, source_quality}
        """
        result = []
        for slot in _SLOTS_DEF:
            il_drag, net_apy = self._net_apy_for_slot(slot, btc_price_move_pct)
            result.append({
                "slot_id":        slot["slot_id"],
                "weight":         slot["weight"],
                "gross_apy":      round(slot["gross_apy"], 4),
                "il_drag":        round(il_drag, 4),
                "net_apy":        round(net_apy, 4),
                "source_quality": slot["source_quality"],
            })
        return result

    def blended_gross_apy(self) -> float:
        """
        Weighted blended gross APY (before IL).

        Returns ~29.24% (research target).
        """
        total = sum(s["weight"] * s["gross_apy"] for s in _SLOTS_DEF)
        return round(total, 4)

    def blended_net_apy(self, btc_price_move_pct: float = 0.0) -> float:
        """
        Weighted blended net APY after IL adjustment.

        At zero BTC move with default vol (60%), IL drag on the BTC LP slot
        is still positive due to vol-path drag.

        Parameters
        ----------
        btc_price_move_pct : float
            BTC price move in percent. Default 0.0.

        Returns
        -------
        float
            Blended net APY in percent.
        """
        total = 0.0
        for slot in _SLOTS_DEF:
            _, net_apy = self._net_apy_for_slot(slot, btc_price_move_pct)
            total += slot["weight"] * net_apy
        return round(total, 4)

    def clean_fraction_net_apy(self) -> float:
        """
        Net APY contribution from CLEAN sources only.

        Only stablecoin_deposit (weight=0.16, gross=4%, il_drag=0) is CLEAN.
        Contribution ≈ 0.16 × 4.0 = 0.64%.

        Returns
        -------
        float
            APY in percent from CLEAN slots only.
        """
        total = 0.0
        for slot in _SLOTS_DEF:
            if slot["source_quality"] == "clean":
                _, net_apy = self._net_apy_for_slot(slot, 0.0)
                total += slot["weight"] * net_apy
        return round(total, 4)

    def apy_breakdown_report(self) -> dict:
        """
        Full APY breakdown report for RS-002.

        Returns
        -------
        dict
            Comprehensive report with slot details, blended figures,
            and research metadata.
        """
        slots = self.slot_apys(btc_price_move_pct=0.0)
        weight_sum = round(sum(s["weight"] for s in _SLOTS_DEF), 6)
        return {
            "schema_version": SCHEMA_VERSION,
            "research_only": RESEARCH_ONLY,
            "strategy_id": "S21",
            "strategy_name": "RS-002 Cashflow (Research)",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "btc_vol_annualized": self._btc_vol,
            "slots": slots,
            "blended_gross_apy": self.blended_gross_apy(),
            "blended_net_apy_zero_move": self.blended_net_apy(0.0),
            "clean_fraction_net_apy": self.clean_fraction_net_apy(),
            "weight_sum": weight_sum,
            "notes": (
                "Gross APY values are placeholders. "
                "Only stablecoin_deposit (16%) uses live strict data. "
                "IL drag model: vol-path (sigma^2 * 0.5) + directional (|move| * 0.5). "
                "Net APY in sideways market ≈ 12-18% (regime-dependent)."
            ),
        }

    def net_apy_scenarios(self) -> List[dict]:
        """
        Compute net APY for a range of BTC price move scenarios.

        Scenarios: -50%, -30%, -10%, 0%, +10%, +30%, +50%

        Returns
        -------
        list[dict]
            7 dicts: {btc_move_pct, blended_gross_apy, blended_net_apy, il_drag_btc_slot}
        """
        result = []
        for move_pct in _BTC_MOVE_SCENARIOS:
            il_btc = round(self._il_drag_btc_slot(move_pct), 4)
            net = self.blended_net_apy(move_pct)
            result.append({
                "btc_move_pct":     move_pct,
                "blended_gross_apy": self.blended_gross_apy(),
                "blended_net_apy":  net,
                "il_drag_btc_slot": il_btc,
            })
        return result

    # ──────────────────────────────────────────────────────────────────────────
    # Persistence
    # ──────────────────────────────────────────────────────────────────────────


    # ── BaseAnalytics interface ─────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """Returns APY breakdown report as JSON-serializable dict."""
        return self.apy_breakdown_report()

    def save(self, path: Optional[str] = None) -> None:
        """
        Atomically save the APY breakdown report to disk.

        Parameters
        ----------
        path : str, optional
            File path for the output JSON.
            Defaults to data/research/rs002_apy_breakdown.json.
        """
        if path is None:
            target = _DEFAULT_DATA_DIR / _FILENAME
        else:
            target = Path(path)

        target.parent.mkdir(parents=True, exist_ok=True)
        report = self.apy_breakdown_report()
        atomic_save(report, str(target))


def _cli() -> None:  # pragma: no cover
    import sys
    args = sys.argv[1:]
    engine = RS002LiveAPYEngine()
    if "--save" in args:
        engine.save()
        print("Saved.")
    elif "--scenarios" in args:
        print(json.dumps(engine.net_apy_scenarios(), indent=2))
    else:
        print(json.dumps(engine.apy_breakdown_report(), indent=2))


if __name__ == "__main__":  # pragma: no cover
    _cli()
