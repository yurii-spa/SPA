"""
RiskPolicy-HY v1.0 — Engine B (Carry/RS-003)
LLM_FORBIDDEN: этот модуль не вызывает и не использует LLM.
Источник правды для лимитов слоя B. Allocator вызывает, не дублирует.
fail-closed: нет данных → approved=False.

Governance:
  - Изменение лимитов → новый ADR + snapshot в spa_core/risk/versions/
  - approved=False не может быть переопределён никаким агентом
  - Версия остаётся hy_v1.0 весь период до отдельного ADR

LLM_FORBIDDEN_AGENTS = {risk, execution, monitoring}
"""
# LLM_FORBIDDEN
from dataclasses import dataclass
from typing import Optional
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Версия политики — меняется только через ADR
HY_POLICY_VERSION = "hy_v1.0"


@dataclass(frozen=True)
class HYRiskLimits:
    """
    Жёсткие лимиты Engine B (Carry/HY). Единственный источник правды.
    Импортировать отсюда, не дублировать в аллокаторе.

    LLM_FORBIDDEN: значения заданы детерминированно, без AI.
    """
    # Per-protocol allocation cap (% от слоя B)
    per_protocol_cap: float = 0.25        # ≤25% слоя

    # Min TVL USD (обёртка/протокол)
    min_tvl_usd: float = 100_000_000.0   # $100M

    # Min audits count
    min_audits: int = 2

    # Drawdown kill (от equity слоя B)
    drawdown_kill_pct: float = 0.08      # −8% слоя

    # Cash buffer minimum (% от слоя B)
    cash_buffer_min: float = 0.10        # ≥10%

    # Sleeve B hard cap (% от total portfolio)
    sleeve_cap_total: float = 0.65       # ≤65% портфеля

    # Funding rate ENTER threshold (annualized) — строже EXIT
    funding_rate_enter: float = 0.05     # >5% APY

    # Funding rate EXIT threshold (annualized) — мягче ENTER (гистерезис)
    funding_rate_exit: float = 0.02      # <2% APY

    # Depeg ENTER threshold — строже EXIT
    depeg_enter_pct: float = 0.003       # <0.3%

    # Depeg EXIT threshold — мягче ENTER (гистерезис)
    depeg_exit_pct: float = 0.006        # ≥0.6%

    # Max term-to-maturity для Pendle PT (дней)
    max_term_to_maturity_days: int = 180

    # Min liquidity (USD depth)
    min_liquidity_usd: float = 500_000.0


# Singleton — аллокатор импортирует это, не переопределяет
HY_LIMITS = HYRiskLimits()


def evaluate_protocol(
    *,
    protocol_name: str,
    yield_apy: Optional[float],
    tvl_usd: Optional[float],
    depeg_pct: Optional[float],
    funding_rate: Optional[float],
    audit_count: Optional[int],
    term_to_maturity_days: Optional[int] = None,
    liquidity_usd: Optional[float] = None,
    sleeve_allocation_pct: Optional[float] = None,
    current_drawdown_pct: float = 0.0,
    limits: HYRiskLimits = HY_LIMITS,
) -> dict:
    """
    ENTER гейт Engine B (fail-closed).

    Проверяет условия для открытия/удержания позиции в протоколе Engine B.
    Все критические параметры обязательны — отсутствие любого → approved=False.

    Returns:
        {
            "approved": bool,
            "violations": list[str],
            "policy_version": str,
            "fail_reason": str | None,
        }

    LLM_FORBIDDEN: детерминированные правила, без AI.
    fail-closed: любой None критического параметра → approved=False.
    """
    # LLM_FORBIDDEN
    violations: list = []

    # --- FAIL-CLOSED: отсутствие критических данных → блок ---
    if yield_apy is None:
        violations.append("FAIL_CLOSED: yield_apy missing")
    if tvl_usd is None:
        violations.append("FAIL_CLOSED: tvl_usd missing")
    if depeg_pct is None:
        violations.append("FAIL_CLOSED: depeg_pct missing")
    if funding_rate is None:
        violations.append("FAIL_CLOSED: funding_rate missing")
    if audit_count is None:
        violations.append("FAIL_CLOSED: audit_count missing")

    # Если критические данные отсутствуют — немедленный return False
    if violations:
        return {
            "approved": False,
            "violations": violations,
            "policy_version": HY_POLICY_VERSION,
            "fail_reason": "fail_closed_missing_data",
        }

    # --- ЛИМИТЫ (все данные присутствуют) ---

    # 1. TVL floor
    if tvl_usd < limits.min_tvl_usd:
        violations.append(
            f"TVL {tvl_usd / 1e6:.1f}M < min {limits.min_tvl_usd / 1e6:.0f}M"
        )

    # 2. Min audits
    if audit_count < limits.min_audits:
        violations.append(
            f"audits {audit_count} < min {limits.min_audits}"
        )

    # 3. Depeg — ENTER только если < enter threshold
    if depeg_pct >= limits.depeg_enter_pct:
        violations.append(
            f"depeg {depeg_pct * 100:.2f}% >= enter threshold {limits.depeg_enter_pct * 100:.1f}%"
        )

    # 4. Funding rate — ENTER только если > enter threshold
    if funding_rate <= limits.funding_rate_enter:
        violations.append(
            f"funding_rate {funding_rate * 100:.2f}% <= enter threshold "
            f"{limits.funding_rate_enter * 100:.1f}%"
        )

    # 5. Per-protocol cap (% от слоя B)
    if sleeve_allocation_pct is not None and sleeve_allocation_pct > limits.per_protocol_cap:
        violations.append(
            f"allocation {sleeve_allocation_pct * 100:.1f}% > cap "
            f"{limits.per_protocol_cap * 100:.0f}%"
        )

    # 6. Cash buffer (остаток после аллокации)
    if sleeve_allocation_pct is not None:
        remaining = 1.0 - sleeve_allocation_pct
        if remaining < limits.cash_buffer_min:
            violations.append(
                f"cash buffer {remaining * 100:.1f}% < min "
                f"{limits.cash_buffer_min * 100:.0f}%"
            )

    # 7. Drawdown kill switch
    if current_drawdown_pct <= -limits.drawdown_kill_pct:
        violations.append(
            f"drawdown {current_drawdown_pct * 100:.1f}% hits kill "
            f"threshold -{limits.drawdown_kill_pct * 100:.0f}%"
        )

    # 8. Term to maturity (Pendle PT и аналоги)
    if (
        term_to_maturity_days is not None
        and term_to_maturity_days > limits.max_term_to_maturity_days
    ):
        violations.append(
            f"term_to_maturity {term_to_maturity_days}d > max "
            f"{limits.max_term_to_maturity_days}d"
        )

    # 9. Liquidity floor
    if liquidity_usd is not None and liquidity_usd < limits.min_liquidity_usd:
        violations.append(
            f"liquidity ${liquidity_usd / 1e3:.0f}K < min "
            f"${limits.min_liquidity_usd / 1e3:.0f}K"
        )

    approved = len(violations) == 0
    return {
        "approved": approved,
        "violations": violations,
        "policy_version": HY_POLICY_VERSION,
        "fail_reason": None if approved else "limit_violation",
    }


def evaluate_exit(
    *,
    depeg_pct: Optional[float],
    funding_rate: Optional[float],
    current_drawdown_pct: float = 0.0,
    limits: HYRiskLimits = HY_LIMITS,
) -> dict:
    """
    EXIT гейт Engine B (с гистерезисом).

    EXIT порог мягче ENTER порога — избегает флипинг при граничных значениях.
    fail-closed: нет данных → should_exit=True (принудительный выход).

    Returns:
        {
            "should_exit": bool,
            "exit_signals": list[str],
            "policy_version": str,
        }

    LLM_FORBIDDEN: детерминированные правила, без AI.
    """
    # LLM_FORBIDDEN
    exit_signals: list = []

    # fail-closed: нет критических данных → принудительный EXIT
    if depeg_pct is None:
        exit_signals.append("FAIL_CLOSED: depeg_pct missing -> EXIT")
    if funding_rate is None:
        exit_signals.append("FAIL_CLOSED: funding_rate missing -> EXIT")

    if exit_signals:
        return {
            "should_exit": True,
            "exit_signals": exit_signals,
            "policy_version": HY_POLICY_VERSION,
        }

    # Гистерезис: EXIT порог мягче ENTER порога
    # Depeg EXIT: ≥0.6% (vs ENTER: <0.3%)
    if depeg_pct >= limits.depeg_exit_pct:
        exit_signals.append(
            f"depeg {depeg_pct * 100:.2f}% >= exit threshold "
            f"{limits.depeg_exit_pct * 100:.1f}%"
        )

    # Funding rate EXIT: ≤2% (vs ENTER: >5%)
    if funding_rate <= limits.funding_rate_exit:
        exit_signals.append(
            f"funding_rate {funding_rate * 100:.2f}% <= exit threshold "
            f"{limits.funding_rate_exit * 100:.1f}%"
        )

    # Drawdown kill (одинаков для ENTER и EXIT)
    if current_drawdown_pct <= -limits.drawdown_kill_pct:
        exit_signals.append(
            f"drawdown kill: {current_drawdown_pct * 100:.1f}% <= "
            f"-{limits.drawdown_kill_pct * 100:.0f}%"
        )

    return {
        "should_exit": len(exit_signals) > 0,
        "exit_signals": exit_signals,
        "policy_version": HY_POLICY_VERSION,
    }
