"""Ось ПАМЯТИ копий карточки (`check_tracker_drift`) — ADR-715, цикл #859.

**Что это за ось и почему она не третья копия старой.** Прибор расхождения трекера
умел спрашивать «какая копия НОВЕЕ» (две оси порядка, ADR-544). Этот вопрос НЕ
защищает память, и доказательство — авария 08.10 (ADR-714): доставка ``359ce9406``
принесла копию стоячего приказа владельца, которая была новее по отметке и БЕДНЕЕ
на 56 записей цикла. «Новее» и «богаче памятью» независимы.

**Положительные контроли — настоящие байты двух аварий, а не выдумка.** Фикстуры
``spa_core/tests/fixtures/cycle_record_loss`` (их завёл цикл #858 для пробы двери)
несут заголовки записей ПОБАЙТОВО из блобов истории; тела синтетические, потому что
настоящие редакции весят 1,8 и 0,95 МиБ. Замер новой осью на этих парах:

* ``359ce9406`` (08.10) — ``records_forked``: дереву не хватает **56**, origin — **2**;
* ``af88d6bfc`` (25.09) — ``records_forked``: дереву не хватает **9**, origin — **1**.

Оба «в обе стороны», и это не придирка к имени вердикта: именно поэтому возврат
СТАРОЙ копии восстановлением не является, а восстановление идёт только объединением.

**Замер на живом трекере хоста 13.10** (ради которого ось и написана): 200 находок
расхождения, обе копии в руках у 187; тетрадей циклов **2**, у обеих копия дерева
строго беднее (приказ владельца 153 записи против 247 — не хватает 94; вторая 0
против 6), не-тетрадей **185**. Поэтому ось добавляет к выводу ДВЕ названные строки,
а не 185 — цена ошибки измерена на той же популяции, что и находка.

**Контроль в обратную сторону обязателен в каждом разделе.** Ось, объявляющая потерю
памяти на ЧЁМ УГОДНО, бесполезна ровно так же, как слепая: разница двух копий почти
всегда сессионное поле захвата, и на ней ось обязана МОЛЧАТЬ (`records_equal`).

Литеральных дат здесь нет вовсе: предмет — номера записей, стенные часы не участвуют.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS = _REPO_ROOT / "scripts"
for _p in (str(_REPO_ROOT), str(_SCRIPTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import check_tracker_drift as drift  # noqa: E402

REF = "main"
FIXTURES = _REPO_ROOT / "spa_core" / "tests" / "fixtures" / "cycle_record_loss"


def _notebook(numbers, status: str = "in-progress", claim: str | None = None,
              body: str = "работа") -> str:
    """Карточка-тетрадь: шапка + по записи цикла на каждый номер."""
    fm = ["---", "trackerStatus:", "  type: inbox", 'title: "приказ"', f"status: {status}"]
    if claim:
        fm.append(f"claimed_by: {claim}")
    fm += ["---", ""]
    for n in numbers:
        fm += [f"## ЦИКЛ #{n} (ADR-{n}): запись", "", f"{body} {n}", ""]
    return "\n".join(fm)


def _task_card(status: str = "new", claim: str | None = None) -> str:
    """Карточка-ЗАДАНИЕ: записей цикла нет ни одной. Членство решает содержимое."""
    fm = ["---", "trackerStatus:", "  type: inbox", 'title: "задание"', f"status: {status}"]
    if claim:
        fm.append(f"claimed_by: {claim}")
    fm += ["---", "", "## Что сделать", "", "тело задания", ""]
    return "\n".join(fm)


# =========================================================================================
# ПОЛОЖИТЕЛЬНЫЕ КОНТРОЛИ: настоящие байты двух аварий
# =========================================================================================

@pytest.mark.parametrize("incident,miss_tree,miss_origin", [
    ("359ce9406", 56, 2),
    ("af88d6bfc", 9, 1),
])
def test_the_real_incidents_are_named_as_memory_divergence(incident, miss_tree, miss_origin):
    """Пара байт настоящей аварии ⇒ ось называет НАПРАВЛЕНИЕ и ЧИСЛА.

    Источник пары назван вслух: зелёный на фикстуре не читается как зелёный на
    истории git (та в CI недостижима — клон на глубину 1).
    """
    before = FIXTURES / f"order_{incident}_before.md"
    after = FIXTURES / f"order_{incident}_after.md"
    if not (before.exists() and after.exists()):
        pytest.fail(f"фикстур аварии {incident} нет ({FIXTURES}) — предпосылка НЕ ОБЕСПЕЧЕНА; "
                    f"это «не измерено», а не «прошло»")
    mem = drift.record_memory(after.read_text(encoding="utf-8"),
                              before.read_text(encoding="utf-8"), REF)
    assert mem.verdict == drift.MEMORY_FORKED, (
        f"авария {incident} была потерей в ОБЕ стороны (доставка и унесла, и добавила) — "
        f"получено {mem.verdict}: {mem.detail}")
    assert (mem.missing_tree, mem.missing_origin) == (miss_tree, miss_origin)
    assert "ОБЪЕДИНЕНИЕМ" in mem.detail, (
        "вердикт «в обе стороны» обязан сказать, что возврат старой копии не починка")


def test_the_incident_is_invisible_to_the_order_axes_alone():
    """Старые оси на той же паре НЕ говорят о памяти ничего — ось не дублирует их.

    Этот тест обязан остаться зелёным: он фиксирует, что прежний прибор о потере
    записей молчал. Покраснеет — значит оси порядка изменили, и ось памяти меряет
    уже не тот разрыв.
    """
    before = (FIXTURES / "order_359ce9406_before.md").read_text(encoding="utf-8")
    after = (FIXTURES / "order_359ce9406_after.md").read_text(encoding="utf-8")
    verdict, why = drift.combined_order(after, before, "in-progress", "in-progress")
    assert "запис" not in why, (
        f"ось порядка не вправе говорить о записях цикла — она о них ничего не знает: {why}")
    assert verdict in (drift.ORDER_TREE_NEWER, drift.ORDER_ORIGIN_NEWER,
                       drift.ORDER_UNMEASURED)


# =========================================================================================
# НАПРАВЛЕНИЕ: четыре исхода, и каждый отличим от остальных
# =========================================================================================

def test_tree_poorer_names_the_missing_numbers_and_the_direction():
    mem = drift.record_memory(_notebook([1, 2]), _notebook([1, 2, 3, 4]), REF)
    assert mem.verdict == drift.MEMORY_TREE_POORER
    assert (mem.missing_tree, mem.missing_origin) == (2, 0)
    assert "#3" in mem.detail and "#4" in mem.detail, "пропавшие номера обязаны быть названы"
    assert "БЕДНЕЕ" in mem.detail


def test_origin_poorer_is_the_other_direction_and_not_the_same_verdict():
    mem = drift.record_memory(_notebook([1, 2, 3]), _notebook([1]), REF)
    assert mem.verdict == drift.MEMORY_ORIGIN_POORER, (
        "недоставленная запись дерева и амнезия дерева — РАЗНЫЕ аварии; один вердикт на "
        "двоих стёр бы направление, ради которого ось и написана")
    assert (mem.missing_tree, mem.missing_origin) == (0, 2)
    assert "не доставлена" in mem.detail


def test_forked_when_each_copy_misses_the_others_records():
    mem = drift.record_memory(_notebook([1, 9]), _notebook([1, 2, 3]), REF)
    assert mem.verdict == drift.MEMORY_FORKED
    assert (mem.missing_tree, mem.missing_origin) == (2, 1)


def test_equal_record_sets_are_not_a_memory_finding():
    """КОНТРОЛЬ В ОБРАТНУЮ СТОРОНУ: разница только в поле захвата ⇒ ось молчит."""
    mem = drift.record_memory(_notebook([1, 2], claim="cycle-1"),
                              _notebook([1, 2], claim="cycle-2"), REF)
    assert mem.verdict == drift.MEMORY_EQUAL
    assert mem.verdict not in drift.MEMORY_FINDINGS
    assert (mem.missing_tree, mem.missing_origin) == (0, 0)


def test_body_rewritten_is_not_a_memory_finding():
    """Тело записи переписано, номера целы ⇒ это НЕ потеря памяти.

    Граница названа вслух и в ADR-714: потерю ТЕЛА записи не ловит ничто, и
    притворяться, что ловит эта ось, запрещено — иначе каждая штатная переписка
    карточки станет находкой (мера общей тетради дала бы 538 отказов из 2133).
    """
    mem = drift.record_memory(_notebook([1, 2], body="переписано"),
                              _notebook([1, 2], body="как было"), REF)
    assert mem.verdict == drift.MEMORY_EQUAL


def test_a_copy_stripped_to_zero_records_is_still_a_notebook():
    """Копия дерева потеряла ВСЕ записи ⇒ `tree_poorer`, а НЕ «карточка-задание».

    Это живой случай, а не домысел: вторая из двух тетрадей, найденных 13.10 на
    трекере хоста, — `inbox-ozhivit-fidy-vne-ethereum-put-k-snyatiyu`, 0 записей в
    дереве против 6 на origin. Мера, опознающая тетрадь по «есть записи у ОБЕИХ
    копий», объявила бы её не тетрадью — то есть полная амнезия копии стала бы
    самым тихим из исходов (замер: мутант `not ours or not theirs` пережил батарею
    до появления этого теста).
    """
    mem = drift.record_memory(_task_card(), _notebook([1, 2, 3]), REF)
    assert mem.verdict == drift.MEMORY_TREE_POORER, mem.detail
    assert mem.missing_tree == 3


def test_an_origin_copy_with_no_records_is_still_a_notebook():
    """Зеркальная сторона того же: записи есть только у дерева ⇒ не доставлены."""
    mem = drift.record_memory(_notebook([7]), _task_card(), REF)
    assert mem.verdict == drift.MEMORY_ORIGIN_POORER, mem.detail
    assert mem.missing_origin == 1


def test_task_card_is_not_a_notebook():
    """Членство решает СОДЕРЖИМОЕ: у карточки-задания ось не спрашивают."""
    mem = drift.record_memory(_task_card(claim="a"), _task_card(claim="b"), REF)
    assert mem.verdict == drift.MEMORY_NOT_A_NOTEBOOK
    assert mem.verdict not in drift.MEMORY_FINDINGS


def test_duplicate_numbers_are_compared_as_a_multiset():
    """Два блока с одним номером: пропажа ОДНОГО из двух — тоже пропажа.

    Мера взята у двери именно за это: множество здесь ответило бы «совпало».
    """
    mem = drift.record_memory(_notebook([1, 2]), _notebook([1, 2, 2]), REF)
    assert mem.verdict == drift.MEMORY_TREE_POORER
    assert mem.missing_tree == 1


# =========================================================================================
# ТРЕТИЙ ИСХОД: «не измерено» никогда не выдаётся за «совпало»
# =========================================================================================

def test_unread_origin_copy_is_unmeasured_not_equal():
    mem = drift.record_memory(_notebook([1, 2]), None, REF)
    assert mem.verdict == drift.MEMORY_UNMEASURED
    assert "не прочитано" in mem.detail and "не «совпало»" in mem.detail


def test_unread_tree_copy_is_unmeasured_too():
    mem = drift.record_memory(None, _notebook([1, 2]), REF)
    assert mem.verdict == drift.MEMORY_UNMEASURED
    assert "дерева" in mem.detail


def test_door_without_the_measure_is_unmeasured_not_clean(monkeypatch):
    """У двери нет меры записей цикла ⇒ «НЕ ИЗМЕРЕНО», а не «записи совпали».

    Это тот самый fail-OPEN, за который проект платит с #29: сторож, лишившийся
    прибора, обязан кричать, а не зеленеть (урок `pyflakes`, цикл #465).
    """
    import push_to_github as door
    monkeypatch.delattr(door, "CYCLE_RECORD_RE", raising=True)
    mem = drift.record_memory(_notebook([1]), _notebook([1, 2]), REF)
    assert mem.verdict == drift.MEMORY_UNMEASURED
    assert "меры записей цикла" in mem.detail


def test_door_not_importable_is_unmeasured(monkeypatch):
    """Дверь не ввезлась (нет файла, сорванный импорт) ⇒ третий исход с причиной."""
    monkeypatch.setitem(sys.modules, "push_to_github", None)   # import → ImportError
    mem = drift.record_memory(_notebook([1]), _notebook([1, 2]), REF)
    assert mem.verdict == drift.MEMORY_UNMEASURED
    assert "не ввезена" in mem.detail


# =========================================================================================
# МЕРА ОДНА: прибор и дверь обязаны понимать запись цикла ОДИНАКОВО
# =========================================================================================

def test_the_measure_is_taken_from_the_delivery_door_not_copied():
    """Объекты меры — ТЕ ЖЕ, которыми отказывает дверь (тождество, а не похожесть)."""
    import push_to_github as door
    pattern, headers = drift.door_record_measure()
    assert pattern is door.CYCLE_RECORD_RE
    assert headers is door.entry_headers


def test_verdict_follows_the_door_when_the_doors_measure_changes(monkeypatch):
    """Подменили меру У ДВЕРИ — вердикт прибора пошёл за ней.

    Это контроль против ВТОРОЙ КОПИИ правила: своя копия регулярного выражения
    осталась бы глуха к подмене, и прибор начал бы называть расхождение, которого
    дверь не видит (так трижды платили, #143–#145).
    """
    import re

    import push_to_github as door
    monkeypatch.setattr(door, "CYCLE_RECORD_RE", re.compile(
        "^#{2,4}[ \t]*ЗАПИСЬ[ \t]*#(?P<id>\\d+)".encode("utf-8"), re.M))
    ours = "## ЗАПИСЬ #1\nа\n"
    theirs = "## ЗАПИСЬ #1\nа\n## ЗАПИСЬ #2\nб\n"
    mem = drift.record_memory(ours, theirs, REF)
    assert mem.verdict == drift.MEMORY_TREE_POORER, (
        "прибор обязан опознавать записи ровно так, как дверь — иначе две меры одного "
        "правила разъедутся молча")
    # И обратная сторона: по МЕРЕ ДВЕРИ прежняя форма записью больше не является.
    assert drift.record_memory(_notebook([1]), _notebook([1, 2]),
                               REF).verdict == drift.MEMORY_NOT_A_NOTEBOOK


# =========================================================================================
# ПРОВОДКА: вердикт обязан доехать до находки, до текста отчёта и до `--json`
# =========================================================================================

def _run(cwd, *args):
    res = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)
    assert res.returncode == 0, f"git {' '.join(args)} -> {res.returncode}: {res.stderr}"
    return res.stdout


@pytest.fixture()
def repo(tmp_path):
    root = tmp_path / "repo"
    (root / drift.TRACKER_REL).mkdir(parents=True)
    # `-b` обязателен: без него имя ветки берёт хост (`init.defaultBranch`), и сцена
    # зелена на Маке и красна на ubuntu-latest (`.claude/rules/deployment.md`).
    _run(root.parent, "init", "-q", "-b", REF, str(root))
    _run(root, "config", "user.email", "t@example.com")
    _run(root, "config", "user.name", "test")
    return root


def _scene(repo, origin_text: str, tree_text: str, name: str = "inbox-prikaz.md"):
    tracker = repo / drift.TRACKER_REL
    (tracker / name).write_text(origin_text, encoding="utf-8")
    _run(repo, "add", "-A")
    _run(repo, "commit", "-q", "-m", "origin: тетрадь")
    (tracker / name).write_text(tree_text, encoding="utf-8")
    return tracker


def test_wiring_the_memory_verdict_reaches_the_finding(repo):
    """Контур целиком: амнезия копии дерева ⇒ находка несёт направление и числа."""
    tracker = _scene(repo, _notebook([1, 2, 3], claim="cycle-1"),
                     _notebook([1], claim="cycle-2"))
    report = drift.analyze(tracker, REF)
    assert len(report.findings) == 1, [f.kind for f in report.findings]
    f = report.findings[0]
    assert f.memory == drift.MEMORY_TREE_POORER, f.memory_detail
    assert f.memory_missing_tree == 2 and f.memory_missing_origin == 0
    assert report.memory_tally() == {drift.MEMORY_TREE_POORER: 1}
    assert [x.card_id for x in report.memory_findings] == ["inbox-prikaz"]


def test_wiring_a_pure_claim_difference_produces_no_memory_finding(repo):
    """КОНТРОЛЬ В ОБРАТНУЮ СТОРОНУ на целом контуре: находка есть, память цела."""
    tracker = _scene(repo, _notebook([1, 2], claim="cycle-1"),
                     _notebook([1, 2], claim="cycle-2"))
    report = drift.analyze(tracker, REF)
    assert report.findings, "расхождение копий само по себе остаётся находкой"
    assert report.memory_findings == []
    assert report.memory_tally() == {drift.MEMORY_EQUAL: 1}


def test_wiring_the_stale_class_is_asked_about_memory_too(repo):
    """Вторая из двух найденных 13.10 тетрадей — класс `stale`, а не `diverged`.

    Класс говорит «дерево отстаёт» и МОЛЧИТ о том, сколько записей не хватает
    читателю прод-дерева. Спрашивать ось только у `diverged` значило бы пропустить
    половину живого населения.
    """
    tracker = repo / drift.TRACKER_REL
    card = tracker / "inbox-prikaz.md"
    behind = _notebook([1, 2, 3])
    card.write_text(behind, encoding="utf-8")
    _run(repo, "add", "-A")
    _run(repo, "commit", "-q", "-m", "origin: три записи")
    card.write_text(_notebook([1, 2, 3, 4]), encoding="utf-8")
    _run(repo, "add", "-A")
    _run(repo, "commit", "-q", "-m", "origin: дописана четвёртая")
    # копия дерева — ПРЕЖНЯЯ версия этого же пути (её blob есть в истории ref) ⇒ `stale`
    card.write_text(behind, encoding="utf-8")

    report = drift.analyze(tracker, REF)
    stale = [f for f in report.findings if f.kind == drift.KIND_STALE]
    assert stale, [f.kind for f in report.findings]
    assert stale[0].memory == drift.MEMORY_TREE_POORER, stale[0].memory_detail
    assert stale[0].memory_missing_tree == 1
    assert "#4" in stale[0].memory_detail


def test_wiring_the_report_text_names_the_notebook_in_its_own_section(repo):
    """Находка про память обязана быть ВИДНА: своя строка и свой раздел.

    На живом входе 13.10 таких позиций ДВЕ на двести, и в общем списке `РАЗОШЛИСЬ`
    из 185 карточек их не видно (урок #243 — сторожа глохнут шумом).
    """
    tracker = _scene(repo, _notebook([1, 2, 3]), _notebook([1]))
    text = drift.format_report(drift.analyze(tracker, REF))
    assert "🧠 ПАМЯТЬ копий" in text
    assert text.count("inbox-prikaz") >= 2, "карточка названа и в классе, и в разделе памяти"
    assert "#2" in text and "#3" in text
    assert "РАЗНЫЕ вопросы" in text, "строка про «новее ≠ богаче» обязана остаться у читателя"


def test_wiring_the_section_distinguishes_intact_memory_from_nothing_measured(repo):
    """«Память цела» и «мерить было нечем» — разные строки, а не одна тишина."""
    tracker = _scene(repo, _notebook([1, 2], claim="a"), _notebook([1, 2], claim="b"))
    text = drift.format_report(drift.analyze(tracker, REF))
    assert "🧠 ПАМЯТЬ копий" in text
    assert "память копий не разошлась" in text
    assert drift.MEMORY_EQUAL in text


def test_wiring_the_memory_verdict_survives_the_json_report(repo):
    """Вердикт обязан дойти до ПОТРЕБИТЕЛЯ, а не только до объекта отчёта."""
    tracker = _scene(repo, _notebook([1, 2, 3]), _notebook([1]))
    res = subprocess.run(
        [sys.executable, str(_SCRIPTS / "check_tracker_drift.py"),
         "--tracker-dir", str(tracker), "--ref", REF, "--json"],
        capture_output=True, text=True, cwd=str(repo))
    assert res.returncode == 1, f"находка ⇒ код 1; получено {res.returncode}: {res.stderr[-400:]}"
    payload = json.loads(res.stdout)
    assert payload["memory_tally"] == {drift.MEMORY_TREE_POORER: 1}
    row = payload["findings"][0]
    assert row["memory"] == drift.MEMORY_TREE_POORER
    assert row["memory_missing_tree"] == 2


def test_wiring_classes_without_a_second_copy_are_not_asked(repo):
    """У `hidden`/`undelivered` второй копии нет вовсе ⇒ ось пуста, а не «не измерено».

    Пустая строка здесь значит «класс об этом не спрашивают»; выдать ему
    `records_unmeasured` значило бы кормить читателя находкой из ничего.
    """
    tracker = repo / drift.TRACKER_REL
    (tracker / "inbox-na-origin.md").write_text(_notebook([1]), encoding="utf-8")
    _run(repo, "add", "-A")
    _run(repo, "commit", "-q", "-m", "origin")
    (tracker / "inbox-na-origin.md").unlink()
    (tracker / "inbox-tolko-v-dereve.md").write_text(_notebook([5]), encoding="utf-8")

    report = drift.analyze(tracker, REF)
    kinds = {f.kind: f for f in report.findings}
    assert drift.KIND_HIDDEN in kinds and drift.KIND_UNDELIVERED in kinds
    assert kinds[drift.KIND_HIDDEN].memory == ""
    assert kinds[drift.KIND_UNDELIVERED].memory == ""
    assert report.memory_tally() == {}
