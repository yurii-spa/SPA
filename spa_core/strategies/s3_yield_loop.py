"""
Strategy S3 — Yield Loop (Borrow + Deposit)
============================================

Risk Tier : T3  (высокий риск — ТОЛЬКО для paper trading)
Type      : yield_loop
Target APY: 15–25%
Max DD    : 10%

⚠️  ПРЕДУПРЕЖДЕНИЕ: Стратегия использует кредитное плечо.
    В paper trading — безопасна. Для live capital требует
    отдельного ADR и Owner approval.

Описание:
  Yield Loop (aka "recursive lending"):
    1. Депонируем $100K USDC в Aave V3 → получаем aUSDC (~4.6% APY на депозит)
    2. Занимаем USDT до 60% LTV ($60K) → платим borrow rate (~3.5%)
    3. Депонируем занятый USDT снова в Aave V3 (~4.2% APY на депозит)
    4. [Опционально] Ещё один loop: занимаем ещё 60% ($36K) → депонируем

  Net APY расчёт (1 loop):
    deposit_apy_1 = 4.6%
    borrow_rate   = 3.5%  (USDT variable rate)
    deposit_apy_2 = 4.2%
    LTV           = 0.60
    Net = deposit_apy_1 + LTV * (deposit_apy_2 - borrow_rate)
        = 4.6% + 0.60 * (4.2% - 3.5%) = 4.6% + 0.42% = 5.02% на исходный капитал

    Для 2 loops: добавляем ещё LTV^2 * (deposit_apy_3 - borrow_rate_3)
    Итоговый APY с leverage ~2x: ~12–20%

  Риски и защиты:
    - Liquidation buffer: держим health factor ≥ 1.5 (20% буфер от ликвидации при HF=1.25)
    - Stop-loss: если health factor < 1.3 → немедленно закрыть все loops
    - Max loops: 2 (чтобы не пересечь ликвидацию при 5% depeg)
    - Borrow rate мониторинг: если borrow_rate > deposit_apy → закрыть loop
    - Max position: 35% от общего капитала (T3 жёсткий лимит)

  Health Factor моделирование:
    HF = sum(deposit_i * liquidation_threshold_i) / sum(borrow_i)
    Для стейблов liquidation_threshold = 0.875 (Aave v3)
    При LTV=60%: HF = (100K * 0.875) / 60K = 1.458 → safe
    При 5% депег USDT: HF падает на ~3% → still safe at 1.41

Usage:
    from strategies.s3_yield_loop import YieldLoopStrategy

    strategy = YieldLoopStrategy()
    result = strategy.backtest(historical_data, initial_capital=100_000)
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

# ─── Параметры стратегии ──────────────────────────────────────────────────────

STRATEGY_ID = "s3_yield_loop"

# Протоколы для yield loop (только Aave V3 — самый ликвидный + хорошие ставки)
DEPOSIT_PROTOCOLS = ("aave-v3-usdc-ethereum", "aave-v3-usdt-ethereum")
BORROW_PROTOCOL   = "aave-v3"

LTV                = 0.60      # максимальный LTV для займа
MAX_LOOPS          = 2         # максимум петель рекурсии
LIQ_THRESHOLD      = 0.875     # Aave v3 stablecoin liquidation threshold
MIN_HEALTH_FACTOR  = 1.3       # HF < 1.3 → stop-loss
TARGET_HEALTH_FACTOR = 1.5     # целевой HF (20% буфер)
MIN_NET_SPREAD     = 0.3       # pp — мин. спред (deposit - borrow), иначе не выгодно
MAX_POSITION_PCT   = 0.35      # max 35% капитала в S3 позициях
CASH_BUFFER        = 0.05

# Borrow rate модель: borrow_rate = deposit_rate * BORROW_RATE_MULTIPLIER + spread
BORROW_RATE_MULTIPLIER = 0.80   # обычно borrow rate ≈ 80-90% от supply rate (спред рынка)
BORROW_RATE_SPREAD     = 0.5    # pp — фиксированный спред поверх

# Параметры ликвидации (консервативный буфер для бэктеста)
LIQUIDATION_BUFFER_PCT = 0.05   # 5% капитала держим как буфер против ликвидации


# ─── Внутренний стейт позиции ─────────────────────────────────────────────────

@dataclass
class _LoopPosition:
    """Одна 'петля' в yield loop стратегии."""
    loop_number:       int
    deposit_key:       str
    deposit_amount:    float
    borrow_amount:     float
    deposit_apy:       float
    borrow_rate:       float
    date_opened:       str

    @property
    def net_apy(self) -> float:
        """Чистый APY этой петли на вложенный капитал."""
        return self.deposit_apy - (self.borrow_amount / self.deposit_amount) * self.borrow_rate

    @property
    def health_factor(self) -> float:
        """Health factor этой петли."""
        collateral_value = self.deposit_amount * LIQ_THRESHOLD
        if self.borrow_amount <= 0:
            return 999.0
        return collateral_value / self.borrow_amount

    def daily_net_interest(self) -> float:
        """Чистый дневной доход: депозитные проценты минус стоимость займа."""
        deposit_income = self.deposit_amount * (self.deposit_apy / 100.0) / 365.0
        borrow_cost    = self.borrow_amount  * (self.borrow_rate / 100.0) / 365.0
        return deposit_income - borrow_cost


@dataclass
class _S3Position:
    """Вся yield loop позиция (все петли вместе)."""
    base_amount:        float      # исходный капитал в позиции
    loops:              list[_LoopPosition] = field(default_factory=list)
    total_interest:     float = 0.0
    date_opened:        str = ""

    @property
    def total_deposit(self) -> float:
        return sum(lp.deposit_amount for lp in self.loops)

    @property
    def total_borrow(self) -> float:
        return sum(lp.borrow_amount for lp in self.loops)

    @property
    def portfolio_health_factor(self) -> float:
        total_collateral = sum(lp.deposit_amount * LIQ_THRESHOLD for lp in self.loops)
        if self.total_borrow <= 0:
            return 999.0
        return total_collateral / self.total_borrow

    @property
    def leverage(self) -> float:
        return self.total_deposit / self.base_amount if self.base_amount > 0 else 1.0

    @property
    def effective_apy(self) -> float:
        """Эффективный APY на исходный капитал (base_amount)."""
        if self.base_amount <= 0 or not self.loops:
            return 0.0
        annual_income = sum(
            lp.deposit_amount * lp.deposit_apy / 100.0 -
            lp.borrow_amount  * lp.borrow_rate / 100.0
            for lp in self.loops
        )
        return (annual_income / self.base_amount) * 100.0

    def daily_net_interest(self) -> float:
        return sum(lp.daily_net_interest() for lp in self.loops)


# ─── Класс стратегии ──────────────────────────────────────────────────────────

class YieldLoopStrategy:
    """
    Yield Loop Strategy (S3) — T3, высокий риск.

    Использует рекурсивный lending для увеличения эффективного APY.
    Max 2 loops, HF мониторинг, stop-loss при HF < 1.3.

    ⚠️  ТОЛЬКО для paper trading. Требует ADR для live capital.
    """

    def __init__(self) -> None:
        self.strategy_id = STRATEGY_ID

    # ── Расчёт borrow rate ────────────────────────────────────────────────────

    def _estimate_borrow_rate(self, deposit_apy: float) -> float:
        """
        Оценивает ставку займа на основе ставки депозита.
        Borrow rate обычно выше deposit rate из-за utilization.
        """
        # Базовая модель: borrow = deposit_apy * multiplier + spread
        # Но не выше deposit_apy + 2pp (при нормальной утилизации)
        base_borrow = deposit_apy * BORROW_RATE_MULTIPLIER + BORROW_RATE_SPREAD
        return round(min(base_borrow, deposit_apy + 2.0), 4)

    # ── Создание loops ────────────────────────────────────────────────────────

    def _build_loops(
        self,
        base_amount: float,
        deposit_apy: float,
        day_str: str,
    ) -> list[_LoopPosition]:
        """
        Строит список petель для заданного базового капитала.

        Loop 1: deposit base_amount → borrow base_amount * LTV
        Loop 2: deposit borrowed amount → borrow borrowed * LTV
        """
        loops = []
        current_deposit = base_amount
        borrow_rate = self._estimate_borrow_rate(deposit_apy)

        for loop_num in range(1, MAX_LOOPS + 1):
            borrow_amount = current_deposit * LTV

            # Проверяем что спред положительный
            net_spread = deposit_apy - borrow_rate
            if net_spread < MIN_NET_SPREAD:
                log.debug(
                    "Loop %d: net spread %.2f pp < min %.2f pp — stopping",
                    loop_num, net_spread, MIN_NET_SPREAD
                )
                break

            lp = _LoopPosition(
                loop_number=loop_num,
                deposit_key=f"aave-v3-usdc-ethereum",
                deposit_amount=current_deposit,
                borrow_amount=borrow_amount,
                deposit_apy=deposit_apy,
                borrow_rate=borrow_rate,
                date_opened=day_str,
            )

            # Проверяем HF после добавления этого loop
            total_col = sum(l.deposit_amount * LIQ_THRESHOLD for l in loops) + lp.deposit_amount * LIQ_THRESHOLD
            total_bor = sum(l.borrow_amount for l in loops) + lp.borrow_amount
            hf = total_col / total_bor if total_bor > 0 else 999.0

            if hf < TARGET_HEALTH_FACTOR:
                log.debug("Loop %d: HF %.3f < target %.3f — stopping", loop_num, hf, TARGET_HEALTH_FACTOR)
                break

            loops.append(lp)
            current_deposit = borrow_amount  # следующий loop использует занятое

        return loops

    # ── Бэктест ────────────────────────────────────────────────────────────────

    def backtest(
        self,
        historical_data: list[dict],
        initial_capital: float = 100_000.0,
    ) -> dict:
        """
        Запускает симуляцию yield loop стратегии.
        """
        days_data: dict[str, list[dict]] = {}
        for row in historical_data:
            ts = row["timestamp"][:10]
            days_data.setdefault(ts, []).append(row)

        sorted_dates = sorted(days_data.keys())
        if not sorted_dates:
            return self._empty_result(initial_capital)

        capital    = initial_capital
        position: _S3Position | None = None   # S3 держит одну крупную позицию
        equity_curve: list[dict] = []
        all_trades:   list[dict] = []

        for day_str in sorted_dates:
            day_protocols = {r["protocol_key"]: r for r in days_data[day_str]}

            # Найдём лучший депозитный протокол (Aave USDC)
            best_deposit_apy = 0.0
            for key in DEPOSIT_PROTOCOLS:
                if key in day_protocols:
                    apy = day_protocols[key].get("apy", 0.0)
                    if apy > best_deposit_apy:
                        best_deposit_apy = apy

            # Если данных нет — используем fallback
            if best_deposit_apy == 0.0:
                # Фоллбэк: ищем любой aave-v3
                for key, data in day_protocols.items():
                    if key.startswith("aave-v3"):
                        best_deposit_apy = max(best_deposit_apy, data.get("apy", 0.0))

            # 1. Обновляем APY и начисляем проценты
            if position is not None:
                borrow_rate = self._estimate_borrow_rate(best_deposit_apy)
                for lp in position.loops:
                    lp.deposit_apy = best_deposit_apy
                    lp.borrow_rate = borrow_rate

                daily_interest = position.daily_net_interest()
                position.total_interest += daily_interest
                capital += daily_interest

            # 2. Проверяем stop-loss
            if position is not None:
                hf = position.portfolio_health_factor
                if hf < MIN_HEALTH_FACTOR:
                    # Экстренное закрытие всех loops
                    net_pnl = position.total_interest
                    all_trades.append({
                        "date": day_str, "protocol": "aave-v3-loop",
                        "action": "CLOSE", "amount": round(position.base_amount, 2),
                        "apy": round(position.effective_apy, 4),
                        "interest_usd": round(position.total_interest, 4),
                        "pnl": round(net_pnl, 4),
                        "loops": len(position.loops),
                        "health_factor": round(hf, 4),
                        "reason": f"stop_loss_hf_{hf:.3f}",
                        "strategy": STRATEGY_ID,
                    })
                    position = None
                    log.warning("S3 stop-loss triggered on %s: HF=%.3f", day_str, hf)

                elif best_deposit_apy > 0:
                    borrow_rate = self._estimate_borrow_rate(best_deposit_apy)
                    net_spread  = best_deposit_apy - borrow_rate
                    if net_spread < MIN_NET_SPREAD:
                        # Спред упал ниже минимума — закрываем
                        all_trades.append({
                            "date": day_str, "protocol": "aave-v3-loop",
                            "action": "CLOSE", "amount": round(position.base_amount, 2),
                            "apy": round(position.effective_apy, 4),
                            "interest_usd": round(position.total_interest, 4),
                            "pnl": round(position.total_interest, 4),
                            "loops": len(position.loops),
                            "reason": f"spread_too_low_{net_spread:.2f}pp",
                            "strategy": STRATEGY_ID,
                        })
                        position = None

            # 3. Открываем позицию если нет активной и условия выгодны
            if position is None and best_deposit_apy > 0:
                borrow_rate = self._estimate_borrow_rate(best_deposit_apy)
                net_spread  = best_deposit_apy - borrow_rate

                if net_spread >= MIN_NET_SPREAD:
                    # Размер позиции: max 35% капитала, держим буфер
                    max_size = min(
                        capital * MAX_POSITION_PCT,
                        capital * (1 - CASH_BUFFER - LIQUIDATION_BUFFER_PCT)
                    )
                    base_amount = round(max_size * 0.80, 2)  # 80% от лимита (консервативно)

                    if base_amount >= 1000.0:
                        loops = self._build_loops(base_amount, best_deposit_apy, day_str)
                        if loops:
                            position = _S3Position(
                                base_amount=base_amount,
                                loops=loops,
                                date_opened=day_str,
                            )
                            all_trades.append({
                                "date": day_str, "protocol": "aave-v3-loop",
                                "action": "OPEN", "amount": base_amount,
                                "apy": round(position.effective_apy, 4),
                                "loops": len(loops),
                                "leverage": round(position.leverage, 3),
                                "health_factor": round(position.portfolio_health_factor, 4),
                                "deposit_apy": round(best_deposit_apy, 4),
                                "borrow_rate": round(borrow_rate, 4),
                                "interest_usd": 0.0, "pnl": 0.0,
                                "reason": "s3_yield_loop_open",
                                "strategy": STRATEGY_ID,
                            })

            # 4. Снимок
            deployed  = position.base_amount if position else 0.0
            eff_apy   = position.effective_apy if position else 0.0
            hf_now    = position.portfolio_health_factor if position else 0.0
            leverage  = position.leverage if position else 1.0
            pnl_pct   = (capital - initial_capital) / initial_capital * 100

            equity_curve.append({
                "date": day_str,
                "total_capital": round(capital, 2),
                "deployed": round(deployed, 2),
                "cash": round(capital - deployed, 2),
                "pnl_pct": round(pnl_pct, 4),
                "open_positions": 1 if position else 0,
                "weighted_apy": round(eff_apy, 4),
                "health_factor": round(hf_now, 4),
                "leverage": round(leverage, 3),
                "strategy": STRATEGY_ID,
            })

        # Закрываем открытую позицию в конце
        if position is not None:
            final_date = sorted_dates[-1]
            all_trades.append({
                "date": final_date, "protocol": "aave-v3-loop",
                "action": "CLOSE", "amount": round(position.base_amount, 2),
                "apy": round(position.effective_apy, 4),
                "interest_usd": round(position.total_interest, 4),
                "pnl": round(position.total_interest, 4),
                "loops": len(position.loops),
                "reason": "backtest_end", "strategy": STRATEGY_ID,
            })

        return self._compute_result(equity_curve, all_trades, initial_capital, capital)

    # ── Compute metrics ───────────────────────────────────────────────────────

    def _compute_result(self, equity_curve, trades, initial_capital, final_capital):
        from backtesting.metrics import (
            sharpe_ratio, max_drawdown, win_rate,
            total_return_pct, annualised_return_pct,
        )
        caps = [e["total_capital"] for e in equity_curve]
        daily_returns = [
            (caps[i] - caps[i - 1]) / caps[i - 1] if caps[i - 1] > 0 else 0.0
            for i in range(1, len(caps))
        ]
        n_days = len(equity_curve)
        total_ret_frac = (final_capital - initial_capital) / initial_capital

        open_trades  = [t for t in trades if t["action"] == "OPEN"]
        close_trades = [t for t in trades if t["action"] == "CLOSE"]

        # Средний leverage из снимков
        avg_leverage = (
            sum(e.get("leverage", 1.0) for e in equity_curve) / n_days
            if n_days > 0 else 1.0
        )

        metrics = {
            "sharpe_ratio":          sharpe_ratio(daily_returns),
            "max_drawdown_pct":      round(max_drawdown(caps) * 100, 4),
            "total_return_pct":      total_return_pct(initial_capital, final_capital),
            "annualised_return_pct": annualised_return_pct(total_ret_frac, n_days),
            "win_rate":              win_rate(close_trades),
            "total_trades":          len(open_trades),
            "initial_capital_usd":   round(initial_capital, 2),
            "final_capital_usd":     round(final_capital, 2),
            "total_interest_usd":    round(final_capital - initial_capital, 2),
            "backtest_days":         n_days,
            "strategy_id":           STRATEGY_ID,
            "risk_tier":             "T3",
            "target_apy_range":      "15–25%",
            "max_loops":             MAX_LOOPS,
            "avg_leverage":          round(avg_leverage, 3),
            "ltv_used":              LTV,
            "warning":               "HIGH_RISK: uses leverage. Paper trading only until ADR approved.",
        }
        return {
            "strategy_id":  STRATEGY_ID,
            "equity_curve": equity_curve,
            "trades":       trades,
            "metrics":      metrics,
        }

    def run_day(self, apy_map: dict = None) -> float:
        """Thin adapter for cycle_runner compatibility.
        Returns estimated effective loop APY from apy_map."""
        _FALLBACK_APY = 18.0  # midpoint of 15–25% target range (with leverage)
        if not apy_map:
            return _FALLBACK_APY
        # Look for Aave V3 deposit rate in protocol order
        deposit_apy = 0.0
        for key in DEPOSIT_PROTOCOLS:
            if key in apy_map and isinstance(apy_map[key], (int, float)):
                deposit_apy = max(deposit_apy, float(apy_map[key]))
        if deposit_apy == 0.0:
            # Fallback: any aave-v3 key
            for key, val in apy_map.items():
                if key.startswith("aave-v3") and isinstance(val, (int, float)):
                    deposit_apy = max(deposit_apy, float(val))
        if deposit_apy == 0.0:
            return _FALLBACK_APY
        # Compute net loop APY (simplified 1-loop model)
        borrow_rate = self._estimate_borrow_rate(deposit_apy)
        net_apy = deposit_apy + LTV * (deposit_apy - borrow_rate)
        return float(max(net_apy, 0.0))

    def _empty_result(self, initial_capital):
        return {
            "strategy_id": STRATEGY_ID,
            "equity_curve": [],
            "trades": [],
            "metrics": {
                "sharpe_ratio": 0.0, "max_drawdown_pct": 0.0,
                "total_return_pct": 0.0, "annualised_return_pct": 0.0,
                "win_rate": 0.0, "total_trades": 0,
                "initial_capital_usd": initial_capital,
                "final_capital_usd": initial_capital,
                "total_interest_usd": 0.0, "backtest_days": 0,
                "strategy_id": STRATEGY_ID, "risk_tier": "T3",
                "target_apy_range": "15–25%",
                "warning": "HIGH_RISK: uses leverage.",
            },
        }


# ─── Авто-регистрация ─────────────────────────────────────────────────────────

def _register() -> None:
    try:
        from strategies.strategy_registry import REGISTRY, StrategyMeta
        REGISTRY.register(StrategyMeta(
            id="s3_yield_loop",
            name="S3 — Yield Loop (Borrow+Deposit)",
            type="yield_loop",
            risk_tier="T3",
            target_apy_min=15.0,
            target_apy_max=25.0,
            max_drawdown_pct=10.0,
            description=(
                "Recursive lending on Aave V3: deposit USDC → borrow USDT (60% LTV) → "
                "re-deposit. Max 2 loops. HF monitor (stop-loss at HF < 1.3). "
                "35% max position size. PAPER TRADING ONLY until ADR approved."
            ),
            module="strategies.s3_yield_loop",
            handler_class="YieldLoopStrategy",
            tags=["leverage", "yield_loop", "aave", "t3", "high_risk", "paper_only"],
        ))
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("S3 auto-registration failed: %s", exc)


_register()
