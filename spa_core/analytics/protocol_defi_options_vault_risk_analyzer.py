"""
ProtocolDeFiOptionsVaultRiskAnalyzer
MP-1083: DeFi options vault risk and breakeven analysis.

Read-only advisory module. No trades. Pure stdlib. Atomic writes.
Ring-buffer log capped at 100 entries (data/options_vault_risk_log.json).
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


class ProtocolDeFiOptionsVaultRiskAnalyzer:
    """
    Analyzes DeFi options vault strategies (covered calls, cash-secured puts,
    strangles) for breakeven, premium yield, risk-reward, and tail risk.

    Inputs (dict keys):
        vault_name              - human-readable vault identifier
        strategy                - "covered_call" | "cash_secured_put" | "strangle"
                                  (or any custom string)
        underlying_asset        - e.g. "ETH", "BTC"
        strike_price_usd        - option strike price (USD)
        current_price_usd       - current market price of underlying (USD)
        premium_apy_pct         - annualized premium yield from writing options (%)
        expiry_days             - days until option expiry
        implied_volatility_pct  - implied volatility of the options (%)
        delta                   - option delta (-1 to 1; negative for puts)
        historical_win_rate_pct - % of past expiries that expired OTM (profitable)
        max_loss_scenario_pct   - estimated maximum loss as % of vault assets

    Outputs (dict keys):
        breakeven_price_usd     - price at which premium offsets loss
        annualized_premium_pct  - APY-equivalent premium yield (%)
        risk_reward_ratio       - period premium / max_loss (reward per unit risk)
        tail_risk_score         - 0-100 composite tail risk (higher = riskier)
        vault_label             - CONSERVATIVE_VAULT / BALANCED_RISK /
                                  ELEVATED_RISK / HIGH_TAIL_RISK / AVOID_VAULT

    Read-only / advisory. Never modifies allocator, risk, or execution.
    """

    LOG_PATH: str = "data/options_vault_risk_log.json"
    MAX_LOG_ENTRIES: int = 100

    # Known high-risk strategies for labeling nudge
    HIGH_RISK_STRATEGIES = {"strangle", "naked_call", "naked_put"}

    def __init__(self, log_path: str = None) -> None:
        self.log_path = log_path if log_path is not None else self.LOG_PATH

    # ------------------------------------------------------------------
    # Primary API
    # ------------------------------------------------------------------

    def analyze(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze an options vault and return risk metrics.

        Parameters
        ----------
        data : dict
            See class docstring for required keys.

        Returns
        -------
        dict with keys: vault_name, strategy, underlying_asset,
            breakeven_price_usd, annualized_premium_pct, risk_reward_ratio,
            tail_risk_score, vault_label
        """
        # --- input parsing ---------------------------------------------------
        vault_name = str(data.get("vault_name", ""))
        strategy = str(data.get("strategy", "covered_call")).lower()
        underlying_asset = str(data.get("underlying_asset", ""))
        strike_price_usd = float(data.get("strike_price_usd", 0.0))
        current_price_usd = float(data.get("current_price_usd", 0.0))
        premium_apy_pct = float(data.get("premium_apy_pct", 0.0))
        expiry_days = float(data.get("expiry_days", 30.0))
        implied_volatility_pct = float(data.get("implied_volatility_pct", 0.0))
        delta = float(data.get("delta", 0.0))
        historical_win_rate_pct = float(data.get("historical_win_rate_pct", 50.0))
        max_loss_scenario_pct = float(data.get("max_loss_scenario_pct", 0.0))

        # --- period premium --------------------------------------------------
        # How much premium is earned in this specific expiry period
        safe_expiry = max(expiry_days, 0.0)
        period_premium_pct = premium_apy_pct * (safe_expiry / 365.0)

        # --- breakeven price -------------------------------------------------
        breakeven_price_usd = self._compute_breakeven(
            strategy=strategy,
            strike_price_usd=strike_price_usd,
            current_price_usd=current_price_usd,
            period_premium_pct=period_premium_pct,
        )

        # --- annualized premium (convert period premium back to APY) ----------
        # Already provided as APY; preserve for output clarity
        annualized_premium_pct = round(premium_apy_pct, 4)

        # --- risk-reward ratio -----------------------------------------------
        risk_reward_ratio = self._compute_risk_reward(
            period_premium_pct=period_premium_pct,
            max_loss_scenario_pct=max_loss_scenario_pct,
        )

        # --- tail risk score (0-100) ------------------------------------------
        tail_risk_score = self._compute_tail_risk(
            implied_volatility_pct=implied_volatility_pct,
            historical_win_rate_pct=historical_win_rate_pct,
            max_loss_scenario_pct=max_loss_scenario_pct,
            delta=delta,
            strategy=strategy,
            period_premium_pct=period_premium_pct,
        )

        # --- label -----------------------------------------------------------
        vault_label = self._assign_label(tail_risk_score)

        return {
            "vault_name": vault_name,
            "strategy": strategy,
            "underlying_asset": underlying_asset,
            "breakeven_price_usd": breakeven_price_usd,
            "annualized_premium_pct": annualized_premium_pct,
            "risk_reward_ratio": risk_reward_ratio,
            "tail_risk_score": tail_risk_score,
            "vault_label": vault_label,
        }

    def analyze_and_log(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze vault and atomically append result to ring-buffer log."""
        result = self.analyze(data)
        self._append_log(result)
        return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _compute_breakeven(
        self,
        strategy: str,
        strike_price_usd: float,
        current_price_usd: float,
        period_premium_pct: float,
    ) -> float:
        """
        Compute breakeven price for the vault strategy.

        covered_call  → downside breakeven = current - premium_received
        cash_secured_put → put writer breakeven = strike - premium_received
        strangle      → lower breakeven = min(strike, current) - premium_received
        default       → uses strike as reference minus premium
        """
        if current_price_usd <= 0.0:
            return 0.0

        # Absolute premium received per unit of current price
        premium_abs = current_price_usd * (period_premium_pct / 100.0)

        if strategy == "covered_call":
            # Writer profits unless price falls below current - premium
            breakeven = current_price_usd - premium_abs
        elif strategy == "cash_secured_put":
            # Put writer profits unless price falls below strike - premium
            premium_abs_strike = strike_price_usd * (period_premium_pct / 100.0)
            breakeven = strike_price_usd - premium_abs_strike
        elif strategy == "strangle":
            # Short strangle: lower breakeven = lower strike - total premium
            lower = min(strike_price_usd, current_price_usd)
            breakeven = lower - premium_abs
        else:
            # Generic: strike minus period premium
            breakeven = strike_price_usd - premium_abs

        return round(max(0.0, breakeven), 4)

    @staticmethod
    def _compute_risk_reward(
        period_premium_pct: float,
        max_loss_scenario_pct: float,
    ) -> float:
        """
        Reward-to-risk ratio for the expiry period.
        ratio = period_premium / max_loss_scenario
        Capped at 10.0 to avoid infinite values when loss is tiny.
        """
        if max_loss_scenario_pct <= 0.0:
            return round(min(10.0, period_premium_pct * 10.0), 4)
        ratio = period_premium_pct / max_loss_scenario_pct
        return round(min(10.0, max(0.0, ratio)), 4)

    @staticmethod
    def _compute_tail_risk(
        implied_volatility_pct: float,
        historical_win_rate_pct: float,
        max_loss_scenario_pct: float,
        delta: float,
        strategy: str,
        period_premium_pct: float,
    ) -> float:
        """
        Composite tail risk score (0-100).  Higher = more tail risk.

        Components:
        1. IV component  (30%): high IV → higher tail risk
        2. Win-rate miss (25%): low win rate → higher tail risk
        3. Max loss      (30%): larger loss scenario → higher tail risk
        4. Delta         (15%): large |delta| → more directional exposure

        Strategy modifier: strangle / naked strategies add +10 pts (capped at 100).
        Premium cushion discount: substantial period premium reduces tail risk slightly.
        """
        # 1. IV contribution: normalized to 0-100, IV≥100% maps to 100
        iv_score = min(100.0, max(0.0, implied_volatility_pct))

        # 2. Win-rate contribution: low win rate = high risk
        win_miss_score = min(100.0, max(0.0, 100.0 - historical_win_rate_pct))

        # 3. Max loss contribution: 0-100% maps linearly
        loss_score = min(100.0, max(0.0, max_loss_scenario_pct))

        # 4. Delta contribution: |delta| 0→1 maps to 0→100
        delta_score = min(100.0, abs(delta) * 100.0)

        # Weighted sum
        raw = (
            0.30 * iv_score
            + 0.25 * win_miss_score
            + 0.30 * loss_score
            + 0.15 * delta_score
        )

        # Strategy modifier: complex / high-risk strategies add tail risk
        strategy_lower = strategy.lower()
        if strategy_lower in {"strangle", "naked_call", "naked_put"}:
            raw += 10.0
        elif strategy_lower == "iron_condor":
            raw -= 5.0  # defined-risk; slight discount

        # Premium cushion: if premium is large, the tail is softer
        # Discount up to 5 pts when period_premium_pct > 5%
        premium_discount = min(5.0, period_premium_pct * 0.5)
        raw -= premium_discount

        return round(max(0.0, min(100.0, raw)), 4)

    @staticmethod
    def _assign_label(score: float) -> str:
        """Map tail risk score to human-readable vault label."""
        if score <= 20.0:
            return "CONSERVATIVE_VAULT"
        if score <= 40.0:
            return "BALANCED_RISK"
        if score <= 60.0:
            return "ELEVATED_RISK"
        if score <= 80.0:
            return "HIGH_TAIL_RISK"
        return "AVOID_VAULT"

    def _append_log(self, entry: Dict[str, Any]) -> None:
        """Atomically append entry to JSON ring-buffer log (cap 100)."""
        log_path = Path(self.log_path)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        existing: list = []
        if log_path.exists():
            try:
                with open(log_path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                if isinstance(data, list):
                    existing = data
            except (json.JSONDecodeError, OSError):
                existing = []

        record = dict(entry)
        record["_logged_at"] = datetime.now(timezone.utc).isoformat()
        existing.append(record)

        if len(existing) > self.MAX_LOG_ENTRIES:
            existing = existing[-self.MAX_LOG_ENTRIES :]

        tmp_path = str(log_path) + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(existing, fh, indent=2)
        os.replace(tmp_path, str(log_path))
