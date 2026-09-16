#!/usr/bin/env python3
"""Кэш таблиц символов карты компонентов не имеет права ключеваться адресом дерева.

Найдено 16.09.2026 при доставке ADR-400 (правка Телеграма, к этому модулю не
относящаяся): ``test_receiver_of_a_method_call_is_a_site`` в одиночку зелёный, а
в составе файла — ``read=False``; на чистом ``origin/main`` файл зелёный, на ветке с
другими файлами в дереве — красный. Причина — ``_SYMBOLS: dict[int, …]`` по ``id(tree)``
без вытеснения: адрес освобождённого дерева переиспользуется следующим ``ast.parse``,
и новое дерево получало таблицы чужого модуля. Такое падение зависит от раскладки
памяти, то есть от любого соседнего изменения, и не воспроизводится «по требованию».

Контроль здесь ДЕТЕРМИНИРОВАННЫЙ: коллизия адресов навязывается подменой ``id`` в
пространстве имён модуля. Прежний кэш под такой подменой отдавал второму дереву
таблицы первого (тест красный), кэш на самом узле дерева не смотрит на адрес вовсе.
"""
from __future__ import annotations

import ast
import textwrap
from unittest import mock

from spa_core.monitoring import cio_component_map as mod


def _t(src: str) -> ast.AST:
    return ast.parse(textwrap.dedent(src))


SRC_A = '''
    from spa_core.utils.atomic import atomic_save
    NAME = "a.json"
    def w(d):
        atomic_save({}, str(d / NAME))
'''
SRC_B = '''
    from pathlib import Path
    NAME = "b.json"
    def r(d):
        return (Path(d) / NAME).read_text()
'''


def test_two_trees_never_share_tables_even_when_addresses_collide():
    """Положительный контроль дефекта: при совпадении id() второе дерево читается само."""
    a = _t(SRC_A)
    b = _t(SRC_B)
    with mock.patch.object(mod, "id", lambda _obj: 42, create=True):
        assert mod.product_sites(a, "a.json")["write"]
        got = mod.product_sites(b, "b.json")
    assert got["read"], "дерево B получило таблицы дерева A — кэш ключуется адресом"
    assert not got["write"]


def test_cache_is_reused_on_the_same_tree():
    """Обратный контроль: производительность не потеряна — таблицы того же дерева не пересобираются."""
    a = _t(SRC_A)
    first = mod._symbols_cached(a)
    assert mod._symbols_cached(a) is first


def test_no_address_keyed_dictionary_remains():
    """Словарь по id() — сам дефект; его отсутствие проверяется явно."""
    assert not hasattr(mod, "_SYMBOLS")
