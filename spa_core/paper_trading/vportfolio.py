"""
spa_core/paper_trading/vportfolio.py — Virtual Portfolio Manager

VPortfolio  : виртуальный портфель одной стратегии ($100K бумажных денег).
VPortfolioManager : управляет N vPortfolio параллельно; simulate_day() обновляет
                    все портфели; атомарная запись в data/vportfolios.json.

Правила:
  - stdlib only, no external deps
  - Атомарные записи (mkstemp + os.replace)
  - read-only / advisory; никаких вызовов execution/ или risk-агентов
  - is_demo: False — реальный paper-track (не демо)
  - Каждый VPortfolio независим, виртуальный капитал $100K
  - simulate_day принимает apy_data: dict[protocol_key -> apy_pct (float)]
    и начисляет дневной yield на каждую позицию по фактическому APY
    из стратегической аллокации.
"""
from __future__ import annotations

import json
import math
import os
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from spa_core.paper_trading.strategy_registry import (
    STRATEGY_REGISTRY,
    StrategyConfig,
    active_strategies,
)

# ─── Константы ────────────────────────────────────────────────────────────────

VPORTFOLIOS_FILENAME = "vportfolios.json"
INITIAL_CAPITAL_USD = 100_000.0
MAX_EQUITY_HISTORY = 730      # ~2 года дневных точек
MAX_RETURNS_HISTORY = 730     # параллельный ring-buffer

# ─── Helpers ──────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        x = float(v)
        return x if math.isfinite(x) else default
    except (TypeError, ValueError):
        return default


# ─── VPortfolio ───────────────────────────────────────────────────────────────

@dataclass
class VPortfolio:
    """Виртуальный портфель одной стратегии.

    Attributes:
        strategy_id: e.g. "S0", "S1", …
        capital_usd: начальный виртуальный капитал (всегда 100K)
        positions: dict[protocol_key -> usd_value]
        cash_usd: свободный кэш
        equity_history: list[{"date": str, "equity": float, "apy_today": float}]
        daily_returns: list[float] — дневные доходности (fraction, не %)
        created_at: ISO timestamp создания
        last_updated: ISO timestamp последнего simulate_day
        total_yield_usd: накопленный yield с начала (USD)
        days_simulated: количество симулированных дней
        peak_equity: максимальная equity (для drawdown)
        status: отражает статус из STRATEGY_REGISTRY (sync при load/save)
    """
    strategy_id: str
    capital_usd: float = INITIAL_CAPITAL_USD
    positions: Dict[str, float] = field(default_factory=dict)
    cash_usd: float = INITIAL_CAPITAL_USD
    equity_history: List[Dict] = field(default_factory=list)
    daily_returns: List[float] = field(default_factory=list)
    created_at: str = field(default_factory=_now_iso)
    last_updated: str = field(default_factory=_now_iso)
    total_yield_usd: float = 0.0
    days_simulated: int = 0
    peak_equity: float = INITIAL_CAPITAL_USD
    status: str = "active"

    # ── Derived properties ────────────────────────────────────────────────────

    @property
    def current_equity(self) -> float:
        """Текущая стоимость портфеля (позиции + кэш)."""
        return sum(self.positions.values()) + self.cash_usd

    @property
    def drawdown_pct(self) -> float:
        """Текущая просадка от peak (0..1)."""
        eq = self.current_equity
        if self.peak_equity <= 0:
            return 0.0
        return max(0.0, (self.peak_equity - eq) / self.peak_equity)

    @property
    def total_return_pct(self) -> float:
        """Суммарная доходность с начала (%)."""
        if self.capital_usd <= 0:
            return 0.0
        return (self.current_equity - self.capital_usd) / self.capital_usd * 100.0

    def _initialize_positions(self) -> None:
        """Инициализировать позиции из аллокаций стратегии.

        Вызывается один раз при создании VPortfolio.
        Без реальных APY данных — аллокации распределяются по целевым весам.
        """
        cfg = STRATEGY_REGISTRY.get(self.strategy_id)
        if cfg is None:
            return
        self.positions = {}
        total_alloc = sum(cfg.allocations.values())
        total_alloc = min(total_alloc, 0.95)  # гарантируем ≥5% кэш
        for protocol, weight in cfg.allocations.items():
            # Пропускаем внешние/watchlist протоколы (pendle_pt, sky_susds)
            if protocol in ("pendle_pt", "sky_susds"):
                continue
            alloc_usd = self.capital_usd * weight
            if alloc_usd > 0:
                self.positions[protocol] = alloc_usd
        positions_total = sum(self.positions.values())
        self.cash_usd = max(0.0, self.capital_usd - positions_total)

    def simulate_day(
        self,
        apy_data: Dict[str, float],
        date_str: Optional[str] = None,
    ) -> float:
        """Начислить дневной yield на все позиции.

        Args:
            apy_data: dict[protocol_key -> apy_pct (годовой %)], e.g.
                      {"aave_v3": 3.5, "morpho_blue": 6.2, ...}
            date_str: "YYYY-MM-DD"; если None → _today_str()

        Returns:
            daily_yield_usd — сумма начисленного yield за день.
        """
        if date_str is None:
            date_str = _today_str()

        daily_yield_usd = 0.0
        prev_equity = self.current_equity

        # Начисляем yield по каждой позиции
        for protocol, pos_usd in list(self.positions.items()):
            apy_pct = _safe_float(apy_data.get(protocol), default=0.0)
            if apy_pct <= 0:
                continue
            daily_yield = pos_usd * apy_pct / 100.0 / 365.0
            self.positions[protocol] = pos_usd + daily_yield
            daily_yield_usd += daily_yield

        # Обновляем агрегаты
        self.total_yield_usd += daily_yield_usd
        self.days_simulated += 1

        new_equity = self.current_equity
        if new_equity > self.peak_equity:
            self.peak_equity = new_equity

        # Дневная доходность
        if prev_equity > 0:
            daily_ret = (new_equity - prev_equity) / prev_equity
        else:
            daily_ret = 0.0
        self.daily_returns.append(daily_ret)
        if len(self.daily_returns) > MAX_RETURNS_HISTORY:
            self.daily_returns = self.daily_returns[-MAX_RETURNS_HISTORY:]

        # APY реализованный сегодня
        apy_today = daily_ret * 365.0 * 100.0

        # Equity history
        self.equity_history.append({
            "date": date_str,
            "equity": round(new_equity, 6),
            "apy_today": round(apy_today, 4),
            "daily_yield_usd": round(daily_yield_usd, 6),
            "drawdown_pct": round(self.drawdown_pct, 6),
        })
        if len(self.equity_history) > MAX_EQUITY_HISTORY:
            self.equity_history = self.equity_history[-MAX_EQUITY_HISTORY:]

        self.last_updated = _now_iso()
        return daily_yield_usd

    def rebalance(self, apy_data: Dict[str, float]) -> None:
        """Ребалансировать позиции по аллокациям стратегии.

        Использует текущую equity как базу.
        Вызывается periodically (например, еженедельно) из VPortfolioManager.
        """
        cfg = STRATEGY_REGISTRY.get(self.strategy_id)
        if cfg is None:
            return

        available = set(apy_data.keys())
        eff_alloc = cfg.effective_allocations(available)
        if not eff_alloc:
            return

        total_eq = self.current_equity
        new_positions: Dict[str, float] = {}
        alloc_sum = sum(eff_alloc.values())
        alloc_sum = min(alloc_sum, 0.95)

        for protocol, weight in eff_alloc.items():
            new_positions[protocol] = total_eq * weight

        positions_total = sum(new_positions.values())
        self.positions = new_positions
        self.cash_usd = max(0.0, total_eq - positions_total)

    # ── Serialization ─────────────────────────────────────────────────────────

    def to_dict(self) -> Dict:
        return {
            "strategy_id": self.strategy_id,
            "capital_usd": self.capital_usd,
            "positions": self.positions,
            "cash_usd": round(self.cash_usd, 6),
            "equity_history": self.equity_history,
            "daily_returns": self.daily_returns,
            "created_at": self.created_at,
            "last_updated": self.last_updated,
            "total_yield_usd": round(self.total_yield_usd, 6),
            "days_simulated": self.days_simulated,
            "peak_equity": round(self.peak_equity, 6),
            "status": self.status,
            # Derived (computed at save time for easy dashboard reading)
            "current_equity": round(self.current_equity, 6),
            "drawdown_pct": round(self.drawdown_pct, 6),
            "total_return_pct": round(self.total_return_pct, 4),
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "VPortfolio":
        vp = cls(
            strategy_id=d["strategy_id"],
            capital_usd=_safe_float(d.get("capital_usd"), INITIAL_CAPITAL_USD),
            positions=dict(d.get("positions") or {}),
            cash_usd=_safe_float(d.get("cash_usd"), 0.0),
            equity_history=list(d.get("equity_history") or []),
            daily_returns=list(d.get("daily_returns") or []),
            created_at=d.get("created_at") or _now_iso(),
            last_updated=d.get("last_updated") or _now_iso(),
            total_yield_usd=_safe_float(d.get("total_yield_usd"), 0.0),
            days_simulated=int(d.get("days_simulated") or 0),
            peak_equity=_safe_float(
                d.get("peak_equity"), _safe_float(d.get("capital_usd"), INITIAL_CAPITAL_USD)
            ),
            status=d.get("status") or "active",
        )
        return vp


# ─── VPortfolioManager ────────────────────────────────────────────────────────

class VPortfolioManager:
    """Управляет N виртуальных портфелей параллельно.

    Создаётся через :meth:`create_all` (новый запуск) или :meth:`load`
    (восстановление из data/vportfolios.json).

    Операции:
        simulate_day(apy_data) — обновляет все ACTIVE/PROMOTED портфели
        save()                 — атомарная запись в data/vportfolios.json
        load(data_dir)         — загрузка из файла (или create_all если нет)
        get(strategy_id)       — получить конкретный VPortfolio
        kill(strategy_id)      — пометить портфель как killed
        promote(strategy_id)   — пометить как promoted
    """

    def __init__(
        self,
        portfolios: Optional[Dict[str, VPortfolio]] = None,
        data_dir: Optional[Path] = None,
    ) -> None:
        self.portfolios: Dict[str, VPortfolio] = portfolios or {}
        self._data_dir: Path = data_dir or (
            Path(__file__).resolve().parents[2] / "data"
        )

    # ── Factory methods ───────────────────────────────────────────────────────

    @classmethod
    def create_all(
        cls,
        data_dir: Optional[Path] = None,
        capital_usd: float = INITIAL_CAPITAL_USD,
    ) -> "VPortfolioManager":
        """Создать VPortfolio для всех стратегий реестра (initial_capital $100K).

        Позиции инициализируются по целевым аллокациям без реальных APY.
        """
        data_dir = data_dir or (Path(__file__).resolve().parents[2] / "data")
        portfolios: Dict[str, VPortfolio] = {}
        for sid, cfg in STRATEGY_REGISTRY.items():
            vp = VPortfolio(
                strategy_id=sid,
                capital_usd=capital_usd,
                status=cfg.status,
            )
            vp.cash_usd = capital_usd  # Начинаем с полного кэша
            vp._initialize_positions()  # Распределяем по аллокациям
            vp.peak_equity = vp.current_equity
            portfolios[sid] = vp
        return cls(portfolios=portfolios, data_dir=data_dir)

    @classmethod
    def load(
        cls,
        data_dir: Optional[Path] = None,
        capital_usd: float = INITIAL_CAPITAL_USD,
    ) -> "VPortfolioManager":
        """Загрузить из data/vportfolios.json; если файл отсутствует — create_all.

        Новые стратегии, добавленные в STRATEGY_REGISTRY после последнего
        сохранения, автоматически создаются и добавляются.
        """
        data_dir = data_dir or (Path(__file__).resolve().parents[2] / "data")
        vport_path = data_dir / VPORTFOLIOS_FILENAME

        if not vport_path.exists():
            return cls.create_all(data_dir=data_dir, capital_usd=capital_usd)

        try:
            with open(vport_path, "r", encoding="utf-8") as f:
                doc = json.load(f)
        except (json.JSONDecodeError, OSError):
            return cls.create_all(data_dir=data_dir, capital_usd=capital_usd)

        raw_portfolios = doc.get("portfolios") or {}
        portfolios: Dict[str, VPortfolio] = {}
        for sid, raw in raw_portfolios.items():
            try:
                portfolios[sid] = VPortfolio.from_dict(raw)
            except Exception:
                # Corrupt entry → fresh portfolio for this strategy
                if sid in STRATEGY_REGISTRY:
                    vp = VPortfolio(strategy_id=sid, capital_usd=capital_usd)
                    vp._initialize_positions()
                    portfolios[sid] = vp

        # Добавить новые стратегии, которых нет в файле
        for sid, cfg in STRATEGY_REGISTRY.items():
            if sid not in portfolios:
                vp = VPortfolio(
                    strategy_id=sid,
                    capital_usd=capital_usd,
                    status=cfg.status,
                )
                vp._initialize_positions()
                portfolios[sid] = vp

        return cls(portfolios=portfolios, data_dir=data_dir)

    # ── Core operations ───────────────────────────────────────────────────────

    def simulate_day(
        self,
        apy_data: Dict[str, float],
        date_str: Optional[str] = None,
        rebalance: bool = False,
    ) -> Dict[str, float]:
        """Обновить все активные vPortfolio с текущими APY.

        Args:
            apy_data: dict[protocol_key -> annual_apy_pct]
            date_str: "YYYY-MM-DD"; None → сегодня UTC
            rebalance: если True — перед yield начислить ребалансировку.

        Returns:
            dict[strategy_id -> daily_yield_usd] для всех обработанных стратегий.
        """
        if date_str is None:
            date_str = _today_str()

        results: Dict[str, float] = {}
        for sid, vp in self.portfolios.items():
            if vp.status in ("killed", "paused"):
                continue
            # Синхронизируем статус из реестра
            cfg = STRATEGY_REGISTRY.get(sid)
            if cfg is not None and cfg.status in ("killed", "paused"):
                vp.status = cfg.status
                continue

            if rebalance:
                vp.rebalance(apy_data)

            daily_yield = vp.simulate_day(apy_data, date_str=date_str)
            results[sid] = daily_yield

        return results

    def kill(self, strategy_id: str) -> None:
        """Пометить портфель и реестр как killed."""
        if strategy_id in self.portfolios:
            self.portfolios[strategy_id].status = "killed"
        if strategy_id in STRATEGY_REGISTRY:
            STRATEGY_REGISTRY[strategy_id].status = "killed"

    def promote(self, strategy_id: str) -> None:
        """Пометить портфель и реестр как promoted."""
        if strategy_id in self.portfolios:
            self.portfolios[strategy_id].status = "promoted"
        if strategy_id in STRATEGY_REGISTRY:
            STRATEGY_REGISTRY[strategy_id].status = "promoted"

    def pause(self, strategy_id: str) -> None:
        """Приостановить стратегию."""
        if strategy_id in self.portfolios:
            self.portfolios[strategy_id].status = "paused"

    def resume(self, strategy_id: str) -> None:
        """Возобновить стратегию."""
        if strategy_id in self.portfolios:
            self.portfolios[strategy_id].status = "active"

    def get(self, strategy_id: str) -> Optional[VPortfolio]:
        """Получить vPortfolio по strategy_id."""
        return self.portfolios.get(strategy_id)

    def active_count(self) -> int:
        """Количество активных/promoted портфелей."""
        return sum(
            1 for vp in self.portfolios.values()
            if vp.status in ("active", "promoted")
        )

    # ── Persistence ───────────────────────────────────────────────────────────

    def save(self) -> Path:
        """Атомарная запись data/vportfolios.json (mkstemp + os.replace).

        Returns:
            Path к записанному файлу.
        """
        self._data_dir.mkdir(parents=True, exist_ok=True)
        out_path = self._data_dir / VPORTFOLIOS_FILENAME

        doc = {
            "generated_at": _now_iso(),
            "source": "vportfolio_manager",
            "is_demo": False,
            "num_portfolios": len(self.portfolios),
            "num_active": self.active_count(),
            "strategy_ids": list(self.portfolios.keys()),
            "portfolios": {
                sid: vp.to_dict()
                for sid, vp in self.portfolios.items()
            },
        }

        # Атомарная запись
        fd, tmp_path = tempfile.mkstemp(
            prefix=".tmp_vportfolios_",
            dir=self._data_dir,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(doc, f, indent=2, ensure_ascii=False)
                f.write("\n")
            os.replace(tmp_path, out_path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

        return out_path

    def summary(self) -> List[Dict]:
        """Краткая сводка по всем портфелям для отладки/отчёта."""
        rows = []
        for sid, vp in sorted(self.portfolios.items()):
            rows.append({
                "strategy_id": sid,
                "status": vp.status,
                "equity": round(vp.current_equity, 2),
                "total_return_pct": round(vp.total_return_pct, 4),
                "drawdown_pct": round(vp.drawdown_pct, 6),
                "days_simulated": vp.days_simulated,
                "total_yield_usd": round(vp.total_yield_usd, 2),
            })
        return rows
