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
* Модули «различается не тем» (замер покрытия ключей 2026-08-06,
  scripts/audit_tier_c_wiring_feasibility.py → _protocol_key_coverage.py):
  score различается между протоколами, но профиль не даёт части ключей,
  которые движок читает, — различие пришло из ПОБОЧНЫХ полей. В Tier-B не
  исполняются, статус "unsourced", исключены из composite и confidence.
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
import typing
from collections import abc, deque
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

# Разметка покрытия ключей (scripts/audit_tier_c_wiring_feasibility.py --tier B
# --emit-markup): модуль различает протоколы, но профиль не даёт части ключей,
# которые его движок читает, — различие пришло из ПОБОЧНЫХ полей. Слепоту
# видно глазом, это — нет. Отсутствие файла = пустой набор.
try:
    from spa_core.analytics._protocol_key_coverage import UNSOURCED_MODULES
except Exception:  # pragma: no cover — разметка ещё не сгенерирована
    UNSOURCED_MODULES = frozenset()

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

# Tier-C: контрольный НЕСУЩЕСТВУЮЩИЙ протокол для in-situ дифференциального
# замера (та же методика, что scripts/audit_protocol_blindness.py). Модуль,
# отдающий тот же score для протокола, которого не существует, гарантированно
# не читает ctx["protocol"] — публиковать его число «по протоколам» значит
# утверждать измерение, которого не было.
TIER_C_CONTROL_PROTOCOL = "__nonexistent_control_protocol__"

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


# ─── Совместимость входа entrypoint'а ─────────────────────────────────────────
#
# Аудит 2026-08-06 (цикл #136). `signature().bind()` проверяет ТОЛЬКО арность:
# для `analyze(inp: BasisTradeInput)` привязка dict'а проходит, модуль
# вызывается и падает `AttributeError: 'dict' object has no attribute
# 'spot_yield_annual'`. В Tier-C так получилось 62 из 64 «failed» — и ни один
# из этих модулей не сломан: агрегатор просто не умеет построить их доменный
# вход. Ярлык «failed» звучал как «код сломан, идите чинить 64 модуля»,
# то есть сторож честно отвечал на свой вопрос («был ли exception»), а читался
# как ответ на нужный («работает ли модуль») — знакомый класс #29/#31/#35-#40.
#
# Имена аннотаций, которые Mapping удовлетворяет. Всё остальное с конкретной
# аннотацией — НЕ вызываем: вход построить нечем, и это UNCHECKED с названной
# причиной, а не выдуманный «отказ модуля».
_MAPPING_ANNOTATION_NAMES = frozenset({
    "dict", "Dict", "Mapping", "MutableMapping", "OrderedDict", "defaultdict",
    "Any", "object",
})

# ``X | None`` — только Python 3.10+; на 3.9 такого типа нет (см. инвариант
# совместимости в шапке модуля). Сентинел, а НЕ None: иначе `origin is None`
# у обычного класса совпало бы с «это union».
try:  # pragma: no cover — ветка зависит от версии интерпретатора
    from types import UnionType as _UNION_TYPE  # type: ignore[attr-defined]
except ImportError:  # pragma: no cover — Python 3.9
    _UNION_TYPE = object()  # type: ignore[assignment]


def _text_accepts_mapping(text: str) -> bool:
    """Текстовый разбор аннотации (``from __future__ import annotations``)."""
    for part in text.split("|"):
        part = part.strip()
        if part.startswith("Optional[") and part.endswith("]"):
            part = part[len("Optional["):-1].strip()
        head = part.split("[", 1)[0].strip().rsplit(".", 1)[-1]
        if head in _MAPPING_ANNOTATION_NAMES:
            return True
    return False


def _annotation_accepts_mapping(annotation: Any) -> bool:
    """Может ли параметр с такой аннотацией принять наш dict-контекст.

    Fail-OPEN ровно в одну сторону: аннотации НЕТ → судить не по чему,
    поведение прежнее (вызываем). Конкретная не-Mapping аннотация → не
    вызываем. Слепого «наверное подойдёт» здесь нет.
    """
    if annotation is inspect.Parameter.empty:
        return True
    if isinstance(annotation, str):
        return _text_accepts_mapping(annotation)
    if annotation is None or annotation is type(None):
        return False   # аннотация `None` — это NoneType, а не «нет аннотации»
    if annotation is Any or annotation is object:
        return True
    origin = typing.get_origin(annotation)
    # Union / Optional / ``X | None`` — достаточно ОДНОЙ подходящей ветки
    if origin is typing.Union or origin is _UNION_TYPE:
        return any(_annotation_accepts_mapping(a) for a in typing.get_args(annotation))
    base = origin if origin is not None else annotation
    if base is Any or base is object:
        return True
    if isinstance(base, type):
        try:
            return issubclass(base, abc.Mapping)
        except TypeError:  # pragma: no cover — экзотическая метаклассовая база
            return False
    return _text_accepts_mapping(str(annotation))


def _context_param(sig: "inspect.Signature", args: Tuple[Any, ...],
                   kwargs: Dict[str, Any], ctx: Any) -> Optional[Any]:
    """Параметр, которому достанется ИМЕННО наш контекст (сверка по identity)."""
    try:
        bound = sig.bind(*args, **kwargs)
    except (TypeError, ValueError):
        return None
    for name, value in bound.arguments.items():
        param = sig.parameters[name]
        if param.kind in (inspect.Parameter.VAR_POSITIONAL,
                          inspect.Parameter.VAR_KEYWORD):
            # контекст уехал в *args/**kwargs — аннотация к нему не относится
            continue
        if value is ctx:
            return param
    return None


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
            try:
                sig = inspect.signature(fn)
            except (TypeError, ValueError):  # pragma: no cover — C-функция без сигнатуры
                continue
            for args, kwargs in (
                ((), {"context": context}),
                ((context,), {}),
            ):
                try:
                    sig.bind(*args, **kwargs)
                except (TypeError, ValueError):
                    continue
                # Сигнатура совместима — исключения изнутри НЕ глотаем здесь:
                # они всплывают в run() и фиксируются как status="failed".
                return fn(*args, **kwargs)
        return UNCHECKED

    def _foreign_input_entrypoint(self, obj: Any) -> Optional[str]:
        """Описание выбранного entrypoint'а, если его вход — НЕ Mapping.

        Только диагноз, ничего не исполняет: вызывается уже ПОСЛЕ падения,
        чтобы отличить «модуль сломан» от «агрегатору нечем построить его
        доменный вход». Порядок перебора — тот же, что в ``_invoke``, иначе
        диагноз относился бы к другому методу.

        Судить по аннотации ДО вызова нельзя (замер #136): у части модулей
        аннотация устарела после обвязки protocol-контекстом —
        ``defi_liquidation_cascade_risk_analyzer`` объявляет
        ``analyze(positions: list[dict])`` и при этом успешно принимает
        контекст. Отказ по одной аннотации погасил бы РАБОТАЮЩИЙ модуль
        Tier-A, то есть блокирующий сигнал.
        """
        probe: Dict[str, Any] = {}
        for meth_name in _ENTRY_METHODS:
            fn = getattr(obj, meth_name, None)
            if not callable(fn):
                continue
            try:
                sig = inspect.signature(fn)
            except (TypeError, ValueError):  # pragma: no cover
                continue
            for args, kwargs in (((), {"context": probe}), ((probe,), {})):
                try:
                    sig.bind(*args, **kwargs)
                except (TypeError, ValueError):
                    continue
                param = _context_param(sig, args, kwargs, probe)
                if param is None or _annotation_accepts_mapping(param.annotation):
                    return None
                ann = param.annotation
                ann_txt = ann if isinstance(ann, str) else getattr(
                    ann, "__name__", str(ann))
                return "%s(%s: %s)" % (meth_name, param.name, ann_txt)
        return None

    def run(self, protocol: str, context: Dict[str, Any]) -> Tuple[Optional[float], str, str]:
        """Выполнить модуль для протокола. Возвращает (score_0_100, status, detail).

        status: ``ok`` (валидный score) | ``unchecked`` (сигнал НЕ измерен: нет
        entrypoint'а, принимающего protocol-контекст, ЛИБО его вход — чужой
        доменный тип, который агрегатору не из чего построить) | ``dormant``
        (вызвался, но результат не коэрсится в score) | ``failed`` (исключение
        у модуля, который контекст принять МОГ, — настоящий отказ).
        Fail-open по-прежнему: не-ok статус не валит цикл, но он ГРОМКИЙ —
        попадает в health-лог и в _meta.module_status выходного JSON.

        Аудит #136: «модуль сломан» отделено от «нам нечем его вызвать».
        Разделение делается ПОСЛЕ падения, а не вместо вызова, — иначе
        устаревшая аннотация погасила бы работающий модуль (см.
        ``_foreign_input_entrypoint``). Текст исключения сохраняется в обоих
        случаях: тише не становится нигде.
        """
        obj = None   # импорт мог упасть — диагноз ниже не должен ронять NameError
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
            diagnosis = f"{type(exc).__name__}: {exc}"
            try:
                foreign = (self._foreign_input_entrypoint(obj)
                           if obj is not None else None)
            except Exception:  # pragma: no cover — диагноз не смеет ронять прогон
                foreign = None
            if foreign:
                # Модуль НЕ сломан: его вход — доменный тип, а мы подали
                # Mapping. Ярлык «failed» отправлял бы чинить исправный код.
                return None, "unchecked", (
                    "entrypoint requires non-mapping input, adapter supplies "
                    "Mapping: %s; raised %s" % (foreign, diagnosis)
                )
            return None, "failed", diagnosis


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
            # ok | unchecked | failed | timeout | dormant | blind | unsourced
            "status": status,
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

    def _run_module_silent(self, module_info: Dict[str, Any], protocol: str,
                           context: Dict[str, Any]) -> Tuple[Optional[float], bool]:
        """Как ``_run_module``, но БЕЗ записи в health-лог и module_status.

        Нужен для контрольного прогона Tier-C: ``_meta.module_status`` обязан
        описывать поведение модулей на РЕАЛЬНЫХ протоколах. Запиши туда
        контрольный прогон — и модуль, ответивший только для несуществующего
        протокола, попал бы в счётчик "ok", то есть счётчик пригодности начал
        бы лгать в другую сторону.
        """
        adapter = _ModuleAdapter(module_info)
        with ThreadPoolExecutor(max_workers=1) as ex:
            fut = ex.submit(adapter.run, protocol, context)
            try:
                score, status, _detail = fut.result(timeout=self.module_timeout)
            except FuturesTimeout:
                return None, False
            except Exception:  # noqa: BLE001 — fail-open, как в проде
                return None, False
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

        Замер покрытия ключей 2026-08-06 (scripts/audit_tier_c_wiring_
        feasibility.py --tier B): критерия «различается» НЕДОСТАТОЧНО, он
        подделываем. 20 модулей из ``UNSOURCED_MODULES`` различают протоколы,
        но профиль не отдаёт часть ключей, которые их движок читает
        (покрытие 0.14…0.90): отсутствующий ключ молча становится 0.0/False, и
        всё различие приходит из побочных полей (``utilization_rate_pct``,
        ``tvl_usd``). Оценка регуляторного риска, оказавшаяся функцией
        утилизации пула, проходит проверку на слепоту и складывается в
        composite как измерение. Обходятся так же, как слепые: НЕ исполняются,
        громкий статус "unsourced", исключены из composite И из числителя
        confidence. Модуль в обоих наборах получает "blind" — вердикт старше и
        строже.
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
                name = m.get("module")
                if name in PROTOCOL_BLIND_MODULES:
                    self._record(m["module"], "blind",
                                 "protocol-blind constant (audit markup)")
                elif name in UNSOURCED_MODULES:
                    self._record(m["module"], "unsourced",
                                 "differentiates on side fields — profile "
                                 "lacks its subject keys (coverage markup)")
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

    def _tier_c_pass(self, modules: List[Dict[str, Any]], protocol: str,
                     context: Dict[str, Any], silent: bool = False
                     ) -> Dict[str, Any]:
        """Один прогон всех Tier-C модулей для протокола → {modules_ok, avg_score}."""
        runner = self._run_module_silent if silent else self._run_module
        ok_count = 0
        scores: List[float] = []
        with ThreadPoolExecutor(max_workers=self.max_workers) as ex:
            futs = {
                ex.submit(runner, m, protocol, context): m
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
        return {
            "modules_ok": ok_count,
            "avg_score": round(sum(scores) / len(scores), 2) if scores else None,
        }

    @staticmethod
    def _tier_c_differentiation(per_proto: Dict[str, Any],
                                control: Dict[str, Any]) -> Dict[str, Any]:
        """Честный вердикт: несёт ли Tier-C протокол-специфичную информацию.

        Замер 2026-08-06 (карточка `inbox-tier-c-analitiki-180-modulei-…`):
        из 180 Tier-C модулей отвечали 9, и все девять отдавали ОДИН И ТОТ ЖЕ
        score для всех 8 протоколов, для повторного прогона, для всей широкой
        вселенной _protocol_facts И для протокола, которого не существует.
        Артефакт при этом публиковал ``protocols: {aave_v3: {avg_score: 20.56},
        …}`` — форму «замер по протоколу» вокруг числа, к протоколу не
        относящегося. Это класс «утверждение об измерении, которого не было»
        (#29/#31/#35–#38/#40), только в виде правдоподобного ЧИСЛА.

        Вердикты (fail-CLOSED — неизмеримое НИКОГДА не сворачивается в OK):
          OK        — avg_score различается между реальными протоколами;
          NONE      — одинаков на всех реальных И на контрольном
                      несуществующем ⇒ ctx["protocol"] не читается;
          WEAK      — одинаков на реальных, но контрольный повёл себя иначе
                      (код протокол читает, данные — нет: слепой сегодня);
          UNCHECKED — измерить нечем (< 2 протоколов / никто не ответил).
        """
        real = [p for p in per_proto]
        if len(real) < 2:
            return {
                "verdict": "UNCHECKED",
                "reason": (
                    "нужно >=2 протокола для дифференциального замера, дано %d"
                    % len(real)
                ),
                "control_protocol": TIER_C_CONTROL_PROTOCOL,
            }
        avgs = [per_proto[p]["avg_score"] for p in real]
        responding = [p for p, a in zip(real, avgs) if a is not None]
        base: Dict[str, Any] = {
            "control_protocol": TIER_C_CONTROL_PROTOCOL,
            "real_protocols_measured": len(real),
            "protocols_with_responding_modules": len(responding),
            "control_modules_ok": control["modules_ok"],
            "control_avg_score": control["avg_score"],
        }
        if not responding:
            base.update({
                "verdict": "UNCHECKED",
                "reason": ("ни один Tier-C модуль не ответил ни для одного "
                           "протокола — различать нечего"),
            })
            return base
        distinct = sorted({a for a in avgs if a is not None})
        base["distinct_avg_scores"] = len(distinct)
        if len(responding) != len(real):
            # Модули ответили не для всех протоколов — это уже
            # протокол-зависимое поведение (ср. "partial_ok" в аудите).
            base.update({
                "verdict": "OK",
                "subtype": "partial_ok",
                "reason": (
                    "модули ответили для %d из %d протоколов — поведение "
                    "зависит от протокола" % (len(responding), len(real))
                ),
            })
            return base
        if len(distinct) > 1:
            base.update({
                "verdict": "OK",
                "reason": (
                    "avg_score различается между реальными протоколами "
                    "(различных значений: %d на %d протоколов)"
                    % (len(distinct), len(real))
                ),
            })
            return base
        only = distinct[0]
        if control["avg_score"] == only and control["modules_ok"] > 0:
            base.update({
                "verdict": "NONE",
                "reason": (
                    "avg_score=%s одинаков у всех %d протоколов И у "
                    "несуществующего контрольного ⇒ модули не читают "
                    "ctx['protocol']" % (only, len(real))
                ),
            })
            return base
        base.update({
            "verdict": "WEAK",
            "reason": (
                "avg_score=%s одинаков у всех %d реальных протоколов; "
                "контрольный несуществующий дал %s ⇒ протокол читается кодом, "
                "но не различается данными" % (only, len(real),
                                               control["avg_score"])
            ),
        })
        return base

    def run_tier_c(self, protocols: List[str], context: Dict[str, Any]) -> Dict[str, Any]:
        """Фоновая аналитика — агрегат для дашборда, НЕ влияет на аллокацию.

        Помимо per-protocol агрегата пишет ``_meta.protocol_differentiation``:
        измеренный В ЭТОТ ЖЕ ПРОГОН ответ на вопрос «а число вообще относится к
        протоколу?». Замер in-situ, а не по статической разметке: разметка
        протухает молча, а контрольный прогон стоит один лишний проход и
        краснеет сам. Каждая запись ``protocols[...]`` несёт
        ``protocol_specific`` (true/false/None) — чтобы потребитель, читающий
        только число, не был введён в заблуждение его формой.
        """
        modules = registry.get_tier_modules("C")
        per_proto: Dict[str, Any] = {}
        for proto in protocols:
            per_proto[proto] = self._tier_c_pass(modules, proto, context)

        # Контрольный прогон — silent: module_status обязан описывать
        # поведение на РЕАЛЬНЫХ протоколах (см. _run_module_silent).
        control = self._tier_c_pass(modules, TIER_C_CONTROL_PROTOCOL,
                                    context, silent=True)
        diff = self._tier_c_differentiation(per_proto, control)
        specific: Optional[bool] = {
            "OK": True, "NONE": False, "WEAK": False,
        }.get(diff["verdict"])
        for entry in per_proto.values():
            entry["protocol_specific"] = specific

        return {
            "_meta": {"timestamp": _utc_now_iso(), "tier": "C",
                      "module_count": len(modules),
                      "protocol_differentiation": diff,
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
