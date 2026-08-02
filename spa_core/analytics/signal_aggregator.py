"""
signal_aggregator.py — Агрегирует сигналы аналитических модулей (ADR-031).

Tier A (каждый цикл): блокирующие сигналы → data/analytics_signals_blocking.json
Tier B (каждый час):  advisory сигналы  → data/analytics_signals_advisory.json
Tier C (раз в день):  фоновая аналитика  → data/analytics_report_full.json

Дизайн-инварианты (соответствуют остальному контуру SPA):
* Pure-stdlib, read-only по отношению к чужим артефактам.
* Атомарная запись (tempfile + os.replace).
* Ring-buffer health-лог 100 записей (data/analytics_health.json).
* Per-module timeout 3 сек (ThreadPoolExecutor future.result(timeout=)).
* Fail-open ГРОМКИЙ (audit 2026-08-02): упавший/таймаутнувший/без-данных модуль
  не валит цикл, но его статус фиксируется явно — unchecked (нет entrypoint,
  принимающего protocol-контекст) / failed (исключение + detail) / dormant
  (вернул некоэрсируемый результат) / timeout — в health-логе и в
  ``_meta.module_status`` выходного JSON. Молчаливого None больше нет.
* НЕТ no-arg fallback: модуль, который нельзя вызвать с контекстом протокола,
  считается UNCHECKED и в score не попадает (раньше fn() выполнялся на
  встроенных demo-данных → протокол-слепая константа для всех протоколов).
* Протокол-слепые «ok»-модули (дифференциальный аудит 2026-08-02,
  scripts/audit_protocol_blindness.py → _protocol_blindness.py): принимают
  контекст, но игнорируют ctx["protocol"] → константный score. В Tier-B не
  исполняются, статус "blind", исключены из composite и confidence.
* Python 3.9 совместимость: Optional[...] из typing, без str | None.

Агрегация:
* Tier-A — «худший выигрывает»: score>70 → BLOCK, 40-70 → WARN, <40 → OK.
* Tier-B — взвешенное среднее score модулей → risk_multiplier 0.5-1.5;
  confidence = доля модулей, реально вернувших валидный сигнал.

CLI:
    python3 -m spa_core.analytics.signal_aggregator --run --tier A
    python3 -m spa_core.analytics.signal_aggregator --run --tier B
    python3 -m spa_core.analytics.signal_aggregator --tier C
"""
from __future__ import annotations

import argparse
import importlib
import inspect
import json
import logging
import os
import sys
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Tuple

from spa_core.analytics import _module_registry as registry

# Эмпирическая разметка протокол-слепых Tier-B модулей (дифференциальный
# аудит scripts/audit_protocol_blindness.py). Отсутствие файла = пустой набор.
try:
    from spa_core.analytics._protocol_blindness import PROTOCOL_BLIND_MODULES
except Exception:  # pragma: no cover — разметка ещё не сгенерирована
    PROTOCOL_BLIND_MODULES = frozenset()

log = logging.getLogger("spa.analytics.signal_aggregator")

# ─── Configuration ────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # SPA_Claude/
DATA_DIR = BASE_DIR / "data"

MODULE_TIMEOUT = 3.0          # сек на отдельный модуль (fail-open при таймауте)
MAX_WORKERS = 8
MAX_HEALTH_LOG = 100          # ring-buffer health-лога

# Tier-A пороги (score 0-100, выше = опаснее)
BLOCK_THRESHOLD = 70.0
WARN_THRESHOLD = 40.0

# Tier-B confidence: ниже порога → сигнал смягчается к нейтральному
MIN_CONFIDENCE = 0.30

# Tier-B кеш TTL (advisory результаты валидны 1 час)
TIER_B_TTL_S = 3600

BLOCKING_FILE = "analytics_signals_blocking.json"
ADVISORY_FILE = "analytics_signals_advisory.json"
HEALTH_FILE = "analytics_health.json"
REPORT_FULL_FILE = "analytics_report_full.json"

# Кандидаты-методы entrypoint в порядке предпочтения.
_ENTRY_METHODS = (
    "analyze", "score", "detect", "check", "assess",
    "evaluate", "monitor", "predict", "run",
)
# Ключи в dict-результате, где может лежать числовой риск 0-100.
# Базовые ключи + ключи Tier-C модулей (fix MP-1305).
# Audit 2026-08-02: generic "value" убран — любой dict с числовым "value"
# (APY, TVL, что угодно) коэрсился в risk-score; принимаем только ключи,
# которые семантически являются риском/оценкой.
_SCORE_KEYS = (
    "risk_score", "score", "composite_risk_0_100", "composite_score",
    "risk", "probability", "depeg_probability", "cascade_risk",
    "score_0_100",
    # Tier-C специфичные ключи (обнаружены при сканировании 180 модулей):
    "attractiveness_score", "rate_sensitivity_score", "attack_feasibility_score",
    "protection_score", "hhi_concentration_score", "average_composability_score",
    "kink_proximity_score", "slashing_risk_score", "revenue_sustainability_score",
    "value_accrual_score", "nim_efficiency_score", "reserve_adequacy_score",
    "mev_bot_activity_score", "worst_cliff_score", "utilization_efficiency_score",
    "capital_efficiency_score",
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


# Sentinel: у модуля нет entrypoint'а, принимающего protocol-контекст —
# сигнал НЕ измерен (в отличие от «модуль вернул None»).
UNCHECKED = object()


# ─── Module adapter ────────────────────────────────────────────────────────────

class _ModuleAdapter:
    """Унифицированная обёртка над разнородным аналитическим модулем.

    Импортирует модуль, пытается вызвать один из ``_ENTRY_METHODS`` с
    protocol-контекстом и нормализует выход в ``(score_0_100, status, detail)``.

    Если модуль не удаётся импортировать / вызвать / получить валидный score —
    score = None и явный status (unchecked/failed/dormant): сигнал
    отбрасывается, цикл живёт, но провал фиксируется громко.
    """

    def __init__(self, module_info: Dict[str, Any]):
        self.module_name = module_info.get("module", "")
        self.class_name = module_info.get("class")
        self.weight = float(module_info.get("weight", 0.0) or 0.0)
        self.category = module_info.get("category", "")

    def _import_callable(self) -> Optional[Any]:
        """Вернуть instance класса (если есть) или сам модуль."""
        mod = importlib.import_module(
            "spa_core.analytics." + self.module_name
        )
        if self.class_name:
            cls = getattr(mod, self.class_name, None)
            if cls is not None:
                try:
                    return cls()
                except Exception:
                    # класс требует аргументов конструктора — отдаём модуль
                    return mod
        return mod

    @staticmethod
    def _coerce_score(result: Any) -> Optional[float]:
        """Нормализовать разнородный выход модуля в score 0-100 (выше=опаснее)."""
        if result is None:
            return None
        # Числовой выход: эвристика — значение в [0,1] трактуем как вероятность.
        if isinstance(result, bool):
            return 100.0 if result else 0.0
        if isinstance(result, (int, float)):
            v = float(result)
            if 0.0 <= v <= 1.0:
                return max(0.0, min(100.0, v * 100.0))
            return max(0.0, min(100.0, v))
        if isinstance(result, dict):
            for key in _SCORE_KEYS:
                v_raw = result.get(key)
                # bool — подкласс int; {"score": True} не является score
                if not isinstance(v_raw, (int, float)) or isinstance(v_raw, bool):
                    continue
                v = float(v_raw)
                # *_probability ключи → [0,1] → *100
                if "probab" in key and 0.0 <= v <= 1.0:
                    return max(0.0, min(100.0, v * 100.0))
                if 0.0 <= v <= 1.0 and key == "risk":
                    return max(0.0, min(100.0, v * 100.0))
                return max(0.0, min(100.0, v))
            # risk_label → числовая шкала (расширена для Tier-C меток, fix MP-1305)
            label = str(result.get("risk_label") or result.get("label") or "").upper()
            label_map = {
                "NEGLIGIBLE": 5.0, "LOW": 20.0, "MODERATE": 45.0,
                "MEDIUM": 50.0, "ELEVATED": 60.0, "HIGH": 78.0,
                "SEVERE": 88.0, "CRITICAL": 95.0,
                # Tier-C метки
                "AVOID": 10.0, "STRONG_AVOID": 5.0, "STRONG AVOID": 5.0,
                "NEUTRAL": 50.0, "ACCEPTABLE": 30.0, "GOOD": 25.0,
                "STRONG": 20.0, "EXCELLENT": 10.0,
                "HEALTHY_ZONE": 15.0, "HEALTHY": 15.0,
                "MINIMAL_OVERHANG": 10.0, "MODERATE_OVERHANG": 50.0,
                "HIGH_OVERHANG": 75.0, "EXTREME_OVERHANG": 90.0,
                "SAFE": 10.0, "UNSAFE": 75.0, "BORDERLINE": 55.0,
                "PASS": 10.0, "FAIL": 80.0, "WARNING": 60.0,
            }
            if label in label_map:
                return label_map[label]
            # Fallback: сканируем dict на любой ключ вида *_score (fix MP-1305).
            # Tier-C модули возвращают разнородные score-поля — берём первый найденный.
            for k, v in result.items():
                if (k.endswith("_score") and isinstance(v, (int, float))
                        and not isinstance(v, bool)):
                    return max(0.0, min(100.0, float(v)))
        return None

    def _invoke(self, obj: Any, context: Dict[str, Any]) -> Any:
        """Найти и вызвать первый entrypoint, принимающий protocol-контекст.

        Audit 2026-08-02: no-arg fallback ``fn()`` УДАЛЁН — он успешно
        выполнялся на встроенных demo-данных модуля, никогда не видел
        ``context["protocol"]`` и давал протокол-слепую константу для всех
        протоколов. Пригодность сигнатуры проверяется через
        ``inspect.signature().bind()`` ДО вызова, чтобы TypeError изнутри
        модуля не глотался как «не та сигнатура», а всплывал как failed.
        Если ни один entrypoint не принимает контекст → ``UNCHECKED``.
        """
        for meth_name in _ENTRY_METHODS:
            fn = getattr(obj, meth_name, None)
            if not callable(fn):
                continue
            for args, kwargs in (
                ((), {"context": context}),
                ((context,), {}),
            ):
                try:
                    inspect.signature(fn).bind(*args, **kwargs)
                except (TypeError, ValueError):
                    continue
                # Сигнатура совместима — исключения изнутри НЕ глотаем здесь:
                # они всплывают в run() и фиксируются как status="failed".
                return fn(*args, **kwargs)
        return UNCHECKED

    def run(self, protocol: str, context: Dict[str, Any]) -> Tuple[Optional[float], str, str]:
        """Выполнить модуль для протокола. Возвращает (score_0_100, status, detail).

        status: ``ok`` (валидный score) | ``unchecked`` (нет entrypoint,
        принимающего protocol-контекст — модуль в принципе не может дать
        протокол-специфичный сигнал) | ``dormant`` (вызвался, но результат
        не коэрсится в score) | ``failed`` (исключение; detail = тип+текст).
        Fail-open по-прежнему: не-ok статус не валит цикл, но он ГРОМКИЙ —
        попадает в health-лог и в _meta.module_status выходного JSON.
        """
        try:
            obj = self._import_callable()
            ctx = dict(context)
            ctx["protocol"] = protocol
            raw = self._invoke(obj, ctx)
            if raw is UNCHECKED:
                return None, "unchecked", "no context-accepting entrypoint"
            score = self._coerce_score(raw)
            if score is None:
                return None, "dormant", (
                    "result not coercible to score (type=%s)" % type(raw).__name__
                )
            return score, "ok", ""
        except Exception as exc:  # noqa: BLE001 — fail-open, но с диагнозом
            return None, "failed", f"{type(exc).__name__}: {exc}"


# ─── Aggregator ────────────────────────────────────────────────────────────────

class SignalAggregator:
    """Параллельный запуск аналитических модулей с timeout/fail-open."""

    def __init__(self, data_dir: Optional[Path] = None,
                 module_timeout: float = MODULE_TIMEOUT,
                 max_workers: int = MAX_WORKERS):
        self.data_dir = Path(data_dir) if data_dir is not None else DATA_DIR
        self.module_timeout = module_timeout
        self.max_workers = max_workers
        self._log: Deque[Dict[str, Any]] = deque(maxlen=MAX_HEALTH_LOG)
        # Audit 2026-08-02: агрегированный статус каждого модуля за прогон
        # (ok выигрывает у любого не-ok: модуль, отработавший хотя бы для
        # одного протокола, считается пригодным).
        self._module_status: Dict[str, str] = {}

    # ── helpers ──────────────────────────────────────────────────────────

    def _record(self, module_name: str, status: str, detail: str = "") -> None:
        self._log.append({
            "ts": _utc_now_iso(),
            "module": module_name,
            "status": status,        # ok | unchecked | failed | timeout | dormant | blind
            "detail": detail,
        })
        if status == "ok" or self._module_status.get(module_name) != "ok":
            self._module_status[module_name] = status

    def _module_status_summary(self) -> Dict[str, Any]:
        """Сводка пригодности модулей за прогон — для _meta выходного JSON.

        counts: {status: n}; not_ok: {status: [module, ...]} — явный список
        того, что НЕ дало сигнал (unchecked/failed/dormant/timeout), чтобы
        было видно, какие из Tier-модулей реально пригодны.
        """
        counts: Dict[str, int] = {}
        not_ok: Dict[str, List[str]] = {}
        for name in sorted(self._module_status):
            st = self._module_status[name]
            counts[st] = counts.get(st, 0) + 1
            if st != "ok":
                not_ok.setdefault(st, []).append(name)
        return {"counts": counts, "not_ok": not_ok}

    def _run_module(self, module_info: Dict[str, Any], protocol: str,
                    context: Dict[str, Any]) -> Tuple[Optional[float], bool]:
        """Запускает один модуль с таймаутом. Возвращает (score, ok). None при сбое."""
        adapter = _ModuleAdapter(module_info)
        with ThreadPoolExecutor(max_workers=1) as ex:
            fut = ex.submit(adapter.run, protocol, context)
            try:
                score, status, detail = fut.result(timeout=self.module_timeout)
            except FuturesTimeout:
                self._record(adapter.module_name, "timeout")
                return None, False
            except Exception as exc:  # noqa: BLE001
                self._record(adapter.module_name, "failed",
                             f"{type(exc).__name__}: {exc}")
                return None, False
        self._record(adapter.module_name, status, detail)
        return score, status == "ok"

    # ── Tier A ───────────────────────────────────────────────────────────

    def run_tier_a(self, protocols: List[str], context: Dict[str, Any]) -> Dict[str, Any]:
        """Возвращает {protocol: {signal: BLOCK|WARN|OK, reason, score, triggered_by}}.

        Агрегация «худший выигрывает»: для каждого протокола берём максимальный
        score среди Tier-A модулей. score>70 → BLOCK, 40-70 → WARN, иначе OK.
        """
        modules = registry.get_tier_modules("A")
        signals: Dict[str, Any] = {}
        for proto in protocols:
            worst_score = 0.0
            triggered_by: List[str] = []
            worst_module = ""
            with ThreadPoolExecutor(max_workers=self.max_workers) as ex:
                futs = {
                    ex.submit(self._run_module, m, proto, context): m
                    for m in modules
                }
                for fut in futs:
                    m = futs[fut]
                    try:
                        score, ok = fut.result()
                    except Exception:
                        score, ok = None, False
                    if not ok or score is None:
                        continue
                    if score >= WARN_THRESHOLD:
                        triggered_by.append(m["module"])
                    if score > worst_score:
                        worst_score = score
                        worst_module = m["module"]
            if worst_score > BLOCK_THRESHOLD:
                sig = "BLOCK"
            elif worst_score >= WARN_THRESHOLD:
                sig = "WARN"
            else:
                sig = "OK"
            signals[proto] = {
                "signal": sig,
                "reason": (
                    f"{worst_module}=score {worst_score:.1f}"
                    if worst_module else "no_active_tier_a_signal"
                ),
                "score": round(worst_score, 2),
                "triggered_by": triggered_by,
            }
        return {
            "_meta": {"timestamp": _utc_now_iso(), "tier": "A",
                      "module_count": len(modules),
                      "module_status": self._module_status_summary()},
            "generated_at": _utc_now_iso(),
            "protocols": signals,
            "signals": signals,  # ADR-031 совместимый алиас
        }

    # ── Tier B ───────────────────────────────────────────────────────────

    def run_tier_b(self, protocols: List[str], context: Dict[str, Any]) -> Dict[str, Any]:
        """Возвращает {protocol: {risk_multiplier, confidence, composite_risk_0_100}}.

        risk_multiplier = 1.0 - (avg_score - 50) / 100, зажат в [0.5, 1.5].
        confidence = доля модулей, реально вернувших ПРОТОКОЛ-СПЕЦИФИЧНЫЙ
        сигнал. Низкая confidence → сигнал смягчается к нейтральному (mult≈1.0).

        Дифференциальный аудит 2026-08-02 (scripts/audit_protocol_blindness.py):
        модули из ``PROTOCOL_BLIND_MODULES`` возвращают константный score,
        не зависящий от ctx["protocol"] (тот же байт-в-байт даже для
        несуществующего контрольного протокола) — протокол-специфичной
        информации не несут. Они НЕ исполняются (детерминированно дешевле),
        получают громкий статус "blind" (health-лог + _meta.module_status)
        и исключаются из composite И из числителя confidence: до фикса 150
        констант складывались в composite ≈8.6 → фиктивный risk_multiplier
        ≈1.41 для ЛЮБОГО протокола одинаково. Advisory-слой; Tier-A (worst-
        wins, не weighted) разметку не потребляет.
        """
        modules = registry.get_tier_modules("B")
        total_modules = max(1, len(modules))
        signals: Dict[str, Any] = {}
        for proto in protocols:
            weighted_sum = 0.0
            weight_total = 0.0
            ok_count = 0
            contributors: List[Dict[str, Any]] = []
            runnable = []
            for m in modules:
                if m.get("module") in PROTOCOL_BLIND_MODULES:
                    self._record(m["module"], "blind",
                                 "protocol-blind constant (audit markup)")
                else:
                    runnable.append(m)
            with ThreadPoolExecutor(max_workers=self.max_workers) as ex:
                futs = {
                    ex.submit(self._run_module, m, proto, context): m
                    for m in runnable
                }
                for fut in futs:
                    m = futs[fut]
                    try:
                        score, ok = fut.result()
                    except Exception:
                        score, ok = None, False
                    if not ok or score is None:
                        continue
                    ok_count += 1
                    w = float(m.get("weight", 0.0) or 0.0) or 0.01
                    weighted_sum += score * w
                    weight_total += w
                    contributors.append(
                        {"module": m["module"], "score": round(score, 1),
                         "weight": round(w, 3)}
                    )
            confidence = ok_count / total_modules
            if weight_total > 0:
                avg_score = weighted_sum / weight_total
            else:
                avg_score = 50.0  # нет данных → нейтрально
            # risk_multiplier из score (50=нейтрал → 1.0; 100=max risk → 0.5)
            mult = 1.0 - (avg_score - 50.0) / 100.0
            mult = max(0.5, min(1.5, mult))
            # confidence-смягчение: тянем mult к 1.0 при низкой confidence
            if confidence < MIN_CONFIDENCE:
                blend = confidence / MIN_CONFIDENCE if MIN_CONFIDENCE else 0.0
                mult = 1.0 + (mult - 1.0) * blend
                avg_score = 50.0 + (avg_score - 50.0) * blend
            contributors.sort(key=lambda c: c["score"], reverse=True)
            signals[proto] = {
                "composite_risk_0_100": round(avg_score, 2),
                "risk_multiplier": round(mult, 4),
                "confidence": round(confidence, 4),
                "modules_ok": ok_count,
                "top_contributors": contributors[:5],
            }
        return {
            "_meta": {"timestamp": _utc_now_iso(), "tier": "B",
                      "ttl_s": TIER_B_TTL_S, "module_count": len(modules),
                      "module_status": self._module_status_summary()},
            "generated_at": _utc_now_iso(),
            "protocols": signals,
            "signals": signals,
        }

    # ── Tier C ───────────────────────────────────────────────────────────

    def run_tier_c(self, protocols: List[str], context: Dict[str, Any]) -> Dict[str, Any]:
        """Фоновая аналитика — агрегат для дашборда, НЕ влияет на аллокацию."""
        modules = registry.get_tier_modules("C")
        per_proto: Dict[str, Any] = {}
        for proto in protocols:
            ok_count = 0
            scores: List[float] = []
            with ThreadPoolExecutor(max_workers=self.max_workers) as ex:
                futs = {
                    ex.submit(self._run_module, m, proto, context): m
                    for m in modules
                }
                for fut in futs:
                    try:
                        score, ok = fut.result()
                    except Exception:
                        score, ok = None, False
                    if ok and score is not None:
                        ok_count += 1
                        scores.append(score)
            per_proto[proto] = {
                "modules_ok": ok_count,
                "avg_score": round(sum(scores) / len(scores), 2) if scores else None,
            }
        return {
            "_meta": {"timestamp": _utc_now_iso(), "tier": "C",
                      "module_count": len(modules),
                      "module_status": self._module_status_summary()},
            "generated_at": _utc_now_iso(),
            "protocols": per_proto,
        }

    # ── persistence ──────────────────────────────────────────────────────

    def _write_atomic(self, path: Path, data: Dict[str, Any]) -> None:
        """Атомарная запись через tempfile + os.replace."""
        from spa_core.utils.atomic import atomic_save
        atomic_save(data, str(path))

    def flush_health(self) -> None:
        """Записать ring-buffer health-лог (100 последних записей)."""
        try:
            existing: List[Dict[str, Any]] = []
            hp = self.data_dir / HEALTH_FILE
            if hp.exists():
                prev = json.loads(hp.read_text(encoding="utf-8"))
                if isinstance(prev, dict):
                    existing = list(prev.get("entries") or [])
                elif isinstance(prev, list):
                    existing = prev
            combined = (existing + list(self._log))[-MAX_HEALTH_LOG:]
            self._write_atomic(hp, {
                "generated_at": _utc_now_iso(),
                "entries": combined,
            })
        except Exception as exc:  # health-лог не должен валить цикл
            log.warning("flush_health failed (%s)", exc)


# ─── Module-level entrypoints ───────────────────────────────────────────────────

DEFAULT_PROTOCOLS = [
    "aave_v3", "compound_v3", "morpho_blue", "yearn_v3",
    "euler_v2", "maple", "pendle", "spark_susds",
]


def run_tier_a(protocols: List[str],
               context: Optional[Dict[str, Any]] = None,
               data_dir: Optional[Path] = None) -> Dict[str, Any]:
    agg = SignalAggregator(data_dir=data_dir)
    result = agg.run_tier_a(protocols, context or {})
    agg._write_atomic(agg.data_dir / BLOCKING_FILE, result)
    agg.flush_health()
    return result


def run_tier_b(protocols: List[str],
               context: Optional[Dict[str, Any]] = None,
               data_dir: Optional[Path] = None,
               use_cache: bool = True) -> Dict[str, Any]:
    agg = SignalAggregator(data_dir=data_dir)
    cache_path = agg.data_dir / ADVISORY_FILE
    # TTL-кеш: свежий advisory переиспользуется (1 час)
    if use_cache and cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            ts = (cached.get("_meta") or {}).get("timestamp")
            if ts:
                age = time.time() - datetime.fromisoformat(
                    ts.replace("Z", "+00:00")
                ).timestamp()
                if age < TIER_B_TTL_S:
                    return cached
        except Exception:
            pass
    result = agg.run_tier_b(protocols, context or {})
    agg._write_atomic(cache_path, result)
    agg.flush_health()
    return result


def run_tier_c(protocols: List[str],
               context: Optional[Dict[str, Any]] = None,
               data_dir: Optional[Path] = None) -> Dict[str, Any]:
    agg = SignalAggregator(data_dir=data_dir)
    result = agg.run_tier_c(protocols, context or {})
    agg._write_atomic(agg.data_dir / REPORT_FULL_FILE, result)
    agg.flush_health()
    return result


# ─── CLI ─────────────────────────────────────────────────────────────────────

def _cli(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Analytics Signal Aggregator (ADR-031) — Tier A/B/C"
    )
    parser.add_argument("--run", action="store_true",
                        help="Выполнить агрегацию и записать JSON.")
    parser.add_argument("--tier", choices=["A", "B", "C", "all"], default="all",
                        help="Какой тир запустить (по умолчанию all).")
    parser.add_argument("--no-cache", action="store_true",
                        help="Игнорировать TTL-кеш Tier-B.")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    )

    protocols = DEFAULT_PROTOCOLS
    context: Dict[str, Any] = {"source": "cli"}

    out: Dict[str, Any] = {}
    if args.tier in ("A", "all"):
        out["A"] = run_tier_a(protocols, context)
    if args.tier in ("B", "all"):
        out["B"] = run_tier_b(protocols, context, use_cache=not args.no_cache)
    if args.tier in ("C", "all"):
        out["C"] = run_tier_c(protocols, context)

    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
