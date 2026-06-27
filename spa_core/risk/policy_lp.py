"""
RiskPolicy-LP v1.0 — Engine C (LP/Liquidity/RS-004)
LLM_FORBIDDEN: нет AI вызовов. Детерминированные правила.
Fail-closed: нет данных → approved=False.
Единственный источник правды для лимитов слоя C.

Governance:
  - Изменение лимитов → новый ADR + snapshot в spa_core/risk/versions/
  - approved=False не может быть переопределён никаким агентом
  - Версия остаётся lp_v1.0 весь период до отдельного ADR

LLM_FORBIDDEN_AGENTS = {risk, execution, monitoring}
"""
# LLM_FORBIDDEN
from dataclasses import dataclass
from typing import Optional
from pathlib import Path
import math

_PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Версия политики — меняется только через ADR
LP_POLICY_VERSION = "lp_v1.0"


@dataclass(frozen=True)
class LPRiskLimits:
    """
    Жёсткие лимиты Engine C (LP/Liquidity).
    Единственный источник правды — импортировать отсюда, не дублировать.

    LLM_FORBIDDEN: значения заданы детерминированно, без AI.
    """
    # Per-pool allocation cap (% от слоя C)
    per_pool_cap: float = 0.20           # ≤20% слоя

    # Minimum TVL пула (USD)
    min_pool_tvl_usd: float = 50_000_000.0   # $50M

    # Min audits протокола
    min_audits: int = 2

    # IL drawdown kill (от equity слоя C)
    il_drawdown_kill_pct: float = 0.12   # −12% IL drawdown → kill

    # Cash buffer minimum (% от слоя C)
    cash_buffer_min: float = 0.15        # ≥15%

    # Sleeve cap (% от total portfolio)
    sleeve_cap_total: float = 0.25       # ≤25% портфеля

    # Maximum price range width (для CLMM, % от текущей цены)
    max_range_width_pct: float = 1.0     # 100% от текущей цены (±50%)

    # Min fee tier APY (24h EMA)
    min_fee_apy_24h: float = 0.03        # ≥3% APY от fees

    # Max 7d fee volatility (Coefficient of Variation)
    max_fee_volatility_7d: float = 0.30  # ≤30% CV

    # Delta neutral requirement
    require_delta_neutral: bool = True   # обязательно симметричный диапазон

    # Min liquidity depth (depth in USD)
    min_liquidity_depth_usd: float = 1_000_000.0  # $1M depth


# Singleton: единственный экземпляр для импорта
LP_LIMITS = LPRiskLimits()


def evaluate_lp_position(
    *,
    pool_name: str,
    protocol: str,
    fee_apy_24h: Optional[float],
    pool_tvl_usd: Optional[float],
    il_current_pct: Optional[float],
    audit_count: Optional[int],
    range_width_pct: Optional[float] = None,
    fee_volatility_7d: Optional[float] = None,
    liquidity_depth_usd: Optional[float] = None,
    sleeve_allocation_pct: Optional[float] = None,
    current_drawdown_pct: float = 0.0,
    is_delta_neutral: Optional[bool] = None,
    limits: LPRiskLimits = LP_LIMITS,
) -> dict:
    """
    Гейт Engine C LP позиции (fail-closed).

    Все критические параметры (fee_apy_24h, pool_tvl_usd, il_current_pct,
    audit_count) обязательны. Любой None → approved=False немедленно.

    Returns:
        {
            "approved": bool,
            "violations": list[str],
            "policy_version": str,
            "fail_reason": str | None,
        }

    LLM_FORBIDDEN. Детерминированные правила.
    approved=False не может быть переопределён никаким агентом.
    """
    # LLM_FORBIDDEN
    violations: list[str] = []

    # ─── FAIL-CLOSED: критические параметры обязательны ────────────────────
    if not pool_name:
        violations.append("FAIL_CLOSED: pool_name missing")
    if not protocol:
        violations.append("FAIL_CLOSED: protocol missing")
    if fee_apy_24h is None:
        violations.append("FAIL_CLOSED: fee_apy_24h missing")
    if pool_tvl_usd is None:
        violations.append("FAIL_CLOSED: pool_tvl_usd missing")
    if audit_count is None:
        violations.append("FAIL_CLOSED: audit_count missing")
    if il_current_pct is None:
        violations.append("FAIL_CLOSED: il_current_pct missing")

    if violations:
        return {
            "approved": False,
            "violations": violations,
            "policy_version": LP_POLICY_VERSION,
            "fail_reason": "fail_closed_missing_data",
        }

    # ─── ЛИМИТЫ ─────────────────────────────────────────────────────────────

    # 1. TVL floor
    if pool_tvl_usd < limits.min_pool_tvl_usd:
        violations.append(
            f"TVL ${pool_tvl_usd / 1e6:.1f}M < min ${limits.min_pool_tvl_usd / 1e6:.0f}M"
        )

    # 2. Min audits
    if audit_count < limits.min_audits:
        violations.append(
            f"audits {audit_count} < min {limits.min_audits}"
        )

    # 3. Fee APY floor
    if fee_apy_24h < limits.min_fee_apy_24h:
        violations.append(
            f"fee_apy_24h {fee_apy_24h * 100:.2f}% < min {limits.min_fee_apy_24h * 100:.1f}%"
        )

    # 4. Fee volatility ceiling
    if fee_volatility_7d is not None and fee_volatility_7d > limits.max_fee_volatility_7d:
        violations.append(
            f"fee_volatility_7d {fee_volatility_7d:.2f} > max {limits.max_fee_volatility_7d:.2f}"
        )

    # 5. Per-pool allocation cap
    if sleeve_allocation_pct is not None and sleeve_allocation_pct > limits.per_pool_cap:
        violations.append(
            f"allocation {sleeve_allocation_pct * 100:.1f}% > cap {limits.per_pool_cap * 100:.0f}%"
        )

    # 6. Cash buffer
    if sleeve_allocation_pct is not None:
        remaining = 1.0 - sleeve_allocation_pct
        if remaining < limits.cash_buffer_min:
            violations.append(
                f"cash buffer {remaining * 100:.1f}% < min {limits.cash_buffer_min * 100:.0f}%"
            )

    # 7. IL drawdown kill
    if current_drawdown_pct <= -limits.il_drawdown_kill_pct:
        violations.append(
            f"IL drawdown {current_drawdown_pct * 100:.1f}% hits kill"
            f" −{limits.il_drawdown_kill_pct * 100:.0f}%"
        )

    # 8. Range width (CLMM)
    if range_width_pct is not None and range_width_pct > limits.max_range_width_pct:
        violations.append(
            f"range_width {range_width_pct * 100:.0f}% > max {limits.max_range_width_pct * 100:.0f}%"
        )

    # 9. Delta neutral requirement
    if (
        limits.require_delta_neutral
        and is_delta_neutral is not None
        and not is_delta_neutral
    ):
        violations.append("FAIL: position is not delta-neutral (asymmetric range)")

    # 10. Liquidity depth
    if (
        liquidity_depth_usd is not None
        and liquidity_depth_usd < limits.min_liquidity_depth_usd
    ):
        violations.append(
            f"liquidity depth ${liquidity_depth_usd / 1e3:.0f}K"
            f" < min ${limits.min_liquidity_depth_usd / 1e3:.0f}K"
        )

    approved = len(violations) == 0
    return {
        "approved": approved,
        "violations": violations,
        "policy_version": LP_POLICY_VERSION,
        "fail_reason": None if approved else "limit_violation",
    }


def estimate_il(
    current_price: float,
    entry_price: float,
    range_lower: float,
    range_upper: float,
) -> dict:
    """
    Оценивает Impermanent Loss для CLMM (Uniswap V3-стиль) позиции.
    Детерминированная математика, без AI.

    Формула:
      - В диапазоне: классическая CLMM IL относительно hold 50/50.
      - Вне диапазона: LP полностью конвертирован в один токен,
        IL рассчитывается как разница с hold 50/50.

    LLM_FORBIDDEN.

    Returns:
        {
            "il_pct": float,            # IL как доля (0..1)
            "in_range": bool,
            "out_of_range_lower": bool,
            "out_of_range_upper": bool,
            "current_price": float,
            "entry_price": float,
            "range": [lower, upper],
        }
    """
    # LLM_FORBIDDEN
    in_range = range_lower <= current_price <= range_upper
    out_lower = current_price < range_lower
    out_upper = current_price > range_upper

    if not in_range:
        # Вне диапазона — позиция полностью однотокенная.
        # LP value относительно hold 50/50 (k=1.0 нормировано к entry_price).
        price_ratio = current_price / entry_price

        # hold 50/50 value (нормировано к 1.0 при entry):
        hold_value = 0.5 * price_ratio + 0.5

        # LP при выходе вниз: 100% в quote (стейбл) → value = 1.0 (не растёт)
        # LP при выходе вверх: 100% в base → value = price_ratio
        lp_value = 1.0 if out_lower else price_ratio

        il = max(0.0, (hold_value - lp_value) / hold_value)
    else:
        # В диапазоне — стандартная формула CLMM IL.
        # Используем упрощённую аналитическую форму:
        #   IL = 1 - 2*sqrt(k) / (1 + k), где k = current_price / entry_price
        # Источник: Uniswap V2/V3 IL derivation.
        k = current_price / entry_price
        if k > 0:
            il = max(0.0, 1.0 - (2.0 * math.sqrt(k)) / (1.0 + k))
        else:
            il = 0.0

    return {
        "il_pct": il,
        "in_range": in_range,
        "out_of_range_lower": out_lower,
        "out_of_range_upper": out_upper,
        "current_price": current_price,
        "entry_price": entry_price,
        "range": [range_lower, range_upper],
    }
