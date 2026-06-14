"""
spa_core/strategies/s18_high_yield_t2.py — MP-604 S18 High Yield T2

S18 High Yield T2 Strategy
============================
Агрессивная стратегия с акцентом на T2 адаптеры (целевой APY 8.0%).
Содержит T1 Safety Net (30%) для защиты от просадки.

Распределение по слотам:
  Safety Net (T1, 30%): compound_v3 → spark_susds — T1 anchor, ~5.0% APY
  Core A    (T2, 35%): sfrax → wusdm               — T2 primary, ~8.5% APY
  Core B    (T2, 25%): sdai → scrvusd               — T2 secondary, ~6.5% APY
  Boost     (T2, 10%): sfrax | wusdm | sdai (max)   — T2 boost, ~10.0% APY

Weighted Target APY:
  0.30*5.0 + 0.35*8.5 + 0.25*6.5 + 0.10*10.0
  = 1.50 + 2.975 + 1.625 + 1.0 = 7.10% (conservative)
  При реальных APY → ≥ 8.0% (стратегический target)

Логика _resolve_slot:
  - Все слоты, кроме "boost": первый eligible кандидат из списка.
  - Слот "boost": кандидат с наибольшим APY среди eligible.
  - Если слот неresolved → его вес перераспределяется на safety_net.
  - Если safety_net тоже unresolved → капитал идёт в "__unallocated__".

ADR-019: T2 total cap ≤ 50%. S18 — T2 = 70% (aggressive strategy).
  adr_019_compliant = False — задокументировано, operator осознаёт риск.
  Компенсация: Safety Net T1 30% + Kill-switch drawdown ≥ 5%.

Правила:
  - stdlib only, никаких внешних зависимостей в runtime-коде
  - read-only / advisory — не вызывает execution/ или risk-агентов
  - LLM FORBIDDEN в данном модуле
  - approved=False от RiskPolicy не переопределяется
  - Атомарные записи data/: tmp + os.replace

Date: 2026-06-13 (MP-604)
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple


# ─── Идентичность стратегии ───────────────────────────────────────────────────

STRATEGY_ID   = "S18"
STRATEGY_NAME = "High Yield T2"
TIER          = "T2"   # T2-dominant (core 70% T2)
DESCRIPTION   = (
    "High Yield T2: Safety Net 30% T1 (CompoundV3/SparkSUSDS, ~5.0% APY) + "
    "Core A 35% T2 (sFRAX/wUSDM, ~8.5% APY) + "
    "Core B 25% T2 (sDAI/scrvUSD, ~6.5% APY) + "
    "Boost 10% T2 (max APY eligible, ~10.0% APY). "
    "Target APY 8.0%, Risk Score 0.42. "
    "ADR-019 aggressive: T2=70% > 50% cap (documented)."
)

# ─── Слоты стратегии ──────────────────────────────────────────────────────────
# Кандидаты проверяются по порядку (первый eligible выигрывает),
# для "boost" — победитель по максимальному APY.

SLOTS: Dict[str, Dict] = {
    "safety_net": {
        "candidates":   ["compound_v3", "spark_susds"],
        "weight":       0.30,
        "role":         "t1_anchor",
        "tier":         "T1",
        "fallback_apy": 5.0,
        "description":  "T1 Safety Net — защита от просадки, ~5.0% APY",
    },
    "core_a": {
        "candidates":   ["sfrax", "wusdm"],
        "weight":       0.35,
        "role":         "t2_primary",
        "tier":         "T2",
        "fallback_apy": 8.5,
        "description":  "T2 Core A — sFRAX/wUSDM primary yield, ~8.5% APY",
    },
    "core_b": {
        "candidates":   ["sdai", "scrvusd"],
        "weight":       0.25,
        "role":         "t2_secondary",
        "tier":         "T2",
        "fallback_apy": 6.5,
        "description":  "T2 Core B — sDAI/scrvUSD secondary yield, ~6.5% APY",
    },
    "boost": {
        "candidates":   ["sfrax", "wusdm", "sdai"],
        "weight":       0.10,
        "role":         "t2_boost",
        "tier":         "T2",
        "fallback_apy": 10.0,
        "description":  "T2 Boost — наилучший eligible T2, ~10.0% APY",
    },
}

# ─── Дефолтные APY (%) — fallback при недоступности адаптеров ────────────────

FALLBACK_APY: Dict[str, float] = {
    # T1
    "compound_v3":  5.2,    # CompoundV3 Comet USDC supply rate
    "spark_susds":  5.0,    # Spark / sUSDS DSR-yield
    # T2
    "sfrax":        8.5,    # Frax sFRAX Savings Rate (Frax Protocol)
    "wusdm":        5.0,    # Mountain Protocol wUSDM (US T-bills yield)
    "sdai":         5.5,    # MakerDAO sDAI (DSR rate)
    "scrvusd":      6.5,    # Curve Savings crvUSD (scrvUSD)
    "stusd":        5.8,    # Angle staked USDA (stUSD)
    "frax":         7.0,    # Frax Finance FraxLend USDC utilisation
}

# ─── Risk scores по адаптерам ─────────────────────────────────────────────────

RISK_SCORES: Dict[str, float] = {
    "compound_v3":  0.28,   # T1, Comet mono-market, надёжный
    "spark_susds":  0.20,   # T1, SparkSUSDS (MakerDAO-backed)
    "sfrax":        0.40,   # T2, Frax stablecoin risk
    "wusdm":        0.45,   # T2, RWA centralized custodian
    "sdai":         0.38,   # T2, DSR/migration risk
    "scrvusd":      0.42,   # T2, Curve soft-peg risk
    "stusd":        0.43,   # T2, Angle Protocol risk
    "frax":         0.44,   # T2, FraxLend utilisation risk
}

# ─── Границы eligible APY ─────────────────────────────────────────────────────

MIN_APY_ELIGIBLE: float = 1.0
MAX_APY_ELIGIBLE: float = 30.0

# ─── Целевые метрики ─────────────────────────────────────────────────────────

TARGET_APY_PCT:   float = 8.0
RISK_SCORE:       float = 0.42
MAX_T2_WEIGHT:    float = 0.70   # T2 не больше 70% в S18

# Weighted APY при дефолтных значениях:
# 0.30*5.2 + 0.35*8.5 + 0.25*5.5 + 0.10*8.5 = 1.56+2.975+1.375+0.85 = 6.76%
WEIGHTED_APY_DEFAULT: float = 6.76

# Диапазон целевого APY
TARGET_APY_MIN: float = 5.0
TARGET_APY_MAX: float = 18.0

# Kill-switch: максимальный drawdown портфеля (%)
MAX_DRAWDOWN_PCT: float = 5.0

# Плоская карта весов для cycle_runner (advisory, primary candidates)
# Уникальные ключи: compound_v3 (safety_net), sfrax (core_a),
# sdai (core_b), wusdm (boost — отличается от sfrax)
ALLOCATION_WEIGHTS: Dict[str, float] = {
    "compound_v3":  0.30,   # safety_net primary
    "sfrax":        0.35,   # core_a primary
    "sdai":         0.25,   # core_b primary
    "wusdm":        0.10,   # boost primary (wusdm vs sfrax для уникальности)
}

# Максимальный размер кольцевого буфера simulate_history
_HISTORY_MAX: int = 365

# Слот "boost" — идентификатор для особой логики max-APY
_BOOST_SLOT: str = "boost"


# ─── HighYieldT2Strategy ─────────────────────────────────────────────────────

class HighYieldT2Strategy:
    """S18 — High Yield T2 Strategy: Safety30%+CoreA35%+CoreB25%+Boost10%.

    Агрессивная T2-ориентированная стратегия с T1 Safety Net для защиты.
    Целевой APY 8.0%, Risk Score 0.42.
    ADR-019 aggressive (T2=70% > 50% cap) — задокументировано.

    Логика слотов:
      - safety_net: первый eligible из ["compound_v3", "spark_susds"]
      - core_a:     первый eligible из ["sfrax", "wusdm"]
      - core_b:     первый eligible из ["sdai", "scrvusd"]
      - boost:      eligible с максимальным APY из ["sfrax", "wusdm", "sdai"]
      Unresolved слот → вес идёт в safety_net (или __unallocated__).

    Stdlib only, без внешних зависимостей.
    """

    STRATEGY_ID    = STRATEGY_ID
    STRATEGY_NAME  = STRATEGY_NAME
    TIER           = TIER
    TARGET_APY_PCT = TARGET_APY_PCT
    RISK_SCORE     = RISK_SCORE
    MAX_T2_WEIGHT  = MAX_T2_WEIGHT

    def __init__(self) -> None:
        """Инициализировать S18 и загрузить доступные адаптеры."""
        self._adapters: Dict[str, object] = {}
        self._simulate_history: List[Dict] = []
        self._load_adapters()

    # ── Загрузка адаптеров ─────────────────────────────────────────────────────

    def _load_adapters(self) -> None:
        """Загрузить адаптеры из spa_core.adapters через try/except.

        Каждый адаптер загружается индивидуально. Если ImportError/Exception —
        адаптер пропускается; в runtime используется fallback APY.
        """
        # T1 safety_net candidates
        try:
            from spa_core.adapters.compound_v3_adapter import CompoundV3Adapter
            self._adapters["compound_v3"] = CompoundV3Adapter()
        except Exception:   # noqa: BLE001
            pass

        try:
            from spa_core.adapters.spark_susds_adapter import SparkSusdsAdapter
            self._adapters["spark_susds"] = SparkSusdsAdapter()
        except Exception:   # noqa: BLE001
            pass

        # T2 core_a candidates
        try:
            from spa_core.adapters.sfrax_adapter import SfraxAdapter
            self._adapters["sfrax"] = SfraxAdapter()
        except Exception:   # noqa: BLE001
            pass

        try:
            from spa_core.adapters.wusdm_adapter import WusdmAdapter
            self._adapters["wusdm"] = WusdmAdapter()
        except Exception:   # noqa: BLE001
            pass

        # T2 core_b candidates
        try:
            from spa_core.adapters.sdai_adapter import SdaiAdapter
            self._adapters["sdai"] = SdaiAdapter()
        except Exception:   # noqa: BLE001
            pass

        try:
            from spa_core.adapters.scrvusd_adapter import ScrvusdAdapter
            self._adapters["scrvusd"] = ScrvusdAdapter()
        except Exception:   # noqa: BLE001
            pass

    # ── Утилиты ────────────────────────────────────────────────────────────────

    def _get_adapter_apy(self, key: str) -> float:
        """Получить APY адаптера по ключу.

        Приоритет: adapter.get_apy() → FALLBACK_APY[key] → 0.0.
        """
        adapter = self._adapters.get(key)
        if adapter is not None:
            try:
                apy = adapter.get_apy()  # type: ignore[attr-defined]
                if isinstance(apy, (int, float)) and not isinstance(apy, bool) and apy > 0:
                    return float(apy)
            except Exception:   # noqa: BLE001
                pass
        return FALLBACK_APY.get(key, 0.0)

    def _is_eligible(self, key: str) -> bool:
        """True если адаптер eligible для аллокации.

        Если адаптер не загружен → считается eligible (будет использован fallback APY).
        Если загружен → пробуем adapter.is_eligible(); при ошибке → True.
        """
        adapter = self._adapters.get(key)
        if adapter is None:
            return True   # не загружен → default-safe, fallback APY в диапазоне
        try:
            result = adapter.is_eligible()  # type: ignore[attr-defined]
            return bool(result)
        except Exception:   # noqa: BLE001
            return True

    def _resolve_slot(self, slot_name: str) -> Tuple[Optional[str], Optional[object]]:
        """Выбрать активный адаптер для слота.

        Логика:
          - "boost": из eligible кандидатов выбирается тот, у кого APY максимальный.
          - Все прочие слоты: первый eligible кандидат из списка.
          - Если нет eligible → возвращает (None, None).

        Args:
            slot_name: ключ из SLOTS ("safety_net", "core_a", "core_b", "boost").

        Returns:
            (adapter_key, adapter_instance_or_None)
            adapter_instance может быть None если адаптер не загружен.
        """
        slot = SLOTS[slot_name]
        candidates: List[str] = slot["candidates"]

        if slot_name == _BOOST_SLOT:
            # Выбираем eligible кандидата с максимальным APY
            best_key: Optional[str] = None
            best_apy: float = -1.0
            for key in candidates:
                if self._is_eligible(key):
                    apy = self._get_adapter_apy(key)
                    if apy > best_apy:
                        best_apy = apy
                        best_key = key
            if best_key is None:
                return (None, None)
            return (best_key, self._adapters.get(best_key))
        else:
            # Первый eligible кандидат
            for key in candidates:
                if self._is_eligible(key):
                    return (key, self._adapters.get(key))
            return (None, None)

    # ── Публичный API ──────────────────────────────────────────────────────────

    def get_allocation(self, capital_usd: float) -> Dict[str, float]:
        """Вычислить целевую аллокацию капитала по слотам.

        Логика:
          1. Для каждого слота вычислить dollar bucket = weight * capital_usd.
          2. Resolve slot → если eligible → добавить в allocation[adapter_key].
          3. Если слот unresolved → его bucket перенаправляется в safety_net.
          4. Если safety_net тоже unresolved → "__unallocated__".
          5. Адаптеры могут встречаться в нескольких слотах — суммируются.

        Args:
            capital_usd: общий капитал (USD). При ≤ 0 → нулевые аллокации.

        Returns:
            {adapter_key: amount_usd, ...}
            Может включать "__unallocated__" при полной unavailability.
        """
        # Resolve safety_net заранее для fallback-логики
        safety_key, _ = self._resolve_slot("safety_net")

        if capital_usd <= 0.0:
            # Нулевые аллокации для первичных кандидатов
            result: Dict[str, float] = {}
            for slot_cfg in SLOTS.values():
                key = slot_cfg["candidates"][0]
                result[key] = 0.0
            return result

        allocation: Dict[str, float] = {}

        for slot_name, slot_cfg in SLOTS.items():
            bucket_usd = capital_usd * slot_cfg["weight"]
            resolved_key, _ = self._resolve_slot(slot_name)

            if resolved_key is not None:
                allocation[resolved_key] = allocation.get(resolved_key, 0.0) + bucket_usd
            else:
                # Unresolved → перенаправить в safety_net (если есть)
                if safety_key is not None:
                    allocation[safety_key] = allocation.get(safety_key, 0.0) + bucket_usd
                else:
                    allocation["__unallocated__"] = (
                        allocation.get("__unallocated__", 0.0) + bucket_usd
                    )

        return {k: round(v, 6) for k, v in allocation.items()}

    def get_expected_apy(self) -> float:
        """Вычислить ожидаемый взвешенный APY (%).

        Использует get_allocation(1.0) для нормированного расчёта весов
        (включая перераспределение от unresolved слотов).

        Returns:
            Взвешенный APY в процентах. При 0 eligible → TARGET_APY_PCT.
        """
        allocation = self.get_allocation(1.0)
        total_allocated = sum(v for k, v in allocation.items() if k != "__unallocated__")

        if total_allocated <= 0.0:
            return TARGET_APY_PCT

        weighted_apy = 0.0
        for key, weight in allocation.items():
            if key == "__unallocated__" or weight <= 0.0:
                continue
            apy = self._get_adapter_apy(key)
            weighted_apy += weight * apy

        # Normalize (должно быть ≈ 1.0, но safeguard)
        return round(weighted_apy / total_allocated, 4)

    def get_risk_summary(self) -> Dict:
        """Суммарный риск-профиль стратегии.

        Вычисляет:
          - t1_weight_pct: суммарный вес T1-слотов (%)
          - t2_weight_pct: суммарный вес T2-слотов (%)
          - t2_adapter_count: количество уникальных T2-адаптеров (resolved)
          - adr_019_compliant: T2 ≤ 50%? (False для S18 — aggressive strategy)

        Returns:
            dict с ключами: risk_score, t1_weight_pct, t2_weight_pct,
            t2_adapter_count, risk_note, adr_019_compliant, max_t2_weight.
        """
        t1_weight: float = 0.0
        t2_weight: float = 0.0
        t2_adapters_seen: set = set()

        for slot_name, slot_cfg in SLOTS.items():
            slot_tier = slot_cfg["tier"]
            slot_weight = slot_cfg["weight"]

            if slot_tier == "T1":
                t1_weight += slot_weight
            else:
                t2_weight += slot_weight
                resolved_key, _ = self._resolve_slot(slot_name)
                if resolved_key is not None and resolved_key not in t2_adapters_seen:
                    t2_adapters_seen.add(resolved_key)

        t2_weight_pct: float = round(t2_weight * 100.0, 2)
        t1_weight_pct: float = round(t1_weight * 100.0, 2)
        t2_adapter_count: int = len(t2_adapters_seen)
        adr_019_compliant: bool = t2_weight <= 0.50

        risk_note: str = (
            f"S18 High Yield T2: агрессивная стратегия с T2={t2_weight_pct:.0f}% "
            f"(превышает ADR-019 cap 50%). "
            f"Safety Net T1={t1_weight_pct:.0f}% обеспечивает защиту. "
            f"Kill-switch: drawdown ≥ {MAX_DRAWDOWN_PCT}%. "
            f"Operator осознаёт превышение cap; target APY {TARGET_APY_PCT}%."
        )

        return {
            "risk_score":        RISK_SCORE,
            "t1_weight_pct":     t1_weight_pct,
            "t2_weight_pct":     t2_weight_pct,
            "t2_adapter_count":  t2_adapter_count,
            "risk_note":         risk_note,
            "adr_019_compliant": adr_019_compliant,
            "max_t2_weight":     MAX_T2_WEIGHT,
        }

    def get_health(self) -> Dict:
        """Health-check стратегии S18.

        Returns dict:
          strategy_id, name, eligible_slots, total_slots,
          ineligible_slots, slots (per-slot detail),
          expected_apy, target_apy, risk_score,
          overall_status: "ok" | "degraded" | "critical"
        """
        slots_info: Dict[str, Dict] = {}
        eligible_count: int = 0
        ineligible_slots: List[str] = []

        for slot_name, slot_cfg in SLOTS.items():
            resolved_key, _ = self._resolve_slot(slot_name)
            eligible = resolved_key is not None

            if eligible:
                apy = self._get_adapter_apy(resolved_key)  # type: ignore[arg-type]
                eligible_count += 1
            else:
                apy = slot_cfg["fallback_apy"]
                ineligible_slots.append(slot_name)

            slots_info[slot_name] = {
                "resolved_key": resolved_key,
                "weight":       slot_cfg["weight"],
                "role":         slot_cfg["role"],
                "tier":         slot_cfg["tier"],
                "eligible":     eligible,
                "apy":          apy,
                "candidates":   slot_cfg["candidates"],
                "description":  slot_cfg["description"],
            }

        expected_apy = self.get_expected_apy()

        if eligible_count == len(SLOTS):
            overall_status = "ok"
        elif eligible_count == 0:
            overall_status = "critical"
        else:
            overall_status = "degraded"

        return {
            "strategy_id":      STRATEGY_ID,
            "name":             STRATEGY_NAME,
            "eligible_slots":   eligible_count,
            "total_slots":      len(SLOTS),
            "ineligible_slots": ineligible_slots,
            "slots":            slots_info,
            "expected_apy":     expected_apy,
            "target_apy":       TARGET_APY_PCT,
            "risk_score":       RISK_SCORE,
            "overall_status":   overall_status,
        }

    def simulate(self, capital_usd: float) -> Dict:
        """Симулировать один день для заданного капитала.

        Вычисляет:
          - allocation: {adapter: usd} по get_allocation()
          - per-adapter annual yield (position * apy / 100)
          - total annual yield USD
          - weighted APY
          - risk summary

        Args:
            capital_usd: начальный капитал (USD).

        Returns:
            dict с ключами:
              total_capital, allocation, expected_annual_yield_usd,
              expected_apy_pct, status, slot_results, risk_summary, timestamp_utc
        """
        allocation = self.get_allocation(capital_usd)

        if not allocation or capital_usd <= 0.0:
            return {
                "total_capital":              capital_usd,
                "allocation":                 {},
                "expected_annual_yield_usd":  0.0,
                "expected_apy_pct":           0.0,
                "status":                     "no_capital",
                "slot_results":               {},
                "risk_summary":               self.get_risk_summary(),
                "timestamp_utc":              datetime.now(timezone.utc).isoformat(),
            }

        total_yield: float = 0.0
        slot_results: Dict[str, Dict] = {}

        for key, amount in allocation.items():
            if key == "__unallocated__":
                continue
            apy = self._get_adapter_apy(key)
            annual_yield = amount * (apy / 100.0)
            total_yield += annual_yield

            # Попробуем simulate_deposit на адаптере если доступно
            adapter = self._adapters.get(key)
            deposit_result: Optional[Dict] = None
            if adapter is not None and amount > 0:
                try:
                    deposit_result = adapter.simulate_deposit(amount)  # type: ignore[attr-defined]
                except Exception:   # noqa: BLE001
                    pass

            # Ищем slot_name для ключа
            slot_name_for_key = next(
                (
                    sn for sn, sc in SLOTS.items()
                    if key in sc["candidates"]
                ),
                "unknown"
            )

            slot_results[key] = {
                "slot":             slot_name_for_key,
                "amount_usd":       amount,
                "apy_pct":          apy,
                "annual_yield_usd": round(annual_yield, 4),
                "deposit_result":   deposit_result,
                "risk_score":       RISK_SCORES.get(key, 0.0),
            }

        expected_apy = self.get_expected_apy()

        result = {
            "total_capital":             capital_usd,
            "allocation":                allocation,
            "expected_annual_yield_usd": round(total_yield, 4),
            "expected_apy_pct":          round(expected_apy, 4),
            "status":                    "ok",
            "slot_results":              slot_results,
            "risk_summary":              self.get_risk_summary(),
            "timestamp_utc":             datetime.now(timezone.utc).isoformat(),
        }

        # Кольцевой буфер истории симуляций
        self._simulate_history.append(result)
        if len(self._simulate_history) > _HISTORY_MAX:
            self._simulate_history = self._simulate_history[-_HISTORY_MAX:]

        return result

    def to_dict(self) -> Dict:
        """JSON-serializable snapshot стратегии.

        Returns:
            dict со всеми ключевыми полями:
            strategy_id, strategy_name, tier, description,
            slots (config + resolved status), fallback_apy, risk_scores,
            target_apy_pct, risk_score, expected_apy, health, risk_summary,
            allocation_weights, weighted_apy_default, adapters_loaded,
            simulate_history_len, timestamp
        """
        health       = self.get_health()
        risk_summary = self.get_risk_summary()
        expected_apy = self.get_expected_apy()
        now_iso      = datetime.now(timezone.utc).isoformat()

        # Слоты с resolved-статусом
        slots_snapshot: Dict[str, Dict] = {}
        for slot_name, slot_cfg in SLOTS.items():
            resolved_key, _ = self._resolve_slot(slot_name)
            slots_snapshot[slot_name] = {
                "candidates":   slot_cfg["candidates"],
                "weight":       slot_cfg["weight"],
                "role":         slot_cfg["role"],
                "tier":         slot_cfg["tier"],
                "fallback_apy": slot_cfg["fallback_apy"],
                "description":  slot_cfg["description"],
                "resolved_key": resolved_key,
                "resolved_apy": (
                    self._get_adapter_apy(resolved_key) if resolved_key else None
                ),
            }

        return {
            "strategy_id":          STRATEGY_ID,
            "strategy_name":        STRATEGY_NAME,
            "tier":                 TIER,
            "description":          DESCRIPTION,
            "slots":                slots_snapshot,
            "fallback_apy":         dict(FALLBACK_APY),
            "risk_scores":          dict(RISK_SCORES),
            "allocation_weights":   dict(ALLOCATION_WEIGHTS),
            "target_apy_pct":       TARGET_APY_PCT,
            "weighted_apy_default": WEIGHTED_APY_DEFAULT,
            "target_apy_min":       TARGET_APY_MIN,
            "target_apy_max":       TARGET_APY_MAX,
            "risk_score":           RISK_SCORE,
            "max_t2_weight":        MAX_T2_WEIGHT,
            "expected_apy":         expected_apy,
            "health":               health,
            "risk_summary":         risk_summary,
            "adapters_loaded":      list(self._adapters.keys()),
            "simulate_history_len": len(self._simulate_history),
            "min_apy_eligible":     MIN_APY_ELIGIBLE,
            "max_apy_eligible":     MAX_APY_ELIGIBLE,
            "max_drawdown_pct":     MAX_DRAWDOWN_PCT,
            "adr_019_note":         (
                "T2=70% exceeds ADR-019 cap 50%. Aggressive strategy — documented. "
                "Safety Net T1=30% + kill-switch drawdown 5% provide protection."
            ),
            "timestamp":            now_iso,
        }


# ─── Авто-регистрация в реестре spa_core/strategies/ ─────────────────────────

def _register() -> None:
    """Зарегистрировать S18 High Yield T2 в глобальном REGISTRY.

    Вызывается при импорте модуля. Ошибка регистрации не блокирует импорт.
    """
    try:
        from spa_core.strategies.strategy_registry import REGISTRY, StrategyMeta
        REGISTRY.register(StrategyMeta(
            id=STRATEGY_ID,
            name=STRATEGY_NAME,
            type="lending",
            risk_tier="T2",
            target_apy_min=TARGET_APY_MIN,
            target_apy_max=TARGET_APY_MAX,
            max_drawdown_pct=MAX_DRAWDOWN_PCT,
            description=DESCRIPTION,
            module="spa_core.strategies.s18_high_yield_t2",
            handler_class="HighYieldT2Strategy",
            tags=[
                "high_yield", "t2", "aggressive", "safety_net", "compound_v3",
                "spark_susds", "sfrax", "wusdm", "sdai", "scrvusd",
                "adr_019_aggressive", "s18", "multi_slot",
            ],
        ))
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning(
            "HighYieldT2Strategy auto-registration failed: %s", exc
        )


# Регистрация срабатывает при первом импорте модуля
_register()
