"""Храповик: класс «прогон пишет в живое git-tracked состояние» может только уменьшаться.

Замер цикла #352 на чистом `origin/main` (`cb1faaa7e`): полный прогон оставляет
после себя изменёнными десятки git-tracked путей — журналы аналитиков, журнал
тревог владельца, `spa.db`, а до починки этого же цикла и `live_execution_log.json`
(домен ИСПОЛНЕНИЯ). Прямой запрет покрасил бы CI в первый же день и был бы снят
раньше, чем починен хоть один писатель — этот проект уже платил за такой сторож
(`test_frozen_date_ratchet`, 346 файлов в классе).

Поэтому база коммитится, а храповик держит НАПРАВЛЕНИЕ:

* новый путь, которого в базе нет, роняет прогон (`live_data_write_guard`);
* база может только уменьшаться — потолок ниже записан числом и снижается вместе
  с ней;
* **дописать путь в базу, чтобы погасить падение, запрещено.** Чинить писателя:
  подменить каталог состояния на tmp в фикстуре его тест-файла (образец —
  `test_engine_bridge.py::test_paper_insert_when_live_fails`, починенный тем же
  циклом), время передавать входом (`now=`).

Карта «какой тест какой путь пишет» снимается прогоном с `SPA_DATA_WRITE_AUDIT=1`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

guard = sys.modules.get("spa_live_data_write_guard")
if guard is None:                                   # прямой запуск без conftest
    from spa_core.tests import live_data_write_guard as guard

#: Потолок класса на 2026-08-23 (замер цикла #352, полная команда CI на чистом
#: `origin/main` cb1faaa7e). Снижать вместе с базой; поднимать — НИКОГДА.
BASELINE_CEILING = 81


def _raw():
    return json.loads(guard.BASELINE_PATH.read_text(encoding="utf-8"))


def test_baseline_exists_and_explains_itself():
    """База без объяснения — молчаливое разрешение; такого здесь быть не должно.

    Пустой список путей допустим НАМЕРЕННО: это состояние «класс закрыт
    полностью», то есть цель храповика. Проверка, требующая непустой базы,
    краснела бы ровно в день победы.
    """
    raw = _raw()
    assert isinstance(raw, dict) and isinstance(raw.get("paths"), list)
    assert len(raw.get("_comment", "")) > 80


def test_baseline_may_only_shrink():
    """Главное утверждение храповика: класс не растёт."""
    paths = _raw()["paths"]
    assert len(paths) <= BASELINE_CEILING, (
        f"в базе {len(paths)} путей при потолке {BASELINE_CEILING}. "
        "Дописывать сюда, чтобы погасить падение, ЗАПРЕЩЕНО — чинить писателя "
        "(карта: прогон с SPA_DATA_WRITE_AUDIT=1)."
    )


def test_baseline_has_no_duplicates_and_is_sorted():
    """Дубль прячет размер класса, а порядок делает diff читаемым."""
    paths = _raw()["paths"]
    assert len(paths) == len(set(paths))
    assert paths == sorted(paths)


def test_baseline_paths_are_repo_relative():
    """Абсолютный путь в базе — разрешение, действующее только на одной машине."""
    for p in _raw()["paths"]:
        assert not Path(p).is_absolute(), p


def test_baseline_covers_only_watched_dirs():
    """Разрешение шире, чем область наблюдения, — тихое расширение полномочий."""
    for p in _raw()["paths"]:
        target = guard.REPO_ROOT / p
        assert any(w in target.parents for w in guard.WATCHED), p


def test_execution_domain_is_not_in_the_baseline():
    """`live_execution_log.json` закрыт починкой, а не разрешением.

    Карточка требовала закрыть его ОТДЕЛЬНО и ПЕРВЫМ (инв. #6: read-only код не
    ходит в домен исполнения). Обратный контроль: если он снова окажется в базе,
    значит кто-то погасил падение разрешением вместо починки.
    """
    assert not any("live_execution_log" in p for p in _raw()["paths"])


def test_unreadable_baseline_is_read_as_empty(tmp_path):
    """Сломанная база делает сторожа СТРОЖЕ, а не слепее (fail-CLOSED)."""
    broken = tmp_path / "broken.json"
    broken.write_text("{не json", encoding="utf-8")
    assert guard.load_baseline(broken) == frozenset()
    assert guard.load_baseline(tmp_path / "нет-такого-файла.json") == frozenset()


def test_baseline_silences_only_what_is_in_it(monkeypatch, tmp_path):
    """Путь из базы прогон не роняет; соседний — роняет."""
    base = tmp_path / "b.json"
    base.write_text(json.dumps({"paths": ["data/allowed.json"]}), encoding="utf-8")
    monkeypatch.setattr(guard, "BASELINE_PATH", base)
    monkeypatch.setattr(guard, "_reported", False)
    monkeypatch.setattr(guard, "_tracked", None)   # снимок подменён — фильтр не нужен
    monkeypatch.setattr(guard, "_session_before", {"data/allowed.json": (1, 1)})
    monkeypatch.setattr(guard, "snapshot",
                        lambda roots=None: {"data/allowed.json": (2, 1)})

    class _S:
        exitstatus = 0

    session = _S()
    assert guard.session_finish(session) == ()
    assert session.exitstatus == 0

    monkeypatch.setattr(guard, "_reported", False)
    monkeypatch.setattr(guard, "snapshot",
                        lambda roots=None: {"data/allowed.json": (2, 1),
                                            "data/new_writer.json": (3, 1)})
    other = _S()
    assert guard.session_finish(other) == ("data/new_writer.json",)
    assert other.exitstatus == 1
