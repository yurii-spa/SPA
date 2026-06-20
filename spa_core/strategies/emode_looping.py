"""
spa_core/strategies/emode_looping.py — S9 Aave E-Mode Looping Strategy
========================================================================

Strategy S9 — Aave E-Mode USDC Looping (2x leverage, paper trading)
Risk Tier : T3  (только paper trading до ADR + Owner approval)
Type      : yield_loop
Target APY: 6.0–9.0%
Max DD    : 5%

E-Mode Looping Mechanism:
  1. Deposit USDC as collateral → earn supply_apy on deposited capital
  2. Borrow USDE/DAI in E-Mode (up to 94% LTV) → pay borrow_apy on borrowed
  3. Reinvest borrowed amount into Pendle/Morpho → earn reinvest_apy

Net APY Formula:
  net_apy = supply_apy + (ltv × reinvest_apy) − (ltv × borrow_apy)

Example at default params (ltv=0.82):
  net_apy = 3.2% + (82% × 8.9%) − (82% × 4.5%)
          = 3.2% + 7.298% − 3.69% = 6.808%

Health Factor:
  HF = (deposited × E_MODE_LIQ_THRESHOLD) / borrowed
     = E_MODE_LIQ_THRESHOLD / operating_ltv

  At operating_ltv = 0.626: HF = 0.97 / 0.626 ≈ 1.55  (safe, normal)
  At operating_ltv = 0.700: HF = 0.97 / 0.70  ≈ 1.39  (warn zone)
  At operating_ltv = 0.808: HF = 0.97 / 0.808 ≈ 1.20  (emergency boundary)
  At operating_ltv = 0.820: HF = 0.97 / 0.820 ≈ 1.18  (emergency → deleverage)

Stress Scenarios:
  - Borrow spike: borrow_apy > 8% → auto-deleverage
  - Supply drop: supply_apy < 0.5% → recalculate attractiveness
  - Liquidation risk: HF < 1.3 → alert + deleverage plan
  - Emergency: HF < 1.2 → immediate deleverage to 60% LTV

APY Sources:
  - supply_apy  : Aave USDC supply rate (mock: 4.2% → param default 3.2%)
  - borrow_apy  : Aave USDC/USDE borrow rate (param default 4.5%)
  - reinvest_apy: Best available Morpho/Pendle (mock: Euler 7.4%, Yearn 6.8%)

⚠️  PAPER TRADING ONLY. Requires ADR + Owner approval for live capital.
    LLM_FORBIDDEN: risk / execution / monitoring domains.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# ─── Константы E-Mode ─────────────────────────────────────────────────────────

#: Liquidation threshold в Aave E-Mode (коррелированные стейблкоины)
E_MODE_LIQ_THRESHOLD: float = 0.97

#: Максимальный LTV в E-Mode
E_MODE_MAX_LTV: float = 0.94

#: Целевой LTV после делевериджа
DELEVERAGE_TARGET_LTV: float = 0.60

#: HF ниже этого → warn-алерт + план делевериджа
HF_WARN: float = 1.50

#: HF ниже этого → немедленный аварийный делеверидж
HF_EMERGENCY: float = 1.20

#: Минимальный кэш-буфер (% от total equity)
MIN_CASH_BUFFER: float = 0.05

#: Порог borrow_apy для авто-делевериджа (abs значение, 8%)
BORROW_SPIKE_THRESHOLD: float = 0.08

#: Порог supply_apy, ниже которого стратегия «непривлекательна»
SUPPLY_DROP_THRESHOLD: float = 0.005

#: Данные adapter_status.json (для чтения live APY)
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_ADAPTER_STATUS_PATH = _PROJECT_ROOT / "data" / "adapter_status.json"


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _read_apy_from_adapter_status(
    protocol_key: str,
    chain: str = "ethereum",
    asset: str = "USDC",
    default: float = 0.0,
) -> float:
    """Читает APY из data/adapter_status.json. Возвращает default при любой ошибке.

    Args:
        protocol_key: ключ протокола ('aave-v3', 'morpho_blue', …)
        chain: цепочка ('ethereum', 'arbitrum', …)
        asset: актив ('USDC', 'USDT', …)
        default: значение по умолчанию при ошибке чтения (доли, не %)

    Returns:
        APY в долях (e.g. 0.042 для 4.2%).
    """
    try:
        with open(_ADAPTER_STATUS_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        for adapter in data.get("adapters", []):
            if adapter.get("protocol_key") == protocol_key:
                mock_apy = adapter.get("mock_apy", {})
                chain_apy = mock_apy.get(chain, {})
                raw = chain_apy.get(asset)
                if raw is not None:
                    return float(raw) / 100.0  # конвертация % → доли
        return default
    except (OSError, ValueError, KeyError):
        return default


def _best_reinvest_apy(chain: str = "ethereum", asset: str = "USDC") -> float:
    """Лучший доступный APY для реинвестиции (Morpho/Yearn/Euler/Pendle).

    Returns:
        APY в долях.
    """
    candidates = [
        ("morpho_blue",  chain, asset),
        ("euler_v2",     chain, asset),
        ("yearn_v3",     chain, asset),
        ("pendle-pt",    chain, asset),
    ]
    # Маппинг mock-ключей на protocol_key
    _key_map = {
        "morpho_blue":  "morpho_blue",
        "euler_v2":     "euler_v2",
        "yearn_v3":     "yearn_v3",
        "pendle-pt":    "pendle-pt",
    }
    best = 0.0
    for proto, ch, ast in candidates:
        apy = _read_apy_from_adapter_status(_key_map.get(proto, proto), ch, ast, default=0.0)
        if apy > best:
            best = apy
    return best if best > 0.0 else 0.089  # fallback 8.9%


# ─── Position state ───────────────────────────────────────────────────────────

@dataclass
class _DailySnapshot:
    """Снимок состояния позиции за один день."""
    date: str
    day: int
    deposited: float
    borrowed: float
    reinvested: float
    supply_apy: float
    borrow_apy: float
    reinvest_apy: float
    net_apy: float
    health_factor: float
    supply_income: float
    borrow_cost: float
    reinvest_income: float
    daily_pnl: float
    cumulative_pnl: float
    equity: float
    status: str          # "active", "warning", "emergency", "deleveraging", "closed"
    alerts: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "date": self.date,
            "day": self.day,
            "deposited": round(self.deposited, 6),
            "borrowed": round(self.borrowed, 6),
            "reinvested": round(self.reinvested, 6),
            "supply_apy": round(self.supply_apy, 6),
            "borrow_apy": round(self.borrow_apy, 6),
            "reinvest_apy": round(self.reinvest_apy, 6),
            "net_apy": round(self.net_apy, 6),
            "health_factor": round(self.health_factor, 4),
            "supply_income": round(self.supply_income, 6),
            "borrow_cost": round(self.borrow_cost, 6),
            "reinvest_income": round(self.reinvest_income, 6),
            "daily_pnl": round(self.daily_pnl, 6),
            "cumulative_pnl": round(self.cumulative_pnl, 6),
            "equity": round(self.equity, 6),
            "status": self.status,
            "alerts": self.alerts,
        }


# ─── Main class ───────────────────────────────────────────────────────────────

class EModeLoopingStrategy:
    """
    Paper-trading симулятор Aave E-Mode USDC Looping (Strategy S9).

    Механика:
      Deposit USDC → borrow USDE/DAI в E-Mode (≤ 94% LTV) →
      reinvest в Pendle/Morpho.

    Параметры (all APY в долях, e.g. 0.032 = 3.2%):
        capital       : начальный виртуальный капитал USDC
        ltv           : рабочий LTV займа (дефолт 0.82 — агрессивный)
        supply_apy    : годовой APY Aave supply (дефолт 3.2%)
        borrow_apy    : годовой APY Aave borrow (дефолт 4.5%)
        reinvest_apy  : годовой APY реинвестиции (дефолт 8.9%)

    Состояние позиции:
        deposited  : USDC в Aave как залог (растёт с supply_apy)
        borrowed   : USDE/DAI занято в Aave (растёт с borrow_apy)
        reinvested : USDC в Pendle/Morpho (растёт с reinvest_apy)
        cumulative_pnl: накопленный P&L в USD

    Health Factor:
        HF = (deposited × E_MODE_LIQ_THRESHOLD) / borrowed

    Warn    : HF < 1.50
    Emergency: HF < 1.20 → deleverage()

    ⚠️  PAPER TRADING ONLY.
    """

    # Публичные константы (для тестов)
    E_MODE_LIQ_THRESHOLD: float = E_MODE_LIQ_THRESHOLD
    E_MODE_MAX_LTV: float = E_MODE_MAX_LTV
    DELEVERAGE_TARGET_LTV: float = DELEVERAGE_TARGET_LTV
    HF_WARN: float = HF_WARN
    HF_EMERGENCY: float = HF_EMERGENCY
    BORROW_SPIKE_THRESHOLD: float = BORROW_SPIKE_THRESHOLD
    SUPPLY_DROP_THRESHOLD: float = SUPPLY_DROP_THRESHOLD

    def __init__(
        self,
        capital: float,
        ltv: float = 0.82,
        supply_apy: float = 0.032,
        borrow_apy: float = 0.045,
        reinvest_apy: float = 0.089,
    ) -> None:
        if capital <= 0:
            raise ValueError(f"capital must be > 0, got {capital}")
        if not (0.0 < ltv <= E_MODE_MAX_LTV):
            raise ValueError(f"ltv must be in (0, {E_MODE_MAX_LTV}], got {ltv}")
        if supply_apy < 0:
            raise ValueError(f"supply_apy must be >= 0, got {supply_apy}")
        if borrow_apy < 0:
            raise ValueError(f"borrow_apy must be >= 0, got {borrow_apy}")
        if reinvest_apy < 0:
            raise ValueError(f"reinvest_apy must be >= 0, got {reinvest_apy}")

        self.initial_capital: float = float(capital)
        self.ltv: float = float(ltv)
        self.supply_apy: float = float(supply_apy)
        self.borrow_apy: float = float(borrow_apy)
        self.reinvest_apy: float = float(reinvest_apy)

        # ── Позиция ────────────────────────────────────────────────────────────
        self.deposited: float = float(capital)          # USDC collateral в Aave
        self.borrowed: float = float(capital) * ltv     # USDE/DAI debt в Aave
        self.reinvested: float = float(capital) * ltv   # размещено в Pendle/Morpho

        # ── Накопленные результаты ─────────────────────────────────────────────
        self.cumulative_pnl: float = 0.0
        self.accrued_supply_income: float = 0.0
        self.accrued_borrow_cost: float = 0.0
        self.accrued_reinvest_income: float = 0.0

        # ── История ────────────────────────────────────────────────────────────
        self.day_count: int = 0
        self.daily_snapshots: list[_DailySnapshot] = []
        self.deleverage_events: list[dict] = []
        self.alerts: list[dict] = []

        # ── Статус ────────────────────────────────────────────────────────────
        self.position_status: str = "active"  # active | warning | emergency | closed
        self.is_closed: bool = False

    # ── Основные расчёты ──────────────────────────────────────────────────────

    def net_apy(self) -> float:
        """Чистый годовой APY стратегии в долях.

        Формула:
            net_apy = supply_apy + (ltv × reinvest_apy) − (ltv × borrow_apy)

        Пример (дефолтные параметры, ltv=0.82):
            net_apy = 3.2% + (82% × 8.9%) − (82% × 4.5%)
                    = 3.2% + 7.298% − 3.69% = 6.808%

        Returns:
            float: APY в долях (e.g. 0.068 = 6.8%).
        """
        return (
            self.supply_apy
            + self.ltv * self.reinvest_apy
            - self.ltv * self.borrow_apy
        )

    def health_factor(
        self,
        supply_apy: Optional[float] = None,
        borrow_apy: Optional[float] = None,
    ) -> float:
        """Текущий health factor позиции.

        Формула:
            HF = (deposited × E_MODE_LIQ_THRESHOLD) / borrowed

        Если переданы supply_apy / borrow_apy — учитывает однодневное
        изменение collateral и debt (projected HF).

        Args:
            supply_apy: актуальный APY supply для проекции (или None = брать self.supply_apy)
            borrow_apy: актуальный APY borrow для проекции (или None = брать self.borrow_apy)

        Returns:
            float: health factor (inf если долга нет)

        Thresholds:
            HF < HF_WARN (1.5)  → warn-алерт
            HF < HF_EMERGENCY (1.2) → аварийный делеверидж
        """
        if self.borrowed <= 0.0:
            return float("inf")

        _sup = supply_apy if supply_apy is not None else self.supply_apy
        _bor = borrow_apy if borrow_apy is not None else self.borrow_apy

        # Projected после одного дня
        projected_col = self.deposited * (1.0 + _sup / 365.0)
        projected_debt = self.borrowed * (1.0 + _bor / 365.0)

        return (projected_col * E_MODE_LIQ_THRESHOLD) / projected_debt

    def current_ltv_ratio(self) -> float:
        """Текущий фактический LTV = borrowed / deposited."""
        if self.deposited <= 0.0:
            return 0.0
        return self.borrowed / self.deposited

    def is_attractive(self) -> bool:
        """Стратегия привлекательна: net_apy > 0 и supply_apy выше минимума."""
        return (
            self.net_apy() > 0.0
            and self.supply_apy > SUPPLY_DROP_THRESHOLD
            and self.borrow_apy < BORROW_SPIKE_THRESHOLD
        )

    # ── Симуляция ─────────────────────────────────────────────────────────────

    def simulate_day(
        self,
        supply_apy: Optional[float] = None,
        borrow_apy: Optional[float] = None,
        reinvest_apy: Optional[float] = None,
    ) -> dict:
        """Один шаг симуляции (один торговый день).

        Порядок действий:
          1. Обновляет APY из аргументов (если переданы)
          2. Начисляет дневной доход на все компоненты
          3. Проверяет health factor и stress-условия
          4. Если HF < HF_EMERGENCY → вызывает deleverage()
          5. Если borrow_apy > BORROW_SPIKE_THRESHOLD → deleverage()
          6. Записывает снимок в daily_snapshots

        Args:
            supply_apy   : новый APY supply на этот день (None = использовать self.supply_apy)
            borrow_apy   : новый APY borrow на этот день
            reinvest_apy : новый APY реинвестиции на этот день

        Returns:
            dict: снимок дня (DailySnapshot.to_dict())
        """
        if self.is_closed:
            return {"status": "closed", "day": self.day_count, "daily_pnl": 0.0}

        # 1. Обновляем APY если переданы новые значения
        if supply_apy is not None:
            self.supply_apy = float(supply_apy)
        if borrow_apy is not None:
            self.borrow_apy = float(borrow_apy)
        if reinvest_apy is not None:
            self.reinvest_apy = float(reinvest_apy)

        self.day_count += 1
        day_alerts: list[str] = []

        # 2. Начисляем дневной yield на позиции
        daily_supply_income  = self.deposited   * self.supply_apy  / 365.0
        daily_borrow_cost    = self.borrowed    * self.borrow_apy  / 365.0
        daily_reinvest_income= self.reinvested  * self.reinvest_apy / 365.0

        # Обновляем состояние
        self.deposited   += daily_supply_income    # supply APY реинвестируется в залог
        self.borrowed    += daily_borrow_cost      # долг растёт на начисленные проценты
        self.reinvested  += daily_reinvest_income  # реинвест-доход реинвестируется

        self.accrued_supply_income   += daily_supply_income
        self.accrued_borrow_cost     += daily_borrow_cost
        self.accrued_reinvest_income += daily_reinvest_income

        daily_net_pnl = daily_supply_income + daily_reinvest_income - daily_borrow_cost
        self.cumulative_pnl += daily_net_pnl

        # 3. Проверяем stress-условия
        deleverage_triggered = False

        # a) Borrow spike
        if self.borrow_apy > BORROW_SPIKE_THRESHOLD:
            msg = (
                f"BORROW_SPIKE: borrow_apy={self.borrow_apy:.2%} > "
                f"threshold={BORROW_SPIKE_THRESHOLD:.2%} → deleverage triggered"
            )
            day_alerts.append(msg)
            log.warning("S9 day %d: %s", self.day_count, msg)
            deleverage_triggered = True

        # b) Supply drop
        if self.supply_apy < SUPPLY_DROP_THRESHOLD:
            msg = (
                f"SUPPLY_DROP: supply_apy={self.supply_apy:.2%} < "
                f"threshold={SUPPLY_DROP_THRESHOLD:.2%} → strategy unattractive"
            )
            day_alerts.append(msg)
            log.warning("S9 day %d: %s", self.day_count, msg)

        # c) Health Factor
        hf = self.health_factor()

        if hf < HF_EMERGENCY:
            msg = f"EMERGENCY: HF={hf:.4f} < {HF_EMERGENCY} → deleverage triggered"
            day_alerts.append(msg)
            log.warning("S9 day %d: %s", self.day_count, msg)
            deleverage_triggered = True
        elif hf < HF_WARN:
            msg = f"WARN: HF={hf:.4f} < {HF_WARN} → monitor closely"
            day_alerts.append(msg)
            log.warning("S9 day %d: %s", self.day_count, msg)
            self.position_status = "warning"

        # 4. Исполняем делеверидж если нужно
        if deleverage_triggered and not self.is_closed:
            dl_result = self.deleverage()
            day_alerts.append(f"DELEVERAGE: {dl_result['summary']}")
            hf = self.health_factor()  # пересчитываем после делевериджа

        # 5. Определяем статус
        if self.is_closed:
            status = "closed"
        elif deleverage_triggered:
            status = "deleveraging"
        elif hf < HF_WARN:
            status = "warning"
        else:
            status = "active"
            if self.position_status == "warning":
                self.position_status = "active"

        # 6. Записываем алерты
        for alert_msg in day_alerts:
            self.alerts.append({
                "day": self.day_count,
                "ts": datetime.now(timezone.utc).isoformat(),
                "message": alert_msg,
            })

        # 7. Equity
        equity = (
            self.deposited
            + self.reinvested
            - self.borrowed
            + self.initial_capital
        )
        # Упрощённый расчёт equity: net_position + capital_base
        # Net position = collateral + reinvested - debt
        net_position = self.deposited + self.reinvested - self.borrowed
        equity = net_position + (self.initial_capital - self.initial_capital * self.ltv)
        # Более прямой: equity = initial_capital + cumulative_pnl
        equity = self.initial_capital + self.cumulative_pnl

        # 8. Создаём снимок
        snapshot = _DailySnapshot(
            date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            day=self.day_count,
            deposited=self.deposited,
            borrowed=self.borrowed,
            reinvested=self.reinvested,
            supply_apy=self.supply_apy,
            borrow_apy=self.borrow_apy,
            reinvest_apy=self.reinvest_apy,
            net_apy=self.net_apy(),
            health_factor=hf,
            supply_income=daily_supply_income,
            borrow_cost=daily_borrow_cost,
            reinvest_income=daily_reinvest_income,
            daily_pnl=daily_net_pnl,
            cumulative_pnl=self.cumulative_pnl,
            equity=equity,
            status=status,
            alerts=list(day_alerts),
        )
        self.daily_snapshots.append(snapshot)

        return snapshot.to_dict()

    # ── Делеверидж ────────────────────────────────────────────────────────────

    def deleverage(self) -> dict:
        """Автоматическое снижение LTV до DELEVERAGE_TARGET_LTV (60%).

        Механика:
          1. Вычисляет целевой долг: target_debt = deposited × 0.60
          2. Разница = current_borrowed − target_debt = сумма для погашения
          3. Погашение из reinvested (Pendle/Morpho → repay Aave debt)
          4. Если reinvested недостаточно → частичное погашение
          5. LTV обновляется

        Returns:
            dict: результат делевериджа с ключами:
                  previous_borrowed, target_borrowed, repaid, new_borrowed,
                  new_ltv, new_hf, reinvested_used, summary
        """
        if self.is_closed:
            return {"status": "closed", "summary": "position already closed"}

        prev_borrowed = self.borrowed
        prev_ltv = self.current_ltv_ratio()

        # Целевой долг
        target_debt = self.deposited * DELEVERAGE_TARGET_LTV

        if self.borrowed <= target_debt:
            # Уже в безопасной зоне
            return {
                "status": "no_action",
                "previous_borrowed": round(prev_borrowed, 6),
                "target_borrowed": round(target_debt, 6),
                "repaid": 0.0,
                "new_borrowed": round(self.borrowed, 6),
                "new_ltv": round(self.current_ltv_ratio(), 6),
                "new_hf": round(self.health_factor(), 4),
                "reinvested_used": 0.0,
                "summary": f"LTV={self.current_ltv_ratio():.3f} already <= target {DELEVERAGE_TARGET_LTV}",
            }

        repay_needed = self.borrowed - target_debt

        # Погашаем из reinvested
        repay_from_reinvested = min(repay_needed, self.reinvested)
        self.reinvested -= repay_from_reinvested
        self.borrowed   -= repay_from_reinvested

        # Если reinvested не хватило — частичное погашение (остаток pending)
        actual_repaid = repay_from_reinvested
        new_ltv = self.current_ltv_ratio()
        new_hf = self.health_factor()

        # Обновляем внутренний LTV
        self.ltv = new_ltv

        event = {
            "day": self.day_count,
            "ts": datetime.now(timezone.utc).isoformat(),
            "previous_borrowed": round(prev_borrowed, 6),
            "previous_ltv": round(prev_ltv, 4),
            "target_borrowed": round(target_debt, 6),
            "repaid": round(actual_repaid, 6),
            "new_borrowed": round(self.borrowed, 6),
            "new_ltv": round(new_ltv, 4),
            "new_hf": round(new_hf, 4),
            "reinvested_used": round(repay_from_reinvested, 6),
            "status": "ok" if new_hf >= HF_WARN else "partial",
            "summary": (
                f"deleverage: {prev_ltv:.3f}→{new_ltv:.3f} LTV, "
                f"repaid ${actual_repaid:,.2f}, HF={new_hf:.3f}"
            ),
        }
        self.deleverage_events.append(event)
        log.info("S9 deleverage: %s", event["summary"])

        return event

    # ── VPortfolio format ─────────────────────────────────────────────────────

    def to_vportfolio_format(self) -> dict:
        """Конвертирует состояние стратегии в формат совместимый с VPortfolio.

        Формат совместим с VirtualPortfolio.to_dict() из spa_core/strategies/vportfolio.py
        для интеграции в multi-strategy runner/tournament.

        Returns:
            dict: VPortfolio-совместимый словарь с ключами:
                  name, initial_capital, cash, positions, equity,
                  last_ts, equity_curve, strategy_meta
        """
        equity = self.initial_capital + self.cumulative_pnl

        # Позиции в формате VPortfolio: {pool_id: usd_value}
        positions: dict[str, float] = {
            "aave_v3_emode_supply":  round(self.deposited, 6),
            "aave_v3_emode_debt":    round(-self.borrowed, 6),   # отрицательная позиция
            "morpho_pendle_reinvest": round(self.reinvested, 6),
        }

        # equity_curve в формате VPortfolio
        equity_curve = [
            {
                "ts": s.date,
                "equity": round(self.initial_capital + s.cumulative_pnl, 6),
                "positions": {
                    "aave_v3_emode_supply":  round(s.deposited, 6),
                    "aave_v3_emode_debt":    round(-s.borrowed, 6),
                    "morpho_pendle_reinvest": round(s.reinvested, 6),
                },
            }
            for s in self.daily_snapshots[-90:]  # ring-buffer 90 точек
        ]

        # net_cash: не занято в позициях
        net_cash = max(0.0, equity - (self.deposited - self.borrowed + self.reinvested))

        return {
            "name": "s9_emode_looping",
            "strategy_id": "S9",
            "initial_capital": round(self.initial_capital, 6),
            "cash": round(net_cash, 6),
            "positions": positions,
            "equity": round(equity, 6),
            "last_ts": (
                self.daily_snapshots[-1].date
                if self.daily_snapshots else
                datetime.now(timezone.utc).strftime("%Y-%m-%d")
            ),
            "equity_curve": equity_curve,
            "strategy_meta": {
                "strategy_class": "emode_looping",
                "ltv": round(self.ltv, 4),
                "net_apy": round(self.net_apy(), 6),
                "health_factor": round(self.health_factor(), 4),
                "supply_apy": round(self.supply_apy, 6),
                "borrow_apy": round(self.borrow_apy, 6),
                "reinvest_apy": round(self.reinvest_apy, 6),
                "position_status": self.position_status,
                "day_count": self.day_count,
                "cumulative_pnl": round(self.cumulative_pnl, 6),
                "deleverage_events": len(self.deleverage_events),
                "is_demo": False,
            },
            "is_demo": False,
        }

    # ── Stress scenarios ──────────────────────────────────────────────────────

    def run_stress_scenario(self, scenario: str) -> dict:
        """Запускает встроенный стресс-сценарий.

        Сценарии:
            "normal"        : HF ~1.55, net APY ~7.2% (ltv=0.626)
            "borrow_spike"  : borrow_apy = 9% → auto-deleverage
            "supply_drop"   : supply_apy = 0.3% → unattractive
            "liquidation_risk": HF < 1.3 → alert + deleverage plan

        Args:
            scenario: название сценария

        Returns:
            dict: результаты сценария
        """
        scenarios = {
            "normal": {
                "supply_apy": 0.032,
                "borrow_apy": 0.045,
                "reinvest_apy": 0.089,
                "description": "Normal market: HF ~1.55 at safe LTV, net APY ~7.2%",
            },
            "borrow_spike": {
                "supply_apy": 0.032,
                "borrow_apy": 0.090,   # > 8% threshold
                "reinvest_apy": 0.089,
                "description": "Borrow rate spike to 9% → auto-deleverage triggered",
            },
            "supply_drop": {
                "supply_apy": 0.003,   # < 0.5% threshold
                "borrow_apy": 0.045,
                "reinvest_apy": 0.089,
                "description": "Aave supply rate collapse → strategy unattractive",
            },
            "liquidation_risk": {
                "supply_apy": 0.010,
                "borrow_apy": 0.075,
                "reinvest_apy": 0.089,
                "description": "HF < 1.3 → alert + deleverage plan",
            },
        }
        if scenario not in scenarios:
            raise ValueError(
                f"Unknown scenario '{scenario}'. "
                f"Available: {sorted(scenarios.keys())}"
            )
        params = scenarios[scenario]
        snapshot = self.simulate_day(
            supply_apy=params["supply_apy"],
            borrow_apy=params["borrow_apy"],
            reinvest_apy=params["reinvest_apy"],
        )
        return {
            "scenario": scenario,
            "description": params["description"],
            "snapshot": snapshot,
            "hf_before_deleverage": (
                E_MODE_LIQ_THRESHOLD / (self.borrowed / self.deposited)
                if self.deposited > 0 else float("inf")
            ),
            "deleverage_events": len(self.deleverage_events),
        }

    # ── Summary ───────────────────────────────────────────────────────────────

    def summary(self) -> dict:
        """Краткая сводка текущего состояния позиции."""
        hf = self.health_factor()
        hf_status = (
            "emergency" if hf < HF_EMERGENCY else
            "warning"   if hf < HF_WARN else
            "safe"
        )
        return {
            "strategy_id": "S9",
            "strategy_class": "emode_looping",
            "initial_capital": round(self.initial_capital, 2),
            "equity": round(self.initial_capital + self.cumulative_pnl, 2),
            "cumulative_pnl": round(self.cumulative_pnl, 2),
            "day_count": self.day_count,
            "deposited": round(self.deposited, 2),
            "borrowed": round(self.borrowed, 2),
            "reinvested": round(self.reinvested, 2),
            "current_ltv": round(self.current_ltv_ratio(), 4),
            "health_factor": round(hf, 4),
            "hf_status": hf_status,
            "net_apy_pct": round(self.net_apy() * 100, 4),
            "supply_apy_pct": round(self.supply_apy * 100, 4),
            "borrow_apy_pct": round(self.borrow_apy * 100, 4),
            "reinvest_apy_pct": round(self.reinvest_apy * 100, 4),
            "position_status": self.position_status,
            "deleverage_events": len(self.deleverage_events),
            "alert_count": len(self.alerts),
            "is_attractive": self.is_attractive(),
            "is_demo": False,
        }


# ─── Авто-регистрация в spa_core/strategies/strategy_registry.py ─────────────

def _register() -> None:
    """Авто-регистрация S9 в StrategyRegistry (spa_core/strategies/)."""
    try:
        from strategies.strategy_registry import REGISTRY, StrategyMeta
        REGISTRY.register(StrategyMeta(
            id="s9_emode_looping",
            name="S9 — Aave E-Mode USDC Looping",
            type="yield_loop",
            risk_tier="T3",
            target_apy_min=6.0,
            target_apy_max=9.0,
            max_drawdown_pct=5.0,
            description=(
                "Aave E-Mode USDC looping: deposit USDC → borrow USDE/DAI (≤94% LTV) → "
                "reinvest in Pendle/Morpho. Net APY = supply + ltv*(reinvest-borrow). "
                "HF monitoring: warn<1.5, emergency<1.2 → auto-deleverage to 60% LTV. "
                "Borrow spike (>8%) → deleverage. PAPER TRADING ONLY until ADR approved."
            ),
            module="strategies.emode_looping",
            handler_class="EModeLoopingStrategy",
            tags=["emode", "looping", "leverage", "aave", "morpho", "pendle", "t3", "paper_only"],
        ))
        log.debug("S9 EModeLoopingStrategy registered in StrategyRegistry.")
    except Exception as exc:
        log.warning("S9 auto-registration failed: %s", exc)


_register()
