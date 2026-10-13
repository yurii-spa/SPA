"""Перепись КОМАНДНЫХ ПОВЕРХНОСТЕЙ владельца: сколько раз объявлен один набор.

Почему прибор существует
========================
Вопрос «какими командами владелец сейчас управляет системой» имел в дереве
**три** ответа, и все три назывались одинаково уверенно:

====================================  ======  =========================================
объявление                            сколько кто читает
====================================  ======  =========================================
``TelegramBot._COMMANDS``             13      прибор органов владельца
                                              (``cio_kill_switch_controls``, по AST)
карта ``handlers`` в ``_dispatch``    13      САМ бот, когда приходит легаси-кнопка
нагрузка ``setMyCommands``            16      САМ Telegram: это меню ☰, которое
                                              владелец ВИДИТ
====================================  ======  =========================================

Первое и второе — побайтово один и тот же набор, набранный руками дважды в
одном классе в двадцати строках друг от друга. Третье отвечает на ДРУГОЙ
вопрос («что владельцу обещано»), и равнять его с первыми двумя значило бы
потерять ровно ту разницу, из-за которой ``/pause`` 30.09 убрали из меню, но
оставили кнопкой.

Что прибор НЕ делает: он не сводит поверхности в одну. Их три вопроса:
**обещано · достижимо · объявлено**. Сводить надо КОПИИ одного ответа, а не
разные вопросы — иначе «один список» достигается слепотой.

Шесть поверхностей, и каждая снята разбором дерева, а не подстрокой
===================================================================
``advertised``
    полезная нагрузка ``setMyCommands`` в ``register_commands`` — что владелец
    видит в меню ☰.
``dispatched``
    ключи карты «команда → метод» внутри ``_dispatch`` — на что отвечает
    легаси-диспетчер.
``declared``
    КАЖДЫЙ класс-атрибут, который есть кортеж/список строк с ведущим ``/``.
    Это детектор копий: объявление, чьё МНОЖЕСТВО равно множеству другой
    поверхности, есть вторая запись того же контракта.
``routed``
    ключи ``router.COMMAND_TO_PATH`` — на что отвечает НАБРАННАЯ команда.
``intercepted``
    ``_INTERCEPTED_COMMANDS`` — перехваты в ``handle_update`` до Router'а.
``buttoned``
    каждый литерал ``callback_data``, начинающийся с ``/``. Легаси-диспетчер
    достижим ТОЛЬКО через такую кнопку (``handle_update``: ``_dispatch``
    зовётся из ветви ``callback_query``, набранный текст туда не попадает
    никогда) — поэтому запись карты без кнопки не есть орган владельца.

Производные и четыре их исхода
==============================
``reachable`` = ``routed`` ∪ ``intercepted`` ∪ (``dispatched`` ∩ ``buttoned``).
``advertised_not_reachable``
    владелец видит в меню команду, до которой нет пути — обещание без двери.
``reachable_not_advertised``
    дверь есть, в меню её нет. Само по себе НЕ дефект (адрес панели, кнопка
    аварийной остановки) — дефект, если причина не названа. Причины живут
    ОДНИМ объявлением ``TelegramBot._UNADVERTISED_BY_DESIGN``.
``dispatched_not_reachable``
    запись в карте диспетчера, до которой не доходит ни кнопка, ни набор, ни
    перехват. Прибор органов владельца считает её органом; путь к ней не
    ведёт ниоткуда.
``duplicate_declarations``
    объявление, чьё множество РАВНО множеству другой поверхности.

Разобрать не удалось — третий исход
===================================
Любой непрочитанный или неразобранный файл даёт ``unmeasured`` с НАЗВАННОЙ
причиной и ненулевой код возврата. «Поверхность пуста» и «поверхность не
измерена» различимы по построению (инв. #17): пустое множество при
``unmeasured = None`` есть ИЗМЕРЕННЫЙ ноль, и только он.

ADVISORY. Прибор только ЧИТАЕТ дерево: ни одной команды он не добавляет, не
убирает и не зовёт. Добавить владельцу ручку — решение владельца, а не строка
замера.
"""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
from typing import TypeGuard

REPO_ROOT = str(Path(__file__).resolve().parents[2])

#: Канал владельца и карта набранных команд — ДВА файла, и у каждого своя причина
#: быть здесь: первый несёт меню, диспетчер и кнопки, второй — маршрут набора.
BOT_REL = "spa_core/telegram/bot.py"
ROUTER_REL = "spa_core/telegram/router.py"

#: Имя атрибута-реестра маршрутов в :mod:`spa_core.telegram.router`.
ROUTER_MAP_NAME = "COMMAND_TO_PATH"

#: Имя объявления причин «дверь есть, в меню её нет».
REASONS_NAME = "_UNADVERTISED_BY_DESIGN"


def _parse(path: Path) -> tuple[ast.Module | None, str | None]:
    """Дерево файла либо НАЗВАННАЯ причина. Не исключение и не пустота."""
    try:
        return ast.parse(path.read_text(encoding="utf-8")), None
    except Exception as exc:  # noqa: BLE001
        return None, f"{path}: {type(exc).__name__}: {exc}"


def _is_command(value: object) -> TypeGuard[str]:
    """Строка — ИМЯ команды, а не просто косая черта.

    Отсечение не косметическое: рядом живёт ``_LEGACY_CB_PREFIXES``, где ``"/"``
    есть ПРЕФИКС (им проверяют `startswith`), а не команда. Считать его
    объявлением набора значило бы мерить не тот предмет.
    """
    return isinstance(value, str) and len(value) > 1 and value.startswith("/")


def _slash_strings(node: ast.AST) -> list[str]:
    """Литералы-команды из кортежа/списка. Нелитерал молча не теряется."""
    if not isinstance(node, (ast.Tuple, ast.List)):
        return []
    return [e.value for e in node.elts
            if isinstance(e, ast.Constant) and _is_command(e.value)]


def _advertised(cls: ast.ClassDef) -> list[str]:
    """Нагрузка ``setMyCommands``: каждый словарь с литеральным ключом ``command``.

    Ищется ФОРМА, а не имя переменной: переименование ``commands`` не должно
    ослеплять замер (тот же приём, что у соседа ``cio_kill_switch_controls``).
    """
    found: list[str] = []
    for fn in [n for n in ast.walk(cls) if isinstance(n, ast.FunctionDef)]:
        if fn.name != "register_commands":
            continue
        for node in ast.walk(fn):
            if not isinstance(node, ast.Dict):
                continue
            for key, value in zip(node.keys, node.values):
                if (isinstance(key, ast.Constant) and key.value == "command"
                        and isinstance(value, ast.Constant)
                        and isinstance(value.value, str)):
                    found.append("/" + value.value.lstrip("/"))
    return found


def _dispatched(cls: ast.ClassDef) -> list[str]:
    """Ключи карты «команда → ``self.<метод>``» внутри ``_dispatch``.

    Это ЕДИНСТВЕННОЕ объявление набора диспетчера: сама карта и есть контракт,
    потому что по ней идёт настоящая отправка. Любой второй список тех же имён
    попадёт в ``declared`` и будет назван копией.
    """
    for fn in [n for n in ast.walk(cls) if isinstance(n, ast.FunctionDef)]:
        if fn.name != "_dispatch":
            continue
        keys: list[str] = []
        for node in ast.walk(fn):
            if not isinstance(node, ast.Dict):
                continue
            for key, value in zip(node.keys, node.values):
                if (isinstance(key, ast.Constant) and _is_command(key.value)
                        and isinstance(value, ast.Attribute)):
                    keys.append(key.value)
        return keys
    return []


def _declarations(cls: ast.ClassDef) -> dict[str, list[str]]:
    """Класс-атрибуты вида ``NAME = ("/a", "/b", ...)`` — кандидаты в копии."""
    out: dict[str, list[str]] = {}
    for node in cls.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        values = _slash_strings(node.value)
        if isinstance(target, ast.Name) and values:
            out[target.id] = values
    return out


def _reasons(cls: ast.ClassDef) -> dict[str, str]:
    """Объявление причин: ``_UNADVERTISED_BY_DESIGN = {"/pause": "...", ...}``.

    Причина обязана быть непустой строкой: «и так понятно» причиной не
    является (`.claude/rules/site-numbers.md`, тот же порядок).
    """
    for node in cls.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if getattr(target, "id", "") != REASONS_NAME:
            continue
        if not isinstance(node.value, ast.Dict):
            return {}
        out: dict[str, str] = {}
        for key, value in zip(node.value.keys, node.value.values):
            if (isinstance(key, ast.Constant) and isinstance(key.value, str)
                    and isinstance(value, ast.Constant)
                    and isinstance(value.value, str)):
                out[key.value] = value.value
        return out
    return {}


def _buttoned(tree: ast.Module) -> list[str]:
    """Литералы ``callback_data``, начинающиеся с ``/`` — то, что КНОПКА пошлёт."""
    found: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values):
            if (isinstance(key, ast.Constant) and key.value == "callback_data"
                    and isinstance(value, ast.Constant)
                    and _is_command(value.value)):
                found.append(value.value)
    return found


def _routed(tree: ast.Module) -> list[str]:
    """Ключи ``COMMAND_TO_PATH`` — на что отвечает НАБРАННАЯ команда."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        if getattr(node.targets[0], "id", "") != ROUTER_MAP_NAME:
            continue
        if not isinstance(node.value, ast.Dict):
            continue
        return [k.value for k in node.value.keys
                if isinstance(k, ast.Constant) and _is_command(k.value)]
    return []


def measure(root: str = REPO_ROOT) -> dict:
    """Перепись шести поверхностей и производных. Только чтение.

    Третий исход: ``unmeasured`` несёт названную причину, и тогда ни одно
    число ниже читать нельзя — множества в ответе остаются пустыми, но
    отличить этот ноль от измеренного даёт именно ``unmeasured``.
    """
    bot_tree, bot_why = _parse(Path(root) / BOT_REL)
    router_tree, router_why = _parse(Path(root) / ROUTER_REL)
    empty = {
        "advertised": [], "dispatched": [], "routed": [], "intercepted": [],
        "buttoned": [], "declared": {}, "reasons": {}, "reachable": [],
        "advertised_not_reachable": [], "reachable_not_advertised": [],
        "dispatched_not_reachable": [], "unexplained_divergence": [],
        "stale_reasons": [], "reasons_without_cause": [],
        "duplicate_declarations": [],
    }
    if bot_tree is None or router_tree is None:
        why = "; ".join(w for w in (bot_why, router_why) if w)
        return {**empty, "unmeasured": why or "дерево не разобрано, причина не названа"}

    classes = [n for n in ast.walk(bot_tree) if isinstance(n, ast.ClassDef)]
    bot_cls = next((c for c in classes if c.name == "TelegramBot"), None)
    if bot_cls is None:
        return {**empty, "unmeasured": f"класс TelegramBot не найден в {BOT_REL}"}

    advertised = _advertised(bot_cls)
    dispatched = _dispatched(bot_cls)
    declared = _declarations(bot_cls)
    reasons = _reasons(bot_cls)
    buttoned = _buttoned(bot_tree)
    routed = _routed(router_tree)
    if not routed:
        return {**empty,
                "unmeasured": f"{ROUTER_MAP_NAME} не разобран в {ROUTER_REL} — "
                              "набранная команда не измерена"}
    intercepted = declared.get("_INTERCEPTED_COMMANDS", [])

    # Легаси-диспетчер достижим ТОЛЬКО кнопкой: `_dispatch` зовётся из ветви
    # callback_query, и набранный текст туда не попадает НИКОГДА.
    reachable = set(routed) | set(intercepted) | (set(dispatched) & set(buttoned))

    # Копия = объявление, чьё МНОЖЕСТВО равно множеству другой поверхности.
    # `_INTERCEPTED_COMMANDS` копией не является: оно есть ИСТОЧНИК своей
    # поверхности, и что оно не лжёт, мерит TestInterceptDeclaration.
    others = {"dispatched": set(dispatched), "advertised": set(advertised),
              "routed": set(routed)}
    duplicates = [{"name": name, "copy_of": surface, "size": len(values)}
                  for name, values in declared.items()
                  for surface, population in others.items()
                  if population and set(values) == population]

    advertised_not_reachable = sorted(set(advertised) - reachable)
    reachable_not_advertised = sorted(reachable - set(advertised))
    dispatched_not_reachable = sorted(set(dispatched) - reachable)
    unexplained = sorted(c for c in reachable_not_advertised if c not in reasons)
    stale = sorted(c for c in reasons if c not in reachable)
    blank = sorted(c for c, why in reasons.items() if not why.strip())

    return {
        "advertised": sorted(advertised),
        "dispatched": sorted(dispatched),
        "routed": sorted(routed),
        "intercepted": sorted(intercepted),
        "buttoned": sorted(set(buttoned)),
        "declared": {name: sorted(values) for name, values in declared.items()},
        "reasons": reasons,
        "reachable": sorted(reachable),
        "advertised_not_reachable": advertised_not_reachable,
        "reachable_not_advertised": reachable_not_advertised,
        "dispatched_not_reachable": dispatched_not_reachable,
        "unexplained_divergence": unexplained,
        "stale_reasons": stale,
        "reasons_without_cause": blank,
        "duplicate_declarations": duplicates,
        "unmeasured": None,
    }


def findings(measurement: dict) -> list[str]:
    """Строки-находки. Пустой список = ИЗМЕРЕННЫЙ ноль (``unmeasured`` is None)."""
    if measurement.get("unmeasured"):
        return [f"НЕ ИЗМЕРЕНО: {measurement['unmeasured']}"]
    out: list[str] = []
    for dup in measurement["duplicate_declarations"]:
        out.append(
            f"КОПИЯ ОБЪЯВЛЕНИЯ: {dup['name']} ({dup['size']}) побайтово повторяет "
            f"множество поверхности «{dup['copy_of']}» — два объявления одного "
            f"контракта расходятся МОЛЧА")
    for cmd in measurement["advertised_not_reachable"]:
        out.append(f"ОБЕЩАНИЕ БЕЗ ДВЕРИ: {cmd} в меню ☰, пути к нему нет")
    for cmd in measurement["dispatched_not_reachable"]:
        out.append(
            f"МЁРТВАЯ ДВЕРЬ: {cmd} есть в карте диспетчера, но до неё не доходит "
            f"ни кнопка, ни набор, ни перехват — органом владельца она не является")
    for cmd in measurement["unexplained_divergence"]:
        out.append(
            f"РАСХОЖДЕНИЕ БЕЗ ПРИЧИНЫ: {cmd} достижим, в меню ☰ его нет, и в "
            f"{REASONS_NAME} причина не названа")
    for cmd in measurement["stale_reasons"]:
        out.append(
            f"ПРИЧИНА ПЕРЕЖИЛА ДВЕРЬ: {REASONS_NAME}[{cmd}] объявлена, а сама "
            f"команда недостижима — исключение стало способом промолчать")
    for cmd in measurement["reasons_without_cause"]:
        out.append(f"ПРИЧИНА ПУСТА: {REASONS_NAME}[{cmd}] — «и так понятно» "
                   f"причиной не является")
    return out


def _report(measurement: dict) -> str:
    if measurement.get("unmeasured"):
        return f"НЕ ИЗМЕРЕНО: {measurement['unmeasured']}"
    lines = [
        "Командные поверхности владельца (разбор дерева, не подстрока):",
        f"  обещано (меню ☰, setMyCommands): {len(measurement['advertised'])}",
        f"  достижимо (набор ∪ перехват ∪ кнопка→диспетчер): "
        f"{len(measurement['reachable'])}",
        f"  карта диспетчера: {len(measurement['dispatched'])}"
        f" · набранных маршрутов: {len(measurement['routed'])}"
        f" · перехватов: {len(measurement['intercepted'])}"
        f" · кнопок: {len(measurement['buttoned'])}",
        f"  объявлений-кортежей в классе: {len(measurement['declared'])}"
        f" ({', '.join(sorted(measurement['declared'])) or '—'})",
        f"  достижимо и не обещано: {len(measurement['reachable_not_advertised'])}"
        f", из них БЕЗ названной причины {len(measurement['unexplained_divergence'])}",
    ]
    found = findings(measurement)
    lines += [f"  ⚠️ {line}" for line in found] or ["  ✅ находок нет (ИЗМЕРЕННЫЙ ноль)"]
    return "\n".join(lines)


def _main(argv: list[str] | None = None) -> int:
    summary = (__doc__ or "перепись командных поверхностей").splitlines()[0]
    parser = argparse.ArgumentParser(description=summary)
    parser.add_argument("--root", default=REPO_ROOT, help="корень дерева для разбора")
    parser.add_argument("--json", action="store_true", help="печатать замер как JSON")
    args = parser.parse_args(argv)

    measurement = measure(args.root)
    print(json.dumps(measurement, ensure_ascii=False, indent=2, sort_keys=True)
          if args.json else _report(measurement))
    if measurement.get("unmeasured"):
        return 2
    return 1 if findings(measurement) else 0


if __name__ == "__main__":  # pragma: no cover - CLI
    raise SystemExit(_main())
