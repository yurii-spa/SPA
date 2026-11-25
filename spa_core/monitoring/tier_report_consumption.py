"""Потребляет ли исходник ОТЧЁТ тир-куратора — вопрос к РОЛИ вхождения, а не к файлу.

Сосед по предмету — `spa_core/monitoring/tier_touch.py`: тот отвечает «трогает ли
исходник КАНОН тира», этот — «добирается ли он до ОТЧЁТА куратора». Вместе они и
есть сторож инварианта «советательный отчёт тир-куратора не двигает тир»
(ярлык тира меняется только ADR-ом, T1 — владелец).

Написан по находке 2026-11-25 (карточка `inbox-storozh-tira-sudit-podstrokoi-imya-kurat`,
замер циклов #1240/#1241). Прежняя мера жила в самом сторо́же
(`test_tier_curator::_mentions_curator_in_code`) и спрашивала о ФАЙЛЕ, а не о
вхождении: любая строковая константа с именем `tier_curator` вне докстроки
объявлялась потреблением, а невинность снималась ОТДЕЛЬНЫМ механизмом на весь
файл — либо отметкой «сгенерированная разметка», либо именем в перечне `allowed`.

**Белый список имён класс не закрывает, и это ИЗМЕРЕНО, а не предположено.**
Цикл #875 внёс в `allowed` третье имя (`tier_touch.py`) ровно с оговоркой «имя
модуля стои́т у него ДАННЫМИ». 25.11 пришёл четвёртый такой модуль —
`spa_core/analytics/cadence_census.py`, у которого `tier_curator` стои́т элементом
кортежа ключевых слов классификатора такта, — и сторож покраснел на ВЕРНОМ
состоянии. Перепись населения в тот же день (модулей `spa_core/**` вне `tests`,
называющих имя, — **7**; НЕ РАЗОБРАНО — **0**):

| роль вхождения | модулей | кто |
|---|---|---|
| ввоз модуля / имени из него | 1 | `paper_trading/cycle_runner.py` (писатель) |
| обращение к атрибуту | 1 | `monitoring/card_acceptance.py` (проба) |
| строка, называющая ОТЧЁТ | 4 | куратор · проба · мост находок · писатель |
| **голое имя модуля элементом данных — и больше ничего** | **3** | `monitoring/tier_touch.py` · `analytics/_untiered_census.py` · `analytics/cadence_census.py` |

Три модуля одного класса, оправданные ДВУМЯ разными ad-hoc механизмами и одним
красным тестом. Предмет — МЕРА, а не перечень: роль вхождения знает разбор.

## Что считается потреблением

| что | `kind` |
|---|---|
| ввоз модуля куратора или имени из него, включая псевдоним | `import` |
| обращение к атрибуту с именем куратора | `attribute` |
| строка, называющая сам ОТЧЁТ (`tier_curator_report`) | `report_path` |
| имя куратора строкой в любой НЕ-ДАННОЙ роли: аргумент вызова, f-строка, склейка, присваивание, сравнение | `expression` |
| голое имя элементом данных ПЛЮС сборка пути к `*_report.json` в том же модуле | `assembled_path` |

Потреблением НЕ является `data` — голое имя модуля (без имени отчёта), стоя́щее
элементом литерального контейнера (кортеж, список, множество, словарь), и
`prose` — вхождение внутри докстроки.

## Почему у `data` есть замыкание `assembled_path`

Голое имя `tier_curator` до отчёта не добирается: отчёт лежит по пути
`data/tier_curator_report.json`, и из голого имени его надо СОБРАТЬ. Сборка
записывается склейкой либо f-строкой, поэтому модуль, держащий ОБЕ половины
пути (`"tier_curator"` данными и `"_report.json"` в склейке или f-строке), снова
считается потребителем — иначе сужение открыло бы ровно одну дверь, которую
прежняя подстрока держала закрытой. Замер 25.11: ни один из трёх модулей класса
`data` не называет `report.json` НИ РАЗУ, то есть замыкание не ложно ни на одном
живом модуле — это наблюдение, а не надежда.

Вторая половина ищется только в роли СБОРКИ (склейка либо f-строка), а не по
наличию: перепись артефактов, перечисляющая `*_report.json` данными, пути не
строит, и краснеть на ней значило бы воспроизвести тот же класс на шаг позже.

## Третий исход назван, а не подменён

Неразбираемый исходник — это НЕ «чисто»: `consumes_report` поднимает
`TierReportConsumptionUnmeasured`, и вызывающий решает сам (инв. #17: «измерено»,
«измерено и равно нулю», «не измерено» различимы). Молча вернуть `False` значило
бы отдать ложный зелёный за опечатку в файле.

Прибор НЕ решает, кому отчёт читать можно: это правило живёт у сторожа
(`test_no_module_consumes_report_to_mutate_tiers`). Здесь — только признак.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass

#: Имя модуля куратора. Голое — ещё не путь к отчёту.
MODULE_TOKEN = "tier_curator"

#: Имя самого ОТЧЁТА. Строка с ним — уже путь, который строят, чтобы файл прочесть.
REPORT_TOKEN = "tier_curator_report"

#: Вторая половина пути к отчёту: из голого имени модуля отчёт собирают ею.
REPORT_SUFFIX = "_report.json"

#: Литеральные контейнеры: вхождение внутри них есть ДАННЫЕ, а не обращение.
_DATA_CONTAINERS = (ast.Tuple, ast.List, ast.Set, ast.Dict)

#: Роли СБОРКИ строки. Только они превращают голое имя в путь.
_ASSEMBLY_ROLES = (ast.BinOp, ast.JoinedStr)

#: Роли, которые потреблением НЕ являются.
NON_CONSUMING_KINDS: frozenset[str] = frozenset({"data", "prose"})


class TierReportConsumptionUnmeasured(Exception):
    """Исходник не разобран ⇒ потребление НЕ ИЗМЕРЕНО (это не «чисто»)."""


@dataclass(frozen=True)
class Mention:
    """Одно вхождение имени: КАКАЯ роль, в какой строке и чем записано."""

    kind: str
    line: int
    token: str

    @property
    def consuming(self) -> bool:
        """Потребление ли это. Роль решает одна — вторых правил рядом нет."""
        return self.kind not in NON_CONSUMING_KINDS

    def __str__(self) -> str:                       # pragma: no cover - проза отчёта
        return f"{self.token!r} ({self.kind}, строка {self.line})"


def _docstring_ids(tree: ast.AST) -> set[int]:
    """Узлы-докстроки: их вхождения — проза, а не роль в выражении."""
    ids: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.FunctionDef,
                                 ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if (isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)):
            ids.add(id(first.value))
    return ids


def _parents(tree: ast.AST) -> dict[int, ast.AST]:
    """Карта «узел → его родитель»: роль вхождения знает именно родитель."""
    table: dict[int, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            table[id(child)] = node
    return table


def _parse(text: str) -> ast.AST:
    try:
        return ast.parse(text)
    except SyntaxError as exc:
        raise TierReportConsumptionUnmeasured(
            f"исходник не разобран ({exc.msg}, строка {exc.lineno}) — "
            f"потребление НЕ ИЗМЕРЕНО") from exc


def _assembles_report_path(tree: ast.AST, parents: dict[int, ast.AST],
                           docs: set[int]) -> int | None:
    """Строка его СОБИРАЕТ: вторая половина пути стои́т в склейке либо f-строке."""
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            continue
        if REPORT_SUFFIX not in node.value or id(node) in docs:
            continue
        if isinstance(parents.get(id(node)), _ASSEMBLY_ROLES):
            return node.lineno
    return None


def mentions(text: str) -> tuple[Mention, ...]:
    """ВСЕ вхождения имени куратора с их ролями. Поднимает третий исход сама.

    Возвращает и непотребляющие роли намеренно: «вхождений нет вовсе» и
    «вхождения есть, и все они данные» — разные наблюдения, и читатель вправе
    их различать (инв. #17).
    """
    tree = _parse(text)
    docs = _docstring_ids(tree)
    parents = _parents(tree)
    found: list[Mention] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if MODULE_TOKEN in alias.name:
                    found.append(Mention("import", node.lineno, alias.name))
        elif isinstance(node, ast.ImportFrom):
            if node.module and MODULE_TOKEN in node.module:
                found.append(Mention("import", node.lineno, node.module))
            for alias in node.names:
                if MODULE_TOKEN in alias.name:
                    found.append(Mention("import", node.lineno, alias.name))
        elif isinstance(node, ast.Attribute) and MODULE_TOKEN in node.attr:
            found.append(Mention("attribute", node.lineno, node.attr))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if MODULE_TOKEN not in node.value:
                continue
            if id(node) in docs:
                found.append(Mention("prose", node.lineno, node.value[:60]))
            elif REPORT_TOKEN in node.value:
                found.append(Mention("report_path", node.lineno, node.value[:60]))
            elif isinstance(parents.get(id(node)), _DATA_CONTAINERS):
                found.append(Mention("data", node.lineno, node.value[:60]))
            else:
                found.append(Mention("expression", node.lineno, node.value[:60]))
    if found and not any(m.consuming for m in found):
        line = _assembles_report_path(tree, parents, docs)
        if line is not None:
            found.append(Mention("assembled_path", line, REPORT_SUFFIX))
    return tuple(found)


def consumes_report(text: str) -> bool:
    """Добирается ли модуль до отчёта куратора.

    Поднимает `TierReportConsumptionUnmeasured` на неразбираемом исходнике:
    вызывающий обязан решить сам, а не получить ложный зелёный.
    """
    return any(m.consuming for m in mentions(text))


def describe(where: str, found: "tuple[Mention, ...] | list[Mention]") -> str:
    """Строка для вердикта сторожа: ЧТО именно сочтено потреблением и где."""
    consuming = [m for m in found if m.consuming]
    if not consuming:
        return f"{where}: потребления нет ({len(found)} вхождений, все — данные/проза)"
    return f"{where}: " + ", ".join(str(m) for m in consuming)
