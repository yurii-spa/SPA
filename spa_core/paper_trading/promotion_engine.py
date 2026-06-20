"""
spa_core/paper_trading/promotion_engine.py — Tournament auto-promotion engine

PromotionEngine: автоматический promote/demote/kill стратегий по tournament метрикам.
Решения принимаются детерминированно по 30-дневным метрикам из TournamentEvaluator.

Правила:
  - Минимум MIN_DAYS=14 дней для любого решения
  - Kill: drawdown < -10% ИЛИ Calmar < -0.5
  - Promote: Sharpe > 0.8
  - Demote: Sharpe < 0.0
  - Hold: всё остальное

Запись: data/promotion_report.json (атомарная: tmp + os.replace).

LLM ЗАПРЕЩЁН. Только stdlib.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
from spa_core.utils.atomic import atomic_save


# ─── Константы ────────────────────────────────────────────────────────────────

PROMOTE_SHARPE: float = 0.8     # 30-дневный Sharpe > 0.8 → promote
DEMOTE_SHARPE: float = 0.0      # 30-дневный Sharpe < 0.0 → demote
KILL_DRAWDOWN: float = -0.10    # drawdown < -10% → kill
KILL_CALMAR: float = -0.5       # Calmar < -0.5 → kill
MIN_DAYS: int = 14              # минимум дней для принятия решения

# Лимиты аллокации для apply_decisions
ALLOC_CAP: float = 0.30         # верхний предел аллокации (+5% promote)
ALLOC_FLOOR: float = 0.0        # нижний предел аллокации (demote)
ALLOC_STEP: float = 0.05        # шаг изменения аллокации (±5%)

PROMOTION_REPORT_FILENAME = "promotion_report.json"

# Допустимые действия
ACTION_PROMOTE = "promote"
ACTION_DEMOTE = "demote"
ACTION_KILL = "kill"
ACTION_HOLD = "hold"


# ─── Dataclass ────────────────────────────────────────────────────────────────

@dataclass
class PromotionDecision:
    """Решение engine'а по одной стратегии.

    Attributes:
        strategy_id: идентификатор стратегии (e.g. "S0", "S1")
        action:      одно из "promote" | "demote" | "kill" | "hold"
        reason:      человекочитаемое объяснение решения
        metrics:     снимок метрик на момент принятия решения
        ts:          ISO-8601 timestamp принятия решения (UTC)
    """
    strategy_id: str
    action: str
    reason: str
    metrics: Dict
    ts: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict:
        """Сериализация в словарь для JSON."""
        return {
            "strategy_id": self.strategy_id,
            "action": self.action,
            "reason": self.reason,
            "metrics": self.metrics,
            "ts": self.ts,
        }


# ─── PromotionEngine ──────────────────────────────────────────────────────────

class PromotionEngine:
    """Автоматический promote/demote/kill стратегий по 30-дневным метрикам.

    Детерминированный движок: LLM запрещён.
    Порядок проверок в evaluate():
      1. Недостаточно данных (days < MIN_DAYS) → hold
      2. Kill-условия (drawdown или Calmar) → kill
      3. Promote (Sharpe) → promote
      4. Demote (Sharpe) → demote
      5. Иначе → hold

    Usage::
        engine = PromotionEngine()
        decision = engine.evaluate("S1", metrics)
        decisions = engine.evaluate_all(metrics_dict)
        new_allocs = engine.apply_decisions(decisions, current_allocs)
        engine.save_report(decisions, Path("data/"))
    """

    # Константы класса (доступны как PromotionEngine.PROMOTE_SHARPE и т.д.)
    PROMOTE_SHARPE: float = PROMOTE_SHARPE
    DEMOTE_SHARPE: float = DEMOTE_SHARPE
    KILL_DRAWDOWN: float = KILL_DRAWDOWN
    KILL_CALMAR: float = KILL_CALMAR
    MIN_DAYS: int = MIN_DAYS

    def evaluate(self, strategy_id: str, metrics: Dict) -> PromotionDecision:
        """Принять решение по одной стратегии на основе её метрик.

        Args:
            strategy_id: идентификатор стратегии
            metrics: словарь с полями:
                - sharpe_30d (float | None)
                - calmar_30d (float | None)
                - max_drawdown_pct (float): отрицательное число или 0;
                  e.g. -0.15 = просадка 15%
                - days_active (int)

        Returns:
            PromotionDecision с выбранным action и обоснованием.
        """
        days = int(metrics.get("days_active", 0))
        sharpe = metrics.get("sharpe_30d")
        calmar = metrics.get("calmar_30d")
        drawdown = metrics.get("max_drawdown_pct", 0.0)

        # 1. Недостаточно данных
        if days < MIN_DAYS:
            return PromotionDecision(
                strategy_id=strategy_id,
                action=ACTION_HOLD,
                reason=(
                    f"Недостаточно данных: {days} дн. < MIN_DAYS={MIN_DAYS}. "
                    "Решение отложено."
                ),
                metrics=dict(metrics),
            )

        # 2. Kill-условия (проверяются раньше promote/demote)
        kill_reasons = []

        if drawdown is not None and drawdown < KILL_DRAWDOWN:
            kill_reasons.append(
                f"max_drawdown_pct={drawdown:.4f} < KILL_DRAWDOWN={KILL_DRAWDOWN}"
            )

        if calmar is not None and calmar < KILL_CALMAR:
            kill_reasons.append(
                f"calmar_30d={calmar:.4f} < KILL_CALMAR={KILL_CALMAR}"
            )

        if kill_reasons:
            return PromotionDecision(
                strategy_id=strategy_id,
                action=ACTION_KILL,
                reason="Kill: " + "; ".join(kill_reasons),
                metrics=dict(metrics),
            )

        # 3. Promote: Sharpe > порога
        if sharpe is not None and sharpe > PROMOTE_SHARPE:
            return PromotionDecision(
                strategy_id=strategy_id,
                action=ACTION_PROMOTE,
                reason=(
                    f"Promote: sharpe_30d={sharpe:.4f} > PROMOTE_SHARPE={PROMOTE_SHARPE}"
                ),
                metrics=dict(metrics),
            )

        # 4. Demote: Sharpe < 0
        if sharpe is not None and sharpe < DEMOTE_SHARPE:
            return PromotionDecision(
                strategy_id=strategy_id,
                action=ACTION_DEMOTE,
                reason=(
                    f"Demote: sharpe_30d={sharpe:.4f} < DEMOTE_SHARPE={DEMOTE_SHARPE}"
                ),
                metrics=dict(metrics),
            )

        # 5. Hold: всё остальное
        reason_parts = []
        if sharpe is not None:
            reason_parts.append(
                f"sharpe_30d={sharpe:.4f} в диапазоне "
                f"[{DEMOTE_SHARPE}, {PROMOTE_SHARPE}]"
            )
        else:
            reason_parts.append("sharpe_30d недоступен")

        return PromotionDecision(
            strategy_id=strategy_id,
            action=ACTION_HOLD,
            reason="Hold: " + "; ".join(reason_parts),
            metrics=dict(metrics),
        )

    def evaluate_all(
        self, metrics_dict: Dict[str, Dict]
    ) -> List[PromotionDecision]:
        """Принять решения по всем стратегиям.

        Args:
            metrics_dict: {strategy_id: metrics_dict} — словарь метрик по всем
                          стратегиям.

        Returns:
            list[PromotionDecision] в том же порядке, что и входной словарь.
        """
        decisions: List[PromotionDecision] = []
        for strategy_id, metrics in metrics_dict.items():
            decision = self.evaluate(strategy_id, metrics)
            decisions.append(decision)
        return decisions

    def apply_decisions(
        self,
        decisions: List[PromotionDecision],
        allocation_map: Dict[str, float],
    ) -> Dict[str, float]:
        """Применить решения к аллокациям портфеля.

        Правила изменения аллокации:
          - promote: allocation += 5% (cap 30%)
          - demote:  allocation -= 5% (floor 0%)
          - kill:    allocation = 0%
          - hold:    без изменений

        Стратегии из decisions, отсутствующие в allocation_map, добавляются
        с базовой аллокацией 0.0 (и затем применяется решение).

        Args:
            decisions: список решений от evaluate_all / evaluate
            allocation_map: текущие аллокации {strategy_id: fraction [0, 1]}

        Returns:
            Новый словарь аллокаций с применёнными решениями.
        """
        # Копируем исходную карту; атомарность — создаём новый dict
        result: Dict[str, float] = dict(allocation_map)

        for decision in decisions:
            sid = decision.strategy_id
            current = result.get(sid, 0.0)

            if decision.action == ACTION_PROMOTE:
                # +5%, cap 30%
                new_alloc = min(current + ALLOC_STEP, ALLOC_CAP)

            elif decision.action == ACTION_DEMOTE:
                # -5%, floor 0%
                new_alloc = max(current - ALLOC_STEP, ALLOC_FLOOR)

            elif decision.action == ACTION_KILL:
                # обнулить позицию
                new_alloc = 0.0

            else:
                # hold — без изменений
                new_alloc = current

            result[sid] = new_alloc

        return result

    def save_report(
        self,
        decisions: List[PromotionDecision],
        path: Path,
    ) -> Path:
        """Атомарная запись отчёта о решениях в JSON-файл.

        Если path — директория, файл сохраняется как
        path/promotion_report.json. Если path — файл — записывается туда.

        Атомарность: tmp-файл + os.replace (никогда прямой open для записи).

        Args:
            decisions: список PromotionDecision для записи
            path:      директория или явный путь к файлу

        Returns:
            Path записанного файла.
        """
        path = Path(path)

        # Определяем итоговый путь к файлу
        if path.is_dir() or (not path.suffix and not path.exists()):
            # path является директорией (существующей или ожидаемой)
            path.mkdir(parents=True, exist_ok=True)
            out_path = path / PROMOTION_REPORT_FILENAME
        else:
            # path — явный файл
            path.parent.mkdir(parents=True, exist_ok=True)
            out_path = path

        # Формируем документ
        doc = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source": "promotion_engine",
            "is_demo": False,
            "num_decisions": len(decisions),
            "thresholds": {
                "PROMOTE_SHARPE": PROMOTE_SHARPE,
                "DEMOTE_SHARPE": DEMOTE_SHARPE,
                "KILL_DRAWDOWN": KILL_DRAWDOWN,
                "KILL_CALMAR": KILL_CALMAR,
                "MIN_DAYS": MIN_DAYS,
            },
            "decisions": [d.to_dict() for d in decisions],
        }

        # Атомарная запись: tmp → os.replace
        tmp_dir = out_path.parent
        atomic_save(doc, str(out_path))
        return out_path
