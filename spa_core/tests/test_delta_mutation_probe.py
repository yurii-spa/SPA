"""Контроль пробы `delta_mutation_instrument_is_re_measurable` (ADR-726, цикл #870).

Проба объявляет, что ВВЕЗЁННЫЙ прибор мутационного замера работает. Проверить это
можно только одним способом: порвать у прибора по одному звену и убедиться, что проба
КРАСНЕЕТ с НАЗВАННЫМ звеном. Проба, никогда не видевшая настоящей поломки, — украшение
(`.claude/rules/deployment.md` § «Проверка сторожа сторожей»).

Рвём не выдуманный заменитель, а НАСТОЯЩИЙ текст прибора — на одноразовой копии дерева,
по одному якорю за раз. Якорь проверяется на единственность ДО подмены: подмена, не
нашедшая якоря, оставила бы прибор исправным, проба позеленела бы, и это читалось бы как
«звено защищено» (ровно класс `mutation_application_census`, ADR-558).
"""
from __future__ import annotations

import os
import shutil
import sys

import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _REPO_ROOT)

from spa_core.monitoring import card_acceptance as ca  # noqa: E402

_PROBE_NAME = "delta_mutation_instrument_is_re_measurable"
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


@pytest.mark.timeout(600)
def test_the_probe_is_green_on_the_live_tree():
    verdict, why = _probe()(None)
    assert verdict == ca.SATISFIED, why
    assert "три РАЗНЫХ ответа" in why


@pytest.mark.timeout(600)
def test_the_probe_is_green_on_an_untouched_copy(tmp_path):
    """Обратная сторона всех поломок ниже: нетронутая копия тоже зелена. Без неё
    красный вердикт мог бы происходить из самого копирования, а не из поломки."""
    verdict, why = _probe()(None, repo_root=_stand(tmp_path))
    assert verdict == ca.SATISFIED, why


# ───────────────────── порванные звенья, каждое НАЗВАНО ─────────────────────


def test_an_absent_instrument_is_the_subject_of_the_card_not_unmeasured(tmp_path):
    """ЗВЕНО: прибора нет. Это ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ на чистой вершине origin/main —
    и вердикт обязан быть `not_satisfied` (предмет карточки), а не `unmeasured`:
    отсутствие прибора есть сам дефект, а не невозможность его измерить."""
    stand = tmp_path / "пусто"
    stand.mkdir()
    verdict, why = _probe()(None, repo_root=str(stand))
    assert verdict == ca.NOT_SATISFIED
    assert "нет в дереве" in why and "не перемерит никто" in why


@pytest.mark.timeout(600)
def test_a_survivor_indistinguishable_from_a_clean_run_is_caught(tmp_path):
    """ЗВЕНО: находка обязана отличаться от чистого замера. Прибор, всегда выходящий
    нулём, печатал бы «выжило 1» и возвращал бы успех — вердикт, на который никто не
    посмотрит."""
    stand = _stand(tmp_path)
    _patch(stand, "        if self.by_outcome(SURVIVED):\n            return RC_MEASURED_SURVIVORS",
           "        if False:\n            return RC_MEASURED_SURVIVORS")
    verdict, why = _probe()(None, repo_root=stand)
    assert verdict == ca.NOT_SATISFIED
    assert "ТОТ ЖЕ код" in why


@pytest.mark.timeout(600)
def test_a_third_outcome_that_does_not_reach_the_return_code_is_caught(tmp_path):
    """ГЛАВНОЕ ЗВЕНО (инв. #17). Ровно этот дефект был у ВСЕХ 25 одноразовых приборов:
    «не применена» печаталась, а код возврата от неё не зависел."""
    stand = _stand(tmp_path)
    _patch(stand,
           "        if self.by_outcome(NOT_APPLIED) or self.by_outcome(BROKE_COLLECTION):\n"
           "            return RC_PARTIALLY_UNMEASURED",
           "        if False:\n            return RC_PARTIALLY_UNMEASURED")
    verdict, why = _probe()(None, repo_root=stand)
    assert verdict == ca.NOT_SATISFIED
    assert "«не измерено» выдаётся за «убито»" in why


@pytest.mark.timeout(600)
def test_a_mutant_left_in_the_tree_is_caught(tmp_path):
    """ЗВЕНО: инертность. Прибор, не возвращающий файл, оставляет мутант в дереве — это
    уже случалось (`inbox-ubityi-progon-perepisi-ostavlyaet-mutant`)."""
    stand = _stand(tmp_path)
    _patch(stand, "            finally:\n                _write_atomically(real, source)",
           "            finally:\n                pass  # возврат снят")
    verdict, why = _probe()(None, repo_root=stand)
    assert verdict == ca.NOT_SATISFIED
    assert "НЕ восстановлено" in why


@pytest.mark.timeout(600)
def test_an_outcome_vanishing_from_the_verdict_is_caught(tmp_path):
    """ЗВЕНО: перечень исходов ЗАКРЫТ. Исход, выпавший из вердикта, читался бы как
    «ничего не нашли» — сумма обязана равняться населению."""
    stand = _stand(tmp_path)
    _patch(stand, '"counts": {o: len(self.by_outcome(o)) for o in OUTCOMES},',
           '"counts": {o: 0 for o in OUTCOMES},')
    verdict, why = _probe()(None, repo_root=stand)
    assert verdict == ca.NOT_SATISFIED
    assert "не ЗАКРЫТ" in why


@pytest.mark.timeout(600)
def test_a_dishonest_denominator_is_caught(tmp_path):
    """ЗВЕНО: знаменатель. Включить не применённые в «применено» значило бы напечатать
    «убито 1 из 1» там, где не измерено НИЧЕГО."""
    stand = _stand(tmp_path)
    _patch(stand,
           "        return len(self.by_outcome(KILLED)) + len(self.by_outcome(SURVIVED))",
           "        return len(self.results)")
    verdict, why = _probe()(None, repo_root=stand)
    assert verdict == ca.NOT_SATISFIED
    assert "знаменатель" in why


@pytest.mark.timeout(600)
def test_a_tool_without_a_machine_verdict_is_unmeasured_not_satisfied(tmp_path):
    """ЗВЕНО: третий исход У ПРОБЫ. Прибор не отдал машинного вердикта ⇒ `unmeasured`
    с названной причиной, и никогда `satisfied`."""
    stand = _stand(tmp_path)
    _patch(stand, '    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2) if args.json\n          else render(report))',
           '    print("вердикта не будет")')
    verdict, why = _probe()(None, repo_root=stand)
    assert verdict == ca.UNMEASURED
    assert "не отдал машинного вердикта" in why


@pytest.mark.timeout(600)
def test_a_tool_that_cannot_kill_a_visible_mutant_is_caught(tmp_path):
    """ЗВЕНО: убийство. Прибор, не замечающий НОВОГО упавшего имени, объявил бы дыру
    покрытия там, где батарея работает, — и каждый цикл получал бы ложные находки."""
    stand = _stand(tmp_path)
    _patch(stand, "            if fresh:", "            if False:")
    verdict, why = _probe()(None, repo_root=stand)
    assert verdict == ca.NOT_SATISFIED
    # Не убив видимого мутанта, прибор объявляет его выжившим ⇒ ломается первая же
    # сцена: «измеренной и чистой» она быть перестаёт.
    assert "не объявлена измеренной и чистой" in why


# ───────────────────── критерий объявлен НА КАРТОЧКЕ ─────────────────────


def test_the_criterion_is_declared_on_the_card_before_the_work():
    """`.claude/rules/acceptance.md` п. 1: критерий машинный и объявлен ДО работы.

    Проверяется САМА карточка этого цикла, а не обычай: проба, не объявленная ни на
    одной карточке, меряет в воздух."""
    card = os.path.join(_REPO_ROOT, "nimbalyst-local", "tracker",
                        "inbox-pribor-mutatsionnogo-zamera-vybrasyvaets.md")
    assert os.path.exists(card), "карточки предмета нет в дереве цикла"
    head = open(card, encoding="utf-8").read().split("---")[1]
    assert f"acceptance_probe: {_PROBE_NAME}" in head, head
