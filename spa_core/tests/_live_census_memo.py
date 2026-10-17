"""Один замер живого дерева на сессию pytest — для тестов, что мерят ОДНО И ТО ЖЕ.

Замер 2026-10-17 (CI #6, группа G01): четыре файла тестов
(`test_rule_second_copy_census`, `test_rule_second_copy_peer_axis`,
`test_decision_surface_census`, `test_constitution_right_to_fix`) каждый
заново звали ``rule_second_copy_census.measure(<живое дерево>, now=_NOW)`` с
ОДНИМ И ТЕМ ЖЕ ``_NOW`` — восемь минут на этом Маке за вызов. Ответ на один
и тот же вопрос о том же дереве не меняется от того, какой файл его задал.

Что память НЕ меняет. Утверждения тестов читают ровно тот документ, который
вернул настоящий ``measure`` над настоящим деревом в этой же сессии; память
лишь не повторяет вызов. Поэтому:

* **ключ — содержимое дерева**, а не имя: ``(путь, mtime_ns, размер)`` каждого
  файла под корнем (без ``.git`` и кэшей байткода). Тест, изменивший хоть
  один файл, получает промах — замер пойдёт заново;
* **``now=None`` память не берёт вовсе**: ответ, зависящий от стенных часов,
  не равен самому себе через минуту, и выдать его второй раз значило бы
  подменить замер;
* **выдача — глубокая копия**: тест, поправивший свой экземпляр, не портит
  ответ соседу;
* **подменённый прибор память не берёт**: звать её разрешено только там, где
  тест ничего у прибора не подменяет (проводку меряют тесты с подменой, и они
  зовут ``measure`` напрямую). Подмена ловится и сама: ключ несёт тождество
  объекта функции, поэтому заменённая на время теста функция получает свой
  ключ, а не чужой ответ.

Контроль в обе стороны — ``test_live_census_memo.py``.
"""
from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any, Callable, Dict, Tuple

#: Каталоги, которые не являются входом ни одной переписи: история git,
#: кэши байткода и тестового прогона, зависимости сайта.
_SKIP_DIRS = frozenset({".git", "__pycache__", ".pytest_cache", ".mypy_cache",
                        "node_modules"})

_MEMO: Dict[Tuple[Any, ...], Any] = {}


def tree_fingerprint(root: Path) -> Tuple[Tuple[str, int, int], ...]:
    """``(путь, mtime_ns, размер)`` каждого файла под ``root`` — в порядке обхода.

    Нечитаемый файл входит в отпечаток своей ошибкой, а не пропадает из него:
    иначе «файл стал нечитаем» было бы неотличимо от «файла не было».
    """
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS)
        for name in sorted(filenames):
            path = os.path.join(dirpath, name)
            try:
                st = os.stat(path)
            except OSError as exc:
                out.append((path, -1, hash(type(exc).__name__)))
                continue
            out.append((path, st.st_mtime_ns, st.st_size))
    return tuple(out)


def measure_once(fn: Callable[..., Any], root: Path, **kwargs: Any) -> Any:
    """``fn(root, **kwargs)`` — из памяти сессии, если дерево не менялось.

    ``now`` обязан быть передан явно: без него ответ зависит от часов и
    память не берётся (вызов идёт как есть).
    """
    if kwargs.get("now") is None:
        return fn(root, **kwargs)
    resolved = Path(root).resolve()
    key = (id(fn), getattr(fn, "__module__", None),
           getattr(fn, "__qualname__", None), str(resolved),
           tuple(sorted((k, repr(v)) for k, v in kwargs.items())),
           tree_fingerprint(resolved))
    if key not in _MEMO:
        # Функция держится в записи, чтобы её `id()` не мог достаться другой.
        _MEMO[key] = (fn, fn(root, **kwargs))
    return copy.deepcopy(_MEMO[key][1])


def clear() -> None:
    """Забыть всё (для контрольных тестов памяти)."""
    _MEMO.clear()
