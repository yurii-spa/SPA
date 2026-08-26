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

# ── Пороги политики — ЧИТАЮТСЯ, а не переписываются (ADR-136) ────────────────
# Тюнер предлагает раскладку, которую потом судит гейт. Любое собственное число
# здесь — это будущее расхождение: замер 2026-08-18 показал предложение с 22.8 %
# в одном T2-протоколе (гейт разрешает 20 %) и 93.5 % в одной сети (гейт — 90 %).
# Поэтому значения берутся из ``RiskConfig``, а не набираются заново.
try:
    from spa_core.risk.policy import RiskConfig as _RiskConfig
    _POLICY = _RiskConfig()
except Exception:  # noqa: BLE001 — тюнер advisory, но тогда он обязан СКАЗАТЬ
    _POLICY = None
    log.warning("tuner: RiskConfig недоступен — зеркало порогов не построено")

_P_SINGLE_CHAIN = _POLICY.max_single_chain_allocation if _POLICY else 0.90
_P_L2_TOTAL = _POLICY.max_l2_total_allocation if _POLICY else 0.50
_P_BASE_CHAIN = _POLICY.BASE_CHAIN_CAP if _POLICY else 0.20
_P_T1_CONC = _POLICY.max_concentration_t1 if _POLICY else 0.40
_P_T2_CONC = _POLICY.max_concentration_t2 if _POLICY else 0.20
_P_T2_TOTAL = _POLICY.max_total_t2_allocation if _POLICY else 0.50
_P_CASH_MIN = _POLICY.min_cash_pct if _POLICY else 0.05
_P_MAX_PROTOCOLS = _POLICY.max_protocols if _POLICY else 8

#: Какие сети считаются L2 — тот же набор, что у входного гейта политики
#: (``check_new_position``, блок 10). Отдельная копия здесь была бы ровно тем
#: расхождением, ради которого всё это и делается.
L2_CHAINS = frozenset({"arbitrum", "base"})


# ─── Dataclasses ─────────────────────────────────────────────────────────────


@dataclass
class TunerConstraints:
    """Ограничения для оптимизатора — ЗЕРКАЛО RiskPolicy v1.0, без запасов.

    Решение владельца 2026-08-26 (cloud-сессия, кнопка «Зеркалить политику»):
    сверх-осторожные запасы поверх политики СНЯТЫ — ОТМЕНЯЕТ его же решение
    25.08 «запас оставить» (последнее решение побеждает; разворот назван
    вслух, не молча). Рацио: два источника лимитов = вечный разъезд
    (ADR-060 §1.4 — предложения тюнера заворачивал гейт); граница риска —
    сама RiskPolicy, она проверяет всё независимо. Ужесточение — только
    через изменение ПОЛИТИКИ (ADR), не через тихие поля здесь.
    """
    t1_min: float = 0.0           # Пола нет — как в политике (снят запас 0.55, реш. 26.08)
    t2_max: float = _P_T2_TOTAL   # ЗЕРКАЛО policy.max_total_t2_allocation (50%, ADR-019)
    per_protocol_max: float = _P_T1_CONC  # Конверт = потолок T1; per-тир min() даёт ровно 40/20
    tvl_floor_usd: float = 5_000_000.0  # Min TVL пула — ЗЕРКАЛО policy.min_tvl_usd
    min_protocols: int = 3        # Min активных протоколов
    max_protocols: int = _P_MAX_PROTOCOLS  # ЗЕРКАЛО policy.max_protocols (ALLOC-002: 8)
    cash_min: float = _P_CASH_MIN  # Min cash buffer — ЗЕРКАЛО policy.min_cash_pct (5%)
    apy_min: float = 1.0          # Min APY % — ЗЕРКАЛО policy.min_apy_for_new_position
    apy_max: float = 30.0         # Max APY % — ЗЕРКАЛО policy.max_apy_for_new_position

    # ── ADR-136: потолки, которых у подборщика не было вовсе ────────────────
    # Все три — ЗЕРКАЛО политики, ни одного нового числа.
    per_protocol_t1_max: float = _P_T1_CONC   # policy.max_concentration_t1 (40%)
    per_protocol_t2_max: float = _P_T2_CONC   # policy.max_concentration_t2 (20%)
    single_chain_max: float = _P_SINGLE_CHAIN  # policy.max_single_chain_allocation (90%)
    l2_total_max: float = _P_L2_TOTAL          # policy.max_l2_total_allocation (50%)
    base_chain_max: float = _P_BASE_CHAIN      # policy.BASE_CHAIN_CAP (20%, ADR-025)

    def protocol_cap(self, tier: str) -> float:
        """Потолок на один протокол: строгий из «запаса» и потолка тира.

        После снятия запасов (реш. владельца 26.08) конверт ``per_protocol_max``
        равен потолку T1, и минимум даёт РОВНО политику: T1 40 % / T2 20 %.
        Формула min() сохранена: если владелец однажды вернёт запас, он снова
        заработает без правки кода.
        """
        t = str(tier or "T2").upper()
        policy_cap = self.per_protocol_t1_max if t == "T1" else self.per_protocol_t2_max
        return min(self.per_protocol_max, policy_cap)


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
    # ADR-136: что именно срезали до потолков политики и почему. Пустой список —
    # «проверено, срезать было нечего», а не «не проверяли»: шаг выполняется
    # всегда (см. ``_enforce_policy_caps``). Молчаливый простой капитала
    # запрещён (ADR-055) — каждый срез назван.
    # ``None`` только как значение по умолчанию dataclass'а — ``__post_init__``
    # немедленно превращает его в список, поэтому «не проверяли» на выходе не
    # существует: шаг выполняется всегда.
    policy_cap_notes: Optional[List[str]] = None
    # ADR-136: протоколы, не взятые в раскладку из-за неопределимой сети.
    # Отказ, а не догадка — условие владельца к варианту A.
    refused_no_chain: Optional[List[str]] = None

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()
        if self.policy_cap_notes is None:
            self.policy_cap_notes = []
        if self.refused_no_chain is None:
            self.refused_no_chain = []

    def to_dict(self) -> dict:
        return asdict(self)


# ─── AllocationTuner ──────────────────────────────────────────────────────────


class AllocationTuner:
    """Grid-search оптимизатор весов портфеля (pure Python, no scipy/numpy)."""

    def __init__(self, constraints: Optional[TunerConstraints] = None):
        self.constraints = constraints or TunerConstraints()
        #: ADR-136: протоколы, отброшенные из-за неопределимой сети. Пустой
        #: список = «проверено, таких нет»; заполняется в ``_eligible_adapters``.
        self.refused_no_chain: List[str] = []

    # ── вспомогательные методы ─────────────────────────────────────────────

    def _eligible_adapters(self, adapter_data: List[dict]) -> List[dict]:
        """Отфильтровывает адаптеры по TVL floor, APY bounds и ИЗВЕСТНОСТИ СЕТИ.

        ADR-136, дословное условие владельца к варианту A: «протокол, у которого
        сеть не определяется, — не берётся в раскладку (**отказ, а не
        догадка**)». Догадка здесь означала бы отнести вес к сети, которой мы не
        знаем, и сетевой потолок недосчитался бы — то есть fail-OPEN.

        Отброшенные НАЗЫВАЮТСЯ (``self.refused_no_chain``), а не исчезают: инв. #17.
        """
        c = self.constraints
        result = []
        refused: List[str] = []
        passed_pre_chain = []
        for a in adapter_data:
            tvl = float(a.get("tvl_usd", 0.0) or 0.0)
            apy = float(a.get("apy", 0.0) or 0.0)
            if tvl < c.tvl_floor_usd:
                continue
            if apy < c.apy_min or apy > c.apy_max:
                continue
            passed_pre_chain.append(a)

        # Сеть берётся из ТОГО ЖЕ реестра, что у гейта. Вызывающий может принести
        # её сам (``_load_adapter_data`` так и делает), но если не принёс — это
        # ещё не «неизвестна»: сперва спрашиваем реестр, и только его молчание
        # означает отказ. Иначе прямой вызов ``optimize()`` отказывал бы всем.
        missing = [a for a in passed_pre_chain if not str(a.get("chain") or "").strip()]
        if missing:
            try:
                from spa_core.risk.policy_enforcer import _resolve_chain_map
                chain_map, _ = _resolve_chain_map([a["id"] for a in missing])
            except Exception as exc:  # noqa: BLE001 — реестр молчит ⇒ отказ всем таким
                log.warning("tuner: карта сетей не построена (%s) — fail-CLOSED", exc)
                chain_map = {}
            for a in missing:
                a["chain"] = str(chain_map.get(a["id"], "") or "").strip().lower()

        for a in passed_pre_chain:
            if not str(a.get("chain") or "").strip():
                refused.append(str(a.get("id", "?")))
                continue
            result.append(a)
        self.refused_no_chain = sorted(refused)
        if refused:
            log.warning(
                "tuner: сеть не определена у %d протокол(ов) — НЕ берутся в "
                "раскладку (fail-CLOSED, ADR-136): %s",
                len(refused), ", ".join(self.refused_no_chain),
            )
        return result

    def _chain_of(self, adapter_data: List[dict]) -> Dict[str, str]:
        """``{протокол: сеть}`` по данным, которые пришли на вход."""
        return {a["id"]: str(a.get("chain") or "").strip().lower()
                for a in adapter_data if a.get("id")}

    def _chain_totals(
        self, weights: Dict[str, float], chain_of: Dict[str, str]
    ) -> Dict[str, float]:
        totals: Dict[str, float] = {}
        for pid, w in weights.items():
            ch = chain_of.get(pid, "")
            if not ch:
                continue
            totals[ch] = totals.get(ch, 0.0) + w
        return totals

    def _enforce_policy_caps(
        self,
        weights: Dict[str, float],
        adapter_data: List[dict],
    ) -> Tuple[Dict[str, float], List[str]]:
        """Срезает раскладку до потолков политики. Срезанное ОСТАЁТСЯ КЭШЕМ.

        ADR-136. Ограничения тюнера — «мягкие» (штрафы в целевой функции), и
        победивший кандидат мог нарушать их и всё равно выигрывать по APY:
        замер 2026-08-18 дал 22.8 % в одном T2-протоколе и 93.5 % в одной сети,
        после чего гейт отвергал раскладку ЦЕЛИКОМ — то есть в таком цикле
        сделок не было вовсе.

        Поэтому здесь — ЖЁСТКИЙ финальный шаг по порядку строгости:
        потолок на протокол (тир-aware) → сеть → L2 → Base → кэш-буфер.
        Излишек НИКОГДА не перекладывается в другой протокол: он честно
        становится кэшем (тот же принцип, что у ``_enforce_t3_total_cap``
        аллокатора — освободившийся вес не уезжает в более рискованный тир).

        Возвращает ``(weights, notes)``; ``notes`` называют КАЖДЫЙ срез —
        молчаливый простой капитала запрещён (ADR-055).
        """
        c = self.constraints
        tier_of = {a["id"]: str(a.get("tier", "T2")).upper() for a in adapter_data}
        chain_of = self._chain_of(adapter_data)
        w = dict(weights)
        notes: List[str] = []

        # 1) Потолок на один протокол — по тиру.
        for pid, val in list(w.items()):
            cap = c.protocol_cap(tier_of.get(pid, "T2"))
            if val > cap + _EPS:
                notes.append(
                    f"{pid}: {val * 100:.2f}% → {cap * 100:.2f}% "
                    f"(потолок на протокол, тир {tier_of.get(pid, 'T2')})"
                )
                w[pid] = cap

        # 2) Потолок на одну сеть, 3) L2 суммарно, 4) Base — одинаковой формой:
        #    пропорциональное сжатие группы до потолка.
        def _scale_group(members: List[str], total: float, cap: float, label: str) -> None:
            if total <= cap + _EPS or total <= _EPS:
                return
            scale = cap / total
            for pid in members:
                w[pid] = w[pid] * scale
            notes.append(f"{label}: {total * 100:.2f}% → {cap * 100:.2f}% (излишек — в кэш)")

        totals = self._chain_totals(w, chain_of)
        for ch, total in sorted(totals.items()):
            members = [p for p in w if chain_of.get(p) == ch]
            _scale_group(members, total, c.single_chain_max, f"сеть {ch}")

        l2_members = [p for p in w if chain_of.get(p) in L2_CHAINS]
        _scale_group(l2_members, sum(w[p] for p in l2_members), c.l2_total_max, "L2 суммарно")

        base_members = [p for p in w if chain_of.get(p) == "base"]
        _scale_group(base_members, sum(w[p] for p in base_members), c.base_chain_max, "сеть base")

        # 5) Кэш-буфер: сумма весов ≤ 1 − cash_min.
        total_w = sum(w.values())
        deploy_cap = 1.0 - c.cash_min
        if total_w > deploy_cap + _EPS and total_w > _EPS:
            scale = deploy_cap / total_w
            for pid in w:
                w[pid] = w[pid] * scale
            notes.append(
                f"кэш-буфер: размещено {total_w * 100:.2f}% → {deploy_cap * 100:.2f}%"
            )

        return {k: round(v, 6) for k, v in w.items()}, notes

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

        # ADR-136: ЖЁСТКИЙ финальный срез до потолков политики. Штрафы в целевой
        # функции — мягкие, и кандидат с высоким APY мог выиграть, нарушая их;
        # гейт потом отвергал раскладку целиком, и цикл оставался без сделок.
        best_weights, cap_notes = self._enforce_policy_caps(best_weights, eligible)

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
            policy_cap_notes=cap_notes,
            refused_no_chain=list(self.refused_no_chain),
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

    rows = []
    for a in raw.get("adapters", []):
        status = a.get("status", "ok")
        if status not in ("ok", "partial"):
            continue
        protocol = a.get("protocol", "")
        if not protocol:
            continue
        rows.append({
            "id": protocol,
            "apy": float(a.get("apy_pct", 0.0) or 0.0),
            "tvl_usd": float(a.get("tvl_usd", 0.0) or 0.0),
            "tier": a.get("tier", "T2"),
        })

    # ADR-136: поле «сеть» приходит из ТОГО ЖЕ источника, что у гейта.
    # Снимок оркестратора сети не несёт вовсе — именно поэтому подборщик о
    # сетевых потолках не знал. Резолвер импортируется, а не копируется: копия
    # разъехалась бы с гейтом ровно так же, как разъехались пороги.
    # Неразрешённая сеть остаётся ПУСТОЙ строкой — ``_eligible_adapters``
    # откажет такому протоколу, а не отнесёт его наугад (fail-CLOSED).
    try:
        from spa_core.risk.policy_enforcer import _resolve_chain_map
        chain_map, unresolved = _resolve_chain_map([r["id"] for r in rows])
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "tuner: карта сетей не построена (%s) — ни один протокол не пройдёт "
            "фильтр сети (fail-CLOSED, ADR-136)", exc,
        )
        chain_map, unresolved = {}, [r["id"] for r in rows]
    if unresolved:
        log.warning("tuner: сеть не определена для: %s", ", ".join(unresolved))
    for r in rows:
        r["chain"] = str(chain_map.get(r["id"], "") or "").strip().lower()
    return rows


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
    data_dir: Optional[str | os.PathLike] = None,
    save: bool = True,
) -> TunerResult:
    """Основная точка входа. Запускает оптимизатор и сохраняет результат.

    Args:
        adapter_data:     Данные адаптеров [{id, apy, tvl_usd, tier}].
                          None → читается из data/adapter_orchestrator_status.json.
        current_weights:  Текущие веса {protocol_id: float 0..1}.
                          None → читается из data/current_positions.json.
        constraints:      Ограничения (None → defaults из TunerConstraints).
        data_dir:         Путь к data/ директории — ``str`` или ``Path``
                          (None → авто). Нормализуется здесь: живой вызывающий
                          (``cycle_runner``) держит эффективную data-директорию
                          строкой ради back-compat API, и до MP-207-фикса это
                          роняло тюнер на ``str / str`` внутри (TypeError съедался
                          fail-safe-обёрткой ⇒ воскресный прогон не отрабатывал).
        save:             Сохранять ли результат в data/tuner_suggestion.json.

    Returns:
        TunerResult с оптимальными весами.
    """
    ddir = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR

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
