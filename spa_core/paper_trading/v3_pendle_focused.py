"""
SPA Strategy v3 — Pendle-Focused (IDEA-005 / Sprint v2.3)
===========================================================

Стратегия v3_pendle_focused специализируется на максимизации APY через:
  1. Агрессивное использование Pendle PT позиций (до 20% T2-лимита)
  2. Умный выбор пулов: только maturity > 30 дней, сортировка по APY
  3. Динамическая ротация: переход в новый пул если его APY на 0.5pp выше
  4. Остаток капитала — в лучшие T1 пулы

Цель: закрыть APY gap (текущий ~4.2% → цель 7.3%) за счёт Pendle PT.
Статус: PAPER TRADING ONLY — не использовать с реальным капиталом.

Архитектура:
  - V3PendleFocusedStrategy — основной класс с логикой аллокации
  - get_strategy_config()  — возвращает конфиг для STRATEGIES registry
  - select_best_pendle()   — выбор оптимального Pendle PT пула
  - should_rotate()        — определяет, нужна ли ротация позиции

Интеграция:
  from paper_trading.v3_pendle_focused import V3PendleFocusedStrategy
  strategy = V3PendleFocusedStrategy(capital=100_000)
  allocation = strategy.compute_allocation(pendle_pools, t1_pools)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

log = logging.getLogger(__name__)


# ─── Параметры стратегии ─────────────────────────────────────────────────────

# Pendle allocation limits (T2 tier constraint from RiskPolicy v1.0)
PENDLE_MAX_PCT        = 0.20   # max 20% капитала в Pendle PT (T2 лимит)
PENDLE_MIN_MATURITY_D = 30     # минимальный срок до maturity (дней)
PENDLE_MIN_APY        = 6.0    # минимальный APY для входа в Pendle PT

# Rotation threshold: rotate only if new pool's APY is significantly better
ROTATION_THRESHOLD_PP = 0.5   # 0.5 pp — порог для смены Pendle позиции

# T1 allocation parameters
T1_MAX_PCT            = 0.40   # max 40% капитала в T1 (RiskPolicy v1.0)
T1_CASH_BUFFER        = 0.05   # держать 5% кэша (RiskPolicy v1.0)
T1_MIN_APY            = 1.0    # минимальный APY для T1 позиции

# Strategy name
STRATEGY_ID = "v3_pendle_focused"


# ─── Dataclass для результата аллокации ─────────────────────────────────────

@dataclass
class AllocationDecision:
    """
    Результат вычисления аллокации для v3_pendle_focused.

    Поля:
        pendle_pool:    выбранный Pendle PT пул (или None если нет подходящих)
        pendle_amount:  сумма в Pendle PT в USD
        t1_allocations: список T1 аллокаций [{pool_key, amount_usd, apy}]
        total_deployed: итого задеплоено в USD
        cash_reserved:  остаток кэша в USD
        rotation_needed: True если нужно ротировать текущую Pendle позицию
        rotation_reason: причина ротации (для лога)
    """
    pendle_pool:     Optional[dict]
    pendle_amount:   float
    t1_allocations:  list[dict] = field(default_factory=list)
    total_deployed:  float = 0.0
    cash_reserved:   float = 0.0
    rotation_needed: bool = False
    rotation_reason: str = ""

    def summary(self) -> str:
        """Human-readable summary for logs."""
        lines = [
            f"v3_pendle_focused allocation:",
            f"  Pendle PT: ${self.pendle_amount:,.0f} "
            f"({self.pendle_pool['symbol'] if self.pendle_pool else 'none'} "
            f"@ {self.pendle_pool['apy']:.2f}% APY)" if self.pendle_pool else "  Pendle PT: $0 (no eligible pool)",
        ]
        for a in self.t1_allocations:
            lines.append(
                f"  T1 {a['pool_key']:30s}: ${a['amount_usd']:,.0f} @ {a['apy']:.2f}%"
            )
        lines.append(f"  Total deployed: ${self.total_deployed:,.0f}")
        lines.append(f"  Cash reserved:  ${self.cash_reserved:,.0f}")
        if self.rotation_needed:
            lines.append(f"  ⚡ Rotation: {self.rotation_reason}")
        return "\n".join(lines)


# ─── Core strategy class ─────────────────────────────────────────────────────

class V3PendleFocusedStrategy:
    """
    Pendle-focused allocation strategy.

    Логика аллокации:
    1. Из всех доступных Pendle PT пулов выбрать с лучшим APY,
       у которого days_to_maturity > PENDLE_MIN_MATURITY_D (30 дней).
    2. Аллоцировать min(PENDLE_MAX_PCT × capital, доступный кэш × 0.95)
       в выбранный Pendle PT пул.
    3. Оставшийся капитал (за вычетом 5% cash buffer) распределить
       по T1 пулам с лучшим APY, соблюдая лимиты концентрации.
    4. Если уже есть открытая Pendle позиция, проверить ротацию:
       ротировать если новый пул на 0.5pp+ лучше И у текущего
       позиция не слишком маленькая (> 30 дней до maturity).

    Все решения проходят через RiskPolicy — approved=False блокирует вход.
    """

    def __init__(
        self,
        capital: float = 100_000.0,
        pendle_max_pct: float = PENDLE_MAX_PCT,
        rotation_threshold: float = ROTATION_THRESHOLD_PP,
        t1_max_pct: float = T1_MAX_PCT,
        cash_buffer: float = T1_CASH_BUFFER,
    ):
        self.capital           = capital
        self.pendle_max_pct    = pendle_max_pct
        self.rotation_threshold = rotation_threshold
        self.t1_max_pct        = t1_max_pct
        self.cash_buffer       = cash_buffer

    # ── Public API ────────────────────────────────────────────────────────────

    def compute_allocation(
        self,
        pendle_pools: list[dict],
        t1_pools: list[dict],
        current_pendle_position: Optional[dict] = None,
        current_capital: Optional[float] = None,
    ) -> AllocationDecision:
        """
        Compute the full allocation plan.

        Args:
            pendle_pools:    List of Pendle PT pools from PendleFetcher.
                             Each dict: {pool_id, symbol, apy, tvl_usd, chain,
                                         maturity_date, days_to_maturity}
            t1_pools:        List of T1 whitelist pools.
                             Each dict: {pool_key, apy, tvl_usd, tier, protocol}
            current_pendle_position: Dict of currently open Pendle position
                             (or None if no position). Used for rotation check.
            current_capital: Override for self.capital (useful mid-session).

        Returns:
            AllocationDecision with full allocation plan.
        """
        capital = current_capital if current_capital is not None else self.capital
        cash_reserve = capital * self.cash_buffer

        # Step 1: Select best Pendle PT pool
        best_pendle = self.select_best_pendle(pendle_pools)

        # Step 2: Check rotation
        rotation_needed = False
        rotation_reason = ""
        if current_pendle_position and best_pendle:
            rotation_needed, rotation_reason = self.should_rotate(
                current_pendle_position, best_pendle
            )

        # Step 3: Compute Pendle allocation size
        pendle_amount = 0.0
        if best_pendle:
            pendle_cap = capital * self.pendle_max_pct
            pendle_amount = min(pendle_cap, capital - cash_reserve)
            pendle_amount = max(0.0, pendle_amount)
            log.info(
                f"v3_pendle_focused: Pendle → {best_pendle['symbol']} "
                f"APY={best_pendle['apy']:.2f}% "
                f"maturity={best_pendle.get('days_to_maturity', '?')}d "
                f"amount=${pendle_amount:,.0f}"
            )
        else:
            log.info("v3_pendle_focused: no eligible Pendle PT pool — T1 only")

        # Step 4: Allocate remaining capital in T1 pools
        remaining_capital = capital - pendle_amount - cash_reserve
        t1_allocations = self._allocate_t1(t1_pools, remaining_capital, capital)

        # Step 5: Compute totals
        t1_total = sum(a["amount_usd"] for a in t1_allocations)
        total_deployed = pendle_amount + t1_total
        cash_actual = capital - total_deployed

        decision = AllocationDecision(
            pendle_pool=best_pendle,
            pendle_amount=pendle_amount,
            t1_allocations=t1_allocations,
            total_deployed=round(total_deployed, 2),
            cash_reserved=round(cash_actual, 2),
            rotation_needed=rotation_needed,
            rotation_reason=rotation_reason,
        )

        log.info(decision.summary())
        return decision

    def select_best_pendle(self, pendle_pools: list[dict]) -> Optional[dict]:
        """
        Select the best Pendle PT pool from the candidate list.

        Criteria:
          1. days_to_maturity > PENDLE_MIN_MATURITY_D (30 days)
          2. apy >= PENDLE_MIN_APY (6%)
          3. Rank by: APY descending (primary), days_to_maturity descending (tie-break)

        Returns the top-ranked pool or None if no eligible pools.
        """
        today = date.today()
        eligible = []

        for pool in pendle_pools:
            apy = pool.get("apy", 0.0)
            dtm = pool.get("days_to_maturity")

            # Compute days_to_maturity if not provided but maturity_date is
            if dtm is None and pool.get("maturity_date"):
                try:
                    mat = date.fromisoformat(pool["maturity_date"])
                    dtm = (mat - today).days
                except (ValueError, TypeError):
                    dtm = None

            if dtm is not None and dtm < PENDLE_MIN_MATURITY_D:
                log.debug(
                    f"  skip {pool.get('symbol', '?')}: "
                    f"days_to_maturity={dtm} < {PENDLE_MIN_MATURITY_D}"
                )
                continue

            if apy < PENDLE_MIN_APY:
                log.debug(
                    f"  skip {pool.get('symbol', '?')}: apy={apy:.2f}% < {PENDLE_MIN_APY:.1f}%"
                )
                continue

            eligible.append({**pool, "days_to_maturity": dtm})

        if not eligible:
            log.info("select_best_pendle: no eligible Pendle PT pools")
            return None

        # Sort: APY desc, then days_to_maturity desc as tie-break
        eligible.sort(
            key=lambda p: (p.get("apy", 0.0), p.get("days_to_maturity") or 0),
            reverse=True,
        )

        best = eligible[0]
        log.info(
            f"select_best_pendle: {best.get('symbol', '?')} "
            f"APY={best.get('apy', 0):.2f}% "
            f"maturity={best.get('days_to_maturity', '?')}d "
            f"({len(eligible)} eligible pools)"
        )
        return best

    def should_rotate(
        self,
        current_position: dict,
        new_pool: dict,
    ) -> tuple[bool, str]:
        """
        Determine if we should rotate from the current Pendle position
        to the new pool.

        Rotation is recommended when ALL of the following are true:
          1. new_pool.apy > current_position.entry_apy + ROTATION_THRESHOLD_PP
          2. new_pool.days_to_maturity > PENDLE_MIN_MATURITY_D
          3. current_position has enough days remaining to justify the switch
             (not within 14 days of maturity — liquidity risk zone)

        Args:
            current_position: Dict of current Pendle position (from engine.py).
                Must contain: entry_apy, days_remaining (or maturity_date).
            new_pool: Candidate Pendle PT pool dict from PendleFetcher.

        Returns:
            (should_rotate: bool, reason: str)
        """
        current_apy = current_position.get("entry_apy", 0.0)
        new_apy = new_pool.get("apy", 0.0)
        new_dtm = new_pool.get("days_to_maturity") or PENDLE_MIN_MATURITY_D

        apy_improvement = new_apy - current_apy

        # Check current position's remaining days
        cur_remaining = current_position.get("days_remaining")
        if cur_remaining is None:
            # Try computing from maturity_date
            mat_str = current_position.get("maturity_date")
            if mat_str:
                try:
                    cur_remaining = (date.fromisoformat(mat_str) - date.today()).days
                except (ValueError, TypeError):
                    cur_remaining = 90  # assume plenty of time if unknown

        # Do not rotate if current position is near maturity (< 14 days)
        near_maturity_threshold = 14
        if cur_remaining is not None and cur_remaining < near_maturity_threshold:
            reason = (
                f"current position only {cur_remaining}d to maturity — "
                f"hold to expiry (no rotation)"
            )
            log.debug(f"should_rotate: NO — {reason}")
            return False, reason

        # Do not rotate if APY improvement is below threshold
        if apy_improvement < self.rotation_threshold:
            reason = (
                f"APY improvement {apy_improvement:+.2f}pp < "
                f"threshold {self.rotation_threshold:.1f}pp — no rotation"
            )
            log.debug(f"should_rotate: NO — {reason}")
            return False, reason

        # Do not rotate if new pool maturity is too close
        if new_dtm < PENDLE_MIN_MATURITY_D:
            reason = (
                f"new pool {new_pool.get('symbol', '?')} only {new_dtm}d to maturity "
                f"— minimum {PENDLE_MIN_MATURITY_D}d required"
            )
            log.debug(f"should_rotate: NO — {reason}")
            return False, reason

        # Rotation approved
        reason = (
            f"new pool {new_pool.get('symbol', '?')} "
            f"APY={new_apy:.2f}% vs current {current_apy:.2f}% "
            f"(improvement {apy_improvement:+.2f}pp ≥ {self.rotation_threshold:.1f}pp threshold)"
        )
        log.info(f"should_rotate: YES — {reason}")
        return True, reason

    # ── Private helpers ───────────────────────────────────────────────────────

    def _allocate_t1(
        self,
        t1_pools: list[dict],
        available_capital: float,
        total_capital: float,
    ) -> list[dict]:
        """
        Allocate available_capital across T1 pools.

        Selects the best-APY T1 pools up to T1_MAX_PCT concentration.
        Stops when capital is exhausted or minimum allocation ($1000) can't be met.

        Returns list of {pool_key, amount_usd, apy, protocol}.
        """
        if available_capital <= 0:
            return []

        # Filter to T1 tier only, sort by APY descending
        t1_eligible = [
            p for p in t1_pools
            if p.get("tier") in ("T1",) and p.get("apy", 0) >= T1_MIN_APY
        ]
        t1_eligible.sort(key=lambda p: p.get("apy", 0.0), reverse=True)

        allocations = []
        remaining = available_capital
        max_per_pool = total_capital * self.t1_max_pct

        for pool in t1_eligible:
            if remaining < 1000.0:
                break

            pool_key = pool.get("pool_key") or pool.get("key") or pool.get("protocol_key", "unknown")
            amount = min(remaining, max_per_pool)
            amount = round(amount, 2)

            if amount < 1000.0:
                continue

            allocations.append({
                "pool_key":   pool_key,
                "amount_usd": amount,
                "apy":        pool.get("apy", 0.0),
                "protocol":   pool.get("protocol", ""),
                "tier":       "T1",
            })
            remaining -= amount

            log.debug(
                f"  T1 alloc: {pool_key} "
                f"${amount:,.0f} @ {pool.get('apy', 0):.2f}%"
            )

        return allocations


# ─── Strategy config (для STRATEGIES registry) ────────────────────────────────

def get_strategy_config() -> dict:
    """
    Return the v3_pendle_focused config dict for the STRATEGIES registry
    in paper_trading/strategies.py.

    Config keys follow the same schema as v1_passive and v2_aggressive.
    Extra keys (pendle_*) are specific to this strategy.
    """
    return {
        "name": "v3 — Pendle-Focused Yield Maximiser",
        "description": (
            "Prioritises Pendle PT fixed-rate positions (up to 20% T2) "
            "to close the APY gap. Selects pools with maturity > 30 days "
            "and best APY. Rotates positions when a 0.5pp+ improvement is "
            "available. Remaining capital deployed in best T1 pools."
        ),
        "config": {
            "target_apy_min":          6.0,    # Pendle min APY gate
            "target_apy_max":          25.0,   # RiskPolicy max (30% absolute)
            "preferred_tiers":         ["T2", "T1"],  # Pendle first, T1 fill
            "max_positions":           9,
            "rebalance_threshold_pct": 0.5,
            "cash_buffer_pct":         0.05,
            # T1 concentration caps (same as v1_passive for safety)
            "max_concentration_t1":    0.40,
            "max_concentration_t2":    0.20,
            # Pendle-specific parameters
            "pendle_max_pct":          0.20,   # max 20% of capital in Pendle PT
            "pendle_min_maturity_days": 30,    # min days-to-maturity for entry
            "pendle_rotation_threshold": 0.5,  # pp improvement required to rotate
            "pendle_min_apy":          6.0,    # min APY for Pendle entry
        },
        # Handler class — importable by engine.py or orchestrator
        "handler_module": "paper_trading.v3_pendle_focused",
        "handler_class":  "V3PendleFocusedStrategy",
    }


# ─── Convenience function ─────────────────────────────────────────────────────

def build_strategy(capital: float = 100_000.0) -> V3PendleFocusedStrategy:
    """Factory function — creates a strategy instance with default config."""
    return V3PendleFocusedStrategy(capital=capital)
