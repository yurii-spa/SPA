#!/usr/bin/env python3
"""Перепись модулей `spa_core/analytics/`, НЕ входящих ни в один тир реестра.

ЗАЧЕМ. Метрика «% работающего слоя» (директива владельца 2026-08-03) считается от
знаменателя 736. Реестр тиров при этом знает 671 модуль, а на диске лежат 754
публичных файла. Разница — **83 модуля, которые не измеряет никто**: они не попадают
ни в одну корзину аудита, не входят ни в `module_status`, ни в отчёт, и потому не
могут ни улучшить метрику, ни ухудшить её. Знаменатель, в котором часть корпуса
просто отсутствует, — не «строгая оценка», а незнание, выдающее себя за оценку.

Инструмент отвечает на ОДИН вопрос про каждый такой модуль: **может ли агрегатор
вообще его позвать** — и, если может, тем же дифференциальным тестом, что и остальные,
проверяет, зависит ли ответ от протокола.

ЧЕГО ОН НЕ ДЕЛАЕТ. Не правит реестр, не исполняет ничего в проде, не двигает капитал,
не выносит суждения «модуль полезен/бесполезен». Он измеряет и записывает.

ПОЧЕМУ ЛОГИКА НЕ СКОПИРОВАНА. Дифференциальный тест живёт в
`scripts/audit_protocol_blindness.py` (`_audit_module`) и импортируется отсюда ПО ПУТИ.
Копия разошлась бы с оригиналом молча, и тогда «перепись» мерила бы другой линейкой,
чем аудит тиров, — сравнивать их числа стало бы нельзя. Не удалось импортировать —
инструмент ОТКАЗЫВАЕТ (fail-CLOSED, код 2), а не мерит своей копией.

КЛАССЫ ВЕРДИКТА (каждый — измерение, а не мнение):

* ``deprecated_tombstone`` — импорт намеренно бросает `ImportError` со словом
  DEPRECATED. Это надгробие: файл оставлен указателем на замену. Из знаменателя
  исключается честно, с названной причиной.
* ``import_failed`` — импорт падает по другой причине (причина записана дословно).
* ``not_a_signal_module`` — модуль импортируется, но в нём нет НИ ОДНОГО ПУБЛИЧНОГО
  класса с методом-входом из `signal_aggregator._ENTRY_METHODS`. Агрегатор позвать его
  не может — по его собственному контракту это не модуль сигнала, а служебный код
  (построитель отчёта, движок, трекер). Из знаменателя исключается честно.
* ``inherits_base_stub`` — класс есть, метод-вход формально есть, но реализован он НЕ
  в модуле: это `BaseAnalytics.analyze`, заглушка-пустышка, возвращающая ``{{}}``.
  Прогон такого модуля даёт ``dormant`` («результат не приводится к score»), и ярлык
  звучит как «модуль поспал» — тогда как измеренная причина другая и точная: вход
  никогда не был написан. Разделено осознанно: `dormant` зовёт чинить данные,
  `inherits_base_stub` — писать реализацию (или признать, что она не нужна).
* всё остальное — тот же набор, что у аудита тиров: ``sensitive`` / ``blind_constant``
  / ``blind_equal`` / ``blind_equal_wide_ok`` / ``unchecked`` / ``failed`` / ``dormant``
  / ``nondeterministic``. Такой модуль агрегатор позвать МОЖЕТ — он кандидат в реестр.

ПОЧЕМУ КЛАСС ОБЯЗАН БЫТЬ ПУБЛИЧНЫМ. Первый прогон переписи зачислил в кандидаты сам
`signal_aggregator` — у него есть `_ModuleAdapter.run`, формально подходящий под
критерий. Адаптер — это механизм ВЫЗОВА модулей, а не модуль; зачислив его, перепись
предложила бы агрегатору звать самого себя. Приватное имя (с подчёркиванием) —
единственный признак, который отделил одно от другого без списка исключений из головы.

ИСПОЛЬЗОВАНИЕ:

    python3 scripts/audit_untiered_analytics.py --out /tmp/untiered.json
    python3 scripts/audit_untiered_analytics.py --emit-markup   # → _untiered_census.py

КОДЫ ВОЗВРАТА: 0 — перепись снята; 2 — снять не удалось (инструмент отказал).
"""
from __future__ import annotations

import argparse
import importlib
import importlib.util
import inspect
import json
import os
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

ANALYTICS_DIR = REPO_ROOT / "spa_core" / "analytics"
CENSUS_PATH = ANALYTICS_DIR / "_untiered_census.py"

#: Вердикты, при которых агрегатор физически НЕ может позвать модуль. Такой модуль
#: не «неработающий» — он не является модулем сигнала, и место ему не в корзине
#: неработающих, а вне знаменателя, с названной причиной.
NOT_CALLABLE = ("deprecated_tombstone", "import_failed", "not_a_signal_module",
                "inherits_base_stub")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_blindness_audit():
    """Импортировать `_audit_module` из аудита тиров ПО ПУТИ. Не смог — бросить.

    Fail-CLOSED осознанно: молча смериться собственной копией дифференциального
    теста хуже, чем не смериться вовсе. Числа переписи сравнивают с числами аудита
    тиров, и это законно ровно до тех пор, пока линейка одна и та же."""
    path = REPO_ROOT / "scripts" / "audit_protocol_blindness.py"
    spec = importlib.util.spec_from_file_location("_blindness_audit_for_census", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"не удалось загрузить {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["_blindness_audit_for_census"] = module
    spec.loader.exec_module(module)
    if not hasattr(module, "_audit_module"):
        raise RuntimeError(f"{path} не несёт `_audit_module` — линейка не та")
    return module


def registry_names() -> set:
    from spa_core.analytics import _module_registry as registry
    return {m["module"] for m in registry.ALL_MODULES}


def modules_on_disk() -> Dict[str, str]:
    """Публичные модули пакета аналитики: ключ — как в реестре (точки), значение — путь.

    Ключ строится ТОЧНО так же, как имя в реестре: путь относительно пакета, разделители
    в точки. Иначе `gross_of/x.py` прочитается как `x`, разойдётся с записью реестра
    `gross_of.x` и 15 зарегистрированных модулей ложно попадут в «вне тиров» — так и
    вышло на первом прогоне (83 против ложных 98)."""
    out: Dict[str, str] = {}
    for root, dirs, files in os.walk(ANALYTICS_DIR):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for fname in files:
            if not fname.endswith(".py"):
                continue
            if fname.startswith("test_") or fname.startswith("_"):
                continue
            full = Path(root) / fname
            rel = full.relative_to(ANALYTICS_DIR)
            key = str(rel)[:-3].replace(os.sep, ".")
            out[key] = str(full.relative_to(REPO_ROOT))
    return out


def untiered_modules() -> Dict[str, str]:
    known = registry_names()
    return {k: v for k, v in sorted(modules_on_disk().items()) if k not in known}


def find_entrypoint(module_name: str) -> Tuple[Optional[str], Optional[str], str, str]:
    """→ (класс, метод, вердикт, причина). Класс/метод — None, если звать нечем."""
    from spa_core.analytics.signal_aggregator import _ENTRY_METHODS

    dotted = "spa_core.analytics." + module_name
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            mod = importlib.import_module(dotted)
        except ImportError as exc:
            text = str(exc)
            if "DEPRECATED" in text.upper():
                return None, None, "deprecated_tombstone", text[:200]
            return None, None, "import_failed", f"ImportError: {text}"[:200]
        except Exception as exc:  # noqa: BLE001 — любой отказ импорта измеряем
            return None, None, "import_failed", f"{type(exc).__name__}: {exc}"[:200]

    n_classes = 0
    for cls_name, obj in vars(mod).items():
        if not inspect.isclass(obj) or obj.__module__ != dotted:
            continue
        n_classes += 1
        if cls_name.startswith("_"):     # механизм вызова, а не модуль сигнала
            continue
        for entry in _ENTRY_METHODS:
            if callable(getattr(obj, entry, None)):
                return cls_name, entry, "callable", ""
    return (None, None, "not_a_signal_module",
            f"нет публичного класса с методом-входом; классов в модуле: {n_classes}")


def entrypoint_implementor(module_name: str, cls_name: str, entry: str) -> Optional[str]:
    """Кто РЕАЛЬНО реализует метод-вход у объекта, который построит агрегатор.

    Объект строит сам `_ModuleAdapter._import_callable` — тот же код, что в проде.
    Своя выемка здесь уже дала ложный ответ однажды: наивный `getattr(mod, cls)` не
    знает, что у 158 записей реестра поля `class` нет вовсе и агрегатор передаёт
    МОДУЛЬ, — и намерил 140 «наследников заглушки» там, где их два. Поэтому спрашиваем
    настоящего вызывающего, а не его пересказ."""
    from spa_core.analytics.signal_aggregator import _ModuleAdapter

    try:
        obj = _ModuleAdapter({"module": module_name, "class": cls_name})._import_callable()
    except Exception:  # noqa: BLE001 — не смогли построить ⇒ не утверждаем ничего
        return None
    if inspect.ismodule(obj):
        return "module-level"
    for klass in type(obj).__mro__:
        if entry in klass.__dict__:
            return klass.__name__
    return None


def run_census() -> Dict[str, Any]:
    audit = _load_blindness_audit()
    targets = untiered_modules()
    results: List[Dict[str, Any]] = []

    for name, path in targets.items():
        cls_name, entry, verdict, reason = find_entrypoint(name)
        row: Dict[str, Any] = {"module": name, "path": path}
        if verdict != "callable":
            row.update({"classification": verdict, "reason": reason})
            results.append(row)
            continue
        info = {"module": name, "class": cls_name, "tier": "untiered",
                "category": "untiered", "weight": 0.0, "protocols": ["all"]}
        measured = audit._audit_module(info)
        classification = measured["classification"]
        implementor = entrypoint_implementor(name, cls_name, entry)
        # `dormant` + вход из базового класса = вход НЕ НАПИСАН. Ярлык уточняем:
        # общий `dormant` («результат не приводится к score») звучал бы как отказ
        # данных, а измеренная причина — отсутствие реализации.
        if classification == "dormant" and implementor == "BaseAnalytics":
            classification = "inherits_base_stub"
        row.update({"classification": classification,
                    "class": cls_name, "entrypoint": entry,
                    "entrypoint_implementor": implementor})
        if "subtype" in measured:
            row["subtype"] = measured["subtype"]
        if "wide" in measured:
            row["wide"] = measured["wide"]
        detail = (measured.get("runs", {}).get("aave_v3", {}) or {}).get("detail")
        if detail:
            row["detail"] = detail
        results.append(row)

    counts: Dict[str, int] = {}
    for r in results:
        counts[r["classification"]] = counts.get(r["classification"], 0) + 1
    return {
        "generated_at": _utc_now_iso(),
        "subject": "модули spa_core/analytics/ вне тиров реестра",
        "registry_size": len(registry_names()),
        "on_disk": len(modules_on_disk()),
        "untiered": len(results),
        "counts": counts,
        "modules": results,
    }


def _py_dict(rows: List[Tuple[str, str]], indent: str = "    ") -> str:
    out = []
    for key, val in rows:
        out.append(f"{indent}{key!r}:\n{indent}    {val!r},")
    return "\n".join(out)


def emit_markup(report: Dict[str, Any]) -> str:
    """Сгенерировать `_untiered_census.py` из ЗАМЕРА (не из списка, набранного руками)."""
    mods = report["modules"]
    tomb = [(m["module"], m["reason"]) for m in mods
            if m["classification"] == "deprecated_tombstone"]
    failed = [(m["module"], m["reason"]) for m in mods
              if m["classification"] == "import_failed"]
    not_sig = [(m["module"], m["reason"]) for m in mods
               if m["classification"] == "not_a_signal_module"]
    stub = [(m["module"], f"{m.get('class')}.{m.get('entrypoint')} не реализован — "
                          f"наследуется заглушка BaseAnalytics, возвращающая пустой dict")
            for m in mods if m["classification"] == "inherits_base_stub"]
    callable_rows = [(m["module"], f"{m['classification']} · класс {m.get('class')}"
                                   f".{m.get('entrypoint')}")
                     for m in mods if m["classification"] not in NOT_CALLABLE]

    text = f'''"""_untiered_census.py — перепись модулей аналитики ВНЕ тиров реестра.

СГЕНЕРИРОВАН ЗАМЕРОМ, руками не набран. Провенанс — одна воспроизводимая команда:

    python3 scripts/audit_untiered_analytics.py --emit-markup

Зачем файл существует. Метрика «% работающего слоя» считается от знаменателя, в
который эти модули не входили ВООБЩЕ: реестр тиров знает {report["registry_size"]},
на диске лежат {report["on_disk"]} публичных модулей, разница — {report["untiered"]}.
Пока они не названы, знаменатель — не оценка, а незнание, выдающее себя за оценку.

Файл ничего не исполняет и ничего не запрещает. Он ТОЛЬКО называет каждый модуль и
измеренную причину его положения, чтобы метрику можно было посчитать от всего корпуса.

Разбивка замера: {json.dumps(report["counts"], ensure_ascii=False, sort_keys=True)}
"""
from typing import Dict

#: Когда снят замер, из которого построен этот файл.
AUDIT_GENERATED_AT = {report["generated_at"]!r}

#: Размер реестра тиров и число публичных модулей на диске на момент замера.
REGISTRY_SIZE = {report["registry_size"]}
ON_DISK = {report["on_disk"]}

#: Надгробия: импорт намеренно бросает ImportError со словом DEPRECATED — файл
#: оставлен указателем на замену. Не модуль сигнала. Имя → дословный текст отказа.
DEPRECATED_TOMBSTONE: Dict[str, str] = {{
{_py_dict(tomb)}
}}

#: Импорт падает по иной причине. Это НЕ «модуль не работает» — это «модуль нельзя
#: даже загрузить», и причина названа дословно. Имя → причина.
IMPORT_FAILED: Dict[str, str] = {{
{_py_dict(failed)}
}}

#: Не модуль сигнала по контракту самого агрегатора: нет публичного класса с
#: методом-входом из `_ENTRY_METHODS`. Служебный код (отчёты, движки, трекеры).
#: Позвать его агрегатор не может, поэтому в корзину «неработающих» он не идёт —
#: он идёт ВНЕ знаменателя, с названной причиной. Имя → причина.
NOT_A_SIGNAL_MODULE: Dict[str, str] = {{
{_py_dict(not_sig)}
}}

#: Класс есть, метод-вход формально есть — но реализован он в базовом классе, а не
#: здесь: `BaseAnalytics.analyze` возвращает пустой dict. Вход НЕ НАПИСАН. Прогон даёт
#: `dormant`, и этот ярлык уводит: он зовёт чинить данные, тогда как чинить надо
#: реализацию (или признать, что она не нужна). Имя → измеренная причина.
INHERITS_BASE_STUB: Dict[str, str] = {{
{_py_dict(stub)}
}}

#: Агрегатор позвать МОЖЕТ — измерен тем же дифференциальным тестом, что и тиры.
#: Это кандидаты в реестр; включение в тир — отдельное решение владельца, не этот
#: файл. Имя → измеренный класс и точка входа.
WIRABLE: Dict[str, str] = {{
{_py_dict(callable_rows)}
}}

#: Вне знаменателя метрики: позвать нечем, и это измерено, а не предположено.
OUT_OF_DENOMINATOR = (
    frozenset(DEPRECATED_TOMBSTONE) | frozenset(IMPORT_FAILED)
    | frozenset(NOT_A_SIGNAL_MODULE) | frozenset(INHERITS_BASE_STUB)
)

#: Все переписанные модули (объединение четырёх наборов).
ALL_UNTIERED = OUT_OF_DENOMINATOR | frozenset(WIRABLE)
'''
    return text


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", help="куда записать JSON-отчёт")
    ap.add_argument("--emit-markup", action="store_true",
                    help=f"перезаписать {CENSUS_PATH.name} из замера")
    args = ap.parse_args()

    try:
        report = run_census()
    except Exception as exc:  # noqa: BLE001 — отказ инструмента виден, а не молчалив
        print(f"ОТКАЗ: перепись не снята — {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    print(f"вне тиров={report['untiered']} "
          f"(реестр={report['registry_size']}, на диске={report['on_disk']}) "
          f"counts={report['counts']}")
    out_of = sum(report["counts"].get(k, 0) for k in NOT_CALLABLE)
    print(f"позвать нечем={out_of} · агрегатор может позвать={report['untiered'] - out_of}")

    if args.out:
        Path(args.out).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"отчёт → {args.out}")

    if args.emit_markup:
        CENSUS_PATH.write_text(emit_markup(report), encoding="utf-8")
        print(f"разметка → {CENSUS_PATH}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
