"""
SPA Risk Policy — детерминированный код (без LLM)
Фаза 0B: все риск-проверки до любого действия с капиталом.

КРИТИЧЕСКИ ВАЖНО: этот файл содержит только детерминированный код.
LLM-агенты не имеют права изменять результаты этих проверок.
Любое изменение правил — только через ADR + код-ревью Owner.

GOVERNANCE:
  Active version: v1.0 (2026-05-20)
  Change process:
    1) Create ADR in docs/adr/
    2) Get owner approval (Yurii)
    3) Snapshot current RiskConfig to spa_core/risk/versions/<vX_Y_name>.py
    4) Paper test new policy for ≥ 2 weeks
    5) Owner sign-off → merge to main
  Rollback: load RiskConfig from spa_core/risk/versions/<old_version>.py
  Enforcement: approved=False from RiskPolicy CANNOT be overridden by any agent.

Использование:
    from risk.policy import RiskPolicy, Position, PortfolioState

    policy = RiskPolicy()
    state = PortfolioState(total_capital_usd=10000.0, positions=[...])
    result = policy.check_new_position(state, "aave-v3-usdc-ethereum", 3000.0, apy=5.5)
    if result.approved:
        execute_trade(...)
"""

from __future__ import annotations

import math
import logging
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger(__name__)

# ─── Конфигурация риск-политики ──────────────────────────────────────────────

@dataclass
class RiskConfig:
    """
    Параметры риск-политики. Изменять только через ADR + Owner approval.

    Governance rules:
    - Agents MUST follow the active policy — they cannot override approved=False.
    - Any parameter change requires: ADR → owner approval → snapshot → paper test → merge.
    - Every change gets a new version number so we can rollback.
    - New policies must be paper-tested for ≥ 2 weeks before any live capital deployment.

    See: docs/adr/ADR_001_initial_risk_policy.md for rationale of current values.
    See: spa_core/risk/versions/ for historical snapshots (rollback targets).
    """

    # ── Version metadata ──────────────────────────────────────────────────────
    version: str = "v1.0"
    version_date: str = "2026-05-20"
    changelog: str = (
        "Initial policy: T1/T2 concentration limits, 5% drawdown kill switch, 5% cash buffer. "
        "MP-352 (2026-06-12): ethereum chain limit 70%→90% (structural, all adapters are L1). "
        "ADR-019 (2026-06-12): T2 cap 35%→50%. "
        "ADR-020 (2026-06-12): T3 Private Credit cap 15% added."
    )

    # Концентрационные лимиты — максимум % портфеля в один протокол
    max_concentration_t1: float = 0.40   # T1: макс 40%
    max_concentration_t2: float = 0.20   # T2: макс 20%
    max_single_protocol:  float = 0.40   # абсолютный макс на любой протокол

    # Circuit breakers — автостоп
    max_apy_for_new_position: float = 30.0   # % — не входим если APY > 30% (слишком высокий риск)
    min_apy_for_new_position: float = 1.0    # % — не входим если APY < 1% (неинтересно)
    min_tvl_usd: float = 5_000_000          # $5M — минимальный TVL для входа
    max_drawdown_stop: float = 0.05          # 5% — kill switch всего портфеля
    max_single_position_drawdown: float = 0.03  # 3% — закрыть позицию

    # VaR параметры (исторический, 95% confidence, 7-дневный горизонт)
    var_confidence: float = 0.95
    var_horizon_days: int = 7
    max_var_pct: float = 0.05               # VaR не более 5% от портфеля

    # Минимальный денежный буфер
    min_cash_pct: float = 0.05              # 5% всегда в кэше

    # ── Multi-chain limits ────────────────────────────────────────────────────
    # MP-352 (2026-06-12): Ethereum single-chain limit raised 70% → 90%.
    # All current T1/T2 adapters (Aave V3, Compound V3, Morpho Blue,
    # Yearn V3, Euler V2, Maple) are on Ethereum L1 mainnet. The old 70%
    # threshold fired on every normal cycle as structural noise.
    # Ethereum concentration natural — all T1/T2 adapters are L1 mainnet.
    # Warning re-enabled when L2 adapters added.
    max_single_chain_allocation: float = 0.90    # max 90% on any single chain (MP-352: was 0.70)
    max_l2_total_allocation: float = 0.50        # L2s combined max 50% (Arbitrum+Base only)
    preferred_chains: list = field(default_factory=lambda: ["ethereum", "arbitrum", "base"])

    # ── T2 category limit (ADR-019, 2026-06-12) ──────────────────────────────
    # Raised from 35% → 50% to accommodate additional T2 protocols
    # (Pendle, Clearpool, etc.) with TVL > $100M guard in allocator.
    # Rationale: ADR-019-t2-cap-increase.md
    max_total_t2_allocation: float = 0.50  # T2 совокупно не более 50% (ADR-019: было 0.35)

    # ── T3 Private Credit / RWA limit (ADR-020, 2026-06-12) ──────────────────
    # New tier: Maple Finance, Clearpool, Goldfinch, Ondo USDY, Mountain USDM.
    # Conditions: audit ✓, TVL $20M+, track record 6+ months,
    # lock period awareness, no instant redemption, min hold 30 days.
    # Rationale: ADR-020-t3-private-credit.md
    max_total_t3_allocation: float = 0.15  # T3 совокупно не более 15% (ADR-020)

    # ── Base Chain cap (ADR-025, 2026-06-12) ─────────────────────────────────
    # Max portfolio allocation across all Base (Coinbase L2) adapters combined.
    # Phase 1: read-only monitoring only (no allocation until 2026-07-12 review).
    # Phase 2: up to 20% allowed after go-live + Owner approval (APPROVE_BASE).
    # Rationale: ADR-025-base-chain-expansion.md
    BASE_CHAIN_CAP: float = 0.20  # max 20% of portfolio across all Base chain adapters (ADR-025)


# ─── Модели данных ───────────────────────────────────────────────────────────

@dataclass
class Position:
    """Открытая позиция в paper trading."""
    protocol_key: str
    tier: str                    # "T1" | "T2"
    asset: str
    amount_usd: float
    apy_at_open: float           # % при входе
    current_apy: float           # % сейчас
    unrealized_pnl_usd: float = 0.0
    days_held: float = 0.0
    chain: str = "ethereum"      # chain name (lowercase); default for backward compat

    @property
    def unrealized_pnl_pct(self) -> float:
        if self.amount_usd == 0:
            return 0.0
        return self.unrealized_pnl_usd / self.amount_usd


@dataclass
class PortfolioState:
    """Текущее состояние портфеля."""
    total_capital_usd: float
    positions: list[Position] = field(default_factory=list)

    @property
    def deployed_usd(self) -> float:
        return sum(p.amount_usd for p in self.positions)

    @property
    def cash_usd(self) -> float:
        return self.total_capital_usd - self.deployed_usd

    @property
    def cash_pct(self) -> float:
        if self.total_capital_usd == 0:
            return 0.0
        return self.cash_usd / self.total_capital_usd

    @property
    def total_pnl_usd(self) -> float:
        return sum(p.unrealized_pnl_usd for p in self.positions)

    @property
    def total_drawdown_pct(self) -> float:
        if self.total_capital_usd == 0:
            return 0.0
        return max(0.0, -self.total_pnl_usd / self.total_capital_usd)

    def concentration_pct(self, protocol_key: str) -> float:
        """Процент портфеля в конкретном протоколе."""
        if self.total_capital_usd == 0:
            return 0.0
        total_in_protocol = sum(
            p.amount_usd for p in self.positions if p.protocol_key == protocol_key
        )
        return total_in_protocol / self.total_capital_usd

    def t2_allocation_pct(self) -> float:
        """Суммарный процент T2 протоколов."""
        if self.total_capital_usd == 0:
            return 0.0
        t2_total = sum(p.amount_usd for p in self.positions if p.tier == "T2")
        return t2_total / self.total_capital_usd

    def chain_allocation_pct(self, chain: str) -> float:
        """Percent of portfolio deployed on a specific chain."""
        if self.total_capital_usd == 0:
            return 0.0
        chain_total = sum(
            p.amount_usd for p in self.positions
            if (p.chain or "ethereum").lower() == chain.lower()
        )
        return chain_total / self.total_capital_usd

    def l2_allocation_pct(self) -> float:
        """Percent of portfolio deployed on L2 chains (Arbitrum+Base+Optimism+Polygon)."""
        L2_CHAINS = {"arbitrum", "base"}
        if self.total_capital_usd == 0:
            return 0.0
        l2_total = sum(
            p.amount_usd for p in self.positions
            if (p.chain or "ethereum").lower() in L2_CHAINS
        )
        return l2_total / self.total_capital_usd


@dataclass
class RiskCheckResult:
    """Результат риск-проверки."""
    approved: bool
    violations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    check_name: str = ""
    # MP-208: результаты проверки осей риска (credit/peg/duration/bridge)
    # Заполняется только при вызове check_axis_compliance или check_portfolio_health(check_axes=True)
    axis_checks: dict = field(default_factory=dict)
    # MP-209: результаты capacity limits check (warn-only первые 2 недели)
    # Заполняется при check_capacity=True в check_new_position / check_portfolio_health
    capacity_check: dict = field(default_factory=dict)

    def __str__(self) -> str:
        status = "APPROVED" if self.approved else "REJECTED"
        parts = [f"[{status}] {self.check_name}"]
        for v in self.violations:
            parts.append(f"  ✗ {v}")
        for w in self.warnings:
            parts.append(f"  ⚠ {w}")
        return "\n".join(parts)


# ─── Risk Policy ─────────────────────────────────────────────────────────────

class RiskPolicy:
    """
    Детерминированный риск-контроль SPA.

    Все методы возвращают RiskCheckResult.
    approved=False означает ЗАПРЕТ на действие.
    Этот запрет не может быть переопределён агентами.
    """

    def __init__(self, config: Optional[RiskConfig] = None) -> None:
        self.config = config or RiskConfig()

    # ── Основные проверки ─────────────────────────────────────────────────────

    def check_new_position(
        self,
        state: PortfolioState,
        protocol_key: str,
        tier: str,
        amount_usd: float,
        current_apy: float,
        tvl_usd: float,
        chain: str = "ethereum",
        check_capacity: bool = True,
    ) -> RiskCheckResult:
        """
        Проверить возможность открытия новой позиции.
        Запускать ПЕРЕД каждой сделкой без исключений.
        """
        violations = []
        warnings = []

        # 1. Circuit breaker: портфельный drawdown
        if state.total_drawdown_pct >= self.config.max_drawdown_stop:
            violations.append(
                f"Portfolio drawdown {state.total_drawdown_pct:.1%} ≥ "
                f"kill switch threshold {self.config.max_drawdown_stop:.1%}"
            )

        # 2. APY в допустимом диапазоне
        if current_apy > self.config.max_apy_for_new_position:
            violations.append(
                f"APY {current_apy:.1f}% exceeds maximum allowed "
                f"{self.config.max_apy_for_new_position:.1f}% (risk too high)"
            )
        elif current_apy < self.config.min_apy_for_new_position:
            violations.append(
                f"APY {current_apy:.1f}% below minimum "
                f"{self.config.min_apy_for_new_position:.1f}% (not attractive)"
            )

        # 3. Минимальный TVL
        if tvl_usd < self.config.min_tvl_usd:
            violations.append(
                f"TVL ${tvl_usd:,.0f} below minimum ${self.config.min_tvl_usd:,.0f}"
            )

        # 4. Достаточно кэша для позиции
        if amount_usd > state.cash_usd:
            violations.append(
                f"Insufficient cash: need ${amount_usd:,.0f}, available ${state.cash_usd:,.0f}"
            )

        # 5. После сделки сохранится минимальный кэш-буфер
        remaining_cash = state.cash_usd - amount_usd
        remaining_cash_pct = remaining_cash / state.total_capital_usd if state.total_capital_usd > 0 else 0
        if remaining_cash_pct < self.config.min_cash_pct:
            violations.append(
                f"After trade, cash buffer {remaining_cash_pct:.1%} < "
                f"minimum {self.config.min_cash_pct:.1%}"
            )

        # 6. Концентрационный лимит по протоколу
        current_conc = state.concentration_pct(protocol_key)
        new_conc = (state.concentration_pct(protocol_key) * state.total_capital_usd + amount_usd) / state.total_capital_usd
        max_conc = (
            self.config.max_concentration_t1 if tier == "T1"
            else self.config.max_concentration_t2
        )
        if new_conc > max_conc:
            violations.append(
                f"Concentration after trade {new_conc:.1%} exceeds "
                f"{tier} limit {max_conc:.1%} for {protocol_key}"
            )
        elif new_conc > max_conc * 0.85:
            warnings.append(
                f"Concentration {new_conc:.1%} approaching {tier} limit {max_conc:.1%}"
            )

        # 7. (Removed — redundant: max_single_protocol == max_concentration_t1 == 0.40,
        #     so check #6 already catches all cases. Removing avoids duplicate violations.)

        # 8. Лимит T2 совокупно
        if tier == "T2":
            new_t2 = state.t2_allocation_pct() + (amount_usd / state.total_capital_usd)
            if new_t2 > self.config.max_total_t2_allocation:
                violations.append(
                    f"Total T2 allocation {new_t2:.1%} would exceed "
                    f"limit {self.config.max_total_t2_allocation:.1%}"
                )

        # 9. Single-chain concentration limit
        if state.total_capital_usd > 0:
            new_chain_alloc = state.chain_allocation_pct(chain) + (amount_usd / state.total_capital_usd)
            if new_chain_alloc > self.config.max_single_chain_allocation:
                violations.append(
                    f"Chain concentration on {chain} after trade {new_chain_alloc:.1%} exceeds "
                    f"single-chain limit {self.config.max_single_chain_allocation:.1%}"
                )
            elif new_chain_alloc > self.config.max_single_chain_allocation * 0.85:
                warnings.append(
                    f"Chain concentration on {chain} {new_chain_alloc:.1%} approaching "
                    f"limit {self.config.max_single_chain_allocation:.1%}"
                )

        # 10. L2 total allocation limit
        L2_CHAINS = {"arbitrum", "base"}
        if chain.lower() in L2_CHAINS and state.total_capital_usd > 0:
            new_l2 = state.l2_allocation_pct() + (amount_usd / state.total_capital_usd)
            if new_l2 > self.config.max_l2_total_allocation:
                violations.append(
                    f"Total L2 allocation {new_l2:.1%} would exceed "
                    f"L2 combined limit {self.config.max_l2_total_allocation:.1%}"
                )

        # 11. MP-209: Capacity limit (warn-only — позиция ≤ 1% TVL пула).
        # Не блокирует: warn-only режим первые 2 недели (ADR-009).
        cap_check: dict = {}
        if check_capacity:
            from spa_core.risk.capacity_limits import (  # lazy, нет цикл. импорта
                check_capacity as _check_cap,
                effective_max_pct,
            )
            eff_pct = effective_max_pct(protocol_key, tier, tvl_usd)
            cap_check = _check_cap(protocol_key, amount_usd, tvl_usd, eff_pct)
            if not cap_check["ok"]:
                warnings.append(
                    f"CAPACITY_WARN (MP-209): {cap_check['message']} "
                    f"for {protocol_key} — warn-only (ADR-009)"
                )

        # 12. MP-203: Chain limits — warn-only (не блокирует).
        # Строит гипотетическую аллокацию с новой позицией и проверяет
        # лимиты по цепочкам через chain_limits.check_chain_limits().
        if state.total_capital_usd > 0:
            try:
                from spa_core.risk.chain_limits import (  # lazy — нет цикл. импорта
                    check_chain_limits,
                    get_default_chain_map,
                )
                _chain_map = get_default_chain_map()
                _chain_map[protocol_key] = chain.lower()
                _alloc = {
                    p.protocol_key: p.amount_usd / state.total_capital_usd
                    for p in state.positions
                }
                _alloc[protocol_key] = (
                    _alloc.get(protocol_key, 0.0)
                    + amount_usd / state.total_capital_usd
                )
                _chain_result = check_chain_limits(_alloc, _chain_map)
                for v in _chain_result.get("violations", []):
                    warnings.append(f"CHAIN_LIMIT_WARN (MP-203): {v}")
            except Exception as _exc:  # noqa: BLE001
                log.warning("chain_limits check failed (non-blocking): %s", _exc)

        approved = len(violations) == 0
        result = RiskCheckResult(
            approved=approved,
            violations=violations,
            warnings=warnings,
            check_name=f"new_position({protocol_key}, ${amount_usd:,.0f})",
            capacity_check=cap_check,
        )
        self._log_result(result)
        return result

    def check_portfolio_health(
        self,
        state: PortfolioState,
        stablecoin_prices: dict[str, float] | None = None,
        check_axes: bool = False,
        exit_latency_map: dict | None = None,
        check_capacity: bool = True,
        tvl_map: dict | None = None,
    ) -> RiskCheckResult:
        """
        Общая проверка здоровья портфеля.
        Запускать при каждом обновлении данных.

        Args:
            state: текущее состояние портфеля.
            stablecoin_prices: optional dict {symbol -> spot price (USD)}. When
                provided, stablecoin depeg detection is run via
                PriceFeedFetcher.detect_depeg(). CRITICAL events become
                violations (kill-switch); WARN events become warnings.
                When None (default), depeg check is skipped — preserves
                byte-for-byte backwards compatibility with existing call-sites.
        """
        violations = []
        warnings = []

        # Kill switch — полный drawdown
        if state.total_drawdown_pct >= self.config.max_drawdown_stop:
            violations.append(
                f"KILL SWITCH TRIGGERED: portfolio drawdown {state.total_drawdown_pct:.1%} "
                f"≥ {self.config.max_drawdown_stop:.1%}. Close all positions."
            )

        # Предупреждение при приближении к лимиту
        elif state.total_drawdown_pct >= self.config.max_drawdown_stop * 0.75:
            warnings.append(
                f"Drawdown {state.total_drawdown_pct:.1%} approaching kill switch "
                f"{self.config.max_drawdown_stop:.1%}"
            )

        # ── Stablecoin depeg kill-switch (FEAT-006 Phase 3) ──────────────────
        # Run only when caller supplied stablecoin_prices — backwards-compatible.
        if stablecoin_prices is not None:
            # Lazy import to avoid any potential import cycle with data_pipeline.
            from data_pipeline.price_feeds import PriceFeedFetcher

            depeg_events = PriceFeedFetcher().detect_depeg(stablecoin_prices)
            for ev in depeg_events:
                sym = ev["symbol"]
                price = ev["price"]
                dev = ev["deviation_pct"]
                severity = ev["severity"]
                if severity == "CRITICAL":
                    violations.append(
                        f"DEPEG KILL SWITCH: {sym} at ${price:.4f} ({dev:+.2f}%) — "
                        f"CRITICAL depeg, close exposed positions"
                    )
                elif severity == "WARN":
                    warnings.append(
                        f"DEPEG WARN: {sym} at ${price:.4f} ({dev:+.2f}%) — monitor closely"
                    )

        # Проверка концентрации всех позиций
        seen_protocols: set[str] = set()
        for pos in state.positions:
            if pos.protocol_key in seen_protocols:
                continue
            seen_protocols.add(pos.protocol_key)

            conc = state.concentration_pct(pos.protocol_key)
            max_conc = (
                self.config.max_concentration_t1 if pos.tier == "T1"
                else self.config.max_concentration_t2
            )
            if conc > max_conc:
                violations.append(
                    f"Concentration breach: {pos.protocol_key} at {conc:.1%} > {max_conc:.1%}"
                )

        # Проверка отдельных позиций на drawdown
        for pos in state.positions:
            if pos.unrealized_pnl_pct < -self.config.max_single_position_drawdown:
                warnings.append(
                    f"Position {pos.protocol_key} at {pos.unrealized_pnl_pct:.1%} loss "
                    f"(threshold: {-self.config.max_single_position_drawdown:.1%})"
                )

        # Кэш-буфер
        if state.cash_pct < self.config.min_cash_pct:
            warnings.append(
                f"Cash buffer {state.cash_pct:.1%} below minimum {self.config.min_cash_pct:.1%}"
            )

        # MP-208: оси риска (credit/peg/duration/bridge) — опционально
        axis_checks: dict = {}
        if check_axes and state.positions:
            allocation = self._state_to_allocation(state)
            axis_result = self.check_axis_compliance(allocation, exit_latency_map)
            violations.extend(axis_result.violations)
            axis_checks = axis_result.axis_checks

        # MP-209: capacity limits check (warn-only — позиция ≤ 1% TVL пула).
        # Не блокирует: warn-only режим первые 2 недели (ADR-009).
        # Требует tvl_map: {protocol_key: tvl_usd}. Если None → skip.
        capacity_check: dict = {}
        if check_capacity and tvl_map and state.positions:
            from spa_core.risk.capacity_limits import (  # lazy, нет цикл. импорта
                check_all_capacities,
            )
            allocation_usd = {p.protocol_key: p.amount_usd for p in state.positions}
            capacity_check = check_all_capacities(allocation_usd, tvl_map)
            for w in capacity_check.get("warnings", []):
                warnings.append(f"CAPACITY_WARN (MP-209): {w}")
            # Нарушения — в warnings (не violations), warn-only режим ADR-009
            for v in capacity_check.get("violations", []):
                warnings.append(f"CAPACITY_WARN (MP-209): {v}")

        # MP-203: Chain limits portfolio health check — warn-only (не блокирует).
        if state.positions:
            try:
                from spa_core.risk.chain_limits import (  # lazy — нет цикл. импорта
                    check_chain_limits,
                    get_default_chain_map,
                )
                _alloc = self._state_to_allocation(state)
                _chain_result = check_chain_limits(_alloc, get_default_chain_map())
                for v in _chain_result.get("violations", []):
                    warnings.append(f"CHAIN_LIMIT_WARN (MP-203): {v}")
            except Exception as _exc:  # noqa: BLE001
                log.warning("chain_limits portfolio check failed (non-blocking): %s", _exc)

        approved = len(violations) == 0
        result = RiskCheckResult(
            approved=approved,
            violations=violations,
            warnings=warnings,
            check_name="portfolio_health",
            axis_checks=axis_checks,
            capacity_check=capacity_check,
        )
        self._log_result(result)
        return result

    def check_stablecoin_depeg(
        self,
        prices: dict[str, float],
        threshold: float | None = None,
    ) -> RiskCheckResult:
        """
        Standalone stablecoin depeg check (FEAT-006 Phase 3).

        Returns a RiskCheckResult so this can be wired into any orchestration
        loop without requiring a full PortfolioState. CRITICAL events become
        violations (approved=False); WARN events become warnings (approved=True).

        Args:
            prices: mapping symbol → spot price (USD).
            threshold: optional override for depeg threshold (fraction). Falls
                back to PriceFeedFetcher.DEFAULT_DEPEG_THRESHOLD when None.
        """
        from data_pipeline.price_feeds import PriceFeedFetcher

        violations: list[str] = []
        warnings: list[str] = []

        events = PriceFeedFetcher().detect_depeg(prices, threshold)
        for ev in events:
            sym = ev["symbol"]
            price = ev["price"]
            dev = ev["deviation_pct"]
            severity = ev["severity"]
            if severity == "CRITICAL":
                violations.append(
                    f"DEPEG KILL SWITCH: {sym} at ${price:.4f} ({dev:+.2f}%) — "
                    f"CRITICAL depeg, close exposed positions"
                )
            elif severity == "WARN":
                warnings.append(
                    f"DEPEG WARN: {sym} at ${price:.4f} ({dev:+.2f}%) — monitor closely"
                )

        approved = len(violations) == 0
        result = RiskCheckResult(
            approved=approved,
            violations=violations,
            warnings=warnings,
            check_name="stablecoin_depeg",
        )
        self._log_result(result)
        return result

    def calculate_var(
        self,
        state: PortfolioState,
        apy_std_pct: float = 2.0,  # стандартное отклонение APY в % (дефолт)
    ) -> dict:
        """
        Исторический VaR (параметрический proxy).

        Для paper trading используем упрощённый расчёт:
        - предполагаем нормальное распределение доходности
        - используем std APY как прокси волатильности

        Returns dict с VaR значениями.
        """
        if not state.positions or state.deployed_usd == 0:
            return {
                "var_usd": 0.0,
                "var_pct": 0.0,
                "confidence": self.config.var_confidence,
                "horizon_days": self.config.var_horizon_days,
                "breach": False,
            }

        # z-score для 95% confidence (одностороннее)
        z = 1.645

        # Портфельная волатильность (упрощённо — без корреляций)
        # σ_daily = σ_annual / sqrt(365)
        daily_std = (apy_std_pct / 100) / math.sqrt(365)
        horizon_std = daily_std * math.sqrt(self.config.var_horizon_days)

        var_pct = z * horizon_std
        var_usd = var_pct * state.deployed_usd

        breach = var_pct > self.config.max_var_pct

        return {
            "var_usd": round(var_usd, 2),
            "var_pct": round(var_pct, 6),
            "confidence": self.config.var_confidence,
            "horizon_days": self.config.var_horizon_days,
            "breach": breach,
            "max_var_pct": self.config.max_var_pct,
        }

    def max_safe_position_size(
        self,
        state: PortfolioState,
        protocol_key: str,
        tier: str,
    ) -> float:
        """
        Вычислить максимальный безопасный размер позиции
        с учётом всех лимитов.
        """
        capital = state.total_capital_usd

        # Ограничение по концентрации
        max_conc = (
            self.config.max_concentration_t1 if tier == "T1"
            else self.config.max_concentration_t2
        )
        max_by_concentration = max_conc * capital - (
            state.concentration_pct(protocol_key) * capital
        )

        # Ограничение по кэшу (оставить минимальный буфер)
        max_by_cash = state.cash_usd - (self.config.min_cash_pct * capital)

        # Ограничение T2
        max_by_t2 = float("inf")
        if tier == "T2":
            remaining_t2 = self.config.max_total_t2_allocation - state.t2_allocation_pct()
            max_by_t2 = max(0.0, remaining_t2 * capital)

        result = max(0.0, min(max_by_concentration, max_by_cash, max_by_t2))
        return round(result, 2)

    # ── Оси риска v2 (MP-208) ────────────────────────────────────────────────

    def check_axis_compliance(
        self,
        allocation: dict,
        exit_latency_map: dict | None = None,
    ) -> RiskCheckResult:
        """
        Проверить соответствие аллокации осям риска v2 (MP-208).

        Вызывает check_all_axes() из risk_axes.py и упаковывает результат
        в стандартный RiskCheckResult. Нарушения → violations (approved=False).

        Args:
            allocation: {protocol_name: weight_fraction} (веса 0…1, сумма ≤ 1)
            exit_latency_map: {protocol_name: exit_latency_hours} (опционально)

        Returns:
            RiskCheckResult с approved=False если любая ось нарушена.
            Поле axis_checks содержит детали каждой из 4 осей.
        """
        from spa_core.risk.risk_axes import check_all_axes  # lazy — нет цикл. импорта
        axes = check_all_axes(allocation, exit_latency_map)
        result = RiskCheckResult(
            approved=axes["ok"],
            violations=axes["violations"],
            warnings=[],
            check_name="axis_compliance(credit/peg/duration/bridge)",
            axis_checks=axes,
        )
        self._log_result(result)
        return result

    def _state_to_allocation(self, state: PortfolioState) -> dict:
        """
        Конвертировать PortfolioState в allocation dict {protocol_key: weight_fraction}.
        Используется для передачи в check_axis_compliance.
        """
        if state.total_capital_usd == 0:
            return {}
        return {
            p.protocol_key: p.amount_usd / state.total_capital_usd
            for p in state.positions
        }

    # ── Утилиты ───────────────────────────────────────────────────────────────

    def _log_result(self, result: RiskCheckResult) -> None:
        if result.approved:
            if result.warnings:
                log.warning(f"Risk check APPROVED with warnings: {result.check_name}")
                for w in result.warnings:
                    log.warning(f"  ⚠ {w}")
            else:
                log.debug(f"Risk check APPROVED: {result.check_name}")
        else:
            log.error(f"Risk check REJECTED: {result.check_name}")
            for v in result.violations:
                log.error(f"  ✗ {v}")
