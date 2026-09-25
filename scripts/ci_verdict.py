#!/usr/bin/env python3
"""Вердикт шага тестов: ИЗМЕРЕНО-ЗЕЛЕНО · ИЗМЕРЕНО-КРАСНО · НЕ ИЗМЕРЕНО (инв. #17).

**Зачем (цикл #694, 2026-09-25, карточка `inbox-ci-na-main-krasnyi-12-progonov-podryad-m`).**
Шаг `Run spa_core unit tests` в `.github/workflows/test.yml` месяц докладывал `failure`,
и это читалось как «тесты падают». Замер прогона 36119204905 (`f1f813226`, 3.11) говорит
другое: шаг не падал, он **ОБРЫВАЛСЯ**. Лог кончается штампом
``+++++++ Timeout +++++++`` и стеком, а сводки pytest (`N passed, M failed`) в нём нет
НИ ОДНОЙ — прогресс доехал до `[ 10%]` за 1732 с и был убит. Из 106 810 собранных тестов
вердикт получили ~10 700, а **≈96 000 не получили никакого**. То есть «не измерено»
выдавалось за «красное» — ровно тот класс, против которого написан инвариант #17, и
жил он внутри процедуры отчётности того самого ряда, который ловит этот класс у других.

**Почему одного кода возврата шага не хватает.** GitHub Actions знает про шаг два
состояния: `success` и `failure`. Третьего исхода у него нет по построению, поэтому
«сессию убили на 10 %» и «42 теста упали» приходят одним и тем же словом. Различить их
может только СОБСТВЕННАЯ запись прогона, сделанная им самим: pytest пишет junit-XML в
конце сессии, значит

* XML есть и в нём нет провалов ⇒ **ИЗМЕРЕНО · ЗЕЛЕНО**;
* XML есть и провалы названы  ⇒ **ИЗМЕРЕНО · КРАСНО**;
* XML нет, не разобран или пуст ⇒ **НЕ ИЗМЕРЕНО** — сессия не дошла до конца.

Отсутствие файла здесь — не сбой прибора, а сам ответ: убитый `os._exit`-ом или
снятый по `timeout-minutes` pytest свою запись не пишет никогда.

**Ноль собранных тестов — тоже НЕ ИЗМЕРЕНО, а не «чисто».** Пустой набор проходит любую
проверку на провалы; выдать его за зелёный — тот же fail-OPEN, что «found no entrypoints
= clean pass», закрытый в `deployment_acceptance` (`.claude/rules/deployment.md`).

Коды возврата: **0** — измерено, зелено · **1** — измерено, красно · **2** — НЕ ИЗМЕРЕНО.
Скрипт ничего не чинит и ничего не перезапускает: он только НАЗЫВАЕТ исход.

Только stdlib (инв. #4).
"""
from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import NamedTuple

# Коды возврата — часть контракта, читаются воркфлоу и тестами.
RC_GREEN = 0
RC_RED = 1
RC_UNMEASURED = 2

_MEASURED_GREEN = "ИЗМЕРЕНО · ЗЕЛЕНО"
_MEASURED_RED = "ИЗМЕРЕНО · КРАСНО"
_UNMEASURED = "НЕ ИЗМЕРЕНО"


class Verdict(NamedTuple):
    """Исход шага. ``reason`` обязателен у НЕ ИЗМЕРЕНО и пуст у остальных."""

    label: str
    rc: int
    tests: int | None
    failures: int | None
    errors: int | None
    skipped: int | None
    reason: str

    @property
    def measured(self) -> bool:
        return self.rc != RC_UNMEASURED


# Счётчики, которые pytest пишет ВСЕГДА. Их отсутствие — не ноль, а отсутствие
# наблюдения: XML с `tests="50"` и без `failures` прочитался бы «зелёным», то есть
# прибор против инварианта #17 сам бы его и нарушил. Найдено мутацией собственной
# батареи (цикл #694), закреплено тестом.
_REQUIRED_COUNTERS = ("tests", "failures", "errors", "skipped")


def _int_attr(node: ET.Element, name: str) -> int | None:
    """Числовой атрибут junit-XML. ``None`` = наблюдения нет, и это НЕ нуль."""
    raw = node.get(name)
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _sum_counter(suites: list[ET.Element], name: str) -> int | None:
    """Сумма счётчика по всем ``<testsuite>``; хотя бы одно отсутствие ⇒ ``None``."""
    total = 0
    for suite in suites:
        value = _int_attr(suite, name)
        if value is None:
            return None
        total += value
    return total


def _suites(root: ET.Element) -> list[ET.Element]:
    """Все ``<testsuite>`` документа.

    pytest пишет либо одиночный ``<testsuite>``, либо обёртку ``<testsuites>`` с
    вложенными — обе формы законны, и разбирать надо обе, иначе прибор объявит
    «не измерено» на исправной записи.
    """
    if root.tag == "testsuite":
        return [root]
    if root.tag == "testsuites":
        return list(root.iter("testsuite"))
    return []


def read_verdict(path: Path) -> Verdict:
    """Прочитать junit-XML и назвать один из трёх исходов."""
    if not path.exists():
        return Verdict(
            _UNMEASURED, RC_UNMEASURED, None, None, None, None,
            f"записи прогона нет ({path}) — сессия pytest не дошла до конца "
            f"(убита сторожем зависаний или снята по timeout-minutes)",
        )
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        return Verdict(
            _UNMEASURED, RC_UNMEASURED, None, None, None, None,
            f"запись прогона не разобрана ({path}): {exc} — обрыв на середине файла "
            f"неотличим от исправной записи, поэтому это НЕ вердикт о тестах",
        )

    suites = _suites(root)
    if not suites:
        return Verdict(
            _UNMEASURED, RC_UNMEASURED, None, None, None, None,
            f"в записи ({path}) нет ни одного <testsuite>: корень <{root.tag}>",
        )

    counted = {name: _sum_counter(suites, name) for name in _REQUIRED_COUNTERS}
    absent = [name for name, value in counted.items() if value is None]
    if absent:
        return Verdict(
            _UNMEASURED, RC_UNMEASURED, None, None, None, None,
            f"в записи ({path}) нет читаемых счётчиков {absent}: подставить здесь нуль "
            f"значило бы объявить набор зелёным по ОТСУТСТВИЮ наблюдения (инв. #17)",
        )

    tests, failures = counted["tests"], counted["failures"]
    errors, skipped = counted["errors"], counted["skipped"]
    assert tests is not None and failures is not None  # выше отсеяно
    assert errors is not None and skipped is not None

    if tests == 0:
        return Verdict(
            _UNMEASURED, RC_UNMEASURED, tests, failures, errors, skipped,
            f"собрано 0 тестов ({path}): пустой набор проходит любую проверку на "
            f"провалы, поэтому «чисто» здесь означало бы fail-OPEN",
        )

    if failures or errors:
        return Verdict(_MEASURED_RED, RC_RED, tests, failures, errors, skipped, "")
    return Verdict(_MEASURED_GREEN, RC_GREEN, tests, failures, errors, skipped, "")


def format_verdict(verdict: Verdict, *, label: str) -> str:
    """Человекочитаемая строка для лога Actions. Исход — первым словом."""
    head = f"{verdict.label} — {label}"
    if not verdict.measured:
        return f"❌ {head}\n   причина: {verdict.reason}"
    counted = (
        f"тестов {verdict.tests} · провалов {verdict.failures} · "
        f"ошибок {verdict.errors} · пропущено {verdict.skipped}"
    )
    mark = "✅" if verdict.rc == RC_GREEN else "🔴"
    return f"{mark} {head}\n   {counted}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Три исхода шага тестов: зелено · красно · НЕ ИЗМЕРЕНО (инв. #17).",
    )
    parser.add_argument("junit", type=Path, help="путь к junit-XML, написанному pytest")
    parser.add_argument(
        "--label", default="шаг тестов",
        help="как называть шаг в выводе (например «spa_core/tests/»)",
    )
    args = parser.parse_args(argv)

    verdict = read_verdict(args.junit)
    print(format_verdict(verdict, label=args.label))
    return verdict.rc


if __name__ == "__main__":  # pragma: no cover - точка входа
    sys.exit(main())
