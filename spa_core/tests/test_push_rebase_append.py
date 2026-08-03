"""
spa_core/tests/test_push_rebase_append.py

Гейт против рецидива: **пере-база дописывания не имеет права дублировать байты**
(карточка `agent-task-povtornoe-dopisyvanie-faila-v-odnom-tsik`, найдено циклом
#95, закрыто циклом #99).

ЧТО ЛОВИМ. `push_to_github.py::rebase_append` распознаёт дописывание побайтово и
накладывает НАШ хвост на свежее содержимое remote. Хвост считался от `base` —
то есть от git HEAD рабочего дерева, — а не от того, что мы сами уже доставили.
Протокол (§3.4 «изолированный worktree» + «Шаг 3 — обновить память») обязывает
цикл дописывать `docs/journal/<неделя>.md`, и цикл, дописавший его ДВАЖДЫ
(сделал → подтвердил прогоном), попадал в условия срабатывания по построению:

    base   = B                (git HEAD рабочего дерева — за цикл не двигается)
    remote = B + S1           (наш же первый пуш этого цикла)
    local  = B + S1 + S2
    tail   = local[len(B):] = S1 + S2
    итог   = remote + tail  = B + S1 + S1 + S2      ← S1 продублирована

Оба `startswith(base)` выполнены, поэтому отказа не было: расхождение
классифицировалось как «чистое дописывание», то есть как БЕЗОПАСНЫЙ случай, и
инструмент печатал `OK … pushed=1, skipped=0` о результате, которого не
проверял. Измерено в цикле #95 на `docs/journal/2026-W32.md`: секция
«### Подтверждено реальным Actions» уехала на origin дважды (строки 167 и 186).
Тот же класс, что закрытые `agent-push-worktree-path-collapse` и
`agent-push-batch-per-file-commits`: доставка рапортует об успехе, которого не
измеряла. На `STATE.md` (правка в СЕРЕДИНЕ файла) это дало бы честный отказ — на
журнале (дописывание в конец) давало тихую порчу общей памяти проекта.

ЧЕГО ЗДЕСЬ НЕТ. Слияния «по смыслу» не появилось: правка в середине файла
по-прежнему `None` ⇒ `DivergenceRefused` (fail-CLOSED, инв. #2), и `--allow-overwrite`
остаётся единственным способом осознанной перезаписи. Ни один существующий
ассерт не ослаблен (инв. #16) — файл только добавляет проверки.

Сеть НЕ ТРОГАЕТСЯ: `rebase_append` — чистая функция над тремя bytes.

Запуск: python3 -m pytest spa_core/tests/test_push_rebase_append.py -v
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

BASE = b"# journal\n\n## week 32\n"
S1 = b"### cycle 99 - work\ndelivered the fix\n"
S2 = b"### cycle 99 - confirmed by Actions\ngreen\n"
OTHER = b"### cycle 100 - another session\nits own entry\n"


def _load(name: str, rel: str):
    """Загрузить пушер по явному пути (как это делает прод-код и copy-guard)."""
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def ptg():
    return _load("_test_rebase_ptg", "push_to_github.py")


# --------------------------------------------------------------------------
# Сценарий цикла #95 — дословно. КРАСНЫЙ без фикса.
# --------------------------------------------------------------------------

def test_second_append_in_one_cycle_duplicates_nothing(ptg):
    """base=B, remote=B+S1 (наш первый пуш), local=B+S1+S2 (дописали второй раз).

    Единственный правильный ответ — ровно `local`: на remote уже лежит S1, наш
    хвост относительно remote — только S2. Ассерт побайтовый и на количество
    вхождений S1, чтобы «почти правильный» результат не прошёл.
    """
    remote = BASE + S1
    local = BASE + S1 + S2

    out = ptg.rebase_append(BASE, local, remote)

    assert out == local, (
        "пере-база продублировала уже доставленное: ожидалось B+S1+S2, "
        f"получено {out!r}")
    assert out.count(S1) == 1, "секция первого пуша уехала на origin дважды"
    assert out.count(S2) == 1, "секция второго пуша уехала на origin дважды"


def test_re_push_of_unchanged_file_does_not_duplicate(ptg):
    """Вырожденный случай той же семьи: local уже РАВЕН remote.

    Считая хвост от базы, функция возвращала B+S1+S1 — дубль на ровном месте.
    Правильный ответ — содержимое remote без изменений (пуш становится no-op).
    """
    remote = BASE + S1

    out = ptg.rebase_append(BASE, remote, remote)

    assert out == remote, f"повторный пуш неизменного файла продублировал S1: {out!r}"


def test_repeated_append_survives_a_parallel_writer_between_our_pushes(ptg):
    """Смешанный случай: между нашими двумя пушами дописала ЧУЖАЯ сессия.

    base=B, remote=B+S1+OTHER, local=B+S1+S2. Наш хвост относительно remote —
    только S2; S1 на remote уже есть, а чужую запись терять нельзя.
    """
    remote = BASE + S1 + OTHER
    local = BASE + S1 + S2

    out = ptg.rebase_append(BASE, local, remote)

    assert out == BASE + S1 + OTHER + S2, f"неожиданный результат: {out!r}"
    assert out.count(S1) == 1, "наша первая секция продублирована"
    assert out.count(OTHER) == 1, "чужая запись потеряна или продублирована"
    assert out.count(S2) == 1, "наша вторая секция продублирована"


# --------------------------------------------------------------------------
# Положительные контроли: то, что работало, обязано работать по-прежнему.
# Без них «ничего не дублируется» проходило бы и на функции, которая просто
# всегда возвращает `local` — это ровно fail-OPEN класса #29/#31/#35–#38/#40.
# --------------------------------------------------------------------------

def test_genuine_parallel_append_keeps_both_entries(ptg):
    """Две сессии дописали РАЗНОЕ от общей базы — обе записи обязаны выжить."""
    remote = BASE + OTHER
    local = BASE + S1

    out = ptg.rebase_append(BASE, local, remote)

    assert out == BASE + OTHER + S1, f"чужая или наша запись потеряна: {out!r}"
    assert OTHER in out and S1 in out


def test_our_tail_is_not_lost_when_remote_moved(ptg):
    """Прямая проверка, что функция вообще накладывает хвост, а не отдаёт remote."""
    out = ptg.rebase_append(BASE, BASE + S1, BASE + OTHER)
    assert out is not None and out.endswith(S1)


# --------------------------------------------------------------------------
# fail-CLOSED: то, что обязано ОТКАЗЫВАТЬ, отказывает по-прежнему.
# --------------------------------------------------------------------------

def test_edit_in_the_middle_is_still_refused(ptg):
    """Так меняется `docs/STATE.md` — префикс сломан, слияния «по смыслу» нет."""
    local = BASE.replace(b"week 32", b"week 33") + S1
    assert ptg.rebase_append(BASE, local, BASE + OTHER) is None


def test_remote_that_left_our_base_is_still_refused(ptg):
    """remote не начинается с базы ⇒ дописыванием это не разрешается."""
    remote = b"totally rewritten\n"
    assert ptg.rebase_append(BASE, BASE + S1, remote) is None


def test_empty_tail_is_refused(ptg):
    """Нам нечего доливать (local == base), а remote ушёл вперёд ⇒ не наш случай."""
    assert ptg.rebase_append(BASE, BASE, BASE + OTHER) is None


@pytest.mark.parametrize("base,local,remote", [
    (None, BASE + S1, BASE + OTHER),
    (BASE, None, BASE + OTHER),
    (BASE, BASE + S1, None),
])
def test_missing_input_is_refused(ptg, base, local, remote):
    """Не прочитали что-то из трёх — отказ, а не догадка (инв. #2)."""
    assert ptg.rebase_append(base, local, remote) is None


# --------------------------------------------------------------------------
# Контроль против «умного» слияния: пере-база НЕ имеет права резать строку
# посередине, даже если две разные записи совпали первыми байтами.
# --------------------------------------------------------------------------

def test_entries_sharing_a_line_prefix_are_not_spliced_mid_line(ptg):
    """`### cycle 98…` и `### cycle 99…` совпадают на 10 байт.

    Наивный «общий префикс» склеил бы их в мусор вида `### cycle 98…9 …`.
    Границей может быть только конец строки.
    """
    remote = BASE + b"### cycle 98 - theirs\nbody 98\n"
    local = BASE + b"### cycle 99 - ours\nbody 99\n"

    out = ptg.rebase_append(BASE, local, remote)

    assert out == remote + b"### cycle 99 - ours\nbody 99\n", f"склейка порезала строку: {out!r}"
    assert b"### cycle 99 - ours\n" in out, "заголовок нашей записи потерян"
    assert b"### cycle 98 - theirs\n" in out, "заголовок чужой записи потерян"

