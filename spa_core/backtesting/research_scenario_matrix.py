"""
spa_core/backtesting/research_scenario_matrix.py

Stress scenario matrix for RS-001 (Anti-Crisis) and RS-002 (Cashflow).
Runs 60 scenarios per strategy = 120 total.

Scenario dimensions for RS-001:
  - BTC price move: -50%, -30%, -10%, 0%, +20%, +50%
  - Market regime: bear, neutral, bull
  - Duration: 30d, 90d, 180d

Scenario dimensions for RS-002:
  - BTC move: -50%, -30%, -10%, 0%, +20%, +50%
  - BTC volatility: low (15% annualized), medium (40%), high (80%)
  - LP range width: narrow (±10%), medium (±30%), wide (±50%)

Each scenario returns:
  {scenario_id, strategy, btc_move, regime/vol/range,
   gross_apy, il_drag, net_apy, risk_score, verdict}

Usage:
    from spa_core.backtesting.research_scenario_matrix import ResearchScenarioMatrix

    m = ResearchScenarioMatrix()
    m.run_all()
    print(m.summary_table())
    m.save()

Stdlib only. LLM FORBIDDEN. Atomic writes.
Date: 2026-06-19 (MP-1313, Sprint v9.29)
"""
from __future__ import annotations

import json
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from spa_core.utils.atomic import atomic_save


# ─── RS-001 Anti-Crisis: allocation weights and component APYs ────────────────

_RS001_COMPONENTS: Dict[str, dict] = {
    "gmx_btc_exposure":    {"weight": 0.20, "base_apy": 15.0, "crypto_corr": 0.90},
    "gmx_eth_exposure":    {"weight": 0.10, "base_apy": 15.0, "crypto_corr": 0.85},
    "btc_stable_pool":     {"weight": 0.35, "base_apy": 25.0, "crypto_corr": 0.60},
    "eth_aggressive_pool": {"weight": 0.05, "base_apy": 45.0, "crypto_corr": 0.80},
    "gold_proxy":          {"weight": 0.15, "base_apy": 15.0, "crypto_corr": -0.20},
    "stablecoin_t1":       {"weight": 0.15, "base_apy":  3.0, "crypto_corr":  0.00},
}

# Regime multipliers for gross APY (bear/neutral/bull)
_REGIME_MULTIPLIERS: Dict[str, Dict[str, float]] = {
    "bear":    {"gmx_btc_exposure": 0.40, "gmx_eth_exposure": 0.45,
                "btc_stable_pool": 0.55, "eth_aggressive_pool": 0.30,
                "gold_proxy": 1.30, "stablecoin_t1": 0.95},
    "neutral": {"gmx_btc_exposure": 1.00, "gmx_eth_exposure": 1.00,
                "btc_stable_pool": 1.00, "eth_aggressive_pool": 1.00,
                "gold_proxy": 1.00, "stablecoin_t1": 1.00},
    "bull":    {"gmx_btc_exposure": 1.60, "gmx_eth_exposure": 1.55,
                "btc_stable_pool": 1.40, "eth_aggressive_pool": 1.80,
                "gold_proxy": 0.70, "stablecoin_t1": 1.02},
}

# BTC move impact on RS-001 components: drags per 10% BTC drop for crypto-correlated
_RS001_BTC_DRAG_PER_10PCT: Dict[str, float] = {
    "gmx_btc_exposure":    1.80,  # % APY drag per 10% BTC down move
    "gmx_eth_exposure":    1.50,
    "btc_stable_pool":     0.80,
    "eth_aggressive_pool": 1.20,
    "gold_proxy":         -0.30,  # gold benefits from BTC crash (flight to safety)
    "stablecoin_t1":       0.00,
}

# ─── RS-002 Cashflow / Concentrated LP: allocation and APY assumptions ────────

_RS002_COMPONENTS: Dict[str, dict] = {
    "btc_usd_conc_liq":    {"weight": 0.60, "gross_apy": 40.0},
    "rwa_conc_liq":        {"weight": 0.10, "gross_apy": 18.0},
    "trader_losses_vault": {"weight": 0.14, "gross_apy": 20.0},
    "stablecoin_deposit":  {"weight": 0.16, "gross_apy":  4.0},
}

# IL model: fraction of gross APY lost to impermanent loss
# Based on: IL ≈ 2 * sqrt(1 + price_ratio) / (2 + price_ratio) - 1
# Simplified linear approximation for scenario modeling

def _estimate_il_pct(btc_move_pct: float, range_width_pct: float, vol_annual: float) -> float:
    """
    Estimate annualized impermanent loss as a percentage of position value.

    For concentrated liquidity positions:
    - BTC move: the directional move (negative = crash, positive = rally)
    - range_width_pct: half-width of the price range (±10%, ±30%, ±50%)
    - vol_annual: annualized BTC volatility

    Returns IL as positive float (e.g., 12.5 means 12.5% APY drag from IL).
    """
    abs_move = abs(btc_move_pct) / 100.0
    range_half = range_width_pct / 100.0

    # Classic IL formula: IL = 2*sqrt(r)/(1+r) - 1 where r = price ratio
    # For full-range position after btc_move
    if abs_move < 1e-9:
        classic_il = 0.0
    else:
        r = 1.0 + abs_move
        classic_il = abs(2.0 * math.sqrt(r) / (1.0 + r) - 1.0)

    # Concentrated LP amplification: 1/range_half when move exceeds range
    if abs_move > range_half:
        # Position is out of range — fee income stops, pure IL
        concentration_factor = min(abs_move / range_half, 8.0)
    else:
        concentration_factor = 1.0 + (abs_move / range_half) * 1.5

    # Volatility friction adds to IL even without directional move (gamma decay)
    vol_friction = (vol_annual / 100.0) ** 2 * 0.15

    raw_il = (classic_il * concentration_factor + vol_friction) * 100.0
    return round(min(raw_il, 95.0), 2)  # cap at 95% (never lose more than position)


def _rs002_gross_apy(btc_move_pct: float, vol_annual: float, range_width_pct: float) -> float:
    """
    Gross blended APY for RS-002 before IL deduction.
    BTC/USD conc LP APY scales with volatility (more fees) and suffers if out of range.
    """
    # BTC/USD leg: APY scales with realized vol, but collapses if move exceeds range
    range_half = range_width_pct / 100.0
    abs_move = abs(btc_move_pct) / 100.0

    # Vol scaling: higher vol → more fee income
    vol_scale = 1.0 + (vol_annual - 40.0) / 100.0 * 0.5  # normalized around vol=40%

    if abs_move <= range_half:
        # In-range: full fee income
        btc_lp_apy = 40.0 * vol_scale
    else:
        # Out-of-range: fee income stops, position just holds one asset
        in_range_fraction = range_half / abs_move if abs_move > 0 else 0.0
        btc_lp_apy = 40.0 * vol_scale * in_range_fraction

    # Trader losses vault: inversely correlated with BTC trend strength
    # In trending markets (large moves), traders make money, vault suffers
    trend_drag = min(abs_move * 25.0, 15.0)  # up to 15% APY drag in strong trends
    vault_apy = max(20.0 - trend_drag, 0.0)

    # RWA conc LP: low crypto correlation, stable-ish
    rwa_apy = 18.0 * (1.0 - abs_move * 0.1)  # slight drag in large market moves

    # Stablecoin: stable
    stable_apy = 4.0

    gross = (
        _RS002_COMPONENTS["btc_usd_conc_liq"]["weight"]    * btc_lp_apy +
        _RS002_COMPONENTS["rwa_conc_liq"]["weight"]        * rwa_apy +
        _RS002_COMPONENTS["trader_losses_vault"]["weight"] * vault_apy +
        _RS002_COMPONENTS["stablecoin_deposit"]["weight"]  * stable_apy
    )
    return round(gross, 2)


# ─── RS-001 scenario model ────────────────────────────────────────────────────

def _rs001_gross_apy(btc_move_pct: float, regime: str) -> float:
    """
    Blended gross APY for RS-001 under a given BTC move and market regime.
    """
    regime_mults = _REGIME_MULTIPLIERS.get(regime, _REGIME_MULTIPLIERS["neutral"])
    drag_per_10 = (btc_move_pct / -10.0)  # positive when BTC is down

    total = 0.0
    for name, comp in _RS001_COMPONENTS.items():
        base = comp["base_apy"] * regime_mults[name]
        drag = _RS001_BTC_DRAG_PER_10PCT[name] * drag_per_10
        component_apy = max(base + drag, 0.0)
        total += comp["weight"] * component_apy

    return round(total, 2)


def _rs001_risk_score(btc_move_pct: float, regime: str, net_apy: float) -> float:
    """
    Risk score 0–10 for RS-001 scenario.
    Higher = riskier (more negative outcomes, high crypto exposure in crash).
    """
    score = 5.0
    # BTC crash risk
    if btc_move_pct <= -30:
        score += 2.5
    elif btc_move_pct <= -10:
        score += 1.0
    elif btc_move_pct >= 30:
        score -= 0.5
    # Regime risk
    if regime == "bear":
        score += 1.5
    elif regime == "bull":
        score -= 1.0
    # Net APY penalty
    if net_apy < 0:
        score += 2.0
    elif net_apy < 5:
        score += 0.5
    return round(min(max(score, 0.0), 10.0), 1)


# ─── RS-002 risk score ────────────────────────────────────────────────────────

def _rs002_risk_score(btc_move_pct: float, vol_annual: float,
                      range_width_pct: float, net_apy: float) -> float:
    """
    Risk score 0–10 for RS-002 scenario.
    Concentrated LP is highly sensitive to vol and directional moves.
    """
    score = 5.0
    # BTC move risk
    if btc_move_pct <= -30:
        score += 2.5
    elif btc_move_pct <= -10:
        score += 1.5
    elif btc_move_pct >= 30:
        score += 0.5  # upside moves also cause IL in conc LP
    # Volatility risk
    if vol_annual >= 80:
        score += 2.0
    elif vol_annual >= 40:
        score += 0.5
    # Narrow range = higher risk
    if range_width_pct <= 10:
        score += 1.5
    elif range_width_pct <= 30:
        score += 0.5
    # Net APY penalty
    if net_apy < 0:
        score += 2.0
    elif net_apy < 5:
        score += 0.5
    return round(min(max(score, 0.0), 10.0), 1)


# ─── ResearchScenarioMatrix ───────────────────────────────────────────────────

class ResearchScenarioMatrix:
    """
    Stress scenario matrix for RS-001 and RS-002 research strategies.

    RS-001 dimensions (60 scenarios):
        BTC move × regime × duration = 6 × 3 × (implicit, duration only adjusts risk) = 60
        Actually: 6 btc_moves × 3 regimes × (duration not changing APY model, used as label) = wait
        Per spec: 6 × 3 × (30d/90d/180d) = 54 → but 60 needed.
        Resolution: add "extreme" regime variant → 6 BTC moves × (3 regimes + extra) ...
        No: use 6 btc_moves × 3 regimes = 18, then 3 durations × 18 = 54, add 6 edge cases = 60.

        Actual design: 6 btc_moves × 3 regimes × 3 durations = 54 + 6 edge scenarios = 60.
        Edge cases: Black swan (BTC -80%), LUNA-style (BTC -90%), DeFi exploit,
                    stablecoin depeg, regulatory ban, hyperinflation.

        Simpler: 6 btc_moves × 3 regimes = 18 base, then each at 3 durations → 54,
                 plus 6 explicit stress tests = 60.

    RS-002 dimensions (60 scenarios):
        6 BTC moves × 3 volatility levels × (narrow/medium/wide) = 6 × 3 × (range_widths)
        but that's only 3 range widths → 6 × 3 × 3 = 54 + 6 stress = 60.

        Actual: 6 × 3 × 3 = 54 base + 6 edge scenarios = 60.
    """

    # RS-001 scenario parameters
    _RS001_BTC_MOVES = [-50.0, -30.0, -10.0, 0.0, 20.0, 50.0]
    _RS001_REGIMES   = ["bear", "neutral", "bull"]
    _RS001_DURATIONS = [30, 90, 180]

    # RS-002 scenario parameters
    _RS002_BTC_MOVES    = [-50.0, -30.0, -10.0, 0.0, 20.0, 50.0]
    _RS002_VOLS         = [15.0, 40.0, 80.0]      # annualized %
    _RS002_RANGE_WIDTHS = [10.0, 30.0, 50.0]       # ± half-width %

    def __init__(self) -> None:
        self._results: List[dict] = []
        self._rs001_results: List[dict] = []
        self._rs002_results: List[dict] = []
        self._ran: bool = False

    # ── RS-001 ────────────────────────────────────────────────────────────────

    def run_rs001_scenarios(self) -> List[dict]:
        """
        Generate and return all 60 RS-001 Anti-Crisis stress scenarios.

        Base: 6 btc_moves × 3 regimes × 3 durations = 54
        Edge: 6 explicit tail-risk scenarios
        Total: 60

        Returns list of scenario dicts, each containing:
            scenario_id, strategy, btc_move, regime, duration_days,
            gross_apy, il_drag, net_apy, risk_score, verdict
        """
        results: List[dict] = []
        idx = 0

        # Base scenarios: 6 × 3 × 3 = 54
        for btc_move in self._RS001_BTC_MOVES:
            for regime in self._RS001_REGIMES:
                for duration in self._RS001_DURATIONS:
                    idx += 1
                    gross = _rs001_gross_apy(btc_move, regime)
                    # Duration scaling: longer duration smooths out short-term shock
                    duration_factor = 1.0 if duration >= 90 else (0.85 if duration == 30 else 1.0)
                    il_drag = 0.0   # RS-001 has no LP components → no IL
                    # Small drawdown adjustment for very short horizons in bear markets
                    if duration == 30 and regime == "bear":
                        net = gross * duration_factor * 0.90
                    elif duration == 30 and btc_move <= -30:
                        net = gross * duration_factor * 0.88
                    else:
                        net = gross * duration_factor
                    net = round(net, 2)
                    risk = _rs001_risk_score(btc_move, regime, net)
                    results.append({
                        "scenario_id":  f"RS001-{idx:03d}",
                        "strategy":     "RS-001",
                        "btc_move":     btc_move,
                        "regime":       regime,
                        "duration_days": duration,
                        "vol_annual":   None,
                        "range_width":  None,
                        "gross_apy":    gross,
                        "il_drag":      il_drag,
                        "net_apy":      net,
                        "risk_score":   risk,
                        "verdict":      "POSITIVE" if net > 0 else "NEGATIVE",
                    })

        # Edge scenarios (6 tail-risk events)
        edge_cases = [
            {"label": "black_swan_btc_crash",   "btc_move": -80.0, "regime": "bear",    "duration": 30},
            {"label": "luna_style_collapse",     "btc_move": -90.0, "regime": "bear",    "duration": 14},
            {"label": "defi_exploit_contagion",  "btc_move": -40.0, "regime": "bear",    "duration": 7},
            {"label": "stablecoin_depeg",        "btc_move": -20.0, "regime": "neutral", "duration": 3},
            {"label": "regulatory_ban",          "btc_move": -60.0, "regime": "bear",    "duration": 60},
            {"label": "hyperinflation_rally",    "btc_move": 100.0, "regime": "bull",    "duration": 90},
        ]
        for edge in edge_cases:
            idx += 1
            gross = _rs001_gross_apy(edge["btc_move"], edge["regime"])
            # Short-duration edge events: extra penalty
            duration_factor = max(0.50, 1.0 - max(0, (90 - edge["duration"]) / 90.0) * 0.40)
            il_drag = 0.0
            net = round(gross * duration_factor, 2)
            risk = _rs001_risk_score(edge["btc_move"], edge["regime"], net)
            results.append({
                "scenario_id":   f"RS001-{idx:03d}",
                "strategy":      "RS-001",
                "btc_move":      edge["btc_move"],
                "regime":        edge["regime"],
                "duration_days": edge["duration"],
                "vol_annual":    None,
                "range_width":   None,
                "gross_apy":     gross,
                "il_drag":       il_drag,
                "net_apy":       net,
                "risk_score":    risk,
                "verdict":       "POSITIVE" if net > 0 else "NEGATIVE",
                "edge_label":    edge["label"],
            })

        self._rs001_results = results
        return results

    # ── RS-002 ────────────────────────────────────────────────────────────────

    def run_rs002_scenarios(self) -> List[dict]:
        """
        Generate and return all 60 RS-002 Cashflow/Concentrated LP stress scenarios.

        Base: 6 btc_moves × 3 volatility levels × 3 range widths = 54
        Edge: 6 explicit tail-risk scenarios
        Total: 60

        Returns list of scenario dicts, each containing:
            scenario_id, strategy, btc_move, vol_annual, range_width,
            gross_apy, il_drag, net_apy, risk_score, verdict
        """
        results: List[dict] = []
        idx = 0

        # Base scenarios: 6 × 3 × 3 = 54
        for btc_move in self._RS002_BTC_MOVES:
            for vol in self._RS002_VOLS:
                for rw in self._RS002_RANGE_WIDTHS:
                    idx += 1
                    gross = _rs002_gross_apy(btc_move, vol, rw)
                    il_drag = _estimate_il_pct(btc_move, rw, vol)
                    # IL drag applied only to the LP portion (60% + 10% = 70%)
                    lp_weight = (
                        _RS002_COMPONENTS["btc_usd_conc_liq"]["weight"] +
                        _RS002_COMPONENTS["rwa_conc_liq"]["weight"]
                    )
                    effective_il_drag = il_drag * lp_weight
                    net = round(gross - effective_il_drag, 2)
                    risk = _rs002_risk_score(btc_move, vol, rw, net)
                    results.append({
                        "scenario_id":   f"RS002-{idx:03d}",
                        "strategy":      "RS-002",
                        "btc_move":      btc_move,
                        "regime":        None,
                        "duration_days": None,
                        "vol_annual":    vol,
                        "range_width":   rw,
                        "gross_apy":     gross,
                        "il_drag":       round(effective_il_drag, 2),
                        "net_apy":       net,
                        "risk_score":    risk,
                        "verdict":       "POSITIVE" if net > 0 else "NEGATIVE",
                    })

        # Edge scenarios (6 tail-risk events)
        edge_cases = [
            {"label": "btc_flash_crash_narrow",   "btc_move": -80.0, "vol": 200.0, "rw": 10.0},
            {"label": "luna_depeg_extreme_vol",   "btc_move": -90.0, "vol": 300.0, "rw": 10.0},
            {"label": "sideways_low_vol",         "btc_move":   0.0, "vol":   5.0, "rw": 30.0},
            {"label": "bull_run_medium_range",    "btc_move":  80.0, "vol":  80.0, "rw": 30.0},
            {"label": "vol_spike_out_of_range",   "btc_move": -50.0, "vol": 150.0, "rw": 10.0},
            {"label": "btc_100_pct_rally_narrow", "btc_move": 100.0, "vol":  90.0, "rw": 10.0},
        ]
        for edge in edge_cases:
            idx += 1
            gross = _rs002_gross_apy(edge["btc_move"], edge["vol"], edge["rw"])
            il_drag = _estimate_il_pct(edge["btc_move"], edge["rw"], edge["vol"])
            lp_weight = (
                _RS002_COMPONENTS["btc_usd_conc_liq"]["weight"] +
                _RS002_COMPONENTS["rwa_conc_liq"]["weight"]
            )
            effective_il_drag = il_drag * lp_weight
            net = round(gross - effective_il_drag, 2)
            risk = _rs002_risk_score(edge["btc_move"], edge["vol"], edge["rw"], net)
            results.append({
                "scenario_id":   f"RS002-{idx:03d}",
                "strategy":      "RS-002",
                "btc_move":      edge["btc_move"],
                "regime":        None,
                "duration_days": None,
                "vol_annual":    edge["vol"],
                "range_width":   edge["rw"],
                "gross_apy":     gross,
                "il_drag":       round(effective_il_drag, 2),
                "net_apy":       net,
                "risk_score":    risk,
                "verdict":       "POSITIVE" if net > 0 else "NEGATIVE",
                "edge_label":    edge["label"],
            })

        self._rs002_results = results
        return results

    # ── run_all ───────────────────────────────────────────────────────────────

    def run_all(self) -> dict:
        """
        Run all 120 scenarios (60 RS-001 + 60 RS-002).

        Returns summary dict:
        {
            "total_scenarios": 120,
            "rs001_count": 60,
            "rs002_count": 60,
            "rs001": [...],
            "rs002": [...],
            "summary": <summary_table()>,
            "generated_at": ISO timestamp
        }
        """
        rs001 = self.run_rs001_scenarios()
        rs002 = self.run_rs002_scenarios()
        self._results = rs001 + rs002
        self._ran = True
        return {
            "total_scenarios": len(self._results),
            "rs001_count":     len(rs001),
            "rs002_count":     len(rs002),
            "rs001":           rs001,
            "rs002":           rs002,
            "summary":         self.summary_table(),
            "generated_at":    datetime.now(timezone.utc).isoformat(),
        }

    # ── summary_table ─────────────────────────────────────────────────────────

    def summary_table(self) -> dict:
        """
        Returns aggregated statistics per strategy:
        {
          "rs001": {"count": 60, "avg_net_apy": X, "worst_net_apy": Y,
                    "best_net_apy": Z, "positive_pct": P},
          "rs002": {"count": 60, "avg_net_apy": X, "worst_net_apy": Y,
                    "best_net_apy": Z, "positive_pct": P}
        }

        Calls run_rs001_scenarios / run_rs002_scenarios if not yet run.
        """
        if not self._rs001_results:
            self.run_rs001_scenarios()
        if not self._rs002_results:
            self.run_rs002_scenarios()

        def _stats(scenarios: List[dict]) -> dict:
            if not scenarios:
                return {"count": 0, "avg_net_apy": 0.0, "worst_net_apy": 0.0,
                        "best_net_apy": 0.0, "positive_pct": 0.0}
            apys = [s["net_apy"] for s in scenarios]
            n = len(apys)
            positive = sum(1 for a in apys if a > 0)
            return {
                "count":         n,
                "avg_net_apy":   round(sum(apys) / n, 2),
                "worst_net_apy": round(min(apys), 2),
                "best_net_apy":  round(max(apys), 2),
                "positive_pct":  round(positive / n * 100.0, 1),
            }

        return {
            "rs001": _stats(self._rs001_results),
            "rs002": _stats(self._rs002_results),
        }

    # ── save ─────────────────────────────────────────────────────────────────

    def save(self, path: str = "data/research/scenario_matrix_rs.json") -> None:
        """
        Atomically save all scenario results to JSON.

        Creates parent directories if needed.
        Uses tmp-file + os.replace pattern (atomic on POSIX).

        Args:
            path: Destination file path (absolute or relative).
        """
        if not self._ran:
            self.run_all()

        dest = Path(path)
        dest.parent.mkdir(parents=True, exist_ok=True)

        payload = {
            "generated_at":    datetime.now(timezone.utc).isoformat(),
            "total_scenarios": len(self._results),
            "rs001_count":     len(self._rs001_results),
            "rs002_count":     len(self._rs002_results),
            "summary":         self.summary_table(),
            "rs001":           self._rs001_results,
            "rs002":           self._rs002_results,
        }

        atomic_save(payload, str(dest))

    # ── to_markdown_summary ───────────────────────────────────────────────────

    def to_markdown_summary(self) -> str:
        """
        Returns a short Markdown table summarising both strategies.

        Example:
        | Strategy | Scenarios | Avg Net APY | Worst | Best | % Positive |
        |----------|-----------|-------------|-------|------|------------|
        | RS001    | 60        | 11.3%       | -6.2% | 22.1%| 72%        |
        | RS002    | 60        | 7.4%        | -31.5%| 26.8%| 48%        |
        """
        st = self.summary_table()
        rs1 = st["rs001"]
        rs2 = st["rs002"]

        lines = [
            "## Research Scenario Matrix — RS-001 & RS-002",
            "",
            "| Strategy | Scenarios | Avg Net APY | Worst Net APY | Best Net APY | % Positive |",
            "|----------|-----------|-------------|---------------|--------------|------------|",
            (
                f"| RS001    | {rs1['count']}        "
                f"| {rs1['avg_net_apy']:>7.1f}%      "
                f"| {rs1['worst_net_apy']:>7.1f}%         "
                f"| {rs1['best_net_apy']:>6.1f}%       "
                f"| {rs1['positive_pct']:>4.0f}%      |"
            ),
            (
                f"| RS002    | {rs2['count']}        "
                f"| {rs2['avg_net_apy']:>7.1f}%      "
                f"| {rs2['worst_net_apy']:>7.1f}%         "
                f"| {rs2['best_net_apy']:>6.1f}%       "
                f"| {rs2['positive_pct']:>4.0f}%      |"
            ),
            "",
            "> RS-001: No IL (no LP components). RS-002: IL applied to 70% LP weight.",
            "> Research projections only — not historical evidence.",
        ]
        return "\n".join(lines)


# ─── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys as _sys

    t0 = time.time()
    matrix = ResearchScenarioMatrix()
    result = matrix.run_all()
    elapsed = time.time() - t0

    print(matrix.to_markdown_summary())
    print()
    print(f"Total scenarios : {result['total_scenarios']}")
    print(f"RS-001          : {result['rs001_count']} scenarios")
    print(f"RS-002          : {result['rs002_count']} scenarios")
    print(f"Elapsed         : {elapsed:.3f}s")

    if "--save" in _sys.argv:
        path = "data/research/scenario_matrix_rs.json"
        matrix.save(path)
        print(f"Saved to        : {path}")
