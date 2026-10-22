"""Память чистых выводов из ТЕКСТА исходника — на процесс, ключ = хэш текста.

Зачем (замер 2026-10-22, `BatteryHoleTests`, перепись G16). Полная перепись
читателей журнала зовёт каждого читателя четыре раза, а читатель
`heir_all_rows_price` внутри себя гонит ту же перепись ещё раз на каждом из
своих четырёх зовов. Читатели-переписи дерева (`acceptance_tree_capability` →
`cio_decision_owner_census` → `cio_target_producers`, `pre_trade_recheck_census`,
`ledger_parse_census`) на КАЖДОМ зове заново разбирали AST тех же ~2500–9700
файлов и обходили его теми же функциями: за одну перепись — двадцать одинаковых
разборов одного и того же дерева.

Что здесь запоминается и почему ответ из памяти тождествен вычислению:

* ключ — sha256 того САМОГО текста, который иначе ушёл бы в ``ast.parse``,
  плюс все прочие входы функции (``extra``: путь файла, искомые виды,
  модульные константы, от которых вывод зависит). Изменённый файл даёт промах
  сам, без отметок времени — mtime здесь не нужен и был бы слабее;
* текст по-прежнему ЧИТАЕТСЯ с диска на каждом зове: память отвечает только на
  вопрос «что выводится из этого текста», а не «что лежит на диске»;
* запоминается только ВЫВОД чистой функции; исключение (``SyntaxError`` и пр.)
  не запоминается и поднимается так же, как без памяти;
* изменяемый результат отдаётся КОПИЕЙ (``copy.deepcopy``): вызывающий вправе
  его править (``cio_target_producers`` переписывает ``provenance`` у сайта), и
  правка не должна протечь в следующий ответ. Неизменяемый (frozenset строк,
  bool, None) отдаётся как есть.

Тот же приём и то же обоснование уже живут в
``run_identity_key_price._IMPORT_DEPS_MEMO`` (замер 2026-10-17, CI #6).
Только stdlib (инв. #4).
"""
from __future__ import annotations

import copy
import hashlib
from typing import Callable, Dict, Hashable, Tuple, TypeVar

T = TypeVar("T")

#: Потолок записей одной памяти. Дерево — ~10 тыс. файлов; потолок держит
#: память ограниченной на долгоживущем процессе, а не меняет ответ.
DEFAULT_CAP = 50_000


def text_digest(text: str) -> bytes:
    """Отпечаток текста: тот же байтовый образ, что уходит в разбор."""
    return hashlib.sha256(text.encode("utf-8", errors="surrogatepass")).digest()


class SourceMemo:
    """Память «(текст, прочие входы) → вывод чистой функции»."""

    def __init__(self, name: str, *, immutable: bool = False,
                 cap: int = DEFAULT_CAP) -> None:
        self.name = name
        self.immutable = immutable
        self.cap = cap
        self._data: Dict[Tuple[bytes, Hashable], object] = {}
        self.hits = 0
        self.misses = 0

    def get(self, text: str, extra: Hashable, compute: Callable[[], T]) -> T:
        key = (text_digest(text), extra)
        try:
            value = self._data[key]
        except KeyError:
            value = compute()          # исключение не запоминается
            if len(self._data) >= self.cap:
                self._data.clear()
            self._data[key] = value
            self.misses += 1
        else:
            self.hits += 1
        return value if self.immutable else copy.deepcopy(value)

    def lookup(self, text: str, extra: Hashable) -> Tuple[bool, object]:
        """``(есть ли, значение)`` — для вызывающего, у которого разбор и вывод
        стоят под РАЗНЫМИ ``except`` и смешивать их нельзя."""
        key = (text_digest(text), extra)
        if key in self._data:
            self.hits += 1
            value = self._data[key]
            return True, (value if self.immutable else copy.deepcopy(value))
        return False, None

    def store(self, text: str, extra: Hashable, value: T) -> T:
        """Положить вычисленный вывод; вернуть то, что отдал бы :meth:`get`."""
        if len(self._data) >= self.cap:
            self._data.clear()
        self._data[(text_digest(text), extra)] = value
        self.misses += 1
        return value if self.immutable else copy.deepcopy(value)

    def clear(self) -> None:
        self._data.clear()
        self.hits = 0
        self.misses = 0

    def __len__(self) -> int:
        return len(self._data)
