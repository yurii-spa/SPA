"""Контроль пробы `mutation_window_restore_refuses_a_live_owner` (ADR-791, цикл #913).

Проба объявляет, что возврат байтов из окна мутационного прибора ОТКАЗЫВАЕТ, пока
владелец окна работает, и ВОЗВРАЩАЕТ, когда владелец мёртв. Проверить это можно только
одним способом: порвать у прибора по одному звену и убедиться, что проба КРАСНЕЕТ с
НАЗВАННЫМ звеном. Проба, никогда не видевшая настоящей поломки, — украшение
(`.claude/rules/deployment.md` § «Проверка сторожа сторожей»).

Рвём не выдуманный заменитель, а НАСТОЯЩИЙ текст прибора — на одноразовой копии, по
одному якорю за раз. Якорь проверяется на единственность ДО подмены: подмена, не нашедшая
якоря, оставила бы прибор исправным, проба позеленела бы, и это читалось бы как «звено
защищено» (класс `mutation_application_census`, ADR-558).

**Чего контроль НЕ покрывает, и это сказано вслух.** Два щита пробы стоя́т ЗА другими по
порядку и одиночной поломкой не достигаются: «живой и мёртвый владелец дали ОДИН код»
(чтобы его достать, надо одновременно сломать распознавание смерти И уравнять коды) и
«после возврата при мёртвом владельце байты не исходные» (любая поломка записи раньше
даёт ненулевой код мёртвой сцены). Они остаются защитой от будущей правки, а не
измеренным звеном, и выдавать их за измеренное нельзя.

Третий щит — сверка БАЙТОВ под работающим прибором — в первой редакции этого файла тоже
был без контроля, и об этом сказал не глаз автора, а мутационный прибор: мутация «проба
перестала сверять байты» ВЫЖИЛА. Контроль ниже
(`test_a_refusal_that_restores_anyway_is_caught`) достаёт его одним якорем — отказ,
который всё равно переписал файл; это не выдуманная поломка, а самый дорогой вид отказа:
вердикт «не тронул» при тронутых байтах.
"""
from __future__ import annotations

import json
import os
import shutil
import sys

import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _REPO_ROOT)

from spa_core.monitoring import card_acceptance as ca  # noqa: E402

_PROBE_NAME = "mutation_window_restore_refuses_a_live_owner"
_TOOL_REL = os.path.join("scripts", "delta_mutation_run.py")


def _probe():
    assert _PROBE_NAME in ca.PROBES, (
        "проба потеряла РЕГИСТРАЦИЮ: шаг 0-офис обходит реестр, а не модуль, — "
        "незарегистрированная проба не меряет ничего и молчит об этом")
    return ca.PROBES[_PROBE_NAME]


def _stand(tmp_path) -> str:
    """Одноразовое дерево с настоящим прибором. Живое дерево не трогается."""
    stand = tmp_path / "stand"
    (stand / "scripts").mkdir(parents=True)
    shutil.copy2(os.path.join(_REPO_ROOT, _TOOL_REL), str(stand / _TOOL_REL))
    return str(stand)


def _patch(stand: str, old: str, new: str) -> None:
    """Порвать ОДНО звено прибора. Якоря нет или он не один ⇒ падать ГРОМКО."""
    path = os.path.join(stand, _TOOL_REL)
    text = open(path, encoding="utf-8").read()
    found = text.count(old)
    assert found == 1, (
        f"звено не найдено однозначно (вхождений {found}): подмена ничего не рвёт, и "
        f"зелёная проба читалась бы как «звено защищено»")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text.replace(old, new))


# ───────────────────────── зелёный контур ─────────────────────────


@pytest.mark.timeout(900)
def test_the_probe_is_green_on_the_live_tree():
    verdict, why = _probe()(None, repo_root=_REPO_ROOT)
    assert verdict == ca.SATISFIED, why
    assert "ПРОТИВОПОЛОЖНЫЕ ответы" in why


@pytest.mark.timeout(900)
def test_the_probe_is_green_on_an_untouched_copy(tmp_path):
    """Обратная сторона всех поломок ниже: нетронутая копия тоже зелена. Без неё красный
    вердикт мог бы происходить из самого копирования, а не из поломки."""
    verdict, why = _probe()(None, repo_root=_stand(tmp_path))
    assert verdict == ca.SATISFIED, why


# ───────────────────── порванные звенья, каждое НАЗВАНО ─────────────────────


def test_an_absent_instrument_is_the_subject_not_unmeasured(tmp_path):
    """ЗВЕНО: прибора нет вовсе. Вердикт обязан быть `not_satisfied` (предмет карточки),
    а не `unmeasured`: отсутствие прибора есть сам дефект, а не невозможность измерить."""
    stand = tmp_path / "пусто"
    stand.mkdir()
    verdict, why = _probe()(None, repo_root=str(stand))
    assert verdict == ca.NOT_SATISFIED
    assert "нет в дереве" in why


@pytest.mark.timeout(900)
def test_a_silent_restore_under_a_working_instrument_is_caught(tmp_path):
    """ГЛАВНОЕ ЗВЕНО — ровно авария цикла #906. Снимаем сам отказ: возврат снова идёт
    молча, отнимая у работающего прибора мутанта вместе с записью окна."""
    stand = _stand(tmp_path)
    _patch(stand, '    if owner["verdict"] not in OWNER_MAY_RESTORE and not allow_live_owner:',
           '    if False and owner["verdict"] not in OWNER_MAY_RESTORE:')
    verdict, why = _probe()(None, repo_root=stand)
    assert verdict == ca.NOT_SATISFIED
    assert "#906" in why and "код 0" in why


@pytest.mark.timeout(900)
def test_an_override_wired_on_by_default_is_caught(tmp_path):
    """ТО ЖЕ ЗВЕНО с другой стороны: отказ на месте, но обход включён НАВСЕГДА. Сторож,
    который всегда обойдён, неотличим от отсутствующего — и проба обязана это назвать."""
    stand = _stand(tmp_path)
    _patch(stand, "                             allow_live_owner=args.allow_live_owner)",
           "                             allow_live_owner=True)")
    verdict, why = _probe()(None, repo_root=stand)
    assert verdict == ca.NOT_SATISFIED
    assert "#906" in why


@pytest.mark.timeout(900)
def test_a_refusal_that_takes_the_window_record_with_it_is_caught(tmp_path):
    """ЗВЕНО: отказ обязан ОСТАВИТЬ запись окна. Отказ, уносящий слепок, хуже отсутствия
    отказа: байты дерева он спасёт, а вернуть мутанта станет нечем НИКОМУ."""
    stand = _stand(tmp_path)
    _patch(stand, '    if owner["verdict"] not in OWNER_MAY_RESTORE and not allow_live_owner:\n        return {',
           '    if owner["verdict"] not in OWNER_MAY_RESTORE and not allow_live_owner:\n'
           '        close_window(root)\n        return {')
    verdict, why = _probe()(None, repo_root=stand)
    assert verdict == ca.NOT_SATISFIED
    assert "снял запись окна" in why


@pytest.mark.timeout(900)
def test_a_refusal_without_a_way_up_is_caught(tmp_path):
    """ЗВЕНО: отказ обязан НАЗВАТЬ осознанный обход. Сторож без пути наверх учит обходить
    себя руками — и тогда его обходят всегда, а не осознанно."""
    stand = _stand(tmp_path)
    _patch(stand, '                       f"--allow-live-owner"),',
           '                       f"обходить нечем"),')
    verdict, why = _probe()(None, repo_root=stand)
    assert verdict == ca.NOT_SATISFIED
    assert "не называет осознанного обхода" in why


@pytest.mark.timeout(900)
def test_a_refusal_that_restores_anyway_is_caught(tmp_path):
    """ЗВЕНО: сверка БАЙТОВ. Отказ, который всё равно переписал файл, — худший из всех:
    код возврата говорит «не тронул», а мутант у работающего прибора уже отнят, и
    остальные вердикты того прогона молча стали недостоверны. Эту дыру в самом контроле
    нашёл мутационный прибор, а не глаз автора (мутация «проба перестала сверять байты»
    выжила в первом прогоне дельты ADR-791)."""
    stand = _stand(tmp_path)
    _patch(stand,
           '            "restored": [], "already_clean": [], "failed": [], "closed": False,\n'
           '            "repo_root": root, "record": doc}',
           '            "restored": [], "already_clean": [], "failed": [], "closed": False,\n'
           '            "repo_root": root, "record": doc,\n'
           '            "_damage": [_write_atomically(\n'
           '                os.path.join(root, *str(i["file"]).split("/")),\n'
           '                open(os.path.join(root, *str(i["pristine_copy"]).split("/")),\n'
           '                     encoding="utf-8").read()) for i in doc["files"]]}')
    verdict, why = _probe()(None, repo_root=stand)
    assert verdict == ca.NOT_SATISFIED
    assert "байты файла изменились" in why


@pytest.mark.timeout(900)
def test_a_refusal_that_also_blocks_a_dead_owner_is_caught(tmp_path):
    """ЗВЕНО: путь наверх для дерева, доставшегося в наследство, обязан остаться открытым.
    Запри его — и каждое наследство потребует обхода, то есть обход станет привычкой."""
    stand = _stand(tmp_path)
    _patch(stand, "OWNER_MAY_RESTORE = (OWNER_DEAD, OWNER_SELF)",
           "OWNER_MAY_RESTORE = (OWNER_SELF,)")
    verdict, why = _probe()(None, repo_root=stand)
    assert verdict == ca.NOT_SATISFIED
    assert "путь" in why and "наследство" in why


# ───── причина, НАЗВАННАЯ дверью, обязана доехать до читателя (ADR-874, цикл #992) ─────


class TestTheDoorsReasonReachesTheReader:
    """`_door_named_reason` — третий исход без причины неотличим от «нечем проверить».

    Замер 30.10, прогон 41126290008 на `ubuntu-latest`: все шесть проб этого файла дали
    `unmeasured` ВЕРНО — дверь там действительно не измеряет живость владельца окна, и
    ужесточение ADR-871 (цикл #989) это вскрыло: до него `rc_live != 0` зачитывалось за
    отказ, и проба объявляла `satisfied` на хосте, где не измерено НИЧЕГО. Но ПОЧЕМУ
    дверь не измерила — вердикт не сказал: печатались последние 200 символов её `--json`,
    то есть ХВОСТ (`"restored": [], "already_clean": [] …`), а причина лежит в ГОЛОВЕ,
    в `owner.detail`. Инв. #17 требует не только отдельного значения для «не измерено»,
    но и его ПРЕДСТАВЛЕНИЯ; представление без причины — не представление.

    Контроль в обе стороны: причина есть ⇒ доезжает; документ не разбирается ⇒ это свой
    НАЗВАННЫЙ исход, а не тихий возврат к прежнему поведению.
    """

    def test_the_named_reason_travels_and_the_tail_does_not_replace_it(self):
        out = json.dumps({
            "measured": True, "refused": True,
            "owner": {"verdict": "unmeasured", "pid": 4242,
                      "command": "/usr/bin/python3 -c нечто-чужое",
                      "hostname": "runner-xyz", "run_label": "прогон-7",
                      "detail": "номер 4242 занят живым процессом, и наш прибор в его "
                                "команде не назван"},
                      "reason": "ВЛАДЕЛЕЦ ОКНА не признан мёртвым (unmeasured)",
            "restored": [], "already_clean": [], "failed": [], "closed": False,
        }, ensure_ascii=False, indent=2)
        said = ca._door_named_reason(out)
        assert "наш прибор в его команде не назван" in said, said
        assert "unmeasured" in said and "4242" in said, said
        assert "не разобрать" not in said, said

    def test_a_null_owner_is_named_and_not_passed_off_as_a_reason(self):
        out = json.dumps({"measured": True, "refused": False, "owner": None,
                          "reason": "записи окна нет — возвращать нечего"},
                         ensure_ascii=False)
        said = ca._door_named_reason(out)
        assert "owner: null" in said or "о владельце не сказано" in said, said

    def test_an_unparsable_document_is_its_own_named_outcome(self):
        """ОБРАТНАЯ сторона: разобрать не вышло ⇒ сказать это ВСЛУХ.

        Молчаливый возврат к хвосту текста сделал бы «причину не прочитали»
        неотличимым от «причины нет» — тот же дефект на шаг короче.
        """
        said = ca._door_named_reason("дверь упала до JSON-а, вот её stderr: Traceback …")
        assert "не разобрать" in said, said
        assert "stderr" in said, said

    def test_the_probe_carries_the_reason_into_its_unmeasured_verdict(self, tmp_path):
        """ЗВЕНО целиком: дверь, отвечающая «НЕ ИЗМЕРЕНО» (2), обязана отдать пробе
        свою причину — иначе красный на чужом хосте не диагностируем ничем.

        Рвём у настоящего прибора РОВНО распознавание живого прибора в команде номера:
        это и есть та ветка, которой `ubuntu-latest` отвечает `unmeasured`.
        """
        stand = _stand(tmp_path)
        _patch(stand, '_TOOL_IN_COMMAND = re.compile(r"delta_mutation_run")',
               '_TOOL_IN_COMMAND = re.compile(r"ЭТОГО-НЕТ-НИ-В-ОДНОЙ-КОМАНДЕ")')
        verdict, why = _probe()(None, repo_root=stand)
        assert verdict == ca.UNMEASURED, (verdict, why)
        assert "НЕ ИЗМЕРЕНО" in why
        assert "наш прибор в его команде не назван" in why, (
            "вердикт `unmeasured` приехал БЕЗ причины двери — ровно дефект ADR-874: "
            f"{why}")
