"""
spa_core/strategies/s21_aave_loop.py — MP-1511 S21_LOOP Aave V3 Loop Strategy

Strategy S21_LOOP — Aave V3 Recursive USDC Loop.
==================================================
Implements recursive USDC deposit → borrow → re-deposit looping on Aave V3
to amplify yield through borrowing rate arbitrage on stablecoins.

Target APY: 6–9% via borrowing rate arbitrage.
Risk: liquidation exposure if collateral factor changes (stablecoins only, low risk).
Tier: T2 (Aave V3 = T1 adapter, but loop leverage makes this T2 risk profile).
Chain: Ethereum mainnet (Aave V3 USDC market).

Loop mechanics:
  - Deposit D0 USDC as collateral
  - Borrow B = D0 × LTV × LOOP_FACTOR USDC
  - Re-deposit B to compound yield
  - Effective APY = (supply_apy × effective_deposit) - (borrow_apy × total_debt)
  - Max loops capped at MAX_LOOPS to stay within safe health factor

Safety gates:
  - HEALTH_FACTOR_MIN = 1.35 (auto-exit if HF drops below)
  - LTV = 0.80 (conservative; Aave V3 eMode USDC LTV = 0.93, using 0.80)
  - LOOP_FACTOR_MAX = 3.0x effective exposure cap (borrow < 2× original)
  - Stablecoins only (USDC collateral, USDC borrow) — no liquidation gap risk

Constraints:
  - T2 tier: per-protocol cap 20%, part of T2 total cap 50% (ADR-019)
  - APY bounds: 1%–30% (RiskPolicy v1.0)
  - No live execution adapter — paper trading only until go-live
  - LLM FORBIDDEN in this module
  - Stdlib only, no external dependencies
  - Atomic writes: tmp + os.replace

ADR: ADR-019 (T2 total cap 50%), ADR-023 (promotion policy)
Date: 2026-06-20 (MP-1511, Sprint v11.27)
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Tuple

# ─── Module-level constants ────────────────────────────────────────────────────

STRATEGY_ID: str = "S21_LOOP"
STRATEGY_NAME: str = "Aave V3 USDC Recursive Loop"
DESCRIPTION: str = "Aave V3 recursive USDC deposit→borrow loop for rate arbitrage"
TARGET_APY_PCT: float = 7.5     # midpoint of 6–9% band (%)
TIER: str = "T2"
CHAIN: str = "ethereum"
RISK_TIER: str = "T2"

# Target APY range for registry
TARGET_APY_MIN: float = 6.0
TARGET_APY_MAX: float = 9.0
MAX_DRAWDOWN_PCT: float = 4.0  # stablecoin-only: lower DD than volatile strategies

# Loop parameters
LTV: float = 0.80               # conservative LTV (Aave V3 USDC ~0.90 eMode, 0.80 safe)
MAX_LOOPS: int = 2              # maximum recursion depth (3 loops → HF~1.28 < 1.35 floor; 2 loops → HF~1.44)
LOOP_FACTOR_MAX: float = 3.0   # max effective exposure multiplier
HEALTH_FACTOR_MIN: float = 1.35  # auto-exit threshold (Aave V3: liquidation at 1.0)

# Cash buffer: always maintain to cover exit slippage
CASH_BUFFER: float = 0.15      # 15% of portfolio always in cash

# APY bounds (RiskPolicy v1.0 — fraction)
APY_MIN: float = 0.01   # 1%
APY_MAX: float = 0.30   # 30%

# Backtest baseline stats (synthetic — no real PIT data yet)
_BACKTEST_STATS: dict = {
    "sharpe": 1.2,
    "max_dd": -0.02,
    "annual_return": 0.075,
    "win_rate": 0.78,
    "calmar": 3.75,
    "note": "Synthetic baseline; stablecoin loop — low DD, lower volatility.",
}


# ─── Loop math helpers ────────────────────────────────────────────────────────

def _compute_effective_multiplier(ltv: float, n_loops: int) -> float:
    """
    Computes effective deposit multiplier for n recursion loops.

    Formula: sum_{k=0}^{n} LTV^k = (1 - LTV^{n+1}) / (1 - LTV)

    Args:
        ltv:     Loan-to-value ratio (0 < ltv < 1).
        n_loops: Number of loop iterations (≥ 0).

    Returns:
        Effective deposit multiplier (≥ 1.0).
    """
    if ltv <= 0 or ltv >= 1:
        return 1.0
    # Geometric series sum
    return (1.0 - ltv ** (n_loops + 1)) / (1.0 - ltv)


def _compute_effective_apy(
    supply_apy: float,
    borrow_apy: float,
    ltv: float,
    n_loops: int,
) -> float:
    """
    Computes effective portfolio APY for the loop strategy.

    Net APY = supply_apy × D_eff - borrow_apy × B_eff
    where:
        D_eff = effective deposit multiplier (geometric series)
        B_eff = total debt multiplier = D_eff - 1 (since B = D - 1 per $1 initial)

    Args:
        supply_apy: Aave V3 supply APY for USDC (fraction, e.g. 0.05 = 5%).
        borrow_apy: Aave V3 borrow APY for USDC (fraction).
        ltv:        LTV ratio.
        n_loops:    Number of recursion loops.

    Returns:
        Net APY as fraction. Can be negative if borrow_apy > supply_apy.
    """
    d_eff = _compute_effective_multiplier(ltv, n_loops)
    b_eff = d_eff - 1.0  # total debt as multiplier of initial deposit
    return supply_apy * d_eff - borrow_apy * b_eff


def _compute_health_factor(
    deposit_value: float,
    debt_value: float,
    liquidation_threshold: float = 0.85,
) -> float:
    """
    Estimates Aave V3 health factor.

    HF = (deposit_value × liquidation_threshold) / debt_value

    Args:
        deposit_value:         Total effective collateral USD.
        debt_value:            Total outstanding debt USD.
        liquidation_threshold: Aave V3 USDC liquidation threshold (default 0.85).

    Returns:
        Health factor float (∞ if no debt).
    """
    if debt_value <= 0:
        return float("inf")
    return (deposit_value * liquidation_threshold) / debt_value


# ─── S21AaveLoop ──────────────────────────────────────────────────────────────

class S21AaveLoop:
    """
    S21_LOOP — Aave V3 USDC Recursive Loop Strategy.

    Public API:
        compute_loop_apy(supply_apy, borrow_apy, n_loops)  → float (% APY)
        optimal_loops(supply_apy, borrow_apy)              → int
        get_allocation(portfolio_value, apy_data)          → {slot: usd_amount}
        health_factor_estimate(capital, n_loops)           → float
        risk_check(apy_data)                               → (ok, reason)
        backtest_stats()                                   → dict
        to_dict(portfolio_value, apy_data)                 → snapshot dict
    """

    STRATEGY_ID = STRATEGY_ID
    STRATEGY_NAME = STRATEGY_NAME
    DESCRIPTION = DESCRIPTION
    TARGET_APY_PCT = TARGET_APY_PCT
    TIER = TIER
    CHAIN = CHAIN
    LTV = LTV
    MAX_LOOPS = MAX_LOOPS
    HEALTH_FACTOR_MIN = HEALTH_FACTOR_MIN

    # ── APY from loop ──────────────────────────────────────────────────────────

    def compute_loop_apy(
        self,
        supply_apy: float,
        borrow_apy: float,
        n_loops: Optional[int] = None,
    ) -> float:
        """
        Computes effective loop APY in percent.

        Args:
            supply_apy: USDC supply APY (fraction).
            borrow_apy: USDC borrow APY (fraction).
            n_loops:    Number of loops; defaults to MAX_LOOPS.

        Returns:
            Net APY in percent (may be negative if borrow > supply).
        """
        loops = n_loops if n_loops is not None else MAX_LOOPS
        loops = min(max(0, loops), MAX_LOOPS)
        net = _compute_effective_apy(supply_apy, borrow_apy, LTV, loops)
        return round(net * 100.0, 4)

    def optimal_loops(self, supply_apy: float, borrow_apy: float) -> int:
        """
        Finds optimal number of loops maximising net APY.

        Tries 0..MAX_LOOPS and returns the loop count with highest net APY.
        Returns 0 if borrowing always reduces APY.

        Args:
            supply_apy: USDC supply APY (fraction).
            borrow_apy: USDC borrow APY (fraction).

        Returns:
            Optimal loop count (0..MAX_LOOPS).
        """
        best_loops = 0
        best_apy = supply_apy  # baseline: 0 loops = just supply APY

        for n in range(1, MAX_LOOPS + 1):
            net = _compute_effective_apy(supply_apy, borrow_apy, LTV, n)
            if net > best_apy:
                best_apy = net
                best_loops = n

        return best_loops

    def get_allocation(
        self,
        portfolio_value: float,
        apy_data: dict,
    ) -> dict:
        """
        Returns USD allocation: looped USDC position + cash buffer.

        Args:
            portfolio_value: Total portfolio USD value.
            apy_data:        Live APY dict with keys:
                               "aave_v3_usdc_supply" → supply APY (fraction)
                               "aave_v3_usdc_borrow" → borrow APY (fraction)

        Returns:
            {"aave_v3_usdc_loop": float, "cash": float}
            Or {"cash": float} if risk_check fails.
        """
        safe_val = max(0.0, portfolio_value)
        ok, _ = self.risk_check(apy_data)

        if not ok:
            return {"cash": safe_val}

        deployed = safe_val * (1.0 - CASH_BUFFER)
        return {
            "aave_v3_usdc_loop": deployed,
            "cash": safe_val * CASH_BUFFER,
        }

    def health_factor_estimate(
        self,
        capital: float,
        n_loops: Optional[int] = None,
    ) -> float:
        """
        Estimates health factor for a given capital and loop count.

        Uses conservative stablecoin liquidation threshold of 0.85.

        Args:
            capital:  Initial deposit in USD.
            n_loops:  Number of loops; defaults to MAX_LOOPS.

        Returns:
            Estimated health factor (float; ∞ if no loops).
        """
        loops = n_loops if n_loops is not None else MAX_LOOPS
        loops = min(max(0, loops), MAX_LOOPS)

        if loops == 0 or capital <= 0:
            return float("inf")

        d_eff = _compute_effective_multiplier(LTV, loops)
        b_eff = d_eff - 1.0
        total_deposit = capital * d_eff
        total_debt = capital * b_eff
        return _compute_health_factor(total_deposit, total_debt)

    def risk_check(self, apy_data: dict) -> Tuple[bool, str]:
        """
        Pre-flight risk check before allocation.

        Validates:
          - supply APY key present and in bounds
          - borrow APY key present
          - net APY (with MAX_LOOPS) is positive
          - estimated health factor ≥ HEALTH_FACTOR_MIN

        Args:
            apy_data: Live APY dict.

        Returns:
            (ok: bool, reason: str)
        """
        supply = apy_data.get("aave_v3_usdc_supply")
        borrow = apy_data.get("aave_v3_usdc_borrow")

        if supply is None:
            return False, "Missing aave_v3_usdc_supply in apy_data"
        if borrow is None:
            return False, "Missing aave_v3_usdc_borrow in apy_data"

        try:
            s = float(supply)
            b = float(borrow)
        except (TypeError, ValueError):
            return False, "Non-numeric APY values in apy_data"

        if not (APY_MIN <= s <= APY_MAX):
            return False, f"supply APY {s*100:.2f}% out of bounds [{APY_MIN*100:.0f}%, {APY_MAX*100:.0f}%]"
        if b < 0:
            return False, f"Negative borrow APY: {b}"

        # Net APY must be positive with optimal loops
        optimal = self.optimal_loops(s, b)
        net_apy = self.compute_loop_apy(s, b, optimal)
        if net_apy <= 0:
            return False, f"Loop APY non-positive: {net_apy:.2f}% — borrow cost exceeds supply yield"

        # Health factor check
        hf = self.health_factor_estimate(1.0, MAX_LOOPS)
        if hf < HEALTH_FACTOR_MIN:
            return False, f"Health factor {hf:.2f} below minimum {HEALTH_FACTOR_MIN}"

        return True, "ok"

    def backtest_stats(self) -> dict:
        """
        Returns synthetic backtest stats for S21_LOOP.

        Replace with real PIT data before go-live promotion.

        Returns:
            dict with: sharpe, max_dd, annual_return, win_rate, calmar, note.
        """
        return dict(_BACKTEST_STATS)

    def to_dict(
        self,
        portfolio_value: float = 0.0,
        apy_data: Optional[dict] = None,
    ) -> dict:
        """Full strategy snapshot for dashboard and reports."""
        apy_data = apy_data or {}
        ok, reason = self.risk_check(apy_data)
        allocation = self.get_allocation(portfolio_value, apy_data)

        supply = float(apy_data.get("aave_v3_usdc_supply", 0.0) or 0.0)
        borrow = float(apy_data.get("aave_v3_usdc_borrow", 0.0) or 0.0)
        opt_loops = self.optimal_loops(supply, borrow) if ok else 0
        net_apy = self.compute_loop_apy(supply, borrow, opt_loops)
        hf = self.health_factor_estimate(portfolio_value * (1 - CASH_BUFFER), opt_loops)

        return {
            "strategy_id": STRATEGY_ID,
            "strategy_name": STRATEGY_NAME,
            "description": DESCRIPTION,
            "tier": TIER,
            "chain": CHAIN,
            "target_apy_range_pct": [TARGET_APY_MIN, TARGET_APY_MAX],
            "loop_params": {
                "ltv": LTV,
                "max_loops": MAX_LOOPS,
                "optimal_loops": opt_loops,
                "cash_buffer": CASH_BUFFER,
            },
            "live_apy": {
                "supply_apy_pct": round(supply * 100, 4),
                "borrow_apy_pct": round(borrow * 100, 4),
                "net_loop_apy_pct": net_apy,
            },
            "health_factor_estimate": round(hf, 4) if hf != float("inf") else None,
            "allocation": allocation,
            "backtest_stats": self.backtest_stats(),
            "risk_check": {"ok": ok, "reason": reason},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


# ─── Auto-registration ────────────────────────────────────────────────────────

def _register() -> None:
    """Register S21_LOOP in the global REGISTRY. Failure does not block import."""
    try:
        from spa_core.strategies.strategy_registry import REGISTRY, StrategyMeta  # type: ignore
        REGISTRY.register(StrategyMeta(
            id=STRATEGY_ID,
            name=STRATEGY_NAME,
            type="yield_loop",
            risk_tier=RISK_TIER,
            target_apy_min=TARGET_APY_MIN,
            target_apy_max=TARGET_APY_MAX,
            max_drawdown_pct=MAX_DRAWDOWN_PCT,
            description=(
                "S21_LOOP Aave V3 recursive USDC loop: deposit→borrow→re-deposit "
                f"(LTV={LTV}, max {MAX_LOOPS} loops). Effective APY 6–9% via borrowing rate "
                "arbitrage on stablecoins. 15% cash buffer. HF≥1.35 gate."
            ),
            module="spa_core.strategies.s21_aave_loop",
            handler_class="S21AaveLoop",
            tags=["aave", "aave_v3", "loop", "usdc", "stablecoin", "borrow",
                  "yield_loop", "t2", "s21_loop"],
        ))
    except Exception as exc:  # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning(
            "S21AaveLoop auto-registration failed: %s", exc
        )


_register()
