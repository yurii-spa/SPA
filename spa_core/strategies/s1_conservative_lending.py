"""
Strategy S1 — Conservative Lending
====================================

Risk Tier : T1
Type      : lending
Target APY: 4–6%
Max DD    : 2%

Описание:
  Распределяет капитал только в топ-5 lending протоколов по TVL из белого списка:
  Aave V3, Compound V3, Morpho, Sky/sUSDS (когда активен), Yearn V3.

  Правила:
  - Принимает только протоколы с tier="T1" (плюс Yearn как "stable T2")
  - Максимум 40% в одном протоколе
  - Минимальный TVL $5M
  - APY должен быть в диапазоне 1–10%
  - Ребалансировка если APY gap между лучшим и текущим > 1 pp
  - Всегда держит 5% cash buffer

Для бэктеста:
  Метод backtest(historical_data, initial_capital) возвращает список дневных
  snapshot'ов в том же формате, что BacktestEngine.

Usage:
    from strategies.s1_conservative_lending import ConservativeLendingStrategy

    strategy = ConservativeLendingStrategy()
    result = strategy.backtest(historical_data, initial_capital=100_000)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger(__name__)

# ─── Параметры стратегии ──────────────────────────────────────────────────────

STRATEGY_ID = "s1_conservative_lending"

# Протоколы, разрешённые для S1 (только lending T1 + Yearn как stable T2)
ALLOWED_PROTOCOL_PREFIXES = (
    "aave-v3",
    "compound-v3",
    "morpho",
    "sky-susds",
    "yearn-v3",
)

MAX_CONCENTRATION   = 0.40   # не более 40% в одном протоколе
MIN_APY             = 1.0    # % — нижняя граница
MAX_APY             = 10.0   # % — верхняя граница
MIN_TVL_USD         = 5_000_000
CASH_BUFFER         = 0.05   # 5% наличными
REBALANCE_THRESHOLD = 1.0    # pp — ребаланс, если лучший APY выше текущего на 1 pp
MAX_POSITIONS       = 5      # максимум открытых позиций


# ─── Внутренний стейт позиции ─────────────────────────────────────────────────

@dataclass
class _S1Position:
    protocol_key:     str
    amount_usd:       float
    apy_at_open:      float
    current_apy:      float = 0.0
    interest_earned:  float = 0.0

    def daily_interest(self) -> float:
        return self.amount_usd * (self.current_apy / 100.0) / 365.0

    def effective_weight(self, total_capital: float) -> float:
        return self.amount_usd / total_capital if total_capital > 0 else 0.0


# ─── Класс стратегии ──────────────────────────────────────────────────────────

class ConservativeLendingStrategy:
    """
    Conservative T1 Lending Strategy (S1).

    Только топ-5 lending протоколов по TVL.
    Ребалансировка при APY gap > 1 pp.
    Max concentration 40%, cash buffer 5%.
    """

    def __init__(self) -> None:
        self.strategy_id = STRATEGY_ID

    # ── Фильтры ───────────────────────────────────────────────────────────────

    def _is_allowed(self, protocol: dict) -> bool:
        """Проверяет, разрешён ли протокол для этой стратегии."""
        key = protocol.get("protocol_key", "")
        apy = protocol.get("apy", 0.0)
        tvl = protocol.get("tvl_usd", 0.0)

        if not any(key.startswith(prefix) for prefix in ALLOWED_PROTOCOL_PREFIXES):
            return False
        if not (MIN_APY <= apy <= MAX_APY):
            return False
        if tvl < MIN_TVL_USD:
            return False
        return True

    def _candidates(self, day_protocols: dict[str, dict]) -> list[dict]:
        """
        Возвращает кандидатов для открытия позиций,
        отсортированных по APY убыванию (топ-5 по TVL из разрешённых).
        """
        allowed = [p for p in day_protocols.values() if self._is_allowed(p)]
        # Сортируем по TVL убыванию, берём топ-5 по TVL...
        by_tvl = sorted(allowed, key=lambda p: p.get("tvl_usd", 0), reverse=True)[:5]
        # ...затем сортируем по APY для выбора лучших
        return sorted(by_tvl, key=lambda p: p.get("apy", 0), reverse=True)

    # ── Бэктест ────────────────────────────────────────────────────────────────

    def backtest(
        self,
        historical_data: list[dict],
        initial_capital: float = 100_000.0,
    ) -> dict:
        """
        Запускает симуляцию стратегии на исторических данных.

        Args:
            historical_data: список записей [{timestamp, protocol_key, apy, tvl_usd, tier}, ...]
            initial_capital: начальный капитал в USD

        Returns:
            dict с ключами: equity_curve, trades, metrics, strategy_id
        """
        # Группируем данные по дням
        days_data: dict[str, list[dict]] = {}
        for row in historical_data:
            ts = row["timestamp"][:10]
            days_data.setdefault(ts, []).append(row)

        sorted_dates = sorted(days_data.keys())
        if not sorted_dates:
            return self._empty_result(initial_capital)

        capital    = initial_capital
        positions: list[_S1Position] = []
        equity_curve: list[dict] = []
        all_trades: list[dict]   = []

        for day_str in sorted_dates:
            day_protocols = {r["protocol_key"]: r for r in days_data[day_str]}

            # 1. Обновляем APY открытых позиций
            for pos in positions:
                if pos.protocol_key in day_protocols:
                    pos.current_apy = day_protocols[pos.protocol_key]["apy"]

            # 2. Начисляем проценты
            for pos in positions:
                interest = pos.daily_interest()
                pos.interest_earned += interest
                capital += interest

            # 3. Ребалансировка — закрываем позиции, если нужно
            candidates = self._candidates(day_protocols)
            best_apy   = candidates[0]["apy"] if candidates else 0.0
            keep, closed = [], []
            for pos in positions:
                data = day_protocols.get(pos.protocol_key)
                should_close = False
                reason = ""
                if data is None:
                    should_close, reason = True, "protocol_not_in_data"
                elif not self._is_allowed(data):
                    should_close, reason = True, "no_longer_allowed"
                elif (best_apy - pos.current_apy) > REBALANCE_THRESHOLD:
                    should_close, reason = True, f"rebalance_gap_{best_apy:.2f}_vs_{pos.current_apy:.2f}"
                if should_close:
                    closed.append({
                        "date": day_str, "protocol": pos.protocol_key,
                        "action": "CLOSE", "amount": round(pos.amount_usd, 2),
                        "apy": round(pos.current_apy, 4),
                        "interest_usd": round(pos.interest_earned, 4),
                        "pnl": round(pos.interest_earned, 4),
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

                # Размер позиции: минимум из (cash - buffer) и (MAX_CONCENTRATION * capital)
                max_size = min(cash - min_cash, MAX_CONCENTRATION * capital)
                # Равномерно делим оставшийся cash на оставшиеся слоты
                remaining_slots = MAX_POSITIONS - len(positions)
                size = min(max_size, (cash - min_cash) / max(remaining_slots, 1))
                size = round(size, 2)

                if size < 100.0:
                    continue

                new_pos = _S1Position(
                    protocol_key=key,
                    amount_usd=size,
                    apy_at_open=candidate["apy"],
                    current_apy=candidate["apy"],
                )
                positions.append(new_pos)
                open_keys.add(key)
                all_trades.append({
                    "date": day_str, "protocol": key,
                    "action": "OPEN", "amount": size,
                    "apy": round(candidate["apy"], 4),
                    "tier": candidate.get("tier", "T1"),
                    "interest_usd": 0.0, "pnl": 0.0,
                    "reason": "s1_allocate", "strategy": STRATEGY_ID,
                })

            # 5. Снимок
            deployed = sum(p.amount_usd for p in positions)
            cash     = capital - deployed
            pnl_pct  = (capital - initial_capital) / initial_capital * 100
            weighted_apy = (
                sum(p.amount_usd * p.current_apy for p in positions) / deployed
                if deployed > 0 else 0.0
            )
            equity_curve.append({
                "date": day_str,
                "total_capital": round(capital, 2),
                "deployed": round(deployed, 2),
                "cash": round(cash, 2),
                "pnl_pct": round(pnl_pct, 4),
                "open_positions": len(positions),
                "weighted_apy": round(weighted_apy, 4),
                "strategy": STRATEGY_ID,
            })

        return self._compute_result(equity_curve, all_trades, initial_capital, capital)

    # ── Compute metrics ───────────────────────────────────────────────────────

    def _compute_result(
        self,
        equity_curve: list[dict],
        trades: list[dict],
        initial_capital: float,
        final_capital: float,
    ) -> dict:
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
            "risk_tier":             "T1",
            "target_apy_range":      f"{MIN_APY}–{MAX_APY}%",
        }
        return {
            "strategy_id":  STRATEGY_ID,
            "equity_curve": equity_curve,
            "trades":       trades,
            "metrics":      metrics,
        }

    def run_day(self, apy_map: dict = None) -> float:
        """Thin adapter for cycle_runner compatibility.
        Returns weighted APY from allowed T1 protocols in apy_map."""
        _FALLBACK_APY = 5.0  # midpoint of 4–6% target range
        if not apy_map:
            return _FALLBACK_APY
        apys = []
        for key, val in apy_map.items():
            if not isinstance(val, (int, float)):
                continue
            if not any(key.startswith(prefix) for prefix in ALLOWED_PROTOCOL_PREFIXES):
                continue
            apy = float(val)
            if MIN_APY <= apy <= MAX_APY:
                apys.append(apy)
        if apys:
            return float(sum(apys) / len(apys))
        return _FALLBACK_APY

    def _empty_result(self, initial_capital: float) -> dict:
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
                "strategy_id": STRATEGY_ID, "risk_tier": "T1",
                "target_apy_range": f"{MIN_APY}–{MAX_APY}%",
            },
        }


# ─── Авто-регистрация в реестре ───────────────────────────────────────────────

def _register() -> None:
    try:
        from spa_core.strategies.strategy_registry import REGISTRY, StrategyMeta
        REGISTRY.register(StrategyMeta(
            id="s1_conservative_lending",
            name="S1 — Conservative Lending",
            type="lending",
            risk_tier="T1",
            target_apy_min=4.0,
            target_apy_max=6.0,
            max_drawdown_pct=2.0,
            description=(
                "T1-only lending: Aave V3, Compound V3, Morpho, Sky/sUSDS, Yearn V3. "
                "Max 40% per protocol, 5% cash buffer, rebalance at +1 pp APY gap."
            ),
            module="spa_core.strategies.s1_conservative_lending",
            handler_class="ConservativeLendingStrategy",
            tags=["conservative", "lending", "t1", "stable"],
        ))
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("S1 auto-registration failed: %s", exc)


_register()
