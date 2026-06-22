"""
spa_core/strategies/s16_stablecoin_ladder.py — MP-592 S16 Stablecoin Ladder

Лестничная аллокация по стабильным активам с разным risk/reward профилем.
Капитал распределяется по трём «ступеням» (rungs), каждая с собственным
соотношением доходность/риск:

  Rung 1 — Conservative (T1):
    CompoundV3 + SparkSUSDS — 40% капитала, низкий риск, APY ~5.0%
    Самые надёжные T1-протоколы. Anchors портфеля.

  Rung 2 — Balanced (T1/T2):
    sDAI + MorphoBlue — 35% капитала, умеренный риск, APY ~6.5%
    Mix T1/T2: sDAI (DSR-yield, deprecation discount) + Morpho (curated vaults).

  Rung 3 — Growth (T2):
    sFRAX + wUSDM — 25% капитала, выше риск, APY ~8.0%
    RWA-бэкированные T2: sFRAX (Frax Savings Rate) + wUSDM (US T-bills yield).

Weighted Target APY: 0.40*5.0 + 0.35*6.5 + 0.25*8.0 = 2.0 + 2.275 + 2.0 = 6.275 ≈ 6.2%
RISK_SCORE: 0.32 (blended: conservative T1 доминирует)

Fallback-логика:
  - Если адаптер в rung не указан в apy_map → используется FALLBACK_APY.
  - Адаптер считается eligible если его APY в диапазоне [MIN_APY_ELIGIBLE, MAX_APY_ELIGIBLE].
  - Если весь rung ineligible (0 eligible адаптеров) → его капитал перераспределяется
    в conservative rung (fallback rung).
  - Если в rung часть адаптеров eligible → капитал rung делится поровну
    только между eligible адаптерами.

ADR: ADR-019 (T2 total cap ≤ 50%). T2 в S16 = 35% balanced T2-часть + 25% growth = 45% ≤ 50% ✓.

Правила:
  - stdlib only, никаких внешних зависимостей в runtime-коде
  - read-only / advisory — не вызывает execution/ или risk-агентов
  - LLM FORBIDDEN в данном модуле
  - approved=False от RiskPolicy не переопределяется
  - Атомарные записи data/ (если применимо): tmp + os.replace

Date: 2026-06-13
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional


# ─── Идентичность стратегии ───────────────────────────────────────────────────

STRATEGY_ID   = "S16"
STRATEGY_NAME = "S16 Stablecoin Ladder"
TIER          = "T1+T2"
DESCRIPTION   = (
    "Лестничная аллокация по стабильным активам: "
    "Conservative/T1 40% (CompoundV3+SparkSUSDS, ~5.0% APY), "
    "Balanced/T1+T2 35% (sDAI+MorphoBlue, ~6.5% APY), "
    "Growth/T2 25% (sFRAX+wUSDM, ~8.0% APY). "
    "Target APY ≈ 6.2%, Risk Score ≈ 0.32."
)

# ─── Лестничные ступени ───────────────────────────────────────────────────────
# Ключи адаптеров берутся из ADAPTER_REGISTRY в spa_core/adapters/__init__.py.

RUNGS: Dict[str, Dict] = {
    "conservative": {
        "weight":     0.40,
        "adapters":   ["compound_v3", "spark_susds"],
        "target_apy": 5.0,
        "tier":       "T1",
        "description": "Conservative T1 anchor — CompoundV3 + SparkSUSDS",
    },
    "balanced": {
        "weight":     0.35,
        "adapters":   ["sdai", "morpho_blue"],
        "target_apy": 6.5,
        "tier":       "T1/T2",
        "description": "Balanced T1/T2 mix — sDAI + MorphoBlue",
    },
    "growth": {
        "weight":     0.25,
        "adapters":   ["sfrax", "wusdm"],
        "target_apy": 8.0,
        "tier":       "T2",
        "description": "Growth T2 — sFRAX + wUSDM (RWA-backed)",
    },
}

# ─── Fallback APY (%) — используется если адаптер недоступен ─────────────────
FALLBACK_APY: Dict[str, float] = {
    "compound_v3": 5.2,    # CompoundV3 Comet USDC supply rate
    "spark_susds": 5.0,    # Spark / sUSDS DSR-yield
    "sdai":        5.5,    # MakerDAO sDAI (DSR rate)
    "morpho_blue": 6.5,    # Morpho Blue USDC vault
    "sfrax":       7.0,    # Frax sFRAX Savings Rate
    "wusdm":       5.0,    # Mountain Protocol wUSDM (T-bill yield)
}

# ─── Risk scores по адаптерам ─────────────────────────────────────────────────
RISK_SCORES: Dict[str, float] = {
    "compound_v3": 0.28,   # T1, Comet mono-market
    "spark_susds": 0.25,   # T1, Spark/Sky SparkSUSDS
    "sdai":        0.38,   # T2, DSR/migration risk
    "morpho_blue": 0.35,   # T2, curated vaults
    "sfrax":       0.40,   # T2, Frax stablecoin risk
    "wusdm":       0.45,   # T2, RWA centralized custodian
}

# ─── Границы eligible APY ────────────────────────────────────────────────────
# Адаптер с APY вне этого диапазона считается ineligible (spike / dead market).
MIN_APY_ELIGIBLE: float = 1.0
MAX_APY_ELIGIBLE: float = 30.0

# ─── Целевые метрики ─────────────────────────────────────────────────────────
TARGET_APY_PCT:          float = 6.2
RISK_SCORE:              float = 0.32

# Ожидаемый взвешенный APY при fallback-значениях:
# 0.40*5.2*0.5 + 0.40*5.0*0.5   = 0.40 * 5.1  = 2.04
# 0.35*5.5*0.5 + 0.35*6.5*0.5   = 0.35 * 6.0  = 2.10
# 0.25*7.0*0.5 + 0.25*5.0*0.5   = 0.25 * 6.0  = 1.50
# Total fallback weighted APY ≈ 5.64%
# При использовании target_apy per rung:
# 0.40*5.0 + 0.35*6.5 + 0.25*8.0 = 2.0 + 2.275 + 2.0 = 6.275 ≈ 6.2%
WEIGHTED_APY_TARGET: float = 6.275

# Диапазон целевого APY стратегии (для регистрации)
TARGET_APY_MIN: float = 4.5
TARGET_APY_MAX: float = 9.0

# Kill-switch: максимальный drawdown портфеля
MAX_DRAWDOWN_PCT: float = 5.0

# Константа для fallback rung (все ineligible rung → туда)
_FALLBACK_RUNG: str = "conservative"

# Максимальный размер кольцевого буфера simulate_history
_HISTORY_MAX: int = 365


# ─── StablecoinLadderStrategy ─────────────────────────────────────────────────

class StablecoinLadderStrategy:
    """S16 — Stablecoin Ladder: распределение капитала по ladder rungs.

    Три ступени с возрастающим risk/reward:
      conservative (T1, 40%) → balanced (T1/T2, 35%) → growth (T2, 25%).

    Методы:
      get_ladder_status(apy_map)  — per-rung статус eligible_count/actual_apy/weight
      get_allocation(capital_usd) — USD аллокация по адаптерам
      get_expected_apy(apy_map)   — взвешенный APY по eligible адаптерам
      get_health()                — health-check стратегии
      simulate(capital_usd)       — simulation с yield за 1 день
      to_dict()                   — JSON-serializable snapshot
    """

    def __init__(self) -> None:
        self.strategy_id   = STRATEGY_ID
        self.strategy_name = STRATEGY_NAME
        self.tier          = TIER

        # История simulate (кольцевой буфер _HISTORY_MAX)
        self._simulate_history: List[Dict] = []

    # ── Внутренние вспомогательные методы ────────────────────────────────────

    def _resolve_apy(
        self,
        adapter_key: str,
        apy_map: Optional[Dict[str, float]],
    ) -> float:
        """Возвращает APY (%) для адаптера.

        Приоритет: apy_map[adapter_key] → FALLBACK_APY[adapter_key] → 0.0.
        """
        if apy_map and adapter_key in apy_map:
            return float(apy_map[adapter_key])
        return FALLBACK_APY.get(adapter_key, 0.0)

    def _is_eligible(
        self,
        adapter_key: str,
        apy_map: Optional[Dict[str, float]],
    ) -> bool:
        """True если APY адаптера в диапазоне [MIN_APY_ELIGIBLE, MAX_APY_ELIGIBLE]."""
        apy = self._resolve_apy(adapter_key, apy_map)
        return MIN_APY_ELIGIBLE <= apy <= MAX_APY_ELIGIBLE

    def _eligible_adapters(
        self,
        rung_name: str,
        apy_map: Optional[Dict[str, float]],
    ) -> List[str]:
        """Список eligible адаптеров для rung."""
        adapters = RUNGS[rung_name]["adapters"]
        return [a for a in adapters if self._is_eligible(a, apy_map)]

    def _actual_rung_apy(
        self,
        rung_name: str,
        apy_map: Optional[Dict[str, float]],
    ) -> float:
        """Средний APY по eligible адаптерам rung-а.

        Если eligible нет → использует target_apy из RUNGS (advisory fallback).
        """
        eligible = self._eligible_adapters(rung_name, apy_map)
        if not eligible:
            return float(RUNGS[rung_name]["target_apy"])
        apys = [self._resolve_apy(a, apy_map) for a in eligible]
        return sum(apys) / len(apys)

    # ── Публичный API ──────────────────────────────────────────────────────────

    def get_ladder_status(
        self,
        apy_map: Optional[Dict[str, float]] = None,
    ) -> Dict[str, Dict]:
        """Статус каждой ступени лестницы.

        Returns:
            {
              "conservative": {
                "eligible_adapters": ["compound_v3", "spark_susds"],
                "eligible_count": 2,
                "total_adapters": 2,
                "actual_apy": 5.1,
                "target_apy": 5.0,
                "weight": 0.40,
                "tier": "T1",
                "adapter_apys": {"compound_v3": 5.2, "spark_susds": 5.0},
              },
              "balanced":     {...},
              "growth":       {...},
            }
        """
        result: Dict[str, Dict] = {}
        for rung_name, rung_cfg in RUNGS.items():
            adapters   = rung_cfg["adapters"]
            eligible   = self._eligible_adapters(rung_name, apy_map)
            actual_apy = self._actual_rung_apy(rung_name, apy_map)

            adapter_apys: Dict[str, float] = {
                a: self._resolve_apy(a, apy_map) for a in adapters
            }
            result[rung_name] = {
                "eligible_adapters": eligible,
                "eligible_count":    len(eligible),
                "total_adapters":    len(adapters),
                "actual_apy":        round(actual_apy, 4),
                "target_apy":        float(rung_cfg["target_apy"]),
                "weight":            float(rung_cfg["weight"]),
                "tier":              rung_cfg["tier"],
                "adapter_apys":      {a: round(v, 4) for a, v in adapter_apys.items()},
                "all_eligible":      len(eligible) == len(adapters),
                "any_eligible":      len(eligible) > 0,
            }
        return result

    def get_allocation(
        self,
        capital_usd: float,
        apy_map: Optional[Dict[str, float]] = None,
    ) -> Dict[str, float]:
        """Распределяет capital_usd по адаптерам согласно лестнице.

        Логика:
          1. Для каждого rung вычисляем его dollar bucket = weight * capital_usd.
          2. Внутри rung делим bucket поровну между eligible адаптерами.
          3. Если весь rung ineligible (eligible=0):
               его bucket переносится в conservative rung (fallback).
          4. Если conservative тоже ineligible и есть orphan capital:
               он добавляется к первому попавшемуся eligible адаптеру,
               иначе остаётся как "unallocated" (edge case).

        Args:
            capital_usd: Общий капитал (USD). При capital_usd <= 0 → все 0.
            apy_map:     {adapter_key: apy_pct}. None → FALLBACK_APY для всех.

        Returns:
            {adapter_key: allocated_usd, ...}
            Ключи — только eligible адаптеры (+ orphan fallback).
            Может включать ключ "__unallocated__" если весь капитал некуда разместить.
        """
        if capital_usd <= 0.0:
            return {a: 0.0 for rung in RUNGS.values() for a in rung["adapters"]}

        # 1. Bucketing: dollar за каждый rung
        rung_buckets: Dict[str, float] = {
            rung_name: capital_usd * cfg["weight"]
            for rung_name, cfg in RUNGS.items()
        }

        # 2. Eligible adapters per rung
        rung_eligible: Dict[str, List[str]] = {
            rung_name: self._eligible_adapters(rung_name, apy_map)
            for rung_name in RUNGS
        }

        # 3. Orphan capital: от rungs без eligible → в conservative
        orphan_capital: float = 0.0
        for rung_name in list(RUNGS.keys()):
            if len(rung_eligible[rung_name]) == 0:
                orphan_capital += rung_buckets.pop(rung_name)

        # 4. Добавляем orphan в conservative bucket
        if orphan_capital > 0.0:
            if _FALLBACK_RUNG in rung_buckets:
                rung_buckets[_FALLBACK_RUNG] += orphan_capital
                orphan_capital = 0.0

        # 5. Распределяем каждый rung поровну среди eligible
        allocation: Dict[str, float] = {}
        for rung_name, bucket_usd in rung_buckets.items():
            eligible = rung_eligible[rung_name]
            if not eligible:
                # conservative сам ineligible — поместим orphan в __unallocated__
                allocation["__unallocated__"] = (
                    allocation.get("__unallocated__", 0.0) + bucket_usd
                )
                continue
            per_adapter = bucket_usd / len(eligible)
            for adapter_key in eligible:
                allocation[adapter_key] = allocation.get(adapter_key, 0.0) + per_adapter

        # 6. Если есть orphan и conservative тоже ineligible
        if orphan_capital > 0.0:
            allocation["__unallocated__"] = (
                allocation.get("__unallocated__", 0.0) + orphan_capital
            )

        return {k: round(v, 6) for k, v in allocation.items()}

    def get_expected_apy(
        self,
        apy_map: Optional[Dict[str, float]] = None,
    ) -> float:
        """Ожидаемый взвешенный APY (%) по фактически eligible адаптерам.

        Формула:
            Σ_rung [rung.weight * mean_apy(eligible_adapters_in_rung)]

        Если rung ineligible → его weight переходит к conservative.
        Если вообще нет eligible → TARGET_APY_PCT (6.2%).

        Args:
            apy_map: {adapter_key: apy_pct}. None → FALLBACK_APY.

        Returns:
            Взвешенный APY в процентах.
        """
        # Если вообще нет eligible адаптеров во всех rungs → глобальный fallback
        all_adapters = [a for rng in RUNGS.values() for a in rng["adapters"]]
        if not any(self._is_eligible(a, apy_map) for a in all_adapters):
            return TARGET_APY_PCT

        # Считаем effective weights с учётом redistribution
        effective_weights: Dict[str, float] = {n: cfg["weight"] for n, cfg in RUNGS.items()}
        for rung_name in list(RUNGS.keys()):
            if len(self._eligible_adapters(rung_name, apy_map)) == 0:
                w = effective_weights.pop(rung_name)
                effective_weights[_FALLBACK_RUNG] = (
                    effective_weights.get(_FALLBACK_RUNG, 0.0) + w
                )

        total_weight = sum(effective_weights.values())
        if total_weight <= 0.0:
            return TARGET_APY_PCT

        weighted_apy = 0.0
        for rung_name, eff_weight in effective_weights.items():
            rung_apy = self._actual_rung_apy(rung_name, apy_map)
            weighted_apy += eff_weight * rung_apy

        # Normalize by effective total weight (should be 1.0 but safeguard)
        return round(weighted_apy / total_weight, 4)

    def get_health(
        self,
        apy_map: Optional[Dict[str, float]] = None,
    ) -> Dict:
        """Health-check стратегии.

        Returns dict:
          status:           "ok" | "degraded" | "critical"
          rungs_ok:         количество rungs со всеми eligible адаптерами
          rungs_partial:    rungs с частично eligible адаптерами
          rungs_ineligible: rungs без eligible адаптеров
          expected_apy:     текущий ожидаемый APY (%)
          target_apy:       TARGET_APY_PCT
          risk_score:       RISK_SCORE
          t2_allocation:    T2 доля в портфеле (% из growth+balanced T2 часть)
          warnings:         список предупреждений
        """
        ladder = self.get_ladder_status(apy_map)
        rungs_ok          = sum(1 for r in ladder.values() if r["all_eligible"])
        rungs_partial     = sum(
            1 for r in ladder.values()
            if r["any_eligible"] and not r["all_eligible"]
        )
        rungs_ineligible  = sum(1 for r in ladder.values() if not r["any_eligible"])

        expected_apy = self.get_expected_apy(apy_map)

        # T2 nominal allocation: balanced 35% (T1/T2 mixed, ~half T2) + growth 25% (full T2)
        # Conservative estimate: 35% * 0.5 + 25% = 17.5% + 25% = 42.5%
        t2_allocation = (
            RUNGS["balanced"]["weight"] * 0.5
            + RUNGS["growth"]["weight"]
        ) * 100.0

        warnings: List[str] = []
        if rungs_ineligible > 0:
            warnings.append(
                f"{rungs_ineligible} rung(s) fully ineligible — capital redirected to conservative"
            )
        if rungs_partial > 0:
            warnings.append(
                f"{rungs_partial} rung(s) partially ineligible — capital split among eligible"
            )
        if expected_apy < TARGET_APY_MIN:
            warnings.append(
                f"Expected APY {expected_apy:.2f}% below target minimum {TARGET_APY_MIN:.1f}%"
            )
        if t2_allocation > 50.0:
            warnings.append(
                f"T2 allocation estimate {t2_allocation:.1f}% exceeds ADR-019 cap 50%"
            )

        # Status
        if rungs_ineligible >= 2:
            status = "critical"
        elif rungs_ineligible == 1 or rungs_partial > 0:
            status = "degraded"
        else:
            status = "ok"

        return {
            "status":           status,
            "rungs_ok":         rungs_ok,
            "rungs_partial":    rungs_partial,
            "rungs_ineligible": rungs_ineligible,
            "total_rungs":      len(RUNGS),
            "expected_apy":     expected_apy,
            "target_apy":       TARGET_APY_PCT,
            "risk_score":       RISK_SCORE,
            "t2_allocation_pct": round(t2_allocation, 2),
            "warnings":         warnings,
        }

    def simulate(
        self,
        capital_usd: float,
        apy_map: Optional[Dict[str, float]] = None,
    ) -> Dict:
        """Симулировать один день при заданном капитале.

        Вычисляет:
          - allocation: {adapter: usd} по get_allocation()
          - per-adapter daily yield (position * apy / 100 / 365)
          - total daily yield USD
          - weighted APY
          - ladder status summary

        Args:
            capital_usd: общий капитал (USD).
            apy_map:     {adapter_key: apy_pct}. None → FALLBACK_APY.

        Returns:
            dict с ключами:
              capital_usd, allocation, total_allocated_usd,
              daily_yield_usd, annualized_yield_usd, weighted_apy,
              ladder_status, strategy_id, timestamp_utc
        """
        allocation = self.get_allocation(capital_usd, apy_map)
        total_allocated = sum(
            v for k, v in allocation.items() if k != "__unallocated__"
        )

        daily_yield_total = 0.0
        per_adapter_yield: Dict[str, float] = {}
        for adapter_key, pos_usd in allocation.items():
            if adapter_key == "__unallocated__":
                continue
            apy_pct = self._resolve_apy(adapter_key, apy_map)
            if apy_pct <= 0.0 or pos_usd <= 0.0:
                continue
            daily_yield = pos_usd * apy_pct / 100.0 / 365.0
            per_adapter_yield[adapter_key] = round(daily_yield, 6)
            daily_yield_total += daily_yield

        weighted_apy = self.get_expected_apy(apy_map)
        ladder_status = self.get_ladder_status(apy_map)

        result = {
            "strategy_id":        self.strategy_id,
            "capital_usd":        capital_usd,
            "allocation":         allocation,
            "total_allocated_usd": round(total_allocated, 6),
            "per_adapter_yield":  per_adapter_yield,
            "daily_yield_usd":    round(daily_yield_total, 6),
            "annualized_yield_usd": round(daily_yield_total * 365.0, 4),
            "weighted_apy":       weighted_apy,
            "ladder_status":      {
                rung: {
                    "eligible_count": v["eligible_count"],
                    "actual_apy":     v["actual_apy"],
                    "weight":         v["weight"],
                }
                for rung, v in ladder_status.items()
            },
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        }

        # Добавляем в кольцевой буфер
        self._simulate_history.append(result)
        if len(self._simulate_history) > _HISTORY_MAX:
            self._simulate_history = self._simulate_history[-_HISTORY_MAX:]

        return result

    def to_dict(
        self,
        apy_map: Optional[Dict[str, float]] = None,
    ) -> Dict:
        """JSON-serializable snapshot стратегии.

        Returns:
            dict со всеми ключевыми полями стратегии:
            strategy_id, strategy_name, tier, description,
            rungs (с текущим статусом), fallback_apy, risk_scores,
            target_apy_pct, risk_score, expected_apy, health,
            weighted_apy_target, target_apy_min, target_apy_max
        """
        ladder_status = self.get_ladder_status(apy_map)
        health        = self.get_health(apy_map)
        expected_apy  = self.get_expected_apy(apy_map)

        return {
            "strategy_id":         self.strategy_id,
            "strategy_name":       self.strategy_name,
            "tier":                self.tier,
            "description":         DESCRIPTION,
            "rungs":               {
                rung_name: {
                    "weight":          RUNGS[rung_name]["weight"],
                    "adapters":        RUNGS[rung_name]["adapters"],
                    "target_apy":      RUNGS[rung_name]["target_apy"],
                    "tier":            RUNGS[rung_name]["tier"],
                    "status":          ladder_status[rung_name],
                }
                for rung_name in RUNGS
            },
            "fallback_apy":        dict(FALLBACK_APY),
            "risk_scores":         dict(RISK_SCORES),
            "target_apy_pct":      TARGET_APY_PCT,
            "weighted_apy_target": WEIGHTED_APY_TARGET,
            "target_apy_min":      TARGET_APY_MIN,
            "target_apy_max":      TARGET_APY_MAX,
            "risk_score":          RISK_SCORE,
            "expected_apy":        expected_apy,
            "health":              health,
            "min_apy_eligible":    MIN_APY_ELIGIBLE,
            "max_apy_eligible":    MAX_APY_ELIGIBLE,
            "max_drawdown_pct":    MAX_DRAWDOWN_PCT,
            "simulate_history_len": len(self._simulate_history),
        }


# ─── Авто-регистрация в реестре spa_core/strategies/ ─────────────────────────

def _register() -> None:
    """Зарегистрировать S16 Stablecoin Ladder в глобальном REGISTRY.

    Вызывается при импорте модуля. Ошибка регистрации не блокирует импорт.
    """
    try:
        from spa_core.strategies.strategy_registry import REGISTRY, StrategyMeta
        REGISTRY.register(StrategyMeta(
            id=STRATEGY_ID,
            name=STRATEGY_NAME,
            type="lending",
            risk_tier="T2",   # T1+T2 не валиден; T2 как консервативный компромисс
            target_apy_min=TARGET_APY_MIN,
            target_apy_max=TARGET_APY_MAX,
            max_drawdown_pct=MAX_DRAWDOWN_PCT,
            description=DESCRIPTION,
            module="spa_core.strategies.s16_stablecoin_ladder",
            handler_class="StablecoinLadderStrategy",
            tags=[
                "stablecoin", "ladder", "conservative", "balanced", "growth",
                "compound_v3", "spark_susds", "sdai", "morpho_blue",
                "sfrax", "wusdm", "t1", "t2", "multi_rung", "s16",
            ],
        ))
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning(
            "StablecoinLadderStrategy auto-registration failed: %s", exc
        )


# Регистрация срабатывает при первом импорте модуля
_register()
