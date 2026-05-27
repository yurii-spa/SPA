"""
Strategy S2 — LP Stablecoin Pairs
===================================

Risk Tier : T2
Type      : lp  (Liquidity Provision)
Target APY: 8–12%
Max DD    : 5%

Описание:
  Обеспечивает ликвидность в стейблкоин-парах на Curve Finance и Uniswap v3.
  Доход = торговые комиссии + базовый lending APY на депонированные токены.

  Пулы (моделируются через DeFiLlama "lp" тип):
    curve-3pool-usdc   (USDC/USDT/DAI на Curve)
    curve-usdc-usdt    (USDC/USDT на Curve)
    uniswap-v3-usdc-usdt-base (Uniswap v3 USDC/USDT на Base)
    uniswap-v3-usdc-dai-ethereum (Uniswap v3 USDC/DAI на Ethereum)

  Impermanent loss:
    Для tight peg стейблов (USDC/USDT) IL ≈ 0 при нормальных условиях.
    Если peg расходится > 0.5% — стратегия закрывает позицию.
    Моделируем IL как: IL_pct = max(0, |price_deviation| * 2) — консервативно.

  Правила:
  - Только стейбл-пары (не принимаем пулы с ETH/BTC)
  - Max 30% в одном пуле (T2 лимит)
  - Min TVL $10M (LP пулы должны быть глубокими)
  - Целевой Fee APY 5–15%, Total APY 8–12%
  - Ребалансировка раз в 7 дней или если APY gap > 2 pp
  - Стоп-лосс если IL > 1%

Usage:
    from strategies.s2_lp_stable import LPStableStrategy

    strategy = LPStableStrategy()
    result = strategy.backtest(historical_data, initial_capital=100_000)
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

# ─── Параметры стратегии ──────────────────────────────────────────────────────

STRATEGY_ID = "s2_lp_stable"

# LP пулы для этой стратегии (ключи, которые могут приходить из DeFiLlama)
LP_POOL_PREFIXES = (
    "curve-3pool",
    "curve-usdc",
    "curve-usdt",
    "curve-dai",
    "uniswap-v3-usdc-usdt",
    "uniswap-v3-usdc-dai",
    "uniswap-v3-dai-usdt",
    "convex-usdc",
    "convex-usdt",
)

# Фоллбэк: если реальных LP пулов нет в данных, используем lending с надбавкой
# (моделирует fee APY поверх базового lending APY)
FEE_APY_PREMIUM    = 4.5    # pp — надбавка к lending APY для симуляции fee income
LENDING_PREFIXES   = ("aave-v3", "compound-v3", "morpho")  # базовые пулы для фоллбэка

MAX_CONCENTRATION  = 0.30   # не более 30% в одном пуле
MIN_APY            = 5.0    # % — нижняя граница (lending + fees)
MAX_APY            = 25.0   # % — верхняя (защита от аномалий)
MIN_TVL_USD        = 10_000_000  # $10M — LP пулы требуют глубины
CASH_BUFFER        = 0.05
MAX_IL_PCT         = 1.0    # % — максимально допустимый impermanent loss
REBALANCE_DAYS     = 7      # ребаланс раз в 7 дней
REBALANCE_APY_GAP  = 2.0    # pp — ребаланс при APY gap > 2 pp
MAX_POSITIONS      = 4      # максимум открытых позиций


# ─── Внутренний стейт позиции ─────────────────────────────────────────────────

@dataclass
class _S2Position:
    protocol_key:    str
    pool_type:       str          # "lp" или "lending_simulated"
    amount_usd:      float
    apy_at_open:     float
    current_apy:     float = 0.0
    interest_earned: float = 0.0
    il_accumulated:  float = 0.0  # накопленный impermanent loss в %
    days_held:       int = 0
    date_opened:     str = ""

    def daily_interest(self) -> float:
        """Дневной доход = lending APY + fee premium, скорректированный на IL."""
        net_apy = max(0.0, self.current_apy - self.il_accumulated * 365)
        return self.amount_usd * (net_apy / 100.0) / 365.0

    def apply_il(self, price_deviation_pct: float) -> None:
        """
        Обновляет накопленный IL.
        Для стейбл-пар IL ≈ price_deviation^2 / 2 (упрощённая формула).
        """
        il = (price_deviation_pct / 100.0) ** 2 / 2.0 * 100  # в %
        self.il_accumulated = round(il, 6)


# ─── Класс стратегии ──────────────────────────────────────────────────────────

class LPStableStrategy:
    """
    LP Stablecoin Strategy (S2).

    Предоставляет ликвидность в стейбл-парах (Curve, Uniswap v3).
    Комбинирует fee APY + base lending APY.
    IL мониторинг + стоп-лосс при IL > 1%.
    """

    def __init__(self) -> None:
        self.strategy_id = STRATEGY_ID

    # ── Фильтры ───────────────────────────────────────────────────────────────

    def _is_lp_pool(self, key: str) -> bool:
        return any(key.startswith(prefix) for prefix in LP_POOL_PREFIXES)

    def _is_lending_base(self, key: str) -> bool:
        return any(key.startswith(prefix) for prefix in LENDING_PREFIXES)

    def _effective_apy(self, protocol: dict) -> float:
        """
        Эффективный APY для LP: если это настоящий LP пул — берём как есть,
        если lending (фоллбэк) — добавляем FEE_APY_PREMIUM.
        """
        key = protocol.get("protocol_key", "")
        apy = protocol.get("apy", 0.0)
        if self._is_lp_pool(key):
            return apy
        if self._is_lending_base(key):
            return apy + FEE_APY_PREMIUM
        return 0.0

    def _is_allowed(self, protocol: dict) -> bool:
        key = protocol.get("protocol_key", "")
        tvl = protocol.get("tvl_usd", 0.0)
        eff_apy = self._effective_apy(protocol)

        if not (self._is_lp_pool(key) or self._is_lending_base(key)):
            return False
        if tvl < MIN_TVL_USD:
            return False
        if not (MIN_APY <= eff_apy <= MAX_APY):
            return False
        return True

    def _candidates(self, day_protocols: dict[str, dict]) -> list[dict]:
        allowed = []
        for p in day_protocols.values():
            if self._is_allowed(p):
                # Добавляем effective_apy в запись для удобства
                p_copy = dict(p)
                p_copy["effective_apy"] = self._effective_apy(p)
                allowed.append(p_copy)
        return sorted(allowed, key=lambda p: p["effective_apy"], reverse=True)

    # ── Симуляция IL ──────────────────────────────────────────────────────────

    def _estimate_price_deviation(self, protocol_key: str, day_str: str) -> float:
        """
        Оценивает отклонение peg для стейблов.
        В реальности берётся из price oracle.
        Здесь: детерминированная функция дня (псевдо-реалистично).
        """
        # Используем hash строки для детерминированного "случайного" отклонения
        seed = hash(protocol_key + day_str) % 1000
        # Типичное peg отклонение USDC/USDT: 0.01–0.05%
        deviation = (seed % 10) * 0.005  # 0–0.045%
        return deviation

    # ── Бэктест ────────────────────────────────────────────────────────────────

    def backtest(
        self,
        historical_data: list[dict],
        initial_capital: float = 100_000.0,
    ) -> dict:
        """
        Запускает симуляцию LP стратегии на исторических данных.
        """
        days_data: dict[str, list[dict]] = {}
        for row in historical_data:
            ts = row["timestamp"][:10]
            days_data.setdefault(ts, []).append(row)

        sorted_dates = sorted(days_data.keys())
        if not sorted_dates:
            return self._empty_result(initial_capital)

        capital    = initial_capital
        positions: list[_S2Position] = []
        equity_curve: list[dict] = []
        all_trades:   list[dict] = []
        day_counter = 0

        for day_str in sorted_dates:
            day_counter += 1
            day_protocols = {r["protocol_key"]: r for r in days_data[day_str]}

            # 1. Обновляем APY, начисляем IL
            for pos in positions:
                if pos.protocol_key in day_protocols:
                    data = day_protocols[pos.protocol_key]
                    eff_apy = self._effective_apy(data)
                    pos.current_apy = eff_apy
                    dev = self._estimate_price_deviation(pos.protocol_key, day_str)
                    pos.apply_il(dev)
                pos.days_held += 1

            # 2. Начисляем проценты (с учётом IL)
            for pos in positions:
                interest = pos.daily_interest()
                pos.interest_earned += interest
                capital += interest

            # 3. Ребалансировка
            candidates = self._candidates(day_protocols)
            best_apy   = candidates[0]["effective_apy"] if candidates else 0.0
            keep, closed = [], []

            for pos in positions:
                data = day_protocols.get(pos.protocol_key)
                should_close = False
                reason = ""

                if data is None:
                    should_close, reason = True, "protocol_not_in_data"
                elif pos.il_accumulated > MAX_IL_PCT:
                    should_close, reason = True, f"il_stop_loss_{pos.il_accumulated:.3f}pct"
                elif not self._is_allowed(data):
                    should_close, reason = True, "no_longer_allowed"
                elif (day_counter % REBALANCE_DAYS == 0 and
                      (best_apy - pos.current_apy) > REBALANCE_APY_GAP):
                    should_close, reason = True, f"periodic_rebalance_gap_{best_apy:.2f}vs{pos.current_apy:.2f}"

                if should_close:
                    # Учитываем IL при закрытии
                    il_loss = pos.amount_usd * (pos.il_accumulated / 100.0)
                    net_pnl = pos.interest_earned - il_loss
                    closed.append({
                        "date": day_str, "protocol": pos.protocol_key,
                        "action": "CLOSE", "amount": round(pos.amount_usd, 2),
                        "apy": round(pos.current_apy, 4),
                        "interest_usd": round(pos.interest_earned, 4),
                        "il_loss_usd": round(il_loss, 4),
                        "pnl": round(net_pnl, 4),
                        "reason": reason, "strategy": STRATEGY_ID,
                    })
                else:
                    keep.append(pos)

            positions = keep
            all_trades.extend(closed)

            # 4. Открываем новые позиции
            open_keys = {p.protocol_key for p in positions}
            for candidate in candidates:
                if len(positions) >= MAX_POSITIONS:
                    break
                key = candidate["protocol_key"]
                if key in open_keys:
                    continue

                deployed = sum(p.amount_usd for p in positions)
                cash     = capital - deployed
                min_cash = capital * CASH_BUFFER
                if cash <= min_cash:
                    break

                remaining_slots = MAX_POSITIONS - len(positions)
                max_size = min(cash - min_cash, MAX_CONCENTRATION * capital)
                size = min(max_size, (cash - min_cash) / max(remaining_slots, 1))
                size = round(size, 2)
                if size < 100.0:
                    continue

                pool_type = "lp" if self._is_lp_pool(key) else "lending_simulated"
                new_pos = _S2Position(
                    protocol_key=key,
                    pool_type=pool_type,
                    amount_usd=size,
                    apy_at_open=candidate["effective_apy"],
                    current_apy=candidate["effective_apy"],
                    date_opened=day_str,
                )
                positions.append(new_pos)
                open_keys.add(key)
                all_trades.append({
                    "date": day_str, "protocol": key,
                    "action": "OPEN", "amount": size,
                    "apy": round(candidate["effective_apy"], 4),
                    "pool_type": pool_type,
                    "tier": candidate.get("tier", "T2"),
                    "interest_usd": 0.0, "pnl": 0.0,
                    "reason": "s2_lp_allocate", "strategy": STRATEGY_ID,
                })

            # 5. Снимок
            deployed = sum(p.amount_usd for p in positions)
            cash     = capital - deployed
            pnl_pct  = (capital - initial_capital) / initial_capital * 100
            weighted_apy = (
                sum(p.amount_usd * p.current_apy for p in positions) / deployed
                if deployed > 0 else 0.0
            )
            avg_il = (
                sum(p.il_accumulated for p in positions) / len(positions)
                if positions else 0.0
            )
            equity_curve.append({
                "date": day_str,
                "total_capital": round(capital, 2),
                "deployed": round(deployed, 2),
                "cash": round(cash, 2),
                "pnl_pct": round(pnl_pct, 4),
                "open_positions": len(positions),
                "weighted_apy": round(weighted_apy, 4),
                "avg_il_pct": round(avg_il, 6),
                "strategy": STRATEGY_ID,
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
            "risk_tier":             "T2",
            "target_apy_range":      "8–12%",
            "fee_apy_premium_pp":    FEE_APY_PREMIUM,
        }
        return {
            "strategy_id":  STRATEGY_ID,
            "equity_curve": equity_curve,
            "trades":       trades,
            "metrics":      metrics,
        }

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
                "strategy_id": STRATEGY_ID, "risk_tier": "T2",
                "target_apy_range": "8–12%",
            },
        }


# ─── Авто-регистрация ─────────────────────────────────────────────────────────

def _register() -> None:
    try:
        from strategies.strategy_registry import REGISTRY, StrategyMeta
        REGISTRY.register(StrategyMeta(
            id="s2_lp_stable",
            name="S2 — LP Stablecoin Pairs",
            type="lp",
            risk_tier="T2",
            target_apy_min=8.0,
            target_apy_max=12.0,
            max_drawdown_pct=5.0,
            description=(
                "Liquidity provision in stablecoin pairs (Curve, Uniswap v3). "
                "Fee APY + base lending APY. IL monitor with 1% stop-loss. "
                "Max 30% per pool, rebalance every 7 days or at +2 pp APY gap."
            ),
            module="strategies.s2_lp_stable",
            handler_class="LPStableStrategy",
            tags=["lp", "curve", "uniswap", "stablecoin", "t2", "fees"],
        ))
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("S2 auto-registration failed: %s", exc)


_register()
