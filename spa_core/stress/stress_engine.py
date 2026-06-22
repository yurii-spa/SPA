"""SPA Stress Engine v1 (MP-112).

Simulate SPA portfolio performance under three historical DeFi crisis scenarios:
  - COVID-2020  : March 2020 — DeFi panic, TVL flight, USDC transient depeg
  - LUNA-2022   : May 2022   — Terra/LUNA collapse, Maple defaults, UST contagion
  - USDC-2023   : March 2023 — Silicon Valley Bank run, USDC 0.87 depeg

Capital loss modeling (``capital_loss_pct``):
  Applied once on day 0 of the scenario. Represents realized losses from protocol
  failures (e.g. Maple pool defaults, Yearn UST strategy impairment). This is
  separate from the running APY which reflects ongoing yield during the crisis.

Design constraints (CLAUDE.md FORBIDDEN list):
  - Stdlib only — no external dependencies.
  - Pure simulation — never touches data/ or live feeds.
  - LLM is forbidden from risk / execution domains; this module is analytics-only.
  - Atomic writes are the caller's responsibility (run_stress_tests.py uses tmp+replace).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Optional

# ─── Data Models ────────────────────────────────────────────────────────────


@dataclass
class StressScenario:
    """Definition of one historical DeFi stress scenario."""

    name: str
    description: str
    duration_days: int
    start_date: str  # "YYYY-MM-DD"

    # protocol_id → impact dict with keys:
    #   apy_pct          (float)  : annualised yield % during crisis
    #   tvl_usd          (float)  : TVL during crisis (used for $5M floor)
    #   available        (bool)   : False → exclude from allocation
    #   capital_loss_pct (float)  : one-time capital impairment on day-0 (0.0–1.0)
    #                               e.g. 0.50 = 50% of allocated capital is lost
    protocol_impacts: Dict[str, dict]

    # USDC peg at worst point (1.0 = fully pegged, 0.87 = SVB crisis low)
    usdc_peg: float
    notes: str


@dataclass
class StressResult:
    """Output of a single stress scenario simulation."""

    scenario_name: str
    initial_equity: float
    final_equity: float
    total_return_pct: float
    max_drawdown_pct: float
    sharpe_ratio: float
    # list of {day, equity, daily_return_pct}
    daily_equity: List[dict]
    # protocol_id → weight actually used (after TVL-floor / cap filtering)
    protocol_allocation_used: dict
    kill_switch_triggered: bool
    kill_switch_day: Optional[int]
    notes: str


# ─── Scenario Definitions ───────────────────────────────────────────────────

# Protocol tier map — used for concentration validation.
_PROTOCOL_TIERS: Dict[str, str] = {
    "aave_v3":     "T1",
    "compound_v3": "T1",
    "morpho_blue": "T2",
    "yearn_v3":    "T2",
    "euler_v2":    "T2",
    "maple":       "T2",
    "sky_susds":   "T2",  # watch-list / 0% alloc in normal conditions
}

# TVL floor from RiskPolicy v1.0
_TVL_FLOOR_USD = 5_000_000

# Kill-switch threshold from RiskPolicy v1.0 (drawdown ≥ 5%)
_KILL_SWITCH_DD = 0.05

SCENARIOS: Dict[str, StressScenario] = {

    # ── COVID-2020 ────────────────────────────────────────────────────────────
    "covid_2020": StressScenario(
        name="COVID-2020",
        description="March 2020 DeFi panic — Black Thursday. "
                    "Ethereum gas crisis, liquidation cascades, TVL flight to safety.",
        duration_days=30,
        start_date="2020-03-01",
        protocol_impacts={
            "aave_v3": {
                # Panic borrowing spiked supply APY; TVL -40%
                "apy_pct": 15.0,
                "tvl_usd": 60_000_000,    # ~-40% from normal
                "available": True,
                "capital_loss_pct": 0.0,  # Aave survived intact
            },
            "compound_v3": {
                "apy_pct": 12.0,
                "tvl_usd": 70_000_000,    # -30%
                "available": True,
                "capital_loss_pct": 0.0,
            },
            "yearn_v3": {
                # Strategies paused — near-zero yield, but capital preserved
                "apy_pct": 0.5,
                "tvl_usd": 20_000_000,    # -60%
                "available": True,
                "capital_loss_pct": 0.02, # ~2% impairment from gas + slippage
            },
            "euler_v2": {
                # Did not exist in 2020
                "apy_pct": 0.0,
                "tvl_usd": 0,
                "available": False,
                "capital_loss_pct": 0.0,
            },
            "maple": {
                # Institutional flight; credit markets froze but no defaults
                "apy_pct": 2.0,
                "tvl_usd": 25_000_000,    # -50%
                "available": True,
                "capital_loss_pct": 0.0,  # No defaults in COVID (pre-protocol)
            },
            "sky_susds": {
                # DSR stable; Maker not deeply affected
                "apy_pct": 1.0,
                "tvl_usd": 500_000_000,
                "available": True,
                "capital_loss_pct": 0.0,
            },
            "morpho_blue": {
                # Not launched yet
                "apy_pct": 0.0,
                "tvl_usd": 0,
                "available": False,
                "capital_loss_pct": 0.0,
            },
        },
        # USDC traded briefly at $0.97 on 12 March 2020 before recovering
        usdc_peg=0.97,
        notes=(
            "USDC depeg 0.97 on day 12 (Black Thursday). "
            "Yearn strategies paused most of the month (~2% slippage). "
            "Expected Sharpe ~0.3 (positive but low). "
            "No protocol defaults — capital largely preserved."
        ),
    ),

    # ── LUNA-2022 ─────────────────────────────────────────────────────────────
    "luna_2022": StressScenario(
        name="LUNA-2022",
        description="May 2022 Terra/LUNA collapse. "
                    "UST de-peg spiral, $40B evaporated, Maple pool defaults "
                    "(Babel Finance, Celsius exposure), Yearn UST strategy impairment.",
        duration_days=30,
        start_date="2022-05-01",
        protocol_impacts={
            "aave_v3": {
                # UST/LUNA liquidation wave boosted borrow rates
                "apy_pct": 8.0,
                "tvl_usd": 7_500_000_000,  # -25% from ~$10B
                "available": True,
                "capital_loss_pct": 0.0,   # Aave survived, no bad debt from UST
            },
            "compound_v3": {
                "apy_pct": 6.0,
                "tvl_usd": 2_400_000_000,  # -20%
                "available": True,
                "capital_loss_pct": 0.0,
            },
            "yearn_v3": {
                # Several vaults had UST/Anchor exposure; significant impairment
                "apy_pct": 0.8,            # ~-80% vs normal yield
                "tvl_usd": 300_000_000,    # -70%
                "available": True,
                "capital_loss_pct": 0.25,  # 25% capital loss from UST strategy impairment
            },
            "euler_v2": {
                # Euler existed; limited but some LUNA contagion
                "apy_pct": 3.0,
                "tvl_usd": 100_000_000,
                "available": True,
                "capital_loss_pct": 0.05,  # Small contagion hit
            },
            "maple": {
                # Babel Finance ($150M) and Celsius exposure → massive defaults
                # Multiple pools suffered 50–100% loss on deployed capital
                "apy_pct": 0.0,
                "tvl_usd": 15_000_000,     # -85%
                "available": False,        # Exclude from allocation (default risk)
                "capital_loss_pct": 0.60,  # 60% loss on any Maple allocation
            },
            "sky_susds": {
                # DAI maintained peg; DSR not directly exposed
                "apy_pct": 2.0,
                "tvl_usd": 6_000_000_000,
                "available": True,
                "capital_loss_pct": 0.0,
            },
            "morpho_blue": {
                # Not launched at scale
                "apy_pct": 0.0,
                "tvl_usd": 0,
                "available": False,
                "capital_loss_pct": 0.0,
            },
        },
        # USDC held peg (UST was the failed stablecoin, not USDC)
        usdc_peg=1.0,
        notes=(
            "USDC held peg. stETH temporary depeg to 0.94 (not modeled). "
            "Maple: 60% capital loss (Babel/Celsius defaults). "
            "Yearn: 25% impairment from UST strategy exposure. "
            "Expected Sharpe ~-1.2 (significant loss scenario)."
        ),
    ),

    # ── USDC-DEPEG-2023 ───────────────────────────────────────────────────────
    "usdc_depeg_2023": StressScenario(
        name="USDC-DEPEG-2023",
        description="March 2023 Silicon Valley Bank run. "
                    "Circle disclosed $3.3B SVB exposure; USDC hit $0.87 on 11 March.",
        duration_days=7,
        start_date="2023-03-10",
        protocol_impacts={
            "aave_v3": {
                # Panic triggered massive borrow demand → high supply APY
                "apy_pct": 25.0,
                "tvl_usd": 5_100_000_000,  # -15% (just above TVL floor)
                "available": True,
                "capital_loss_pct": 0.0,   # No Aave-specific default
            },
            "compound_v3": {
                "apy_pct": 20.0,
                "tvl_usd": 1_800_000_000,  # -10%
                "available": True,
                "capital_loss_pct": 0.0,
            },
            "yearn_v3": {
                # USDC-based strategies temporarily repriced / paused
                "apy_pct": 1.5,
                "tvl_usd": 400_000_000,
                "available": True,
                "capital_loss_pct": 0.0,
            },
            "euler_v2": {
                # Euler was exploited on 13 March 2023 (same week!)
                "apy_pct": 0.0,
                "tvl_usd": 0,
                "available": False,        # Hack risk
                "capital_loss_pct": 0.0,   # We're excluded so no loss
            },
            "maple": {
                "apy_pct": 4.0,
                "tvl_usd": 50_000_000,
                "available": True,
                "capital_loss_pct": 0.0,
            },
            "sky_susds": {
                # sDAI partially a safe haven (DAI had brief instability)
                "apy_pct": 3.5,
                "tvl_usd": 5_000_000_000,
                "available": True,
                "capital_loss_pct": 0.0,
            },
            "morpho_blue": {
                # Not yet launched at scale in March 2023
                "apy_pct": 0.0,
                "tvl_usd": 0,
                "available": False,
                "capital_loss_pct": 0.0,
            },
        },
        # USDC hit $0.87 on 11 March (worst point); recovered to ~$1 by 13 March
        usdc_peg=0.87,
        notes=(
            "USDC depeg 0.87 (day 2 of scenario). Recovery in 3 days. "
            "Euler excluded (hack same week). "
            "APY signals boosted during panic — but denominated in depegged USDC. "
            "Expected Sharpe ~-0.5."
        ),
    ),
}


# ─── Allocation Helpers ─────────────────────────────────────────────────────


def _default_realistic_allocation() -> Dict[str, float]:
    """Realistic pre-crisis portfolio allocation for stress testing.

    Represents a diversified DeFi portfolio that a yield optimizer would
    hold before a crisis event — includes T2 protocols to capture realistic
    exposure to protocol failures.

    Layout (sums to 0.95; 5% implicit cash buffer):
      Aave V3    (T1) : 30%
      Compound V3(T1) : 20%
      Yearn V3   (T2) : 20%
      Maple      (T2) : 15%
      Sky/sUSDS  (T2) : 10%
    """
    return {
        "aave_v3":     0.30,
        "compound_v3": 0.20,
        "yearn_v3":    0.20,
        "maple":       0.15,
        "sky_susds":   0.10,
    }


def _effective_allocation(
    requested: Dict[str, float],
    scenario: StressScenario,
) -> Dict[str, float]:
    """Return the allocation actually deployable given scenario constraints.

    Rules applied (mirrors RiskPolicy v1.0):
      1. Protocol not available in scenario → weight = 0
      2. Protocol TVL < $5M floor → weight = 0
      3. Per-T1 cap ≤ 40%; per-T2 cap ≤ 20%
      4. T2 total cap ≤ 35%
      5. Cash buffer floor 5% (total deployed ≤ 95%)

    Note: zeroed weights are NOT redistributed to surviving protocols —
    the cash buffer simply increases. This models realistic behavior where
    a manager cannot instantly redeploy capital during a crisis.
    """
    effective: Dict[str, float] = {}

    # Step 1: filter unavailable / below TVL floor
    for proto, weight in requested.items():
        impact = scenario.protocol_impacts.get(proto, {})
        available = impact.get("available", True)
        tvl = impact.get("tvl_usd", _TVL_FLOOR_USD)
        if not available or tvl < _TVL_FLOOR_USD:
            effective[proto] = 0.0
        else:
            effective[proto] = float(weight)

    # Step 2: Apply per-protocol caps
    for proto in effective:
        tier = _PROTOCOL_TIERS.get(proto, "T2")
        cap = 0.40 if tier == "T1" else 0.20
        effective[proto] = min(effective[proto], cap)

    # Step 3: Apply T2 total cap (35%)
    t2_total = sum(w for p, w in effective.items() if _PROTOCOL_TIERS.get(p, "T2") == "T2")
    if t2_total > 0.35:
        scale = 0.35 / t2_total
        for p in list(effective.keys()):
            if _PROTOCOL_TIERS.get(p, "T2") == "T2":
                effective[p] *= scale

    # Step 4: Enforce cash buffer floor (total deployed ≤ 95%)
    total_w = sum(effective.values())
    if total_w > 0.95:
        scale = 0.95 / total_w
        for p in effective:
            effective[p] *= scale

    return effective


# ─── Sharpe (inline, no import from analytics) ──────────────────────────────


def _sharpe(daily_returns: List[float], risk_free_rate: float = 0.05) -> float:
    """Annualised Sharpe from daily fractional returns. Same formula as analytics/sharpe.py."""
    n = len(daily_returns)
    if n < 2:
        return 0.0
    rf_daily = risk_free_rate / 365.0
    excess = [r - rf_daily for r in daily_returns]
    mean = sum(excess) / n
    variance = sum((x - mean) ** 2 for x in excess) / (n - 1)
    std = math.sqrt(variance)
    if std <= 1e-12 or not math.isfinite(std):
        return 0.0
    return mean / std * math.sqrt(365.0)


# ─── USDC Depeg Curve ───────────────────────────────────────────────────────


def _usdc_peg_on_day(scenario: StressScenario, day_index: int) -> float:
    """USDC effective value (1.0 = par) on a given simulation day.

    Depeg curve model:
      day 0: peg starts slipping → (1.0 + worst) / 2
      day 1: worst point (scenario.usdc_peg)
      day 2: halfway recovery → (1.0 + worst) / 2
      day 3+: full recovery → 1.0

    No effect when usdc_peg == 1.0.
    """
    worst = scenario.usdc_peg
    if worst >= 1.0:
        return 1.0
    if day_index == 0:
        return (1.0 + worst) / 2.0
    if day_index == 1:
        return worst
    if day_index == 2:
        return (1.0 + worst) / 2.0
    return 1.0


# ─── Core Simulation ────────────────────────────────────────────────────────


def run_stress_test(
    scenario_id: str,
    initial_equity: float = 100_000.0,
    initial_allocation: Optional[Dict[str, float]] = None,
    risk_policy=None,  # optional — kept for forward-compatibility; kill switch is hard-coded
) -> StressResult:
    """Simulate portfolio performance under a historical DeFi stress scenario.

    Simulation loop (per day):
      1. Day 0 only: apply one-time capital losses (``capital_loss_pct`` per protocol)
      2. Day 0 only: apply USDC peg mark-to-market drop (if scenario.usdc_peg < 1.0)
      3. Day 2 partial recovery / day 3 full USDC recovery
      4. Compute daily yield for each deployed protocol: equity * weight * apy / 365
      5. Accumulate equity; compute drawdown from running peak
      6. Kill-switch check: drawdown ≥ 5% → close all positions; no further yield
      7. Record daily equity point

    Args:
        scenario_id:        Key in SCENARIOS dict.
        initial_equity:     Starting portfolio value (USD).
        initial_allocation: {protocol_id: weight}. None → realistic diversified default.
        risk_policy:        Unused (kill switch is deterministic at 5% per policy v1.0).

    Returns:
        StressResult with full daily equity series and summary metrics.
    """
    if scenario_id not in SCENARIOS:
        raise ValueError(
            f"Unknown scenario '{scenario_id}'. Available: {list(SCENARIOS.keys())}"
        )

    scenario = SCENARIOS[scenario_id]
    initial_equity = float(initial_equity)

    if initial_allocation is None:
        initial_allocation = _default_realistic_allocation()

    # Resolve effective weights under scenario constraints
    alloc = _effective_allocation(initial_allocation, scenario)

    equity = initial_equity
    peak_equity = equity
    max_dd = 0.0
    kill_switch_triggered = False
    kill_switch_day: Optional[int] = None
    positions_open = True  # becomes False after kill switch

    daily_equity: List[dict] = []
    daily_returns: List[float] = []

    # Track per-day USDC peg state for recovery math
    prev_peg = _usdc_peg_on_day(scenario, -1) if scenario.usdc_peg < 1.0 else 1.0

    for day in range(scenario.duration_days):
        day_start_equity = equity

        # ── Day 0: one-time capital losses from protocol failures ──────────
        if day == 0 and positions_open:
            for proto, weight in alloc.items():
                if weight <= 0:
                    continue
                impact = scenario.protocol_impacts.get(proto, {})
                loss_pct = float(impact.get("capital_loss_pct", 0.0))
                if loss_pct > 0:
                    position_value = equity * weight
                    loss_usd = position_value * loss_pct
                    equity -= loss_usd

        # ── USDC depeg mark-to-market ──────────────────────────────────────
        if scenario.usdc_peg < 1.0 and positions_open:
            current_peg = _usdc_peg_on_day(scenario, day)
            if prev_peg > 0 and current_peg != prev_peg:
                # Scale equity by peg ratio change
                equity = equity * (current_peg / prev_peg)
            prev_peg = current_peg

        # ── Daily yield from deployed capital ─────────────────────────────
        if positions_open:
            for proto, weight in alloc.items():
                if weight <= 0:
                    continue
                impact = scenario.protocol_impacts.get(proto, {})
                apy_pct = float(impact.get("apy_pct", 0.0))
                if apy_pct <= 0:
                    continue
                position_value = equity * weight
                daily_yield = position_value * (apy_pct / 100.0) / 365.0
                equity += daily_yield

        # ── Drawdown & kill-switch check ───────────────────────────────────
        if equity > peak_equity:
            peak_equity = equity

        dd = (peak_equity - equity) / peak_equity if peak_equity > 0 else 0.0
        if dd > max_dd:
            max_dd = dd

        if not kill_switch_triggered and dd >= _KILL_SWITCH_DD:
            kill_switch_triggered = True
            kill_switch_day = day
            positions_open = False  # close all; equity is flat for remaining days

        # ── Record ─────────────────────────────────────────────────────────
        daily_ret = (equity - day_start_equity) / day_start_equity if day_start_equity > 0 else 0.0
        daily_returns.append(daily_ret)
        daily_equity.append({
            "day": day,
            "equity": round(equity, 4),
            "daily_return_pct": round(daily_ret * 100, 6),
        })

    total_return_pct = (equity - initial_equity) / initial_equity * 100.0
    sharpe = _sharpe(daily_returns)

    return StressResult(
        scenario_name=scenario.name,
        initial_equity=initial_equity,
        final_equity=round(equity, 4),
        total_return_pct=round(total_return_pct, 4),
        max_drawdown_pct=round(max_dd * 100, 4),
        sharpe_ratio=round(sharpe, 4),
        daily_equity=daily_equity,
        protocol_allocation_used={p: round(w, 6) for p, w in alloc.items()},
        kill_switch_triggered=kill_switch_triggered,
        kill_switch_day=kill_switch_day,
        notes=scenario.notes,
    )


# ─── Batch Runner ───────────────────────────────────────────────────────────


def run_all_scenarios(
    initial_equity: float = 100_000.0,
    initial_allocation: Optional[Dict[str, float]] = None,
) -> Dict[str, StressResult]:
    """Run all three scenarios and return {scenario_id: StressResult}."""
    return {
        sid: run_stress_test(sid, initial_equity, initial_allocation)
        for sid in SCENARIOS
    }


# ─── Report Generator ───────────────────────────────────────────────────────


def generate_stress_report(results: Dict[str, StressResult]) -> str:
    """Generate a human-readable summary of stress test results.

    Format::

        === SPA Stress Test Report ===
        COVID-2020         :  +2.45% over 30d | max DD  1.47% | Sharpe +2.68 | kill switch: NO
        LUNA-2022          : -12.31% over 30d | max DD 14.52% | Sharpe -9.17 | kill switch: YES (day 0)
        USDC-DEPEG-2023    :  -6.45% over  7d | max DD  6.45% | Sharpe -7.20 | kill switch: YES (day 0)

        Worst scenario    : LUNA-2022 (-12.31%)
        Portfolio survived 1/3 scenarios without kill switch.
    """
    if not results:
        return "=== SPA Stress Test Report ===\nNo results.\n"

    lines = ["=== SPA Stress Test Report ==="]

    # Canonical display order
    scenario_order = ["covid_2020", "luna_2022", "usdc_depeg_2023"]
    ordered = [
        (sid, results[sid])
        for sid in scenario_order
        if sid in results
    ]
    # Append any extras not in the canonical order
    seen = {s for s, _ in ordered}
    for sid, r in results.items():
        if sid not in seen:
            ordered.append((sid, r))

    survived_count = 0
    worst_id: Optional[str] = None
    worst_ret: float = float("inf")

    for sid, r in ordered:
        duration = SCENARIOS[sid].duration_days if sid in SCENARIOS else "?"
        ks_str = f"YES (day {r.kill_switch_day})" if r.kill_switch_triggered else "NO"
        # Format return with explicit sign, no double-sign
        ret_str = f"{r.total_return_pct:+.2f}%"
        line = (
            f"{r.scenario_name:<18}: {ret_str:>8} over {duration:>2}d"
            f" | max DD {r.max_drawdown_pct:6.2f}%"
            f" | Sharpe {r.sharpe_ratio:+.2f}"
            f" | kill switch: {ks_str}"
        )
        lines.append(line)

        if not r.kill_switch_triggered:
            survived_count += 1
        if r.total_return_pct < worst_ret:
            worst_ret = r.total_return_pct
            worst_id = sid

    lines.append("")
    if worst_id and worst_id in SCENARIOS:
        worst_name = SCENARIOS[worst_id].name
        lines.append(f"Worst scenario    : {worst_name} ({worst_ret:+.2f}%)")
    lines.append(
        f"Portfolio survived {survived_count}/{len(ordered)} scenarios without kill switch."
    )

    return "\n".join(lines) + "\n"
