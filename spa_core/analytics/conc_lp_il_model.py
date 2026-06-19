"""
spa_core/analytics/conc_lp_il_model.py

Impermanent Loss (IL) calculator for concentrated liquidity positions
(Uniswap V3 style).

Theory
------
Full-range IL (standard AMM):
    IL_full(r) = 2*sqrt(r) / (1 + r) - 1
    where r = P_current / P_initial  (price ratio)
    IL_full ∈ (-1, 0]; negative means loss relative to hold.

Concentrated liquidity IL (range [P_a, P_b]):
    When price is INSIDE the range [P_a, P_b]:
        The position behaves like a full-range AMM scaled by a concentration
        factor. The value of the position at price P is:

            V(P) = 2 * L * (sqrt(P) - sqrt(P_a))
                 + 2 * L * (1/sqrt(P_a) - 1/sqrt(P)) * P   (simplified)

        We use the standard ratio formula from the Uniswap V3 whitepaper:

            V_lp(P)   = L * (sqrt(P) - sqrt(P_a))
                       + L * (1/sqrt(P) - 1/sqrt(P_b)) * P_b   (token1)
                   simplified relative form

        IL for concentrated LP relative to 50/50 hold:

            conc_factor = sqrt(P_b / P_a) / (sqrt(P_b / P_a) - 1)

        However, for practical scenario analysis we use the direct V3 LP value
        formula compared to hold value:

            LP value at P (both tokens combined in token1 units):
              V_lp = 2*L*(sqrt(P) - sqrt(P_a))   when P_a < P < P_b

            Hold value (initial 50/50 in token1 units):
              V_hold = L/sqrt(P_0)*(P + P_0)    [approx at initial P_0]

        In practice, we compute IL as the relative underperformance of the LP
        position vs holding the initial portfolio composition.

    When price is OUTSIDE the range:
        The position is 100% in one asset → no more IL accumulates, but fees
        also stop. The IL is "locked" at the boundary value.

Usage
-----
    model = ConcLPILModel(price_lower=40000, price_upper=80000, initial_price=60000)
    il = model.il_pct(current_price=50000)  # Returns IL as negative percentage
    net = model.net_apy_estimate(gross_fee_apy=40.0, price_move_pct=20.0)

Правила (проектные):
    - Только stdlib Python (math)
    - Чисто вычислительный модуль — никаких I/O, никаких записей
    - Не импортировать из execution / feed_health / risk

MP-1308 (v9.24)
"""
from __future__ import annotations

import math
from typing import List, Optional


# ── вспомогательные функции ───────────────────────────────────────────────────

def _sqrt(x: float) -> float:
    """math.sqrt с проверкой на отрицательное значение (возвращает 0.0)."""
    return math.sqrt(max(0.0, x))


# ── модель ────────────────────────────────────────────────────────────────────

class ConcLPILModel:
    """Калькулятор Impermanent Loss для concentrated liquidity (Uniswap V3).

    Параметры
    ---------
    price_lower : float
        Нижняя граница диапазона позиции (P_a). Должна быть > 0.
    price_upper : float
        Верхняя граница диапазона позиции (P_b). Должна быть > price_lower.
    initial_price : float
        Цена в момент открытия позиции (P_0). Должна быть в [P_a, P_b].
    fee_tier : float
        Уровень комиссии: 0.001 (0.1%), 0.003 (0.3%), 0.01 (1.0%).
        Используется только как метаданные — расчёт APY передаётся явно.
    """

    # Дефолтные сценарии движения цены (в %)
    DEFAULT_PRICE_MOVES: List[float] = [-50, -30, -20, -10, -5, 0, 5, 10, 20, 30, 50]

    def __init__(
        self,
        price_lower: float,
        price_upper: float,
        initial_price: float,
        fee_tier: float = 0.003,
    ) -> None:
        if price_lower <= 0:
            raise ValueError(f"price_lower must be > 0, got {price_lower}")
        if price_upper <= price_lower:
            raise ValueError(
                f"price_upper ({price_upper}) must be > price_lower ({price_lower})"
            )
        if initial_price <= 0:
            raise ValueError(f"initial_price must be > 0, got {initial_price}")

        self.price_lower: float = float(price_lower)
        self.price_upper: float = float(price_upper)
        self.initial_price: float = float(initial_price)
        self.fee_tier: float = float(fee_tier)

        # Сохраняем sqrts для эффективности
        self._sqrt_pa: float = _sqrt(self.price_lower)
        self._sqrt_pb: float = _sqrt(self.price_upper)
        self._sqrt_p0: float = _sqrt(self.initial_price)

    # ── Uniswap V3 LP value formula ───────────────────────────────────────────

    def _lp_value_ratio(self, current_price: float) -> float:
        """Возвращает стоимость LP-позиции относительно начальной стоимости hold.

        Используем Uniswap V3 LP value formula (L=1, значения в token1 units).

        В Uniswap V3 при цене P внутри диапазона [Pa, Pb]:
            token0 (risky, e.g. BTC/ETH):   x = 1/sqrt(P) - 1/sqrt(Pb)
            token1 (stable, e.g. USDC):      y = sqrt(P)   - sqrt(Pa)

        Начальные количества при P_0 (inside range):
            x0 = 1/sqrt(P0) - 1/sqrt(Pb)
            y0 = sqrt(P0)   - sqrt(Pa)

        Hold value при текущей цене P:
            V_hold(P) = x0 * P + y0

        LP value при текущей цене P:
            - Inside range:  V_lp = x*P + y = (1/sqrt(P) - 1/sqrt(Pb))*P + sqrt(P) - sqrt(Pa)
            - P < Pa (100% token0): x_full = 1/sqrt(Pa) - 1/sqrt(Pb), V_lp = x_full * P
            - P > Pb (100% token1): y_full = sqrt(Pb) - sqrt(Pa),      V_lp = y_full

        Возвращает V_lp / V_hold. При V_hold ≈ 0 → 1.0.
        Гарантия: V_lp/V_hold = 1.0 при P = P0 (нет IL в момент открытия).
        """
        P = float(current_price)
        Pa = self.price_lower
        Pb = self.price_upper
        P0 = self.initial_price

        sqrt_P = _sqrt(P)
        sqrt_Pa = self._sqrt_pa
        sqrt_Pb = self._sqrt_pb
        sqrt_P0 = self._sqrt_p0

        if sqrt_P0 <= 0 or sqrt_Pb <= 0:
            return 1.0

        # Начальные количества при P0 (inside range, L=1)
        x0 = 1.0 / sqrt_P0 - 1.0 / sqrt_Pb   # token0 (risky asset)
        y0 = sqrt_P0 - sqrt_Pa                  # token1 (stablecoin)

        # Hold value (держим x0 token0 + y0 token1, оцениваем при P)
        v_hold = x0 * P + y0

        if v_hold <= 0:
            return 1.0

        # LP value при текущей цене P
        if P <= Pa:
            # Позиция полностью в token0 (весь стейбл конвертирован в risky)
            x_full = (1.0 / sqrt_Pa - 1.0 / sqrt_Pb) if sqrt_Pa > 0 else 0.0
            v_lp = x_full * P
        elif P >= Pb:
            # Позиция полностью в token1 (весь risky конвертирован в стейбл)
            y_full = sqrt_Pb - sqrt_Pa
            v_lp = y_full
        else:
            # Внутри диапазона
            x = (1.0 / sqrt_P - 1.0 / sqrt_Pb) if sqrt_P > 0 else 0.0
            y = sqrt_P - sqrt_Pa
            v_lp = x * P + y

        return v_lp / v_hold

    # ── основные методы ───────────────────────────────────────────────────────

    def il_pct(self, current_price: float) -> float:
        """Возвращает IL как процент (отрицательный = потеря).

        Примеры:
            il_pct(initial_price) ≈ 0.0   (нет IL при входе)
            il_pct(price * 2)     ≈ -5.7% (50% вверх, GLP Univ3-wide)
            il_pct(price * 0.5)   ≈ -5.7% (50% вниз)

        Когда цена выходит за пределы диапазона, IL «фиксируется» на уровне
        границы: позиция в 100% одного актива, новый IL не накапливается.
        """
        ratio = self._lp_value_ratio(current_price)
        return (ratio - 1.0) * 100.0

    def is_in_range(self, price: float) -> bool:
        """True, если цена находится внутри диапазона позиции [price_lower, price_upper]."""
        return self.price_lower <= price <= self.price_upper

    def fee_apy_needed_to_break_even(self, il_pct: float, holding_days: int) -> float:
        """Минимальный APY комиссий для покрытия IL за holding_days.

        Параметры
        ---------
        il_pct : float
            Текущий IL в процентах (ожидается ≤ 0; используется abs значение).
        holding_days : int
            Горизонт удержания позиции в днях (> 0).

        Возвращает APY в процентах, необходимый для break-even.
        При holding_days ≤ 0 возвращает infinity.
        """
        if holding_days <= 0:
            return float("inf")
        abs_il = abs(il_pct)
        # break_even_apy = |IL_pct| / (holding_days / 365)
        return abs_il / (holding_days / 365.0)

    def net_apy_estimate(
        self,
        gross_fee_apy: float,
        price_move_pct: float,
        holding_days: int = 365,
    ) -> float:
        """Оценивает чистый APY с учётом IL при заданном движении цены.

        Параметры
        ---------
        gross_fee_apy : float
            Валовый APY от комиссий (в процентах, e.g. 40.0 = 40%).
        price_move_pct : float
            Изменение цены от начальной в процентах (e.g. 20.0 = +20%).
        holding_days : int
            Горизонт удержания (по умолчанию 365 дней = год).

        Возвращает чистый APY в процентах.
        При нулевом движении цены ≈ gross_fee_apy.
        """
        current_price = self.initial_price * (1 + price_move_pct / 100.0)
        current_price = max(current_price, 1e-9)  # защита от нуля/отрицательного

        il = self.il_pct(current_price)  # ≤ 0

        # IL annualized: il% за holding_days → годовое
        il_annual = il / (holding_days / 365.0)

        return gross_fee_apy + il_annual  # il_annual ≤ 0

    def scenario_analysis(
        self,
        gross_fee_apy: float = 40.0,
        price_moves: Optional[List[float]] = None,
    ) -> List[dict]:
        """Анализ сценариев: возвращает таблицу IL/net_apy для разных движений цены.

        Параметры
        ---------
        gross_fee_apy : float
            Валовый APY комиссий (%, default 40.0).
        price_moves : list of float, optional
            Список изменений цены в % (default: DEFAULT_PRICE_MOVES).

        Возвращает список словарей:
            {
              "price_move_pct": float,
              "current_price": float,
              "il_pct": float,        # отрицательный = потеря
              "net_apy": float,
              "in_range": bool,
              "break_even_apy": float,
            }
        """
        if price_moves is None:
            price_moves = self.DEFAULT_PRICE_MOVES

        results = []
        for move_pct in price_moves:
            current_price = self.initial_price * (1 + move_pct / 100.0)
            current_price = max(current_price, 1e-9)

            il = self.il_pct(current_price)
            net = self.net_apy_estimate(gross_fee_apy, move_pct)
            in_range = self.is_in_range(current_price)
            be_apy = self.fee_apy_needed_to_break_even(il, 365)

            results.append(
                {
                    "price_move_pct": float(move_pct),
                    "current_price": current_price,
                    "il_pct": round(il, 4),
                    "net_apy": round(net, 4),
                    "in_range": in_range,
                    "break_even_apy": round(be_apy, 4),
                }
            )

        return results

    # ── фабричные методы ─────────────────────────────────────────────────────

    @classmethod
    def for_btc_usd(
        cls,
        initial_btc_price: float = 60_000.0,
        range_width_pct: float = 50.0,
        fee_tier: float = 0.003,
    ) -> "ConcLPILModel":
        """Фабрика: BTC/USD пул с диапазоном ±range_width_pct% от текущей цены.

        Параметры
        ---------
        initial_btc_price : float
            Текущая цена BTC в USD.
        range_width_pct : float
            Ширина диапазона в % от текущей цены (± симметрично).
        fee_tier : float
            Тир комиссии (default 0.3%).
        """
        if initial_btc_price <= 0:
            raise ValueError("initial_btc_price must be > 0")
        if range_width_pct <= 0 or range_width_pct >= 100:
            raise ValueError("range_width_pct must be in (0, 100)")

        half = range_width_pct / 100.0
        price_lower = initial_btc_price * (1 - half)
        price_upper = initial_btc_price * (1 + half)

        return cls(
            price_lower=price_lower,
            price_upper=price_upper,
            initial_price=initial_btc_price,
            fee_tier=fee_tier,
        )

    @classmethod
    def for_eth_usd(
        cls,
        initial_eth_price: float = 3_000.0,
        range_width_pct: float = 50.0,
        fee_tier: float = 0.003,
    ) -> "ConcLPILModel":
        """Фабрика: ETH/USD пул с диапазоном ±range_width_pct% от текущей цены."""
        if initial_eth_price <= 0:
            raise ValueError("initial_eth_price must be > 0")
        if range_width_pct <= 0 or range_width_pct >= 100:
            raise ValueError("range_width_pct must be in (0, 100)")

        half = range_width_pct / 100.0
        price_lower = initial_eth_price * (1 - half)
        price_upper = initial_eth_price * (1 + half)

        return cls(
            price_lower=price_lower,
            price_upper=price_upper,
            initial_price=initial_eth_price,
            fee_tier=fee_tier,
        )

    # ── RS-002 helpers ────────────────────────────────────────────────────────

    def rs002_net_apy(self, btc_price_move_pct: float) -> float:
        """Net APY для RS-002 BTC/USD concentrated LP позиции.

        Использует gross_fee_apy=40.0 (типичный GMX/Uniswap V3 BTC пул).
        Возвращает net APY в процентах.
        """
        return self.net_apy_estimate(40.0, btc_price_move_pct)

    # ── utility ───────────────────────────────────────────────────────────────

    def concentration_factor(self) -> float:
        """Коэффициент концентрации ликвидности относительно full-range.

        concentration_factor ≈ sqrt(P_b/P_a) / (sqrt(P_b/P_a) - 1)
        Показывает, во сколько раз позиция «мощнее» full-range AMM.
        """
        ratio = self._sqrt_pb / self._sqrt_pa if self._sqrt_pa > 0 else float("inf")
        if ratio <= 1.0:
            return float("inf")
        return ratio / (ratio - 1.0)

    def range_width_pct(self) -> float:
        """Ширина диапазона в процентах от начальной цены."""
        return (self.price_upper - self.price_lower) / self.initial_price * 100.0

    def __repr__(self) -> str:
        return (
            f"ConcLPILModel("
            f"Pa={self.price_lower:.2f}, "
            f"Pb={self.price_upper:.2f}, "
            f"P0={self.initial_price:.2f}, "
            f"fee={self.fee_tier*100:.2f}%)"
        )
