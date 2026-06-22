"""AllocationTuner (MP-207) — grid-search оптимизатор аллокации.

Находит оптимальные веса портфеля, максимизируя Sharpe-подобный показатель
при соблюдении constraints: T1/T2 caps, TVL floor, per-protocol cap.

Только stdlib Python. Atomic writes. Строго read-only относительно капитала —
никаких imports из execution/ или risk-агентов.
"""
from __future__ import annotations

import json
import logging
import math
import os
import random
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from spa_core.utils.atomic import atomic_save

log = logging.getLogger("spa.tuner")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"
_ORCH_STATUS = _DEFAULT_DATA_DIR / "adapter_orchestrator_status.json"
_CURRENT_ALLOC = _DEFAULT_DATA_DIR / "current_positions.json"
_TUNER_OUT = _DEFAULT_DATA_DIR / "tuner_suggestion.json"

_EPS = 1e-9
# Торговые дни в году (365 для круглосуточного DeFi)
_DAYS_YEAR = 365.0


# ─── Dataclasses ─────────────────────────────────────────────────────────────


@dataclass
class TunerConstraints:
    """Ограничения для оптимизатора — зеркало RiskPolicy v1.0."""
    t1_min: float = 0.55          # Min T1 allocation (55%)
    t2_max: float = 0.35          # Max T2 total allocation (35%)
    per_protocol_max: float = 0.25  # Max single protocol (25%, снижен с 40%)
    tvl_floor_usd: float = 5_000_000.0  # Min TVL пула
    min_protocols: int = 3        # Min активных протоколов
    max_protocols: int = 6        # Max активных протоколов (не index fund!)
    cash_min: float = 0.05        # Min cash buffer (5%)
    apy_min: float = 1.0          # Min APY % для включения
    apy_max: float = 30.0         # Max APY % для включения


@dataclass
class TunerResult:
    """Результат оптимизации аллокации."""
    optimal_weights: Dict[str, float]    # {protocol_id: weight}
    expected_apy: float                   # Взвешенный средний APY
    expected_sharpe: float               # Оценка Sharpe
    backtest_return: float               # Backtest total return %
    backtest_days: int
    improvements: List[str]              # Что изменилось vs текущее
    protocol_breakdown: List[dict]       # [{id, weight, apy, tier}]
    objective_score: float               # Значение целевой функции
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        return asdict(self)


# ─── AllocationTuner ──────────────────────────────────────────────────────────


class AllocationTuner:
    """Grid-search оптимизатор весов портфеля (pure Python, no scipy/numpy)."""

    def __init__(self, constraints: Optional[TunerConstraints] = None):
        self.constraints = constraints or TunerConstraints()

    # ── вспомогательные методы ─────────────────────────────────────────────

    def _eligible_adapters(self, adapter_data: List[dict]) -> List[dict]:
        """Отфильтровывает адаптеры по TVL floor и APY bounds."""
        c = self.constraints
        result = []
        for a in adapter_data:
            tvl = float(a.get("tvl_usd", 0.0) or 0.0)
            apy = float(a.get("apy", 0.0) or 0.0)
            if tvl < c.tvl_floor_usd:
                continue
            if apy < c.apy_min or apy > c.apy_max:
                continue
            result.append(a)
        return result

    def _t1_t2_split(self, adapter_data: List[dict]) -> Tuple[List[dict], List[dict]]:
        """Разбивает на T1 и T2 адаптеры."""
        t1 = [a for a in adapter_data if str(a.get("tier", "T2")).upper() == "T1"]
        t2 = [a for a in adapter_data if str(a.get("tier", "T2")).upper() != "T1"]
        return t1, t2

    def _normalize(self, weights: Dict[str, float]) -> Dict[str, float]:
        """Нормализует веса к сумме 1.0."""
        total = sum(weights.values())
        if total < _EPS:
            n = len(weights)
            return {k: 1.0 / n for k in weights} if n > 0 else {}
        return {k: v / total for k, v in weights.items()}

    def _weighted_apy(
        self, weights: Dict[str, float], adapter_data: List[dict]
    ) -> float:
        """Вычисляет взвешенный средний APY (в %)."""
        apy_map = {a["id"]: float(a.get("apy", 0.0) or 0.0) for a in adapter_data}
        return sum(weights.get(pid, 0.0) * apy_map.get(pid, 0.0) for pid in weights)

    def _concentration_penalty(self, weights: Dict[str, float]) -> float:
        """Штраф за концентрацию (HHI-подобный)."""
        hhi = sum(w * w for w in weights.values())
        # hhi = 1 означает всё в одном протоколе → большой штраф
        return hhi * 0.5

    def _check_constraints(
        self,
        weights: Dict[str, float],
        adapter_data: List[dict],
    ) -> Tuple[bool, float]:
        """Проверяет constraints, возвращает (valid, penalty).

        penalty > 0 если нарушены soft constraints.
        valid=False если нарушены hard constraints (нельзя использовать вообще).
        """
        c = self.constraints
        tier_map = {a["id"]: str(a.get("tier", "T2")).upper() for a in adapter_data}

        penalty = 0.0

        # 1) per-protocol cap
        for pid, w in weights.items():
            if w > c.per_protocol_max + _EPS:
                penalty += (w - c.per_protocol_max) * 10.0

        # 2) T1 minimum
        t1_total = sum(w for pid, w in weights.items()
                       if tier_map.get(pid, "T2") == "T1")
        if t1_total < c.t1_min - _EPS:
            deficit = c.t1_min - t1_total
            penalty += deficit * 8.0

        # 3) T2 maximum
        t2_total = sum(w for pid, w in weights.items()
                       if tier_map.get(pid, "T2") != "T1")
        if t2_total > c.t2_max + _EPS:
            excess = t2_total - c.t2_max
            penalty += excess * 8.0

        # 4) минимальное количество протоколов
        active = sum(1 for w in weights.values() if w > 0.01)
        if active < c.min_protocols:
            penalty += (c.min_protocols - active) * 2.0

        # 5) cash buffer (сумма весов не превышает 1 - cash_min)
        total_w = sum(weights.values())
        if total_w > 1.0 - c.cash_min + _EPS:
            penalty += (total_w - (1.0 - c.cash_min)) * 5.0

        # Hard constraint: сумма весов не может превышать 1.0
        if total_w > 1.0 + 0.001:
            return False, penalty + 100.0

        return True, penalty

    # ── целевая функция ────────────────────────────────────────────────────

    def _score_allocation(
        self,
        weights: Dict[str, float],
        adapter_data: List[dict],
    ) -> float:
        """Вычисляет objective score для аллокации.

        Score = weighted_apy - concentration_penalty - constraint_violations
        Выше = лучше.
        """
        if not weights:
            return -999.0

        w_apy = self._weighted_apy(weights, adapter_data)
        conc_pen = self._concentration_penalty(weights)
        valid, const_pen = self._check_constraints(weights, adapter_data)

        if not valid:
            return -999.0

        return w_apy - conc_pen - const_pen

    # ── генерация кандидатов ───────────────────────────────────────────────

    def _generate_candidates(
        self,
        adapter_data: List[dict],
        n_candidates: int = 200,
    ) -> List[Dict[str, float]]:
        """Генерирует кандидаты аллокаций через grid search + random sampling.

        Уважает структуру T1/T2 и ограничения.
        """
        c = self.constraints
        t1, t2 = self._t1_t2_split(adapter_data)
        ids = [a["id"] for a in adapter_data]
        t1_ids = [a["id"] for a in t1]
        t2_ids = [a["id"] for a in t2]

        if not ids:
            return []

        candidates: List[Dict[str, float]] = []
        rng = random.Random(42)  # детерминированный seed для воспроизводимости

        # ── 1. Базовые детерминированные кандидаты ────────────────────────

        # Все равные веса (eligible protocols)
        n = len(ids)
        if n > 0:
            eq = {pid: 1.0 / n for pid in ids}
            candidates.append(eq)

        # APY-пропорциональный
        apy_map = {a["id"]: max(float(a.get("apy", 0.0) or 0.0), 0.0) for a in adapter_data}
        apy_total = sum(apy_map.values())
        if apy_total > _EPS:
            apy_w = {pid: apy_map[pid] / apy_total for pid in ids}
            candidates.append(apy_w)

        # T1-якорь максимальный + T2 равные
        if t1_ids:
            cand = {}
            t1_per = min(c.per_protocol_max, 1.0 / len(t1_ids))
            t1_total = t1_per * len(t1_ids)
            t2_budget = min(c.t2_max, 1.0 - t1_total - c.cash_min)
            t2_per = (t2_budget / len(t2_ids)) if t2_ids else 0.0
            t2_per = min(t2_per, c.per_protocol_max)
            for pid in t1_ids:
                cand[pid] = t1_per
            for pid in t2_ids:
                cand[pid] = t2_per
            candidates.append(cand)

        # T1-макс (один протокол) + T2
        for t1_anchor in t1_ids:
            cand = {pid: 0.0 for pid in ids}
            cand[t1_anchor] = c.per_protocol_max  # 40%
            # Остаток T1
            remaining_t1 = [p for p in t1_ids if p != t1_anchor]
            if remaining_t1:
                sub = min(c.t1_min - c.per_protocol_max, c.per_protocol_max)
                sub = max(sub, 0.0)
                for p in remaining_t1:
                    cand[p] = sub / len(remaining_t1)
            t1_used = sum(cand[p] for p in t1_ids)
            t2_budget = min(c.t2_max, 1.0 - t1_used - c.cash_min)
            t2_per = (t2_budget / len(t2_ids)) if t2_ids else 0.0
            t2_per = min(t2_per, c.per_protocol_max)
            for pid in t2_ids:
                cand[pid] = t2_per
            candidates.append(cand)

        # ── 2. Grid search по T1/T2 весам ─────────────────────────────────
        # Дискретная сетка: пробуем разные доли T1 (0.55 до 0.80 шагом 0.05)
        for t1_frac in [round(x * 0.05, 2) for x in range(11, 17)]:  # 0.55..0.80
            if not t1_ids:
                break
            t1_per = min(t1_frac / len(t1_ids), c.per_protocol_max)
            t2_budget = min(c.t2_max, 1.0 - t1_frac - c.cash_min)
            if t2_budget < 0:
                continue
            t2_per = (t2_budget / len(t2_ids)) if t2_ids else 0.0
            t2_per = min(t2_per, c.per_protocol_max)
            cand = {}
            for pid in t1_ids:
                cand[pid] = t1_per
            for pid in t2_ids:
                cand[pid] = t2_per
            candidates.append(cand)

        # ── 3. Random sampling с ограничениями ────────────────────────────
        n_random = max(0, n_candidates - len(candidates))
        for _ in range(n_random):
            cand: Dict[str, float] = {}

            # T1 веса: сумма в [t1_min, 1 - cash_min]
            t1_target = rng.uniform(c.t1_min, min(0.80, 1.0 - c.cash_min))
            if t1_ids:
                # Случайное разбиение T1 бюджета
                t1_raw = [rng.random() for _ in t1_ids]
                t1_sum = sum(t1_raw)
                for i, pid in enumerate(t1_ids):
                    raw_w = (t1_raw[i] / t1_sum) * t1_target
                    cand[pid] = min(raw_w, c.per_protocol_max)
                # Откалибруем, если обрезали до cap
                actual_t1 = sum(cand[p] for p in t1_ids)
                if actual_t1 < c.t1_min:
                    # добираем равномерно
                    deficit = c.t1_min - actual_t1
                    per = deficit / len(t1_ids)
                    for pid in t1_ids:
                        cand[pid] = min(cand[pid] + per, c.per_protocol_max)
            else:
                t1_target = 0.0

            # T2 веса: сумма ≤ t2_max
            actual_t1 = sum(cand.get(p, 0.0) for p in t1_ids)
            t2_budget = min(c.t2_max, 1.0 - actual_t1 - c.cash_min)
            t2_budget = max(t2_budget, 0.0)
            if t2_ids and t2_budget > _EPS:
                t2_target = rng.uniform(0.0, t2_budget)
                t2_raw = [rng.random() for _ in t2_ids]
                t2_sum = sum(t2_raw)
                for i, pid in enumerate(t2_ids):
                    raw_w = (t2_raw[i] / t2_sum) * t2_target
                    cand[pid] = min(raw_w, c.per_protocol_max)
            else:
                for pid in t2_ids:
                    cand[pid] = 0.0

            candidates.append(cand)

        # Убедимся, что все кандидаты содержат все протоколы (с 0.0 если нет)
        result = []
        for cand in candidates:
            full = {pid: cand.get(pid, 0.0) for pid in ids}
            # Проверяем: сумма не больше 1
            total = sum(full.values())
            if total > 1.0 + _EPS:
                scale = 1.0 / total
                full = {k: v * scale for k, v in full.items()}
            result.append(full)

        return result

    # ── оптимизация ────────────────────────────────────────────────────────

    def optimize(
        self,
        adapter_data: List[dict],
        current_weights: Optional[Dict[str, float]] = None,
        n_candidates: int = 500,
    ) -> TunerResult:
        """Находит оптимальную аллокацию через grid search.

        Если eligible-протоколов нет → возвращает all-cash результат.
        Если current_weights передан → вычисляет improvements.
        """
        eligible = self._eligible_adapters(adapter_data)

        # All-cash fallback
        if len(eligible) < self.constraints.min_protocols:
            log.warning(
                "Tuner: только %d eligible протоколов (нужно ≥ %d) → all-cash",
                len(eligible), self.constraints.min_protocols,
            )
            return TunerResult(
                optimal_weights={},
                expected_apy=0.0,
                expected_sharpe=0.0,
                backtest_return=0.0,
                backtest_days=0,
                improvements=["Нет eligible протоколов — all-cash"],
                protocol_breakdown=[],
                objective_score=-999.0,
            )

        candidates = self._generate_candidates(eligible, n_candidates=n_candidates)

        best_score = float("-inf")
        best_weights: Dict[str, float] = {}

        for cand in candidates:
            score = self._score_allocation(cand, eligible)
            if score > best_score:
                best_score = score
                best_weights = cand

        if not best_weights:
            # Если ни один кандидат не прошёл → equal weight
            n = len(eligible)
            best_weights = {a["id"]: 1.0 / n for a in eligible}
            best_score = self._score_allocation(best_weights, eligible)

        # Округляем веса до 6 знаков
        best_weights = {k: round(v, 6) for k, v in best_weights.items()}

        # Метрики
        w_apy = self._weighted_apy(best_weights, eligible)

        # Sharpe estimate: APY / std (упрощённая оценка через дисперсию весов)
        apy_map = {a["id"]: float(a.get("apy", 0.0) or 0.0) for a in eligible}
        variance = sum(
            best_weights.get(pid, 0.0) * ((apy_map.get(pid, 0.0) - w_apy) ** 2)
            for pid in apy_map
        )
        std_dev = math.sqrt(variance) if variance > 0 else 0.01
        # Risk-free rate для DeFi считаем ~3% (Aave baseline)
        rf_rate = 3.0
        sharpe = (w_apy - rf_rate) / std_dev if std_dev > _EPS else 0.0

        # Backtest
        bt = self.backtest_allocation(best_weights, eligible, days=30)

        # Improvements vs current
        improvements: List[str] = []
        if current_weights:
            cur_apy = self._weighted_apy(current_weights, eligible)
            if w_apy > cur_apy + 0.05:  # улучшение > 0.05% APY
                improvements.append(
                    f"APY: {cur_apy:.2f}% → {w_apy:.2f}% (+{w_apy - cur_apy:.2f}%)"
                )
            cur_hhi = sum(v * v for v in current_weights.values())
            best_hhi = sum(v * v for v in best_weights.values())
            if best_hhi < cur_hhi - 0.01:
                improvements.append(
                    f"Концентрация (HHI): {cur_hhi:.3f} → {best_hhi:.3f} (диверсификация)"
                )
            # Изменения в аллокации
            for pid in best_weights:
                cur_w = current_weights.get(pid, 0.0)
                new_w = best_weights.get(pid, 0.0)
                if abs(new_w - cur_w) > 0.05:
                    improvements.append(
                        f"{pid}: {cur_w * 100:.1f}% → {new_w * 100:.1f}%"
                    )
            if not improvements:
                improvements = ["Текущая аллокация близка к оптимальной"]

        # Protocol breakdown
        breakdown = []
        tier_map = {a["id"]: a.get("tier", "T2") for a in eligible}
        for pid, w in sorted(best_weights.items(), key=lambda x: -x[1]):
            if w > _EPS:
                breakdown.append({
                    "id": pid,
                    "weight": round(w, 4),
                    "weight_pct": round(w * 100, 2),
                    "apy": apy_map.get(pid, 0.0),
                    "tier": tier_map.get(pid, "T2"),
                })

        return TunerResult(
            optimal_weights=best_weights,
            expected_apy=round(w_apy, 4),
            expected_sharpe=round(sharpe, 4),
            backtest_return=round(bt["total_return_pct"], 4),
            backtest_days=bt["days"],
            improvements=improvements,
            protocol_breakdown=breakdown,
            objective_score=round(best_score, 6),
        )

    # ── backtest ───────────────────────────────────────────────────────────

    def backtest_allocation(
        self,
        weights: Dict[str, float],
        adapter_data: List[dict],
        days: int = 30,
    ) -> dict:
        """Симулирует доходность аллокации за `days` при фиксированных APY.

        Returns:
            {total_return_pct, daily_returns, annualized_pct, sharpe_estimate, days}
        """
        apy_map = {a["id"]: float(a.get("apy", 0.0) or 0.0) for a in adapter_data}

        # Дневная доходность каждого протокола
        daily_rates = {
            pid: apy_map.get(pid, 0.0) / 100.0 / _DAYS_YEAR
            for pid in weights
        }

        # Дневная доходность портфеля
        portfolio_daily = [
            sum(weights.get(pid, 0.0) * daily_rates.get(pid, 0.0) for pid in weights)
            for _ in range(days)
        ]

        # Compound total return
        total_return_pct = (
            math.prod(1.0 + r for r in portfolio_daily) - 1.0
        ) * 100.0

        annualized_pct = ((1.0 + total_return_pct / 100.0) ** (_DAYS_YEAR / days) - 1.0) * 100.0

        # Sharpe оценка на дневных доходностях
        if len(portfolio_daily) > 1:
            mean_r = sum(portfolio_daily) / len(portfolio_daily)
            variance = sum((r - mean_r) ** 2 for r in portfolio_daily) / (len(portfolio_daily) - 1)
            std_r = math.sqrt(variance) if variance > 0 else _EPS
            # Annualize Sharpe (rf=0 для упрощения backtest)
            sharpe = (mean_r / std_r) * math.sqrt(_DAYS_YEAR) if std_r > _EPS else 0.0
        else:
            sharpe = 0.0

        return {
            "total_return_pct": total_return_pct,
            "daily_returns": portfolio_daily,
            "annualized_pct": annualized_pct,
            "sharpe_estimate": round(sharpe, 4),
            "days": days,
        }


# ─── Загрузка данных ──────────────────────────────────────────────────────────


def _load_adapter_data(data_dir: Optional[Path] = None) -> List[dict]:
    """Загружает адаптерные данные из adapter_orchestrator_status.json.

    Нормализует ключи к контракту тюнера: {id, apy, tvl_usd, tier}.
    """
    ddir = data_dir or _DEFAULT_DATA_DIR
    path = ddir / "adapter_orchestrator_status.json"
    if not path.exists():
        log.warning("adapter_orchestrator_status.json не найден: %s", path)
        return []

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        log.warning("Ошибка чтения adapter_orchestrator_status.json: %s", e)
        return []

    result = []
    for a in raw.get("adapters", []):
        status = a.get("status", "ok")
        if status not in ("ok", "partial"):
            continue
        protocol = a.get("protocol", "")
        if not protocol:
            continue
        result.append({
            "id": protocol,
            "apy": float(a.get("apy_pct", 0.0) or 0.0),
            "tvl_usd": float(a.get("tvl_usd", 0.0) or 0.0),
            "tier": a.get("tier", "T2"),
        })
    return result


def _load_current_weights(data_dir: Optional[Path] = None) -> Optional[Dict[str, float]]:
    """Загружает текущие веса из current_positions.json.

    Нормализует USD-позиции к долям (weights). Возвращает None если файл
    недоступен или капитал равен нулю.
    """
    ddir = data_dir or _DEFAULT_DATA_DIR
    path = ddir / "current_positions.json"
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        log.warning("Ошибка чтения current_positions.json: %s", e)
        return None

    positions = raw.get("positions", {})
    if not positions:
        return None

    total = sum(float(v) for v in positions.values() if isinstance(v, (int, float)))
    if total < _EPS:
        return None

    return {k: float(v) / total for k, v in positions.items()
            if isinstance(v, (int, float)) and float(v) > 0}


def _atomic_write(path: Path, data: dict) -> None:
    """Атомарная запись JSON: tmp-файл + os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_save(data, str(path))
# ─── Точка входа ─────────────────────────────────────────────────────────────


def run_allocation_tuner(
    adapter_data: Optional[List[dict]] = None,
    current_weights: Optional[Dict[str, float]] = None,
    constraints: Optional[TunerConstraints] = None,
    data_dir: Optional[Path] = None,
    save: bool = True,
) -> TunerResult:
    """Основная точка входа. Запускает оптимизатор и сохраняет результат.

    Args:
        adapter_data:     Данные адаптеров [{id, apy, tvl_usd, tier}].
                          None → читается из data/adapter_orchestrator_status.json.
        current_weights:  Текущие веса {protocol_id: float 0..1}.
                          None → читается из data/current_positions.json.
        constraints:      Ограничения (None → defaults из TunerConstraints).
        data_dir:         Путь к data/ директории (None → авто).
        save:             Сохранять ли результат в data/tuner_suggestion.json.

    Returns:
        TunerResult с оптимальными весами.
    """
    ddir = data_dir or _DEFAULT_DATA_DIR

    if adapter_data is None:
        adapter_data = _load_adapter_data(ddir)

    if current_weights is None:
        current_weights = _load_current_weights(ddir)

    tuner = AllocationTuner(constraints=constraints)
    result = tuner.optimize(
        adapter_data=adapter_data,
        current_weights=current_weights,
        n_candidates=500,
    )

    if save:
        out_path = ddir / "tuner_suggestion.json"
        payload = result.to_dict()
        payload["generated_at"] = datetime.now(timezone.utc).isoformat()
        payload["note"] = (
            "Предложение тюнера — только для информации. "
            "Применяется вручную после review (MP-207)."
        )
        _atomic_write(out_path, payload)
        log.info("Tuner suggestion saved to %s", out_path)

    return result
