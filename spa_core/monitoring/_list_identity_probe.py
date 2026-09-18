"""Зов питоньих читателей ОДИН раз и разбор списков в их ответах.

Заказ **G34, п. 1**. Здесь живёт правило классификации одного списка; сам зов
населения и свод — у `list_identity_census`. Разделение не косметическое: зонд
исполняется отдельным процессом, потому что втягивает под сотню читателей, а
их импорт не имеет права оседать в процессе, который пишет артефакт.

Правило «кто такая личность» НЕ копируется: годность поля спрашивается у той же
`element_identity`, которой судит перепись, а её кортеж имён читается отсюда же
(`IDENTITY_FIELDS`). Вторая копия правила была бы ровно тем классом, который
семья приборов и ловит у читателей.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import os
import sys

# Запуск по пути кладёт каталог скрипта первым в `sys.path`, и сосед
# `spa_core/monitoring/signal.py` затенил бы стандартный `signal`. Зонд зовётся
# через `-m` (пина часов тут нет, и класс подменять нечем), но снимать всё
# равно ДО остальных импортов: цена ошибки — падение импорта всего пакета.
if __name__ == "__main__" and sys.path and (
        os.path.realpath(sys.path[0])
        == os.path.dirname(os.path.realpath(__file__))):
    del sys.path[0]

import importlib  # noqa: E402
import json  # noqa: E402
import pathlib  # noqa: E402
from typing import Dict, List, Optional, Tuple  # noqa: E402

from spa_core.monitoring.run_identity_key_price import (  # noqa: E402
    _IDENTITY_FIELDS, _ident_token, element_identity, indexed,
    module_driver, no_entry_cause,
)

#: Каталог стенда (его подкаталог ``data/`` получает читатель).
STAND_ENV = "SPA_READER_STAND"

#: Момент прогона — он же значение ``now=`` (ISO-8601 с поясом).
CLOCK_ENV = "SPA_CENSUS_PINNED_NOW"

#: Имена, которыми элемент вправе назвать себя СЕГОДНЯ — у самой переписи.
IDENTITY_FIELDS: Tuple[str, ...] = tuple(_IDENTITY_FIELDS)

#: Потолок узлов на ОДНОГО читателя. Превышен ⇒ строка помечается усечённой, а
#: не молча обрезается: «не досмотрели» и «не нашли» обязаны быть различимы.
NODE_BUDGET = 200_000

_MISSING = object()


class _Budget:
    """Счётчик узлов обхода. Исчерпан — говорит об этом, а не молчит."""

    def __init__(self, limit: int = NODE_BUDGET) -> None:
        self.left = int(limit)
        self.exhausted = False

    def spend(self) -> bool:
        if self.left <= 0:
            self.exhausted = True
            return False
        self.left -= 1
        return True


def field_verdict(items: List[dict], field: str) -> Tuple[bool, str]:
    """Годно ли поле в личность — и ПОЧЕМУ нет, если нет.

    Вердикт (первое значение) обязан совпадать с тем, что вынесла бы
    `element_identity`; вторая половина — только диагноз для отчёта. Поэтому
    «поля нет» и «поле не скалярно» дают ОДИН вердикт (``get`` отдаёт ``None``,
    а ``None`` не скаляр) и разные причины: причина объясняет, вердикт решает.
    """
    values = [item.get(field, _MISSING) for item in items]
    if any(v is _MISSING for v in values):
        return False, "field_absent"
    if not all(isinstance(v, (str, int, float)) and not isinstance(v, bool)
               for v in values):
        return False, "not_scalar"
    tokens = [_ident_token(v) for v in values]
    if len(set(tokens)) != len(tokens):
        return False, "not_unique"
    return True, ""


def candidates_outside(items: List[dict]) -> List[str]:
    """Годные поля, которых НЕТ в нынешнем списке имён.

    Население кандидатов — объединение ключей по всем элементам, а не ключи
    первого: элемент, у которого поля нет, всё равно отвергнет кандидата
    (``field_absent``), и брать ключи одного элемента значило бы решать состав
    населения порядком обхода.
    """
    keys: List[str] = []
    seen = set()
    for item in items:
        for key in item:
            if isinstance(key, str) and key not in seen and key not in IDENTITY_FIELDS:
                seen.add(key)
                keys.append(key)
    return sorted(k for k in keys if field_verdict(items, k)[0])


def classify_list(items) -> dict:
    """Один список — один исход, и их четыре, а не два.

    * ``named`` — личность есть, названа полем из нынешнего списка имён;
    * ``unnamed_empty`` — список пуст: называть нечего;
    * ``unnamed_not_dicts`` — элементы не словари: полем себя не называют
      по построению, и это не пробел списка имён;
    * ``unnamed_candidate_outside`` — словари, годного имени из списка нет, а
      ВНЕ списка — есть. Это и есть предмет заказа;
    * ``unnamed_no_candidate`` — словари, годного поля нет вовсе. Третий исход
      честен: обход остаётся позиционным не от недосмотра.
    """
    row: dict = {"n": len(items) if isinstance(items, list) else 0}
    if not isinstance(items, list) or not items:
        row["outcome"] = "unnamed_empty"
        return row
    if not all(isinstance(item, dict) for item in items):
        row["outcome"] = "unnamed_not_dicts"
        return row
    field = element_identity(items)
    if field is not None:
        row["outcome"] = "named"
        row["field"] = field
        return row
    outside = candidates_outside(items)
    row["outcome"] = ("unnamed_candidate_outside" if outside
                      else "unnamed_no_candidate")
    if outside:
        row["candidates"] = outside
    # Почему отвергнуты имена ИЗ списка — диагноз, а не вердикт: без него
    # «личности нет» не отличить от «поле есть, но неуникально».
    rejected = {}
    for name in IDENTITY_FIELDS:
        ok, cause = field_verdict(items, name)
        if not ok and cause != "field_absent":
            rejected[name] = cause
    if rejected:
        row["whitelisted_rejected"] = rejected
    return row


def walk_lists(answer, budget: _Budget, path: str = "") -> List[dict]:
    """Все списки ответа — с координатой, записанной ПРАВИЛОМ семьи.

    Координата собирается тем же ``indexed``, которым её собирают обходы
    переписи: разойдись запись, ни одна найденная координата не нашлась бы у
    соседа по своему же адресу.

    Контейнеры, уже виденные по тождеству объекта, не обходятся повторно —
    ответ читателя вправе делить один список между полями, и цикл в нём тоже
    возможен; молчаливое зацикливание было бы «не измерено» без причины.
    """
    out: List[dict] = []
    seen: set = set()

    def _walk(node, where: str) -> None:
        if not budget.spend():
            return
        if isinstance(node, dict):
            if id(node) in seen:
                return
            seen.add(id(node))
            for key in sorted(node, key=str):
                _walk(node[key], f"{where}.{key}")
        elif isinstance(node, list):
            if id(node) in seen:
                return
            seen.add(id(node))
            row = classify_list(node)
            row["coord"] = where or "."
            out.append(row)
            field = row.get("field")
            for suffix, value in indexed(node, field):
                _walk(value, f"{where}{suffix}")

    _walk(answer, path)
    return out


def probe_modules(names: List[str], stand: pathlib.Path, now) -> Dict[str, dict]:
    """Позвать каждого читателя ОДИН раз и разобрать списки его ответа.

    Одного зова довольно: вопрос про СОСТАВ ответа, а не про его устойчивость.
    Второй зов ответил бы на вопрос соседа и стоил бы вдвое.
    """
    out: Dict[str, dict] = {}
    for name in names:
        try:
            mod = importlib.import_module(name)
        except BaseException as exc:                          # noqa: BLE001
            out[name] = {"cause": "import_failed",
                         "reason": f"импорт не удался: {type(exc).__name__}"}
            continue
        entry, call = module_driver(mod, now=now)
        if call is None:
            cause, reason = no_entry_cause(mod)
            out[name] = {"cause": cause, "reason": reason}
            continue
        try:
            answer = call(stand)
        except BaseException as exc:                          # noqa: BLE001
            out[name] = {"cause": "entry_raised",
                         "reason": f"{entry}() упал: {type(exc).__name__}"}
            continue
        budget = _Budget()
        rows = walk_lists(answer, budget)
        out[name] = {"entry": entry, "lists": rows,
                     "truncated": budget.exhausted}
    return out


def main(argv: Optional[List[str]] = None) -> int:
    """``_list_identity_probe <modules.json> <out.json>``.

    Стенд и часы обязаны быть заданы: без стенда зов пошёл бы против ЖИВОГО
    каталога, без часов читатель взял бы их у машины — и то и другое сделало бы
    замер выдумкой, а не наблюдением.
    """
    argv = sys.argv[1:] if argv is None else list(argv)
    if len(argv) != 2:
        sys.stderr.write("usage: _list_identity_probe <modules.json> <out.json>\n")
        return 2
    stand_raw = str(os.environ.get(STAND_ENV) or "").strip()
    if not stand_raw:
        sys.stderr.write(f"ОТКАЗ: {STAND_ENV} не задана — зов пошёл бы против "
                         "ЖИВОГО каталога\n")
        return 2
    pinned_iso = str(os.environ.get(CLOCK_ENV) or "").strip()
    if not pinned_iso:
        sys.stderr.write(f"ОТКАЗ: {CLOCK_ENV} не задана — читатель взял бы часы "
                         "у машины\n")
        return 2
    import datetime as _dt
    now = _dt.datetime.fromisoformat(pinned_iso)
    if now.tzinfo is None:
        sys.stderr.write(f"ОТКАЗ: {CLOCK_ENV} без пояса: {pinned_iso!r}\n")
        return 2

    names = json.loads(pathlib.Path(argv[0]).read_text(encoding="utf-8"))
    answer = {"__modules__": probe_modules(list(names), pathlib.Path(stand_raw), now)}
    pathlib.Path(argv[1]).write_text(
        json.dumps(answer, sort_keys=True, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":                                    # pragma: no cover
    raise SystemExit(main())
